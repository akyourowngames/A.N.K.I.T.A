from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from extension_system import ExtensionCatalog, load_extension_catalog
from jarvis_nim import JarvisConfig, NimChatError, chat_once, env_int, load_dotenv
from latency_trace import LatencyTrace, latency_debug_enabled, trace_mark, use_latency_trace
from local_router import ROUTE_DIRECT_CHAT, route_chat_turn
from main import build_messages, configure_console_output, vector_memory_system_message
from memory_system import MemoryConfig, remember_chat
from tools import discover_tools
from tools.registry import set_active_registry


class WebAssistantError(Exception):
    pass


@dataclass(frozen=True)
class WebAssistantConfig:
    session_dir: Path
    max_session_messages: int

    @classmethod
    def from_env(cls, workspace: Path) -> "WebAssistantConfig":
        raw_session_dir = os.environ.get("JARVIS_WEB_SESSION_DIR", "").strip() or "media/web/sessions"
        session_dir = Path(raw_session_dir)
        if not session_dir.is_absolute():
            session_dir = workspace / session_dir
        return cls(
            session_dir=session_dir,
            max_session_messages=env_int("JARVIS_WEB_MAX_SESSION_MESSAGES", 80),
        )


@dataclass
class WebSession:
    session_id: str
    messages: list[dict[str, str]]
    created_at: str
    last_active: str


class QueueWriter:
    def __init__(self, emit: Any) -> None:
        self.emit = emit

    def write(self, text: str) -> int:
        if text:
            self.emit(text)
        return len(text)

    def flush(self) -> None:
        return None


class WebAssistantRuntime:
    def __init__(
        self,
        web_config: WebAssistantConfig,
        jarvis_config: JarvisConfig,
        registry: Any,
        memory_config: MemoryConfig,
        extension_catalog: ExtensionCatalog,
    ) -> None:
        self.web_config = web_config
        self.jarvis_config = jarvis_config
        self.registry = registry
        self.memory_config = memory_config
        self.extension_catalog = extension_catalog
        self.chat_lock = asyncio.Lock()

    @classmethod
    def from_env(cls, workspace: Path | None = None) -> "WebAssistantRuntime":
        configure_console_output()
        root = workspace or Path.cwd()
        load_dotenv(root / ".env")
        extension_catalog = load_extension_catalog()
        registry = discover_tools(extension_catalog=extension_catalog)
        set_active_registry(registry)
        return cls(
            web_config=WebAssistantConfig.from_env(root),
            jarvis_config=JarvisConfig.from_env(),
            registry=registry,
            memory_config=MemoryConfig.from_env(root),
            extension_catalog=extension_catalog,
        )

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "assistant": self.jarvis_config.assistant_name,
            "model": self.jarvis_config.model,
            "streaming": self.jarvis_config.stream,
            "tools": len(self.registry.visible_tools()),
        }

    def run_chat_turn(self, user_text: str, session_id: str = "") -> dict[str, str]:
        clean_text = user_text.strip()
        if not clean_text:
            raise WebAssistantError("Message is empty.")
        session = self.load_session(session_id, clean_text)
        trace_mark("session_loaded")
        memory_config = self.memory_config
        turn_messages = [*session.messages]
        direct_chat = route_chat_turn(clean_text, turn_messages, self.registry).mode == ROUTE_DIRECT_CHAT
        if count_role(session.messages, "user") > 0 and not (
            direct_chat and env_bool("JARVIS_DIRECT_CHAT_SKIP_VECTOR_MEMORY", True)
        ):
            vector_message = vector_memory_system_message(clean_text, memory_config, self.jarvis_config)
            if vector_message is not None:
                turn_messages.append(vector_message)
        turn_messages.append({"role": "user", "content": clean_text})
        reply = chat_once(self.jarvis_config, turn_messages, self.registry)
        session.messages.append({"role": "user", "content": clean_text})
        session.messages.append({"role": "assistant", "content": reply})
        session.last_active = now_text()
        session.messages = prune_session_messages(session.messages, self.web_config.max_session_messages)
        self.save_session(session)
        remember_chat(memory_config, self.jarvis_config, clean_text, reply)
        return {"session_id": session.session_id, "reply": reply}

    async def stream_chat(self, user_text: str, session_id: str = "") -> AsyncIterator[dict[str, str]]:
        async with self.chat_lock:
            queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            loop = asyncio.get_running_loop()
            debug_latency = latency_debug_enabled()

            def push(event: dict[str, str]) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, event)

            def emit_token(text: str) -> None:
                push({"type": "token", "content": text})

            def emit_latency(event: dict[str, Any]) -> None:
                if not debug_latency:
                    return
                stage = str(event.get("stage", ""))
                if stage == "local_router_started":
                    push({"type": "status", "stage": "checking_tools"})
                if stage == "tool_execution_started":
                    push({"type": "status", "stage": "running_tool"})
                if stage == "final_model_started":
                    push({"type": "status", "stage": "finalizing"})
                push({"type": "latency", **event})

            def worker() -> None:
                trace = LatencyTrace(enabled=True, sink=emit_latency if debug_latency else None)
                try:
                    trace.mark("request_received")
                    with use_latency_trace(trace):
                        with contextlib.redirect_stdout(QueueWriter(emit_token)):
                            result = self.run_chat_turn(user_text, session_id)
                    if debug_latency:
                        push({"type": "latency_summary", "trace": trace.finish()})
                    push({"type": "done", **result})
                except (NimChatError, WebAssistantError) as error:
                    push({"type": "error", "message": str(error)})
                except Exception as error:
                    push({"type": "error", "message": f"Assistant request failed: {error}"})

            thread = threading.Thread(target=worker, name="jarvis-web-chat", daemon=True)
            thread.start()
            while True:
                event = await queue.get()
                yield event
                if event["type"] in {"done", "error"}:
                    break
            thread.join(timeout=0.1)

    def load_session(self, session_id: str, user_text: str) -> WebSession:
        clean_id = clean_session_id(session_id)
        path = self.session_path(clean_id)
        fresh_messages = build_messages(
            self.jarvis_config,
            self.registry,
            self.memory_config,
            self.extension_catalog,
            user_text,
        )
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                data = {}
            session = session_from_data(data, clean_id)
            session.messages = refreshed_session_messages(fresh_messages, session.messages)
            return session
        now = now_text()
        return WebSession(session_id=clean_id, messages=fresh_messages, created_at=now, last_active=now)

    def save_session(self, session: WebSession) -> None:
        self.web_config.session_dir.mkdir(parents=True, exist_ok=True)
        path = self.session_path(session.session_id)
        data = {
            "session_id": session.session_id,
            "messages": session.messages,
            "created_at": session.created_at,
            "last_active": session.last_active,
        }
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def session_path(self, session_id: str) -> Path:
        return self.web_config.session_dir / f"{clean_session_id(session_id)}.json"


def clean_session_id(value: str) -> str:
    text = value.strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if not text:
        return uuid.uuid4().hex
    for character in text:
        if character not in allowed:
            return uuid.uuid4().hex
    return text


def session_from_data(data: Any, fallback_id: str) -> WebSession:
    if not isinstance(data, dict):
        data = {}
    messages = data.get("messages", [])
    if not isinstance(messages, list):
        messages = []
    clean_messages: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if isinstance(role, str) and isinstance(content, str):
            clean_messages.append({"role": role, "content": content})
    session_id = data.get("session_id")
    created_at = data.get("created_at")
    last_active = data.get("last_active")
    return WebSession(
        session_id=clean_session_id(session_id) if isinstance(session_id, str) else fallback_id,
        messages=clean_messages,
        created_at=created_at if isinstance(created_at, str) else now_text(),
        last_active=last_active if isinstance(last_active, str) else now_text(),
    )


def refreshed_session_messages(fresh_messages: list[dict[str, str]], saved_messages: list[dict[str, str]]) -> list[dict[str, str]]:
    retained = [message for message in saved_messages if message.get("role") != "system"]
    return [*fresh_messages, *retained]


def prune_session_messages(messages: list[dict[str, str]], max_messages: int) -> list[dict[str, str]]:
    system_messages = [message for message in messages if message.get("role") == "system"]
    turn_messages = [message for message in messages if message.get("role") != "system"]
    limit = max(2, max_messages)
    return [*system_messages, *turn_messages[-limit:]]


def count_role(messages: list[dict[str, str]], role: str) -> int:
    return sum(1 for message in messages if message.get("role") == role)


def now_text() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def env_bool(name: str, fallback: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return fallback
    return value in {"1", "true", "yes", "on"}
