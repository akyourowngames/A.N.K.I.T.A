"""
Telegram bridge for A.N.K.I.T.A.

OpenClaw-style channel adapter — reuses the same agent runtime as gui.py and
chat.py, now upgraded with:
  - Multi-agent Orchestrator (Supervisor → Specialists → Synthesizer)
  - Vector memory (ChromaDB) per Telegram chat
  - ProactiveEngine — DreamState epiphanies and ContentAgent raw_ideas events
    are automatically pushed to the Telegram chat that triggered them (or the
    first allowed chat if no interaction has occurred yet)
  - Commands: /start, /help, /reset, /agents on|off, /memory
"""
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests
from dotenv import load_dotenv

from agent_runtime import AgentRuntime, new_session
from agents import Orchestrator
from corn import CornRunner
from llm import build_runtime_from_env
from memory import MemoryStore
from proactive import ProactiveEngine

WORKSPACE_ROOT = Path.cwd().resolve()
STATE_DIR = Path(".ankita") / "telegram"
OFFSET_FILE = STATE_DIR / "update-offset.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

    # Vector memory (shared across all Telegram chats — scoped by session_id per chat)
    memory = MemoryStore(workspace_root=WORKSPACE_ROOT)

    # Corn scheduler
    runner: Optional[CornRunner] = None
    if _env_bool("CORN_AUTO_RUN", True):
        runner = CornRunner(
            workspace_root=WORKSPACE_ROOT,
            poll_interval_sec=float(os.getenv("CORN_POLL_INTERVAL_SEC", "5")),
            max_jobs_per_tick=int(os.getenv("CORN_MAX_JOBS_PER_TICK", "5")),
        )
        runner.start()

    # Proactive engine — memory session id will be updated to the real per-chat
    # session id as soon as the first message arrives (see set_last_interaction below).
    proactive = ProactiveEngine(workspace_root=WORKSPACE_ROOT)
    proactive.attach_memory(memory, "telegram-session")  # placeholder; updated on first message
    proactive.attach_runtime(runtime)  # Required for Sentinel (idle screen-watch) to function
    proactive.start()

    # Per-chat state
    sessions: Dict[int, List[Dict[str, Any]]] = {}   # chat_id → message history
    last_active_chat_id: Optional[int] = None        # for routing proactive events

    offset = read_offset()
    poll_timeout = max(5, min(int(os.getenv("TELEGRAM_POLL_TIMEOUT", "5")), 120))
    idle_sleep = max(0.2, min(float(os.getenv("TELEGRAM_IDLE_SLEEP_SEC", "0.5")), 3.0))
    # How often (seconds) to check the proactive queue between Telegram polls
    proactive_check_interval = float(os.getenv("TELEGRAM_PROACTIVE_CHECK_SEC", "5"))
    _last_proactive_check = time.time()

    print("╔══════════════════════════════════════╗")
    print("║   A.N.K.I.T.A Telegram Bridge ACTIVE ║")
    print("╚══════════════════════════════════════╝")
    print(f"  Provider    : {runtime.provider}")
    print(f"  Model       : {runtime.model}")
    print(f"  Multi-agent : {'ON' if use_multi_agent else 'OFF'}")
    print(f"  Memory      : {'ON (ChromaDB)' if memory.enabled else 'OFF'}")
    print(f"  Proactive   : ON (DreamState + ContentAgent)")
    print(f"  Scheduler   : {'ON' if runner is not None else 'OFF'}")
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
            # ---- DreamState epiphany ----------------------------------------
            if event.kind == "dream_epiphany":
                epiphany_text = event.data.get("text", event.message)
                if not epiphany_text:
                    continue
                try:
                    send_text(bot_token, target_chat, f"💭 {epiphany_text}")
                    memory.add("telegram-session", "assistant", epiphany_text)
                except Exception as err:
                    print(f"[proactive-dream-send-error] {err}")
                continue

            # ---- ContentAgent raw_ideas request ------------------------------
            if event.kind == "content_request":
                suggested_prompt = event.data.get("suggested_prompt", "")
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
                    memory.add("telegram-session", "assistant", content_reply or "")
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

            # ---- All other proactive events (system alerts, cron, drop_file) -
            try:
                send_text(bot_token, target_chat, f"⚙️ {event.message}")
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
                text = str(msg.get("text", "")).strip()
                if not text:
                    continue

                chat = msg.get("chat") or {}
                chat_id = int(chat.get("id", 0))
                msg_id = int(msg.get("message_id", 0))

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
                    sessions[chat_id] = new_session()

                # Update proactive engine to use this chat's real session_id
                # so DreamAgent searches the correct ChromaDB memories
                proactive.attach_memory(memory, session_id)

                # Reset idle tracker so DreamState doesn't fire while user is chatting
                proactive.set_last_interaction()

                # ----------------------------------------------------------
                # Commands
                # ----------------------------------------------------------
                if text.lower() in {"/start", "/help"}:
                    send_text(
                        bot_token,
                        chat_id,
                        (
                            "🤖 *A.N.K.I.T.A* is online.\n\n"
                            "Commands:\n"
                            "/reset — clear chat memory\n"
                            "/memory — show recent relevant memories\n"
                            "/agents on — enable multi-agent mode\n"
                            "/agents off — disable multi-agent mode\n\n"
                            "Then just send normal prompts!"
                        ),
                        msg_id,
                    )
                    continue

                if text.lower() == "/reset":
                    sessions[chat_id] = new_session()
                    send_text(bot_token, chat_id, "✅ Conversation reset.", msg_id)
                    continue

                if text.lower() in {"/agents on", "/agents off"}:
                    use_multi_agent = text.lower() == "/agents on"
                    label = "ON ✅" if use_multi_agent else "OFF ❌"
                    send_text(bot_token, chat_id, f"Multi-agent mode: {label}", msg_id)
                    continue

                if text.lower() == "/memory":
                    hits = memory.search(text, n=5, session_id=session_id)
                    if hits:
                        lines = ["🧠 Recent relevant memories:"]
                        for h in hits:
                            role = h.get("meta", {}).get("role", "?")
                            snippet = h.get("text", "")[:120]
                            lines.append(f"  [{role}] {snippet}")
                        send_text(bot_token, chat_id, "\n".join(lines), msg_id)
                    else:
                        send_text(bot_token, chat_id, "No memories found yet.", msg_id)
                    continue

                # ----------------------------------------------------------
                # Normal message — inject memory context + route to agent
                # ----------------------------------------------------------
                try:
                    tg_api(bot_token, "sendChatAction",
                           {"chat_id": chat_id, "action": "typing"}, timeout=20)
                except Exception:
                    pass

                # Inject relevant memories as context
                mem_context = memory.format_memory_context(text, n=4)
                if mem_context:
                    sessions[chat_id].append({"role": "system", "content": mem_context})

                try:
                    if use_multi_agent:
                        reply = orchestrator.run(
                            user_text=text,
                            messages=sessions[chat_id],
                        )
                    else:
                        reply = agent.process_user_text(
                            user_text=text,
                            messages=sessions[chat_id],
                        )
                except Exception as err:
                    send_text(bot_token, chat_id, f"⚠️ Error: {err}", msg_id)
                    continue

                # Store in vector memory BEFORE sending (so memory is always saved
                # even if the Telegram send fails)
                print(f"[telegram] Saving to memory: session={session_id}", flush=True)
                memory.add(session_id, "user", text)
                memory.add(session_id, "assistant", reply or "")

                send_text(bot_token, chat_id, reply or "(empty response)", msg_id)

        except KeyboardInterrupt:
            print("\nStopping Telegram bot bridge.")
            break
        except Exception as err:
            print(f"[telegram-error] {err}")
            time.sleep(2.0)

    proactive.stop()
    if runner is not None:
        runner.stop()


if __name__ == "__main__":
    main()
