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
| `API_BASE` / `API_KEY` | unset | OpenAI-compatible endpoint instead of Copilot |
| `GROQ_API_KEY` / `STT_MODEL` | unset / `whisper-large-v3-turbo` | Mic transcription (free key at console.groq.com) |
| `TTS_PROVIDER` | `edge` | `edge`, `groq`, or `auto` (groq when a key exists) |
| `TTS_MODEL` / `TTS_VOICE` | `canopylabs/orpheus-v1-english` / provider default | `tara` on groq, `en-US-AriaNeural` on edge — see `/voices` |
| `TTS_RATE` / `SPEAK` / `MIC_DEVICE` | `+0%` / `off` / auto | Edge speech rate, auto-speak replies, preferred mic |
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
| `mcp_manage` | Add/list/remove/enable/disable MCP servers — extra tools from external processes |
| `project` | Add/list/show/switch/rename/archive projects; records what each one is, where it lives, how you like it done, who the client is |
| `project_memory` | Remember notes, decisions and open todos per project; `log` shows the timeline, `brief` hands over a catch-up |
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

**Memory never enters the system prompt.** Only the name, summary, path and conventions do. Ten notes later the block is still the same size — otherwise every turn would pay for history you didn't ask for. This is exactly why `brief` exists as the deliberate, opt-in way to pull memory into context.

Lists are capped (50 notes, 50 decisions, 100 todos, newest kept) and `show` says when older entries were dropped.

The block is capped (200-char summary, 5 conventions) because it is paid on every turn alongside the tool specs.

## MCP servers

Ankita can use [Model Context Protocol](https://modelcontextprotocol.io) servers — external processes that provide tools. Hand-rolled over stdio, so the zero-dependency rule holds.

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

**Tools are namespaced** `mcp__<server>__<tool>`, so they can't collide with built-ins. Approval follows the server's own `readOnlyHint`: only an explicit read-only hint skips the gate; anything unset or destructive asks first, and the prompt shows the command that will spawn.

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

204 tests across `core`, `provider`, `tools`, `voice`, `web`, `proactive`, `projects` and `mcp`. The web suite runs pure parsers and guards against fixtures, stubs DNS for the SSRF checks, and skips the two live bridge tests automatically when Python/Scrapling aren't installed. The MCP suite drives a real stdio server fixture, and skips cleanly when Python `mcp` isn't importable.

## Security notes

- Mutating tools always show a diff and ask first; `-y`/`AUTO_APPROVE` is explicit and visible per call.
- `.env` is gitignored (copy `.env.example`); tokens live in `~/.copilot-chat-cli/` with `0600` perms, never in the repo.
- `delete_file` refuses the workspace root; `move_file` refuses overwrites; `fetch_url` is text-only with byte/time caps.
- Web tools refuse non-public hosts, including via redirects. Scraping needs local Python + `pip install scrapling` for the browser tier; the static tier works anywhere the bridge runs.
