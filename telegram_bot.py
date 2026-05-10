from __future__ import annotations

import argparse
import asyncio
import html
import importlib
import json
import os
import subprocess
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from extension_system import ExtensionCatalog, load_extension_catalog
from jarvis_nim import JarvisConfig, NimChatError, chat_once, load_dotenv
from main import build_messages, configure_console_output, vector_memory_system_message
from memory_system import MemoryConfig, load_memory_context, remember_chat
from tools import discover_tools
from tools.telegram_bot_tools import (
    TelegramToolContext,
    auto_queue_file_outputs,
    clear_telegram_context,
    drain_telegram_outbox,
    resolve_send_file_path,
    set_telegram_context,
)
from voice_system import VoiceConfig, VoiceError, transcribe_nvidia_audio_at_rate


DEFAULT_CONFIG_PATH = Path("config/telegram_bot.json")
DEFAULT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"


class TelegramBotError(Exception):
    pass


@dataclass(frozen=True)
class TelegramConfig:
    agent_name: str
    bot_token_env: str
    allowed_chat_ids: tuple[int, ...]
    memory_mode: str
    per_user_memory_root: Path
    session_dir: Path
    upload_dir: Path
    download_dir: Path
    max_session_messages: int
    max_message_length: int
    parse_mode: str
    typing_indicator: bool
    rate_limit_per_minute: int
    voice_transcription: bool
    send_files_inline: bool
    webhook_mode: bool
    webhook_url: str
    webhook_port: int
    rejection_message: str
    slow_down_message: str
    ffmpeg_command: str
    auto_send_file_result_paths: tuple[str, ...]
    config_path: Path

    @classmethod
    def from_env(cls, workspace: Path) -> "TelegramConfig":
        config_path = Path(os.environ.get("JARVIS_TELEGRAM_CONFIG", "").strip() or DEFAULT_CONFIG_PATH)
        if not config_path.is_absolute():
            config_path = workspace / config_path
        data = read_json_object(config_path)
        memory_mode = text_value(data, "memory_mode", "shared").casefold()
        if memory_mode not in {"shared", "per_user"}:
            raise TelegramBotError("telegram memory_mode must be shared or per_user")

        allowed_chat_ids = allowed_chats_from_config(data.get("allowed_chat_ids"))
        env_allowed = os.environ.get("TELEGRAM_ALLOWED_CHATS", "").strip()
        if env_allowed:
            allowed_chat_ids = parse_chat_ids(env_allowed)

        webhook_url = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip() or text_value(data, "webhook_url", "")
        return cls(
            agent_name=text_value(data, "agent_name", "Jarvis Telegram Bot"),
            bot_token_env=text_value(data, "bot_token_env", DEFAULT_TOKEN_ENV),
            allowed_chat_ids=tuple(allowed_chat_ids),
            memory_mode=memory_mode,
            per_user_memory_root=config_path_value(data, "per_user_memory_root", "media/telegram/memory", workspace),
            session_dir=config_path_value(data, "session_dir", "media/telegram/sessions", workspace),
            upload_dir=config_path_value(data, "upload_dir", "media/telegram/uploads", workspace),
            download_dir=config_path_value(data, "download_dir", "media/telegram/downloads", workspace),
            max_session_messages=bounded_int(data.get("max_session_messages"), 80, 2, 2000),
            max_message_length=bounded_int(data.get("max_message_length"), 4000, 500, 4096),
            parse_mode=text_value(data, "parse_mode", "MarkdownV2"),
            typing_indicator=bool_value(data, "typing_indicator", True),
            rate_limit_per_minute=bounded_int(data.get("rate_limit_per_minute"), 20, 0, 600),
            voice_transcription=bool_value(data, "voice_transcription", True),
            send_files_inline=bool_value(data, "send_files_inline", True),
            webhook_mode=bool_value(data, "webhook_mode", False),
            webhook_url=webhook_url,
            webhook_port=bounded_int(data.get("webhook_port"), 8443, 1, 65535),
            rejection_message=text_value(data, "rejection_message", "This Jarvis Telegram bot is private."),
            slow_down_message=text_value(data, "slow_down_message", "Slow down a bit and try again."),
            ffmpeg_command=text_value(data, "ffmpeg_command", "ffmpeg"),
            auto_send_file_result_paths=text_list_value(data, "auto_send_file_result_paths"),
            config_path=config_path,
        )

    def bot_token(self) -> str:
        return os.environ.get(self.bot_token_env, "").strip()

    def is_allowed(self, chat_id: int) -> bool:
        return not self.allowed_chat_ids or chat_id in self.allowed_chat_ids

    def ensure_dirs(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        if self.memory_mode == "per_user":
            self.per_user_memory_root.mkdir(parents=True, exist_ok=True)


@dataclass
class TelegramSession:
    chat_id: int
    user_name: str
    messages: list[dict[str, str]]
    memory_dir: str
    created_at: str
    last_active: str
    active_file_path: str = ""


@dataclass(frozen=True)
class IncomingTurn:
    user_text: str
    active_file_path: str = ""
    direct_reply: str = ""


class TelegramSessionStore:
    def __init__(
        self,
        telegram_config: TelegramConfig,
        jarvis_config: JarvisConfig,
        registry: Any,
        base_memory_config: MemoryConfig,
        extension_catalog: ExtensionCatalog,
    ) -> None:
        self.telegram_config = telegram_config
        self.jarvis_config = jarvis_config
        self.registry = registry
        self.base_memory_config = base_memory_config
        self.extension_catalog = extension_catalog

    def load(self, chat_id: int, user_name: str, initial_user_text: str = "") -> TelegramSession:
        path = self.path_for_chat(chat_id)
        memory_config = memory_config_for_chat(self.base_memory_config, self.telegram_config, chat_id)
        if path.exists():
            session = session_from_json(path.read_text(encoding="utf-8-sig"), chat_id, user_name, memory_config.root)
            if not session.messages:
                session.messages = build_messages(
                    self.jarvis_config,
                    self.registry,
                    memory_config,
                    self.extension_catalog,
                    initial_user_text,
                )
            return session

        now = now_text()
        messages = build_messages(
            self.jarvis_config,
            self.registry,
            memory_config,
            self.extension_catalog,
            initial_user_text,
        )
        return TelegramSession(
            chat_id=chat_id,
            user_name=user_name,
            messages=messages,
            memory_dir=str(memory_config.root),
            created_at=now,
            last_active=now,
        )

    def save(self, session: TelegramSession) -> None:
        self.telegram_config.session_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for_chat(session.chat_id)
        data = {
            "chat_id": session.chat_id,
            "user_name": session.user_name,
            "messages": session.messages,
            "memory_dir": session.memory_dir,
            "created_at": session.created_at,
            "last_active": session.last_active,
            "active_file_path": session.active_file_path,
        }
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def count(self) -> int:
        if not self.telegram_config.session_dir.exists():
            return 0
        return sum(1 for path in self.telegram_config.session_dir.glob("*.json") if path.is_file())

    def path_for_chat(self, chat_id: int) -> Path:
        return self.telegram_config.session_dir / f"{chat_id}.json"


class PerChatRateLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = limit_per_minute
        self.events: dict[int, deque[float]] = {}

    def allow(self, chat_id: int) -> bool:
        if self.limit_per_minute <= 0:
            return True
        now = time.monotonic()
        window_start = now - 60.0
        events = self.events.setdefault(chat_id, deque())
        while events and events[0] < window_start:
            events.popleft()
        if len(events) >= self.limit_per_minute:
            return False
        events.append(now)
        return True

    def snapshot(self) -> dict[str, Any]:
        return {
            "limit_per_minute": self.limit_per_minute,
            "tracked_chats": len(self.events),
            "message_counts": {str(chat_id): len(events) for chat_id, events in self.events.items()},
        }


class TelegramRuntime:
    def __init__(
        self,
        telegram_config: TelegramConfig,
        jarvis_config: JarvisConfig,
        registry: Any,
        memory_config: MemoryConfig,
        extension_catalog: ExtensionCatalog,
    ) -> None:
        self.telegram_config = telegram_config
        self.jarvis_config = jarvis_config
        self.registry = registry
        self.memory_config = memory_config
        self.extension_catalog = extension_catalog
        self.sessions = TelegramSessionStore(
            telegram_config,
            jarvis_config,
            registry,
            memory_config,
            extension_catalog,
        )
        self.rate_limiter = PerChatRateLimiter(telegram_config.rate_limit_per_minute)
        self.chat_locks: dict[int, asyncio.Lock] = {}

    def lock_for_chat(self, chat_id: int) -> asyncio.Lock:
        lock = self.chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self.chat_locks[chat_id] = lock
        return lock

    async def handle_update(self, update: Any, context: Any) -> None:
        message = getattr(update, "effective_message", None)
        chat = getattr(update, "effective_chat", None)
        if message is None or chat is None:
            return
        chat_id = int(chat.id)
        if not self.telegram_config.is_allowed(chat_id):
            await message.reply_text(self.telegram_config.rejection_message)
            return
        if not self.rate_limiter.allow(chat_id):
            await message.reply_text(self.telegram_config.slow_down_message)
            return

        user_name = telegram_user_name(getattr(update, "effective_user", None), chat_id)
        async with self.lock_for_chat(chat_id):
            turn = await self.incoming_turn(message, context.bot, chat_id)
            if turn.direct_reply:
                await reply_text(message, turn.direct_reply, self.telegram_config)
                return
            if not turn.user_text.strip():
                await reply_text(message, "Send text, a document, a photo, or a voice note.", self.telegram_config)
                return

            if self.telegram_config.typing_indicator:
                await context.bot.send_chat_action(chat_id=chat_id, action="typing")

            session = self.sessions.load(chat_id, user_name, turn.user_text)
            session.user_name = user_name
            session.active_file_path = turn.active_file_path
            loop = asyncio.get_running_loop()
            try:
                reply = await loop.run_in_executor(None, self.run_chat_turn, session, turn.user_text)
            except NimChatError as error:
                reply = str(error)

            await reply_text(message, reply, self.telegram_config)
            if self.telegram_config.send_files_inline:
                await self.send_queued_files(context.bot, chat_id)

    async def incoming_turn(self, message: Any, bot: Any, chat_id: int) -> IncomingTurn:
        text = getattr(message, "text", None)
        if isinstance(text, str) and text.strip():
            return IncomingTurn(user_text=text.strip())

        caption = getattr(message, "caption", None)
        caption_text = caption.strip() if isinstance(caption, str) else ""
        document = getattr(message, "document", None)
        if document is not None:
            path = await self.download_attachment(
                bot,
                chat_id,
                document.file_id,
                getattr(document, "file_name", "") or "document",
            )
            return IncomingTurn(file_user_text("document", path, caption_text), str(path))

        photos = getattr(message, "photo", None)
        if photos:
            photo = photos[-1]
            name = "photo-" + getattr(photo, "file_unique_id", uuid.uuid4().hex) + ".jpg"
            path = await self.download_attachment(bot, chat_id, photo.file_id, name)
            return IncomingTurn(file_user_text("photo", path, caption_text), str(path))

        voice = getattr(message, "voice", None)
        if voice is not None:
            path = await self.download_attachment(
                bot,
                chat_id,
                voice.file_id,
                "voice-" + getattr(voice, "file_unique_id", uuid.uuid4().hex) + ".ogg",
            )
            if not self.telegram_config.voice_transcription:
                return IncomingTurn(
                    active_file_path=str(path),
                    direct_reply="Voice transcription is disabled in the Telegram bot config.",
                )
            loop = asyncio.get_running_loop()
            try:
                transcript = await loop.run_in_executor(None, self.transcribe_voice_file, path)
            except VoiceError as error:
                return IncomingTurn(
                    active_file_path=str(path),
                    direct_reply=f"Voice transcription requires working NVIDIA STT configuration. {error}",
                )
            if not transcript.strip():
                return IncomingTurn(
                    active_file_path=str(path),
                    direct_reply="I could not detect speech in that voice note.",
                )
            return IncomingTurn(file_user_text("voice note", path, transcript), str(path))

        audio = getattr(message, "audio", None)
        if audio is not None:
            name = getattr(audio, "file_name", "") or "audio-" + getattr(audio, "file_unique_id", uuid.uuid4().hex)
            path = await self.download_attachment(bot, chat_id, audio.file_id, name)
            return IncomingTurn(file_user_text("audio file", path, caption_text), str(path))

        return IncomingTurn(user_text="")

    async def download_attachment(self, bot: Any, chat_id: int, file_id: str, name: str) -> Path:
        chat_dir = self.telegram_config.upload_dir / str(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        filename = safe_file_name(name)
        path = unique_path(chat_dir / filename)
        telegram_file = await bot.get_file(file_id)
        await telegram_file.download_to_drive(custom_path=str(path))
        return path.resolve()

    def transcribe_voice_file(self, path: Path) -> str:
        voice_config = VoiceConfig.from_env()
        audio = audio_file_to_pcm(path, voice_config.stt_sample_rate, self.telegram_config.ffmpeg_command)
        return transcribe_nvidia_audio_at_rate(voice_config, audio, voice_config.stt_sample_rate)

    def run_chat_turn(self, session: TelegramSession, user_text: str) -> str:
        memory_config = memory_config_for_chat(self.memory_config, self.telegram_config, session.chat_id)
        turn_messages = [*session.messages]
        if count_role(session.messages, "user") > 0:
            vector_message = vector_memory_system_message(user_text, memory_config, self.jarvis_config)
            if vector_message is not None:
                turn_messages.append(vector_message)
        turn_messages.append({"role": "user", "content": user_text})

        outbox_dir = self.telegram_config.download_dir / "outbox"
        set_telegram_context(
            TelegramToolContext(
                active=True,
                chat_id=str(session.chat_id),
                session_path=str(self.sessions.path_for_chat(session.chat_id)),
                session_metadata={
                    "created_at": session.created_at,
                    "last_active": session.last_active,
                    "turns": count_role(session.messages, "user"),
                    "messages": len(session.messages),
                },
                memory_mode=self.telegram_config.memory_mode,
                webhook_mode=self.telegram_config.webhook_mode,
                rate_limit=self.rate_limiter.snapshot(),
                session_count=self.sessions.count(),
                active_file_path=session.active_file_path,
                outbox_dir=outbox_dir,
                download_dir=self.telegram_config.download_dir,
                auto_send_file_result_paths=self.telegram_config.auto_send_file_result_paths,
            )
        )
        try:
            reply = chat_once(
                self.jarvis_config,
                turn_messages,
                TelegramDeliveryRegistry(self.registry, self.telegram_config.send_files_inline),
            )
        finally:
            clear_telegram_context()

        session.messages.append({"role": "user", "content": user_text})
        session.messages.append({"role": "assistant", "content": reply})
        session.last_active = now_text()
        session.active_file_path = ""
        session.messages = prune_session_messages(session.messages, self.telegram_config.max_session_messages)
        self.sessions.save(session)
        remember_chat(memory_config, self.jarvis_config, user_text, reply)
        return reply

    async def send_queued_files(self, bot: Any, chat_id: int) -> None:
        entries = drain_telegram_outbox(str(chat_id), self.telegram_config.download_dir / "outbox")
        for entry in entries:
            file_path = Path(str(entry.get("file_path", "")))
            if not file_path.is_file():
                continue
            caption = str(entry.get("caption", "") or "")
            with file_path.open("rb") as handle:
                await bot.send_document(
                    chat_id=chat_id,
                    document=handle,
                    filename=file_path.name,
                    caption=caption[:1024] if caption else None,
                )

    def check_lines(self) -> tuple[bool, list[str]]:
        token = self.telegram_config.bot_token()
        names = {tool.name for tool in self.registry.visible_tools()}
        required_tools = {"telegram_status", "telegram_send_file", "telegram_session_info"}
        package_ok = telegram_package_available()
        tools_ok = required_tools.issubset(names)
        lines = [
            f"Config -> {self.telegram_config.config_path}",
            f"python-telegram-bot -> {'ok' if package_ok else 'missing'}",
            f"{self.telegram_config.bot_token_env} -> {'set' if token else 'missing'}",
            f"Telegram tools -> {'ok' if tools_ok else 'missing'}",
            f"Mode -> {'webhook' if self.telegram_config.webhook_mode else 'polling'}",
            f"Memory mode -> {self.telegram_config.memory_mode}",
            f"Session dir -> {self.telegram_config.session_dir}",
            f"Upload dir -> {self.telegram_config.upload_dir}",
            f"Download dir -> {self.telegram_config.download_dir}",
            f"Allowed chats -> {'open' if not self.telegram_config.allowed_chat_ids else len(self.telegram_config.allowed_chat_ids)}",
            f"Rate limit -> {self.telegram_config.rate_limit_per_minute}/minute/chat",
            f"Auto file delivery paths -> {len(self.telegram_config.auto_send_file_result_paths)}",
        ]
        return bool(token and package_ok and tools_ok), lines


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise TelegramBotError(f"Telegram config is not valid JSON: {path}") from error
    if not isinstance(data, dict):
        raise TelegramBotError(f"Telegram config must be a JSON object: {path}")
    return data


class TelegramDeliveryRegistry:
    def __init__(self, registry: Any, send_files_inline: bool) -> None:
        self.registry = registry
        self.send_files_inline = send_files_inline

    def visible_tools(self) -> list[Any]:
        return self.registry.visible_tools()

    def openai_tools(self) -> list[dict[str, Any]]:
        return self.registry.openai_tools()

    def planner_tools(self) -> list[dict[str, Any]]:
        return self.registry.planner_tools()

    def capability_text(self) -> str:
        return self.registry.capability_text()

    def execute(self, name: str, arguments: Any) -> str:
        if name == "telegram_send_file" and not delivery_file_exists(arguments):
            return json.dumps(
                {
                    "ok": True,
                    "tool": name,
                    "result": {
                        "queued": False,
                        "deferred": True,
                        "summary": "Telegram file delivery is waiting for the producing tool to return an actual local file path.",
                    },
                },
                ensure_ascii=False,
            )
        payload = self.registry.execute(name, arguments)
        if self.send_files_inline and name != "telegram_send_file":
            auto_queue_file_outputs(payload)
        return payload


def delivery_file_exists(arguments: Any) -> bool:
    params = arguments if isinstance(arguments, dict) else {}
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            params = parsed
    value = params.get("file_path") if isinstance(params, dict) else None
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return resolve_send_file_path(value).is_file()
    except Exception:
        return False


def text_value(data: dict[str, Any], key: str, fallback: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def text_list_value(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            text = item.strip()
            if text not in result:
                result.append(text)
    return tuple(result)


def bool_value(data: dict[str, Any], key: str, fallback: bool) -> bool:
    value = data.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip():
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return fallback


def config_path_value(data: dict[str, Any], key: str, fallback: str, workspace: Path) -> Path:
    value = text_value(data, key, fallback)
    path = Path(value)
    if not path.is_absolute():
        path = workspace / path
    return path


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def allowed_chats_from_config(value: Any) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TelegramBotError("allowed_chat_ids must be a list")
    chat_ids: list[int] = []
    for item in value:
        try:
            chat_ids.append(int(item))
        except (TypeError, ValueError) as error:
            raise TelegramBotError("allowed_chat_ids must contain chat id numbers") from error
    return chat_ids


def parse_chat_ids(value: str) -> list[int]:
    chat_ids: list[int] = []
    for raw in value.split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            chat_ids.append(int(item))
        except ValueError as error:
            raise TelegramBotError("TELEGRAM_ALLOWED_CHATS must be comma-separated chat id numbers") from error
    return chat_ids


def memory_config_for_chat(
    base_config: MemoryConfig,
    telegram_config: TelegramConfig,
    chat_id: int,
) -> MemoryConfig:
    if telegram_config.memory_mode == "shared":
        return base_config
    return replace(base_config, root=telegram_config.per_user_memory_root / str(chat_id))


def session_from_json(content: str, chat_id: int, user_name: str, memory_root: Path) -> TelegramSession:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    now = now_text()
    return TelegramSession(
        chat_id=safe_int(data.get("chat_id"), chat_id),
        user_name=text_from_any(data.get("user_name"), user_name),
        messages=message_list(data.get("messages")),
        memory_dir=text_from_any(data.get("memory_dir"), str(memory_root)),
        created_at=text_from_any(data.get("created_at"), now),
        last_active=text_from_any(data.get("last_active"), now),
        active_file_path=text_from_any(data.get("active_file_path"), ""),
    )


def message_list(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    messages: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if isinstance(role, str) and isinstance(content, str):
            messages.append({"role": role, "content": content})
    return messages


def text_from_any(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def count_role(messages: list[dict[str, str]], role: str) -> int:
    return sum(1 for message in messages if message.get("role") == role)


def prune_session_messages(messages: list[dict[str, str]], max_non_system_messages: int) -> list[dict[str, str]]:
    system_messages = [message for message in messages if message.get("role") == "system"]
    turn_messages = [message for message in messages if message.get("role") != "system"]
    return [*system_messages, *turn_messages[-max_non_system_messages:]]


def file_user_text(kind: str, path: Path, text: str) -> str:
    parts = [f"User uploaded a {kind} available at {path}."]
    if text.strip():
        parts.append(text.strip())
    return " ".join(parts)


def safe_file_name(name: str) -> str:
    text = name.strip() or uuid.uuid4().hex
    parts: list[str] = []
    for char in text:
        if char.isalnum() or char in {" ", ".", "-", "_", "(", ")"}:
            parts.append(char)
        else:
            parts.append("_")
    cleaned = "".join(parts).strip(" .")
    return cleaned or uuid.uuid4().hex


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{uuid.uuid4().hex}{suffix}")


def telegram_user_name(user: Any, chat_id: int) -> str:
    if user is None:
        return str(chat_id)
    full_name = getattr(user, "full_name", "")
    if isinstance(full_name, str) and full_name.strip():
        return full_name.strip()
    username = getattr(user, "username", "")
    if isinstance(username, str) and username.strip():
        return username.strip()
    user_id = getattr(user, "id", chat_id)
    return str(user_id)


def audio_file_to_pcm(path: Path, sample_rate: int, ffmpeg_command: str) -> bytes:
    command = [
        ffmpeg_command,
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise VoiceError(f"Missing audio converter: {ffmpeg_command}") from error
    except subprocess.TimeoutExpired as error:
        raise VoiceError("Audio conversion timed out.") from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise VoiceError(detail or "Audio conversion failed.")
    return completed.stdout


def chunk_telegram_response(text: str, max_length: int) -> list[str]:
    clean = text if text.strip() else "Done."
    units = code_aware_units(clean)
    chunks: list[str] = []
    current = ""
    for unit in units:
        pieces = [unit] if len(unit) <= max_length else split_long_unit(unit, max_length)
        for piece in pieces:
            if not piece:
                continue
            candidate = current + piece if current else piece
            if len(candidate) <= max_length:
                current = candidate
                continue
            if current:
                chunks.append(current.strip())
            current = piece
    if current:
        chunks.append(current.strip())
    return chunks or ["Done."]


def code_aware_units(text: str) -> list[str]:
    units: list[str] = []
    buffer: list[str] = []
    in_code = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            if not in_code and buffer:
                units.extend(paragraph_units("".join(buffer)))
                buffer = []
            buffer.append(line)
            in_code = not in_code
            if not in_code:
                units.append("".join(buffer))
                buffer = []
            continue
        buffer.append(line)
    if buffer:
        if in_code:
            units.append("".join(buffer))
        else:
            units.extend(paragraph_units("".join(buffer)))
    return units


def paragraph_units(text: str) -> list[str]:
    units: list[str] = []
    parts = text.split("\n\n")
    for index, part in enumerate(parts):
        if not part:
            continue
        suffix = "\n\n" if index < len(parts) - 1 else ""
        units.append(part + suffix)
    return units


def split_long_unit(text: str, max_length: int) -> list[str]:
    if text.lstrip().startswith("```"):
        return hard_chunks(text, max_length)
    pieces: list[str] = []
    for line in text.splitlines(keepends=True):
        if len(line) <= max_length:
            pieces.append(line)
            continue
        pieces.extend(split_long_line(line, max_length))
    return pack_units(pieces, max_length)


def split_long_line(text: str, max_length: int) -> list[str]:
    words = text.split(" ")
    pieces: list[str] = []
    current = ""
    for word in words:
        spacer = " " if current else ""
        candidate = current + spacer + word
        if len(candidate) <= max_length:
            current = candidate
            continue
        if current:
            pieces.append(current)
        if len(word) > max_length:
            pieces.extend(hard_chunks(word, max_length))
            current = ""
        else:
            current = word
    if current:
        pieces.append(current)
    return pieces


def hard_chunks(text: str, max_length: int) -> list[str]:
    return [text[index : index + max_length] for index in range(0, len(text), max_length)]


def pack_units(units: list[str], max_length: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = current + unit if current else unit
        if len(candidate) <= max_length:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = unit
    if current:
        chunks.append(current)
    return chunks


async def reply_text(message: Any, text: str, telegram_config: TelegramConfig) -> None:
    for chunk in chunk_telegram_response(text, telegram_config.max_message_length):
        await send_text_with_fallback(message, chunk, telegram_config.parse_mode)


async def send_text_with_fallback(message: Any, text: str, parse_mode: str) -> None:
    bad_request = telegram_bad_request()
    if parse_mode and parse_mode.casefold() != "plain":
        try:
            await message.reply_text(text, parse_mode=parse_mode, disable_web_page_preview=True)
            return
        except bad_request:
            pass
    try:
        await message.reply_text(telegram_html(text), parse_mode="HTML", disable_web_page_preview=True)
        return
    except bad_request:
        await message.reply_text(text, disable_web_page_preview=True)


def telegram_html(text: str) -> str:
    lines: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            if in_code:
                lines.append("</pre>")
            else:
                lines.append("<pre>")
            in_code = not in_code
            continue
        lines.append(html.escape(line))
    if in_code:
        lines.append("</pre>")
    return "\n".join(lines)


def telegram_bad_request() -> type[Exception]:
    try:
        module = importlib.import_module("telegram.error")
    except ImportError:
        return Exception
    bad_request = getattr(module, "BadRequest", Exception)
    return bad_request if isinstance(bad_request, type) else Exception


def telegram_package_available() -> bool:
    try:
        importlib.import_module("telegram")
        importlib.import_module("telegram.ext")
    except ImportError:
        return False
    return True


def build_telegram_application(runtime: TelegramRuntime) -> Any:
    try:
        telegram_ext = importlib.import_module("telegram.ext")
    except ImportError as error:
        raise TelegramBotError("Install python-telegram-bot to run telegram_bot.py.") from error
    token = runtime.telegram_config.bot_token()
    if not token:
        raise TelegramBotError(f"Missing {runtime.telegram_config.bot_token_env}.")
    application = telegram_ext.Application.builder().token(token).build()
    application.add_handler(telegram_ext.MessageHandler(telegram_ext.filters.ALL, runtime.handle_update))
    return application


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis Telegram bot entrypoint.")
    parser.add_argument("--check", action="store_true", help="Validate Telegram config, token env, package, and tools.")
    return parser


def build_runtime() -> TelegramRuntime:
    workspace = Path.cwd()
    telegram_config = TelegramConfig.from_env(workspace)
    telegram_config.ensure_dirs()
    jarvis_config = JarvisConfig.from_env()
    extension_catalog = load_extension_catalog()
    registry = discover_tools(extension_catalog=extension_catalog)
    memory_config = MemoryConfig.from_env(workspace)
    load_memory_context(memory_config)
    return TelegramRuntime(telegram_config, jarvis_config, registry, memory_config, extension_catalog)


def main() -> int:
    configure_console_output()
    load_dotenv(Path.cwd() / ".env")
    args = build_parser().parse_args()
    try:
        runtime = build_runtime()
        if args.check:
            ok, lines = runtime.check_lines()
            print("\n".join(lines))
            return 0 if ok else 1

        application = build_telegram_application(runtime)
        config = runtime.telegram_config
        print(f"{config.agent_name} starting in {'webhook' if config.webhook_mode else 'polling'} mode.")
        if config.webhook_mode:
            if not config.webhook_url:
                raise TelegramBotError("webhook_mode needs webhook_url or TELEGRAM_WEBHOOK_URL.")
            application.run_webhook(
                listen="0.0.0.0",
                port=config.webhook_port,
                webhook_url=config.webhook_url,
                allowed_updates=None,
            )
        else:
            application.run_polling(allowed_updates=None)
        return 0
    except (TelegramBotError, NimChatError, VoiceError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
