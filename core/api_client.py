import json
from typing import Any, Generator, Iterable, Optional

import requests

from core.config import get_api_key, get_base_url
from core.models import ChatResult, ChatUsage, Message, ModelInfo


class KiloError(RuntimeError):
    def __init__(self, message: str, status_code: int = 0, code: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


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
    if status == 401:
        return "Invalid or missing API key. Check KILO_API_KEY / OPENCODE_API_KEY."
    if status == 402:
        return "Insufficient balance. Add credits at https://opencode.ai/auth."
    if status == 403:
        return "Model blocked by organization policy. Try a free model like muse-spark-1.3-contributor-free."
    if status == 429:
        return "Rate limited. Wait a moment and retry."
    if status in (502, 503):
        return "Upstream provider error. Retry or pick another model."
    return ""


def _request_json(method: str, url: str, headers: dict, payload: Optional[dict] = None, timeout: int = 60) -> Any:
    try:
        resp = requests.request(method, url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise KiloError(f"Network error reaching Kilo gateway: {exc}") from exc
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
            raise KiloError(f"Network error reaching Kilo gateway: {exc}") from exc
    if resp.status_code >= 400:
        try:
            data = resp.json()
        except Exception:
            data = {"error": resp.text[:500]}
        msg = _gateway_error_message(resp.status_code, data)
        hint = _friendly_hint(resp.status_code)
        full = f"[{resp.status_code}] {msg}" + (f" ({hint})" if hint else "")
        code = data.get("error", {}).get("code") if isinstance(data, dict) else None
        raise KiloError(full, status_code=resp.status_code, code=code)
    try:
        return resp.json()
    except Exception as exc:
        raise KiloError(f"Invalid JSON response from gateway: {exc}") from exc


def list_models(base_url: str = "", timeout: int = 30) -> list[ModelInfo]:
    base = (base_url or get_base_url()).rstrip("/")
    data = _request_json("GET", f"{base}/models", headers={"User-Agent": "zumba/1.0"}, timeout=timeout)
    items = data.get("data", []) if isinstance(data, dict) else []
    models = [ModelInfo.from_dict(m) for m in items if isinstance(m, dict) and m.get("id")]
    models.sort(key=lambda m: (not m.is_free, m.id))
    return models


def list_free_models(base_url: str = "", timeout: int = 30) -> list[ModelInfo]:
    return [m for m in list_models(base_url=base_url, timeout=timeout) if m.is_free]


def list_providers(base_url: str = "", timeout: int = 30) -> Any:
    base = (base_url or get_base_url()).rstrip("/")
    return _request_json("GET", f"{base}/providers", headers={"User-Agent": "zumba/1.0"}, timeout=timeout)


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
        "messages": [m.to_dict() for m in messages],
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


def _needs_responses_api(model: str) -> bool:
    m = (model or "").lower()
    if "muse-spark" in m or m.startswith("gpt-") or "codex" in m:
        return True
    if m.startswith("claude-") or m.startswith("gemini-") or m.startswith("grok"):
        return True
    if m.startswith("qwen"):
        return True
    return False


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
        u = data.get("usage") or {}
        usage = ChatUsage(
            prompt_tokens=int(u.get("input_tokens", 0) or 0),
            completion_tokens=int(u.get("output_tokens", 0) or 0),
            total_tokens=int(u.get("total_tokens", 0) or 0),
        )
    except Exception:
        pass
    raw = {"choices": [{"message": {"content": text, "tool_calls": calls}}], "responses_raw": data} if calls else data
    return ChatResult(content=text, model=str(data.get("model", model)), usage=usage, raw=raw)


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
    if _needs_responses_api(model):
        return _responses_completion(messages, model, api_key=api_key, base_url=base_url, max_tokens=max_tokens, temperature=temperature, timeout=timeout, tools=tools)
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
        if exc.status_code in (400, 404, 500) and not tools:
            return _responses_completion(messages, model, api_key=key, base_url=base, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
        raise
    try:
        choice = data["choices"][0]
        content = choice["message"].get("content") or ""
    except Exception as exc:
        if not tools:
            try:
                return _responses_completion(messages, model, api_key=key, base_url=base, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
            except Exception:
                pass
        raise KiloError(f"Unexpected chat response shape: {str(data)[:500]}") from exc
    usage = ChatUsage.from_dict(data.get("usage"))
    return ChatResult(content=str(content), model=str(data.get("model", model)), usage=usage, raw=data)


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
    if _needs_responses_api(model):
        result = _responses_completion(messages, model, api_key=key, base_url=base, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
        yield result.content
        return result
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
        raise KiloError(f"Network error reaching Kilo gateway: {exc}") from exc
    if resp.status_code >= 400:
        try:
            data = resp.json()
        except Exception:
            try:
                data = {"error": resp.text[:500]}
            except Exception:
                data = {"error": f"HTTP {resp.status_code}"}
        if resp.status_code in (400, 404, 500):
            try:
                resp.close()
            except Exception:
                pass
            result = _responses_completion(messages, model, api_key=key, base_url=base, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
            yield result.content
            return result
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
                choices = obj.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                text = delta.get("content")
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
