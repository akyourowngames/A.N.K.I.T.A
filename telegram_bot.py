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
from agents.hive import HiveMind
from corn import CornRunner
from llm import build_runtime_from_env
from memory import MemoryStore
from proactive import ProactiveEngine
from session_manager import SessionManager

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

    # Per-chat state
    sessions: Dict[int, List[Dict[str, Any]]] = {}           # chat_id → message history
    tg_session_managers: Dict[int, SessionManager] = {}      # chat_id → SessionManager
    last_active_chat_id: Optional[int] = None                # for routing proactive events

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
                epiphany_text = event.message
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

                # Ensure session exists — restore from vault if available
                if chat_id not in sessions:
                    sm = SessionManager(
                        workspace_root=WORKSPACE_ROOT / ".ankita" / "telegram" / str(chat_id),
                        runtime=runtime,
                    )
                    tg_session_managers[chat_id] = sm
                    restored = sm.load()
                    base = new_session()
                    if restored:
                        sessions[chat_id] = sm.build_restored_messages(base)
                        try:
                            send_text(
                                bot_token, chat_id,
                                f"🧠 Session restored — I remember our last {len(restored)} messages.",
                            )
                        except Exception:
                            pass
                    else:
                        sessions[chat_id] = base

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
                            "/agents off — disable multi-agent mode\n"
                            "/hive — show background task status\n"
                            "/watchdogs — show all watcher statuses\n"
                            "/github status — check GitHub token\n"
                            "/reauth github — re-authorize GitHub (device flow)\n"
                            "/feedback stats — show self-improvement stats\n"
                            "show <id> — get result of a background task\n\n"
                            "Then just send normal prompts!"
                        ),
                        msg_id,
                    )
                    continue

                if text.lower() == "/hive":
                    send_text(bot_token, chat_id, hive.list_tasks(), msg_id)
                    continue

                if text.lower() == "/watchdogs":
                    send_text(bot_token, chat_id, watchdog_mgr.status(), msg_id)
                    continue

                if text.lower() in ("/reauth github", "/reauth-github"):
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

                if text.lower() == "/github status":
                    from tools.auth_manager import github_token_status
                    send_text(bot_token, chat_id, github_token_status(), msg_id)
                    continue

                if text.lower() == "/feedback stats":
                    try:
                        send_text(bot_token, chat_id, feedback_engine.get_stats(), msg_id)
                    except Exception as _exc:
                        send_text(bot_token, chat_id, f"Error: {_exc}", msg_id)
                    continue

                if text.lower().startswith("show "):
                    task_id = text[5:].strip()
                    send_text(bot_token, chat_id, hive.get_result(task_id), msg_id)
                    continue

                if text.lower() == "/reset":
                    sessions[chat_id] = new_session()
                    if chat_id in tg_session_managers:
                        tg_session_managers[chat_id].clear()
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

                # Build per-chat send_fn — called by drone when reply is ready
                _chat_id_for_drone = chat_id
                _session_id_for_drone = session_id
                _msg_id_for_drone = msg_id

                _sm_for_drone = tg_session_managers.get(chat_id)

                def _drone_reply(
                    note: str,
                    _cid: int = _chat_id_for_drone,
                    _sid: str = _session_id_for_drone,
                    _sm: "SessionManager | None" = _sm_for_drone,
                ) -> None:
                    """Called from drone thread when reply is ready — sends to Telegram."""
                    if not note:
                        return
                    try:
                        memory.add(_sid, "assistant", note)
                        send_text(bot_token, _cid, note)
                        # ── Save to session vault + compress if needed ─────────
                        if _sm is not None:
                            _sm.add_message("assistant", note)
                            _sm.compress_if_needed()
                    except Exception as err:
                        print(f"[drone-reply-error] {err}")

                # Save user message now (reply saved in _drone_reply when it arrives)
                memory.add(session_id, "user", text)
                if chat_id in tg_session_managers:
                    tg_session_managers[chat_id].add_message("user", text)

                try:
                    ack = hive.delegate(text, sessions[chat_id], send_fn=_drone_reply)
                except Exception as err:
                    send_text(bot_token, chat_id, f"⚠️ Error: {err}", msg_id)
                    continue

                # For heavy tasks: send the "Started 🐝" acknowledgement immediately
                # For normal tasks: ack is "" — _drone_reply delivers the real reply async
                if ack:
                    send_text(bot_token, chat_id, ack, msg_id)

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
