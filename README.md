# JAKATA

Personal AI assistant with foreground chat, explicit background task execution, live memory, and OS automation.

JAKATA now supports:

- normal multi-turn chat
- long-running background tasks with persisted task state
- dynamic multi-agent orchestration (planner, researcher, executor, verifier)
- self-healing verify-and-repair loops
- permanent memory plus a live memory graph
- goal-oriented `os_agent` automation
- Tavily web search, OpenWeather, datetime, files, and OS surfaces
- live webcam preview plus NVIDIA vision analysis from the CLI
- Telegram long-polling access with guest chat, password unlock, task details, approvals, files, reports, uploads, and image generation

## Model setup

The default split is:

- chat and normal tool routing: NVIDIA OpenAI-compatible models from `.env`
- browser and OS automation reasoning: NVIDIA models by default, with optional Codex CLI fallback if you choose it

Automation stays local and uses JAKATA's own OS surfaces instead of an external computer-use API branch.

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

Anyone can send basic guest chat messages. Private control requires `/unlock <password>` and expires by timeout.

Admin task and control commands:

- `/start`, `/help`, `/commands`, `/admin`
- `/task <goal>`, `/tasks`, `/details <task_id>`, `/approve <id>`, `/deny <id>`, `/cancel <task_id>`
- `/screen`, `/kill`, `/unkill`, `/lock`

Admin artifact commands:

- `/sendfile <path>`, `/senddir <path>`, `/ls <path>`, `/findfile <query>`
- `/outputs`, `/download <artifact_id>`
- `/report <task_id>`, `/export <task_id> md|json|zip`, `/logs <task_id>`
- upload a Telegram document/photo to save it under `data/telegram/uploads/<telegram_user_id>/`
- `/put <artifact_or_upload_id> <pc_path>`
- `/img <prompt>` sends a photo preview, `/imgfile <prompt>` sends the generated image as a document

All tool-driven admin work goes through the task completion loop. Approval is now policy-driven:

- `JAKATA_APPROVAL_POLICY=auto_safe` auto-runs safe local actions and still pauses destructive ones
- `JAKATA_APPROVAL_POLICY=manual` pauses all guarded desktop actions
- `JAKATA_APPROVAL_POLICY=auto` runs guarded desktop actions without approval prompts

Telegram file uploads from outside safe roots always pause for `/approve` before JAKATA sends them.

Optional local automation config:

- `JAKATA_CHROME_PATH` for a specific Chrome executable
- `JAKATA_TESSERACT_CMD` for a specific `tesseract.exe`
- `JAKATA_BROWSER_BACKEND=playwright|native|auto` to choose DOM-level browser control or native UI fallback
- `NVIDIA_VISION_MODEL` to override the camera analysis model
- `NVIDIA_VISION_FALLBACK_MODELS` for extra multimodal fallbacks
- `JAKATA_CAMERA_DEVICE_INDEX` for a different webcam
- `JAKATA_CAMERA_FRAME_WIDTH` / `JAKATA_CAMERA_FRAME_HEIGHT` to tune preview latency
- `JAKATA_AUTOMATION_BACKEND=codex|nvidia|auto`
- `JAKATA_AUTOMATION_MODEL=` to override the automation planner model if needed
- `JAKATA_CODEX_CLI_PATH=codex`
- `JAKATA_APPROVAL_POLICY=auto_safe|manual|auto`
- `JAKATA_WORKSPACE_DIR=.`
- `JAKATA_TELEGRAM_SAFE_ROOTS=` optional comma-separated override for safe upload roots
- `NVIDIA_IMAGE_BASE_URL=` optional image endpoint override
- `NVIDIA_IMAGE_SIZE=1024x1024`

## Current behavior

- normal multi-turn chat
- retry with exponential backoff
- fallback across multiple NVIDIA chat models
- persistent chat archives across runs
- permanent memory extraction into SQLite
- live memory graph built from chats and task/tool events
- automatic loading of `.txt` knowledge files
- low-latency retrieval from prior chats, memories, and knowledge files
- model-driven tool use
- explicit `/bg` background execution only
- local daemon-backed background task queue
- foreground tool requests are wrapped in persisted task records
- dynamic multi-agent task orchestration
- self-healing verification and repair loop
- policy-driven approval gates for OS actions with final task reports
- `os_agent` facade for desktop/browser workflows
- internal browser tool for Playwright-backed Chrome navigation, history/tab control, search, result opening, page inspection, media playback checks, and wait-for-text verification
- native local mouse, keyboard, window, browser, shell, file, OCR, and system controls
- richer native controls for machine status, process lookup, URL opening, window move/resize/center/close, and region-based screen/OCR capture
- live webcam preview with `/camera`
- current-scene analysis through the `camera` tool and NVIDIA multimodal models
- Tavily web search
- OpenWeather current weather lookup
- datetime lookup

## Memory layout

JAKATA now keeps memory in `data/`:

- `data/chats/` raw per-session chat logs
- `data/knowledge/` plain `.txt` files loaded on startup
- `data/memory/jakata.db` permanent extracted memory records
- `data/daemon/` daemon pid and kill switch files

The SQLite database now also stores:

- background tasks and task events
- agent runs and agent messages
- graph nodes and graph edges

## CLI commands

- `/bg <goal>` queue a background task; normal prompts stay foreground
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
- `/kill` enable the global daemon kill switch
- `/unkill` clear the global daemon kill switch

If you restart the app with the same session id, it continues from the same conversation and still retrieves relevant older chats plus saved knowledge text.

With the preview open, prompts like `what do you see right now?` or `describe the live camera feed` will use the current webcam frame automatically.

## Notes

- OCR support uses `pytesseract` plus a local Tesseract installation.
- On Windows, `JAKATA_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` works with the standard installer path.
- Background tasks are processed by a local daemon launched with `python -m jakata_agent.daemon_entry`.
- The upgraded `os_agent` can now use dedicated `mouse`, `window`, `browser`, `screen`, and `system` controls for richer local automation.
