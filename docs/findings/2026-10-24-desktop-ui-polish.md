# Desktop UI polish — 2026-10-24

Status: implemented and covered by UI tests; packaged-desktop screenshot review
remains open.

## Problems observed

- Engine failures printed the transport string verbatim, including
  `Error invoking remote method 'engine:invoke'` and the listening port, in the
  floating error toast. The text was not actionable and covered the composer.
- Connection state used at least ten different dot treatments (bare dots, halos,
  coloured text, pills) across the chat header, sidebar, jobs, browser stage,
  plugins, review runs and ChatGPT settings.
- Providers stacked every action as a separate full-width-looking button.
  ChatGPT settings mixed browser choices, teammate selection, setup, session
  actions and native-tool setup without a stable reading order.
- Settings forms mixed the old beige accent with the graphite/slate accent,
  used native selects with a different height from inputs, and the privacy
  toggle used `window.confirm`.

## Changes

- `desktop/shared/error-notices.mjs` humanizes IPC, scheduler, network, auth,
  quota, disk and permission failures. The raw string and the hint live in an
  anchored `Details` popover; the visible card stays two lines tall.
  `cleanErrorMessage()` is now shared by Plugins, Skills, browser plugins,
  Settings and ChatGPT settings instead of three copy-pasted regexes.
- `NoticeCard` + `.notice-stack` replace the toast: compact dismissible cards
  (icon, title, two-line detail, `Details`) in a 340px top-right stack below the
  update banners. The popover is bounded to 320×260 with its own scroll and
  closes on Escape or an outside click, so technical text never stretches the
  card across the chat. Secret confirmations auto-dismiss; errors do not.
- **Capture bridge conflicts are no longer engine failures.**
  `desktop/electron/capture-actions.mjs` runs every `CAPTURE_ACTIONS` request
  through one boundary: a remembered-port conflict returns
  `{ unavailable }` for setup and inert values (`[]`/`false`) for polling,
  registration, cancellation and acknowledgement instead of rejecting
  `engine:invoke`. `BrowserHelperSetup` explains that result with the shared
  humanizer. Passive mascot hover/focus refreshes are quiet, and neither mascot
  tooltip prints capture messages, so the old raw bubble has no source.
- **Island failures use the same human copy.** `useIslandChat` and the island
  error card pass engine, send, cancel and scheduled-job failures through
  `describeErrorNotice`, so the floating companion no longer prints transport
  prefixes either.
- **Dev shutdown owns the process tree.** `desktop/scripts/process-tree.mjs`
  terminates the whole task tree on Windows (`taskkill /T /F`) and signals the
  detached process group on POSIX; `dev-server.close()` awaits that before
  releasing Vite. `dev.mjs` handles `SIGINT`, `SIGTERM`, `SIGBREAK` and `SIGHUP`,
  so an interrupted `npm run desktop:dev` no longer leaves an Electron host
  holding the persisted capture port and scheduler lock.
- `StatusPill` is the single state language (`live`, `busy`, `warn`, `error`,
  `idle`) for the conversation header, ChatGPT connection and tool cards,
  channel status and sidebar phase. Remaining bare dots share the same 6px dot
  and 3px halo geometry.
- Providers: one calm provider column with radio cards, grouped browser choices,
  one setup action row (`primary` + `secondary`), a separated session row with a
  destructive text action, and one save bar. Inputs and selects share height,
  radius, focus ring and token colours.
- Settings: inline danger confirmation for secret scrubbing (`alertdialog`),
  switch rows for Telegram/privacy, tokenized banners, navigation, modal shell,
  theme cards, About page, success/error notices and focus states.
- Chat chrome: unified header pill, gold rail active indicator, composer focus
  ring, tokenized update and version-mismatch banners, shared focus-visible ring.
- Chat chrome, final pass (screenshot feedback):
  - The composer adds a `:focus-visible` override for its textarea
    (`desktop/renderer/src/workbench.css`), so the rounded shell border and
    accent glow are the only focus frame. The global blue ring no longer draws a
    second square rectangle around the text box.
  - The green `Ready` / `Working` pill is gone from the conversation header.
    Blocked-reply state still disables Send and explains itself through the send
    button tooltip, which existing tests assert.
  - The `↗` browser-helper badge is removed from the mascot corner. The setup
    moved to the header `Conversation options` menu → `Browser helper`, which
    opens the same `BrowserHelperSetup` in a bounded dialog. Pairing remains
    reachable in the main window and in the island's Settings view.
  - The mascot drag hint now says `Pair Chrome/Edge in Browser helper first`
    instead of pointing at the removed corner menu.

## Verification

- `npm run desktop:build` (tsc `--noEmit` + Vite production build): passed.
- Final header/composer pass:
  - `test/desktop/companion-capture-ui.test.mjs` asserts the focused textarea
    computes `outline-style: none`, `.conversation-state` and
    `.companion-helper-toggle` both render zero times, and helper setup still
    opens from `Conversation options` → `Browser helper` with the same human
    unavailable copy.
  - `test/desktop/chatgpt-first-use-ui.test.mjs` waits on the Send button's
    disabled state instead of the removed pill; blocked replies still preserve
    the draft and show the Settings/Providers title.
  - Serial run of the three affected UI suites: **3/3 passed**
    (`companion-capture-ui`, `chatgpt-first-use-ui`, `error-notice-ui`).
  - `tsc --noEmit -p desktop/tsconfig.json`: passed.
  - Headless screenshots at 1280×800 confirm the rounded composer border with
    no square outline, a header without the green pill or corner badge, and the
    helper dialog fitting inside the viewport.
  - `scripts/verify-desktop-workbench.mjs` was updated to open the helper from
    the header menu and measure `.helper-dialog`; the script was syntax-checked,
    not re-run (it needs the live desktop bridge).
- `test/desktop/error-notices.test.mjs`: 6/6 passed (copy mapping and technical
  preservation).
- `test/desktop/error-notice-ui.test.mjs`: 1/1 passed with a real `App` render:
  the card measures under 80px, raw transport text is absent until `Details` is
  opened, the anchored popover stays under 340px wide and does not grow the card,
  Escape closes it, dismissal works, no page errors.
- `test/desktop/capture-actions.test.mjs`: 5/5 passed. Covers a synthetic
  `engine:invoke` rejection, inert values for all background actions, action
  dispatch with the calling window identity, helper-folder isolation, and a live
  two-`CompanionCapture` conflict on the remembered port (real HTTP, no
  rejection).
- `test/desktop/companion-capture-ui.test.mjs`: 1/1 passed with a real `App`
  render: hovering the mascot while setup rejects leaves no
  `.companion-capture-toast`, the tooltip contains no transport/port text, and
  both rejection and `{ unavailable }` helper results render the human notice
  without offering a pairing code.
- `test/desktop/process-tree.test.mjs`: 1/1 passed with real Node processes; a
  spawned parent's `setInterval` descendant is gone after shutdown.
- `test/desktop/desktop-dev.test.mjs`: 3/3 passed after switching shutdown to
  `terminateProcessTree`.
- Focused serial run across capture, notices, dev, island, mascot, layout and
  provider suites: **54/54 passed**.
- `npm run desktop:build`: passed (tsc `--noEmit` + Vite production build, 383
  modules).
- `test/desktop/settings-providers-ui.test.mjs`: 1/1 passed — provider cards
  share one column, browser choices and setup actions share rows, selects match
  field height, one save bar, no horizontal overflow, no page errors.
- `test/desktop/chatgpt-connection-ui.test.mjs` and
  `test/desktop/chatgpt-first-use-ui.test.mjs`: 1/1 each passed after the layout
  change, preserving every existing accessible name and payload.
- `desktop-settings`, `desktop-channels`, `desktop-layout` and `desktop-plugins`:
  34/34 passed.
- Headless screenshots at 1000×768 (`chat-notice`, `chat-notice-details`,
  `companion-helper-unavailable`) plus the earlier 1200×820 set were reviewed.
  The compact card measures about 64px tall, its `Details` popover stays inside
  a 320×260 box and does not resize the card, and the helper status reads as a
  human sentence. The notice stack still sits below the version banner.
- Full serial suite (`node --test --test-concurrency=1`): **1,429 passed, 5
  failed, 1 skipped, 1,435 total** (`duration_ms 1705264`). All five failures are
  pre-existing and unrelated to this diff; details below. The run stalled once
  in `test/tools/developer-tools.test.mjs` waiting for its disposable
  `setInterval` child, which survived `kill_process`; ending that child let the
  remaining suite finish.

## Grouped transcript activity (follow-up)

The first pass left every tool call as its own boxed card and rendered a
reasoning-only assistant message as an empty assistant bubble. Long agent turns
therefore stacked dozens of cards and blank replies between the prompt and the
answer.

- `desktop/renderer/src/lib/activity.ts` folds the stored flat transcript into
  render blocks. Consecutive generic tool calls and reasoning-only assistant
  messages become one activity group; a content-bearing assistant message stays
  the prominent answer; edited-file stats are read from the filesystem tools'
  existing receipts (`+a -r`, `Created … (N lines)`, and `apply_patch` file
  lines) and summed per path.
- `ActivityGroup` renders one collapsible `Ran N tools` block with compact
  one-line rows: status glyph, humanized label, monospace argument chip, and a
  truncated thought preview. Rows open their own input/result inline. Failed
  rows and the group header stay marked, but failures no longer auto-expand a
  large detail block.
- `ToolCallCard` gained a `row` variant that reuses the same detail body,
  image/stock previews and browser-setup action. The default card variant is
  unchanged. `delegate_task`, `schedule`, browser sign-in and image results keep
  their dedicated cards; hidden tools stay hidden.
- `EditSummaryCard` closes each edited turn with `Edited N files`, total
  `+added -removed`, up to three file rows, `Show N more files`, and a `Review`
  action that opens the existing Work review panel.
- Tool labels were shortened to compact row phrases (`Read file`, `Edit file`,
  `Ran command`, `Find files`) without changing tool identity.

Verification: `npx tsc --noEmit -p desktop/tsconfig.json` passed.
`node --test --test-concurrency=1` over `transcript-activity-ui`,
`companion-capture-ui`, `error-notice-ui` and `chatgpt-first-use-ui` passed
**4/4**. The new `test/desktop/transcript-activity-ui.test.mjs` seeds a real
transcript and asserts five tool rows, two thought rows, no empty assistant
bubbles, failed-row marking, row-level expansion, group collapse/reopen,
live-turn spinner, and `Edited 2 files +121 -4`. Screenshots were captured to a
scratch directory and reviewed (not committed). The full serial suite and a
packaged-desktop pass were not re-run for this follow-up.

Limits: delete/move tools do not contribute line counts, and edit attribution is
per turn rather than per git commit; `Review` opens the workspace-wide panel
instead of a per-file diff.

## Live sub-agent side panel (follow-up)

The inline `delegate_task` card is useful after the fact, but a running child was
easy to miss in a long transcript. A newly delegated child now takes the right
side slot so its work stays visible while the chat narrows beside it.

- `App` merges live `state.subagents` with `activityFromReceipt` transcript
  fallbacks, then focuses a child the first time its live key appears. The panel
  opens for new work only; historical receipts stay inline until opened.
- `SubagentPanel` shows the child's type, description, status, elapsed/total
  duration, tokens, depth, tool count, streaming output with a caret, tool rows,
  summary, task brief and transcript path. Multiple children sharing a turn get
  a status-dot switcher, and the panel keeps following the child the user is
  watching rather than the newest one.
- Closing the panel returns the chat width and does not re-open by itself. While
  it is open, inline `delegate_task` cards are hidden so the run is not shown
  twice; they return to the transcript as anchors when the panel closes. The
  context-bar `N agents working` chip and the restored inline card's
  `Watch live` / `Open in side panel` action reopen it, remembering the last
  focus.
- Review, browser, job sheets and the sub-agent panel share one side slot:
  opening one closes the others, and auto-open defers while the browser stage or
  a job sheet owns the slot. Workspace changes raised by the child no longer pop
  Work review over the live panel.
- Below 1200px the panel becomes a fixed overlay so the chat does not keep
  shrinking. Labels, statuses and tones moved to
  `desktop/renderer/src/lib/subagent.ts`; card and panel share `SubagentTools`.

Verification: `npx tsc --noEmit -p desktop/tsconfig.json` passed and
`npm run desktop:build` produced 393 modules. The new
`test/desktop/subagent-panel-ui.test.mjs` passes 1/1 in a real Chromium
renderer: history stays inline, a `subagent-start` auto-opens the panel, the
chat narrows by more than 200px, streamed text and a completed tool row appear,
the inline delegate card is hidden while the panel owns the run, a second child
joins the switcher without stealing focus, completion shows `Done` without a
spinner, close restores both the chat width and the inline card, the chip and
inline card reopen the remembered run, and 1100px switches the panel to
`position: fixed`.
Adjacent suites passed 9/9 (`subagent-state`, `transcript-activity-ui`,
`error-notice-ui`) and 2/2 (`companion-capture-ui`, `chatgpt-first-use-ui`).
The bridge was stubbed; no packaged-desktop pass was run for this follow-up.

Limits: auto-open is skipped while the browser stage or a scheduled-job sheet is
open, and a completed child reconstructed only from a receipt has no live key,
so it never auto-opens. The switcher shows descriptions rather than a full
per-child history, and deeply nested delegation is out of scope because children
cannot recurse.

## Jobs card and sub-agent density pass (2026-10-25)

The first pass gave the jobs card above the composer more room, then user
feedback showed the card itself was the problem: scheduled work should not
occupy composer space on every message. The card was removed and its status
moved into the context bar. The live child panel also stayed dense: 10–11px
rows, actions press-fit together, 28 near-identical `Read a page` rows, and
output rendered as one unbroken monospace block.

- The always-visible `JobsPill` above the composer was removed. One context-bar
  chip now carries the live summary (`1 job · All paused`, `Running`,
  `Needs attention`, or `Next …`), adds a dot for running or blocked work, and
  opens the existing Scheduled tasks panel for names, timing and actions.
  `nextRunLabel` and the attention rule moved to `lib/jobs.ts` so the chip and
  panel cannot drift. The composer keeps the full message-box width.
- `SubagentTools` folds consecutive same-name runs longer than three into one
  expandable row with a call count and aggregate state; long runs start folded.
  Source URLs lose their scheme for scanning while the full argument stays in
  the tooltip. Single rows gained status chips, and the same component still
  powers the inline card.
- The panel widened to `clamp(360px, 31vw, 440px)`, raised its title to 14px,
  separated status facts with middots, and renders output/summary/brief in the
  UI font at 12.5px/1.72 with `text-wrap: pretty`. Section spacing is 18px,
  chips and tool rows share new sub-agent accent tokens, and the task brief uses
  a custom disclosure arrow instead of the browser default.

Verification: typecheck passed and `npm run desktop:build` produced 393 modules.
`test/desktop/jobs-entry-ui.test.mjs` passes 1/1 in real Chromium — no
`.jobs-pill` or `.jobs-composer` wrapper, `Schedule` when empty, `1 job · All
paused` for a paused routine, no dot when paused, a pulsing dot while running,
amber attention for blocked work, pluralized `2 jobs · 2 need attention`, and
the chip opening the task list. `subagent-state.test.mjs` passes 8/8 including
the new fold test (six reads → one row, expand to six, scheme-stripped hint).
`subagent-panel-ui.test.mjs` passes 1/1 with six seeded fetches folding into one
row and an output line-height ratio of at least 1.6. The full `test/desktop`
suite passes 291/291. Captures reviewed:
`.tmp-ui-captures/jobs-header-entry.png` and `subagent-panel-live.png`.

Limits: the chip hides its text below 1050px and keeps only the clock and dot;
the panel still owns `Run now` / `Edit` / `Pause`, so those actions are one
click further away; folding only groups consecutive calls, so interleaved tools
stay in sequence; output bytes are not re-paragraphed, only re-typeset;
verification is Chromium with a stubbed bridge, not the packaged desktop.

## Existing suite failures (not caused by this diff)

- `test/core/browser-workflow.test.mjs` — the same three baseline failures
  recorded on 2026-10-22/23/24: both managed-browser discovery tests miss the
  tool budget (`budget=21313` / `21212`, `core=16422`) and the live form flow
  receives `fill_form needs 1 to 10 fields…` instead of `Filled 2 fields`.
- `test/desktop/desktop.test.mjs:105` and `:146` — these engine tests omit
  `settingsFile` and `sessionsDir`, so `DesktopEngine` reads the real
  `%CONFIG_HOME%\desktop-settings.json`. On this machine that file selects
  `chatgpt-browser`, so the injected `FakeAgent` is bypassed and both tests fail
  with `Connect your existing ChatGPT conversation in Settings before sending.`
  They reproduce in isolation and are a test-isolation gap, not renderer code.

## Remaining

- Run the packaged Windows build and review the same screens live, including
  the native select popup and window chrome.
- The two-process conflict was reproduced with real bridge instances and the UI
  path with a rejected stub, not by launching the packaged app alongside a
  second dev instance on a desktop session. That final manual check remains.
- No light theme exists; contrast was checked on graphite, and token-level
  overrides for mono/slate only by construction.
