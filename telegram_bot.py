"""
Telegram bridge for A.N.K.I.T.A.

OpenClaw-style channel adapter — reuses the same agent runtime as gui.py and
chat.py.
  - Multi-agent Orchestrator (Supervisor → Specialists → Synthesizer)
  - ProactiveEngine — DreamState epiphanies and ContentAgent raw_ideas events
    are automatically pushed to the Telegram chat that triggered them
  - Commands: /start, /help, /reset, /agents on|off
"""
import json
import mimetypes
import os
import re
import time
import uuid
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from dotenv import load_dotenv

from agent_runtime import AgentRuntime, new_session
from agents import Orchestrator
from agents.hive import HiveMind
from corn import CornRunner
from llm import build_runtime_from_env, call_chat_once
from llm.client import call_chat_with_image
from proactive import ProactiveEngine

WORKSPACE_ROOT = Path.cwd().resolve()
STATE_DIR = Path(".ankita") / "telegram"
OFFSET_FILE = STATE_DIR / "update-offset.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class ParsedTelegramInput:
    kind: str
    text: str
    file_id: str = ""
    file_name: str = ""
    mime_type: str = ""
    file_size: int = 0
    caption: str = ""
    chat_id: int = 0
    message_id: int = 0

def read_offset() -> int:
    try:
        payload = json.loads(OFFSET_FILE.read_text(encoding="utf-8"))
        value = int(payload.get("offset", 0))
        return max(value, 0)
    except Exception:
        return 0


def write_offset(offset: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(
        json.dumps({"offset": int(offset)}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def chunk_text(text: str, chunk_size: int = 3900) -> List[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start: start + chunk_size])
        start += chunk_size
    return chunks


def tg_api(token: str, method: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    res = requests.post(url, json=payload, timeout=timeout)
    res.raise_for_status()
    data = res.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API {method} failed: {data}")
    return data


def tg_api_form(
    token: str,
    method: str,
    data: Dict[str, Any],
    files: Dict[str, Any],
    timeout: int = 120,
) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    res = requests.post(url, data=data, files=files, timeout=timeout)
    res.raise_for_status()
    payload = res.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API {method} failed: {payload}")
    return payload


def send_text(
    token: str,
    chat_id: int,
    text: str,
    reply_to_message_id: Optional[int] = None,
) -> None:
    for chunk in chunk_text(text):
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": chunk}
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        try:
            tg_api(token, "sendMessage", payload, timeout=60)
        except Exception:
            # Retry once without reply target (some contexts reject reply links)
            payload.pop("reply_to_message_id", None)
            tg_api(token, "sendMessage", payload, timeout=60)


def send_document(
    token: str,
    chat_id: int,
    file_path: Path,
    caption: str = "",
    reply_to_message_id: Optional[int] = None,
) -> None:
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Document not found: {file_path}")
    with file_path.open("rb") as fh:
        data: Dict[str, Any] = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = reply_to_message_id
        tg_api_form(
            token,
            "sendDocument",
            data=data,
            files={"document": (file_path.name, fh, "application/octet-stream")},
            timeout=180,
        )


def send_photo(
    token: str,
    chat_id: int,
    file_path: Path,
    caption: str = "",
    reply_to_message_id: Optional[int] = None,
) -> None:
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Photo not found: {file_path}")
    guessed_type, _ = mimetypes.guess_type(str(file_path))
    mime = guessed_type or "image/jpeg"
    with file_path.open("rb") as fh:
        data: Dict[str, Any] = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = reply_to_message_id
        tg_api_form(
            token,
            "sendPhoto",
            data=data,
            files={"photo": (file_path.name, fh, mime)},
            timeout=180,
        )


def send_voice(
    token: str,
    chat_id: int,
    file_path: Path,
    caption: str = "",
    reply_to_message_id: Optional[int] = None,
) -> None:
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Voice file not found: {file_path}")
    with file_path.open("rb") as fh:
        data: Dict[str, Any] = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = reply_to_message_id
        tg_api_form(
            token,
            "sendVoice",
            data=data,
            files={"voice": (file_path.name, fh, "audio/ogg")},
            timeout=180,
        )


def send_file_auto(
    token: str,
    chat_id: int,
    file_path: Path,
    caption: str = "",
    reply_to_message_id: Optional[int] = None,
) -> None:
    guessed, _ = mimetypes.guess_type(str(file_path))
    if (guessed or "").startswith("image/"):
        send_photo(token, chat_id, file_path, caption=caption, reply_to_message_id=reply_to_message_id)
        return
    if (guessed or "") in {"audio/ogg", "audio/opus"}:
        send_voice(token, chat_id, file_path, caption=caption, reply_to_message_id=reply_to_message_id)
        return
    send_document(token, chat_id, file_path, caption=caption, reply_to_message_id=reply_to_message_id)


def send_reaction(token: str, chat_id: int, message_id: int, emoji: str) -> None:
    if not emoji:
        return
    tg_api(
        token,
        "setMessageReaction",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
            "is_big": False,
        },
        timeout=30,
    )


def choose_reaction(parsed_input: ParsedTelegramInput, processing_state: str, result_state: str) -> Optional[str]:
    if result_state == "hard_failure":
        return "⚠️"
    if result_state == "recoverable_failure":
        return "🤔"
    if processing_state == "start":
        return "⚡"
    if result_state == "success":
        return "🔥" if parsed_input.kind in {"photo", "voice"} else "✅"
    if processing_state == "received":
        return "👀" if parsed_input.kind != "text" else "👍"
    return None


def choose_reaction_with_llm(
    runtime: Any,
    parsed_input: ParsedTelegramInput,
    processing_state: str,
    result_state: str,
) -> Optional[str]:
    # Keep a deterministic fallback if LLM call fails.
    fallback = choose_reaction(parsed_input, processing_state, result_state)
    try:
        prompt = (
            "Pick ONE emoji reaction for this Telegram message state.\n"
            "Rules:\n"
            "- Return ONLY one emoji from: 👀 👍 ⚡ ✅ 🔥 🤔 ⚠️ or NONE\n"
            "- If no reaction needed, return NONE.\n"
            f"- kind={parsed_input.kind}, processing_state={processing_state}, result_state={result_state}, "
            f"text={parsed_input.text[:200]!r}, caption={parsed_input.caption[:200]!r}"
        )
        msg = call_chat_once(
            runtime=runtime,
            messages=[
                {"role": "system", "content": "You choose concise Telegram emoji reactions."},
                {"role": "user", "content": prompt},
            ],
            tools=None,
            max_tokens=16,
        )
        out = str(msg.get("content", "")).strip()
        allowed = {"👀", "👍", "⚡", "✅", "🔥", "🤔", "⚠️", "NONE"}
        if out in allowed:
            return None if out == "NONE" else out
    except Exception:
        pass
    return fallback


def _vision_analyze_image(runtime: Any, image_path: Path, caption: str = "") -> str:
    try:
        raw = image_path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        mime, _ = mimetypes.guess_type(str(image_path))
        mime = mime or "image/jpeg"
        prompt = "Analyze this user image and summarize what matters."
        if caption:
            prompt += f" User context: {caption}"
        return call_chat_with_image(runtime, prompt=prompt, image_b64=b64, mime_type=mime)
    except Exception:
        return ""


def parse_incoming_message(msg: Dict[str, Any]) -> Optional[ParsedTelegramInput]:
    chat = msg.get("chat") or {}
    chat_id = int(chat.get("id", 0))
    message_id = int(msg.get("message_id", 0))
    text = str(msg.get("text", "")).strip()
    caption = str(msg.get("caption", "")).strip()
    if text:
        return ParsedTelegramInput(
            kind="text",
            text=text,
            caption=caption,
            chat_id=chat_id,
            message_id=message_id,
        )
    photos = msg.get("photo") or []
    if photos:
        best = max(photos, key=lambda item: int(item.get("file_size", 0) or 0))
        return ParsedTelegramInput(
            kind="photo",
            text=caption or "Analyze this image.",
            file_id=str(best.get("file_id", "")),
            file_name="photo.jpg",
            mime_type="image/jpeg",
            file_size=int(best.get("file_size", 0) or 0),
            caption=caption,
            chat_id=chat_id,
            message_id=message_id,
        )
    doc = msg.get("document")
    if doc:
        return ParsedTelegramInput(
            kind="document",
            text=caption or "",
            file_id=str(doc.get("file_id", "")),
            file_name=str(doc.get("file_name", "document.bin")),
            mime_type=str(doc.get("mime_type", "application/octet-stream")),
            file_size=int(doc.get("file_size", 0) or 0),
            caption=caption,
            chat_id=chat_id,
            message_id=message_id,
        )
    voice = msg.get("voice")
    if voice:
        return ParsedTelegramInput(
            kind="voice",
            text=caption or "",
            file_id=str(voice.get("file_id", "")),
            file_name="voice.ogg",
            mime_type=str(voice.get("mime_type", "audio/ogg")),
            file_size=int(voice.get("file_size", 0) or 0),
            caption=caption,
            chat_id=chat_id,
            message_id=message_id,
        )
    audio = msg.get("audio")
    if audio:
        fname = str(audio.get("file_name", "audio.mp3"))
        return ParsedTelegramInput(
            kind="voice",
            text=caption or "",
            file_id=str(audio.get("file_id", "")),
            file_name=fname,
            mime_type=str(audio.get("mime_type", "audio/mpeg")),
            file_size=int(audio.get("file_size", 0) or 0),
            caption=caption,
            chat_id=chat_id,
            message_id=message_id,
        )
    return None


def get_file_metadata(token: str, file_id: str) -> Dict[str, Any]:
    payload = tg_api(token, "getFile", {"file_id": file_id}, timeout=60)
    return payload.get("result", {}) or {}


def download_file(token: str, file_path: str, destination: Path, timeout: int = 180) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://api.telegram.org/file/bot{token}/{file_path.lstrip('/')}"
    with requests.get(url, stream=True, timeout=timeout) as res:
        res.raise_for_status()
        with destination.open("wb") as out:
            for chunk in res.iter_content(chunk_size=64 * 1024):
                if chunk:
                    out.write(chunk)
    return destination


def _build_media_prompt(parsed: ParsedTelegramInput, local_file: Path, transcript: str = "") -> str:
    if parsed.kind == "photo":
        base = "Analyze this image and give practical insights."
        if parsed.caption:
            base += f"\nUser caption/context: {parsed.caption}"
        return f"{base}\nLocal image path: {local_file}"
    if parsed.kind == "document":
        extra = f"User instruction: {parsed.caption}" if parsed.caption else "No extra user instruction provided."
        return (
            "Summarize and extract key points from this file. "
            "If needed, use file-reading tools to inspect it.\n"
            f"Filename: {parsed.file_name}\n"
            f"MIME: {parsed.mime_type}\n"
            f"Local file path: {local_file}\n"
            f"{extra}"
        )
    if parsed.kind == "voice":
        if transcript:
            base = f"The user sent a voice note. Transcript:\n{transcript}"
            if parsed.caption:
                base += f"\nCaption: {parsed.caption}"
            return base
        return (
            "The user sent a voice note, but transcription is unavailable in this runtime. "
            "Ask them to resend as text and offer concise help meanwhile."
        )
    return parsed.text


def _extract_candidate_paths(text: str) -> List[Path]:
    candidates: List[Path] = []
    if not text:
        return candidates
    patterns = [
        r"[A-Za-z]:\\[^\s\"']+",          # Windows absolute path
        r"\.[\\/][^\s\"']+",              # ./relative or .\relative
        r"[A-Za-z0-9_\-./\\]+\.[A-Za-z0-9]{1,8}",  # generic file-like token
    ]
    seen: Set[str] = set()
    for pat in patterns:
        for raw in re.findall(pat, text):
            token = raw.strip().strip(".,;:!?)(").strip("\"'")
            if not token:
                continue
            p = Path(token)
            if not p.is_absolute():
                p = (WORKSPACE_ROOT / p).resolve()
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            if p.exists() and p.is_file():
                candidates.append(p)
    return candidates


def _parse_send_file_intent(text: str) -> Optional[str]:
    t = (text or "").strip()
    if not t:
        return None
    if t.lower().startswith("/sendfile "):
        return t[len("/sendfile "):].strip().strip('"').strip("'")
    lowered = t.lower()
    # User asks for random file from Downloads
    if "send" in lowered and "download" in lowered:
        return "__DOWNLOADS_RANDOM__"
    send_markers = ("send", "telegram", "file")
    if all(m in lowered for m in send_markers):
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", t)
        if quoted:
            return quoted[0].strip()
        paths = _extract_candidate_paths(t)
        if paths:
            return str(paths[0])
        return "__LAST_ARTIFACT__"
    # Natural follow-ups like "send me this", "send it on telegram", etc.
    if "send" in lowered and ("this" in lowered or "it" in lowered):
        if "telegram" in lowered or "tg" in lowered:
            return "__LAST_ARTIFACT__"
    # Implicit Telegram delivery intent in Telegram chat: "send random image/file from my pc"
    if "send" in lowered and any(k in lowered for k in ("image", "photo", "file", "document", "pic")):
        if any(k in lowered for k in ("my pc", "computer", "laptop", "system", "downloads", "desktop", "pictures", "folder", "random")):
            return "__AGENT_PICK__"
    return None


def _pick_random_file_from_downloads() -> Optional[Path]:
    base = Path.home() / "Downloads"
    if not base.exists() or not base.is_dir():
        return None
    # Keep scan bounded for responsiveness.
    pool = [p for p in base.rglob("*") if p.is_file()]
    if not pool:
        return None
    # deterministic-enough pseudo-random based on current time
    idx = int(time.time()) % len(pool)
    return pool[idx]


def _extract_mentioned_filenames(text: str) -> List[str]:
    out: List[str] = []
    if not text:
        return out
    # quoted file names like "photo_123.jpg"
    for token in re.findall(r"['\"]([^'\"]+\.[A-Za-z0-9]{1,8})['\"]", text):
        out.append(Path(token).name)
    # unquoted leaf names like abc.pdf
    for token in re.findall(r"\b([A-Za-z0-9_\-]+\.[A-Za-z0-9]{1,8})\b", text):
        out.append(Path(token).name)
    dedup: List[str] = []
    seen: Set[str] = set()
    for name in out:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(name)
    return dedup


def _resolve_file_by_name(file_name: str) -> Optional[Path]:
    if not file_name:
        return None
    roots = [
        WORKSPACE_ROOT,
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path.home() / "Pictures",
    ]
    target = file_name.lower()
    for root in roots:
        try:
            if not root.exists():
                continue
            direct = root / file_name
            if direct.exists() and direct.is_file():
                return direct.resolve()
            for p in root.rglob(file_name):
                if p.exists() and p.is_file():
                    return p.resolve()
            # case-insensitive fallback
            for p in root.rglob("*"):
                if p.is_file() and p.name.lower() == target:
                    return p.resolve()
        except Exception:
            continue
    return None


def _extract_send_directives(note: str) -> Tuple[str, List[Path], List[str]]:
    """Extract TELEGRAM_FILE, TELEGRAM_IMAGE, and TELEGRAM_NOTIFY directives from agent output.

    Returns:
        (clean_text, file_paths, notify_messages)
        clean_text    — agent reply with directives stripped (safe to send as text)
        file_paths    — paths to send as Telegram photos/documents (auto-detected)
        notify_messages — plain text mid-task notifications to send immediately
    """
    if not note:
        return note, [], []
    out_paths: List[Path] = []
    notify_msgs: List[str] = []
    clean = note
    # Contract for agents:
    # TELEGRAM_FILE: C:\path\to\file.ext
    # ```telegram_send
    # C:\path\one
    # C:\path\two
    # ```
    for m in re.findall(r"TELEGRAM_FILE:\s*(.+)", note):
        raw = m.strip().strip("`").strip("\"'")
        p = Path(raw)
        if not p.is_absolute():
            p = (WORKSPACE_ROOT / p).resolve()
        if p.exists() and p.is_file():
            out_paths.append(p)
    # TELEGRAM_IMAGE: — sends image as inline Telegram photo (same delivery, explicit intent)
    for m in re.findall(r"TELEGRAM_IMAGE:\s*(.+)", note):
        raw = m.strip().strip("`").strip("\"'")
        p = Path(raw)
        if not p.is_absolute():
            p = (WORKSPACE_ROOT / p).resolve()
        if p.exists() and p.is_file():
            out_paths.append(p)
    # TELEGRAM_NOTIFY: — mid-task plain text notification
    for m in re.findall(r"TELEGRAM_NOTIFY:\s*(.+)", note):
        msg = m.strip()
        if msg:
            notify_msgs.append(msg)
    block = re.search(r"```telegram_send\s*([\s\S]*?)```", note, flags=re.IGNORECASE)
    if block:
        for line in block.group(1).splitlines():
            raw = line.strip().strip("`").strip("\"'")
            if not raw:
                continue
            p = Path(raw)
            if not p.is_absolute():
                p = (WORKSPACE_ROOT / p).resolve()
            if p.exists() and p.is_file():
                out_paths.append(p)
    # Remove directives from the user-facing text.
    clean = re.sub(r"TELEGRAM_FILE:\s*.+", "", clean)
    clean = re.sub(r"TELEGRAM_IMAGE:\s*.+", "", clean)
    clean = re.sub(r"TELEGRAM_NOTIFY:\s*.+", "", clean)
    clean = re.sub(r"```telegram_send[\s\S]*?```", "", clean, flags=re.IGNORECASE)
    clean = clean.strip()
    dedup: List[Path] = []
    seen: Set[str] = set()
    for p in out_paths:
        k = str(p).lower()
        if k in seen:
            continue
        seen.add(k)
        dedup.append(p)
    return clean, dedup, notify_msgs


def parse_allowed_chat_ids(raw: str) -> Set[int]:
    out: Set[int] = set()
    for part in (raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            out.add(int(token))
        except ValueError:
            continue
    return out


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise SystemExit("Error: TELEGRAM_BOT_TOKEN is not set.")

    allowed_chat_ids = parse_allowed_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", ""))
    use_multi_agent = _env_bool("ANKITA_MULTI_AGENT", True)

    runtime = build_runtime_from_env()
    agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)
    orchestrator = Orchestrator(runtime=runtime, workspace_root=WORKSPACE_ROOT)

    # Track active chat early — needed by heartbeat delivery closure below
    last_active_chat_id: Optional[int] = None

    # Corn scheduler — with heartbeat agent execution
    runner: Optional[CornRunner] = None
    if _env_bool("CORN_AUTO_RUN", True):
        runner = CornRunner(
            workspace_root=WORKSPACE_ROOT,
            poll_interval_sec=float(os.getenv("CORN_POLL_INTERVAL_SEC", "5")),
            max_jobs_per_tick=int(os.getenv("CORN_MAX_JOBS_PER_TICK", "5")),
        )
        # Wire heartbeat: agent payload jobs run through the orchestrator
        runner.attach_orchestrator(orchestrator, runtime)

        # Delivery callback: push heartbeat results to the active Telegram chat
        def _heartbeat_deliver(job_name: str, result_text: str) -> None:
            target = last_active_chat_id
            if target is None and allowed_chat_ids:
                target = next(iter(sorted(allowed_chat_ids)))
            if target is None:
                print(f"[heartbeat] No chat to deliver to: {job_name}")
                return
            header = f"⏰ *Heartbeat — {job_name}*\n\n"
            try:
                send_text(bot_token, target, header + result_text)
            except Exception as err:
                print(f"[heartbeat-send-error] {err}")

        runner.set_delivery_fn(_heartbeat_deliver)
        runner.start()

    # Proactive engine — memory session id will be updated to the real per-chat
    # session id as soon as the first message arrives (see set_last_interaction below).
    proactive = ProactiveEngine(workspace_root=WORKSPACE_ROOT)
    proactive.attach_runtime(runtime)
    proactive.start()

    from tools.notification_router import NotificationRouter
    notification_router = NotificationRouter(WORKSPACE_ROOT)

    # Hive Mind — async background task manager
    hive = HiveMind(orchestrator=orchestrator, agent_runtime=agent, use_multi_agent=use_multi_agent)

    # Watchdog system — always-on 24/7 monitoring (shared singleton with chat/gui)
    from watchdog_manager import WatchdogManager
    watchdog_mgr = WatchdogManager(workspace_root=WORKSPACE_ROOT, proactive=proactive)
    watchdog_mgr.load_config()
    watchdog_mgr.start_all()

    # Self-improvement feedback engine
    from tools.feedback_engine import init_engine as _init_fb
    feedback_engine = _init_fb(workspace_root=WORKSPACE_ROOT, llm_runtime=runtime)

    # Initialise memory root so all interfaces share the same facts.db
    try:
        from agent_runtime import set_memory_root
        set_memory_root(WORKSPACE_ROOT)
        from memory import get_memory_manager
        _mem = get_memory_manager(WORKSPACE_ROOT)
        _mem.attach_runtime(runtime)
    except Exception as exc:
        print(f"[telegram] Memory init warning: {exc}")

    # Per-chat state
    sessions: Dict[int, List[Dict[str, Any]]] = {}   # chat_id → message history
    recent_artifacts: Dict[int, List[Path]] = {}     # chat_id -> most recent file artifacts mentioned/sent

    offset = read_offset()
    poll_timeout = max(5, min(int(os.getenv("TELEGRAM_POLL_TIMEOUT", "5")), 120))
    idle_sleep = max(0.2, min(float(os.getenv("TELEGRAM_IDLE_SLEEP_SEC", "0.5")), 3.0))
    media_enabled = _env_bool("TELEGRAM_MEDIA_ENABLED", True)
    reactions_enabled = _env_bool("TELEGRAM_REACTIONS_ENABLED", True)
    max_file_mb = max(1, int(os.getenv("TELEGRAM_MAX_FILE_MB", "25")))
    max_file_bytes = max_file_mb * 1024 * 1024
    inbox_dir = Path(os.getenv("TELEGRAM_INBOX_DIR", ".ankita/telegram/inbox")).resolve()
    inbox_dir.mkdir(parents=True, exist_ok=True)
    # How often (seconds) to check the proactive queue between Telegram polls
    proactive_check_interval = float(os.getenv("TELEGRAM_PROACTIVE_CHECK_SEC", "5"))
    _last_proactive_check = time.time()

    print("╔══════════════════════════════════════╗")
    print("║   A.N.K.I.T.A Telegram Bridge ACTIVE ║")
    print("╚══════════════════════════════════════╝")
    print(f"  Provider    : {runtime.provider}")
    print(f"  Model       : {runtime.model}")
    print(f"  Multi-agent : {'ON' if use_multi_agent else 'OFF'}")
    print(f"  Proactive   : ON (DreamState + ContentAgent)")
    print(f"  Scheduler   : {'ON' if runner is not None else 'OFF'}")
    print(f"  Heartbeat   : {'ON 💓' if runner is not None and runner._orchestrator else 'OFF'}")
    print()

    # ------------------------------------------------------------------
    # Helper: handle proactive events and push to Telegram
    # ------------------------------------------------------------------
    def _flush_proactive_events() -> None:
        nonlocal last_active_chat_id
        target_chat = last_active_chat_id
        if target_chat is None and allowed_chat_ids:
            target_chat = next(iter(sorted(allowed_chat_ids)))
        if target_chat is None:
            return  # Nobody to send to yet

        for event in proactive.get_pending_events():
            result = notification_router.route_notification(event)
            if not result.get("delivered") or "telegram" not in result.get("channels", []):
                continue
            formatted = result.get("formatted_messages", {}).get("telegram", event.message)

            # ---- DreamState epiphany ----------------------------------------
            if event.kind == "dream_epiphany":
                epiphany_text = event.message
                if not epiphany_text:
                    continue
                try:
                    send_text(bot_token, target_chat, f"💭 {epiphany_text}")
                except Exception as err:
                    print(f"[proactive-dream-send-error] {err}")
                continue

            # ---- Morning briefing (first boot of day) -----------------------
            if event.kind == "morning_briefing":
                briefing_text = event.data.get("text", event.message)
                if briefing_text:
                    try:
                        send_text(bot_token, target_chat, f"☀️ *Morning Briefing*\n\n{briefing_text}")
                    except Exception as err:
                        print(f"[proactive-morning-send-error] {err}")
                continue

            # ---- ContentAgent raw_ideas request ------------------------------
            if event.kind == "content_request":
                suggested_prompt = event.message
                if not suggested_prompt:
                    continue
                try:
                    send_text(bot_token, target_chat, f"📝 {event.message}")
                    # Run content generation synchronously (Telegram is already async via long-poll)
                    fresh_msgs = new_session()
                    if use_multi_agent:
                        content_reply = orchestrator.run(
                            user_text=suggested_prompt,
                            messages=fresh_msgs,
                        )
                    else:
                        content_reply = agent.process_user_text(
                            user_text=suggested_prompt,
                            messages=fresh_msgs,
                        )
                    send_text(bot_token, target_chat, content_reply or "(empty response)")
                except Exception as err:
                    print(f"[proactive-content-send-error] {err}")
                continue

            # ---- Sentinel (idle screen-watch alert) -------------------------
            if event.kind == "sentinel":
                sentinel_text = event.data.get("text", event.message)
                idle_label = event.data.get("idle_label", "a while")
                if sentinel_text:
                    try:
                        send_text(
                            bot_token,
                            target_chat,
                            f"👁️ *Sentinel* — I noticed you've been away for {idle_label}:\n\n{sentinel_text}",
                        )
                    except Exception as err:
                        print(f"[proactive-sentinel-send-error] {err}")
                continue

            # ---- Price alert from PriceWatcher ---------------------------------
            if event.kind == "price_alert":
                symbol = event.data.get("symbol", "")
                price = event.data.get("price", "")
                condition = event.data.get("condition", "")
                msg = event.message or f"{symbol} price alert: {condition} @ {price}"
                try:
                    send_text(bot_token, target_chat, f"\U0001f4c8 *Price Alert*\n{msg}")
                except Exception as err:
                    print(f"[proactive-price-send-error] {err}")
                continue

            # ---- News alert from NewsWatcher ------------------------------------
            if event.kind == "news_alert":
                keyword = event.data.get("keyword", "")
                headline = event.data.get("headline", event.message)
                url = event.data.get("url", "")
                body = f"\U0001f4f0 *News Alert*"
                if keyword:
                    body += f" — {keyword}"
                body += f"\n{headline}"
                if url:
                    body += f"\n{url}"
                try:
                    send_text(bot_token, target_chat, body)
                except Exception as err:
                    print(f"[proactive-news-send-error] {err}")
                continue

            # ---- File change from FileWatcher -----------------------------------
            if event.kind == "file_change":
                path = event.data.get("path", "")
                change_type = event.data.get("change_type", "changed")
                msg = event.message or f"File {change_type}: {path}"
                try:
                    send_text(bot_token, target_chat, f"\U0001f4c2 *File Change*\n{msg}")
                except Exception as err:
                    print(f"[proactive-file-send-error] {err}")
                continue

            # ---- Git commit/PR from GitWatcher ----------------------------------
            if event.kind == "git_commit":
                repo = event.data.get("repo", "")
                commits = event.data.get("commits", [])
                msg = event.message or f"New commits in {repo}"
                body = f"\U0001f4bb *Git Update*"
                if repo:
                    body += f" — {repo}"
                body += f"\n{msg}"
                if commits:
                    body += "\n" + "\n".join(f"  • {c}" for c in commits[:5])
                try:
                    send_text(bot_token, target_chat, body)
                except Exception as err:
                    print(f"[proactive-git-send-error] {err}")
                continue

            # ---- All other proactive events (system alerts, cron, drop_file) -
            try:
                send_text(bot_token, target_chat, formatted)
            except Exception as err:
                print(f"[proactive-send-error] {err}")

    # ------------------------------------------------------------------
    # Main polling loop
    # ------------------------------------------------------------------
    while True:
        # Check proactive queue periodically
        now = time.time()
        if now - _last_proactive_check >= proactive_check_interval:
            _last_proactive_check = now
            try:
                _flush_proactive_events()
            except Exception as err:
                print(f"[proactive-flush-error] {err}")

        try:
            data = tg_api(
                bot_token,
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": poll_timeout,
                    "allowed_updates": ["message"],
                },
                timeout=poll_timeout + 15,
            )
            updates = data.get("result", [])
            if not updates:
                time.sleep(idle_sleep)
                continue

            for upd in updates:
                update_id = int(upd.get("update_id", 0))
                if update_id >= offset:
                    offset = update_id + 1
                    write_offset(offset)

                msg = upd.get("message") or {}
                parsed = parse_incoming_message(msg)
                if not parsed:
                    continue

                text = parsed.text
                chat_id = parsed.chat_id
                msg_id = parsed.message_id

                # Access control
                if allowed_chat_ids and chat_id not in allowed_chat_ids:
                    allowed_preview = ",".join(str(v) for v in sorted(allowed_chat_ids))
                    send_text(
                        bot_token,
                        chat_id,
                        f"This bot is not enabled for this chat.\nchat_id={chat_id}\nallowed={allowed_preview}",
                        msg_id,
                    )
                    continue

                # Track last active chat for proactive event routing
                last_active_chat_id = chat_id
                session_id = f"telegram-{chat_id}"

                # Ensure session exists
                if chat_id not in sessions:
                    sessions[chat_id] = new_session(text)
                if chat_id not in recent_artifacts:
                    recent_artifacts[chat_id] = []

                # Save user turn to shared long-term memory
                try:
                    from memory import get_memory_manager
                    get_memory_manager(WORKSPACE_ROOT).save("user", text, interface="telegram")
                except Exception:
                    pass

                # Reset idle tracker so DreamState doesn't fire while user is chatting
                proactive.set_last_interaction()

                if reactions_enabled:
                    try:
                        emoji = choose_reaction_with_llm(runtime, parsed, processing_state="received", result_state="")
                        if emoji:
                            send_reaction(bot_token, chat_id, msg_id, emoji)
                    except Exception:
                        pass

                # ----------------------------------------------------------
                # Commands
                # ----------------------------------------------------------
                if parsed.kind == "text" and text.lower().startswith("/sendfile "):
                    send_intent_path = text[len("/sendfile "):].strip().strip('"').strip("'")
                    candidate: Optional[Path] = None
                    p = Path(send_intent_path)
                    if not p.is_absolute():
                        p = (WORKSPACE_ROOT / p).resolve()
                    candidate = p
                    if candidate is None:
                        send_text(
                            bot_token,
                            chat_id,
                            "I couldn't find which file you meant. Send `/sendfile <path>`.",
                            msg_id,
                        )
                        continue
                    try:
                        if candidate.is_file():
                            send_file_auto(
                                bot_token,
                                chat_id,
                                candidate,
                                caption=f"📎 {candidate.name}",
                                reply_to_message_id=msg_id,
                            )
                            existing = recent_artifacts.setdefault(chat_id, [])
                            existing.append(candidate)
                            recent_artifacts[chat_id] = existing[-10:]
                        else:
                            send_text(bot_token, chat_id, f"File not found: {candidate}", msg_id)
                    except Exception as err:
                        send_text(bot_token, chat_id, f"❌ Could not send file: {err}", msg_id)
                    continue

                send_intent_path = _parse_send_file_intent(text) if parsed.kind == "text" else None

                if parsed.kind == "text" and text.lower() in {"/start", "/help"}:
                    send_text(
                        bot_token,
                        chat_id,
                        (
                            "🤖 *A.N.K.I.T.A* is online.\n\n"
                            "Commands:\n"
                            "/reset — clear current session (memory persists)\n"
                            "/mood — show current personality/mood state\n"
                            "/memory — show memory stats\n"
                            "/agents on — enable multi-agent mode\n"
                            "/agents off — disable multi-agent mode\n"
                            "/hive — show background task status\n"
                            "/heartbeats — show scheduled agent heartbeat jobs\n"
                            "/watchdogs — show all watcher statuses\n"
                            "/github status — check GitHub token\n"
                            "/reauth github — re-authorize GitHub (device flow)\n"
                            "/feedback stats — show self-improvement stats\n"
                            "/sendfile <path> — send a local file/photo/voice\n"
                            "show <id> — get result of a background task\n\n"
                            "Then just send normal prompts!"
                        ),
                        msg_id,
                    )
                    continue

                if parsed.kind == "text" and text.lower() == "/hive":
                    send_text(bot_token, chat_id, hive.list_tasks(), msg_id)
                    continue

                if parsed.kind == "text" and text.lower() == "/watchdogs":
                    send_text(bot_token, chat_id, watchdog_mgr.status(), msg_id)
                    continue

                if parsed.kind == "text" and text.lower() == "/heartbeats":
                    try:
                        from corn import CornService
                        _cs = CornService(workspace_root=WORKSPACE_ROOT)
                        _jobs = _cs.list().get("jobs", [])
                        _agent_jobs = [j for j in _jobs if isinstance(j, dict) and j.get("payload", {}).get("kind") == "agent"]
                        if not _agent_jobs:
                            send_text(bot_token, chat_id, "No agent heartbeat jobs scheduled yet.\n\nTry: \"every morning tell me the news\"", msg_id)
                        else:
                            import datetime as _dt
                            lines = ["⏰ *Heartbeat Jobs*\n"]
                            for j in _agent_jobs:
                                _name = j.get("name", "?")
                                _sched = j.get("schedule", {})
                                _expr = _sched.get("expr", _sched.get("every_ms", "?"))
                                _next_ms = j.get("state", {}).get("next_run_at_ms")
                                _next = "?"
                                if _next_ms:
                                    _next = _dt.datetime.fromtimestamp(_next_ms / 1000).strftime("%Y-%m-%d %H:%M")
                                _prompt = j.get("payload", {}).get("prompt", "")[:60]
                                lines.append(f"• [{j.get('id', '?')[:8]}] {_name}\n  Schedule: {_expr}\n  Next: {_next}\n  Prompt: {_prompt}...")
                            send_text(bot_token, chat_id, "\n".join(lines), msg_id)
                    except Exception as hb_err:
                        send_text(bot_token, chat_id, f"Error listing heartbeats: {hb_err}", msg_id)
                    continue

                if parsed.kind == "text" and text.lower() in ("/reauth github", "/reauth-github"):
                    send_text(bot_token, chat_id, "⏳ GitHub Device Flow started — check server logs for the code and URL, then authorize in browser.", msg_id)
                    import threading as _thr
                    def _tg_reauth(_cid=chat_id, _mid=msg_id):
                        try:
                            from tools.auth_manager import get_github_token, github_token_status
                            get_github_token(force_reauth=True)
                            send_text(bot_token, _cid, github_token_status(), _mid)
                        except Exception as _exc:
                            send_text(bot_token, _cid, f"❌ Re-auth failed: {_exc}", _mid)
                    _thr.Thread(target=_tg_reauth, daemon=True).start()
                    continue

                if parsed.kind == "text" and text.lower() == "/github status":
                    from tools.auth_manager import github_token_status
                    send_text(bot_token, chat_id, github_token_status(), msg_id)
                    continue

                if parsed.kind == "text" and text.lower() == "/feedback stats":
                    try:
                        send_text(bot_token, chat_id, feedback_engine.get_stats(), msg_id)
                    except Exception as _exc:
                        send_text(bot_token, chat_id, f"Error: {_exc}", msg_id)
                    continue

                if parsed.kind == "text" and text.lower().startswith("show "):
                    task_id = text[5:].strip()
                    send_text(bot_token, chat_id, hive.get_result(task_id), msg_id)
                    continue

                if parsed.kind == "text" and text.lower() == "/reset":
                    sessions[chat_id] = new_session("")  # empty query, still injects recent memory
                    # Reset personality engine mood state
                    try:
                        from tools.personality_engine import get_mood_tracker
                        get_mood_tracker().reset()
                    except Exception:
                        pass
                    send_text(bot_token, chat_id, "✅ Conversation reset. Long-term memory preserved.", msg_id)
                    continue

                if parsed.kind == "text" and text.lower() == "/mood":
                    try:
                        from tools.personality_engine import mood_status
                        send_text(bot_token, chat_id, f"🎭 *Personality Engine*\n{mood_status()}", msg_id)
                    except Exception as _mood_err:
                        send_text(bot_token, chat_id, f"⚠️ Personality engine error: {_mood_err}", msg_id)
                    continue

                if parsed.kind == "text" and text.lower() in {"/agents on", "/agents off"}:
                    use_multi_agent = text.lower() == "/agents on"
                    label = "ON ✅" if use_multi_agent else "OFF ❌"
                    send_text(bot_token, chat_id, f"Multi-agent mode: {label}", msg_id)
                    continue

                if parsed.kind == "text" and text.lower() == "/memory":
                    try:
                        from memory import get_memory_manager
                        _m = get_memory_manager(WORKSPACE_ROOT)
                        _count = _m._facts.count()
                        _chroma = "online" if _m._vectors.available else "SQLite fallback"
                        send_text(
                            bot_token,
                            chat_id,
                            f"🧠 *Memory System*\n"
                            f"Long-term facts: {_count}\n"
                            f"Vector search: {_chroma}\n"
                            f"Storage: `.ankita/memory/`",
                            msg_id,
                        )
                    except Exception as _mexc:
                        send_text(bot_token, chat_id, f"Memory status error: {_mexc}", msg_id)
                    continue

                # ----------------------------------------------------------
                # Normal message — inject memory context + route to agent
                # ----------------------------------------------------------
                media_local_file: Optional[Path] = None
                user_payload_text = text
                if parsed.kind == "text" and send_intent_path is not None:
                    last_artifact = recent_artifacts.get(chat_id, [])[-1] if recent_artifacts.get(chat_id, []) else None
                    user_payload_text = (
                        f"{text}\n\n"
                        "Telegram transport handoff contract:\n"
                        "- If you choose a file that should be sent to the user on Telegram, include:\n"
                        "  TELEGRAM_FILE: <absolute-or-workspace-relative-path>\n"
                        "- You may include multiple files via:\n"
                        "  ```telegram_send\n<path1>\n<path2>\n```\n"
                        "- Verify file paths exist on disk before emitting.\n"
                        "- IMPORTANT: Do not open files/apps for this task. Select and return file paths for Telegram delivery.\n"
                    )
                    if send_intent_path == "__LAST_ARTIFACT__" and last_artifact:
                        user_payload_text += f"\nKnown recent artifact: {last_artifact}\n"
                    if send_intent_path == "__DOWNLOADS_RANDOM__":
                        user_payload_text += "\nUser asked for a random file from Downloads. Use FileAgent/System/Terminal tools to pick one safely.\n"
                    if send_intent_path == "__AGENT_PICK__":
                        user_payload_text += (
                            "\nUser asked to send file/image from their PC to Telegram. "
                            "Pick an appropriate file path (prefer image if requested) and emit TELEGRAM_FILE directive.\n"
                        )
                if parsed.kind in {"photo", "document", "voice"}:
                    if not media_enabled:
                        send_text(bot_token, chat_id, "Media handling is disabled right now.", msg_id)
                        continue
                    if parsed.file_size > max_file_bytes:
                        send_text(
                            bot_token,
                            chat_id,
                            f"File is too large ({parsed.file_size / (1024*1024):.1f} MB). Max allowed is {max_file_mb} MB.",
                            msg_id,
                        )
                        continue
                    try:
                        meta = get_file_metadata(bot_token, parsed.file_id)
                        tg_path = str(meta.get("file_path", "")).strip()
                        if not tg_path:
                            raise RuntimeError("file_path missing from Telegram getFile response")
                        suffix = Path(parsed.file_name or tg_path).suffix or ".bin"
                        local_name = f"{chat_id}_{msg_id}_{uuid.uuid4().hex[:8]}{suffix}"
                        media_local_file = inbox_dir / local_name
                        download_file(bot_token, tg_path, media_local_file)
                        # Transcribe voice/audio messages
                        _voice_transcript = ""
                        if parsed.kind == "voice":
                            try:
                                from tools.voice_ops import transcribe_audio
                                stt = transcribe_audio(media_local_file)
                                if stt.get("ok"):
                                    _voice_transcript = stt["text"]
                                    _lang = stt.get("language", "")
                                    print(f"[voice-stt] lang={_lang} len={len(_voice_transcript)}")
                                else:
                                    print(f"[voice-stt-error] {stt.get('error')}")
                            except Exception as stt_err:
                                print(f"[voice-stt-error] {stt_err}")
                        user_payload_text = _build_media_prompt(parsed, media_local_file, transcript=_voice_transcript)
                        if parsed.kind == "photo":
                            vision_summary = _vision_analyze_image(runtime, media_local_file, parsed.caption)
                            if vision_summary:
                                user_payload_text += (
                                    "\n\nVision pre-analysis (for agent coordination):\n"
                                    f"{vision_summary}"
                                )
                    except Exception as err:
                        if reactions_enabled:
                            try:
                                emoji = choose_reaction_with_llm(runtime, parsed, processing_state="", result_state="recoverable_failure")
                                if emoji:
                                    send_reaction(bot_token, chat_id, msg_id, emoji)
                            except Exception:
                                pass
                        send_text(bot_token, chat_id, f"I couldn't process that media file: {err}", msg_id)
                        continue

                try:
                    tg_api(bot_token, "sendChatAction",
                           {"chat_id": chat_id, "action": "typing"}, timeout=20)
                except Exception:
                    pass

                # Memory injection is handled by orchestrator's _inject_memory()
                # Removed duplicate injection here to avoid polluting history with system messages

                # Build per-chat send_fn — called by drone when reply is ready
                _chat_id_for_drone = chat_id
                _session_id_for_drone = session_id
                _msg_id_for_drone = msg_id

                _sm_for_drone = None

                def _drone_reply(
                    note: str,
                    _cid: int = _chat_id_for_drone,
                ) -> None:
                    """Called from drone thread when reply is ready — sends to Telegram."""
                    if not note:
                        return
                    # Save assistant reply to shared memory
                    try:
                        from memory import get_memory_manager
                        get_memory_manager(WORKSPACE_ROOT).save("assistant", note, interface="telegram")
                    except Exception:
                        pass
                    try:
                        clean_note, directive_paths, notify_msgs = _extract_send_directives(note)
                        if clean_note:
                            send_text(bot_token, _cid, clean_note)
                        for nm in notify_msgs:
                            try:
                                send_text(bot_token, _cid, nm)
                            except Exception:
                                pass
                        found_paths = directive_paths or _extract_candidate_paths(note)
                        if not found_paths and send_intent_path is not None:
                            # Recovery: if agent mentioned a filename (e.g., "Opened random image: photo_x.jpg"),
                            # resolve it to a real path and still deliver to Telegram.
                            for fname in _extract_mentioned_filenames(note):
                                resolved = _resolve_file_by_name(fname)
                                if resolved:
                                    found_paths.append(resolved)
                                    break
                        if found_paths:
                            existing = recent_artifacts.setdefault(_cid, [])
                            for p in found_paths:
                                existing.append(p)
                                try:
                                    send_file_auto(bot_token, _cid, p, caption=f"📎 Generated file: {p.name}")
                                except Exception as send_err:
                                    print(f"[artifact-send-error] {send_err}")
                            recent_artifacts[_cid] = existing[-10:]
                        elif send_intent_path is not None:
                            send_text(
                                bot_token,
                                _cid,
                                "I couldn't resolve a sendable file path yet. Please give a direct path or ask: `/sendfile <path>`.",
                            )
                        if reactions_enabled:
                            try:
                                emoji = choose_reaction_with_llm(runtime, parsed, processing_state="", result_state="success")
                                if emoji:
                                    send_reaction(bot_token, _cid, msg_id, emoji)
                            except Exception:
                                pass
                    except Exception as err:
                        print(f"[drone-reply-error] {err}")


                try:
                    if reactions_enabled:
                        try:
                            emoji = choose_reaction_with_llm(runtime, parsed, processing_state="start", result_state="")
                            if emoji:
                                send_reaction(bot_token, chat_id, msg_id, emoji)
                        except Exception:
                            pass
                    ack = hive.delegate(user_payload_text, sessions[chat_id], send_fn=_drone_reply)
                except Exception as err:
                    if reactions_enabled:
                        try:
                            emoji = choose_reaction_with_llm(runtime, parsed, processing_state="", result_state="hard_failure")
                            if emoji:
                                send_reaction(bot_token, chat_id, msg_id, emoji)
                        except Exception:
                            pass
                    send_text(bot_token, chat_id, f"⚠️ Error: {err}", msg_id)
                    continue

                # For heavy tasks: send the "Started 🐝" acknowledgement immediately
                # For normal tasks: ack is "" — _drone_reply delivers the real reply async
                if ack:
                    clean_ack, directive_paths, notify_msgs = _extract_send_directives(ack)
                    if clean_ack:
                        send_text(bot_token, chat_id, clean_ack, msg_id)
                    for nm in notify_msgs:
                        try:
                            send_text(bot_token, chat_id, nm)
                        except Exception:
                            pass
                    if directive_paths:
                        existing = recent_artifacts.setdefault(chat_id, [])
                        for p in directive_paths:
                            existing.append(p)
                            try:
                                send_file_auto(bot_token, chat_id, p, caption=f"📎 Generated file: {p.name}")
                            except Exception as send_err:
                                print(f"[ack-artifact-send-error] {send_err}")
                        recent_artifacts[chat_id] = existing[-10:]

        except KeyboardInterrupt:
            print("\nStopping Telegram bot bridge.")
            break
        except Exception as err:
            print(f"[telegram-error] {err}")
            time.sleep(2.0)

    proactive.stop()
    watchdog_mgr.stop_all()
    if runner is not None:
        runner.stop()


if __name__ == "__main__":
    main()
