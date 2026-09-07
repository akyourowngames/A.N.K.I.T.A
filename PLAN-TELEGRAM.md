# PLAN-TELEGRAM — Telegram channel for Zumba

Goal: chat with Zumba (text + voice notes) from Telegram, with full memory
integration, mirroring how Friday/Ares does it (`ares/channels/telegram.py`)
but sized to Zumba's much simpler architecture.

## What Friday does (reference design)

- **Direct Bot API over HTTPS long-polling** via `httpx` — no webhook, no
  bot framework, no public URL needed. One `getUpdates(offset)` loop.
- **Offset cursor persisted in SQLite** (`channel_cursors` table,
  `MAX()` upsert) so restarts never replay or drop messages.
- **Security = chat-ID allowlist.** Nothing is processed until the exact
  chat id is in the allowlist; unknown chats get a polite refusal.
- **Voice notes**: download via `getFile` → local **faster-whisper**
  (`small`, task=translate) → English transcript → normal chat pipeline.
  Duration cap enforced (config).
- **Chat mapping**: (channel, external_chat_id) → conversation id so
  history survives across restarts.
- **Message splitting** to Telegram's 4096-char limit; typing indicator
  (`sendChatAction`) while thinking; attachment handling.

## What Zumba already has (don't rebuild)

| Need | Existing piece |
|---|---|
| Chat brain | `server/app.py` `/api/chat` (uses `_recall_block()`) |
| Memory read | `memory.get_memory().recall(query, top_k, max_bytes)` |
| Memory write | `mem.capture_async(user_text, reply, session_id=...)` |
| Voice → text | `POST /api/voice/stt` (frontend webm/opus upload) |
| Text → voice | `POST /api/voice/tts` (edge-tts, returns mp3 bytes) |
| Sessions | `core/store.py` sessions (id, model, messages) |
| Config | `.env` loader in `core/config.py` |

## Architecture decision

Run Telegram as an **in-process background task inside the existing FastAPI
server**, not a separate process. Zumba's chat endpoint is a plain function
call internally (`_build_messages` + `api_client` + capture), so the channel
can call the same internal helpers directly — no HTTP self-calls.

New modules: `server/telegram_channel.py` (+ `server/channel_store.py` for
the cursor, `server/tts.py` shared TTS helper). Estimated ~400 lines —
Friday's is 2295 because it also routes skills, multi-agent, watchers and
medical flows; Zumba only needs chat + voice.

## Config (add to `.env.example`)

```
ZUMBA_TG_BOT_TOKEN=          # from @BotFather
ZUMBA_TG_ALLOWED_CHAT_IDS=   # comma-separated numeric chat ids; empty = nobody
ZUMBA_TG_VOICE_REPLY=1       # reply with voice (edge-tts) when user sent voice
```

Token + allowlist read via env. Token never logged. `/start` from an unknown
chat replies with the chat id and a hint to add it to `.env` — that's the
## Milestones

### M1 — Skeleton, polling, security (text only)
1. `server/channel_store.py`: SQLite in `~/.zumba/memory.db` (reuse existing
   connection helper):
   - `channel_cursors(channel TEXT PRIMARY KEY, next_offset INTEGER,
     updated_at)` — copy Friday's `MAX()` upsert semantics exactly.
   - `channel_map(channel, external_chat_id, session_id)` — chat → session.
2. `server/telegram_channel.py`:
   - `TelegramAPI` thin wrapper: `get_updates`, `send_message`, `get_file`,
     `send_chat_action` (httpx, ~60 lines).
   - `TelegramChannel.run()`: asyncio long-poll loop (timeout 30s), persist
     offset per Friday's pattern (`MAX()` upsert means no replays on restart).
   - Allowlist gate on every update; log-and-ignore non-allowed chats.
   - Text messages → resolve session via `channel_map` (auto-create
     `tg-<chat_id>` on first message) → **refactor** `_build_messages()` +
     `_recall_block()` from `app.py` into a shared
     `core/chat_pipeline.answer(session_id, text)` helper so HTTP and
     Telegram share one code path — do not duplicate recall injection.
   - Reply: split at 4096 chars on newlines; send `typing` action before
     the LLM call.
3. Memory: after each reply, `mem.capture_async(user_text, reply,
   session_id=f"tg-{chat_id}", kind="chat")` — exactly like `main.py:290`.
   Telegram conversations become memory episodes like CLI ones.
4. Startup: in `run.py`, spawn the channel as an asyncio task if
   `ZUMBA_TG_BOT_TOKEN` is set; channel crash must not kill the API (wrap
   loop, backoff on 429/5xx respecting `retry_after`).
5. Commands (minimal): `/new` (fresh session for that chat), `/help`.
   Skip Friday's `/model /provider /watchers …` zoo.

**Deliverable:** text chat on Telegram with memory recall + capture working.

### M2 — Voice notes in (STT)
1. On `message.voice` / `message.audio`: download via `get_file` to
   `~/.zumba/tg_audio/<msg_id>.ogg`.
2. Transcribe reusing Friday's proven approach: local **faster-whisper**
   (`small`, task=`translate` for Hinglish→English — this machine already
   ran it fine for Ares). Add `faster-whisper` to
   `server/requirements.txt`; lazy-load behind an asyncio lock (copy the
   structure of `ares/channels/audio.py::EnglishAudioTranscriber`).
3. Duration cap (config, default 5 min) → friendly error reply.
4. Pipeline the transcript through the same text path as M1. Memory sees
   plain text, same as typed messages.

### M3 — Voice replies out (TTS)
1. If the incoming message was a voice note and `ZUMBA_TG_VOICE_REPLY=1`:
   extract the edge-tts logic from `app.py` `/api/voice/tts` into
   `server/tts.py` so endpoints and channel share it. `_tts_short_text`
   already trims to 280 chars — right for voice.
2. Send as `sendVoice` (multipart mp3 upload) **plus** the full text reply
   as a message (voice alone loses detail).
3. `record_voice` chat action while generating.

### M4 — Polish
- Markdown scrubbing: plain text first (parse_mode omitted), HTML later.
- Per-chat rate limiting (simple token bucket).
- `/memory` command → shows recall for the user's last message (CLI `/why`).
- Graceful shutdown: cancel loop, `mem.flush()` on exit.
- Tests: `tests/test_telegram_channel.py` with a mocked `TelegramAPI`:
  offset persistence, allowlist rejection, 4096 splitting, chat→session
  mapping, voice duration cap.

## Non-goals (explicitly)
- Webhook mode (needs public TLS; long-polling is correct for localhost).
- Attachments/documents (later; needs an `inspect_attachment` equivalent).
- Group chats (single-user personal bot; allowlist one chat id).
- Friday's marketplace/skills/multi-agent Telegram surfaces.

## Risks
- **faster-whisper model download** (~500MB): first voice msg slow; preload
  at server start when `ZUMBA_TG_BOT_TOKEN` is set.
- **Kilo free-tier latency**: send typing action immediately; 10s
  "still working…" nudge for long turns.
- **Blocking the event loop**: `api_client` is sync httpx → wrap LLM calls
  in `asyncio.to_thread` so the web API stays responsive.
- Token security: `.env` only; `.env` already gitignored.

## Effort estimate
M1 ~1 session, M2 ~0.5, M3 ~0.5, M4 ~0.5. Total ≈ one focused day.

onboarding path (Friday's allowlist UX, minus config-file rewriting).
