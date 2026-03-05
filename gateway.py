import os
import sys

# Ensure stdout/stderr use UTF-8 on Windows (cp1252 can't encode emoji)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv


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
        import telegram_bot  # lazy import — avoids loading PyQt6/gui/voice_web unnecessarily
        telegram_bot.main()
        return
    if mode == "voice":
        import voice_web  # lazy import
        voice_web.main()
        return
    if mode == "gui":
        import gui  # lazy import — PyQt6 only loaded when actually needed
        gui.main()
        return
    import chat  # lazy import
    chat.main()


if __name__ == "__main__":
    main()
