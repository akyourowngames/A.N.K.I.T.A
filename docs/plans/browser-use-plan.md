# Real browser use for ankita — implementation plan

Status: the core browser tool, two plugin choices, Playwright runtime, Chrome
DevTools MCP connection flow, CLI toggles, and desktop live stage are implemented.
See [Browser use](../guides/browser-use.md) for current setup and operation.
The browser entries now share the compact integration rows and settings drawer
under **By Ankita team**. Plugins and the live browser use the app's global
appearance tokens; the larger standalone card design below is superseded.
The timeline scrubber, element highlights, and DevTools panel handoff below
remain design proposals.
The desktop now connects Chrome on demand with remembered command approval,
checks for a lost connection before actions, and makes one reconnect attempt.
Disabled backends are excluded from selection. Stop interrupts queued and
in-flight browser requests, including takeover and setup approval waits.
The visible preview targets 10 FPS through direct JPEG results, with a single
request in flight and infrequent tab metadata refreshes. Opening the stage
collapses the left sidebar. Interrupted model streams have bounded step retries.

Goal: let the agent drive a **real browser** — fast and accurately — the way
Codex, Claude, and Manus do, exposed as **two first-party plugins** under a
**By Ankita** section in Plugins:

1. **Playwright Browser** — isolated Chromium, own profile, clean cookies.
2. **Chrome (local)** — the user's own Chrome/Edge, driven via CDP, reusing
   their logins/sessions/residential IP.

---

## 1. How the others do it (research summary)

### Codex / ChatGPT (Operator → in-app browser + Computer Use)

- In-app Chromium with a **shared view**: the user watches what the agent does.
- Vision-first CUA model: screenshots in, mouse/keyboard out (click, type,
  scroll, inspect rendered state, screenshot to verify).
- Alt path: drive the user's real Chrome via extension + native host
  (`@Browser` / `@Chrome`), `browser-client.mjs` + JS execution as the runtime hook.
- Safety: per-site Allow/Block, confirm before submit/purchase/delete,
  **takeover mode** for login/CAPTCHA/payment, file-upload blocked, full CDP
  gated behind Developer Mode + explicit approval.
- Lesson: a visible browser kills the "what did it do?" loop, but pure-pixels
  is slow and fragile. Keep backends (in-app vs Chrome) isolated — Codex's
  live bugs are backend-discovery hangs when the two mix.

### Claude (browser_toolset_20260801 + computer use)

- Best-designed API; copy its shape. One toolset entry declares ~27 default +
  4 opt-in members. The **app hosts the browser**, Claude only calls members.
- Perception = **accessibility tree + pixels**: `read_page` returns the tree
  with `[ref_N]` tags, `find(query)` is natural-language element search,
  `get_page_text` for articles. `screenshot`/`zoom` only when vision is needed.
- Action on **refs, not coordinates**: click/type/key/`form_input` (set value
  directly, no per-keystroke simulation), tab members with a full
  `browser_state` block (never a delta).
- **Batch actions**: several calls per turn run sequentially, halt on first error.
- **Stale-ref contract**: refs die on navigation/DOM change; the error tells
  the model to re-snapshot. No silent wrong-clicks.
- Gated power: `javascript_exec`, `file_upload`, `read_console`,
  `read_network` are off by default, enabled per-member.
- Safety: page content treated as untrusted, fresh low-priv profile, probes
  scan tool results for prompt injection, classifier verifies each action
  against the user request.

### Manus (Sandbox + Cloud Browser + Browser Operator)

- **Sandbox per task**: isolated cloud VM (FS + network + browser + code).
  Sleep/awake lifecycle, per-task isolation.
- **Two browsers** — the key idea to copy:
  - *Cloud Browser*: datacenter IP, clean profile. Good for research/scale,
    hits CAPTCHAs more.
  - *Browser Operator* extension: drives the **user's local browser**, reusing
    logins/sessions/residential IP. Dedicated tab per task, watch live,
    click-to-takeover, close-to-kill, full audit log.
- Controller splits big tasks to parallel subagents and aggregates.
- Takeover prompts for SMS/2FA/CAPTCHA, then hands control back.

### Chrome DevTools MCP (official server — backing for our Chrome plugin)

Source: <https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session>
(Dec 2025, Chrome M144). This changes the Chrome-local backing from
"hand-rolled CDP" to "preconfigured official MCP server":

- **Four connection modes**, in increasing trust order:
  1. MCP-specific user profile (the default — isolated, like our Playwright mode).
  2. Attach to a running Chrome via remote debug port.
  3. Multiple isolated instances, each in a temp profile.
  4. NEW: `--autoConnect` to the user's **active** browsing session — the
     agent reuses existing logins with no extra sign-in (exactly our
     Manus-Operator rationale), and can read an **active DevTools debugging
     session**: select an element in the Elements panel or a request in the
     Network panel and ask the agent to investigate it.
- **Permission model to copy**: remote debugging is off by default and must be
  enabled once at `chrome://inspect#remote-debugging`; every `--autoConnect`
  request pops a Chrome permission dialog; while attached, Chrome shows the
  "being controlled by automated test software" banner. That is our
  approval/takeover UX in Google's words — adopt the same language.
- **Beyond clicking**: the server exposes performance traces, console, and
  network inspection — i.e. our gated diagnostics members (`read_console`,
  `read_network`, JS evaluation) come for free instead of being built.
- **Fits our MCP stack**: it is an MCP server (`npx chrome-devtools-mcp`),
  so install + version-pinned approval + reload reuse the existing
  `mcp_manage` / `/mcp` flow. No new transport code.
- Constraints to note: `--autoConnect` needs a user-started Chrome on M144+;
  the agent cannot silently attach. Panel-data handoff (selected
  element/request) is the seed of a phase-3 "debug what I'm looking at"
  feature.

### Comparison

| | Codex | Claude | Manus | ankita today |
|---|---|---|---|---|
| Sees page as | screenshots | axtree refs + screenshots | screenshots + DOM | markdown text dump |
| Acts via | click/type/CDP | ~31 ref-aware members | click/type/code in VM or local tab | nothing interactive |
| Runs where | in-app browser or user Chrome | browser the app hosts | cloud VM or user browser | one-shot Python fetch |
| Auth | separate profile, sign in per task | fresh profile, no creds | cloud login OR local session reuse | n/a |
| Tabs | yes | first-class `browser_state` | yes, tab group per task | no |
| Batch | no | yes, halt-on-error | parallel subagents | no |
| Safety | site rules, confirm sensitive, takeover | probes + action classifier, gated js/upload | per-session auth, audit log, takeover | SSRF guard only |

ankita today is **read-only scrape** (`web_search`/`web_fetch`/`scrape_low-mid-high`
via the Scrapling bridge: static fetch, escalate to stealth Chromium on
403/429/503 or thin body). Interactive use is only possible via the external
MCP Playwright server (~25 tools, ~4700 tokens, on-demand load) — works but
slow, heavy, no shared view, no ref-stability rules, no auth story.

---

## 2. Proposed shape (two plugins, one tool)

### Plugins (opt-in, no Composio key)

New **By Ankita** section at the top of the desktop Plugins page (above the
Composio catalog, visible even when Composio is unconfigured), with two cards
and toggle switches:

| Plugin | Mode | Backing | Best for |
|---|---|---|---|
| Playwright Browser (`ankita-playwright`) | `isolated` | Playwright + downloaded Chromium, profile under `~/.copilot-chat-cli/browser/` | research, JS-heavy scraping, sandboxed multi-step flows |
| Chrome local (`ankita-chrome`) | `local` | Official **`chrome-devtools-mcp`** MCP server (see §1), preconfigured by us; sub-modes: default isolated profile → remote-debug-port attach → `--autoConnect` to the active session (Chrome M144+, one-time opt-in at `chrome://inspect#remote-debugging`) | authenticated portals, CAPTCHA-heavy sites, anything needing the user's logins/IP; plus DevTools-grade debugging (perf traces, console, network) |

Why DevTools MCP instead of hand-rolled CDP: zero new transport code (it
rides the existing `mcp_manage` install → approve-exact-command → reload
flow), Google maintains the protocol surface, and we inherit the diagnostics
for free. The plugin card offers the sub-mode choice; recommended default is
the MCP-specific profile, with `--autoConnect` as the explicit "use my
session" escalation — mirroring how Manus keeps Cloud Browser default and
Operator opt-in.

### Plugin cards — nice UI/UX, not just toggles

Each By Ankita card is a mini product page (logo, one-line promise, status),
not a settings row:

- **Anatomy**: plugin logo (Playwright mask / Chrome circle), name,
  one-line blurb ("Isolated Chromium for the agent" / "Your Chrome, with your
  logins"), readiness pill (Ready green / Setup needed amber / Error red with
  the concrete reason), version line (Chromium build / `chrome-devtools-mcp`
  pin), and a toggle switch. Expanding the card reveals settings + actions.
- **Setup flows inline** (no terminal spelunking):
  - Playwright: **Install** button runs `npm i -D playwright && npx playwright
    install chromium` with a progress bar, then flips the pill to Ready.
    Show download size (~150MB) upfront so it never surprises.
  - Chrome: step checklist with copy buttons — (1) launch flag or
    `chrome://inspect#remote-debugging` opt-in for `--autoConnect`,
    (2) **Test connection** button that probes `:9222` and reports the
    detected browser string, (3) sub-mode picker (isolated profile /
    debug-port / active session). Each step checks itself off live.
- **Per-plugin settings** (collapsed by default): CDP port, headless on/off,
  profile path, site allowlist/blocklist shortcut, JS-execution gate. Power
  knobs, not onboarding.
- **Health at a glance**: last-used time, tabs opened this week, last error
  with one-click retry. A card that only says on/off teaches nothing; a card
  that says "used yesterday, 14 tabs, healthy" builds trust.
- **Deep link from failure**: when the `browser` tool refuses (plugin off /
  backing missing), the chat error carries an **Open Plugins** button that
  jumps straight to the right card with the needed step highlighted — the
  fastest path from "it doesn't work" to "it's working".

### What else belongs in the plugin experience

- **Inline enable CTA in chat**: first time the agent needs a browser and none
  is enabled, it asks with one-click enable buttons inline (not "go find the
  Plugins page"). Approval + setup start from the conversation.
- **First-run coach mark**: after enabling, a one-time hint bubble points at
  the stage ("runs appear here — watch, stop, or take control anytime").
- **Site permissions manager**: per-plugin list of allowed/blocked sites with
  add/remove, mirroring Codex's site rules — the "serious user" surface that
  makes auto-approve feel safe.
- **Session labels**: each run names its tab group after the task ("Filling
  form · HN login") so the tab strip, timeline, and Work review all tell the
  same story.
- **Update nudges**: when a pinned `chrome-devtools-mcp` or Playwright
  version goes stale, the card shows "Update available" (re-approval on bump,
  same rule as all MCP servers) instead of silently rotting.
- **Keyboard**: `Ctrl/Cmd+Shift+B` toggles the stage (same muscle memory as
  Codex's in-app browser), `Esc` hands control back to the agent during
  takeover.

Enabling records intent only. The tool refuses with actionable next steps
until the backing is actually ready (install Playwright / launch Chrome with
the debug flag). CLI parity: `/browser list|enable|disable`.

### Tool (one schema, not seven — keeps token cost flat)

One deferred `browser` tool in a new `browser` catalog group (loaded via
`find_tools("browser")`), dispatching on `action`:

- `open(url, mode?)` → creates a tab, SSRF-guarded like all web tools.
- `snapshot(filter?)` → axtree-ish listing with `[ref=N]` tags (default
  `interactive`, capped like other tools).
- `act(op, ref, text?)` → `click/type/press/select/fill/hover/scroll/drag`
  on a ref. Refs are epoch-checked: stale ref returns
  "re-read the page", never a silent wrong click. `type`/`fill` always prompt.
- `read / tabs / screenshot / close` → article text, full tab inventory
  (`browser_state`-style), image handoff (desktop panel / `downloaded-images/`
  on CLI), tab teardown.

Prompt rules (not discoverable from schemas, learned from Claude/Codex
postmortems): put search terms in the URL instead of typing into site search
boxes; re-snapshot before each interaction; never retry a failed ref; reads
never prompt, `type`/`fill`/submit/upload/JS always do.

### Safety (merge of all three)

- Reuse the existing SSRF guard on every navigate + redirect hop;
  `BROWSER_ALLOWLIST`/`BROWSER_BLOCKLIST` + `ALLOW_PRIVATE_HOSTS` for dev servers.
- Isolated profile is fresh (no password import). Local mode needs explicit
  per-session approval + a "driving your browser" banner.
- Treat page content as untrusted (system-prompt line); block `javascript:`
  URLs; cap title/URL lengths; log every act to the transcript.
- Takeover pattern for logins/CAPTCHAs: pause the agent, user acts, hand back.
  Chrome's own model (enable once at `chrome://inspect#remote-debugging`, allow
  per attach request, banner while controlled) is the UX to mirror so users
  meet one consistent mental model, not two.
- Gated diagnostics (`read_console`, `read_network`, JS evaluation, perf
  traces) arrive via DevTools MCP rather than custom tools — same approval
  posture (off by default, per-task enable), none of the maintenance cost.

### Desktop shared view (wanted badly — phase 2) + DevTools handoff (phase 3)

- `BrowserPanel`: live view of the active tab via CDP screencast (or 1fps
  Playwright screenshots while a browser tool runs), with Takeover / Hand-back
  buttons. Main process owns the browser (process-level, like MCP servers, so
  REPL/Telegram/routines share it); the renderer only displays + approves.
- Status line + trajectory in Work review (`snapshot` diffs, screenshots).
- Phase 3, straight from the DevTools MCP post: **"debug what I'm looking
  at"** — the user selects an element (Elements panel) or a failing request
  (Network panel) in DevTools and asks the agent to investigate. No new
  protocol work; it falls out of the DevTools MCP backing once the Chrome
  plugin exists.

---

## 3. Build order

1. `src/integrations/browser-plugins.mjs` — plugin definitions
   (`ankita-playwright`, `ankita-chrome`), `BrowserPluginStore`
   (`~/.copilot-chat-cli/browser.json`), readiness probes.
2. `tools/browser/session.mjs` + `tools/browser/browser.mjs` — session manager
    (persistent context per mode, ref epochs, batch-halt semantics) + the
    single dispatch tool. Executors lazy: dynamic-import Playwright for
    isolated; Chrome-local delegates to the preconfigured `chrome-devtools-mcp`
    server (no hand-rolled CDP client).
3. `tools/catalog.mjs` + `src/core/agent.mjs` + `tools/find-tools.mjs` —
   deferred `browser` group, prompt hint lines, discovery keywords.
4. Desktop: `DesktopBrowserPlugins` store wrapper, `browserPluginsOverview` /
   `browserPluginSetEnabled` IPC, By Ankita section in `PluginsPage.tsx`,
   `wire.ts` types. CLI: `/browser` command.
5. Tests: `test/tools/browser.test.mjs` (ref lifecycle, gating, approvals,
   store round-trip) + a live verify script against example.com and a local
   demo form. Keep `npm test` and desktop `tsc --noEmit` green.
6. Phase 2: real axtree extraction + screencast panel + takeover.

---

## 5. UI/UX design — "see what's going on inside"

Reference: the user's screenshot (Manus-style run view). It nails the pattern:
a live browser stage beside the chat, a task header with site + Stop + "Take
control of the browser", a tab chip, the page rendered in a frame, and a
compact repeat of the same state inside the chat thread (Browse card with live
thumbnail + "Open browser", agent avatar with an "Applying login" status
pill). Copy that skeleton, then beat it with animation and framing.

### Layout — two surfaces, one session

1. **Browser stage** (right split pane in the desktop app, same session as the chat):
   - Header: task title ("Filling form"), live status line
     ("Working · news.ycombinator.com"), red **Stop**, blue **Take control of
     the browser**, close X.
   - Tab strip: favicon + truncated-domain chips for every open tab (mirrors
     the `tabs` tool's `browser_state`, never a delta).
   - Read-only URL bar under the tabs (current URL + lock icon) — the user
     reads where the agent is; navigation stays agent-driven.
   - **Framed viewport**: the live page inside a "computer" frame — rounded
     corners, subtle shadow/border, tab chrome on top — so it reads as a
     monitor inside the app, not a bare image. Feed: CDP screencast where
     available, else ~1fps screenshots while a browser tool runs.
2. **Chat-embedded browser card** (in the message thread, same live session):
   - Globe icon + "Browse / <task>" title, live thumbnail of the viewport,
     **Open browser** button that expands to the full stage.
   - Agent avatar with an animated status pill naming the current micro-step
     ("Applying login", "Reading results") — one glance tells you the *what*,
     the thumbnail tells you the *where*.

### Animation — make every agent action visible

- **Act flash**: after each `act`, pulse a highlight ring on the target
  element's box for ~800ms so the eye lands where the agent just clicked/typed.
- **Typing caret**: blinking caret + streaming characters in the field while
  the agent types (thumbnails update mid-action, not just after).
- **Ghost cursor**: a distinctively colored virtual cursor showing the agent's
  pointer, visually separate from the user's own cursor — same idea as Codex's
  "own cursor".
- **Status pill lifecycle**: Working → Acting ("Clicking Sign in…") →
  Verifying (fresh screenshot) → Done / Needs you. Animated transitions, never
  a static label.
- **Expand/collapse**: smooth shared-element-style transition between the chat
  thumbnail and the full stage; keep the thumbnail live (small, low-fps) so
  the thread stays glanceable.
- **Connecting skeleton**: shimmer placeholder while the backing starts
  (Playwright launch / CDP attach), with the concrete next step printed
  ("Launching isolated Chromium…" / "Waiting for Chrome permission dialog…").

### Takeover — the blue button is the whole trust model

- Click **Take control of the browser** → agent pauses mid-loop, banner flips
  to "You're in control — agent paused", ghost cursor hides, input routes to
  the page. **Hand back** resumes exactly where it stopped (refs are
  re-snapshotted, never reused across the handoff).
- Closing the stage tab = stop the run (Manus rule: close-to-kill).
- Chrome `--autoConnect` permission dialogs and login/CAPTCHA moments
  auto-suggest takeover with one click, instead of the agent stalling.

### Better than the screenshot

- **Action timeline scrubber**: step list under the stage (navigated →
  snapshot → clicked login → typed…) synced with the viewport; click any step
  to see that moment's screenshot (trajectory viewer, like Claude's `runs/`).
  This is also what lands in Work review.
- **Numbered callouts**: badge each interacted element in the viewport
  matching the step list, so "step 3" points at a visible marker.
- **Mini PiP**: when the user scrolls away in chat, the live view collapses to
  a floating mini-frame that follows — the run stays visible without hogging
  layout.
- Multi-tab strip from day one (the screenshot shows one tab; our
  `browser_state` already models many).

### States to design explicitly (not as afterthoughts)

Loading/connecting, permission-requested (Chrome dialog pending), takeover
(you drive), blocked (site allowlist/SSRF refusal with reason + retry),
auth-needed (suggest local-Chrome sub-mode when isolated hits a login wall),
error with one-click retry, and empty (no tabs yet → "Ask me to open a page").

### Non-desktop surfaces

- CLI: no live view — screenshots land in `downloaded-images/`, snapshots
  print as text; `--plain` stays axtree-only.
- Telegram/mobile: push latest screenshot + one-line status per milestone;
  takeover unavailable there, so progress is read-only with a Stop command.

---

## 6. Open decisions (not yet locked)

- Single dispatch tool vs one tool per action (single keeps the schema cheap;
  per-action is more Claude-faithful but costs context every turn).
- Whether local mode auto-launches Chrome with the debug port or only
  attaches to an already-debuggable instance. (DevTools MCP's answer:
  `--autoConnect` requires a user-started Chrome on M144+ and asks permission
  per attach — default to that posture; auto-launch only for the isolated
  profile sub-mode.)
- Screenshot cadence for the shared view (CDP screencast vs polling).
- Pin strategy for `chrome-devtools-mcp` versions (approval is remembered per
  exact command, so bumps re-prompt — same rule as all MCP servers).
