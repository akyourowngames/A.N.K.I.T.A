# ankita

Terminal coding agent powered by GitHub Copilot models. Chat, run shell commands, edit files with approval diffs, and talk hands-free with mic input + spoken replies — all from your terminal, zero npm dependencies.

```
ankita › list the files in tools/ and tell me which one handles edits
  → list_dir({"path":"tools"})
  ...
```

## Quickstart

**Prereqs:** Node.js 18+.

```bash
node chat.mjs
# or
npm start
```

First run prints a code and opens `github.com/login/device` — sign in once and the token is cached (`~/.copilot-chat-cli/auth.json`, mode `0600`). Every later run skips login.

**Voice mode** additionally needs `ffmpeg` + `ffplay` on PATH (`winget install Gyan.FFmpeg`) and a free Groq key for mic transcription:

```bash
ankita --voice
```

## What it can do

- **Chat** with streaming markdown replies (syntax-highlighted code boxes, tables) that re-render live without garbling, even on long answers
- **Act** via 15 tools: shell (foreground + background jobs), file read/write/edit (string, multi-edit atomic, or by line number), search, glob, mkdir/move/delete, URL fetch, todo lists — every mutating call shows a unified `@@` diff and asks first
- **Talk**: `/mic` dictates via Groq Whisper, `/voice` runs a hands-free loop, replies are spoken with Edge neural TTS (Aria) or Groq Orpheus
- **Remember**: named sessions, autosave after every turn, `--continue`, sanitized restores, persistent history, tab-completion
- **Run anywhere**: interactive REPL, one-shot `-p`, script-friendly `--plain` / `--json`, or point it at any OpenAI-compatible endpoint (Ollama, LM Studio, …)

## CLI

```
ankita [options] [message...]

  -p, --prompt <text>   send one message and exit
  -m, --model <id>      model to use
      --max-tokens <n>  cap generated tokens per reply
      --list-models     print available models and exit
      --config          print resolved configuration and exit
      --continue [name] resume a saved session (default: autosave)
  -y, --yes             auto-approve every tool call
      --no-tools        disable tool use
      --no-banner       hide the startup banner
      --plain           no colors or markdown boxes (best for pipes)
      --json            print one JSON result (requires -p)
      --api-base <url>  use an OpenAI-compatible endpoint instead of Copilot
      --api-key <key>   credentials for --api-base
      --speak           read replies aloud
      --voice           start in voice mode (mic in, speech out)
```

Slash commands: `/help /config /reload /models /model /tools /auto /cd /save /load /sessions /paste /usage /mic /voice /say /speak /voices /clear /exit`.

## Configuration

`.env` in the working directory, falling back to `~/.copilot-chat-cli/config.env`. Values in files beat environment variables (Windows already defines `USERNAME`, which would otherwise shadow yours). `/reload` picks up edits live.

| Key | Default | What |
|---|---|---|
| `USERNAME` / `AGENT_NAME` | `user` / `assistant` | Names used in prompts and replies |
| `MODEL` | auto | Pinned model, else newest capable default |
| `TOOLS` / `AUTO_APPROVE` | `on` / `off` | Tool use and the y/n approval gate |
| `HISTORY_MESSAGES` | `40` | Turns kept in context (`HISTORY_LINES` still works) |
| `MAX_TOKENS` / `MAX_TOOL_CHARS` / `CONTEXT_WINDOW` | `4096` / `65536` / `32768` | Output cap, per-result context cap, trim budget |
| `INPUT_COST_PER_MILLION` / `OUTPUT_COST_PER_MILLION` | unset | Enables `$` estimates in `/usage` |
| `API_BASE` / `API_KEY` | unset | OpenAI-compatible endpoint instead of Copilot |
| `GROQ_API_KEY` / `STT_MODEL` | unset / `whisper-large-v3-turbo` | Mic transcription (free key at console.groq.com) |
| `TTS_PROVIDER` | `edge` | `edge`, `groq`, or `auto` (groq when a key exists) |
| `TTS_MODEL` / `TTS_VOICE` | `canopylabs/orpheus-v1-english` / provider default | `tara` on groq, `en-US-AriaNeural` on edge — see `/voices` |
| `TTS_RATE` / `SPEAK` / `MIC_DEVICE` | `+0%` / `off` / auto | Edge speech rate, auto-speak replies, preferred mic |

## Tools

| Tool | Does |
|---|---|
| `run_command` | Shell (pwsh/`sh`), stdin, env, timeout, 64KB bounded output, background jobs |
| `read_file` / `write_file` | Numbered reads; atomic create/overwrite with overwrite diff |
| `edit_file` | Exact string edits, atomic multi-edit, fuzzy fallback ladder (line-endings → trailing whitespace → indentation), refuses ambiguity |
| `edit_lines` | Line-range replace/insert/delete, validated atomically |
| `list_dir` / `glob` / `search_files` | Browse (recursive), find by glob, regex search with excludes — all read-only, run in parallel |
| `create_dir` / `move_file` / `delete_file` | Filesystem verbs (root-protected, no silent overwrites) |
| `fetch_url` | Byte-capped, timed HTTP(S) fetch for docs/APIs |
| `write_todos` | Session checklist for multi-step work |
| `job_status` / `job_stop` | Read and stop background jobs |

Read-only tools skip approval and execute concurrently; mutations are sequential barriers and always confirm first.

## Architecture

```
chat.mjs            thin entry (arg parsing lives in cli)
src/
  cli.mjs           REPL, slash commands, sessions, --json/--plain, voice loop
  agent.mjs         tool-calling loop: stream → tool_calls → execute → repeat
  provider.mjs      model picking + CompatibleClient (any OpenAI-style API)
  auth.mjs          GitHub device flow → short-lived Copilot token
  config.mjs        layered .env (project > global > env > defaults)
  history.mjs       sanitize + budget-aware trimming (never splits tool pairs)
  markdown.mjs      streaming markdown renderer (LiveRenderer commits scrollback)
  net.mjs           fetch with selective retry (429/5xx + transient sockets only)
  ui.mjs            terminal I/O, colors, banner, completion
  voice.mjs         mic record, Groq STT, Edge/Groq TTS, playback
tools/
  index.mjs         registry (specs/get/names) + job cleanup
  *.mjs             one self-contained module per tool (name/description/
                    parameters/approval/run); _shared + _diff are helpers
test/               node:test suite (node --test "test/*.test.mjs")
```

## How it works

**Auth.** The CLI runs the OAuth device flow with the Copilot client id, polls for a user token, then exchanges it at `copilot_internal/v2/token` for a short-lived Copilot token (refreshed automatically on 401). With `API_BASE` set, the device flow is skipped entirely.

**Agentic loop.** Each turn sends `messages + tools` to `/chat/completions` and streams SSE deltas. Text renders live; `tool_calls` accumulate by index, execute (read-only ones concurrently), and results return as `tool` messages for up to 16 steps. Between steps, history is trimmed to the token budget without orphaning tool pairs, every tool result is head+tail capped, and a dropped stream keeps its partial reply with an interruption marker instead of losing it.

**Rendering.** The reply re-renders as tokens arrive. Once output exceeds the screen, finished lines are committed to the scrollback and only the tail redraws — verified by a terminal simulation asserting cursor moves never leave the visible screen.

**Voice.** Mic audio is captured with ffmpeg (16kHz mono WAV), transcribed by Groq Whisper. Replies are stripped of code/markdown and spoken — via Edge neural TTS over a raw-TLS WebSocket that reproduces the official handshake (`Sec-MS-GEC` time-windowed token, `ConnectionId`, MUID cookie), or via Groq Orpheus (sentence-chunked, WAV-joined) when selected.

## Tests

```bash
npm test   # node --test "test/*.test.mjs" — core, provider, tools, voice
```

## Security notes

- Mutating tools always show a diff and ask first; `-y`/`AUTO_APPROVE` is explicit and visible per call.
- `.env` is gitignored (copy `.env.example`); tokens live in `~/.copilot-chat-cli/` with `0600` perms, never in the repo.
- `delete_file` refuses the workspace root; `move_file` refuses overwrites; `fetch_url` is text-only with byte/time caps.
