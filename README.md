# ankita

A coding agent and personal assistant in your terminal, powered by GitHub Copilot models. Chat, run shell commands, edit files with approval diffs, search the live web, scrape pages, talk hands-free — and let it work while you are away: scheduled briefings, watched pages, and a Telegram inbox. The CLI has zero runtime npm dependencies.

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

### Run it from anywhere

```bash
npm link          # once, from the repo
ankita            # now works from any folder
```

`npm link` puts `ankita` on your PATH (your npm global prefix must be on it — check with `npm config get prefix`). Because it is a link, edits to the source take effect immediately with no re-install.

Then, so it behaves the same in folders with no `.env`, put your settings in the global fallback:

```bash
cp .env ~/.copilot-chat-cli/config.env
```

Without that, running from `C:\` would fall back to defaults — and on Windows `USERNAME` is already set to your OS account name, so the agent would call you `anime` instead of whatever you chose.

Either way, from the repo:

```bash
node chat.mjs
# or
npm start
```

First run prints a code and opens `github.com/login/device` — sign in once and the token is cached (`~/.copilot-chat-cli/auth.json`, mode `0600`). Every later run skips login.

### Desktop app

The desktop app uses the same agent, configuration, models, tools, and saved GitHub login as the CLI. It adds teammate conversations with their own personas and saved threads, streaming replies, tool cards, approvals, and a model picker.

```bash
npm install
npm run desktop:dev        # Vite + Electron for development

# Or run the production bundle locally:
npm run desktop:build
npm run desktop:start
```

Run these commands from the repository root. With Copilot selected and no cached login, the desktop window shows a GitHub device code; open the verification page and enter it to sign in. Open **Settings** from the sidebar gear or with `Ctrl+,` (`Cmd+,` on macOS) to choose a model or provider, add a Composio key, test a custom OpenAI-compatible endpoint, and change the appearance. Desktop settings are saved in `~/.copilot-chat-cli/desktop-settings.json` and take priority over `.env` in the desktop app. The CLI continues to use `.env` or its global fallback.

Open **Plugins** in the sidebar to browse and search the Composio app catalog. Connect an app in your browser, see connected accounts in **Installed**, add another account, or disconnect individual accounts. Add a Composio project key in **Settings → Providers** first; without one, Plugins shows a setup link instead of an empty catalog.

**Settings → Channels** connects the app to a chat service so you can reach your agent from anywhere, starting with Telegram. Create a bot with [@BotFather](https://t.me/BotFather), paste its token, pick the teammate that should answer, and add the chat ids allowed to talk to it — an unknown chat is told its own id so you can add it. While enabled, the bridge runs with the app and routes each message to that teammate, sharing the same thread and history as the desktop; tool approvals are asked and answered in the chat. Voice notes are transcribed when a Groq key is set, and replies can be spoken back. Channel settings live in `~/.copilot-chat-cli/desktop-channels.json`. Only one process may poll a bot token at a time, so stop the CLI `--daemon` before enabling the same bot here.

Open **Projects** to record a working folder, conventions, decisions, and open tasks. Assign a project from the teammate header or when editing a teammate. That teammate uses the project's folder for file and command tools and receives a short project brief. The **Work review** button in chat opens Git changes with file diffs, recent artifacts, and command jobs with output and a stop action; file edits open it automatically. The agent allows at most six `web_search` calls per user request, then uses the sources already gathered.

```bash
ankita -p "summarise what this repo does"        # one-shot
ankita --voice                                   # hands-free conversation
ankita --api-base http://localhost:11434/v1      # local models via Ollama
```

## What it can do

- **Chat** with streaming markdown replies (syntax-highlighted code boxes, tables) that re-render live without garbling, even on long answers
- **Act** through 24 tools: shell (foreground + background jobs), file read/write/edit (string, atomic multi-edit, or by line number), search, glob, mkdir/move/delete, raw fetch, todo lists — every mutating call shows a unified `@@` diff and asks first
- **Know the internet**: `web_search` (keyless, five fused backends) plus `web_fetch` and three scraping tiers that escalate from plain HTTP to a headless stealth browser to a multi-page crawl
- **Talk**: `/mic` dictates via Groq Whisper, `/voice` runs a hands-free loop, replies are spoken with Edge neural TTS (Aria) or Groq Orpheus
- **Knows your projects**: tell her about one — a folder, a server, a client — and she keeps the details, the conventions and the open questions, and stops asking you the same things
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

Slash commands: `/help /config /reload /models /model /tools /auto /cd /save /load /sessions /paste /usage /mic /voice /say /speak /voices /brief /routines /watches /daemon /project /projects /clear /exit`.

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
| `PROVIDER` | `copilot` | Backend: `copilot`, `groq` (low latency; reuses `GROQ_API_KEY`, defaults to `openai/gpt-oss-120b`), or `kilo` — the [Kilo AI Gateway](https://kilo.ai/docs/gateway) with free, keyless models (`nex-agi/nex-n2.5-mini:free` by default) |
| `API_BASE` / `API_KEY` | unset | OpenAI-compatible endpoint instead of Copilot (always wins over `PROVIDER`) |
| `TOOL_PROVIDER` / `TOOL_MODEL` | unset | Split the turn: the main model handles chat and the first tool decision, and once a turn uses a tool this model runs the rest of the loop (e.g. `kilo` + `nex-agi/nex-n2.5-mini:free`) while the main model writes the reply. Blank = one model for everything |
| `GROQ_API_KEY` / `STT_MODEL` | unset / `whisper-large-v3-turbo` | Mic transcription (free key at console.groq.com) |
| `TTS_PROVIDER` | `edge` | `edge`, `groq`, or `auto` (groq when a key exists) |
| `TTS_MODEL` / `TTS_VOICE` | `canopylabs/orpheus-v1-english` / provider default | `tara` on groq, `en-US-AriaNeural` on edge — see `/voices` |
| `TTS_RATE` / `SPEAK` / `MIC_DEVICE` | `+0%` / `off` / auto | Edge speech rate, auto-speak replies, preferred mic |
| `VOICE_VAD` / `VOICE_SILENCE_MS` / `VOICE_NOISE_DB` | `on` / `1200` / `-35` | Hands-free turn-taking: auto-send on a pause (ffmpeg `silencedetect`) |
| `VOICE_BARGE_IN` / `VOICE_BARGE_DB` | `on` / `-25` | Interrupt a spoken reply by talking over it |
| `VOICE_HFP_ROUTING` | `on` | Keep Bluetooth speech audible while the mic is open (routes playback to the headset's Hands-Free endpoint) |
| `VOICE_ADDRESS` / `VOICE_SPEAK_ITEMS` / `VOICE_SPEAK_SENTENCES` / `VOICE_SPEAK_MAX_CHARS` / `VOICE_FULL_READ` | `sir` / `8` / `6` / `1200` / `off` | Spoken-reply shaping for long lists and paragraphs |
| `VOICE_SUMMARY_NOTE` | `{address}, that's {spoken} of {total}. The rest is on your screen, {address}.` | Template for the "rest is on screen" note |
| `ANKITA_NO_WEB` / `ANKITA_NO_SCRAPE` | unset | Kill switches for web and scraping |
| `WEB_TIMEOUT` / `WEB_MAX_OUTPUT` / `WEB_CACHE_TTL` / `WEB_RETRIES` | `20` / `8000` / `300` / `1` | Search + fetch timeouts, output caps, result cache, retries |
| `WEB_REGION` / `JINA_FALLBACK` | `wt-wt` / `1` | Search region; use `r.jina.ai` when extraction is thin |
| `ALLOW_PRIVATE_HOSTS` | `off` | Opt in to loopback/LAN pages — for watching your own dev server |
| `SCRAPE_TIMEOUT` / `SCRAPE_STEALTH_TIMEOUT` | `30` / `30` | Static and browser timeouts (seconds) |
| `SCRAPE_MAX_OUTPUT` / `SCRAPE_MAX_PAGES` / `SCRAPE_RETRIES` | `8000` / `20` / `1` | Scrape caps |
| `PYTHON_BIN` | auto | Interpreter for the Scrapling bridge |
| `PS_STRICT` | `1` | PowerShell stops on first error (set `0` for lenient) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | unset | Bot + your chat for the inbox and outbound alerts |
| `TELEGRAM_ALLOWED_CHAT_IDS` | `TELEGRAM_CHAT_ID` | Who may talk to the bot; empty means nobody |
| `TELEGRAM_VOICE_REPLY` | `off` | Answer voice notes with a spoken reply |
| `TELEGRAM_CONFIRM_TIMEOUT` | `300` | Seconds to wait for a Telegram approval before skipping |
| `DAEMON_TICK` / `BRIEFING_PROMPT` | `20` / built in | Scheduler tick seconds; what `--brief` asks for |
| `MAX_CONCURRENT` | `4` | Routines that may run at once (everything at 08:00 would otherwise stampede the API) |
| `WATCH_ALERT_LLM` / `WATCH_ALERT_PROMPT` | `on` / built in | Model-written alerts; override the wording with placeholders |

## Tools

| Tool | Does |
|---|---|
| `run_command` | Shell (PowerShell/`sh`), stdin/env, bounded output; yields a live job after 1 second by default |
| `read_file` / `write_file` | Numbered reads; atomic create/overwrite with overwrite diff |
| `edit_file` | Exact string edits, atomic multi-edit, fuzzy fallback ladder (line-endings → trailing whitespace → indentation), refuses ambiguity |
| `edit_lines` | Line-range replace/insert/delete, validated atomically |
| `apply_patch` | Unified multi-file/multi-hunk diffs, renames, additions/deletions; validates first, stages writes and rolls back failures |
| `list_dir` / `glob` / `search_files` | Browse (recursive), find by glob, regex search with excludes — all read-only, run in parallel |
| `create_dir` / `move_file` / `delete_file` | Filesystem verbs (root-protected, no silent overwrites) |
| `http_request` | HTTP methods, headers, JSON/form/raw bodies, bearer/basic auth, status/headers, redirect policy and text/base64 responses |
| `git` | Deferred `git` group: status/diff/log/show/blame/branch/checkout/stage/unstage/commit/stash/restore |
| `port_status` / `kill_process` | Deferred `process` group: port owners and approved PID/port termination with identity rechecks |
| `web_search` | Keyless live search (DuckDuckGo + Wikipedia + news + HN + Reddit), fused and de-duped |
| `web_fetch` | Read a page as text, Jina reader fallback when extraction is thin |
| `scrape_low` | One simple page, static fetch with browser impersonation |
| `scrape_mid` | Blocked/JS pages (auto stealth browser) or named CSS/XPath fields |
| `scrape_high` | Multi-page BFS crawl (depth≤2, ≤20 pages, same-domain default) |
| `mcp_manage` | Add/list/remove/enable/disable MCP servers — extra tools from external processes |
| `composio` | Manage connected apps, accounts, and authorization links |
| `project` | Add/list/show/switch/rename/archive projects; records what each one is, where it lives, how you like it done, who the client is |
| `project_memory` | Remember notes, decisions and open todos per project; `log` shows the timeline, `brief` hands over a catch-up |
| `schedule` | Create/list/pause recurring prompts ("every weekday at 8, brief me") |
| `watch` | Track a page or a number on it (signups, logins, prices) and report changes |
| `github_notifications` | Your GitHub inbox: mentions, review requests, invitations |
| `write_todos` | Session checklist for multi-step work |
| `job_status` / `job_wait` | List jobs, read incremental output by byte cursor or tail, and wait briefly |
| `job_input` / `job_stop` | Send stdin/EOF and stop session-owned background jobs |

Read-only actions skip approval and execute concurrently; mutations are sequential barriers and show a preview unless auto-approval is enabled. Git and HTTP choose their approval behavior by action/method. Stopping an existing session job is available without an extra prompt. `fetch_url` remains callable for old transcripts; new tool schemas offer `http_request`.

### Background commands you can control

`run_command` waits up to `yield_ms=1000`, then returns a job ID if the command is still running. The command keeps running while the assistant continues other work or replies. `background:true` returns immediately. `timeout_ms` is a separate, optional execution deadline; servers have no automatic one-minute lifetime. Use `yield_ms` up to 10000 when a short command's result is needed immediately.

The interactive CLI prints start/completion notices and shows the active job count in its prompt. These commands work without a model call, including while the assistant is busy:

```text
/bg npm run dev
/jobs
/job 1
/job 1 0
/input 1 yes
/eof 1
/wait 1 1000
/stop 1
```

`/job` reads only new output; offset `0` replays retained output. Tool calls can specify `since_offset`, `max_bytes`, or `tail` (lines). Results include absolute `next_offset`, `dropped` byte counts and `more`, so log rollover is explicit. `job_wait` caps each wait at 10 seconds and cancellation stops waiting without killing the job. `job_input` sends exact text; `/input` adds a newline. Supplied foreground stdin closes after writing unless `keep_stdin_open:true`; background stdin stays open unless explicitly closed.

Jobs belong to the current CLI session, survive conversation clearing, and stop when that session exits. They are not restored from saved transcripts. Retention is bounded to 100 jobs and 32 simultaneously running commands. Input/output use pipes: line-based prompts work; full-screen terminals and programs requiring a real TTY need a separate terminal. No terminal-emulation dependency is installed.

### Structured developer actions

Load `git` or `process` with `find_tools`. Git uses literal paths and shell-free arguments; read-only status/history/diffs run without prompts, while stage/unstage/commit/checkout/restore and branch/stash changes show their commands. `port_status` inspects a port; `kill_process` accepts exactly one PID or port, shows process identities, and rechecks them before termination. Windows uses `netstat -ano` and `taskkill /T`.

`apply_patch` accepts standard unified diffs with Git rename metadata. It validates every file and hunk before writing, preserves line endings and newline markers, stages replacements and rolls back ordinary write failures. Multi-file visibility is not simultaneous and power-loss recovery is not guaranteed. If rollback fails, recovery backups are retained and reported. Binary patches, symlinks and moves that overwrite an existing destination are rejected. Patch paths stay within the working directory; other filesystem tools retain their absolute-path support.

`http_request` supports localhost development APIs, custom methods/headers, one of `json`, `form`, or raw `body`, and `auth` with bearer/basic credentials. Responses contain status, headers and a bounded body even for HTTP errors; `expected_status` makes mismatches explicit. Redirect policy is `follow`, `manual`, or `error`; cross-origin redirects strip credentials, HTTPS downgrade is rejected, and mutations are not automatically replayed (303 can follow as GET). One deadline covers redirects and streaming. Request auth is redacted in traces, while response headers/body remain available for API workflows.

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

**Agentic loop.** Each turn sends `messages + tools` to `/chat/completions` and streams SSE deltas. Text renders live; `tool_calls` accumulate by index, execute (read-only ones concurrently as a batch, mutations as barriers), and results return as `tool` messages for up to 16 steps. Between steps, history is trimmed to the token budget without orphaning tool pairs, every tool result is head+tail capped, and a dropped stream keeps its partial reply with an interruption marker instead of losing it. Every declared `tool_call` gets exactly one reply even when the tool throws, when a UI callback throws, or when you cancel mid-batch — an unanswered call makes the API reject the entire next request, which would end the session rather than fail one step.

**Two-model turns.** With `TOOL_PROVIDER` set, the primary model handles chat and the first tool decision, and the tool model runs the loop. If the primary's opening response calls no tool, it is a plain chat turn and the tool model is never woken. Once a tool is called, the tool model takes over the loop *and* writes the user-facing reply (the status line shows `nex-agi/nex-n2.5-mini:free`); keeping the reply on the tool model matters because a post-tool context is large and a small per-minute token budget on the chat model would reject it. Its intermediate text is withheld from the UI, and if it never gets to write, the draft is restored rather than losing the turn. When the chat model is rate-limited (429), over its per-minute token budget (413), or returns 5xx, the call fails fast and is retried on the tool model instead of sitting out the retry backoff — so a busy free tier degrades to the other provider rather than stalling or stopping mid-turn. Tool loops run up to 100 steps.

**Rendering.** The reply re-renders as tokens arrive. Once output exceeds the screen, finished lines are committed to the scrollback and only the tail redraws — verified by a terminal simulation asserting cursor moves never leave the visible screen.

**Web.** `web_search` fans out to DuckDuckGo (with a lite fallback when the HTML endpoint 202s), Google News RSS, Wikipedia, Hacker News and Reddit, then fuses and de-dupes by normalized URL. `web_fetch` extracts readable text without a DOM, drops comments/CDATA/declarations, and falls back to `r.jina.ai` when the page is a script shell. Both share a TTL cache keyed on normalized URL.

**Scraping.** Tiers mirror what the task needs: `scrape_low` is a fast static fetch with Chrome impersonation, `scrape_mid` escalates to a headless stealth browser on block signals (403/429/503 or a thin body) or extracts named fields via CSS/`xpath:`, `scrape_high` runs a bounded BFS crawl reusing per-page escalation. Node drives Scrapling through `scripts/scrape_bridge.py` — one JSON argument in, one JSON document out, UTF-8 forced on both ends so non-ASCII page content (Wikipedia's zero-width spaces) can't kill the process on a Windows codepage.

**SSRF guard.** Every web tool resolves the host and refuses loopback, private, link-local and other non-global addresses, failing closed when DNS doesn't resolve. Redirect chains are re-checked hop by hop, on both the Node and Python sides.

**Voice.** Mic audio is captured with ffmpeg (16kHz mono WAV), transcribed by Groq Whisper. Replies are stripped of code/markdown and spoken — via Edge neural TTS over a raw-TLS WebSocket that reproduces the official handshake (`Sec-MS-GEC` time-windowed token, `ConnectionId`, MUID cookie), or via Groq Orpheus (sentence-chunked, WAV-joined) when selected.

`/voice` is hands-free: a single ffmpeg process both records and streams `silencedetect` speech boundaries, so a turn ends when you pause (no Enter) and talking over a reply barges in — playback stops and your interruption becomes the next turn. On Bluetooth headsets, capturing through the Hands-Free mic drops A2DP and would silence replies; voice mode detects the headset's matching Hands-Free playback endpoint and routes speech there for the session (`VOICE_HFP_ROUTING`, via the Windows Core Audio API with no extra dependency), then restores your device on exit. Long replies are shaped before they are spoken: the first `VOICE_SPEAK_ITEMS` list items or `VOICE_SPEAK_SENTENCES` sentences are read, then a note built from the real counts (`{address}`, `{spoken}`, `{total}`, `{remaining}`) says the rest is on screen. Every threshold and the note wording are config, not constants; `/say` and `VOICE_FULL_READ=on` read in full.

## Projects

A project is anything you keep coming back to: a folder or repo, a server and its database, a client you do work for — or all three. Only a **name** is required to start, and she asks for the rest instead of inventing it:

```
you › add this to our project
  → project({"action":"add"})
ankita › Which project shall I add? I don't know any yet.

you › zumba, it's my telegram assistant at C:\Users\anime\zumba
  → project({"action":"add","name":"zumba","path":"C:\\Users\\anime\\zumba"})
    Added project "zumba" and made it the active project.
    Worth asking about: what it is, which database, which servers, how you like things done.
ankita › Saved. What is zumba, and does it use a database?
```

The rest fills in as you go, with `update` or just by telling her:

```
you › remember we use pnpm here, not npm
  → project({"action":"update","name":"zumba","convention":"pnpm not npm"})
```

Once a project is active, a short block carries into her system prompt, so she simply knows:

```
Active project: zumba (zumba)
  what it is: My Telegram personal assistant (Python/FastAPI)
  path: C:\Users\anime\zumba
  conventions: pnpm not npm; edge-tts for voice
  databases: sqlite memory
```

Ask *"which project am I on and how do I like things done here?"* and she answers without touching a single tool. `/project <name>` switches, `/projects` lists, `/project` shows the active one, and switching `cd`s into the project's path if it has one. Adding a project makes it active automatically — you were clearly about to work on it.

Databases and environments record a credential **name**, never a value — nothing secret is stored. `project action=forget` removes the record and touches nothing on disk.

### It remembers what you did together

Notes, decisions and open items, each dated, so a project has a state beyond its fields:

```
you › remember we chose SQLite because there's nothing to run
  → project_memory({"action":"decide","text":"chose SQLite - single writer, nothing to run"})
ankita › Decision recorded on "Zumba Bot". (2 notes, 3 decisions, 2 open)

you › where does zumba stand?
  → project_memory({"action":"brief"})
ankita › The Zumba Bot project is progressing well, Krish. It's your local-first Telegram
         assistant... Voice now works end to end. SQLite was chosen for memory, consistent
         with staying local-first. Open: rotate the exposed Groq key, wire project tags into
         the daemon worker. Worth deciding next is which environments it runs on - still unknown.
```

`log` is the raw timeline; `brief` assembles everything — tasks, decisions, recent notes, plus that project's own routines and watches — and the **model** writes the catch-up from it. A tool can't call a model, so `brief` returns the material and the writing happens in the reply. That also means it only costs tokens when you ask.

`done` closes an item by id (`t2`), by its number among the open ones, or by part of its text — and refuses to guess when a reference is ambiguous, listing the candidates instead.

**Project memory never enters the system prompt.** Only the name, summary, path and conventions do. Ten notes later the block is still the same size — otherwise every turn would pay for history you didn't ask for. This is exactly why `brief` exists as the deliberate, opt-in way to pull memory into context. Personal memory has a separate, strictly bounded exception for explicitly pinned preferences, described below.

Lists are capped (50 notes, 50 decisions, 100 todos, newest kept) and `show` says when older entries were dropped.

The block is capped (200-char summary, 5 conventions) because it is paid on every turn alongside the tool specs.

## Personal memory and recall

Personal facts live in `~/.copilot-chat-cli/profile.json` (or `CONFIG_DIR`), independently of projects. Ask naturally; the model chooses when to call `remember` and `recall`. These compact tools in the `personal` catalog group are available in the first request, so memory does not require a `find_tools` round trip:

```text
you › Remember I always want PowerShell, and avoid em dashes in replies.
  → remember({"action":"add","text":"Use PowerShell","kind":"preference","always":true})
  → remember({"action":"add","text":"Avoid em dashes in replies","kind":"style","always":true})
you › What do you know about me?
  → remember({"action":"list"})
you › What did we decide about backups?
  → recall({"query":"backups"})
```

`remember` supports `add`, `list`, `update` and `forget`. Corrections and deletion use stable IDs returned by `list`; `always: false` unpins a fact. Only the latest **12 facts explicitly marked `always: true`**, each limited to **160 characters**, enter the permanent system block. Full text stays on disk. Prompt refresh checks the file timestamp and reuses the bounded block when unchanged; it makes no model request.

`recall` searches personal facts, project notes, decisions, todos and session summaries, returning source information. Optional `project`, `offset` and `limit` narrow or page results. Search uses local lexical ranking; when wording has no overlap, it returns a bounded page of stored candidates explicitly marked as a browse fallback. The conversational model judges relevance, reformulates terms or paginates. A small fact-count indicator tells fresh sessions that unpinned memory exists without injecting its contents. The model is instructed to check memory before personal recommendations or asking users to repeat preferences, and to save through a successful tool call before claiming anything was remembered. There is no topic-specific router, embedding service or hidden classification model call.

Fresh turns perform personal recall before contacting the reply model, so using memory does not depend solely on the model remembering to search. Up to six candidates fit within `MEMORY_RECALL_CHARS=1600` UTF-8 bytes of temporary tool-result content. The query and candidate bundle are bounded, count against the context budget, and never accumulate in history/autosaves or the system prompt. The model decides whether they matter and can request more. This removes a chat-model round trip when the candidates already answer the request. Set `MEMORY_RECALL_CHARS=0` for exclusively model-requested recall. Unpinned memory is never promoted to a permanent prompt block.

That automatic recall must not turn a slow embedding provider into a slow reply. It waits at most `MEMORY_RECALL_BUDGET_MS=300` for the semantic ranking; if the provider has not answered by then it uses local lexical candidates for this turn and lets the query embedding finish in the background, where it is cached so a model-requested `recall` is still semantic and instant. At boot, one throwaway embedding request warms DNS/TLS and any provider cold start so the first real turn does not pay for it. Set `MEMORY_RECALL_BUDGET_MS=0` to wait for embeddings on every turn (the old behaviour); raise it if you would rather block longer for semantic ordering.

For **semantic recall**, set these in `~/.copilot-chat-cli/config.env`:

```dotenv
CLOUDFLARE_ACCOUNT_ID=your-account-id
CLOUDFLARE_API_TOKEN=your-workers-ai-token
EMBED_MODEL=@cf/qwen/qwen3-embedding-0.6b
```

Cloudflare Workers AI embeds the query and memories; cosine similarity ranks paraphrases without topic rules. The same `recall` tool searches personal facts, project notes/decisions/todos, and session summaries. Project filters apply before embedding and ranking. Query instructions are configurable with `EMBED_QUERY_INSTRUCTION`; the reply model still decides whether a candidate is relevant. The hosted model's current [Cloudflare reference](https://developers.cloudflare.com/workers-ai/models/qwen3-embedding-0.6b/) lists an 8,192-token window. Embedding inputs are capped at 6,000 UTF-8 bytes each; full memories remain stored and available to recall.

Document vectors are cached atomically under `~/.copilot-chat-cli/embeddings/`, keyed by model and content hash. New and edited memories get new vectors; deleted memories are excluded using the current source stores. Startup, memory writes and completed consolidation warm the cache in the background, in batches of 32, within `EMBED_INDEX_TIMEOUT_MS=30000`. Repeated queries reuse an in-process cache of 128 vectors. A warm search normally makes one embedding request and no extra chat-model request. Uncached foreground work shares a strict `EMBED_TIMEOUT_MS=2000` budget; slow or unavailable Cloudflare falls back to local recall, and failed services back off for 30 seconds. Partial indexes report `hybrid` with coverage; complete indexes report `semantic`. Cold indexing progresses across searches and background passes.

Configuring Cloudflare sends memory text and search queries to Cloudflare for embedding. This does not upload raw session transcripts. The vector cache contains derived vectors and hashes, not plaintext memories, queries, or credentials. Old vector cache files can remain after edits/deletions but cannot participate in recall without a current source record; deleting the `embeddings/` directory safely rebuilds them. `EMBEDDINGS=off` disables all embedding requests and uses local recall. `--config` redacts the API token. No new dependencies are required.

Live semantic verification with synthetic memories: `node scripts/verify-embeddings.mjs --live --timeout-ms=15000`. The longer verification deadline measures actual provider latency; normal chat retains its configured foreground deadline.

With `ankita --daemon`, `MEMORY_CONSOLIDATION=on` (default) processes yesterday and older unprocessed transcripts after `MEMORY_CONSOLIDATION_HOUR` (default **03:00**, in `TIMEZONE` or system local time). New CLI and Telegram turns are journaled under `sessions/journal/`; old saved sessions and autosaves are also read. A journal preserves completed user/final-assistant exchanges before autosave replacement or history trimming. Existing legacy autosaves are archived on the first journaled replacement.

The configured model extracts durable facts, project decisions and open/completed tasks as structured JSON. It gets no executable tools, must cite transcript evidence, and cannot automatically pin facts. Validated writes use the same `remember` and `project_memory` operations as chat. Project memory is only written when the transcript has an unambiguous project ID. One-line summaries and crash-recovery checkpoints live in `memory-index.json`; replay does not duplicate completed batches. Newer explicit personal corrections take precedence over old transcripts. Forgetting keeps no deleted text: a deletion timestamp prevents **all older transcripts from creating personal facts again**, while newer conversations and explicit `remember` requests can still add them. Raw sessions and their historical summaries remain separate records.

Maintenance starts when the daemon is idle, does not occupy a chat concurrency slot, and processes at most `MEMORY_BATCH_SIZE=4` chunks per run (`MEMORY_CHUNK_CHARS=12000`, `MEMORY_TIMEOUT=60` seconds per model call). Backlogs continue on later ticks; empty scans and failures back off for an hour. Chat adds bounded recall and a journal write, with no extra classification or consolidation model call. Set `MEMORY_CONSOLIDATION=off` to disable automatic journaling and consolidation; personal memory still works. Journals and summaries remain local until a consolidation batch sends its transcript to your configured model provider; configuring embeddings also sends extracted memories and summary text to Cloudflare. They have no automatic retention deletion.

## Notification delivery

Proactive messages try **Telegram → configured HTTP service → desktop → terminal**, falling through when a channel fails. HTTP services are optional and use built-in `fetch`: [ntfy publishing](https://docs.ntfy.sh/publish/) via `NTFY_URL` and optional `NTFY_TOKEN`, Discord via `DISCORD_WEBHOOK_URL`, or [Pushover](https://pushover.net/api) via `PUSHOVER_TOKEN` plus `PUSHOVER_USER`. If several are configured, ntfy takes precedence, then Discord, then Pushover. Discord mentions are disabled. `NOTIFY_TIMEOUT=10` bounds each HTTP request.

Windows uses an existing `New-BurntToastNotification` command when available, otherwise the built-in [taskbar balloon API](https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.notifyicon.showballoontip). Nothing is installed. macOS uses [`osascript` notifications](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/DisplayNotifications.html); Linux uses an installed `notify-send`. Desktop submission cannot guarantee display when the OS suppresses notifications. Set `DESKTOP_NOTIFICATIONS=off` to disable it.

`QUIET_HOURS=22:00-08:00` holds proactive messages in `notification-queue.json`, including across restarts; `TIMEZONE=Asia/Kolkata` is an example IANA timezone, not a hardcoded user preference. After quiet hours, pending messages are combined into digests. Completed routine/watch messages batch at daemon ticks; large digests split to channel limits. Telegram chat replies and approval questions stay immediate. The daemon must be running to flush queued notifications. Equal quiet-hour endpoints disable the quiet interval.

Run `node --test "test/*.test.mjs"` for automated checks. `node scripts/verify-personal-memory.mjs --live` also checks real model tool selection, fresh-session memory, extraction, recall and replay using synthetic data in a temporary config directory and your configured provider credentials.

## Connected apps (Composio)

Set `COMPOSIO_API_KEY=ak_...` in `.env` or `~/.copilot-chat-cli/config.env`, then restart Ankita. The key stays in that environment file. Ankita creates a Composio session, saves its user and session IDs in `~/.copilot-chat-cli/composio.json`, and connects Composio's HTTP MCP endpoint automatically. The agent can find connected app tools with `COMPOSIO_SEARCH_TOOLS`, inspect their schemas, and call them.

Use `/composio status`, `/composio list`, `/composio search gmail`, `/composio connect gmail`, `/composio accounts`, `/composio disconnect gmail [account-id]`, or `/composio reload`. `connect` prints an HTTPS authorization link; finish OAuth in your browser. The deferred `composio` agent tool exposes the same actions. `disconnect` revokes the upstream account grant.

Alternatively, set `COMPOSIO_BROKER_URL` for a managed broker. The client registers once and stores the installation token in `composio.json`; an explicit `COMPOSIO_BROKER_TOKEN` can be supplied. A project key takes precedence. Hosting the broker Worker is a later phase and is not included here.

**Composio MCP tools run without approval prompts, even when `AUTO_APPROVE=off`.** They can send email, post messages, edit documents, and change repositories. Only configure a Composio project whose connected accounts you want Ankita to control. Project keys are never saved in `composio.json`; that file is written with owner-only permissions where supported.

## MCP servers

Ankita can use [Model Context Protocol](https://modelcontextprotocol.io) servers — external processes that provide tools. The client supports stdio for user-added servers and streamable HTTP for Composio, with no runtime dependencies.

### Finding and installing them

Just ask. Ankita searches the [official MCP registry](https://registry.modelcontextprotocol.io), tells you what it found, and installs what you pick:

```
you › I want you to be able to drive a browser

  → mcp_manage({"action": "search", "query": "playwright"})
    8 installable match(es) for "playwright" (official MCP registry):

    - io.github.microsoft/playwright-mcp (v0.0.82)
        Playwright Tools for MCP
        command: npx @playwright/mcp@0.0.82
    ...

  → mcp_manage({"action": "install", "server": "io.github.microsoft/playwright-mcp"})
    Installed "playwright-mcp" from io.github.microsoft/playwright-mcp @ 0.0.82.
      command: npx @playwright/mcp@0.0.82

    It has NOT been started. Run action 'reload' with this id to start it.
```

Then `/mcp reload playwright-mcp` shows you that exact command and asks before anything executes. After that, ask for what you wanted:

```
you › open example.com and tell me the h1

  → find_tools({"query": "playwright-mcp"})
  → mcp__playwright-mcp__browser_navigate({"url": "https://example.com"})
  → mcp__playwright-mcp__browser_evaluate({"function": "() => document.querySelector('h1').textContent"})
The h1 heading is "Example Domain".
```

**Installing is not running, and the command is built from typed fields.** The registry returns structured package data — registry type, identifier, version, runtime arguments — not a command string, and we assemble `npx @playwright/mcp@0.0.82` from those fields with the version pinned exactly. The registry payload never picks the executable: an entry that asks for a `curl` runtime, or whose identifier contains shell metacharacters or a version range like `1.x`, is refused rather than run. Search and install touch only config; the approval gate on `reload` is what guards execution.

### Big servers load on demand

A server's tool list is sent with every request, so size matters. Playwright's 25 browser tools are ~4,700 tokens — enough on its own to push a request past the context window and fail it outright.

So a server under ~1,200 tokens (`time`, 2 tools) is always available, and a bigger one is connected but held back. The system prompt says it exists and how to load it, and `find_tools("playwright")` pulls its tools in for the rest of the session. You get the capability without paying for it on every unrelated turn.

When a browser server is connected, the prompt also carries the three things about browser automation that aren't discoverable from the tool schemas: put search terms in the URL rather than typing into a site's search box, treat `[ref=e12]` as valid only until the next page change, and use `browser_evaluate` to read a value rather than parsing a snapshot. Without them a model will retry a stale ref until you give up on it.

If a capability isn't connected at all, `find_tools` no longer dead-ends. A miss points at the registry, and the `mcp` group's catalogue line names what discovery is for — so a request to drive a browser or reach a specific service loads `mcp_manage` instead of becoming a guess at a shell command.

### Adding one by hand

```
/mcp add time uvx mcp-server-time
  registered "time"
  command: uvx mcp-server-time
  start it with:  /mcp reload time   (asks for approval first)

/mcp reload time
  ── start MCP server "time" ──────────────
  command: uvx mcp-server-time
  runs third-party code; approval is remembered for this exact command
  ─────────────────────────────────────────
  allow? [y/n] > y
  live · 2 tool(s): get_current_time, convert_time
```

Then just ask:

```
you › what time is it in Tokyo?
  → mcp__time__get_current_time({"timezone": "Asia/Tokyo"})
    { "datetime": "2026-09-20T02:01:29+09:00", "day_of_week": "Sunday" }
In Tokyo it's 2:01 AM on Sunday.
```

**Adding is separate from running.** `add` only records a command; nothing executes until you approve that exact command. Approval is remembered against a hash of `command + args`, so bumping a version `npx -y pkg@1.0.0` → `@2.0.0` asks again rather than silently running different code.

**Tools are namespaced** `mcp__<server>__<tool>`, so they can't collide with built-ins. User-added server approval follows the server's own `readOnlyHint`: only an explicit read-only hint skips the gate; anything unset or destructive asks first, and the prompt shows the command that will spawn. Composio is the configured trusted exception described above.

**Servers are process-level, not per-session.** The REPL, Telegram chats and every routine worker share one live connection — so a cron job calling an MCP tool reuses the running server instead of spawning one per invocation. The daemon reconciles against `~/.copilot-chat-cli/mcp.json` every tick, so `/mcp add` reaches a running daemon without a restart.

**Servers get a stripped environment** (PATH, HOME, SystemRoot and an explicit per-server map) — third-party code does not inherit your secrets. Teardown closes every server, including on daemon exit.

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

Detection is a hash comparison, not a diff and not a model call: fetch fresh (never from cache), extract the value, `sha256` it, compare with the stored hash. Different hash means changed; if both old and new parse as numbers you also get a delta. Because the regex picks only your number, a rotating banner elsewhere on the page cannot trigger a false alert.

**Alerts are written by the model, not a template.** Instead of `Active users: 1,305 → 1,298 (-7)` you get a sentence:

> Krish, a quick update: "Signups today" just jumped from 335 to 350 🎉, while "Active users" nudged down from 1,305 to 1,298. Great to see more signups coming in, and the dip looks mild — worth a quick glance if you're tracking trends.

Everything that moved in one check becomes **one message**, not one per watch. Alerts run with tools enabled but **read-only**: an alert may fetch the page or search to ground its wording, and mutations are declined outright, so an unattended notification can never change your machine. If the model is unavailable the plain one-liner is sent instead, so a change is never silently dropped. Tune the wording with `WATCH_ALERT_PROMPT`, or set `WATCH_ALERT_LLM=off` to skip the model.

Two knobs worth knowing:
- **`alert_every`** (default `10m`) rate-limits *notifications*, not checks. A number that moves every 20 seconds is checked every 20 seconds but only messages you once per cooldown, so a busy dashboard cannot flood you.
- Alerts that decide to look something up take 10–25s instead of ~5s. That is the price of a grounded message.
- **`ALLOW_PRIVATE_HOSTS=1`** lifts the loopback/LAN block so you can watch your own dev server. Off by default: a page you fetch should not be able to make the agent probe your network.

A dashboard to practise against ships in the repo — it serves numbers that wander up and down:

```bash
node scripts/demo-dashboard.mjs 4173
# then, with ALLOW_PRIVATE_HOSTS=1
ankita › watch http://127.0.0.1:4173, grab "Active users: ([\d,]+)", alert me at most every 10m
```

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

**Routines can create routines.** The agent has the same `schedule` and `watch` tools you do, so a routine can set up follow-on work for itself. State is shared through one file (`~/.copilot-chat-cli/state.json`) that every writer re-reads before it changes anything, so a watch the agent adds mid-routine is never lost to the daemon's bookkeeping. `MAX_CONCURRENT` (default 4) caps how many routines run at once, so a pile of schedules landing on 08:00 queue instead of stampeding the provider.

### One honest limitation

A Telegram **bot** only receives messages sent *to it*, plus posts in groups and channels it is a member of. It cannot read your personal DMs with other people — that needs a user-account (MTProto) client, which is a different design and a different set of ToS questions. For "DMs and invitations" from the developer side, `github_notifications` covers mentions, review requests and repo invitations. Also use a **separate bot** from any other app: Telegram delivers each update to exactly one long-poller, so two processes sharing a token silently steal each other's messages.

## Tests

```bash
npm test   # node --test "test/*.test.mjs"
```

Tests cover `core`, `provider`, `tools`, `voice`, `web`, `proactive`, `projects`, personal memory, consolidation, notifications, `mcp`, `registry` and `tool-loop`. The web suite runs pure parsers and guards against fixtures, stubs DNS for the SSRF checks, and skips the two live bridge tests automatically when Python/Scrapling aren't installed. The MCP suite drives a real stdio server fixture, and skips cleanly when Python `mcp` isn't importable. The registry suite runs entirely against recorded response shapes, so it never touches the network or the user's real config.

## Benchmarking latency

When replies feel slow, measure instead of guessing. `scripts/bench-latency.mjs` drives the real agent loop and splits each turn into the phases a user actually waits on:

```bash
npm run bench                                    # configured model, 3 runs
npm run bench -- --runs 5 --tools
npm run bench -- --models "a,b,c"                # compare models on your account
npm run bench -- --json                          # raw per-run samples
```

| Phase | What it is |
|---|---|
| `pre` | personal recall + system-prompt rebuild + history trim |
| `ttft` | request sent → first streamed token — **the number you feel** |
| `gen` | first token → last (decode throughput, reported as `tok/s`) |
| `total` | whole turn, including any tool rounds |

Warmup sends are discarded so a provider cold start does not skew the medians, and the first token dominates short replies while `gen` matters for long ones. On a keyless Kilo account only `:free` models run without signing in; paid IDs return `PAID_MODEL_AUTH_REQUIRED`. Benchmarks run with tools on, so a model marked `no-tools` is skipped.


## Security notes

- Mutating tools always show a diff and ask first; `-y`/`AUTO_APPROVE` is explicit and visible per call.
- `.env` is gitignored (copy `.env.example`); tokens live in `~/.copilot-chat-cli/` with `0600` perms, never in the repo.
- `delete_file` refuses the workspace root; `move_file` refuses overwrites; `fetch_url` is text-only with byte/time caps.
- Web tools refuse non-public hosts, including via redirects. Scraping needs local Python + `pip install scrapling` for the browser tier; the static tier works anywhere the bridge runs.
