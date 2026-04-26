# JAKATA

Personal AI assistant with foreground chat, live memory, voice I/O, and OS automation.

JAKATA now supports:

- normal multi-turn chat
- proactive companion thoughts in the web app, with durable feedback so JAKATA learns which styles to repeat or avoid
- foreground task execution with persisted task records
- dynamic multi-agent orchestration (planner, researcher, executor, verifier)
- self-healing verify-and-repair loops
- permanent memory plus a live memory graph
- goal-oriented `os_agent` automation
- goal-oriented `coding_agent` automation for repo edits, terminal commands, tests, online lookup, screenshots, and opening results
- local document creation and editing for DOCX/PDF reports, researched documents, templates, conversion, extraction, and PDF page operations
- Tavily web search, OpenWeather, Google Calendar, Gmail, datetime, files, and OS surfaces
- live webcam preview plus NVIDIA vision analysis from the CLI
- Telegram long-polling access with guest chat, password unlock, task details, approvals, files, reports, uploads, and image generation

## Model setup

The default split is:

- chat and normal tool routing: NVIDIA OpenAI-compatible models from `.env`
- browser and OS automation reasoning: NVIDIA models by default, with optional Codex CLI fallback if you choose it

Automation stays local and uses JAKATA's own OS surfaces instead of an external computer-use API branch.

## Prompt files

JAKATA's core model instructions live in root-level Markdown files under `prompts/` instead of being embedded directly in Python. This keeps routing, OS-agent, verifier, Telegram guest, and vision prompts editable without changing runtime code.

Set `JAKATA_PROMPTS_DIR=prompts` to use the repo defaults, or point it at another prompt folder with the same relative file names.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Set `NVIDIA_API_KEY` in `.env`, then run:

```powershell
python main.py
```

If you forget to activate the virtualenv first, `main.py` will automatically re-launch itself with the local `.venv` when that interpreter exists.

## Web App

JAKATA now serves the imported JARVIS-style frontend from the root-level `frontend/` directory:

```powershell
python main.py web --host 127.0.0.1 --port 8000
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The web app includes:

- the imported JARVIS UI served directly from `frontend/`
- streamed SSE chat over `/chat/stream`, `/chat/realtime/stream`, and `/chat/jarvis/stream`
- browser-session isolation through `session_id`
- health checks at `/health`

## Telegram Bot

Run the public Telegram bridge with long polling:

```powershell
python main.py telegram
```

Set these values in `.env` first:

- `JAKATA_TELEGRAM_BOT_TOKEN`
- `JAKATA_TELEGRAM_ADMIN_PASSWORD` or `JAKATA_TELEGRAM_ADMIN_PASSWORD_HASH`
- `JAKATA_TELEGRAM_SESSION_TTL_MINUTES=720`
- `JAKATA_TELEGRAM_GUEST_DAILY_LIMIT=50`
- `JAKATA_TELEGRAM_MAX_UPLOAD_MB=45`
- `NVIDIA_IMAGE_MODEL=flux.2-klein-4b`
- `JAKATA_IMAGE_OUTPUT_DIR=data/generated/images`
- `JAKATA_DOCUMENT_OUTPUT_DIR=data/generated/documents`
- `JAKATA_DOCUMENT_TEMPLATE_DIR=data/document_templates`

Anyone can send basic guest chat messages. Private control requires `/unlock <password>` and expires by timeout.
After unlock, normal Telegram messages use the same JAKATA agent path as CLI: chat, memory, terminal, files, browser, system, camera, web, and coding tools route through the normal planner. Work stays in the foreground task flow.

Admin task and control commands:

- `/start`, `/help`, `/commands`, `/admin`
- `/task <goal>`, `/tasks`, `/details <task_id>`, `/approve <id>`, `/deny <id>`, `/cancel <task_id>`
- `/screen`, `/lock`

Admin artifact commands:

- `/sendfile <path>`, `/senddir <path>`, `/ls <path>`, `/findfile <query>`
- `/outputs`, `/download <artifact_id>`
- `/report <task_id>`, `/export <task_id> md|json|zip`, `/logs <task_id>`
- upload a Telegram document/photo to save it under `data/telegram/uploads/<telegram_user_id>/`
- `/put <artifact_or_upload_id> <pc_path>`
- `/img <prompt>` sends a photo preview, `/imgfile <prompt>` sends the generated image as a document
- normal unlocked Telegram chat can also route through `telegram_send` for requests like "send me this file", "send the cat image here", or "send me the latest generated image"

Normal unlocked Telegram chat uses direct foreground agent execution like CLI. Explicit `/task` commands use the task completion loop. Approval is policy-driven for guarded desktop actions, but terminal tools (`shell`, `read_file`, `list_dir`, `search_files`, `write_file`, `open_path`) are not blacklisted or approval-gated:

- `JAKATA_APPROVAL_POLICY=auto_safe` auto-runs safe local actions and still pauses guarded destructive non-shell actions
- `JAKATA_APPROVAL_POLICY=manual` pauses all guarded desktop actions
- `JAKATA_APPROVAL_POLICY=auto` runs guarded desktop actions without approval prompts

Telegram file uploads from outside safe roots always pause for `/approve` before JAKATA sends them.

Optional local automation config:

- `JAKATA_CHROME_PATH` for a specific Chrome executable
- `JAKATA_TESSERACT_CMD` for a specific `tesseract.exe`
- `JAKATA_BROWSER_BACKEND=playwright|native|auto` to choose DOM-level browser control or native UI fallback
- `NVIDIA_VISION_MODEL` to override the camera analysis model
- `NVIDIA_VISION_FALLBACK_MODELS` for extra multimodal fallbacks
- `JAKATA_ROUTER_MODEL`, `JAKATA_ROUTER_TIMEOUT_SECONDS`, `JAKATA_ROUTER_MAX_RETRIES`, and `JAKATA_ROUTER_MAX_TOKENS` for the fast JSON planner
- `JAKATA_ROUTER_TOOL_LIMIT` and `JAKATA_ROUTER_MIN_TOOL_SCORE` for NVIDIA embedding-backed tool shortlisting
- `SARVAM_API_KEY`, `SARVAM_TTS_SPEAKER`, `SARVAM_TTS_LANGUAGE`, and `SARVAM_TTS_MODEL` for web text-to-speech
- `SARVAM_TTS_MAX_SPOKEN_CHARS` and `SARVAM_TTS_LONG_RESPONSE_PHRASES` to avoid reading long replies aloud
- `JAKATA_CAMERA_DEVICE_INDEX` for a different webcam
- `JAKATA_CAMERA_FRAME_WIDTH` / `JAKATA_CAMERA_FRAME_HEIGHT` to tune preview latency
- `JAKATA_AUTOMATION_BACKEND=codex|nvidia|auto`
- `JAKATA_AUTOMATION_MODEL=` to override the automation planner model if needed
- `JAKATA_CODEX_CLI_PATH=codex`
- `JAKATA_APPROVAL_POLICY=auto_safe|manual|auto`
- `JAKATA_COMPANION_ENABLED=true`
- `JAKATA_COMPANION_MIN_INTERVAL_SECONDS=300`
- `JAKATA_COMPANION_MAX_PER_DAY=12`
- `JAKATA_COMPANION_MIN_SCORE=0.62`
- `JAKATA_WORKSPACE_DIR=.`
- `JAKATA_PATH_SEARCH_ROOTS=` optional path-separated roots for terminal path discovery
- `JAKATA_PATH_DISCOVERY_MAX_DEPTH=6` / `JAKATA_PATH_DISCOVERY_MAX_VISITS=50000`
- `JAKATA_PATH_DISCOVERY_EXCLUDE_DIRS=` optional comma-separated dependency/cache folders to skip during fallback discovery
- `JAKATA_PROMPTS_DIR=prompts`
- `JAKATA_GOOGLE_CREDENTIALS_PATH=data/integrations/google_credentials.json`
- `JAKATA_GOOGLE_TOKEN_PATH=data/integrations/google_token.json`
- `JAKATA_TELEGRAM_SAFE_ROOTS=` optional comma-separated override for safe upload roots
- `NVIDIA_IMAGE_BASE_URL=` optional image endpoint override
- `NVIDIA_IMAGE_MODEL_NAMESPACE=black-forest-labs` for hosted NVIDIA GenAI image endpoints when the model id has no provider prefix
- `NVIDIA_IMAGE_INFER_URL=` optional full hosted image infer URL override
- `NVIDIA_IMAGE_SIZE=1024x1024`

## Current behavior

- normal multi-turn chat
- automatic companion conversation starters in the web app when the page is idle
- explicit companion feedback: more like this, good, boring, less, snooze, and stop auto
- retry with exponential backoff
- fallback across multiple NVIDIA chat models
- persistent chat archives across runs
- permanent memory extraction into SQLite
- live memory graph built from chats and task/tool events
- automatic loading of `.txt` knowledge files
- low-latency retrieval from prior chats, memories, and knowledge files
- model-driven tool use
- terminal file tools resolve missing relative paths by searching configured, workspace, user-profile, OneDrive, home, and drive roots, then verify the matched path before use
- `open_path` opens local files, folders, and URLs with the OS default app and reports launch/window evidence when Windows exposes it
- `telegram_send` prepares and sends existing files, folders, artifacts, and generated images back to the current Telegram chat
- file-backed Markdown prompts loaded from `prompts/`
- foreground tool requests are wrapped in persisted task records
- dynamic multi-agent task orchestration
- self-healing verification and repair loop
- policy-driven approval gates for OS actions with final task reports
- `os_agent` facade for desktop/browser workflows
- `coding_agent` facade for code/project work with shell, file, web-search, browser/system, screen/OCR, and verify-and-repair access
- internal browser tool for Playwright-backed Chrome navigation, history/tab control, search, result opening, page inspection, media playback checks, and wait-for-text verification
- native local mouse, keyboard, window, browser, public shell, file, open-path, OCR, and system controls
- Telegram chat delivery for files/images without opening them on the PC
- richer native controls for machine status, disk/network/environment checks, executable lookup, process lookup, terminal opening, URL opening, window move/resize/center/close, and region-based screen/OCR capture
- live webcam preview with `/camera`
- current-scene analysis through the `camera` tool and NVIDIA multimodal models
- hosted NVIDIA GenAI image generation fallback with optional open-after-save support
- Google Workspace context tools for Calendar and Gmail through local OAuth
- Tavily web search
- keyless DuckDuckGo HTML fallback when Tavily is not configured
- OpenWeather current weather lookup
- datetime lookup

## Memory layout

JAKATA now keeps memory in `data/`:

- `data/chats/` raw per-session chat logs
- `data/knowledge/` plain `.txt` files loaded on startup
- `data/memory/jakata.db` permanent extracted memory records
- `data/companion/` proactive companion messages, preferences, and feedback
- `data/integrations/` local OAuth tokens and external-service sync cache

The SQLite database now also stores:

- foreground tasks and task events
- agent runs and agent messages
- graph nodes and graph edges

## Proactive Companion

The web app can now let JAKATA speak first when the page is open and idle. This is intentionally companion-style, not calendar/productivity nagging.

- Starter generation is model-driven through `prompts/companion/starter.md`.
- Frequency, daily limits, snooze, and stop are handled as policy.
- Delivered messages and feedback are stored in `data/companion/companion.db`.
- The web UI sends explicit feedback from the buttons under each companion message.
- If you reply after a companion message, the web UI records that as implicit positive engagement.

Useful controls:

- Set `JAKATA_COMPANION_ENABLED=false` to disable by default.
- Set `JAKATA_COMPANION_MIN_INTERVAL_SECONDS` to control how often JAKATA can speak first.
- Set `JAKATA_COMPANION_MAX_PER_DAY` to cap daily companion starts.
- Use the web settings toggle or the `Stop auto` feedback button to stop it for the current session.

## Google Calendar and Gmail

JAKATA can connect to Google Workspace with the free Google APIs and a local desktop OAuth token. This gives the assistant real Calendar and Gmail context without adding phone integration.

1. Create a Google Cloud OAuth desktop client with Calendar and Gmail API access.
2. Download the OAuth client JSON and save it as `data/integrations/google_credentials.json`, or set `JAKATA_GOOGLE_CREDENTIALS_PATH` to another local path.
3. Start JAKATA and ask it to check `external_services_status`.
4. Run `google_workspace_connect` with `authorize=true` once. This opens the browser OAuth flow and saves `data/integrations/google_token.json`.

Connected tools:

- `calendar_today` reads today's Google Calendar events.
- `calendar_upcoming` reads upcoming Google Calendar events.
- `gmail_unread` reads unread Gmail message metadata.
- `gmail_search` searches Gmail with Gmail query syntax.
- `gmail_create_draft` creates a Gmail draft only when `confirm_create=true`; it never sends mail.
- `external_services_status` reports Google auth state and local sync-cache counts.

Calendar and Gmail reads are cached in `data/integrations/external_services.db` so later proactive work can reason over recent external context quickly. Sending mail is intentionally not implemented here; draft creation is the highest write level in this slice.

## CLI commands

- `/camera` open the live camera preview window
- `/camera off` close the preview window
- `/camera status` inspect live camera state
- `/camera ask <prompt>` force analysis of the current camera frame
- `/tasks` list recent tasks
- `/task <id>` inspect one task
- `/approve <id>` approve a waiting action
- `/deny <id>` deny a waiting action
- `/cancel <id>` cancel a task
- `/agents <id>` inspect orchestrator/executor/verifier runs
- `/graph <query>` inspect the live memory graph

If you restart the app with the same session id, it continues from the same conversation and still retrieves relevant older chats plus saved knowledge text.

With the preview open, prompts like `what do you see right now?` or `describe the live camera feed` will use the current webcam frame automatically.

## Notes

- OCR support uses `pytesseract` plus a local Tesseract installation.
- On Windows, `JAKATA_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` works with the standard installer path.
- The upgraded `os_agent` can now use dedicated `mouse`, `window`, `browser`, `screen`, and `system` controls for richer local automation.
