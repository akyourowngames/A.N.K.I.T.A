import json
from typing import Any, Generator, Iterable, Optional

import requests

from core.config import get_api_key, get_base_url
from core.models import ChatResult, ChatUsage, Message, ModelInfo


class GatewayError(RuntimeError):
    """Provider gateway error (OpenAI-compatible endpoint, default NVIDIA NIM)."""

    def __init__(self, message: str, status_code: int = 0, code: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


# Backward-compat alias: the Kilo gateway was the previous default provider.
KiloError = GatewayError


def _gateway_error_message(status: int, payload: Any) -> str:
    if isinstance(payload, dict):
        err = payload.get("error", payload)
        if isinstance(err, dict):
            msg = err.get("message", "")
            if msg:
                return str(msg)
        elif isinstance(err, str) and err:
            return err
        try:
            return json.dumps(payload)[:500]
        except Exception:
            return str(payload)[:500]
    return f"HTTP {status}"


def _friendly_hint(status: int) -> str:
    if status == 400:
        return "Bad request. Drop unsupported fields (logprobs, logit_bias, messages[].name) and keep N=1."
    if status == 401:
        return "Invalid or missing API key. Check ZUMBA_API_KEY (get one at https://build.nvidia.com)."
    if status == 402:
        return "Payment required. Check billing/limits for your provider."
    if status == 403:
        return "Model decommissioned or blocked. Try the default model (`zumba models --refresh`)."
    if status == 404:
        return "Endpoint or model not found. Check ZUMBA_BASE_URL and the model id (`zumba models --refresh`)."
    if status == 429:
        return "Rate limited (TPM/RPM). Wait a moment and retry."
    if status == 413:
        return "Payload too large for the context window. Shorten history or raise ZUMBA_CONTEXT_LIMIT carefully."
    if status in (502, 503):
        return "Upstream provider error. Retry or pick another model."
    return ""


def _request_json(method: str, url: str, headers: dict, payload: Optional[dict] = None, timeout: int = 60) -> Any:
    try:
        resp = requests.request(method, url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise KiloError(f"Network error reaching LLM API: {exc}") from exc
    if resp.status_code in (429, 502, 503):
        try:
            retry_after = int(resp.headers.get("Retry-After", "") or 0)
        except Exception:
            retry_after = 0
        wait = retry_after or (8 if resp.status_code == 429 else 5)
        try:
            import time as _time

            _time.sleep(max(1, min(20, wait)))
        except Exception:
            pass
        try:
            resp = requests.request(method, url, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise KiloError(f"Network error reaching LLM API: {exc}") from exc
    if resp.status_code >= 400:
        try:
            data = resp.json()
        except Exception:
            data = {"error": resp.text[:500]}
        msg = _gateway_error_message(resp.status_code, data)
        hint = _friendly_hint(resp.status_code)
        full = f"[{resp.status_code}] {msg}" + (f" ({hint})" if hint else "")
        raise KiloError(full, status_code=resp.status_code, code=_error_code(data))
    try:
        return resp.json()
    except Exception as exc:
        raise KiloError(f"Invalid JSON response from LLM API: {exc}") from exc


def list_models(base_url: str = "", timeout: int = 30, api_key: str = "") -> list[ModelInfo]:
    base = (base_url or get_base_url()).rstrip("/")
    headers = {"User-Agent": "zumba/1.0"}
    key = (api_key or "").strip() or _optional_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = _request_json("GET", f"{base}/models", headers=headers, timeout=timeout)
    items = data.get("data", []) if isinstance(data, dict) else []
    models = [ModelInfo.from_dict(m) for m in items if isinstance(m, dict) and m.get("id")]
    models.sort(key=lambda m: m.id)
    return models


def list_free_models(base_url: str = "", timeout: int = 30, api_key: str = "") -> list[ModelInfo]:
    return [m for m in list_models(base_url=base_url, timeout=timeout, api_key=api_key) if m.is_free]


def list_providers(base_url: str = "", timeout: int = 30) -> Any:
    base = (base_url or get_base_url()).rstrip("/")
    # Most OpenAI-compatible gateways (Groq, NVIDIA NIM) expose no
    # /providers endpoint; keep the command working by returning an
    # empty provider list instead of surfacing a 404.
    try:
        return _request_json("GET", f"{base}/providers", headers={"User-Agent": "zumba/1.0"}, timeout=timeout)
    except KiloError as exc:
        if exc.status_code in (400, 401, 403, 404, 405):
            return {"data": []}
        raise


def _optional_api_key() -> str:
    try:
        return get_api_key(require=False)
    except Exception:
        return ""


def _sanitize_temperature(temperature: Optional[float]) -> Optional[float]:
    # Some gateways reject temperature=0; send a tiny positive value
    # directly so deterministic memory/JSON prompts stay valid.
    if temperature is None:
        return None
    try:
        value = float(temperature)
    except Exception:
        return temperature
    if value <= 0:
        return 1e-8
    if value > 2:
        return 2.0
    return value


def _chat_payload(
    messages: Iterable[Message],
    model: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    stream: bool = False,
    tools: Optional[list] = None,
) -> dict:
    payload: dict = {
        "model": model,
        # Some providers reject messages[].name — strip it while keeping
        # tool ids/names in their dedicated fields (tool_call_id / tool_calls).
        "messages": [{k: v for k, v in m.to_dict().items() if k != "name"} for m in messages],
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    temperature = _sanitize_temperature(temperature)
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


def _error_code(payload: Any) -> Any:
    try:
        if not isinstance(payload, dict):
            return None
        err = payload.get("error", None)
        if isinstance(err, dict):
            return err.get("code")
        return None
    except Exception:
        return None


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                t = b.get("text", "")
                if isinstance(t, str) and t:
                    parts.append(t)
                elif isinstance(t, dict) and isinstance(t.get("text"), str):
                    parts.append(str(t.get("text")))
                elif isinstance(b.get("content"), str):
                    parts.append(str(b.get("content")))
        return "".join(parts)
    return str(content)


def _extract_chat_content(data: Any) -> tuple[str, list, str]:
    model_name = ""
    try:
        if isinstance(data, dict) and data.get("model"):
            model_name = str(data.get("model"))
    except Exception:
        pass
    try:
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if not isinstance(choices, list) or not choices:
            return "", [], model_name
        choice = choices[0] if isinstance(choices[0], dict) else {}
        msg = choice.get("message", {}) if isinstance(choice, dict) else {}
        if isinstance(msg, str):
            return msg, [], model_name
        if not isinstance(msg, dict):
            return "", [], model_name
        text = _content_to_text(msg.get("content"))
        calls = msg.get("tool_calls") or []
        if not isinstance(calls, list):
            calls = []
        return str(text or ""), calls, model_name
    except Exception:
        return "", [], model_name


def _chat_tools_to_responses(tools: Optional[list]) -> Optional[list]:
    out = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        fn = t.get("function", t) if isinstance(t.get("function", None), dict) else t
        name = str(fn.get("name", "") or t.get("name", ""))
        if not name:
            continue
        desc = str(fn.get("description", "") or "")[:1000]
        params = fn.get("parameters", {}) or {}
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}}
        params = dict(params)
        params.setdefault("type", "object")
        out.append({"type": "function", "name": name, "description": desc, "parameters": params})
    return out or None


def _messages_to_responses_input(messages: Iterable[Message]) -> list:
    items: list = []
    for m in messages:
        role = (m.role or "user").strip().lower()
        content = (m.content or "")
        if role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": getattr(m, "tool_call_id", "") or "",
                "output": content[:6000] if content else "(empty tool result)",
            })
            continue
        if role == "assistant" and getattr(m, "tool_calls", None):
            if content and content.strip():
                items.append({"role": "assistant", "content": content.strip()[:6000]})
            for call in m.tool_calls or []:
                try:
                    fn = (call.get("function", {}) or {}) if isinstance(call, dict) else {}
                    args = fn.get("arguments", "{}")
                    if isinstance(args, dict):
                        args = json.dumps(args, ensure_ascii=False)
                    items.append({
                        "type": "function_call",
                        "call_id": str(call.get("id", "") or ""),
                        "name": str(fn.get("name", "") or ""),
                        "arguments": str(args or "{}"),
                    })
                except Exception:
                    continue
            continue
        if not content.strip():
            continue
        if role == "system":
            items.append({"role": "system", "content": content.strip()[:6000]})
        elif role == "assistant":
            items.append({"role": "assistant", "content": content.strip()[:6000]})
        else:
            items.append({"role": "user", "content": content.strip()[:6000]})
    return items or [{"role": "user", "content": "hi"}]


def _responses_completion(
    messages: list[Message],
    model: str,
    api_key: str = "",
    base_url: str = "",
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    timeout: int = 120,
    tools: Optional[list] = None,
) -> ChatResult:
    key = api_key or get_api_key(require=True)
    base = (base_url or get_base_url()).rstrip("/")
    payload: dict = {"model": model, "input": _messages_to_responses_input(messages)}
    if max_tokens is not None:
        payload["max_output_tokens"] = max_tokens
    rtools = _chat_tools_to_responses(tools) if tools else None
    if rtools:
        payload["tools"] = rtools
    data = _request_json(
        "POST",
        f"{base}/responses",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "zumba/1.0",
        },
        payload=payload,
        timeout=timeout,
    )
    text = ""
    calls: list = []
    try:
        if not isinstance(data, dict):
            raise ValueError("unexpected responses payload type")
        for item in data.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for block in item.get("content", []) or []:
                    if isinstance(block, dict) and block.get("type") == "output_text":
                        text += str(block.get("text", ""))
            elif item.get("type") == "function_call":
                args = item.get("arguments", "{}")
                if not isinstance(args, str):
                    try:
                        args = json.dumps(args, ensure_ascii=False)
                    except Exception:
                        args = "{}"
                calls.append({
                    "id": str(item.get("call_id", "") or item.get("id", "") or ""),
                    "type": "function",
                    "function": {"name": str(item.get("name", "") or ""), "arguments": args or "{}"},
                })
    except Exception:
        pass
    usage = ChatUsage()
    try:
        u = data.get("usage") if isinstance(data, dict) else None
        if isinstance(u, dict):
            def _n(*keys: str) -> int:
                for k in keys:
                    try:
                        v = int(u.get(k, 0) or 0)
                        if v:
                            return v
                    except Exception:
                        continue
                return 0
            usage = ChatUsage(
                prompt_tokens=_n("input_tokens", "prompt_tokens"),
                completion_tokens=_n("output_tokens", "completion_tokens"),
                total_tokens=_n("total_tokens"),
            )
    except Exception:
        pass
    raw = {"choices": [{"message": {"content": text, "tool_calls": calls}}], "responses_raw": data} if calls else data
    return ChatResult(content=text, model=str(data.get("model", model) if isinstance(data, dict) else model), usage=usage, raw=raw)


def chat_completion(
    messages: list[Message],
    model: str,
    api_key: str = "",
    base_url: str = "",
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    timeout: int = 120,
    tools: Optional[list] = None,
) -> ChatResult:
    key = api_key or get_api_key(require=True)
    base = (base_url or get_base_url()).rstrip("/")
    payload = _chat_payload(messages, model, max_tokens, temperature, stream=False, tools=tools)
    try:
        data = _request_json(
            "POST",
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "zumba/1.0",
            },
            payload=payload,
            timeout=timeout,
        )
    except KiloError as exc:
        # Surface the real 4xx (usually a bad model id or unsupported
        # param) with its hint instead; only try the /responses API on
        # gateways known to implement it.
        if exc.status_code in (404, 422, 500) and not tools and "groq.com" not in base.lower():
            return _responses_completion(messages, model, api_key=key, base_url=base, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
        raise
    try:
        content, _calls, _rmodel = _extract_chat_content(data)
        if not content and not _calls:
            raise ValueError("empty chat content")
    except Exception as exc:
        if not tools:
            try:
                return _responses_completion(messages, model, api_key=key, base_url=base, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
            except Exception:
                pass
        raise KiloError(f"Unexpected chat response shape: {str(data)[:500]}") from exc
    usage = ChatUsage.from_dict(data.get("usage") if isinstance(data, dict) else None)
    return ChatResult(content=str(content), model=str(_rmodel or (data.get("model", model) if isinstance(data, dict) else model)), usage=usage, raw=data)


def stream_agent_completion(
    messages: list[Message], model: str, api_key: str = "", base_url: str = "",
    max_tokens: Optional[int] = None, temperature: Optional[float] = None,
    timeout: int = 120, tools: Optional[list] = None, on_token=None, control=None,
) -> ChatResult:
    """Stream text immediately and assemble fragmented tool calls before execution."""
    if control:
        control.check()
    key = api_key or get_api_key(require=True)
    base = (base_url or get_base_url()).rstrip("/")
    try:
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "Accept": "text/event-stream", "User-Agent": "zumba/1.0"},
            json=_chat_payload(messages, model, max_tokens, temperature, stream=True, tools=tools),
            stream=True, timeout=(10, timeout),
        )
    except requests.RequestException as exc:
        raise KiloError(f"Network error reaching LLM API: {exc}") from exc
    content, calls, usage, response_model = [], {}, ChatUsage(), model
    finished = False
    try:
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except Exception:
                payload = {"error": resp.text[:500]}
            msg = _gateway_error_message(resp.status_code, payload)
            hint = _friendly_hint(resp.status_code)
            full = f"[{resp.status_code}] {msg}" + (f" ({hint})" if hint else "")
            raise KiloError(full, status_code=resp.status_code)
        for raw in resp.iter_lines(chunk_size=1, decode_unicode=False):
            if control:
                control.check()
            line = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                finished = True
                break
            if not data:
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise KiloError("LLM stream returned malformed streaming JSON") from exc
            if event.get("error"):
                raise KiloError(_gateway_error_message(0, event))
            response_model = event.get("model") or response_model
            if event.get("usage"):
                usage = ChatUsage.from_dict(event["usage"])
            choices = event.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            if choice.get("finish_reason"):
                finished = True
            delta = choice.get("delta") or choice.get("message") or {}
            text = _content_to_text(delta.get("content"))
            if text:
                content.append(text)
                if on_token:
                    on_token(text)
            for fragment in delta.get("tool_calls") or []:
                index = fragment.get("index", 0)
                call = calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if fragment.get("id"):
                    call["id"] += fragment["id"]
                function = fragment.get("function") or {}
                for field in ("name", "arguments"):
                    call["function"][field] += function.get(field) or ""
            if choice.get("finish_reason") in ("length", "content_filter") and calls:
                raise KiloError("Incomplete tool call; no tool was executed")
    finally:
        resp.close()
    text = "".join(content)
    if control:
        control.check()
    if not finished:
        raise KiloError("LLM stream ended before completion; no tool was executed")
    if not text and not calls:
        raise KiloError("LLM stream ended without content or tool calls")
    raw = {"choices": [{"message": {"content": text, "tool_calls": [calls[k] for k in sorted(calls)]}}]}
    return ChatResult(content=text, model=response_model, usage=usage, raw=raw)


def stream_chat_completion(
    messages: list[Message],
    model: str,
    api_key: str = "",
    base_url: str = "",
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    timeout: int = 120,
) -> Generator[str, None, ChatResult]:
    key = api_key or get_api_key(require=True)
    base = (base_url or get_base_url()).rstrip("/")
    payload = _chat_payload(messages, model, max_tokens, temperature, stream=True)
    try:
        resp = requests.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "zumba/1.0",
            },
            json=payload,
            stream=True,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise KiloError(f"Network error reaching LLM API: {exc}") from exc
    if resp.status_code >= 400:
        try:
            data = resp.json()
        except Exception:
            try:
                data = {"error": resp.text[:500]}
            except Exception:
                data = {"error": f"HTTP {resp.status_code}"}
        msg = _gateway_error_message(resp.status_code, data)
        hint = _friendly_hint(resp.status_code)
        full = f"[{resp.status_code}] {msg}" + (f" ({hint})" if hint else "")
        raise KiloError(full, status_code=resp.status_code)
    full_text = ""
    resp_model = model
    usage = ChatUsage()
    try:
        # Decode explicitly as UTF-8. requests' decode_unicode would otherwise
        # guess the encoding of the SSE stream (often ISO-8859-1), mangling
        # multibyte characters (smart quotes, dashes) into mojibake like "â".
        resp.encoding = "utf-8"
        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace").strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                obj = json.loads(chunk)
            except Exception:
                continue
            if isinstance(obj, dict) and obj.get("model"):
                resp_model = str(obj.get("model"))
            if isinstance(obj, dict) and obj.get("usage"):
                usage = ChatUsage.from_dict(obj.get("usage"))
            try:
                if not isinstance(obj, dict):
                    continue
                choices = obj.get("choices", [])
                if not choices or not isinstance(choices, list):
                    continue
                first = choices[0] if isinstance(choices[0], dict) else {}
                delta = first.get("delta", {}) if isinstance(first, dict) else {}
                if isinstance(delta, str):
                    text = delta
                elif isinstance(delta, dict):
                    text = _content_to_text(delta.get("content"))
                else:
                    text = ""
                if text:
                    full_text += str(text)
                    yield str(text)
            except Exception:
                continue
    finally:
        try:
            resp.close()
        except Exception:
            pass
    return ChatResult(content=full_text, model=resp_model, usage=usage, raw=None)
