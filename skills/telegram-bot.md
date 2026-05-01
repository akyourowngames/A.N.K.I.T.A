# Telegram Bot Bridge

Use this when sir asks to chat with JARVIS through Telegram.

Behavior:

- Run `python telegram_bot.py` to start the Telegram bridge.
- The bridge receives Telegram messages and sends them into the same local Brain.
- Use `TELEGRAM_ALLOWED_CHAT_ID` to keep the bot private to sir.
- Keep Telegram replies compact because Telegram has message-size limits.
- Do not expose bot tokens or chat ids in chat.

Setup:

- Create a bot token with BotFather.
- Add `TELEGRAM_BOT_TOKEN` to `.env`.
- Optional: add `TELEGRAM_ALLOWED_CHAT_ID` to restrict access.
