# Jarvis NIM Python Assistant

A tiny Python assistant CLI that talks to NVIDIA NIM through the OpenAI-compatible chat completions API.

This project lives at the root and stays separate from `openclaw/`.

It only tells the model about registered local tools. That keeps Jarvis from claiming broad phone, reminder, file, app, or messaging powers it does not actually have.

## Run

Interactive chat:

```powershell
python main.py
```

One-shot message:

```powershell
python main.py "say hello in one sentence"
```

Check env wiring without sending a message:

```powershell
python main.py --check-env
```

List registered tools:

```powershell
python main.py --list-tools
```

List enabled extensions:

```powershell
python main.py --list-extensions
```

Run Jarvis through Telegram without changing the CLI brain:

```powershell
python telegram_bot.py --check
python telegram_bot.py
```

Benchmark configured NIM models:

```powershell
python scripts\benchmark_nim_models.py
```

Run the live Jarvis behavior checks:

```powershell
python scripts\verify_jarvis_live.py
```

Check voice wiring and microphones:

```powershell
python main.py --check-voice
python main.py --list-mics
python main.py --voice-levels
python main.py --list-voices
```

Run live NVIDIA voice checks:

```powershell
python main.py --voice-say "Jarvis voice online."
python main.py --voice-roundtrip "Jarvis voice online for Krish"
```

Discover and benchmark the live NVIDIA model catalog:

```powershell
python scripts\benchmark_nim_models.py --discover --mode stream
```

Memory files are created automatically:

```powershell
memory\user.txt
memory\extracted.txt
memory\transcripts\YYYY-MM-DD.txt
```

## Environment

Required:

- `NVIDIA_API_KEY`
- `NVIDIA_BASE_URL`
- `NVIDIA_MODEL`

Optional:

- `NVIDIA_STREAM`
- `NIM_STREAM_MODE`
- `NIM_SYNTHETIC_CHUNK_CHARS`
- `NIM_SYNTHETIC_CHUNK_DELAY_SECONDS`
- `NVIDIA_TIMEOUT_SECONDS`
- `NVIDIA_TOOL_MODEL`
- `NVIDIA_MEMORY_MODEL`
- `NVIDIA_EMBEDDING_MODEL`
- `NIM_RETRY_ATTEMPTS`
- `NIM_RETRY_DELAY_SECONDS`
- `JARVIS_AUTO_TOOLS`
- `JARVIS_SYSTEM_PROMPT_FILE`
- `JARVIS_PERSONA_FILE`
- `JARVIS_TOOL_PROTOCOL_FILE`
- `JARVIS_TOOL_RESULTS_PROMPT_FILE`
- `TEMPERATURE`
- `MAX_TOKENS`
- `TOOL_MAX_ROUNDS`
- `TOOL_PLANNER_MAX_TOKENS`
- `TOOL_PLANNER_DESCRIPTION_CHARS`
- `TOOL_PLANNER_FIELD_DESCRIPTIONS`
- `NIM_TOOL_MODE`
- `NIM_PARALLEL_TOOL_CALLS`
- `NIM_NATIVE_PLANNER_CONFIRM`
- `NIM_NATIVE_VERIFY_NO_TOOL`
- `USER_NAME`
- `AI_NAME`
- `WEATHER_UNITS`
- `WEATHER_TIMEOUT_SECONDS`
- `WEATHER_GEOCODING_BASE_URL`
- `WEATHER_FORECAST_BASE_URL`
- `TIME_API_BASE_URL`
- `TIME_API_ZONE_PARAM`
- `TIME_API_TIMEOUT_SECONDS`
- `JARVIS_MEMORY_DIR`
- `MEMORY_CONTEXT_CHARS`
- `MEMORY_FILE_CHARS`
- `MEMORY_INCLUDE_TRANSCRIPTS`
- `MEMORY_EXTRACT_FROM_CHAT`
- `MEMORY_EXTRACT_BACKGROUND`
- `MEMORY_EXTRACT_MAX_TOKENS`
- `MEMORY_CONTEXT_PROMPT_FILE`
- `MEMORY_VECTOR_ACTIVE`
- `MEMORY_VECTOR_BACKGROUND_REINDEX`
- `MEMORY_VECTOR_QUERY_TIMEOUT_SECONDS`
- `MEMORY_VECTOR_RETRY_ATTEMPTS`
- `MEMORY_VECTOR_RETRY_DELAY_SECONDS`
- `MEMORY_VECTOR_QUERY_RETRY_ATTEMPTS`
- `MEMORY_VECTOR_CHUNK_CHARS`
- `MEMORY_VECTOR_TOP_K`
- `MEMORY_VECTOR_CONTEXT_CHARS`
- `MEMORY_VECTOR_INDEX_PATH`
- `JARVIS_MODEL_CATALOG`
- `JARVIS_TERMINAL_SHELL`
- `JARVIS_TERMINAL_TIMEOUT_SECONDS`
- `JARVIS_TERMINAL_MAX_OUTPUT_CHARS`
- `JARVIS_PATH_ALIASES_CONFIG`
- `JARVIS_LIST_DIRECTORY_LIMIT`
- `JARVIS_BROWSER_CONFIG`
- `JARVIS_BROWSER_HEADLESS`
- `JARVIS_EXTENSIONS_DIR`
- `JARVIS_ENABLED_EXTENSIONS`
- `JARVIS_DISABLED_EXTENSIONS`
- `JARVIS_SKILLS_DIR`
- `JARVIS_SKILL_CONTEXT_CHARS`
- `JARVIS_TELEGRAM_CONFIG`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHATS`
- `TELEGRAM_WEBHOOK_URL`
- `JARVIS_WEB_SEARCH_URL`
- `JARVIS_RESEARCH_CONFIG`
- `TAVILY_API_KEY`
- `JARVIS_ENTERTAINMENT_CONFIG`
- `JARVIS_ENTERTAINMENT_LIBRARY_DIR`
- `JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER`
- `JARVIS_PRODUCTIVITY_CONFIG`
- `JARVIS_PRODUCTIVITY_DRY_RUN`
- `GOOGLE_OAUTH_CLIENT_SECRETS`
- `GMAIL_TOKEN_FILE`
- `GOOGLE_CALENDAR_TOKEN_FILE`
- `JARVIS_INSTAGRAM_CONFIG`
- `INSTAGRAM_USERNAME`
- `INSTAGRAM_PASSWORD`
- `INSTAGRAM_SESSION_FILE`
- `INSTAGRAM_DRY_RUN`
- `VOICE_ENABLED`
- `VOICE_SPACE_TRIGGER`
- `VOICE_LISTEN_WAIT_TIMEOUT_SECONDS`
- `VOICE_LISTEN_AFTER_TTS_DELAY_SECONDS`
- `JARVIS_VOICE_PROFILE_FILE`
- `JARVIS_VOICE_PROFILE`
- `STT_ENABLED`
- `STT_PROVIDER`
- `STT_NVIDIA_SERVER`
- `STT_NVIDIA_FUNCTION_ID`
- `STT_NVIDIA_LANGUAGE_CODE`
- `STT_NVIDIA_STREAMING`
- `STT_NVIDIA_STREAMING_CHUNK_BYTES`
- `STT_INPUT_DEVICE`
- `STT_SAMPLE_RATE`
- `STT_START_TIMEOUT_SECONDS`
- `STT_LISTEN_MAX_SECONDS`
- `STT_POST_SPEECH_SILENCE_SECONDS`
- `STT_ENERGY_THRESHOLD`
- `STT_MIN_SPEECH_RMS`
- `STT_NOISE_SAMPLE_SECONDS`
- `STT_NOISE_MULTIPLIER`
- `STT_PREROLL_SECONDS`
- `STT_INPUT_GAIN`
- `TTS_ENABLED`
- `TTS_PROVIDER`
- `TTS_VOICE`
- `TTS_RATE`
- `TTS_VOLUME`
- `TTS_PITCH`
- `TTS_NVIDIA_SERVER`
- `TTS_NVIDIA_FUNCTION_ID`
- `TTS_NVIDIA_LANGUAGE_CODE`
- `TTS_NVIDIA_STREAMING`
- `TTS_NVIDIA_SSML`
- `TTS_VOICE_EFFECT`
- `TTS_PLAYBACK_SPEED`
- `TTS_MAX_SPEAK_CHARS`
- `TTS_SPEAK_ONESHOT`

The assistant does not invent a model if `NVIDIA_MODEL` is missing. The current `.env` decides which NIM model is used.

Model profiles live in `config/nim_models.json`; the benchmark script reads that file.

The benchmark can also discover model IDs directly from NVIDIA's `/models` endpoint and writes the latest live timing report to `config/nim_benchmark_results.json`.

For grounded tool-heavy chat, keep `NVIDIA_MODEL=mistralai/mistral-nemotron`, `NVIDIA_TOOL_MODEL=mistralai/mistral-nemotron`, `NIM_STREAM_MODE=native`, and `NIM_TOOL_MODE=json`. Earlier tiny-model latency was faster for plain greetings, but live research-agent checks showed `meta/llama-3.2-3b-instruct` ignoring the tool-result contract. `mistralai/mistral-nemotron` kept the final answer grounded while staying usable for interactive research. `NIM_RETRY_ATTEMPTS` can stay low for speed or be raised slightly when the provider is returning temporary rate-limit errors.

`JARVIS_AUTO_TOOLS` controls whether Jarvis plans local tool calls before answering. Keep it `true` when you want tools such as `run_terminal` available in chat. Set it to `false` for pure no-tool conversation.

The normal chat prompt lives in `prompts/chat_system.txt`. Jarvis's voice/persona lives in `prompts/persona.txt`. The optional tool-planner protocol lives in `prompts/tool_protocol.txt`. Tool-result answer shaping lives in `prompts/tool_results.txt`.

`NIM_STREAM_MODE` defaults to `native`: Jarvis reads NVIDIA NIM server-sent events and prints tokens as they arrive. Set `NIM_STREAM_MODE=synthetic` only if a provider endpoint is having temporary SSE trouble and you want local chunk printing after a JSON completion.

`NIM_TOOL_MODE=json` is the current low-latency default for auto tools. Jarvis asks the compact planner for tool calls first, then streams the final NIM response without attaching the whole native tool schema wall to casual chat.

`TOOL_PLANNER_DESCRIPTION_CHARS` and `TOOL_PLANNER_FIELD_DESCRIPTIONS` control how much manifest schema text is sent to the compact planner. The default keeps schemas small enough for the fast tool model while preserving tool names, required fields, types, and enums.

`NIM_TOOL_MODE=native_stream` is still available for providers that handle many native tool schemas quickly. On the current 2026-05-09 NIM route it was slower than compact JSON planning for this assistant.

`NIM_TOOL_MODE=native` is still available for non-streaming OpenAI-compatible `tool_calls`.

`NIM_PARALLEL_TOOL_CALLS=true` allows the provider to return multiple tool calls for one request when the model decides the task needs them.

`NIM_NATIVE_PLANNER_CONFIRM=true` asks the compact JSON planner to verify the tool set after native mode has already selected at least one tool. This protects multi-tool requests without replacing native tool calling.

`NIM_NATIVE_VERIFY_NO_TOOL=false` is the low-latency streaming default. Native no-tool replies print as tokens arrive. Set it to `true` only when you want an extra planner check before showing no-tool replies, accepting slower first-token time.

## Voice

Interactive chat supports voice without changing the tool registry. Press Space on an empty prompt to record one utterance from the configured microphone. Typed spaces after any character stay normal text input.

Use `/speakoff` in interactive mode to stop spoken assistant replies. Use `/speakon` to turn spoken replies back on.

STT uses NVIDIA Riva/NVCF streaming recognition by default because the current managed ASR endpoint accepts streaming calls while rejecting offline recognition for this route. Endpointing uses a local noise-floor threshold, preroll, and a short post-speech silence window so the mic stops after the user's sentence instead of waiting on room noise.

TTS uses NVIDIA Riva/NVCF streaming synthesis with the configured voice profile. Profiles live in `config/voice_profiles.json`, so the voice can be swapped without touching the chat loop. The default profile is `heavy_english_jarvis`, currently using `Magpie-Multilingual.EN-US.Jason.Neutral`.

TTS runs in a background speaker thread during interactive chat, so text streaming remains the fast path. If Space is pressed while Jarvis is still talking, the mic waits until speech output is idle plus a short cooldown before recording, which prevents Jarvis from listening to its own voice.

Long spoken replies are split before they reach NVIDIA TTS, and speech output removes raw paths/URLs so music downloads do not get read as `C colon slash...`.

## Tools

Tool definitions live in `tools/tools.json` and `extensions/*/extension.json`. The Python files only provide executor functions. To add or remove a tool from the assistant surface, edit the JSON manifest; the chat loop does not need to change.

Tool results are grounded data, not final canned replies. Jarvis sends tool results to the model and lets the model write the final sentence naturally.

Extension packs can also provide prompt fragments and `SKILL.txt` folders. Jarvis loads enabled extension prompts and skills into the system context.

Current tools:

- `calculate`
- `browser_manage`
- `browser_status`
- `calendar_api`
- `compare_text`
- `fetch_url_text`
- `document_extract_text`
- `entertainment_config`
- `entertainment_download`
- `entertainment_play`
- `entertainment_playlist`
- `entertainment_queue`
- `entertainment_search`
- `entertainment_status`
- `extract_url_content`
- `generate_uuid`
- `get_current_datetime`
- `get_file_info`
- `get_pc_status`
- `get_runtime_info`
- `get_system_info`
- `get_weather`
- `hash_text`
- `instagram_config`
- `instagram_manage`
- `instagram_status`
- `jarvis_latency_probe`
- `list_directory`
- `productivity_status`
- `productivity_config`
- `github_manage`
- `gmail_api`
- `calendar_api`
- `research_status`
- `research_config`
- `research_plan`
- `research_search`
- `research_fetch_sources`
- `research_rank_sources`
- `research_extract_claims`
- `research_verify_claims`
- `research_synthesize`
- `research_save`
- `research_watchlist`
- `research_run`
- `run_terminal`
- `run_jarvis_qa`
- `read_text_file`
- `search_text_files`
- `skill_workshop`
- `text_stats`
- `telegram_send_file`
- `telegram_session_info`
- `telegram_status`
- `transform_text`
- `list_registered_tools`
- `web_search`
- `workspace_inspect`
- `wiki_apply`
- `wiki_get`
- `wiki_lint`
- `wiki_search`
- `wiki_status`
- `memory_vector_status`
- `memory_vector_reindex`
- `memory_vector_search`

`run_terminal` is a manifest-registered local command tool. Its schema lives in `tools/tools.json`; the chat loop does not need to change when the tool is added or removed.

For GUI launch requests, `run_terminal` supports background execution so Jarvis can start a local app without waiting for the app window to close.

For local system facts such as installed Python, Node, npm, file, environment, and test state, Jarvis must use `run_terminal` before answering. For facts about the running Jarvis process itself, Jarvis must use `get_runtime_info`.

Natural local folder names are resolved through `config/path_aliases.json`, so requests such as `desktop`, `download folder`, `screenshots`, and `documents` can map to real user folders before a file tool gives up.

Directory listing output is compact by default through `JARVIS_LIST_DIRECTORY_LIMIT`, and each result includes total count plus whether the listing was truncated. Display names are normalized for the assistant response so unusual emoji/stylized filenames do not break Windows console streaming or spoken output.

## Telegram Bot

`telegram_bot.py` is a parallel Jarvis entrypoint, not a wrapper around `main.py`. It boots the same config, extension catalog, registry, memory, skills, and `chat_once(...)`, then uses Telegram polling or webhook delivery as the input/output channel.

Default personal-assistant mode is polling with shared memory:

```powershell
python telegram_bot.py --check
python telegram_bot.py
```

Settings live in `config/telegram_bot.json`. `TELEGRAM_BOT_TOKEN` supplies the bot token. `TELEGRAM_ALLOWED_CHATS` can override the config allowlist with comma-separated chat IDs; when the allowlist is empty the bot is open for development.

Each chat gets a persisted session JSON under `media/telegram/sessions/`. Uploads are saved under `media/telegram/uploads/<chat_id>/`, and file deliveries are queued under `media/telegram/downloads/outbox/` before the handler sends them through Telegram.

When Jarvis creates or locates a report, dossier, chart, document, archive, or any other requested file, the Telegram prompt tells it to call `telegram_send_file` with the real local path. The handler can send any readable local file path, including files outside the project folder, while the user-facing reply avoids exposing private paths unless you explicitly ask for them.

Voice notes are downloaded and converted through the configured `ffmpeg_command`, then transcribed with the existing NVIDIA STT path when `voice_transcription` is true. If STT is not configured, Telegram replies with that grounded reason instead of pretending it heard the message.

## Research Agent

`research-agent` is an extension-backed specialist named Jarvis Research Agent. Its tools are registered from `extensions/research-agent/extension.json`; behavior lives in `extensions/research-agent/prompts/research-agent.txt`, `extensions/research-agent/skills/research/SKILL.txt`, and `config/research_agent.json`.

The agent runs an evidence pipeline: plan, multi-query search, source fetch, source ranking, claim extraction, claim verification, evidence synthesis, dossier saving, and watchlist updates. `research_run` performs the whole local pipeline for quick briefings, while the stage tools are available for deep or audited research.

The config owns source policy, query families, provider order, quality limits, scoring weights, and research storage paths. `TAVILY_API_KEY` enables Tavily search when present; DuckDuckGo HTML search remains the fallback. Dossiers and cache files are stored under ignored `memory/research/` runtime folders.

Try:

```powershell
python main.py --message "Research AI agents from the last week. Give me top developments, confidence labels, and sources."
python main.py --message "Give me verified headlines on Israel and US diplomacy in the Middle East from the last 24 hours."
python main.py --message "Track NVIDIA AI chip news weekly and save it to my research watchlist."
```

## Browser Agent

`browser-agent` is an extension-backed specialist named Codex Browser Agent. Its tools are registered from `extensions/browser-agent/extension.json`, with settings in `config/browser_agent.json`.

The agent can open URLs, run browser searches, inspect page text, click visible text, type into page fields, press keys, save screenshots, and close its browser session. It uses Playwright with a configured Chrome or Edge executable, and its browser profile/screenshots live under `media/` by default so local browsing state is not committed.

## Entertainment Agent

`entertainment-agent` is an extension-backed specialist named Codex Entertainment Agent. Its tools are registered from `extensions/entertainment-agent/extension.json`; the chat loop does not change when the agent gains or loses tools.

The agent can search music with yt-dlp, download songs into the configured local library, play cached songs without downloading again, manage favorites/playlists in `config/entertainment_agent.json`, and control queue operations such as next, previous, stop, and clear.

Default music files and playback state live under `media/music/`, which is ignored by git. Change `library_dir` in `config/entertainment_agent.json` or set `JARVIS_ENTERTAINMENT_LIBRARY_DIR` to use another folder.

The entertainment prompt and skill explicitly treat Hindi, Haryanvi, Punjabi, Hinglish, and English requests as normal music requests. Jarvis should preserve the user's wording, search with the requested language context, and prefer the already downloaded local file when the same song is requested again.

## Productivity Agent

`productivity-agent` is an extension-backed specialist named Codex Productivity Agent. It registers GitHub, Gmail, and Google Calendar tools from `extensions/productivity-agent/extension.json`.

GitHub operations use the local authenticated `gh` CLI. `gmail_api` and `calendar_api` use OAuth-backed Google APIs for Gmail auth/list/read/send/draft and Calendar auth/list/read/create.

Google OAuth client secrets and tokens are config/env driven. Defaults point at `config/google/client_secret.json`, `media/google/gmail_token.json`, and `media/google/calendar_token.json`; token files live under ignored `media/` by default.

The agent is grounded: it should not claim private Gmail content was read or a Calendar event was created unless a tool result proves that action.

## Instagram Agent

`instagram-agent` is an extension-backed specialist named Codex Instagram Agent. Its tools are registered from `extensions/instagram-agent/extension.json`, with settings in `config/instagram_agent.json`.

The agent can check Instagram readiness, store monitored profiles, log in through a session file, inspect profiles, fetch recent posts, monitor multiple profiles, and prepare or run account actions such as photo post, like, comment, and DM. It uses `instagrapi` when installed; if that package or credentials are missing, the tool reports the missing piece instead of pretending.

Instagram sessions live under `media/instagram/session.json` by default. `INSTAGRAM_DRY_RUN=true` keeps account actions as prepared operations until you intentionally enable live behavior.

## Memory

Jarvis reads durable memory on every turn. You can write stable details directly in `memory/user.txt`; Jarvis stores extracted chat memory in `memory/extracted.txt`.

By default, active memory context includes hand-written memory and extracted facts, while raw transcripts stay archived as text files in `memory/transcripts/`. Set `MEMORY_INCLUDE_TRANSCRIPTS=true` if you want raw transcripts injected too.

The memory system does not use regex matching or keyword routing. It loads bounded context and lets the model use it as durable background.

Memory extraction uses `NVIDIA_MEMORY_MODEL` when set, then `NVIDIA_TOOL_MODEL`, then the chat model.

`memory-wiki` is an extension-backed TXT vault under `memory/wiki/`. It gives Jarvis source-backed wiki pages through `wiki_status`, `wiki_search`, `wiki_get`, `wiki_apply`, and `wiki_lint`.

Vector memory is extension-backed and uses NVIDIA NIM embeddings. The default embedding model is `nvidia/nv-embedqa-e5-v5`, chosen from the live NVIDIA model catalog because it was the fastest successful QA-style embedding in this workspace check. Override it with `NVIDIA_EMBEDDING_MODEL`.

Vector memory stores its cached index under `memory/vector/index.json`. Normal chat does not rebuild this index. Use:

```powershell
python main.py "reindex vector memory"
python main.py "search deep vector memory for my preferences"
```

`MEMORY_VECTOR_ACTIVE=false` by default so every casual message does not pay an embedding round trip. The model can still call `memory_vector_search` when semantic memory is useful, and you can set `MEMORY_VECTOR_ACTIVE=true` if you want existing-index recall injected every turn.

Vector reindex retries temporary NIM embedding throttles with `MEMORY_VECTOR_RETRY_ATTEMPTS`. Query-side retries stay off by default through `MEMORY_VECTOR_QUERY_RETRY_ATTEMPTS=0` so semantic recall does not slow normal chat when the embedding endpoint is busy.

## Skills And Extensions

Enabled extensions are loaded from `extensions/*/extension.json`. Each extension can declare tools, prompt fragments, skill roots, and env requirements.

Workspace skills live as `skills/<name>/SKILL.txt`; extension skills live under their extension folder. Use `skill_workshop` to queue or apply reusable workflow skills without changing core code.

Current bundled extensions:

- `web`
- `memory-wiki`
- `skill-workshop`
- `qa`
- `content-tools`
- `workspace`
- `diagnostics`
- `browser-agent`
- `entertainment-agent`
- `productivity-agent`
- `instagram-agent`
- `research-agent`
- `telegram-bot`
