# Personal AI Agent (Groq/Copilot Chat + Modular Tools)

The app is now split into:
- `chat.py` -> chat runtime only
- `llm/client.py` -> provider selection + API transport
- `tools/fs_ops.py` -> file operations + workspace safety
- `tools/engine.py` -> tool schemas, dispatch, NLP local routing
- `corn/` -> cron scheduler core (store/schedule/service)

## Setup

```powershell
cd ANKITA
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configure

`.env`:

```env
LLM_PROVIDER=groq
LLM_MAX_TOKENS=120

# Groq
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.1-8b-instant

# Copilot (choose one auth mode)
# COPILOT_GITHUB_TOKEN=your_github_token
# COPILOT_API_KEY=your_copilot_api_token
COPILOT_MODEL=gpt-4o
```

## Run

```powershell
python chat.py
```

`chat.py` now auto-starts the Corn scheduler in-process by default (`CORN_AUTO_RUN=true`).

## Desktop GUI (One-on-One)

Run:

```powershell
python gui.py
```

Or via gateway:

```powershell
setx GATEWAY_MODE "gui"
python gateway.py
```

Voice continuous call in GUI:
- Set `SARVAM_API_KEY` in `.env`
- Click `Start Voice Call`
- Speak naturally; ANKITA listens in chunks, replies, and speaks back continuously
- Click `Stop Voice` to end call loop
- Global hotkey: double-press `F8` to start/stop voice (`VOICE_HOTKEY_KEY` / `VOICE_HOTKEY_DOUBLE_PRESS_MS`)
- STT defaults to Python `SpeechRecognition` (`VOICE_STT_PROVIDER=speech_recognition`)
- TTS stays on Sarvam (speaker/pace from `.env`)

Install voice deps:

```powershell
pip install numpy sounddevice SpeechRecognition
```

## Telegram Integration (OpenClaw-style Channel Adapter)

This project now has a dedicated Telegram transport layer that reuses the same ANKITA agent runtime:
- `agent_runtime.py` -> shared agent execution (LLM + tools + history)
- `telegram_bot.py` -> Telegram polling bridge

Set env:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
# Optional: only allow these chat ids
# TELEGRAM_ALLOWED_CHAT_IDS=123456789,-1001234567890
```

Run:

```powershell
python telegram_bot.py
```

`telegram_bot.py` also auto-starts Corn scheduler in-process by default.

## Unified Gateway Entry

Single launcher (OpenClaw-style unified runtime):

```powershell
python gateway.py
```

Mode selection:
- `GATEWAY_MODE=telegram` -> run Telegram + Cron
- `GATEWAY_MODE=chat` -> run CLI chat + Cron
- `GATEWAY_MODE=voice` -> run browser voice gateway + Cron
- `GATEWAY_MODE=gui` -> run desktop GUI + Cron
- unset `GATEWAY_MODE`: auto-select Telegram when `TELEGRAM_BOT_TOKEN` exists, otherwise chat

## External Voice Gateway (Option 2)

One-on-one voice interaction outside Telegram using Sarvam:

```powershell
setx SARVAM_API_KEY "your_key"
setx GATEWAY_MODE "voice"
python gateway.py
```

Open:

```text
http://127.0.0.1:8765
```

Flow:
- Browser mic capture (push-to-talk)
- Sarvam STT (`speech-to-text`)
- ANKITA agent response
- Sarvam TTS (`text-to-speech`)
- Audio reply in browser player

Behavior:
- per-chat memory sessions
- `/reset` command clears session for that chat
- update offset persistence in `.ankita/telegram/update-offset.json`

## 🎙 Changing the Microphone / Sound Device

A.N.K.I.T.A auto-detects your microphone on startup, preferring real physical
mics (Microsoft, Realtek, HD Audio, Headset) over virtual ones (SplitCam,
DroidCam, Stereo Mix, etc.). If it picks the wrong mic, here's how to fix it.

### Step 1 — List all available audio devices

Run this in your terminal from the ANKITA folder:

```powershell
python -c "import sounddevice as sd; [print(f'{i:>3}: [{\"IN\" if d[\"max_input_channels\"]>0 else \"  \"}/{\"OUT\" if d[\"max_output_channels\"]>0 else \"   \"}] {d[\"name\"]}') for i, d in enumerate(sd.query_devices())]"
```

Example output:
```
  0: [IN /OUT] Microsoft Sound Mapper - Input
  1: [IN /   ] Microphone Array (Realtek(R) Audio)
  2: [IN /   ] Headset Microphone (USB Audio)
  3: [   /OUT] Speakers (Realtek(R) Audio)
 27: [IN /   ] SplitCam Virtual Microphone
```

### Step 2 — Set the device index in `.env`

Find the index number of the mic you want (e.g. `1` for Realtek above) and add
it to your `.env` file:

```env
# Use device index 1 (Realtek Microphone Array)
VOICE_GUI_DEVICE_INDEX=1
```

Restart ANKITA — it will use that specific device from now on.

### Step 3 — Remove the setting to go back to auto-detect

Delete or comment out the line in `.env`:

```env
# VOICE_GUI_DEVICE_INDEX=1
```

ANKITA will auto-detect again, preferring Microsoft/Realtek/HD Audio mics.

> **Tip:** The GUI shows the active mic name in the status bar when you press
> **🎙 Listen**. If it shows `⚠️ Mic fallback`, your configured index is
> invalid — check the list above and update `.env`.

---

## Tool Abilities (God Tier File Ops)
- `list_files(path, max_entries)`
- `read_file(path)`
- `search_text(query, path, max_results)`
- `write_file(path, content, overwrite)`
- `edit_file(path, old_text, new_text, replace_all)`
- `rename_path(path, new_name, overwrite)`
- `delete_path(path, recursive, missing_ok)`
- `move_path(src, dst, overwrite)`
- `copy_path(src, dst, overwrite, recursive)`
- `make_dir(path, parents, exist_ok)`
- `file_info(path)`
- `apply_patch(patch)`
- `run_command(command, args, cwd, timeout_ms, use_shell, env)`
- `launch_app(app, args, cwd)`
- `terminate_app(app, force)`
- `search_web(query, max_results)` (realtime web data)
- `search_news(query, max_results)` (realtime news headlines)
- `cron(action, ...)` (status/list/add/update/remove/run/runs/run_due)
- `search_music(query, max_results)` (music candidate matching)
- `play_music(query, headless, stop_current)` (headless/background playback)
- `stop_music()` (stop active music playback)
- `system_control(action, amount, path)` (`volume_up`, `volume_down`, `mute_toggle`, `show_desktop`, `media_play_pause`, `media_next`, `media_prev`, `lock_screen`, `window_minimize_all`, `window_restore_all`, `brightness_up`, `brightness_down`, `brightness_set`, `wifi_on`, `wifi_off`, `bluetooth_on`, `bluetooth_off`, `screenshot`)

## Safety model (OpenClaw-inspired)
- All paths are resolved under workspace root.
- Any path escape (`../`) is blocked.
- Destructive ops require explicit parameters (`recursive`, `overwrite`) and fail closed by default.

## Notes
- Local NLP routing handles common file commands directly (fast, no API cost).
- Local NLP routing also handles explicit terminal commands like `run <command>`.
- Local NLP routing handles app launch requests: `open notepad`, `launch calc`, `start code`.
- Local NLP routing handles app close requests: `close notepad`, `kill chrome`.
- Local NLP routing handles realtime search: `search web for ...`, `latest news about ...`.
- Local NLP routing handles cron quick commands: `cron status`, `cron list`, `cron run <job_id>`.
- Local NLP routing handles music commands: `play <song name>`, `stop music`.
- Local NLP routing handles system controls: `increase volume`, `decrease sound`, `show desktop`, `next track`, `lock screen`.
- Additional system NLP examples: `set brightness to 40`, `turn off wifi`, `turn on bluetooth`, `take screenshot`.
- `search_web` uses Google Custom Search API if configured; otherwise falls back to DuckDuckGo HTML.
- LLM tool-calling handles advanced multi-step operations.
- Copilot mode uses OpenClaw-style token exchange:
  - GitHub token (`COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`) exchanges at `https://api.github.com/copilot_internal/v2/token`.
  - If no GitHub token is set, ANKITA runs GitHub Device Login and opens browser auth flow automatically.
  - Base URL is auto-derived from `proxy-ep=...` in the returned token.
  - Token cache path: `.ankita/credentials/github-copilot.token.json`.
  - GitHub device auth cache path: `.ankita/credentials/github.device.token.json`.

## Test

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## Corn Worker (Cron Runner)

Use the background worker to execute scheduled jobs:

```powershell
python corn_worker.py
```

Use this only if you want a dedicated scheduler process. For most setups, `chat.py`, `telegram_bot.py`, or `gateway.py` already runs cron internally.

## Headless Music Playback Requirements

`play_music` needs one of these local player stacks:
- `yt-dlp` + `ffplay`
- `mpv`
- `vlc`

If none are installed, ANKITA returns a clear install error.

Example cron tool payload (from chat):

```json
{
  "action": "add",
  "job": {
    "name": "quick-note",
    "schedule": {"kind": "every", "every_ms": 60000},
    "payload": {"kind": "note", "text": "heartbeat"}
  }
}
```

---

## 🐕 Watchdog System — Complete Reference

### Architecture Overview

```
gui.py / chat.py
    │
    ├── ProactiveEngine (proactive.py)          ← 1 daemon thread
    │       │   _queue (queue.Queue)
    │       ├── _check_system_resources()       ← CPU/RAM/Battery via psutil
    │       ├── _check_drop_files()             ← .ankita/proactive_events/*.json
    │       ├── _check_raw_ideas()              ← .ankita/raw_ideas/
    │       ├── _check_idle()                   ← spawns DreamAgent thread after 1 hr idle
    │       ├── _check_sentinel()               ← spawns ScreenAgent thread after 5 min idle
    │       └── _check_cron_overdue()           ← monitors CornRunner delays
    │
    ├── WatchdogManager (watchdog_manager.py)   ← owns 4 watcher daemon threads
    │       ├── PriceWatcher                    ← every 2 min
    │       ├── NewsWatcher                     ← every 10 min
    │       ├── FileWatcher                     ← every 30 sec
    │       └── GitWatcher                      ← every 5 min
    │           (each watcher → _alert() → ProactiveEngine._queue)
    │
    └── CornRunner (corn/runner.py)             ← 1 daemon thread, polls every 5 sec
            └── CornService                     ← reads .ankita/corn/jobs.json, runs due jobs
```

---

### The 4 Watchers

#### 💰 PriceWatcher

| Property | Value |
|---|---|
| **Poll interval** | Every **120 seconds** (2 min) |
| **External APIs** | CoinGecko API → Yahoo Finance → `search_price()` tool (fallback chain) |
| **What it watches** | `config["assets"]` list — crypto/stock symbols with alert conditions |
| **Alert conditions** | `price_above`, `price_below`, `change_pct_above`, `change_pct_below` |
| **Cooldown** | **1800 seconds (30 min)** — won't spam the same asset within cooldown |
| **State stored** | `last_price`, `last_alert_time`, `last_change_pct` per symbol |
| **Config file** | `.ankita/watchdogs/price_config.json` |
| **Example alert** | `💰 BTC crossed $100,000! Current price: $100,432` |

#### 📰 NewsWatcher

| Property | Value |
|---|---|
| **Poll interval** | Every **600 seconds** (10 min) |
| **External APIs** | `search_news()` tool → Google News RSS (`news.google.com/rss`) → urllib fallback |
| **What it watches** | `config["keywords"]` list (e.g. `"AI India"`, `"Helper ID"`) |
| **Deduplication** | SHA256 hash of URL/title — never shows the same article twice |
| **Max per cycle** | 5 articles per check cycle |
| **Max hash store** | 5,000 hashes before pruning |
| **Config file** | `.ankita/watchdogs/news_config.json` |
| **Example alert** | `📰 AI India: OpenAI expands to India — TechCrunch 🔗 https://...` |

#### 📁 FileWatcher

| Property | Value |
|---|---|
| **Poll interval** | Every **30 seconds** |
| **External APIs** | None — pure `os.scandir()` |
| **What it watches** | `config["directories"]` list of folder paths |
| **Change detection** | Compares live `mtime` snapshot against stored baseline |
| **First run** | Baseline only, no alerts (avoids startup spam) |
| **Auto-summarise** | Offers `"Say 'summarise [file]'"` hint for `.pdf`, `.docx`, `.txt`, `.md` |
| **Ignored extensions** | `.tmp`, `.lock`, `.lnk`, `.ini`, `.db`, `.log`, `.part` |
| **State stored** | `snapshots[dir_path][filename] = mtime` |
| **Config file** | `.ankita/watchdogs/file_config.json` |
| **Example alert** | `📄 New file in Downloads: report.pdf 💡 Say 'summarise report.pdf' to read it!` |

#### 🔀 GitWatcher

| Property | Value |
|---|---|
| **Poll interval** | Every **300 seconds** (5 min) |
| **External APIs** | Local `git log --since=<timestamp>` + optional GitHub API for PRs/issues |
| **GitHub token** | Resolves from `GITHUB_TOKEN` → `GH_TOKEN` → cached device login token |
| **What it watches** | `config["repos"]` list of local repo paths |
| **First run** | Records baseline timestamp only — no alerts |
| **Max commits shown** | 10 per check (rest shown as `"...and N more"`) |
| **State stored** | `last_check_time[repo_path] = epoch_float` |
| **Config file** | `.ankita/watchdogs/git_config.json` |
| **Example alert** | `🔀 ANKITA New commit by Prakhar (2026-03-01): a1b2c3 — fix: tool schema bug` |

---

### ProactiveEngine — The Alert Bus

Runs a single daemon thread every **15 seconds**, doing 6 checks:

| Check | Trigger | Action |
|---|---|---|
| `_check_system_resources()` | CPU >85%, RAM >90%, Battery <15% | Pushes `system_alert` event |
| `_check_drop_files()` | New `.json` in `.ankita/proactive_events/` | Reads + forwards event |
| `_check_raw_ideas()` | New file in `.ankita/raw_ideas/` | Triggers content generation |
| `_check_idle()` | No user input for **3600s (1 hr)** | Spawns `DreamAgent` thread to synthesize insights |
| `_check_sentinel()` | OS idle >**300s (5 min)** | Spawns `ScreenAgent` thread (screenshot + offers help) |
| `_check_cron_overdue()` | Cron job past its schedule | Warns about delayed jobs |

All 4 watchers push alerts directly into `ProactiveEngine._queue` via `BaseWatcher._alert()`.

---

### CornRunner / CornService

| Component | Role |
|---|---|
| `CornRunner` | Daemon thread, polls every **5 seconds**, calls `CornService.run_due()` |
| `CornService` | CRUD for jobs stored in `.ankita/corn/jobs.json`, runs due jobs via subprocess |
| `CornStore` | Atomic JSON file read/write using temp-file rename (crash-safe) |
| Schedule types | `"at"` (one-shot datetime), `"every"` (repeating interval ms), `"cron"` (5-field cron expr) |
| Payload types | `"command"` (subprocess with timeout) or `"note"` (text message) |
| Concurrency | File lock (`.json.lock`) prevents double execution |
| Run history | Appended to `.ankita/corn/runs.jsonl` |

---

### Startup Wiring

```
gui.py (or chat.py)
│
├── proactive = ProactiveEngine(workspace_root)
├── proactive.start()                         → daemon thread starts
│
├── watchdog_mgr = WatchdogManager(workspace_root, proactive=proactive)
├── watchdog_mgr.load_config()                → reads 4 config JSONs, instantiates 4 watchers
├── watchdog_mgr.start_all()                  → spawns 4 daemon threads
│
└── corn_runner = CornRunner(workspace_root)
    └── corn_runner.start()                   → spawns 1 daemon thread
```

All watcher threads are **daemon threads** — they die automatically when the app exits. All watcher state is persisted to `.ankita/watchdogs/state/*.json` so alerts survive restarts.

---

### Dynamic Wiring (runtime commands)

You can add new watches at runtime by telling ANKITA:

| What you say | What it calls |
|---|---|
| `"Alert me when BTC drops 5%"` | `watchdog_mgr.add_price_alert(symbol, conditions)` |
| `"Watch news for Helper ID"` | `watchdog_mgr.add_news_keyword(keyword)` |
| `"Watch my Downloads folder"` | `watchdog_mgr.add_watch_dir(path)` |
| `"Watch my ANKITA repo for commits"` | `watchdog_mgr.add_git_repo(path)` |

These update the config JSON and hot-reload the watcher without restarting the app.

---

### BaseWatcher — Self-Healing Core

All 4 watchers inherit from `BaseWatcher` which provides:

- **Auto-crash recovery** with exponential backoff (1s → 2s → 4s → ... capped at 300s)
- **Graceful shutdown** via `threading.Event` (`_stop.set()`)
- **State persistence** to `.ankita/watchdogs/state/<name>.json` across restarts
- **Alert routing** to `ProactiveEngine._queue` via `_alert(message, kind)`
