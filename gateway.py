import os

from dotenv import load_dotenv

import chat
import telegram_bot


def _select_mode() -> str:
    mode = os.getenv("GATEWAY_MODE", "").strip().lower()
    if mode in {"chat", "telegram"}:
        return mode
    if os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        return "telegram"
    return "chat"


def main() -> None:
    load_dotenv()
    mode = _select_mode()
    print(f"ANKITA Gateway mode: {mode}")
    if mode == "telegram":
        telegram_bot.main()
        return
    chat.main()


if __name__ == "__main__":
    main()

