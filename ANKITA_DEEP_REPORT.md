# A.N.K.I.T.A — Deep System Report
### Autonomous Neural Knowledge & Intelligence Task Automaton
**Report generated:** 2026-03-01 | **Scanned by:** Rovo Dev

---

## TABLE OF CONTENTS

1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [Entry Points & Gateway](#3-entry-points--gateway)
4. [LLM Layer — `llm/`](#4-llm-layer--llm)
5. [Agent Runtime — `agent_runtime.py`](#5-agent-runtime--agent_runtimepy)
6. [Multi-Agent System — `agents/`](#6-multi-agent-system--agents)
7. [Tool Engine — `tools/`](#7-tool-engine--tools)
8. [Corn Scheduler — `corn/`](#8-corn-scheduler--corn)
9. [Memory System — `memory.py`](#9-memory-system--memorypy)
10. [Session Manager — `session_manager.py`](#10-session-manager--session_managerpy)
11. [Proactive Engine — `proactive.py`](#11-proactive-engine--proactivepy)
12. [Interfaces](#12-interfaces)
13. [Services — `services/`](#13-services--services)
14. [Configuration & Environment](#14-configuration--environment)
15. [Data Flow — End to End](#15-data-flow--end-to-end)
16. [File & Directory Map](#16-file--directory-map)
17. [Key Protocols & Design Patterns](#17-key-protocols--design-patterns)
18. [Dependencies](#18-dependencies)

---

## 1. PROJECT OVERVIEW

**A.N.K.I.T.A** (Autonomous Neural Knowledge & Intelligence Task Automaton) is a **fully local, multi-modal, multi-agent AI assistant** built in Python. It is authored by **Krish Verma**, a 15-year-old developer and founder of Helper ID.

ANKITA is not a simple chatbot. It is a **full-stack autonomous agent system** that can:
- Control the Windows operating system (volume, brightness, WiFi, Bluetooth, screenshots, media keys)
- Read, write, move, edit, and search files on disk
- Execute terminal/PowerShell commands
- Search the web and read live content in real time
- Conduct multi-source deep research (parallel scout threads)
- Play, stop, search music
- Schedule cron jobs with full cron-expression support
- Generate long-form content (poems, essays, reports, scripts, emails)
- Operate a **WhatsApp AI Bridge** to auto-reply to contacts
- Operate a **Telegram bot** interface
- Operate a **voice-over-WebSocket** interface using Sarvam STT/TTS
- Operate a **PyQt5 GUI** with a chat window and voice button
- Interact with **Google Sheets**, **YouTube**, and **Figma** via cloud APIs
- See the screen via **GPT-4o vision** (capture_screen + visual_click)
- See through the **webcam** (capture_webcam)
- Remember conversations long-term via **ChromaDB vector memory**
- Think autonomously while idle via the **DreamAgent**
- Watch the screen while idle via the **Sentinel**
- Spawn **background drone threads** (HiveMind) for heavy tasks without blocking
- Persist sessions across restarts via **SessionManager**

It supports two LLM backends:
- **Groq** (LLaMA 3.1 8B — fast, free-tier)
- **GitHub Copilot / GPT-4o** (premium quality, vision-capable)

---

## 2. ARCHITECTURE OVERVIEW

```
User Input (any interface)
        │
        ▼
   [Gateway / Interface Layer]
   chat.py | telegram_bot.py | gui.py | voice_web.py | whatsapp_runner.py
        │
        ▼
   [HiveMind] ──── background drone threads for heavy tasks
        │
        ▼
   [Orchestrator]
        │
   [SupervisorAgent] ── routes via LLM JSON decision
        │
   ┌────┴─────────────────────────────────────────────┐
   │  Fan-Out: run specialist agents (sequential/parallel) │
   └─────────────────────────────────────────────────┘
        │        │        │        │         │
   FileAgent  WebAgent SystemAgent MusicAgent ...12 total
        │
   [Tool Engine] — executes tool calls
        │
   [LLM Client] — Groq or Copilot API
        │
   [MemoryStore] — ChromaDB vector memory
        │
   [SessionManager] — disk-persistent conversation
        │
   [ProactiveEngine] — background health + idle + dream + sentinel
        │
   [CornService] — cron scheduler
```

ANKITA follows a **multi-layer architecture**:

| Layer | Description |
|-------|-------------|
| Interface | How the user talks to ANKITA (CLI, GUI, Telegram, Voice, WhatsApp) |
| Gateway | Routes to the correct interface module |
| HiveMind | Task dispatcher — instant vs. background drone |
| Orchestrator | Multi-agent fan-out/fan-in engine |
| Supervisor | LLM-powered request router |
| Specialists | 12 domain-focused sub-agents |
| AgentRuntime | Core tool-calling loop (ReAct pattern) |
| Tool Engine | Executes all tool calls with specs |
| LLM Client | Groq / Copilot HTTP client with retry/backoff |
| Memory | ChromaDB vector store for long-term recall |
| SessionManager | JSON-on-disk conversation persistence |
| ProactiveEngine | Background monitoring, alerts, DreamAgent, Sentinel |
| CornService | Cron job scheduler with at/every/cron expressions |

---

## 3. ENTRY POINTS & GATEWAY

### `gateway.py`
The **universal entry point**. Reads `GATEWAY_MODE` from `.env` and lazy-imports the correct interface:

| `GATEWAY_MODE` | Module loaded |
|---|---|
| `chat` | `chat.py` — terminal CLI chat |
| `telegram` | `telegram_bot.py` — Telegram bot |
| `voice` | `voice_web.py` — WebSocket voice server |
| `gui` | `gui.py` — PyQt5 desktop GUI |
| (auto) | If `SARVAM_API_KEY` + `VOICE_WEB_AUTO_SELECT=true` → voice |
| (auto) | If `TELEGRAM_BOT_TOKEN` set → telegram |
| (default) | chat |

**Key design:** lazy imports mean PyQt6/voice/browser deps are **never loaded unless actually needed**.

### `chat.py`
Terminal CLI interface. Maintains a `messages[]` list, calls `HiveMind.delegate()`, handles special commands like `/memory`, `/hive`, `/reset`, `/search`. Calls `ProactiveEngine.set_last_interaction()` to update idle timer after each input.

### `corn_worker.py`
Standalone process for running the Corn cron scheduler. Polls `CornService.run_due()` every N seconds (default 5s, configurable via `CORN_POLL_INTERVAL_SEC`). Runs as a separate process alongside the main agent.

### `demo_closed_loop.py`
A **standalone demo** of the full See → Think → Click → Verify vision pipeline. Takes a target description (e.g., `"click the Start button"`), captures screen before, calls `visual_click()`, captures screen after, and asks GPT-4o to describe what changed.

---

## 4. LLM LAYER — `llm/`

### `llm/__init__.py`
Exports: `LLMRuntime`, `build_runtime_from_env`, `call_chat_once`.

### `llm/client.py`
The **entire LLM API abstraction layer**. ~508 lines.

#### `LLMRuntime` (dataclass)
Holds: `provider`, `model`, `api_key`, `base_url`, `max_tokens`.

#### `build_runtime_from_env()`
Reads `.env` and builds an `LLMRuntime`:
- **Groq path:** reads `GROQ_API_KEY`, `GROQ_MODEL` (default `llama-3.1-8b-instant`)
- **Copilot path:**
  1. Tries `COPILOT_API_KEY` directly
  2. Tries `COPILOT_GITHUB_TOKEN` → exchanges via `_exchange_github_to_copilot_token()`
  3. Falls back to **GitHub Device Login** (opens browser, polls for token)
  - Copilot tokens are **cached on disk** at `.ankita/credentials/github-copilot.token.json`
  - Token is refreshed 5 minutes before expiry
  - Base URL is **auto-derived** from the token's `proxy-ep=` field

#### `build_vision_runtime_from_env()`
Returns a vision-capable runtime (GPT-4o) for image analysis:
- Priority: `VISION_PROVIDER` env → main runtime if already copilot → auto-fallback to Copilot if token available → main runtime (fails gracefully)

#### `call_chat_with_image()`
Sends a **multimodal vision request** to GPT-4o with an inline base64 image. Used by `ScreenAgent` tools.

#### `call_chat_once()`
Core HTTP POST to the LLM API. Features:
- **Exponential backoff with jitter** for 429/502/503/504 errors (max 3 retries)
- **Retry-After header** respected
- Configurable timeout via `LLM_REQUEST_TIMEOUT_SEC` (default 45s)
- Supports `tools` (function calling) and `tool_choice: auto`
- Handles both `max_tokens` (Groq) and `max_completion_tokens` (Copilot) naming

---

## 5. AGENT RUNTIME — `agent_runtime.py`

The **core ReAct loop** for single-agent operation. ~270 lines.

### `SYSTEM_PROMPT`
Defines ANKITA's personality: Gen-Z queen, bestie energy, attitude, zero robotic speak. Lists capabilities and the ReAct pattern (Think → Act → Observe → Repeat → Respond).

### `new_session()`
Creates a fresh `messages[]` list with the system prompt + any existing long-term memory pre-injected.

### `AgentRuntime`
- `__init__(runtime, workspace_root)` — stores LLM runtime and workspace path
- `_adaptive_step_limit(messages)` — dynamically adjusts max tool steps:
  - 20 steps for multi-domain tasks ("and then", "after that")
  - 16 steps for research/debug tasks
  - 6 steps for simple actions (open, play, mute)
  - 12 steps default
- `_execute_tool_calls_parallel(tool_calls)` — executes multiple tool calls **concurrently** via `ThreadPoolExecutor` (max 4 threads). Single tool calls skip the thread overhead.
- `run_turn(messages, tools)` — the main ReAct loop:
  1. **Token Guardian:** if estimated tokens > 48,000 → compact messages proactively
  2. Call LLM → get response
  3. If no tool calls → return text reply
  4. **Deduplication:** skip repeated tool calls (same name + args) to prevent infinite loops, keep last 6 signatures
  5. Execute tool calls in parallel
  6. Append tool results to messages
  7. Repeat up to `step_limit` times
- `process_user_text(user_text, messages)` — public entry point:
  - Refreshes memory block in system prompt on every turn
  - Appends user message
  - Calls `run_turn()`
  - Handles HTTP errors: 413 → compact + retry; 400 token limit → emergency compact (keep 4 messages) + retry; 400 tool validation → retry without tools

---

## 6. MULTI-AGENT SYSTEM — `agents/`

### `agents/__init__.py`
Exports all agents: `Orchestrator`, `SupervisorAgent`, `FileAgent`, `WebAgent`, `SystemAgent`, `MusicAgent`, `CodeAgent`, `CronAgent`, `GeneralAgent`.

### `agents/supervisor.py` — The Routing Brain
The **SupervisorAgent** makes ONE job decision: read the user request, pick the right specialist(s).

- Uses a **dedicated LLM call** with a strict JSON-only system prompt
- Returns: `{"agents": [...], "parallel": bool, "reasoning": "..."}`
- Knows **12 agents**: FileAgent, WebAgent, SystemAgent, MusicAgent, CodeAgent, CronAgent, ContentAgent, CommsAgent, GeneralAgent, TerminalAgent, ScreenAgent, IntegrationAgent
- **Assembly Line rules** (relay race model): `write a poem` → `[ContentAgent, FileAgent]`; `write a poem in Notepad` → `[ContentAgent, FileAgent, SystemAgent]`
- Validates agent names; falls back to `GeneralAgent` on any JSON parse error
- 256 max tokens per routing call (cheap and fast)

### `agents/orchestrator.py` — The Engine (700 lines)
The **Orchestrator** is the brain that coordinates everything.

**`Orchestrator.run(user_text, messages)`:**
1. Calls `SupervisorAgent.route()` to get agent list + parallel flag
2. Single `GeneralAgent` → fast path via `AgentRuntime`
3. **Action Override check**: re-routes lazy `GeneralAgent` answers to correct specialists via keyword matching
4. **TIME LORD override**: forces sequential if producer→consumer dependency detected (ContentAgent → FileAgent → SystemAgent)
5. **Fan-Out**: parallel (`ThreadPoolExecutor`, max 4) or sequential
6. **Fan-In**: single result → return directly; multiple → `_synthesize()`

**`_run_sequential_with_context(specialists, task)`** — Assembly Line:
- Runs agents one-by-one
- **BATON PASS**: `_extract_artifacts()` sniffs file paths + URLs from each agent's reply
- **TELEPATHY**: `_build_prior_context_block()` injects prior agent output into next agent's system prompt
- **HYDRA PROTOCOL**: if agent fails → look up `_ESCALATION_MATRIX` → reroute to backup agent with post-mortem context. Example: `SystemAgent` fails → `TerminalAgent` takes over with PowerShell fallback
- **AUDIT LOG**: every agent result written to `.ankita/audit.jsonl`

**`_ESCALATION_MATRIX`** — Hydra Protocol fallbacks:
| Agent Failed | Backup | Strategy |
|---|---|---|
| SystemAgent | TerminalAgent | PowerShell via execute_shell |
| WebAgent | GeneralAgent | Use LLM knowledge, state cutoff |
| FileAgent | TerminalAgent | Force-write via New-Item PowerShell |
| ContentAgent | GeneralAgent | Shorter version |
| CodeAgent | CodeAgent | Re-read error, retry |
| MusicAgent | TerminalAgent | Start-Process spotify: |

**Vision handling in orchestrator**: after a `capture_screen` or `capture_webcam` tool call returns base64 data:
- Strips base64 from text history (saves tokens)
- Builds a multimodal `image_url` message
- **Groq Blind Fix**: Groq/LLaMA can't process images → pre-describes them via GPT-4o vision runtime, injects description as plain text

**`_SYNTHESIZER_PROMPT`**: Final synthesizer LLM call — ONE terse confirmation sentence. Never echoes content. Pure status reporter.

**Token Guardian**: every specialist call is guarded — if estimated tokens > 48,000, compact before calling. `_estimate_tokens()` uses 4 chars ≈ 1 token heuristic.

**Prism Protocol (💎)**: if LLM returns 400/context_length_exceeded → find last tool message → replace with truncation notice → retry.

**`_DEEP_MODE_MAX_TOKENS = 8192`**: ContentAgent in deep mode gets 8192 tokens to write full 10-page documents.

### `agents/specialists.py` — The 12 Agents (551 lines)
Each specialist is a `SpecialistAgent(name, tool_names, system_prompt)`.

| Agent | Tools Available | Purpose |
|---|---|---|
| **FileAgent** | list_files, read_file, write_file, edit_file, launch_app + memory | File system wizard. GPS-locked to Desktop. Auto-opens files after saving (Proof of Life). |
| **WebAgent** | search_web, search_news, search_and_fetch, fetch_page_content, deep_research, download_file, launch_app + memory | Research analyst. Reads actual content, not just links. Deep research via parallel scouts. |
| **SystemAgent** | system_control, launch_app, terminate_app, desktop_interact, execute_shell, run_command + memory | OS controller. Volume, brightness, WiFi, Bluetooth, screenshots, keyboard God Mode. MacGyver fallback to PowerShell. |
| **MusicAgent** | play_music, stop_music, search_music, current_music + memory | Music search and playback. |
| **CodeAgent** | run_command, apply_patch, execute_shell, check_syntax, read_file, write_file, launch_app + memory | Autonomous bug fixer. Self-healing dev loop: run → read traceback → read lines → edit → check_syntax → run again. |
| **TerminalAgent** | execute_shell, list_files, read_file, run_command + memory | Raw PowerShell/CMD access. Output guardrails (Select-Object -First 50). Security: blocks rm -rf, format c:, shutdown. |
| **CronAgent** | cron + memory | Scheduler management. |
| **ContentAgent** | *(no tools)* | Pure text generator. JOURNALIST MODE when given research context. SCALE PROTOCOL: normal vs deep (6000-8000+ words). |
| **CommsAgent** | *(no tools)* | WhatsApp personality agent. Gen-Z, casual, covers for Krish. |
| **ScreenAgent** | capture_screen, read_screen_context, visual_click, system_control, desktop_interact, capture_webcam | Vision God. Sees screen, reads errors, clicks UI elements. Never describes — DOES. Webcam support. |
| **IntegrationAgent** | sheets_op, youtube_op, figma_op + memory | Cloud API specialist. Google Sheets, YouTube, Figma. |
| **GeneralAgent** | ALL tools | Full-capability fallback. All tools, all tasks. |

### `agents/hive.py` — HiveMind (344 lines)
The **async task dispatcher**. ANKITA never blocks on heavy tasks.

**Task Classification:**
- `_INSTANT_KEYWORDS`: "hello", "what time", "who are you" → tiny tasks, reply via `send_fn` immediately
- `_HEAVY_KEYWORDS`: "research", "write", "generate", "deep report", "analyze", "build", "batch" → spawn named drone with "Started 🐝" acknowledgement
- `_is_search_and_write()`: if BOTH search verbs AND write verbs present → always heavy drone

**DroneTask** (dataclass): `id`, `prompt`, `status` (queued/running/done/error), `result`, `error`, `start_time`, `end_time`, `task_type`

**HiveMind.delegate(user_input, messages, send_fn)**:
- Heavy task → spawns daemon thread → returns `"🐝 Started background task [ID: xxxx]"` immediately → `send_fn` called with result when done
- Normal task → spawns daemon thread silently → `send_fn` called with result → returns `""`
- No `send_fn` → synchronous fallback

**Commands**: `/hive` → `list_tasks()` table; `show <id>` → `get_result(id)`; `check_notifications()` drains queue.

### `agents/dream_agent.py` — DreamState (183 lines)
Runs autonomously when user is idle. Not routed through Supervisor.

**`DreamAgent.synthesize(memory_store, session_id, n_memories=15)`:**
1. Searches ChromaDB for 15 recent memories about "recent work tasks ideas problems"
2. Formats them as a numbered list
3. Calls LLM with `_DREAM_SYSTEM_PROMPT` — strict JSON output: `{is_technical, problem, solution, confidence}`
4. **Confidence filter**: only surfaces epiphanies with confidence ≥ 60
5. **Duplicate filter**: checks `.ankita/dreams.jsonl` — skips if exact solution already logged
6. Writes to `.ankita/dreams.jsonl` and returns the solution string
7. `DREAM_MAX_TOKENS` env var controls output length (default 300)

---

## 7. TOOL ENGINE — `tools/`

### `tools/engine.py` — The Master Registry (~2306 lines)
The **central tool dispatch system**. Contains:
- `TOOL_SPECS`: list of all OpenAI-format function-calling JSON specs
- `execute_tool_call(tc, workspace_root)`: routes a tool call dict to the correct Python function
- `compact_messages(messages, keep_tail, char_limit)`: trims old messages to stay within token limits
- `_estimate_tokens(messages)`: estimates token count (4 chars = 1 token heuristic)

Every tool is registered here with its full JSON schema (name, description, parameters with types and descriptions). The engine maps tool names to handler functions from the various `*_ops.py` modules.

### `tools/fs_ops.py` — File System (~702 lines)
All file system operations:
- `list_files(path, pattern)` — directory listing with glob
- `read_file(path)` — full file content
- `read_file_lines(path, start, end)` — specific line range
- `write_file(path, content)` — creates/overwrites file, returns absolute path receipt
- `edit_file(path, old, new)` — search-and-replace in file
- `edit_file_lines(path, start_line, end_line, new_content)` — surgical line-range replacement
- `search_text(path, pattern)` — regex search across files
- `rename_path`, `delete_path`, `move_path`, `copy_path`, `make_dir`, `file_info` — full CRUD
- `apply_patch(path, patch)` — apply a unified diff patch
- `write_content(content, filename, folder)` — smart content-save with auto Desktop fallback

### `tools/realtime_search.py` — Web Search (~803 lines)
- `search_web(query, n)` — DuckDuckGo search (ddgs library)
- `search_news(query, n)` — DuckDuckGo news
- `search_and_fetch(query, n)` — search + fetches page content of top results simultaneously
- `fetch_page_content(url)` — fetches and extracts readable text from a URL (strips HTML)
- `search_price(symbol)` — CoinGecko (crypto) or Yahoo Finance (stocks) direct API
- `download_file(url, dest)` — downloads file to disk, returns path

### `tools/deep_research.py` — Parallel Research (~341 lines)
**The most powerful research tool.**
- `deep_research(topic)` — spawns **10 parallel scout threads**, each searching a different angle
- Collects results and synthesises a **RESEARCH_CONTEXT_BLOCK** — a structured intel brief
- This block is passed to ContentAgent for **Journalist Mode** writing with citations
- Returns raw `RESEARCH_CONTEXT_BLOCK:...:END_RESEARCH_CONTEXT` for the Orchestrator to parse

### `tools/desktop_ops.py` — Screen & Vision (~732 lines)
- `capture_screen(monitor)` — takes screenshot via `mss`, resizes for LLM efficiency, returns base64 + path + scale factors
- `read_screen_context(path)` — loads existing screenshot as base64
- `visual_click(target_description, runtime, verify)` — the **closed-loop click**:
  1. Capture screen
  2. Ask GPT-4o vision: "where is X? reply with JSON coordinates"
  3. Scale coordinates from resized image to real screen pixels
  4. Move mouse + click via `pyautogui`
  5. If `verify=True`: re-capture screen 0.8s later (proof of click)
- `capture_webcam()` — captures a frame from the default webcam, returns base64

### `tools/system_ops.py` — OS Control (~537 lines)
- `system_control(action, value)` — one function, many actions:
  - `volume_up/down/mute_toggle` — Windows COM audio via `comtypes`
  - `brightness_up/down/brightness_set` — WMI monitor brightness
  - `wifi_on/off`, `bluetooth_on/off` — netsh / PnP device commands
  - `screenshot` — saves to Desktop
  - `show_desktop`, `lock_screen`, `sleep_display`, `empty_recycle_bin`
  - `window_minimize_all`, `window_restore_all`
  - `media_play_pause`, `media_next`, `media_prev` — WScript Shell SendKeys
  - `open_url` — Start-Process
  - `get_system_info` — OS, CPU%, RAM%, uptime
- `launch_app(app, args)` — launches any app (notepad, chrome, spotify, explorer, etc.)
- `terminate_app(name)` — kills a process by name (protected: never kills system/OS processes)
- `desktop_interact(action, text, shortcut, focus)` — keyboard God Mode:
  - `type_text` — types text into focused window
  - `press_shortcut` — sends key combos (ctrl+c, win+d, alt+f4, etc.)
  - `focus` parameter — always focuses the target window first for safety

### `tools/terminal_ops.py` — Shell (~529 lines)
- `execute_shell(command, cwd, timeout)` — runs PowerShell (Windows) or sh (Linux/Mac)
  - Security blocklist: `del /s`, `rmdir /s`, `rm -rf`, `format c:`, `dd if=`, `shutdown /s`, `reg delete hklm`
  - Output capped at 8000 chars to prevent context overflow
  - Returns: `{ok, exit_code, stdout, stderr, duration_ms}`
- `run_command(command, cwd)` — simpler wrapper
- `check_syntax(path)` — Python AST syntax check (instant, no execution)

### `tools/music_ops.py` — Music (~595 lines)
- `play_music(query)` — searches and plays music
- `stop_music()` — stops playback
- `search_music(query)` — searches without playing
- `current_music()` — returns what's currently playing
Uses platform-specific playback (Spotify, Windows Media Player, VLC, etc.)

### `tools/memory_ops.py` — Long-Term Memory (~343 lines)
- `remember(key, value, session_id)` — stores a key-value fact in `.ankita/memory.json`
- `recall(key, session_id)` — retrieves stored facts
- `forget(key, session_id)` — removes a stored fact
- `format_memory_block()` — formats all stored facts as a `--- LONG TERM MEMORY ---` block for injection into system prompts

### `tools/content_ops.py` — Content Generation (~499 lines)
- `write_content(content, filename, folder)` — saves generated content to disk
- `detect_format_type(name, text)` — auto-detects content format (poem, essay, report, script, email, letter) from filename + raw text
Used by ProactiveEngine's raw_ideas watcher.

### `tools/auth_manager.py` — OAuth2 (~216 lines)
Google OAuth2 flow manager:
- `get_google_credentials(scopes)` — loads cached tokens from `~/.ankita/tokens.json`; triggers browser OAuth flow on first use
- Handles token refresh automatically
- Supports both `GOOGLE_CLIENT_ID`+`GOOGLE_CLIENT_SECRET` env vars OR `GOOGLE_CLIENT_SECRET_FILE` path

### `tools/sheets_ops.py` — Google Sheets (~295 lines)
- `sheets_action(action, spreadsheet_id, range, values, ...)` — unified Sheets API wrapper
- Actions: `read_range`, `append_row`, `update_range`, `clear_range`, `get_sheet_info`
- Prism sanitization: empty rows purged, data converted to Markdown table format

### `tools/youtube_ops.py` — YouTube (~241 lines)
- `youtube_action(action, ...)` — YouTube Data API v3 wrapper
- Actions: `search_channel_videos`, `get_subscriptions`, `create_playlist`, `add_to_playlist`, `get_playlists`
- Prism sanitization: only Title, Channel, URL returned (strips etag, contentDetails, etc.)

### `tools/figma_ops.py` — Figma (~260 lines)
- `figma_action(action, file_key, ...)` — Figma REST API wrapper
- Actions: `list_files`, `read_comments`, `get_node_properties`, `get_file_structure`
- Prism sanitization: strips all layout/style data. Keeps only Name, ID, Text Content.
- Auth: `FIGMA_ACCESS_TOKEN` env var (Personal Access Token)

### `tools/cron_ops.py` — Cron Bridge
Thin bridge: `cron_action(workspace_root, action, ...)` delegates to `CornService`.

### `tools/idle_ops.py` — Idle Detection
- `get_idle_seconds()` — uses Windows `GetLastInputInfo` + `GetTickCount` via ctypes
- Returns seconds since last mouse/keyboard activity
- Cross-platform safe: returns 0.0 on non-Windows
- `is_idle(threshold_seconds)` — convenience bool
- `idle_status()` — structured dict for tool engine

