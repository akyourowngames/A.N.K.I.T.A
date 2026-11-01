# Ankita

An AI workspace for getting work done on your computer. Ankita brings teammate
conversations, real tools, projects and scheduled work into a desktop app, a
floating companion and a terminal CLI.

Ask it to inspect a repository, edit files, run commands, research a page or
handle a recurring task. Tool activity, results and approval requests stay in the
conversation. Choose ChatGPT Browser, GitHub Copilot, Groq, Kilo or an
OpenAI-compatible provider.

[Download for Windows](https://github.com/akyourowngames/A.N.K.I.T.A/releases/latest)
 · [Release notes](CHANGELOG.md)
 · [Contributing](CONTRIBUTING.md)
 · [MIT license](LICENSE)

> How it was built: [How I built a 4-tier approval gate for my AI companion: a heuristic that can never say no](https://dev.to/krish_verma_77e28d3fd63ca/how-i-built-a-4-tier-approval-gate-for-my-ai-companion-a-heuristic-that-can-never-say-no-2k7o) — the write-up behind Ankita's safety model.

## Desktop, companion and terminal

| Surface | Use it for |
| --- | --- |
| **Desktop workspace** | Conversations, file review, projects, connected apps and settings |
| **Floating island** | Quick chats, approvals and live tool activity while the main window is hidden |
| **Terminal CLI** | Interactive coding, one-shot prompts, pipelines and background automation |

They use the same agent runtime and tools. Desktop teammates have separate
threads, personas and drafts; assign a project to give a teammate its working
folder and shared context.

## Chat channels (source build)

Connect Telegram, Discord or Slack in **Settings → Channels**. Choose a teammate,
add allowed people or conversations, test the account and save. Requests use the
same tools with owner-only private approvals, work updates, file delivery and
per-conversation cancellation. Discord and Slack connect through outbound
sockets; no extra hosted service is needed. The terminal shares setup through
`/channels` and can host enabled connections alongside existing schedules.

This is source-branch work, not a new installer release. Real Discord/Slack
account acceptance remains a separate setup check. See the
[channel guide](docs/guides/channels.md) and
[verification matrix](docs/verification/multi-channel-communication.md).

## Voice delegation (source build)

Speak a Hinglish or English request in terminal `/voice`, or choose **Voice** in
an app conversation. Sarvam handles speech and a voice-only Baseten Meta planner
handles the work. The desktop panel and floating island share one session, a
smooth dark-pearl orb, short captions and individual task controls.

Give another request while earlier work runs. Independent voice jobs can work in
parallel; conflicting file and app actions wait for shared access. **End voice**
stops audio while delegated work continues. **Stop** cancels the chosen job.
`/task` lists saved requests and `/task <id>` shows their steps and result.

Interrupting a report leaves it suspended while the planner interprets your next
request. Ask naturally to continue, repeat, skip speech or hear another ready
result. Completed sentences are retained; the unfinished sentence may restart.
Speech recognition and planner intent choices can still be wrong.

| Already existed before this build | Added during 27–29 October |
| --- | --- |
| Mic recording, pause detection, playback and barge-in | Sarvam recognition and speech generation for Hinglish |
| Agent tools, approvals and typed chat | Separate Meta voice planning and saved request records |
| Process jobs and scheduled work | Parallel voice workers, shared-access guards and observed spoken updates |
| Desktop and floating island | Shared voice panel, state animation, captions and contextual report controls |

This feature is available from source through
[PR #70](https://github.com/akyourowngames/A.N.K.I.T.A/pull/70); it is not included
in the existing 2.7.1 installer. Generated-audio checks do not replace physical
headset/echo testing or the three clean workspace takes required before filming.
See the [voice guide](docs/guides/voice-delegation.md) for setup and limits and the
[dated plan](docs/plans/voice-delegation-hackathon-plan.md) for evidence. Existing
providers remain available; earlier voice infrastructure is not claimed as new
hackathon work.

## What's new in 2.6.0

Use your already-open ChatGPT conversation from ANKITA. Messages, attachments
and replies stay tied to the chat you choose; its current model and account
limits apply. Separate Core, Desktop and Plugins connections let ChatGPT use
ANKITA's files, commands, browser and computer controls. Stop ends owned work,
and Resume reads the original reply after a restart without sending it again.
See the [ChatGPT Browser setup guide](docs/guides/chatgpt-browser.md).

This release also brings native Windows Computer Use, a visible animated
pointer, better menu layering, skill authoring tools and useful schedule
templates. The [release notes](CHANGELOG.md#260---2026-10-14) cover the changes
and verification limits.

## Desktop startup repair in 2.5.2

The desktop now starts correctly in development and packaged Windows builds.
A shared browser metadata import previously reached host-only code that the
renderer's security policy blocked before the UI could mount. The import boundary
is corrected without weakening that policy or removing browser form batching.
See the [startup findings](docs/desktop-startup-findings.md) for reproduction and
verification evidence. If you run from source, rebuild before `desktop:start`;
`desktop:dev` serves the corrected source directly.

## Browser improvements in 2.5.1

- **More reliable form batches.** Live target checks and original node bindings
  keep mixed fills, clicks and selects from invalidating their own refs. Changed
  controls stop with fresh observations and accurate partial-work receipts.
- **Browser instructions you can see.** The complete guide loads without an
  extra model call; the desktop header confirms actual request inclusion.
- **Readable page evidence.** Markdown reads, bounded text search and labelled
  hidden DOM evidence accompany grouped controls and state flags.
- **Clearer browser activity.** Separate planning, reading, acting and checking
  states, takeover dialogs and throttled hidden previews improve live feedback.
- **Better failure recovery.** Original goals survive bounded tool history;
  flight direction/date checks, native-menu guidance and one protocol correction
  reduce confused retries. Provider errors distinguish their actual categories.
- **Consistent terminal controls.** `/commands`, help, completion and typo hints
  share a registry; startup shows version/provider.

Experimental browser runtime, focus and context switches remain opt-in. See the
[complete changelog](CHANGELOG.md#251---2026-10-09) for capabilities, test evidence
and the remaining limits.

## Desktop and companion in 2.5.0

- **A redesigned desktop.** A compact navigation rail, mascot teammate faces,
  clearer conversation controls and responsive work panels share the island's
  graphite style. Graphite, Mono and Slate appearances remain available.
- **A live companion.** Up to four teammate avatars appear in two columns.
  Tools roll upward as they run, complete or fail; full output remains in chat.
  Approvals stay visible, and restoring the desktop keeps the companion's draft.
- **File-eating mascots.** Drop a supported file onto the selected mascot. It
  opens its mouth, swallows the file and reacts to the actual reader's result.
  The extracted content becomes an attachment for you to review before sending.
- **Webpage capture.** A separately loaded Chrome/Edge helper lets you drag a
  mascot onto an ordinary webpage and attach its readable text to the original
  teammate. Pair once per browser profile; capture does not send a model request.
- **Better project organization.** Overview, Tasks and Context separate the
  project brief, next steps and searchable notes/decisions. Long records expand
  on demand; task and context drafts stay with their project while switching.
- **Clearer scheduling and settings.** See the next run, owner and result of a
  task. Background settings show scheduled/enabled/running counts and open the
  right conversation. Model choice, optional limits and saving have distinct
  controls. Hard rectangular focus outlines are removed.
- **Less repeated rendering.** Completed Markdown replies are memoized during
  streaming. Hidden mascots and idle tool tickers stop their animation work;
  motion respects the operating system's reduced-motion setting.

See the [desktop guide](docs/guides/desktop-workbench.md) and
[companion guide](docs/guides/desktop-companion.md) for behavior and verification.

## Install the Windows app

1. Open the [latest release](https://github.com/akyourowngames/A.N.K.I.T.A/releases/latest).
2. Download the **setup-x64.exe** to install Ankita, or **portable-x64.exe** for
   a standalone copy.
3. Open Ankita, choose your provider in **Settings → Providers**, and create a
   teammate. Fresh desktop installs start with Kilo's keyless free models;
   availability and rate limits depend on the provider. Existing choices remain.
4. With GitHub Copilot selected, follow the GitHub device sign-in shown by the
   app. For a custom provider, enter its API base URL and credentials in Settings.

The installer includes the application runtime; Node.js is only needed to run
from source. Installed NSIS builds support in-app updates. Portable builds are
updated by downloading a newer executable. Windows x64 is the published target;
macOS/Linux packaging targets are declared, but this release is verified on Windows.

### Set up webpage capture

The capture helper is included in the desktop package and must be loaded into
your browser separately:

1. Open **Browser helper** beside the desktop mascot or in the island's settings.
2. Choose **Open helper folder**.
3. On Chrome/Edge's Extensions page, enable Developer mode, choose **Load unpacked**
   and select that folder.
4. Use **Copy pairing code** in Ankita and paste it into the helper popup.
5. Drag a mascot onto an HTTP/HTTPS page. Review the captured attachment in chat.

The helper extracts readable document text. Browser-internal pages, extension
stores and inaccessible frames/viewers cannot be captured. It is separate from
Ankita's browser automation connection. Details and recovery steps are in the
[companion guide](docs/guides/desktop-companion.md#webpage-capture-and-responsiveness--2026-10-05).

## Run from source

The CLI supports the Node ranges declared in [`package.json`](package.json):
Node 20.19+, 22.12+, or 23+. Use Node 22.12+ for desktop development/packaging.
The following commands run from the repository root.

```bash
git clone --branch ankita https://github.com/akyourowngames/A.N.K.I.T.A.git
cd A.N.K.I.T.A
npm ci
```

Start the desktop in development:

```bash
npm run desktop:dev
```

Or build and open the production renderer:

```bash
npm run desktop:build
npm run desktop:start
```

Start the CLI:

```bash
npm link
ankita
```

Copy [`.env.example`](.env.example) to `.env` and configure the CLI provider.
On PowerShell use `Copy-Item .env.example .env`; on a POSIX shell use
`cp .env.example .env`. A global `config.env` is also supported under the
configuration directory (`~/.copilot-chat-cli` by default, overridable with
`CONFIG_DIR`). Desktop settings take priority over `.env` for desktop sessions.

Voice features optionally need `ffmpeg`/`ffplay`; the optional stealth scraping
tier uses Python and Scrapling. Ordinary chat, tools and desktop setup do not
require those optional features.

## Working with Ankita

### Conversations and real tools

Stream Markdown replies with code, tables and tool cards. Inspect a command or
file diff before approving a change. Long commands can become background jobs
with status, output, stdin and Stop controls while chat continues.

| Tool family | Capabilities |
| --- | --- |
| Files and code | Read, write, edit, patch, list, glob and search files |
| Commands and processes | Run commands, inspect ports, manage processes and background jobs |
| Git and HTTP | Repository operations and structured requests |
| Web and browser | Search, readable page extraction, browser actions, tabs and screenshots |
| Projects and memory | Working context, decisions, tasks and personal facts |
| Automation | Scheduled prompts, page watches and job control |
| Images | Original generation, Unsplash search and Pixabay search |
| Connected apps | MCP servers and Composio integrations |

Deferred tool families load when needed. Approval rules depend on the action;
MCP/Composio tier controls cover auto-allow, ask-once, always-ask and deny. See
[`tools/catalog.mjs`](tools/catalog.mjs) for the available families.

### Projects and work review

Use **Projects → Overview** for the folder, client and working rules,
**Tasks** for open/completed work, and **Context** for notes and decisions.
Assign a teammate to a project from the overview, teammate editor or chat header.
Its file/command tools use that folder and its prompt receives a bounded brief.

Run the CLI from a project folder and that project attaches automatically unless
another one is active; teammates attach through assignment. After a turn that
changes files, the project gets one bounded **Recent work** line and matching
todos, shown in Overview with **Undo**. With
`PROJECT_INLINE_CONSOLIDATION=on`, a small local extraction can also propose
notes and decisions. `/project undo` in the CLI removes the latest session's
automatic entries. Explicit activation always wins over folder detection.

**Work review** beside chat shows Git changes and diffs, recent artifacts, and
command runs with output and Stop. File edits can open it automatically. The
**Edited N files** card appears once the turn ends, so it never jumps around
while tools are still running.

### Browsers and connected apps

**Plugins** includes an isolated Playwright browser, a Chrome connection and
saved browser sign-ins. Live runs have a page preview, tabs and Stop/takeover
controls. Credentials use the device's encrypted store; the model works with
private credential references rather than plaintext password fields.

Composio apps connect through browser sign-in without requiring you to host a
callback service. Existing project-key configuration remains supported. MCP
servers and tools extend the runtime with per-action approval rules.

Read [Browser use](docs/guides/browser-use.md) for connection modes and permissions.

### Scheduled work and channels

Describe the task, timing and success criteria in chat. Ankita's `schedule` tool
creates a task in that teammate's conversation. Open **Schedule** to inspect,
edit, pause/resume, run now or stop it. Jobs use independent isolated browser
profiles; their results return through the owning teammate with expandable proof.

**Settings → Background jobs** shows current counts, startup availability and
the task list. Closing/minimizing keeps scheduling in the tray; **Quit** stops
it. Startup at sign-in is opt-in. See [Desktop jobs](docs/guides/desktop-jobs.md).

**Settings → Channels** routes Telegram messages to a chosen teammate. Add a bot
token, allowed chat IDs and the teammate that should answer. Desktop and Telegram
share that thread; tool approvals can be answered in Telegram. Voice notes can
be transcribed, and current-turn image artifacts can be returned after a reply.
Use one active Telegram poller for a bot token.

For CLI background automation, use `ankita --daemon` for schedules, watches,
notifications and Telegram. Quiet hours and fallback delivery are configurable
in [`.env.example`](.env.example).

### Memory and skills

Personal memory stores preferences and facts separately from project records.
Bounded recall keeps prompts small, while optional daemon consolidation processes
the journal in the background. Named CLI sessions can be saved and resumed.

Built-in chat skills live in [`skills/`](skills). Use `/skills` to inspect them
or the desktop command palette to discover enabled skills. Contribution and
size limits are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

The [codebase-tour skill](skills/codebase-tour/SKILL.md) explains an unfamiliar
repository from verified files only: top-level layout, documentation and
manifests, entry points, build/run/test commands and component relationships,
with a bounded read budget and no writes. It was contributed by
[Pradyumna Parida (@Pradyumna-red)](https://github.com/Pradyumna-red) in
[PR #69](https://github.com/akyourowngames/A.N.K.I.T.A/pull/69).

The [browser-use skill](skills/browser-use/SKILL.md) loads its full guide when
an interactive chat discovers or uses the browser, without a separate model
request. It covers current refs, form batching, result checks and error recovery.
Before browser discovery, turns retain its description. While browser tools
remain available, the whole guide precedes each decision; **Plugins → Skills**
can disable it. The desktop header confirms whole-body request inclusion.

## Keyboard and CLI reference

| Desktop shortcut | Action |
| --- | --- |
| `Ctrl+K` / `Cmd+K` | Search commands, skills and scheduled tasks |
| `Ctrl+,` / `Cmd+,` | Open settings |
| `Enter` / `Shift+Enter` | Send / insert a newline |
| `Escape` | Close the active palette or dialog |
| Arrow keys / Home / End | Navigate project tabs when the tab has focus |

```bash
ankita -p "Summarize this repository"      # one-shot request
ankita --continue                        # resume the autosaved session
ankita --list-models                      # available models
ankita --voice                            # hands-free mode
ankita --daemon                           # background automation
```

Use `/help` for the current command list and `/commands` for the full grouped
cheatsheet (every command, subcommand and tab-completion comes from one
registry). Common commands include `/models`,
`/model`, `/tools`, `/auto`, `/skills`, `/project`, `/projects`, `/browser`,
`/composio`, `/mcp`, `/save`, `/load`, `/sessions`, `/usage`, `/mic`, `/voice`,
`/routines`, `/watches`, `/brief` and `/exit`. `/bg`, `/jobs`, `/job`, `/input`
and `/stop` manage command jobs. Flags such as `--model`, `--max-tokens`,
`--api-base`, `--api-key`, `--no-tools`, `--plain` and `--json` configure CLI runs.

## Configuration and privacy

| Configuration | Where to set it |
| --- | --- |
| Desktop provider, model, limits and appearance | Settings; saved in `desktop-settings.json` under the config directory |
| CLI provider, tool budgets, voice and notifications | Project `.env` or global `config.env`; `/reload` refreshes it |
| Telegram desktop bridge | Settings → Channels; `desktop-channels.json` |
| Browser sign-ins | Plugins → Saved sign-ins; device-encrypted vault |
| Complete environment reference | [`.env.example`](.env.example) |

Secret scrubbing is enabled by default for supported key/token shapes, labeled
passwords and private-key blocks in saved history, logs and exports. Explicit
save intent can put detected secrets in the encrypted vault. Scrubbing is a
persistence protection: a live model request can still receive pasted content.
Arbitrary unlabeled secrets or values split across messages may not be detected.

File tools enforce workspace boundaries, and web tools guard private hosts and
redirects. Approved shell commands and MCP processes run with your OS permissions.
Review requested actions before approving them; provider and integration data
policies still apply. `.env`, generated images, media, logs, dumps and local
verification output are excluded from source control.

## Development and verification

```bash
npm test                               # serial node:test suite
npm run desktop:build                  # TypeScript and production renderer
node scripts/verify-desktop-workbench.mjs
node scripts/verify-desktop-island.mjs
node scripts/verify-desktop-companion-native.mjs
node scripts/verify-desktop-workbench.mjs --focus-only
```

Desktop checks use isolated fixture configuration and temporary evidence folders.
The companion verifier exercises real Electron IPC, file tools, approvals,
capture delivery and project/settings persistence. Browser capture checks also
load the actual extension; physical OS drag transfer is a separate manual check.
See the guides for measured results and uncovered platforms/workloads.

```text
desktop/electron/       windows, IPC, agent hosting, capture, vault and scheduler
desktop/renderer/       React workspace, companion, readers and live tool UI
desktop/browser-helper/ Chrome/Edge capture extension
desktop/shared/         typed contracts, state and interaction helpers
src/                    CLI, agent, providers, automation, channels and memory
tools/                  core and deferred tool families
skills/                 built-in chat skills
test/                   subsystem regression suites
scripts/                live verification and development utilities
```

Local packaging: `npm run desktop:package:win`. Release workflow, update assets
and required gates are documented in [Releasing](docs/guides/releasing.md).
Third-party companion attribution ships in
[`desktop/THIRD_PARTY_NOTICES.md`](desktop/THIRD_PARTY_NOTICES.md).

## Documentation and contributing

- [Desktop workspace](docs/guides/desktop-workbench.md)
- [Companion, file drops and webpage capture](docs/guides/desktop-companion.md)
- [Phone pairing](docs/guides/phone-pairing.md)
- [Browser connections and permissions](docs/guides/browser-use.md)
- [Browser lab fixes and remaining limits](docs/browser-lab-FINDINGS.md)
- [Browser request cost and A/B evidence](docs/browser-lab-token-research.md)
- [Scheduled desktop jobs](docs/guides/desktop-jobs.md)
- [Release and auto-update](docs/guides/releasing.md)
- [Code signing](docs/guides/code-signing.md)
- [Release history](CHANGELOG.md)
- [Contribution guide](CONTRIBUTING.md)

Read [AGENTS.md](AGENTS.md), preserve existing work and include execution evidence
with changes. Contributions target the `ankita` branch.
