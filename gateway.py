import os

from dotenv import load_dotenv

import chat
import gui
import telegram_bot
import voice_web


def _select_mode() -> str:
    mode = os.getenv("GATEWAY_MODE", "").strip().lower()
    if mode in {"chat", "telegram", "voice", "gui"}:
        return mode
    if os.getenv("SARVAM_API_KEY", "").strip() and os.getenv("VOICE_WEB_AUTO_SELECT", "false").strip().lower() in {"1", "true", "yes", "on"}:
        return "voice"
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
    if mode == "voice":
        voice_web.main()
        return
    if mode == "gui":
        gui.main()
        return
    chat.main()


if __name__ == "__main__":
    main()
