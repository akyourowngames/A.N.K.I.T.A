import json
from typing import Any, Generator, Iterable, Optional

import requests

from config import get_api_key, get_base_url
from models import ChatResult, ChatUsage, Message, ModelInfo


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
        return "Invalid or missing API key. Check KILO_API_KEY."
    if status == 402:
        return "Insufficient balance. Add credits at https://kilo.ai."
    if status == 403:
        return "Model blocked by organization policy. Try a free model like kilo-auto/free."
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
    try:
        choice = data["choices"][0]
        content = choice["message"].get("content") or ""
    except Exception as exc:
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
