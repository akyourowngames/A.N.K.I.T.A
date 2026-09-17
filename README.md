# ankita

A coding agent and personal assistant in your terminal, powered by GitHub Copilot models. Chat, run shell commands, edit files with approval diffs, search the live web, scrape pages, talk hands-free — and let it work while you are away: scheduled briefings, watched pages, and a Telegram inbox. Zero npm dependencies.

```
ankita › search for the latest Node.js LTS release and fetch the announcement
  → web_search({"query":"latest Node.js LTS release","when":"7d"})
  → web_fetch({"url":"https://nodejs.org/en/blog/release/v24.11.0"})
  │ Node 24.11.0 is the current LTS (Krypton).
  · 3.8s · gpt-4.1 · 5.2k in / 45 out
```

## Quickstart

**Prereqs:** Node.js 18+ (Node 22+ recommended).
Optional: `ffmpeg`/`ffplay` on PATH for voice (`winget install Gyan.FFmpeg`), and Python 3 + `pip install scrapling` for the stealth scraping tier.

```bash
node chat.mjs
# or
npm start
```

First run prints a code and opens `github.com/login/device` — sign in once and the token is cached (`~/.copilot-chat-cli/auth.json`, mode `0600`). Every later run skips login.

```bash
ankita -p "summarise what this repo does"        # one-shot
ankita --voice                                   # hands-free conversation
ankita --api-base http://localhost:11434/v1      # local models via Ollama
```

## What it can do

- **Chat** with streaming markdown replies (syntax-highlighted code boxes, tables) that re-render live without garbling, even on long answers
- **Act** through 20 tools: shell (foreground + background jobs), file read/write/edit (string, atomic multi-edit, or by line number), search, glob, mkdir/move/delete, raw fetch, todo lists — every mutating call shows a unified `@@` diff and asks first
- **Know the internet**: `web_search` (keyless, five fused backends) plus `web_fetch` and three scraping tiers that escalate from plain HTTP to a headless stealth browser to a multi-page crawl
- **Talk**: `/mic` dictates via Groq Whisper, `/voice` runs a hands-free loop, replies are spoken with Edge neural TTS (Aria) or Groq Orpheus
- **Works while you are away**: `ankita --daemon` runs scheduled routines, watches pages for changes, and answers Telegram messages — see [The proactive assistant](#the-proactive-assistant)
- **Remember**: named sessions, autosave after every turn, `--continue`, sanitized restores, persistent history, tab-completion
- **Run anywhere**: interactive REPL, one-shot `-p`, script-friendly `--plain` / `--json`, or any OpenAI-compatible endpoint (Ollama, LM Studio, OpenRouter, …)

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
      --daemon          run in the background: schedules, watches, Telegram inbox
      --brief           print a briefing now and exit
```

Slash commands: `/help /config /reload /models /model /tools /auto /cd /save /load /sessions /paste /usage /mic /voice /say /speak /voices /brief /routines /watches /daemon /clear /exit`.

## Configuration

`.env` in the working directory, falling back to `~/.copilot-chat-cli/config.env`. Values in files beat environment variables (Windows already defines `USERNAME`, which would otherwise shadow yours). `/reload` picks up edits live. See `.env.example` for the annotated list.

| Key | Default | What |
|---|---|---|
| `USERNAME` / `AGENT_NAME` | `user` / `assistant` | Names used in prompts and replies |
| `MODEL` | auto | Pinned model, else best capable default |
| `TOOLS` / `AUTO_APPROVE` | `on` / `off` | Tool use and the y/n approval gate |
| `HISTORY_MESSAGES` | `40` | Turns kept in context (`HISTORY_LINES` still works) |
| `MAX_TOKENS` / `MAX_TOOL_CHARS` / `CONTEXT_WINDOW` | `4096` / `65536` / `32768` | Output cap, per-result context cap, trim budget |
| `INPUT_COST_PER_MILLION` / `OUTPUT_COST_PER_MILLION` | unset | Enables `$` estimates in `/usage` |
| `API_BASE` / `API_KEY` | unset | OpenAI-compatible endpoint instead of Copilot |
| `GROQ_API_KEY` / `STT_MODEL` | unset / `whisper-large-v3-turbo` | Mic transcription (free key at console.groq.com) |
| `TTS_PROVIDER` | `edge` | `edge`, `groq`, or `auto` (groq when a key exists) |
| `TTS_MODEL` / `TTS_VOICE` | `canopylabs/orpheus-v1-english` / provider default | `tara` on groq, `en-US-AriaNeural` on edge — see `/voices` |
| `TTS_RATE` / `SPEAK` / `MIC_DEVICE` | `+0%` / `off` / auto | Edge speech rate, auto-speak replies, preferred mic |
| `ANKITA_NO_WEB` / `ANKITA_NO_SCRAPE` | unset | Kill switches for web and scraping |
| `WEB_TIMEOUT` / `WEB_MAX_OUTPUT` / `WEB_CACHE_TTL` / `WEB_RETRIES` | `20` / `8000` / `300` / `1` | Search + fetch timeouts, output caps, result cache, retries |
| `WEB_REGION` / `JINA_FALLBACK` | `wt-wt` / `1` | Search region; use `r.jina.ai` when extraction is thin |
| `SCRAPE_TIMEOUT` / `SCRAPE_STEALTH_TIMEOUT` | `30` / `30` | Static and browser timeouts (seconds) |
| `SCRAPE_MAX_OUTPUT` / `SCRAPE_MAX_PAGES` / `SCRAPE_RETRIES` | `8000` / `20` / `1` | Scrape caps |
| `PYTHON_BIN` | auto | Interpreter for the Scrapling bridge |
| `PS_STRICT` | `1` | PowerShell stops on first error (set `0` for lenient) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | unset | Bot + your chat for the inbox and outbound alerts |
| `TELEGRAM_ALLOWED_CHAT_IDS` | `TELEGRAM_CHAT_ID` | Who may talk to the bot; empty means nobody |
| `TELEGRAM_VOICE_REPLY` | `off` | Answer voice notes with a spoken reply |
| `TELEGRAM_CONFIRM_TIMEOUT` | `300` | Seconds to wait for a Telegram approval before skipping |
| `DAEMON_TICK` / `BRIEFING_PROMPT` | `20` / built in | Scheduler tick seconds; what `--brief` asks for |

## Tools

| Tool | Does |
|---|---|
| `run_command` | Shell (pwsh/`sh`), stdin, env, timeout, 64KB bounded output, background jobs |
| `read_file` / `write_file` | Numbered reads; atomic create/overwrite with overwrite diff |
| `edit_file` | Exact string edits, atomic multi-edit, fuzzy fallback ladder (line-endings → trailing whitespace → indentation), refuses ambiguity |
| `edit_lines` | Line-range replace/insert/delete, validated atomically |
| `list_dir` / `glob` / `search_files` | Browse (recursive), find by glob, regex search with excludes — all read-only, run in parallel |
| `create_dir` / `move_file` / `delete_file` | Filesystem verbs (root-protected, no silent overwrites) |
| `fetch_url` | Byte-capped, timed raw HTTP(S) fetch for APIs/exact content |
| `web_search` | Keyless live search (DuckDuckGo + Wikipedia + news + HN + Reddit), fused and de-duped |
| `web_fetch` | Read a page as text, Jina reader fallback when extraction is thin |
| `scrape_low` | One simple page, static fetch with browser impersonation |
| `scrape_mid` | Blocked/JS pages (auto stealth browser) or named CSS/XPath fields |
| `scrape_high` | Multi-page BFS crawl (depth≤2, ≤20 pages, same-domain default) |
| `schedule` | Create/list/pause recurring prompts ("every weekday at 8, brief me") |
| `watch` | Track a page or a number on it (signups, logins, prices) and report changes |
| `github_notifications` | Your GitHub inbox: mentions, review requests, invitations |
| `write_todos` | Session checklist for multi-step work |
| `job_status` / `job_stop` | Read and stop background jobs |

Read-only tools skip approval and execute concurrently; mutations are sequential barriers and always confirm first.

### Working outside the project directory

The agent is **not** confined to the working directory — any absolute path works, and every path a tool prints is one it can feed straight back into the next call. Search results outside the cwd come back absolute (results inside stay cwd-relative for brevity), so a `glob` over `C:\Users\you` yields paths that `read_file` and `run_command` can use directly instead of paths relative to the search root that nothing else can resolve.

When a tool fails the agent diagnoses and retries with a corrected path, quoting, or command before reporting a problem. On Windows this is backed by `$ErrorActionPreference='Stop'`, because PowerShell otherwise continues past a non-terminating error and still exits `0` — so a failed command used to look like success. A single command can still opt out with `-ErrorAction SilentlyContinue`.

## Architecture

```
chat.mjs              thin entry (arg parsing lives in cli)
src/
  cli.mjs             REPL, slash commands, sessions, --json/--plain, voice loop
  agent.mjs           tool-calling loop: stream → tool_calls → execute → repeat
  provider.mjs        model picking + CompatibleClient (any OpenAI-style API)
  auth.mjs            GitHub device flow → short-lived Copilot token
  config.mjs          layered .env (project > global > env > defaults)
  history.mjs         sanitize + budget-aware trimming (never splits tool pairs)
  markdown.mjs        streaming markdown renderer (LiveRenderer commits scrollback)
  net.mjs             fetch with selective retry (429/5xx + transient sockets only)
  ui.mjs              terminal I/O, colors, banner, completion
  voice.mjs           mic record, Groq STT, Edge/Groq TTS, audio conversion
  cron.mjs            cron parsing/matching plus "every 30m" / "daily 08:00" shorthands
  routines.mjs        durable store: schedules, watches, readings, change detection
  watcher.mjs         page fetch + value extraction, shared by tool and daemon
  telegram.mjs        Bot API long-polling, allowlist, message splitting
  daemon.mjs          the proactive loop: routines + watches + inbox → agent
scripts/
  scrape_bridge.py    stdlib Python bridge to Scrapling (JSON argv → JSON stdout)
tools/
  index.mjs           registry (specs/get/names) + job cleanup
  _shared.mjs         paths, atomic writes, bounded output, globbing
  _diff.mjs           LCS diff → hunks → colored unified diff
  _web.mjs            SSRF guard, TTL cache, retrying HTTP, HTML entities, bridge spawn
  *.mjs               one self-contained module per tool (name / description /
                      parameters / approval / run)
test/                 node:test suite — core, provider, tools, voice, web
```

## How it works

**Auth.** The CLI runs the OAuth device flow with the Copilot client id, polls for a user token, then exchanges it at `copilot_internal/v2/token` for a short-lived Copilot token (refreshed automatically on 401). With `API_BASE` set, the device flow is skipped entirely.

**Agentic loop.** Each turn sends `messages + tools` to `/chat/completions` and streams SSE deltas. Text renders live; `tool_calls` accumulate by index, execute (read-only ones concurrently as a batch, mutations as barriers), and results return as `tool` messages for up to 16 steps. Between steps, history is trimmed to the token budget without orphaning tool pairs, every tool result is head+tail capped, and a dropped stream keeps its partial reply with an interruption marker instead of losing it.

**Rendering.** The reply re-renders as tokens arrive. Once output exceeds the screen, finished lines are committed to the scrollback and only the tail redraws — verified by a terminal simulation asserting cursor moves never leave the visible screen.

**Web.** `web_search` fans out to DuckDuckGo (with a lite fallback when the HTML endpoint 202s), Google News RSS, Wikipedia, Hacker News and Reddit, then fuses and de-dupes by normalized URL. `web_fetch` extracts readable text without a DOM, drops comments/CDATA/declarations, and falls back to `r.jina.ai` when the page is a script shell. Both share a TTL cache keyed on normalized URL.

**Scraping.** Tiers mirror what the task needs: `scrape_low` is a fast static fetch with Chrome impersonation, `scrape_mid` escalates to a headless stealth browser on block signals (403/429/503 or a thin body) or extracts named fields via CSS/`xpath:`, `scrape_high` runs a bounded BFS crawl reusing per-page escalation. Node drives Scrapling through `scripts/scrape_bridge.py` — one JSON argument in, one JSON document out, UTF-8 forced on both ends so non-ASCII page content (Wikipedia's zero-width spaces) can't kill the process on a Windows codepage.

**SSRF guard.** Every web tool resolves the host and refuses loopback, private, link-local and other non-global addresses, failing closed when DNS doesn't resolve. Redirect chains are re-checked hop by hop, on both the Node and Python sides.

**Voice.** Mic audio is captured with ffmpeg (16kHz mono WAV), transcribed by Groq Whisper. Replies are stripped of code/markdown and spoken — via Edge neural TTS over a raw-TLS WebSocket that reproduces the official handshake (`Sec-MS-GEC` time-windowed token, `ConnectionId`, MUID cookie), or via Groq Orpheus (sentence-chunked, WAV-joined) when selected.

## The proactive assistant

`ankita --daemon` turns the agent into something that works while you are away. It runs three loops against the same tools the REPL uses:

**Routines** are prompts on a schedule. Ask in plain language — *"every weekday at 8, brief me on my GitHub inbox and any watch changes"* — and the agent sets it up itself:

```
ankita › remind me every morning at 8 about my inbox
  → schedule({"action":"add","name":"Morning briefing","cron":"weekdays 08:00","prompt":"..."})
    Scheduled "Morning briefing" (morning-briefing) - weekdays at 08:00
```

`cron` accepts standard five-field expressions, shorthands (`every 30m`, `daily 08:00`, `weekdays 09:30`) and `@daily`/`@hourly`. Results are delivered to Telegram when configured, otherwise printed locally.

**Watches** track a page — or one number on it — and alert only when something moves:

```
ankita › tell me if the signups on https://my.app/dashboard change
  → watch({"action":"add","url":"...","regex":"([\\d,]+)\\s+users","interval":"1h"})
    First reading: 1,204
```

The first read is a baseline, so you get `Signups: 1,204 → 1,227 (+23)` rather than a spurious alert. A `regex` (capture group 1) or a CSS `selector` narrows the watch to a value; without either, the whole page is hashed and any edit is reported. Selector watches go through the scrape tiers, so Cloudflare-protected dashboards still work.

**The Telegram inbox** lets you talk to ankita from your phone: text or voice notes in (Whisper), replies out (text, or spoken with `TELEGRAM_VOICE_REPLY=1`). Only chat ids in `TELEGRAM_ALLOWED_CHAT_IDS` are served; anyone else gets their own id back so you can add it.

**Approvals come to your phone.** A DM cannot answer a terminal y/n prompt, so when a requested action would change something, ankita sends you the diff in the chat and parks the turn until you reply:

```
Permission needed: write_file

notes/plan.md  +12 -0

Reply y = allow once, a = always, n = deny
(times out in 5 min)
```

`y` allows it once, `a` allows it for the rest of the session, anything else (or no reply) skips it. The approval reply is consumed, not treated as a new request, and the poll loop keeps running while the turn waits — so replying immediately works. Routines and `--brief` ask the same way instead of being silently denied. Set `AUTO_APPROVE=on` to skip the questions entirely.

`/brief` (or `ankita --brief`) runs the briefing prompt immediately — GitHub inbox, watch changes, anything needing a decision — and prints it or sends it to Telegram.

### One honest limitation

A Telegram **bot** only receives messages sent *to it*, plus posts in groups and channels it is a member of. It cannot read your personal DMs with other people — that needs a user-account (MTProto) client, which is a different design and a different set of ToS questions. For "DMs and invitations" from the developer side, `github_notifications` covers mentions, review requests and repo invitations. Also use a **separate bot** from any other app: Telegram delivers each update to exactly one long-poller, so two processes sharing a token silently steal each other's messages.

## Tests

```bash
npm test   # node --test "test/*.test.mjs"
```

74 tests across `core`, `provider`, `tools`, `voice`, `web` and `proactive`. The web suite runs pure parsers and guards against fixtures, stubs DNS for the SSRF checks, and skips the two live bridge tests automatically when Python/Scrapling aren't installed.

## Security notes

- Mutating tools always show a diff and ask first; `-y`/`AUTO_APPROVE` is explicit and visible per call.
- `.env` is gitignored (copy `.env.example`); tokens live in `~/.copilot-chat-cli/` with `0600` perms, never in the repo.
- `delete_file` refuses the workspace root; `move_file` refuses overwrites; `fetch_url` is text-only with byte/time caps.
- Web tools refuse non-public hosts, including via redirects. Scraping needs local Python + `pip install scrapling` for the browser tier; the static tier works anywhere the bridge runs.
