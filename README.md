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
- 🔌 **Extend** — MCP servers, 1000+ Composio app integrations with per-action approval tiers, project-aware teammates

## 🚀 Quickstart

**Prereqs:** Node.js 20.19+, 22.12+, or 23+ for the CLI and bundled Chrome bridge; Node 22.12+ for desktop development and packaging. The minimum versions follow the Chrome bridge and Electron build dependencies. The packaged app supplies its own runtime. Optional: `ffmpeg`/`ffplay` on PATH for voice, and Python 3 + `pip install scrapling` for the stealth scraping tier.

```bash
npm install
npm link          # once — `ankita` now works from any folder
cp .env.example .env   # or ~/.copilot-chat-cli/config.env as global fallback
ankita            # talk to it
```

Run these commands from the repository root. A fresh desktop install starts with Kilo's free `poolside/laguna-s-2.1:free` model without an API key; free access is subject to provider availability and rate limits. Existing provider choices are preserved. With Copilot selected and no cached login, the window shows a GitHub device code for sign-in. Open **Settings** from the sidebar gear or with `Ctrl+,` (`Cmd+,` on macOS) to choose a model or provider, add a Composio key, test a custom OpenAI-compatible endpoint, and change the appearance. Desktop settings are saved in `~/.copilot-chat-cli/desktop-settings.json` and take priority over `.env` in the desktop app. The CLI continues to use `.env` or its global fallback.

For CLI Copilot sign-in, the first run prints a code. Sign in at `github.com/login/device` once; the token is cached with `0600` permissions, so later runs skip login.

**Images are three separate tools.** Ask the agent to generate an image, search Unsplash, or search Pixabay; it loads the image tools on demand. Generated images are saved under `generated-images/` in the current workspace, and a chosen stock photo can be downloaded to `downloaded-images/`; both preview inline. Unsplash and Pixabay searches return separate attributed preview galleries. Configure the image-generation endpoint/model and the two stock-search keys in **Settings → Images**, or use `IMAGE_API_BASE`, `IMAGE_API_KEY`, `IMAGE_MODEL`, `UNSPLASH_ACCESS_KEY`, and `PIXABAY_API_KEY` in `config.env`. Generation uses the configured image endpoint (or falls back to the current model provider) and may incur provider charges. Both folders are git-ignored — they are content, not source.

### Launch film

Open [`docs/media/ankita-launch-film.html`](docs/media/ankita-launch-film.html) in a browser to play the self-contained, 30-second Canvas 2D A.N.K.I.T.A. launch film. Use **Space** to pause/play, **R** to restart, and **F** or the fullscreen control to toggle fullscreen. The memory-search sequence animates a typed prompt, a flying send arrow, and contextual results. Add `?seed=your-seed` to the URL for a repeatable particle arrangement.

Open **Plugins** in the sidebar to browse and search the Composio app catalog, with a real brand icon on every app. Connect an app in your browser, see connected accounts in **Installed**, add another account, or disconnect individual accounts. On desktop, connecting needs **no API key**: Ankita opens a browser sign-in (OAuth 2.1 + PKCE) that returns to a one-time `127.0.0.1` address on your own machine and keeps the token in the OS vault rather than a config file — there is nothing for you to host. An existing Composio project key in **Settings → Providers** keeps working until the deprecation window closes; without either, Plugins shows a setup link instead of an empty catalog.

**Saved sign-ins** in Plugins is the browser vault: the site/username pairs Ankita may fill for the built-in browser and Chromium. Entries are sealed with this device's encryption, never shown in chat, and removable from the same card.

App actions run behind per-action **approval tiers**: reads run quietly, while sending, deleting, publishing or paying always asks first, every time. The assistant's `composio` tool exposes `tiers`, `allow`, `always` and `deny` to inspect or change the gate — and a call that loosens protection can never run under auto-approve.

The **By Ankita** section in Plugins works without a Composio key. It offers an isolated Playwright Chromium and an optional Chrome connection for sites that need your existing session. Browser runs have a live stage beside chat with tabs, a page preview, Stop, and takeover controls. See [Browser use](docs/guides/browser-use.md) for setup, permissions, and CLI commands.

**Desktop scheduled tasks** start in chat: tell Ankita what to do, how to check success and when. Its `schedule` tool creates an active task and shows a compact card with the next run. Ask it to update, pause, resume or remove a task; the clock opens a thin upcoming list with details and optional advanced settings. Jobs use independent isolated Chromium profiles and saved credentials, so chat stays available. New chat tasks browse autonomously for the requested work; existing scoped tasks keep their inline permissions. Heartbeat checks an idle teammate's context and stays quiet when there is no useful update. Closing/minimizing keeps jobs in the tray; **Quit** stops them. Startup is opt-in. No mobile wiring. See [Scheduled desktop jobs](docs/guides/desktop-jobs.md).

**Command palette:** press `Ctrl+K` (`Cmd+K` on macOS), or click the search icon in the chat header. Search commands, enabled skills and jobs; use arrows and Enter to run, Escape to close. Job launches use the normal scheduler path.

### Secret protection

Secret scrubbing is on by default. Supported API-key/token shapes, labeled passwords, high-entropy labeled tokens, private-key blocks and encoded wrappers are replaced in saved transcripts, tool logs, job state, text diagnostics and exports. The live model turn still receives the original value. Explicit save intent stores detected values with OS encryption and leaves a `[STORED:keychain:name]` reference in history; ordinary pastes are redacted without vault storage. Previously detected desktop values also stay hidden in later unlabeled echoes.

First launch migrates app-managed history, job state, teammate previews, daemon/text logs and exports. Provider configuration and encrypted vault records are excluded. Exported files outside app-managed folders must be exported again to receive protection. Settings → Privacy can disable scrubbing with a warning. Detection cannot guarantee protection for arbitrary unlabeled secrets or values split between messages. Native binary crash dumps are not collected by this feature; only app-written text diagnostics are protected. See [CONTRIBUTING.md](CONTRIBUTING.md) for persistence and skill contribution rules.

**Settings → Channels** connects the app to a chat service so you can reach your agent from anywhere, starting with Telegram. Create a bot with [@BotFather](https://t.me/BotFather), paste its token, pick the teammate that should answer, and add the chat ids allowed to talk to it — an unknown chat is told its own id so you can add it. While enabled, the bridge runs with the app and routes each message to that teammate, sharing the same thread and history as the desktop; tool approvals are asked and answered in the chat. Voice notes are transcribed when a Groq key is set, and replies can be spoken back. Channel settings live in `~/.copilot-chat-cli/desktop-channels.json`. Only one process may poll a bot token at a time, so stop the CLI `--daemon` before enabling the same bot here.

Open **Projects** to record a working folder, conventions, decisions, and open tasks. Assign a project from the teammate header or when editing a teammate. That teammate uses the project's folder for file and command tools and receives a short project brief. The **Work review** button in chat opens Git changes with file diffs, recent artifacts, and command jobs with output and a stop action; file edits open it automatically. The agent allows at most six `web_search` calls per user request, then uses the sources already gathered.

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

Extras in the sidebar: **Plugins** (the Composio app catalog with a real icon per app, keyless browser sign-in, a Saved sign-ins browser vault, and a built-in Playwright browser with live stage, tabs, and takeover), **Channels** (connect Telegram — create a bot with [@BotFather](https://t.me/BotFather), paste the token, done), **Projects** (working folders with conventions + open tasks the agent actually remembers).

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
| `COMPOSIO_API_KEY` | unset | Connected-app integrations (deprecated — desktop signs in without a key) |

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

**Composio:** connect an app from **Plugins**, or set `COMPOSIO_API_KEY` and run `/composio connect gmail` — OAuth in your browser, and the agent can act on connected apps. On desktop, connecting needs no API key at all: you sign in through the browser and the token is kept in the OS vault. Every app action runs behind an **approval tier** — read-only discovery runs quietly, while sending, deleting, publishing or paying always asks first, every time. Inspect or change the gate with the `composio` tool's `tiers`, `allow`, `always` and `deny` actions; a change that loosens protection can never be auto-approved.

## 🧪 Tests & benchmarks

```bash
npm test                # node:test suites across every subsystem
npm run bench           # real agent loop latency split: pre / ttft / gen / total
```

700+ tests per release. Web suites run against fixtures (no network), MCP suite drives a real stdio fixture.

## 🔒 Security notes

Desktop and CLI Telegram turns keep typing active, send throttled tool-step
updates and acknowledge receipt/completion/failure with reactions. Current-turn
generated images, downloads and browser captures are uploaded after the final
text reply (up to five files). `/cancel` stops the active task in that chat,
including a task waiting for approval. Incoming photos/documents/videos receive
a not-supported reply; send text or voice notes instead. Captions and file reads
stay bounded, and generated files remain available in the workspace if an upload
fails.

**Approvals come to your phone.** A DM cannot answer a terminal y/n prompt, so when a requested action would change something, Ankita sends you the diff in the chat and waits for your reply.

- Mutating actions ask first by default (`-y` / `AUTO_APPROVE=on` opts out; file writes re-verify the plan at write time).
- `.env` is gitignored; tokens live in `~/.copilot-chat-cli/` with `0600` perms, never in the repo.
- File tools are workspace-contained: no traversal escapes, symlinks, or device aliases.
- Web tools refuse non-public hosts, including via redirects.
- Approved shell commands and MCP processes run with your OS permissions — the sandbox covers file tools, not your terminal.

## 🤝 Contributing

Hacktoberfest-friendly 🎃 — check [`CONTRIBUTING.md`](CONTRIBUTING.md) for the 5-minute setup, grab a [`good first issue`](https://github.com/akyourowngames/A.N.K.I.T.A/labels/good%20first%20issue), and send a PR. Every contributor lands in the release notes.

---

Built in the open. Star it if it does something cool for you ⭐
