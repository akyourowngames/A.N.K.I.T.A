# 🤖 Ankita

**Your AI assistant that actually _does_ stuff.** Terminal + desktop app, plugin/skill system, local-first. Chat with it — it'll run commands, edit your files, browse the real web, watch pages for changes, and ping you on Telegram while you're away.

```
ankita › search for the latest Node.js LTS release and fetch the announcement
  → web_search({"query":"latest Node.js LTS release","when":"7d"})
  → web_fetch({"url":"https://nodejs.org/en/blog/release/v24.11.0"})
  │ Node 24.11.0 is the current LTS (Krypton).
  · 3.8s · gpt-4.1 · 5.2k in / 45 out
```

## ✨ What it can do

- 💬 **Chat** — streaming markdown replies with syntax-highlighted code, tables, zero garbling
- 🛠️ **Act** — 24 tools: shell (foreground + background jobs), file read/write/edit with approval diffs, search, git, HTTP, todos… every mutation shows a diff and asks first
- 🌐 **Know the internet** — keyless `web_search` (5 fused backends) + `web_fetch` + 3 scraping tiers up to a headless stealth browser
- 🖱️ **Drive a real browser** — opens pages, reads elements, clicks, types, manages tabs, screenshots (Playwright loads on demand)
- 🎙️ **Talk** — dictate with `/mic`, go hands-free with `/voice`, replies spoken back (Edge neural TTS / Groq Orpheus)
- 🧠 **Remember** — personal memory, per-project memory, named sessions with autosave
- ⏰ **Work while you're away** — `ankita --daemon` runs scheduled routines, watches pages, answers Telegram DMs
- 🖼️ **Make & find images** — generate originals or search Unsplash/Pixabay, saved + previewed inline
- 🔌 **Extend** — MCP servers, Composio app integrations, project-aware teammates

## 🚀 Quickstart

**Prereqs:** Node.js 20+ (`22.12+` for desktop dev). Optional: `ffmpeg` for voice, Python 3 + `pip install scrapling` for stealth scraping.

```bash
npm install
npm link          # once — `ankita` now works from any folder
cp .env.example .env   # or ~/.copilot-chat-cli/config.env as global fallback
ankita            # talk to it
```

First run prints a code → sign in at `github.com/login/device` once, token is cached (`0600` perms). Every later run skips login.

```bash
ankita -p "summarise what this repo does"        # one-shot
ankita --voice                                   # hands-free conversation
ankita --api-base http://localhost:11434/v1      # local models via Ollama
ankita --daemon                                  # background mode: schedules, watches, Telegram
```

## 🖥️ Desktop app

Same agent, models, tools, and login as the CLI — plus teammate conversations with personas, streaming replies, tool cards, approvals, and a model picker.

```bash
npm run desktop:dev        # Vite + Electron dev mode
# or run the production bundle:
npm run desktop:build && npm run desktop:start
```

Open **Settings** (gear icon or `Ctrl+,`) to pick models/providers, add a Composio key, test custom OpenAI-compatible endpoints, and tweak appearance. Fresh installs start on Kilo's free keyless models — no API key needed.

Extras in the sidebar: **Plugins** (Composio app catalog + a built-in Playwright browser with live stage, tabs, and takeover), **Channels** (connect Telegram — create a bot with [@BotFather](https://t.me/BotFather), paste the token, done), **Projects** (working folders with conventions + open tasks the agent actually remembers).

## ⌨️ CLI reference

<details>
<summary><b>Flags & slash commands</b></summary>

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

Background jobs: `/bg npm run dev`, `/jobs`, `/job 1`, `/input 1 yes`, `/stop 1` — commands keep running while you keep chatting.

</details>

## ⚙️ Configuration

`.env` in the working dir, falling back to `~/.copilot-chat-cli/config.env`. `/reload` picks up edits live. Full annotated list in [`.env.example`](.env.example).

<details>
<summary><b>All config keys</b></summary>

| Key | Default | What |
|---|---|---|
| `USERNAME` / `AGENT_NAME` | `user` / `assistant` | Names used in prompts and replies |
| `MODEL` | auto | Pinned model, else best capable default |
| `TOOLS` / `AUTO_APPROVE` | `on` / `off` | Tool use and the y/n approval gate |
| `HISTORY_MESSAGES` | `40` | Turns kept in context |
| `MAX_TOKENS` / `MAX_TOOL_CHARS` / `CONTEXT_WINDOW` | `4096` / `65536` / `32768` | Output cap, per-result context cap, trim budget |
| `MAX_TOOL_STEPS` / `MAX_TOOL_CALLS` | `24` / `60` | Tool rounds and total calls per request |
| `PROVIDER` | `copilot` | `copilot`, `groq` (fast, reuses `GROQ_API_KEY`), or `kilo` (free keyless models) |
| `API_BASE` / `API_KEY` | unset | OpenAI-compatible endpoint (wins over `PROVIDER`) |
| `GROQ_API_KEY` / `STT_MODEL` | unset / `whisper-large-v3-turbo` | Mic transcription |
| `TTS_PROVIDER` / `TTS_VOICE` | `edge` / `en-US-AriaNeural` | `edge`, `groq`, or `auto` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `TELEGRAM_ALLOWED_CHAT_IDS` | unset | Telegram inbox + who may talk to it |
| `DAEMON_TICK` / `MAX_CONCURRENT` | `20` / `4` | Scheduler tick (s); routines running at once |
| `QUIET_HOURS` / `TIMEZONE` | unset | Hold proactive messages, e.g. `22:00-08:00` |
| `NTFY_URL` / `DISCORD_WEBHOOK_URL` / `PUSHOVER_TOKEN`+`PUSHOVER_USER` | unset | Notification fallbacks after Telegram |
| `ANKITA_NO_WEB` / `ANKITA_NO_SCRAPE` | unset | Kill switches for web and scraping |
| `ALLOW_PRIVATE_HOSTS` | `off` | Opt in to loopback/LAN pages (watch your own dev server) |
| `IMAGE_API_BASE` / `IMAGE_API_KEY` / `IMAGE_MODEL` | provider defaults | Image generation endpoint |
| `UNSPLASH_ACCESS_KEY` / `PIXABAY_API_KEY` | unset | Stock-photo search tools |
| `COMPOSIO_API_KEY` | unset | Connected-app integrations |

</details>

## 🧰 Tools

<details>
<summary><b>Full tool list (24)</b></summary>

| Tool | Does |
|---|---|
| `run_command` | Shell, stdin/env, bounded output; long commands become controllable background jobs |
| `read_file` / `write_file` / `edit_file` / `edit_lines` / `apply_patch` | Numbered reads, atomic writes, exact/fuzzy/line-range/patch edits — all with diffs |
| `list_dir` / `glob` / `search_files` / `create_dir` / `move_file` / `delete_file` | Filesystem verbs (root-protected, no silent overwrites) |
| `http_request` | Full HTTP client: methods, headers, auth, redirects, text/base64 |
| `git` / `port_status` / `kill_process` | Deferred groups: git ops, port owners, safe process kill |
| `web_search` / `web_fetch` | Keyless live search (5 backends, fused) + readable page extraction |
| `browser` | Deferred interactive browser: open, snapshot, act, tabs, screenshot |
| `scrape_low` / `scrape_mid` / `scrape_high` | Static fetch → stealth browser → multi-page crawl |
| `mcp_manage` | Install/enable MCP servers from the official registry |
| `composio` | Connected apps (Gmail, GitHub, …) via OAuth |
| `project` / `project_memory` | Project profiles + dated notes/decisions/todos |
| `schedule` / `watch` | Recurring prompts + page/number change tracking |
| `github_notifications` | Your GitHub inbox: mentions, reviews, invites |
| `write_todos` / `job_status` / `job_wait` / `job_input` / `job_stop` | Session checklists + background job control |

Read-only actions run concurrently without prompts; mutations are sequential and show previews. `find_tools` loads deferred families on demand so big tool lists don't eat your context.

</details>

## 🏗️ Architecture

```
chat.mjs              thin CLI entry
src/
  core/               CLI, agent loop, provider, config, history, UI
  automation/         daemon, schedules, watches, alerts, notifications
  channels/           Telegram and voice
  integrations/       MCP and Composio clients and stores
  memory/             personal and project memory, embeddings
  tooling/            tool workers and job UI
scripts/              bench/, bridges/, demo/, fixtures/, verify/
tools/
  index.mjs           core tool registry
  catalog.mjs         deferred tool families
  shared/             output, diff, web, job, and image helpers
  filesystem/, git/, web/, process/, personal/, skills/
  automation/, project/, github/, connectors/, mcp/, images/
test/                 node:test suites grouped by subsystem
```

**Under the hood:** agentic loop over `/chat/completions` with streaming SSE — read-only tools run concurrently, mutations act as barriers, up to 24 tool steps per turn. Optional two-model mode (`TOOL_PROVIDER`) splits chat from tool-running. Every web tool passes an SSRF guard (no loopback/private hosts, redirects re-checked hop by hop). Voice is ffmpeg + Groq Whisper in, Edge/Groq TTS out, with pause-to-send and barge-in for hands-free mode.

## ⏰ Proactive mode — works while you're away

`ankita --daemon` runs three loops on the same tools the REPL uses:

- 📅 **Routines** — prompts on a schedule. *"Every weekday at 8, brief me on my GitHub inbox"* → it sets up the cron itself.
- 👀 **Watches** — track a page or one number on it (`Signups: 1,204 → 1,227 (+23)`), alerts written as real sentences, not templates. Read-only by design — an unattended alert can never change your machine.
- 💬 **Telegram inbox** — text/voice notes in, replies out. Approvals come to your phone as diffs: reply `y`/`a`/`n`.

Notifications fall through **Telegram → ntfy/Discord/Pushover → desktop → terminal**. `QUIET_HOURS=22:00-08:00` holds messages into digests.

## 🧠 Memory

- **Personal** — `remember`/`recall` natural-language facts and preferences; only 12 pinned facts ever enter the prompt, everything else is recalled on demand (local lexical + optional Cloudflare semantic ranking).
- **Project** — per-project notes, decisions, open todos with `log`/`brief`; the system prompt only carries name + conventions, so context never bloats.
- **Overnight consolidation** — the daemon journals transcripts and extracts durable facts while you sleep (`MEMORY_CONSOLIDATION=on`).

## 🔌 MCP + Composio

**MCP:** just ask — Ankita searches the official registry, installs what you pick, and loads big servers on demand (`find_tools`) so 25 Playwright tools don't nuke your context window. Installing ≠ running: every server start asks for approval first, tools are namespaced `mcp__<server>__<tool>`, third-party code gets a stripped environment without your secrets.

**Composio:** set `COMPOSIO_API_KEY`, then `/composio connect gmail` — OAuth in your browser, and the agent can act on connected apps. Heads up: Composio tools run without approval prompts, so only connect accounts you actually want Ankita driving.

## 🧪 Tests & benchmarks

```bash
npm test                # node:test suites across every subsystem
npm run bench           # real agent loop latency split: pre / ttft / gen / total
```

700+ tests per release. Web suites run against fixtures (no network), MCP suite drives a real stdio fixture.

## 🔒 Security notes

- Mutating actions ask first by default (`-y` / `AUTO_APPROVE=on` opts out; file writes re-verify the plan at write time).
- `.env` is gitignored; tokens live in `~/.copilot-chat-cli/` with `0600` perms, never in the repo.
- File tools are workspace-contained: no traversal escapes, symlinks, or device aliases.
- Web tools refuse non-public hosts, including via redirects.
- Approved shell commands and MCP processes run with your OS permissions — the sandbox covers file tools, not your terminal.

## 🤝 Contributing

Hacktoberfest-friendly 🎃 — check [`CONTRIBUTING.md`](CONTRIBUTING.md) for the 5-minute setup, grab a [`good first issue`](https://github.com/akyourowngames/A.N.K.I.T.A/labels/good%20first%20issue), and send a PR. Every contributor lands in the release notes.

---

Built in the open. Star it if it does something cool for you ⭐
