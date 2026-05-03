# Telegram Bot Bridge

Use this when sir asks to chat with JARVIS through Telegram.

Behavior:

- Run `python telegram_bot.py` to start the Telegram bridge.
- The bridge receives Telegram messages and sends them into the same local Brain.
- Use `TELEGRAM_ALLOWED_CHAT_ID` to keep the bot private to sir.
- Keep Telegram replies compact because Telegram has message-size limits.
- Prefer natural Telegram-side file work: "show desktop files", "find invoice in downloads", "send 1", "send desktop.ini", "read it", or "details for the second one".
- Slash commands still exist as a fallback, but normal chat should be enough.
- Numbered file choices are cached per chat in the running bridge, so follow-ups like "send 1" or "send me 1 file" should send the selected local file through Telegram instead of only describing it.
- Normal Telegram chat still goes through Brain, so connected tools such as web search, weather, calendar, Gmail, music, image generation, terminal-backed work, and system controls are available without special Telegram commands.
- Incoming Telegram documents, photos, voice notes, audio, video notes, and videos are downloaded into the configured Telegram download folder.
- Voice notes and audio/video attachments are transcribed locally with `faster-whisper` when installed. Leave `TELEGRAM_WHISPER_LANGUAGE` empty for automatic language detection.
- Folders are zipped automatically before upload. Respect `TELEGRAM_MAX_SEND_MB` and `TELEGRAM_MAX_BATCH_SEND`.
- Do not expose bot tokens or chat ids in chat.

Setup:

- Create a bot token with BotFather.
- Add `TELEGRAM_BOT_TOKEN` to `.env`.
- Optional: add `TELEGRAM_ALLOWED_CHAT_ID` to restrict access.
- Install free local audio transcription support with `python -m pip install faster-whisper` or `pip install -r requirements.txt`.
