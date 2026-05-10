from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .path_resolver import resolve_local_path
from .registry import ToolInputError, optional_text, require_text


@dataclass(frozen=True)
class TelegramToolContext:
    active: bool
    chat_id: str
    session_path: str
    session_metadata: dict[str, Any]
    memory_mode: str
    webhook_mode: bool
    rate_limit: dict[str, Any]
    session_count: int
    active_file_path: str
    outbox_dir: Path
    download_dir: Path
    auto_send_file_result_paths: tuple[str, ...] = ()


_LOCAL = threading.local()


def set_telegram_context(context: TelegramToolContext) -> None:
    _LOCAL.context = context


def clear_telegram_context() -> None:
    if hasattr(_LOCAL, "context"):
        delattr(_LOCAL, "context")


def current_telegram_context() -> TelegramToolContext | None:
    context = getattr(_LOCAL, "context", None)
    if isinstance(context, TelegramToolContext):
        return context
    return None


def telegram_status(params: dict[str, Any]) -> dict[str, Any]:
    context = current_telegram_context()
    if context is None or not context.active:
        return {
            "active": False,
            "summary": "Telegram tools are registered, but this chat is not running inside telegram_bot.py.",
        }
    return {
        "active": True,
        "chat_id": context.chat_id,
        "session_count": context.session_count,
        "memory_mode": context.memory_mode,
        "mode": "webhook" if context.webhook_mode else "polling",
        "rate_limit": context.rate_limit,
        "download_dir": str(context.download_dir),
        "summary": f"Telegram bot active for chat {context.chat_id} in {context.memory_mode} memory mode.",
    }


def telegram_session_info(params: dict[str, Any]) -> dict[str, Any]:
    context = current_telegram_context()
    if context is None or not context.active:
        return {
            "active": False,
            "summary": "No active Telegram session is attached to this tool call.",
        }
    return {
        "active": True,
        "chat_id": context.chat_id,
        "session_path": context.session_path,
        "metadata": context.session_metadata,
        "memory_mode": context.memory_mode,
        "active_file": bool(context.active_file_path),
        "active_file_path": context.active_file_path,
    }


def telegram_send_file(params: dict[str, Any]) -> dict[str, Any]:
    context = current_telegram_context()
    if context is None or not context.active:
        raise ToolInputError("telegram_send_file is available only inside an active telegram_bot.py chat turn")

    path = resolve_send_file_path(require_text(params, "file_path"))
    if not path.is_file():
        raise ToolInputError(f"file_path is not a file: {path}")
    caption = optional_text(params, "caption", "")
    outbox_path = queue_file_for_telegram(context, path.resolve(), caption)
    return {
        "queued": True,
        "file_path": str(path.resolve()),
        "file_name": path.name,
        "caption": caption,
        "outbox_path": str(outbox_path),
        "summary": f"Queued {path.name} for Telegram delivery.",
    }


def queue_file_for_telegram(context: TelegramToolContext, path: Path, caption: str) -> Path:
    chat_outbox = context.outbox_dir / context.chat_id
    chat_outbox.mkdir(parents=True, exist_ok=True)
    entry_id = datetime.now().astimezone().strftime("%Y%m%d%H%M%S%f") + "-" + uuid.uuid4().hex
    payload = {
        "id": entry_id,
        "chat_id": context.chat_id,
        "file_path": str(path),
        "file_name": path.name,
        "caption": caption,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    outbox_path = chat_outbox / f"{entry_id}.json"
    outbox_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return outbox_path


def drain_telegram_outbox(chat_id: str, outbox_dir: Path) -> list[dict[str, Any]]:
    chat_outbox = outbox_dir / str(chat_id)
    if not chat_outbox.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(chat_outbox.glob("*.json"), key=lambda item: item.name):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            entries.append(data)
        try:
            path.unlink()
        except OSError:
            pass
    return entries


def auto_queue_file_outputs(tool_payload_text: str) -> list[Path]:
    context = current_telegram_context()
    if context is None or not context.active:
        return []
    try:
        payload = json.loads(tool_payload_text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict) or not payload.get("ok"):
        return []
    result = payload.get("result")
    queued: list[Path] = []
    for path in existing_file_paths_from_value(result, context.auto_send_file_result_paths):
        if path in queued:
            continue
        queue_file_for_telegram(context, path, f"Prepared file: {path.name}")
        queued.append(path)
    return queued


def existing_file_paths_from_value(value: Any, result_paths: tuple[str, ...] = ()) -> list[Path]:
    found: list[Path] = []
    for text in configured_path_values(value, result_paths):
        path = resolve_existing_file(text)
        if path is not None and path not in found:
            found.append(path)
    return found


def configured_path_values(value: Any, result_paths: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for result_path in result_paths:
        for item in values_at_result_path(value, result_path):
            if isinstance(item, str) and item.strip() and item not in values:
                values.append(item)
    return values


def values_at_result_path(value: Any, result_path: str) -> list[Any]:
    parts = [part.strip() for part in result_path.split(".") if part.strip()]
    if not parts:
        return []
    return values_at_parts(value, parts)


def values_at_parts(value: Any, parts: list[str]) -> list[Any]:
    if not parts:
        return [value]
    if not isinstance(value, dict):
        return []
    part = parts[0]
    list_mode = part.endswith("[]")
    key = part[:-2] if list_mode else part
    if not key:
        return []
    item = value.get(key)
    if list_mode:
        if not isinstance(item, list):
            return []
        values: list[Any] = []
        for child in item:
            values.extend(values_at_parts(child, parts[1:]))
        return values
    return values_at_parts(item, parts[1:])


def resolve_existing_file(text: str) -> Path | None:
    if not text.strip():
        return None
    try:
        path = resolve_send_file_path(text)
    except Exception:
        return None
    if path.is_file():
        return path.resolve()
    return None


def resolve_send_file_path(value: str) -> Path:
    return resolve_local_path(clean_file_reference(value))


def clean_file_reference(value: str) -> str:
    text = value.strip()
    changed = True
    while changed and len(text) >= 2:
        changed = False
        if text[0] in {"'", '"', "`"} and text[-1] == text[0]:
            text = text[1:-1].strip()
            changed = True
    for prefix in ("file:///", "file://", "file:"):
        if text.casefold().startswith(prefix):
            text = text[len(prefix) :].strip()
            if prefix == "file:///" and len(text) >= 2 and text[1] == "|":
                text = text[0] + ":" + text[2:]
            break
    return text
