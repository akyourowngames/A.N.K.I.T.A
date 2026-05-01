from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from core.brain import Brain


API_ROOT = "https://api.telegram.org/bot{token}/{method}"
MAX_TELEGRAM_MESSAGE = 3900


class TelegramBot:
    def __init__(self, brain: Brain, token: str, allowed_chat_id: str = "") -> None:
        self.brain = brain
        self.token = token
        self.allowed_chat_id = allowed_chat_id.strip()
        self.offset = 0

    def run(self, poll_seconds: float = 1.0) -> None:
        print("Telegram bot bridge is running. Press Ctrl+C to stop.")
        while True:
            try:
                for update in self.get_updates():
                    self.handle_update(update)
            except KeyboardInterrupt:
                raise
            except Exception as error:
                print(f"Telegram polling error: {error}")
                time.sleep(max(poll_seconds, 3.0))
            time.sleep(poll_seconds)

    def get_updates(self) -> list[dict[str, Any]]:
        params = {"timeout": 25, "offset": self.offset}
        response = self._request("getUpdates", params)
        updates = response.get("result", [])
        if updates:
            self.offset = max(update["update_id"] for update in updates) + 1
        return updates

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        text = str(message.get("text") or "").strip()
        if not chat_id or not text:
            return
        if self.allowed_chat_id and chat_id != self.allowed_chat_id:
            self.send_message(chat_id, "This JARVIS bridge is private.")
            return
        if text.lower() in {"/start", "/help"}:
            self.send_message(chat_id, "JARVIS is online, sir.")
            return

        try:
            reply = self.brain.answer(text).strip() or "Done, sir."
        except Exception as error:
            reply = f"Sorry sir, Telegram bridge error: {error}"
        self.send_message(chat_id, reply)

    def send_message(self, chat_id: str, text: str) -> None:
        for chunk in split_message(text):
            self._request("sendMessage", {"chat_id": chat_id, "text": chunk})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        url = API_ROOT.format(token=self.token, method=method)
        data = urllib.parse.urlencode(params).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(request, timeout=35) as response:
            body = response.read().decode("utf-8")
        payload = json.loads(body)
        if not payload.get("ok"):
            raise RuntimeError(payload)
        return payload


def split_message(text: str) -> list[str]:
    if len(text) <= MAX_TELEGRAM_MESSAGE:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        chunks.append(remaining[:MAX_TELEGRAM_MESSAGE])
        remaining = remaining[MAX_TELEGRAM_MESSAGE:]
    return chunks


def main() -> None:
    project_root = Path(__file__).resolve().parent
    load_env(project_root / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env before running telegram_bot.py")
    allowed_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    bot = TelegramBot(Brain.create(project_root), token, allowed_chat_id)
    bot.run()


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    main()
