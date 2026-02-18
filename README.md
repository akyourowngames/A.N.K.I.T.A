# Personal AI Agent (Groq/Copilot Chat + Modular Tools)

The app is now split into:
- `chat.py` -> chat runtime only
- `llm/client.py` -> provider selection + API transport
- `tools/fs_ops.py` -> file operations + workspace safety
- `tools/engine.py` -> tool schemas, dispatch, NLP local routing

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

Behavior:
- per-chat memory sessions
- `/reset` command clears session for that chat
- update offset persistence in `.ankita/telegram/update-offset.json`

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

## Safety model (OpenClaw-inspired)
- All paths are resolved under workspace root.
- Any path escape (`../`) is blocked.
- Destructive ops require explicit parameters (`recursive`, `overwrite`) and fail closed by default.

## Notes
- Local NLP routing handles common file commands directly (fast, no API cost).
- Local NLP routing also handles explicit terminal commands like `run <command>`.
- Local NLP routing handles app launch requests: `open notepad`, `launch calc`, `start code`.
- Local NLP routing handles app close requests: `close notepad`, `kill chrome`.
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
