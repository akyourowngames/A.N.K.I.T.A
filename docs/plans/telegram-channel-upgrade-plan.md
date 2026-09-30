# Telegram channel upgrade — plan

Date: 2026-09-26. Status: implemented 2026-09-27; original proposal preserved below.
Locked scope: **progress replies** (typing + interim messages, final reply at
end) · **bot-ack reactions only** · **send-first files**.

Implementation and exact verification are recorded in
[the ledger](vault-model-selection-telegram-implementation.md). Production uses
supported 👀/👍/👎 reactions rather than the unsupported emoji proposed below.
The real configured bot completed progress, one file upload and cancellation in
the user-approved test chat; its model/engine decisions were scripted.

## 1. Current state (verified)

- `src/channels/telegram.mjs`: text in, voice-note in (Groq-transcribed),
  chunked text out, TTS voice out, single typing indicator. `updateToJob`
  drops photos/docs/video/reactions/callbacks. No `editMessageText`,
  no `sendPhoto`/`sendDocument`, no `setMessageReaction` anywhere.
- `desktop/electron/channels.mjs` `handleJob`: one `sendTyping`, then blocks
  on `waitForTurn` — engine emits `assistant-delta` / `tool-call` /
  `tool-result` (`engine.mjs`), but the channel never subscribes. Same shape
  in CLI `src/automation/daemon.mjs` `handleJob`.

## 2. What ships

### 2.1 Live progress replies

`TelegramChannel.handleJob` subscribes to the engine event bus for its turn
(`turn-start → assistant-delta → tool-call/result → turn-end`) and:

- sends the `typing` chat action on a heartbeat (every ~4s; Telegram expiry
  is ~5s),
- posts short interim replies at meaningful beats only (tool started /
  finished, approval needed) — throttled (max ~1 per 5s, text-capped) so a
  20-tool turn does not spam 40 messages,
- final answer arrives as the existing reply-to message. No
  `editMessageText` needed.
- Mirror the same hook in CLI `daemon.mjs` `handleJob` (it owns its own
  `Agent`; subscribe to its callbacks the same way).

### 2.2 Bot-ack reactions

New `TelegramBot.react(chatId, messageId, emoji)` via `setMessageReaction`:
`⏳` on receipt, `✅` on final reply, `❌` on error/timeout. Incoming
reactions are explicitly out of scope (no `message_reaction` handling;
approvals stay as `y/a/n` text).

### 2.3 Send-first files

After the text reply, push turn artifacts to chat:

- discover via existing `recentArtifacts(cwd, messages)`
  (`workspace.mjs`) — covers `generated_image`, `downloaded_image`,
  `browser_screenshot`,
- read safely via the `readGeneratedImage` containment pattern
  (`engine.mjs`: folder + mime + 15MB gate),
- new `TelegramBot.sendPhoto` / `sendDocument` (copy the `sendVoice`
  FormData template; `upload_photo` / `upload_document` chat action while
  uploading), captioned, one message per file (cap ~5/turn; the rest stay as
  workspace artifacts with paths in text).
- Receive path (photos/docs from the user) is deliberately deferred —
  `updateToJob` still returns `null` for them with a "not yet supported"
  nudge. Voice notes keep working.

### 2.4 Approval + cancel polish

Approval prompts already work (`y/a/n`); add `/cancel` mid-turn
(`engine.cancel` → `❌` reaction + "stopped" reply). Small, high-value.

## 3. Build order

1. `TelegramBot.react` + hook into `handleJob` (⏳/✅/❌) + test.
2. Progress subscription (typing heartbeat + throttled interim beats) in the
   desktop channel; mirror in daemon.
3. `sendPhoto` / `sendDocument` + artifact push after reply; caps + error
   fallback to text.
4. `/cancel`, photo/doc "coming soon" nudge, README/docs + findings update.

## 4. Verification

- Extend `test/desktop/desktop-channels.test.mjs` StubBot
  (`react` / `sendPhoto` / `sendDocument`): ack-on-receipt, interim beats
  throttled (rapid stub tool events → bounded messages), artifact push after
  text reply, cancel path. New cases must fail without the implementation
  (reproduce-then-fix).
- `updateToJob` photo/doc cases stay `null` + nudge (locks the deferred
  scope).
- Full `node --test` green; live round trip against a real test bot: long
  turn shows typing + beats + final reply; image turn delivers the file;
  reactions appear on both ends.

## 5. Risks

- Telegram rate limits on chat actions/messages — heartbeat + throttle
  values are the defense; expose as channel settings if needed.
- Interim beats duplicating the final answer — beats carry step labels
  only, never model text.
- Group topics/threads — reactions/replies already target the tracked
  `message_id`; no change.

## 6. Deliberately not in this tier

Shared multi-channel core (Discord/WhatsApp plug-in helper) — parked. When
revived, this upgrade should be retargeted at that core, guarded by per
channel `capabilities()`, so future channels inherit progress/reactions /
files for free.
