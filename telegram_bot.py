import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv

from agent_runtime import AgentRuntime, new_session
from llm import build_runtime_from_env

WORKSPACE_ROOT = Path.cwd().resolve()
STATE_DIR = Path(".ankita") / "telegram"
OFFSET_FILE = STATE_DIR / "update-offset.json"


def read_offset() -> int:
    try:
        payload = json.loads(OFFSET_FILE.read_text(encoding="utf-8"))
        value = int(payload.get("offset", 0))
        return max(value, 0)
    except Exception:
        return 0


def write_offset(offset: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(json.dumps({"offset": int(offset)}, ensure_ascii=True, indent=2), encoding="utf-8")


def chunk_text(text: str, chunk_size: int = 3900) -> List[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
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


def send_text(token: str, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
    for chunk in chunk_text(text):
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": chunk}
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        try:
            tg_api(token, "sendMessage", payload, timeout=60)
        except Exception:
            # Retry once without reply target (some contexts reject reply links).
            payload.pop("reply_to_message_id", None)
            tg_api(token, "sendMessage", payload, timeout=60)


def parse_allowed_chat_ids(raw: str) -> set[int]:
    out: set[int] = set()
    for part in (raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            out.add(int(token))
        except ValueError:
            continue
    return out


def main() -> None:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Error: TELEGRAM_BOT_TOKEN is not set.")

    allowed_chat_ids = parse_allowed_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", ""))
    runtime = build_runtime_from_env()
    agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)
    sessions: Dict[int, List[Dict[str, Any]]] = {}
    offset = read_offset()

    poll_timeout = max(5, min(int(os.getenv("TELEGRAM_POLL_TIMEOUT", "30")), 120))
    idle_sleep = max(0.2, min(float(os.getenv("TELEGRAM_IDLE_SLEEP_SEC", "0.5")), 3.0))

    print("Telegram bot bridge started")
    print(f"Provider: {runtime.provider}")
    print(f"Model: {runtime.model}")
    print(f"Workspace: {WORKSPACE_ROOT}")

    while True:
        try:
            data = tg_api(
                token,
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
                if allowed_chat_ids and chat_id not in allowed_chat_ids:
                    allowed_preview = ",".join(str(v) for v in sorted(allowed_chat_ids))
                    send_text(
                        token,
                        chat_id,
                        f"This bot is not enabled for this chat.\nchat_id={chat_id}\nallowed={allowed_preview}",
                        msg_id,
                    )
                    continue

                if chat_id not in sessions:
                    sessions[chat_id] = new_session()

                if text.lower() in {"/start", "/help"}:
                    send_text(
                        token,
                        chat_id,
                        "ANKITA is online.\nCommands:\n/reset - clear chat memory\n/exit - no-op on Telegram\nThen send normal prompts.",
                        msg_id,
                    )
                    continue
                if text.lower() == "/reset":
                    sessions[chat_id] = new_session()
                    send_text(token, chat_id, "Conversation reset.", msg_id)
                    continue

                try:
                    tg_api(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=20)
                except Exception:
                    pass

                reply = agent.process_user_text(user_text=text, messages=sessions[chat_id])
                send_text(token, chat_id, reply or "(empty response)", msg_id)
        except KeyboardInterrupt:
            print("\nStopping Telegram bot bridge.")
            break
        except Exception as err:
            print(f"[telegram-error] {err}")
            time.sleep(2.0)


if __name__ == "__main__":
    main()
