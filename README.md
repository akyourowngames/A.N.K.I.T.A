# Zumba — Personal AI Assistant

Zumba provides chat, voice, sessions and tools through a Python CLI, a local web app and Telegram.

## Simple memory

Memory follows Jarvis's chat-log approach:

1. Save the original user and assistant messages to `~/.zumba/ChatLog.json`.
2. Keep the latest 80 messages across conversations.
3. Include recent exchanges in chronological order, labelled with speaker and sent time.
4. Give the latest user request priority over older conversation.

Saving and reading memory need no model calls, embeddings, graph extraction, inferred profiles, mood tracking, reflection or background consolidation. Writes are atomic and serialized across CLI/server processes using `ChatLog.lock`. Original messages stay intact in storage; the model receives bounded excerpts.

The current session supplies its own conversation, so cross-chat memory excludes that session. Full session transcripts and tool results are stored separately in `~/.zumba/zumba.db` for resume. Default assistant prompts do not inject old soul or profile files.

```powershell
python main.py memory stats
python main.py memory search "recent conversation"
python main.py memory add "Text to remember"
python main.py memory forget <exchange-id>
python main.py memory clear --yes
```

`search` shows recent saved messages and their exchange IDs; it does not classify meaning or rank relevance. `forget` removes both sides of an exchange from the cross-chat log. `clear` empties that log; existing sessions remain available through the session manager.

The web sidebar links to **Saved conversation** at `/memory`. Set `ZUMBA_NO_MEMORY=1` to stop automatic cross-chat saving and recall. Set `ZUMBA_MEMORY_HOME` to relocate the JSON log.

## Reset old memory and traces

Stop the app before resetting. Preview the exact local targets first:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/reset_memory.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/reset_memory.ps1 -Apply
```

The reset removes old graph memory, queued captures, derived document indexes, generated profiles, local audit logs, cached voice/web data, legacy session files and memory screenshots/test snapshots. It clears session messages, execution events and stored locations from the app database, rebuilds full-text indexes and compacts the database.

Credentials, model settings, MCP configuration and original vault documents remain. Telegram update positions are retained so cleared updates are not replayed. The script defaults to `~/.zumba`; use `-DataRoot` for a different directory. Separately configured document/location stores need their own explicit cleanup.

## Run

Python 3.11+ is required. Configure the chat provider in `.env` using `.env.example`.

```powershell
python main.py chat
python main.py ask "Hello"
python main.py sessions
python -m server.run
```

The backend listens locally on port 8000. For the Next.js frontend:

```powershell
cd frontend
npm run dev
```

Chat uses `ZUMBA_API_KEY`, `ZUMBA_BASE_URL` and `ZUMBA_MODEL`. The default provider is NVIDIA NIM. Optional document analysis uses the separate `ZUMBA_KNOWLEDGE_*` configuration.

## Desktop voice

Desktop speech recognition runs locally through faster-whisper and sounddevice. Chrome is no longer needed. A separate persistent recognition process keeps native speech libraries isolated from Qt.

```powershell
python desktop/run.py --hands-free
python desktop/mic_test.py --list-devices
python desktop/mic_test.py --file tests/fixtures/stt-six-seconds.wav --lang en
python main.py doctor
```

The voice dependencies are in `requirements-desktop.txt`. Cache the configured model once with `python desktop/mic_test.py --download-model`; recognition then works offline. Chat answers and Edge TTS still use their configured online services.

`--lang auto` (or `en`, `hi`, etc.) overrides the shared `ZUMBA_STT_LANG` setting. Use `--mic-device <id>` to select an input. `--wake-word` enables “Hey Ankita” activation using the configured chat model. `--barge-in` enables immediate microphone activity interruption; use headphones to avoid playback echo. Type `/stop` to interrupt or `/exit` to close.

The browser mic records audio for the same server recognizer: click to start, click again to finish. The server now supports real `/api/voice/stt` uploads and streamed partial transcripts. See [voice setup and checks](docs/issue-12-local-voice.md).

## Tools and sessions

- Resume conversations with `python main.py chat --last` or `--resume <id>`.
- MCP servers are configured in `~/.zumba/mcp.json`; tools also include shell, files, web, calendar and location.
- Explicit document uploads and vault queries remain available. Chat logs are never copied into the document graph.
- Explicit goal and reminder commands remain available. Chat does not run automatic goal discovery or proactive memory checks.
- Telegram supports durable tool execution, approval controls and voice input.

Use `python main.py --help` and each command's `--help` for details.
