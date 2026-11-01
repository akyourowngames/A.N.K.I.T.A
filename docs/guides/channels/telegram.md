# Telegram

1. Create a bot with [BotFather](https://t.me/BotFather), then open its private
   conversation and send Start. Keep the token private.
2. In Ankita **Settings → Channels → Telegram**, enter the token and select a
   teammate. Use Test connection to check its identity.
3. Add your numeric private chat ID under Allowed chat IDs. Set Owner private
   conversation to that same positive ID. Owner user ID is optional for a
   Telegram private chat because its user and chat IDs match.
4. Enable the channel and save. Send a short request to your bot.

Group IDs are often negative. Add a group explicitly and mention the bot in each
request. Keep BotFather's privacy mode unless you deliberately want broader
group delivery; platform privacy mode can suppress messages before Ankita sees
them. Approvals always go to a configured positive private owner destination,
never a group. If no owner is set, the first positive allowed private chat is
the compatibility fallback. Unknown senders are silently denied by the shared
core; do not depend on an unauthorized chat getting an ID hint.

For local config: `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`TELEGRAM_ALLOWED_CHAT_IDS`, `TELEGRAM_VOICE_REPLY` and
`TELEGRAM_CONFIRM_TIMEOUT`. Explicit saved settings win over environment values,
including an explicitly cleared token. The unattended daemon retains legacy
token-based activation only when no saved enabled/disabled choice exists.

Telegram sends typing, received/complete reactions, bounded tool progress and
generated/downloaded image attachments. Voice-note input retains the existing
Groq transcription setup and local ffmpeg requirement. Optional spoken replies
retain the existing channel speech providers; they are not the desktop voice
session. Non-voice incoming attachments get an unsupported-media reply.

Use `y`, `a` or `n` in the owner's private conversation for permission. `/cancel`
stops the owned request immediately. Bot-authored messages do not run work.

Only one poller should use the token. A rejected token is shown as a connection
error. On first connection without a saved cursor, the historical Telegram
startup behavior drains old pending updates; do not send your acceptance request
until the connection reports ready.

Official protocol: [Bot API](https://core.telegram.org/bots/api).
Shared access/recovery rules: [Channels](../channels.md).
External acceptance, when an explicit test chat is approved:

```text
node scripts/verify-telegram-upgrade.mjs <approved-private-chat-id>
```

This sends real messages and a sample image. It was not rerun against a user's
account during the multi-channel build; the new local HTTP checks are distinct
from earlier live Telegram evidence.
