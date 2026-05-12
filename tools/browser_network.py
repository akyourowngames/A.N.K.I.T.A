from __future__ import annotations

import time
from weakref import WeakSet
from typing import Any


_CAPTURES: dict[str, list[dict[str, Any]]] = {}
_CAPTURE_SETTINGS: dict[str, dict[str, Any]] = {}
_PENDING_COUNTS: dict[str, int] = {}
_ATTACHED_PAGES: WeakSet[Any] = WeakSet()
_MOCKS: dict[str, list[dict[str, Any]]] = {}


def attach_network_listeners(page: Any, session_id: str, config: dict[str, Any]) -> None:
    if page in _ATTACHED_PAGES:
        return
    _ATTACHED_PAGES.add(page)
    _CAPTURES.setdefault(session_id, [])
    _PENDING_COUNTS.setdefault(session_id, 0)
    ensure_capture_settings(session_id, config)

    def on_request(request: Any) -> None:
        _PENDING_COUNTS[session_id] = _PENDING_COUNTS.get(session_id, 0) + 1
        if should_capture(session_id, request.url):
            append_capture(session_id, config, request_entry(request))

    def on_request_done(request: Any) -> None:
        _PENDING_COUNTS[session_id] = max(0, _PENDING_COUNTS.get(session_id, 0) - 1)

    def on_response(response: Any) -> None:
        if not should_capture(session_id, response.url):
            return
        append_capture(session_id, config, response_entry(response, session_id, config))

    page.on("request", on_request)
    page.on("requestfinished", on_request_done)
    page.on("requestfailed", on_request_done)
    page.on("response", on_response)


def ensure_capture_settings(session_id: str, config: dict[str, Any]) -> dict[str, Any]:
    if session_id in _CAPTURE_SETTINGS:
        return _CAPTURE_SETTINGS[session_id]
    network_config = config.get("network_interception")
    if not isinstance(network_config, dict):
        network_config = {}
    settings = {
        "enabled": bool(network_config.get("enabled", True)),
        "patterns": text_list(network_config.get("capture_patterns")),
        "capture_bodies": False,
    }
    _CAPTURE_SETTINGS[session_id] = settings
    return settings


def start_capture(session_id: str, config: dict[str, Any], patterns: list[str] | None = None, capture_bodies: bool = False) -> dict[str, Any]:
    network_config = config.get("network_interception")
    if not isinstance(network_config, dict):
        network_config = {}
    chosen_patterns = patterns if patterns is not None else text_list(network_config.get("capture_patterns"))
    _CAPTURE_SETTINGS[session_id] = {
        "enabled": True,
        "patterns": [item for item in chosen_patterns if item.strip()],
        "capture_bodies": capture_bodies,
    }
    _CAPTURES.setdefault(session_id, [])
    return {"summary": "Network interception started.", "session_id": session_id, "patterns": _CAPTURE_SETTINGS[session_id]["patterns"], "capture_bodies": capture_bodies}


def stop_capture(session_id: str, include_bodies: bool = True) -> dict[str, Any]:
    settings = _CAPTURE_SETTINGS.get(session_id, {})
    settings["enabled"] = False
    _CAPTURE_SETTINGS[session_id] = settings
    return {"summary": "Network interception stopped.", "session_id": session_id, "captured": network_log(session_id, 200, include_bodies)["entries"]}


def network_log(session_id: str, limit: int, include_bodies: bool) -> dict[str, Any]:
    entries = list(_CAPTURES.get(session_id, []))[-bounded_int(limit, 50, 1, 500):]
    if not include_bodies:
        entries = [without_body(entry) for entry in entries]
    return {"session_id": session_id, "entries": entries, "pending_requests": _PENDING_COUNTS.get(session_id, 0)}


def network_idle(session_id: str) -> bool:
    return _PENDING_COUNTS.get(session_id, 0) == 0


def recent_request_summaries(session_id: str, limit: int = 20) -> list[dict[str, Any]]:
    entries = list(_CAPTURES.get(session_id, []))[-bounded_int(limit, 20, 1, 100):]
    return [without_body(entry) for entry in entries]


def should_capture(session_id: str, url: str) -> bool:
    settings = _CAPTURE_SETTINGS.get(session_id)
    if not settings or not settings.get("enabled", True):
        return False
    patterns = settings.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        return True
    return any(pattern_matches(url, pattern) for pattern in patterns if isinstance(pattern, str))


def pattern_matches(value: str, pattern: str) -> bool:
    target = value.casefold()
    text = pattern.strip().casefold()
    if not text:
        return True
    if "*" not in text:
        return text in target
    position = 0
    for part in [item for item in text.split("*") if item]:
        found = target.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    return True


def append_capture(session_id: str, config: dict[str, Any], entry: dict[str, Any]) -> None:
    entries = _CAPTURES.setdefault(session_id, [])
    entries.append(entry)
    network_config = config.get("network_interception")
    max_entries = 50
    if isinstance(network_config, dict):
        max_entries = bounded_int(network_config.get("max_captured_responses"), 50, 1, 1000)
    _CAPTURES[session_id] = entries[-max_entries:]


def request_entry(request: Any) -> dict[str, Any]:
    return {
        "kind": "request",
        "timestamp": time.time(),
        "method": request.method,
        "url": request.url,
        "resource_type": request.resource_type,
    }


def response_entry(response: Any, session_id: str, config: dict[str, Any]) -> dict[str, Any]:
    headers = response.headers
    entry: dict[str, Any] = {
        "kind": "response",
        "timestamp": time.time(),
        "status": response.status,
        "url": response.url,
        "content_type": headers.get("content-type", ""),
    }
    settings = _CAPTURE_SETTINGS.get(session_id, {})
    if settings.get("capture_bodies", False):
        body = safe_response_text(response)
        network_config = config.get("network_interception")
        max_chars = 10000
        if isinstance(network_config, dict):
            max_chars = bounded_int(network_config.get("max_response_body_chars"), 10000, 0, 500000)
        entry["body"] = body[:max_chars]
        entry["body_truncated"] = len(body) > max_chars
    return entry


def safe_response_text(response: Any) -> str:
    try:
        return response.text()
    except Exception:
        return ""


def without_body(entry: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(entry)
    if "body" in cleaned:
        cleaned["body_chars"] = len(str(cleaned.pop("body")))
    return cleaned


def install_mock(page: Any, session_id: str, url_pattern: str, status: int, content_type: str, body: str) -> dict[str, Any]:
    mock = {
        "url_pattern": url_pattern,
        "status": bounded_int(status, 200, 100, 599),
        "content_type": content_type or "application/json",
        "body": body,
    }
    mocks = _MOCKS.setdefault(session_id, [])
    mocks.append(mock)

    def handle(route: Any) -> None:
        request_url = route.request.url
        for item in _MOCKS.get(session_id, []):
            if pattern_matches(request_url, str(item.get("url_pattern", ""))):
                route.fulfill(
                    status=int(item.get("status", 200)),
                    content_type=str(item.get("content_type", "application/json")),
                    body=str(item.get("body", "")),
                )
                return
        route.continue_()

    page.route("**/*", handle)
    return {"summary": "Network mock installed.", "url_pattern": url_pattern, "status": mock["status"], "content_type": mock["content_type"]}


def text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))
