# Changelog

Every notable change to Ankita is recorded here, newest first. The dated
releases mirror the entries in the root [`CHANGELOG.md`](../../CHANGELOG.md) that
the release workflow publishes to GitHub; "Unreleased" collects work that is in
the tree but not yet packaged.

## Unreleased

No unreleased changes.

## 2.5.1 — 2026-10-09

### Browser reliability, evidence and desktop progress

- Automatic browser instructions precede decisions that advertise browser tools;
  an actual whole-body request receipt appears in the desktop header. The next
  turn/clear resets it. No router or memory migration is added.
- Mixed independent fills/clicks/selects preflight current targets and defer
  intermediate snapshots, preserving original refs. Replaced/blocked targets
  stop with accurate partial receipts and fresh controls; no automatic replay.
- Connected Chrome startup separates blank-tab creation from its first site
  navigation, using the observed native page ID. Ambiguous tabs, Stop and refused
  navigation do not replay; the change adds one native call and no model round.
- Markdown reads, bounded literal find/chunks, hidden DOM evidence and native
  control-state flags improve page interpretation. Actual node identity prevents
  same-label/cloned-ref retargeting. Original flight goals survive bounded history
  trimming, and route/date/results evidence is checked before completion claims.
- Live browser phases, per-scope state, takeover dialogs and throttled hidden
  previews make active work and uncertainty visible. Source dev profiles avoid
  installed-app cache contention, and shutdown releases the companion after drain.
- Experimental structured receipts, guarded Playwright sequences, explicitly
  selected uploads and bounded workspace downloads remain behind runtime V2.
  Browser focus, request projection, retained evidence and progress diagnostics
  remain independently opt-in, with no causal speed claim.

### Providers, terminal and release checks

- Provider errors distinguish quota/rate limits from authentication, paid/client
  restrictions, image support and upstream failure. Keyless Kilo discovery keeps
  eligible free routes, and vision support uses catalogue metadata.
- CLI help, `/commands`, subcommand completion and typo suggestions use a shared
  registry. Startup shows version/provider; Composio tier arguments are validated.
- Default tool rounds increase to 100 with the separate call/repeat/Stop guards
  retained. Failed Windows job termination is recorded without claiming exit.
- Main/lab native regression, actual HTTP/renderer receipts and release metadata
  checks accompany the repair. CI downloads locked Chromium before tests. Full
  source release notes are in [CHANGELOG.md](../../CHANGELOG.md#251---2026-10-09),
  with measured outcomes and known model/native-desktop limits in
  [browser findings](../browser-use-reference-findings.md).

## 2.5.0 — 2026-10-05

### Desktop workspace, companion and capture

- The main desktop and floating island share graphite surfaces, system type,
  mascot faces and action-driven motion. Responsive navigation keeps teammate
  selection and window controls available in smaller windows.
- The live island retains drafts, streams actual tool states and keeps four
  avatars in two columns. Scheduled jobs remain activities rather than teammates;
  long approval details scroll while decision buttons remain visible.
- Mascots anticipate and swallow dropped files, chew during extraction and react
  to actual reader outcomes. Chrome/Edge's separately loaded MV3 helper captures
  readable page text through paired loopback IPC and single-use drag tickets.
  Captures stay with their original teammate, retain drafts and never auto-send.
- Projects separate the overview, tasks and searchable context; notes expand on
  demand. Scheduling/settings show useful owner, next-run and actual job status.
  Failed saves retain text and startup controls retain confirmed state.
- Saved Markdown is memoized during streaming, idle/hidden animations stop work,
  and hard focus rectangles are removed across desktop and island controls.
- README and release/setup instructions are rewritten. Generated launch-film HTML
  is untracked with its local copy retained; logs, media and dumps are ignored.
- Root [release notes](../../CHANGELOG.md#250---2026-10-05) include the previously
  unreleased Composio work below. The installed release includes the companion's
  software attribution and unpacked browser helper.

### Composio Direct-MCP: approval tiers, tier controls, keyless sign-in — 2026-10-01

- MCP tool calls resolve a four-level approval tier (auto-allow, ask once, always
  ask, deny) instead of the old read-only-hint rule. A connection's `trusted` flag
  no longer skips the gate — that flag vets the server, not its actions, and it is
  what let a connected Gmail send mail with no prompt. Composio meta-tools are
  classified by the worst action they enclose: `COMPOSIO_MULTI_EXECUTE_TOOL`
  wrapping `GMAIL_SEND_EMAIL` asks, `COMPOSIO_SEARCH_TOOLS` does not. The
  resolution order is blocklist → explicit tool rule → per-app rule → locked app
  defaults → heuristic, and a heuristic can never reach deny. Overrides, a
  blocklist and allowed/asked/denied counters persist to `mcp-tiers.json`
  (`CONFIG_DIR`), deliberately separate from the MCP server records so the
  synthetic `composio` connection never makes `reconcile()` spawn a process that
  does not exist. `gmail` ships locked to *always ask*.
- `composio` gains `tiers`, `allow`, `always` and `deny`, and the management tool
  is refusal-guarded so auto-approve can never loosen protection. This closes the
  one real scheduled-job hole: a job holds the management tool and runs with
  `autoApprove: true`, so it could previously persist a lower tier that then
  applied to every later interactive session. A scheduled job still cannot reach
  `mcp__composio__*` at all — `JOB_TOOLS` contains no `mcp__*` entry, which
  `test/core/background-worker-policy.test.mjs` asserts.
- Keyless sign-in lands: discovery, dynamic client registration (public client,
  `token_endpoint_auth_method: none`), PKCE S256, a single-use `127.0.0.1`
  loopback callback validated against `state`, and a vault-only access token. The
  grant file carries no secret, and revoking drops the vaulted token and the
  metadata together. The RFC 8707 `resource` indicator is now sent on both the
  authorization and token requests — the MCP authorization spec requires it, and
  omitting it is the difference between a granted sign-in and a 400 at the token
  endpoint. The endpoint allowlist accepts the sibling `login.composio.dev` host
  that the live Composio metadata actually uses. Nothing needs to be hosted.
- `composio status` appends a deprecation notice naming the exact variable to
  replace, derived from `package.json` rather than written down, and worded so it
  never tells the user to run a switch the build does not offer yet.
- Evidence: `test/integrations/mcp-tiers.test.mjs`,
  `test/integrations/composio-deprecation.test.mjs`,
  `test/integrations/composio-oauth.test.mjs` (real stub authorization server over
  real HTTP, PKCE recomputed server-side) and new assertions in
  `test/core/background-worker-policy.test.mjs` and `test/desktop/desktop.test.mjs`
  (engine wiring, live local MCP mount over Bearer). Live Composio sign-in with a
  real account remains outstanding; discovery, DCR support, PKCE method and the
  resource requirement were checked against the real published metadata.
  Implementation ledger: [composio-direct-mcp-implementation.md](../plans/composio-direct-mcp-implementation.md).

### Plugins: real integration icons and a rebuilt browser vault — 2026-10-01

- Every Composio app row renders its real brand mark from the toolkit's logo URL
  (the catalog was already receiving it and dropping it). The curated marks and
  the monogram remain the offline/unknown fallback, so a row never shows an empty
  tile. Only the logo CDN is added to the renderer's `img-src`, and
  `pluginLogoUrl()` drops any logo that is not https on that host before it ever
  reaches an `<img src>`.
- **Saved sign-ins** is rebuilt as a first-class section of Plugins rather than a
  collapsed disclosure: a section head with a live count, a framed browser-vault
  card explaining that it is what the built-in browser and Chromium fill from, and
  rows showing the site, username, last-saved time and a Remove action, with
  loading, empty and error states. It loads on mount and refreshes on
  `secure-store-changed`.

### Scheduled task UI rework and thread scoping — 2026-10-01

- The jobs panel groups tasks by state (needs attention, running, upcoming,
  paused) with a summary line, count badge and stat tiles; run receipts read as
  plain status labels with relative times; the pill shows a live status dot. The
  scheduler surfaces use theme tokens instead of a green success color, and their
  motion is transform/opacity only and honours `prefers-reduced-motion`.
- Fixed: a scheduled task and its run result could appear in a different
  teammate's conversation. `App.tsx` passed unfiltered `state.jobs` to the panel
  and routine sheet while the chat pane received the thread-filtered set; both now
  receive the same thread-scoped jobs plus the thread id.
- The panel also no longer mirrors the task prompt (it stays editable in the
  routine sheet), and the "latest run" card was rewritten in plain language.

## 2.4.4 — 2026-09-30

### Teammate-written scheduled results — 2026-09-30

- The owning desktop teammate writes the final chat update from the completed
  worker result with a tool-free model call. A compact, collapsed run record
  keeps the raw details and browser proof available without replacing its reply.
- Delivery waits for a live chat turn and saves the model draft before acknowledging
  a run. Retrying after a provider failure or restart does not repeat browser work
  or create a second chat answer. The desktop app verifier covers two completed
  browser submissions, two teammate handoffs, and reload restoration.

### Scheduled task completion fixes — 2026-09-28

- Regular desktop tasks finish without token, active-time or fixed tool/search-count
  cutoffs. Usage accounting remains; Stop, real blockers and no-progress detection
  still work. Explicit limits are optional, and heartbeats retain bounded defaults.
- Watch-live tab selection is independent from the worker's target and refs.
  Navigation to other app pages leaves jobs running; completion proof follows
  the worker's page. Details and editing expose
  the actual task prompt, and last-successful-result context supports comparisons
  even after a failed run. See the [verification record](../plans/scheduled-job-completion-fixes.md).
- Malformed credential-field selections return fresh refs and schema guidance
  before vault access or filling, allowing the model to correct the call and
  continue. Packaged tests reproduce and recover this mistake on both login runs.

### Chat scheduling, secret protection and command palette — 2026-09-28

- Desktop models receive `schedule` directly, with active creation, identity-preserving
  updates, idempotency, lifecycle controls and structured task receipts. Compact chat
  cards open a thin upcoming list; advanced manual settings remain optional.
- New jobs browse autonomously in their own persistent Chromium profile. Existing
  scoped permissions remain intact. Fresh project context, idle heartbeat, quiet
  receipts and explicit MFA/foreground outcomes are supported. Mobile is unchanged.
- Worker browser schemas advertise isolated Chromium only. Missing login URLs bind
  the selected tab; saved credentials remain private even when password visibility
  changes. Generic unattended password fill/type cannot substitute guessed values.
- Both browser adapters preflight form targets. Validation failures return fresh
  refs before any write; uncertain partial writes stop without replay. Chrome custom
  toggles remain supported and dialog interruptions are reported as incomplete.
- Printed tool-call text receives one bounded native-tool correction. Repetition or
  exhausted tool loops cannot become successful job receipts. Owned Chromium cleanup
  shares one close across concurrent network-error and scheduler callbacks.
- Secrets are scrubbed from persisted/exported copies while live model input remains
  usable. Explicit save intent stores an OS-encrypted named value; ordinary pastes
  remain transient. Managed transcript, job state, daemon log, export and diagnostic
  artifacts migrate once. Detection limits and configuration exclusions are documented.
- Ctrl/Cmd+K searches commands, jobs and skill manifest contributions. Keyboard focus,
  async result readiness and normal job/skill execution paths are preserved.
- Local multi-step authentication, repeated expired-session runs, private vault fills,
  MFA, task cards and palette execution are exercised in the actual Windows app.
  Scripted model fixtures and real-provider results are reported separately in the
  [verification ledger](../plans/assistant-scheduling-security-implementation.md).

### Desktop scheduled browser jobs — 2026-09-28

- The Electron main process owns timezone-aware cron jobs, fresh serial workers
  and isolated Chromium profiles. Results and bounded proof receipts land in the
  owning teammate's chat; live chat and browser cancellation remain independent.
- Added the routine sheet, jobs pill, readonly model status tool, inline scoped
  approvals, saved-only login, optional daily budgets and bounded approval waits.
  New chat-created jobs use the autonomous policy described above; existing scoped
  jobs keep their permissions. Failures never retry the browser
  task automatically. Pending delivery can retry without repeating an action.
- Close/minimize hides to the tray; Show, Pause all and Quit are available there.
  Startup is opt-in. PID ownership and cooperative CLI takeover prevent two hosts
  from scheduling the same store concurrently.
- Per the user's backend decision, background jobs use isolated Chromium only.
  Redirect and Fetch/XHR interception precedes request dispatch, including popups
  and embedded frames. Foreground Chrome remains available. Mobile is unchanged.
- Development and packaged Windows round trips passed actual browser submissions,
  chat concurrency, approvals, live preview, tray/reload receipt delivery and
  relaunch ownership release. See the [evidence and limits](../plans/desktop-background-jobs-implementation.md).

### Model-directed credentials and Telegram progress — 2026-09-27

- Replaced detector-gated credential requests with explicit model calls. Login
  without fields opens the secure dialog and returns refs; `credential_fields`
  maps observed refs to private username/password slots, with optional
  `submit_ref`. The model handles sequential login screens, inspects the result
  and continues the task. No form or sign-out-name heuristic gates this flow.
- Transient credentials remain main-process only, scoped to thread/origin/tab/
  page, and clear on password use, Stop, turn end or expiry. Control type, node
  identity, origin and native GET guards still apply. IPC contract is now 7.
- Telegram desktop/CLI channels gained four-second typing heartbeats,
  five-second throttled tool labels, supported bot-ack reactions, current-turn
  image uploads with containment/size/cap checks, and `/cancel` during approvals.
  Incoming media gets an explicit deferred-support reply; voice remains intact.
- Real Telegram transport completed progress/reactions/file/cancellation checks;
  the engine/model decisions in verification are scripted. See the
  [implementation ledger](../plans/vault-model-selection-telegram-implementation.md).

### Public login forms and managed browser routing — 2026-09-27

- Fixed the practice site's JavaScript login controls being refused because they
  have no native `<form>` and use **Submit**. The smallest unique credential group
  is bound with its actual controls; replacement and origin checks still apply.
- Empty/refused navigations no longer claim success or show a white Ready frame.
  Deferred rendering is observed before the first snapshot, and an HTTP refusal
  persists through subsequent snapshot/read/preview calls.
- Desktop discovery, model schemas and execution use the built-in browser's
  Playwright or approved local Chrome backend. External browser MCP calls from old
  conversations cannot bypass it or switch the live panel to an external session.

### Packaged Chrome and secure browser sign-in — 2026-09-27

- Chrome's pinned MCP bridge is now a shipped production dependency, unpacked
  from ASAR for the packaged Node runtime. Electron-owned MCP children receive
  `ELECTRON_RUN_AS_NODE=1`; no Node/npm/npx installation or package cache is needed.
- Desktop Playwright `browser login` integrates a native themed Secure store
  card/dialog with asynchronous OS-encrypted, exact-origin credentials, optional
  saving and metadata-only management in Plugins. Passwords bypass model/chat
  state, logs and receipts, and are cleared at fill time.
- One submission and positive signed-in evidence resume the original task;
  wrong passwords/2FA require explicit Retry or takeover. Escape/Stop cancels
  pending prompts. GET credential submission, ambiguous/cross-origin/signup forms,
  Chrome vault access and channel/CLI vault access are rejected.
- Main-frame IPC gating, contract 6, compact browser schemas/guidance, focused
  regressions and a real packaged Windows verifier cover the changed paths.
  See the root [Unreleased entry](../../CHANGELOG.md) and
  [verification record](../browser-screenshot-findings.md) for details and limits.

## 2.4.3 — 2026-09-26

Browser automation, a live browser stage that follows the app appearance,
reliable cancellation and reconnection, filesystem security fixes, and faster
command/file/Markdown processing. Detailed changes and verification follow.

### Added

- A packaged desktop verifier exercises the actual executable and shipped
  modules with disposable settings, a local HTTP/SSE model fixture, appearance
  switching, browser submission, screenshot pixels, takeover, Stop, command
  stdin/EOF and the Chromium installer dry run. It downloads no dependencies.
- `browser fill_form` fills up to ten fields from one snapshot after checking
  their refs. A disposable browser verification script covers both backends,
  screenshots, Stop, reconnect, automatic selection, and preview refresh rate
  without downloading packages or using a personal browser profile.
- **Browser tools.** Ankita can open real pages, read text and snapshots, act on
  fresh element references, manage tabs, take screenshots, and run batches of up
  to ten steps. Browser tools load on demand through `find_tools`.
- **Two browser plugins.** Playwright Browser uses a separate Chromium profile;
  Chrome local connects through the pinned Chrome DevTools MCP server. Desktop
  setup supports Private Chrome, Debug port, and My session, with Chromium
  download progress, a background option, and a debug-port connection test.
  Both plugins start disabled and save their settings across restarts.
- **Live browser beside chat.** The stage shows tabs, URL, status, and the current
  page, with Stop and Take control. Playwright takeover supports clicking,
  typing, pasting, and scrolling through the preview. Chrome takeover happens
  in Chrome. Hand back or Esc resumes Playwright control;
  `Ctrl/Cmd+Shift+B` toggles the stage.
- **Browser site controls.** Each plugin has allowed and blocked domain lists.
  Browser navigation accepts HTTP/HTTPS; private hosts are blocked by default.
  The isolated browser also checks page-initiated navigation and resource hosts.
  Browser actions require approval, and tool-card previews redact entered text.
- Browser setup and verification documentation, including the
  [browser guide](../guides/browser-use.md), implementation plan, real Chrome
  and Playwright benchmark script, desktop UI verification script, and
  [security audit record](../guides/audit-verification.md).

### Changed

- Windows command creation, shell discovery and process-tree work run in a
  worker so slow native startup can no longer block the owner's event loop.
  PowerShell selection is preserved. Stdin/output use native acknowledgements
  and backpressure; input waits for launch readiness before its write deadline.
- Browser plugin cards now match the existing integration cards in a compact
  **By Ankita team** section. Settings open in a details dialog. Plugin cards,
  dialogs, and the browser stage follow the app's global appearance colors.
- The browser stage uses the app's restrained tab, address-bar, and footer
  styling. Opening it collapses the left sidebar and closes workspace review
  to give chat and the page more room.
- Visible browser previews target ten updates per second with one capture in
  flight. Chrome returns JPEG data directly through MCP, avoiding temporary
  screenshot files. Live frames update independently of chat; tab metadata and
  chat thumbnails refresh every two seconds. Hidden/lost-connection states poll less
  frequently. Actual refresh rate depends on screenshot latency.
- File inspection reuses a resident worker instead of starting one for every
  call. A local 30-call README sample measured a 3.37 ms warm median and
  5.64 ms p95 after 174 ms initial startup.
- Terminal Markdown redraws coalesce on a fixed 20 ms deadline. Syntax keyword
  and type Sets are reused, skill catalogs load once per turn, tool schemas are
  shared within each model round, and tool-call signatures are computed once.
  History trimming measures message/group costs incrementally and caches image
  costs instead of repeatedly measuring the entire conversation.
- Added the Playwright runtime dependency, pinned the Chrome MCP launch
  version, and raised the desktop IPC contract to 5 for browser events and
  recovered-message replacement.

### Fixed

- Windows command cleanup keeps the launcher referenced until every pending
  Stop acknowledgement settles. Native pipe closure can arrive first on fast
  machines; it no longer leaves cleanup promises unresolved or cancels the
  remaining command tests on the clean release runner.
- Recoverable browser errors no longer mark a healthy session disconnected or
  dump fresh snapshots, page code and raw call logs into the live sidebar.
  Page/action notices preserve preview refresh and Take control; only connection
  and startup failures prompt setup. Completed actions keep the last frame.
- An unexpected Windows launcher worker exit cleans up its identity-checked
  native process tree before reporting failure; changed or missing process
  identities are refused instead of killing an unrelated PID.
- Chrome typing no longer sends an unsupported snapshot argument. Keyboard
  presses focus the supplied element ref without clicking it, and refuse to
  send a key when that control cannot receive focus.
- Browser `auto` mode uses enabled-backend selection. Tool guidance requires
  exact opaque refs rather than invented selectors or labels. Invalid refs
  return a fresh snapshot without replaying the mutation; successful open and
  action results provide the next refs, avoiding redundant snapshot calls.
- Playwright snapshots include visible controls beyond hidden input lists,
  accessible labels and states, custom roles, open shadow roots, and child
  frames. Label queries reach controls beyond snapshot limits. Password values
  remain hidden. Re-rendered refs follow only a unique control in the original
  frame; ambiguous replacements fail safely. Form filling supports selects and
  checkboxes as well as text fields.
- Chrome binds refs to their tab, excludes static text from actionable refs,
  and uses snapshots included in native action and form-fill responses to
  reduce MCP round trips.
- Successful browser interactions reset prior browser-read repetition counts,
  allowing multi-step workflows to continue. Snapshot-only loops and existing
  tool/round limits still stop. Schema budgeting reserves the actual system
  prompt and user attachments so tool discovery does not crowd out the task.
- Browser screenshot receipts attach validated PNG pixels to the next model
  request through the existing user-image format, retaining text tool messages
  and original input attachments. Workspace, file, byte, signature, and image
  count limits apply. MCP shutdown now observes asynchronous process teardown
  failures rather than leaving an unhandled rejection; the older Chrome
  verification script handles the adapter's structured screenshot receipt.
- Disabling Chrome prevents further selection and routes the next page open to
  enabled Playwright. New sessions prefer Playwright when both plugins are
  enabled; an existing session keeps its enabled backend. Old tab IDs and
  element references cannot silently execute against a replacement browser.
- Chrome connects when a browser request needs it and makes one recovery attempt
  after losing its connection. Approval is remembered for the exact server
  command. Read recovery gets fresh references; clicks and form submissions
  are never automatically replayed.
- Composer Stop cancels active and queued browser calls, including calls paused
  for takeover or setup approval. Closing the stage stops the run and disconnects
  Chrome. Browser/MCP deadlines and transport-close rejection prevent lost
  connections from waiting indefinitely; cancelled turns avoid spurious errors.
- Preview captures share pending work, recover their ready state after an error,
  and avoid retaining stale error frames. Browser sessions close during app
  shutdown.
- Interrupted model streams retry the current model step up to twice, preserve
  completed tool results, discard incomplete tool requests, and replace
  unfinished text when recovered wording differs. Stop cancels recovery.
- Desktop replies use consistent Markdown guidance across models. The message
  view repairs common plain-text headings, bullet glyphs, tabular rows, and
  whole-answer Markdown fences while preserving code blocks and existing markup.
- Deferred MCP server activation uses namespaced IDs, preventing collisions
  with built-in tool names. Browser discovery loads the first-party browser
  capability and retains registry guidance for other missing capabilities.
- File tools enforce the workspace boundary for absolute and relative paths,
  including Git inventories. They reject traversal escapes, interior
  symlinks/junctions, Windows device aliases, and alternate data streams while
  supporting a junction at the workspace root. Delete/move refuse both the
  workspace and current-directory roots.
- Approved edits, whole-file writes, and patches retain the displayed plan and
  recheck arguments, workspace identity, file identity, permissions, and bytes.
  Files changed during approval require a new approval. Atomic writes preserve
  permissions and use exclusive, unpredictable staging files with no direct-write
  fallback, closing the temporary-file symlink escape.
- Empty approval previews no longer bypass required confirmation.
  `mcp_manage` declares its approval policy by action. Auto-approval and
  confirmation results require explicit boolean `true`, including daemon gates;
  auto-approval remains an opt-in and still prepares file/process snapshots.
- Approval fallback and MCP diagnostics redact recognizable credentials plus
  secrets from environment variables, config files, server settings, and headers.
  Stderr buffering prevents split-chunk leaks; ordinary command descriptions
  remain readable.
- MCP stdout is capped at 16 MiB per message, including unterminated frames.
  Oversize closes the transport and rejects outstanding calls. Stderr lines are
  capped at 16 KiB and discarded through their newline when oversized.
  Split UTF-8 is decoded correctly.
- A filesystem worker watchdog terminates pathological regex searches or
  cancelled inspections, then serves queued healthy reads on a replacement.
  Inspection admission is bounded, and the worker shuts down explicitly with
  the CLI.
- Renderer finish flushes pending text, cancels redraw timers, removes resize
  listeners, and is idempotent. CLI stream failure and replacement paths finish
  the renderer. History trimming preserves input attachment objects, and
  optional recall warm-up failures cannot become unhandled rejections.
- Daemon SIGINT uses the daemon shutdown path, wakes tick sleep, settles queued
  permits, denies pending approvals, and drains active turns and alert
  composition. Queued work does not start after Stop.
- Failed alert enqueue retains one prepared message for delivery retries without
  repeating the LLM call. New watch changes coalesce from the earliest baseline
  to the latest reading; the pending backlog caps at 100 distinct changes and
  logs displacement of its oldest entry.
- Voice payload reads, writes, and cleanup use asynchronous I/O, including
  daemon audio staging. Stop/abort during a write cannot start delayed playback
  or transcription; playback removes its abort listener after exit.
- The full test command runs serially to avoid Windows process and MCP test
  timeouts caused by parallel execution.

### Verification

- The clean GitHub Windows release run passed **691 tests, 0 failed, 0 cancelled,
  23 skipped (714 total)**; optional Chromium/Python coverage ran locally instead.
  All four published release assets were downloaded and their SHA-256 digests
  checked. The installer's SHA-512, size and version match the update manifest.
- Release preflight on 2.4.3: **713 passed, 0 failed, 1 skipped (714 total)**,
  desktop production build and rendered sidebar round trip passed. The CLI's
  declared Node minimum now matches Playwright's Node 20 requirement; desktop
  development requires Node 22.12+ for the Electron build dependencies.
- Browser continuation: both real backends completed form, advanced controls,
  screenshot, Stop, reconnect and disabled-Chrome fallback checks. Real stale-ref
  recovery keeps the live pane usable without displaying snapshot/code text.
  The packaged executable passed appearance, eight HTTP/SSE model rounds,
  browser submission, screenshot pixels, takeover, Stop, command stdin/EOF,
  launcher crash cleanup and Chromium installer dry run. Chrome used cached MCP
  **1.8.0**; configured **1.10.1**, real downloads, personal attachment and live
  provider/site completion remain untested. Traces and coverage are recorded in
  [browser findings](../browser-screenshot-findings.md).
- Latest full gate: **713 passed, 0 failed, 1 skipped (714 total)**. The
  previous command startup/output failures now pass without weaker deadlines.
  Desktop TypeScript checking and production build passed;
  `git diff --check` and new browser-file whitespace checks passed.
- Earlier security implementation verification: **660 tests passed, zero failed, one
  expected Windows skip** for POSIX executable permissions. Desktop TypeScript
  checking and the Vite production build passed, as did `git diff --check`.
  Regression tests cover workspace escapes, approval races, stuck workers,
  credential redaction, stream recovery, browser cancellation, rendering,
  daemon shutdown, alert retries, and audio staging.
- The review's reported voice-default, provider-config, and web-fetch failures
  did not reproduce: their 62 tests passed without changing expected behavior.

### Known limits

- Website challenges and rejected navigation can still prevent a task. The
  supplied Air India booking URL failed with HTTP/2 in background Chromium and
  returned 404 in visible Chromium; the sidebar now reports a short page notice.
- Live Chrome verification used cached MCP 1.8.0 rather than configured 1.10.1.
  Personal-session permission dialogs, real Chromium downloads, non-Windows
  packaged builds and live model/vision-provider completion remain uncovered.
- Closed shadow roots, rare cross-origin frame changes and some Chrome widget
  operations remain limited. Failed mutations are never automatically replayed,
  and partial form fills require inspection before continuing.

## 2.4.2 — 2026-09-25

### Added

- **Skill controls in Plugins.** The Skills section lists installed workflows,
  shows their instructions, and lets users enable or disable them. The choice
  persists, updates existing desktop chats, and governs the agent's skill
  catalogue and tool access.

### Fixed

- Packaged desktop builds include the built-in skill files, so chats can load
  the same workflows shown in the interface.
- Checklists stay visible between turns and after a chat is reopened, with
  their status available to the agent as it finishes a task.

### Changed

- Source, tools, tests, scripts, and documentation now have focused directories.
  Imports, build paths, and release automation follow the new layout.

## 2.4.1 — 2026-09-24

### Fixed

- **Image previews through workspace aliases.** A Windows junction could give
  the same workspace a different path spelling and cause a valid generated
  image to be rejected. The preview accepts paths under either spelling and
  still checks the resolved file against the canonical workspace directory.
- **Windows release gate.** Git test fixtures now fix their own line-ending
  setting instead of inheriting the runner's global configuration. Tests are a
  required release step, so failures stop publication.

## 2.4.0 — 2026-09-24

### Added

- **Kilo starter model.** On a genuinely fresh desktop install, Ankita saves
  Kilo as the provider and selects `poolside/laguna-s-2.1:free`. The model
  advertises tool support and needs no key; free access remains subject to
  provider availability and rate limits. Existing teammate data, saved desktop
  settings, and explicit provider settings prevent automatic migration.
- **Conversation plan at the input.** Successful `write_todos` calls drive a
  compact, expandable checklist above the composer. The row shows completion
  count and active step, updates live, and reconstructs from saved thread
  messages. New user turns clear stale plans until the agent updates them.

### Changed

- **Bounded file inspection.** Search and glob use Git's tracked/unignored file
  inventory where available, skip generated folders, and report incomplete
  results when a file, depth, byte, or time budget is reached. Blocking file
  inspection runs in a cancellable worker so the app can still respond.

### Fixed

- **The agent loop stops itself now.** A request could run up to 100 consecutive
  tool rounds, and the only thing that ended a turn was the model deciding it was
  finished; running out of rounds ended the request with the literal string
  `(stopped: too many tool calls in a row)` written into the conversation. The
  loop is bounded by `MAX_TOOL_STEPS` (default 24, clamped 1-200, so it stays
  configurable but never unlimited), and it stops early when one call repeats with
  identical arguments in three separate rounds - the shape of a model asking a
  question it already has the answer to. Repetition is counted once per round so
  three identical parallel reads remain a batch. When either limit trips, the
  model gets one last tools-free turn to say what it completed, what is uncertain
  and what the next step is; if even that call fails the turn still returns honest
  text naming what it ran and why it stopped. The system prompt carries the
  matching policy - answer once you have enough instead of researching on, and do
  not wander into state the request never asked about.
- **Project state is safer.** Duplicate open tasks are rejected, todo history is
  retained until the limit is reached, and malformed or conflicting stored
  project data is not overwritten by later writes. Stored notes are labelled
  as records rather than proof of current production state.
- **Windows command cancellation.** If the command root has already exited,
  descendant cleanup still runs; if `taskkill /T` fails, the fallback runs.

## 2.3.0 — 2026-09-24

### Added

- **Attachments in the composer.** The `+` button in the message box now
  attaches files and images (click, drag-and-drop, or paste). Uploaded images
  are normalized/compressed, budgeted by estimated vision tokens rather than
  raw upload bytes, and preserved through history trimming. Text and code files
  are folded into the prompt as labelled blocks the model can read. Up to 8
  files per message, 10 MB per image and 200 KB per text file, with unsupported
  or binary files refused before they reach the model. Attachments appear as
  chips on the sent message.
- **Documents and scans are read properly (Phase 1).** PDF/DOCX/XLSX/PPTX
  attach as extracted text. PDF parsing was rebuilt: every stream is inflated
  before operator scanning, hex-encoded strings and UTF-16 (BE/LE) literals are
  decoded, stream bodies are scanned with a byte-preserving reader so high bytes
  survive, and binary image/object streams are excluded. Raw PDF source is no
  longer used as fallback text. A prose-quality check and coverage heuristic
  detect scans and decoded noise (almost no genuine text layer). A scanned or
  otherwise unreadable PDF is rasterized in the main process via a hidden
  `BrowserWindow` (`renderPdfPages`) and its pages are sent as compressed JPEG
  `image_url` parts for a vision model; on-demand OCR (Tesseract, lazy CDN load)
  is the fallback when pages cannot be read. Page images are charged by estimated
  vision tokens (reserved before the text is clipped); when pages do not all fit,
  the leading pages are retained with an explicit omission note. `trimMessages`
  drops `image_url` parts before throwing a context-budget error.
- **Image tools.** Three separate capabilities, loadable on demand:
  `image_generate` (OpenAI-compatible `/images/generations`, saved to
  `generated-images/`), `unsplash_search`, and `pixabay_search`, plus
  `image_download` to save a chosen stock result into `downloaded-images/`.
  Generated and downloaded images preview inline in the desktop app and appear
  in Work review → Artifacts. Configure under **Settings → Images** or with
  `IMAGE_API_BASE`, `IMAGE_API_KEY`, `IMAGE_MODEL`, `UNSPLASH_ACCESS_KEY`,
  `PIXABAY_API_KEY`. Both output folders are git-ignored.
- **First-launch profile setup.** Once the provider connects, the app asks for
  a display name and timezone in a skippable dialog (name pre-filled from
  config, timezone auto-detected with IANA suggestions). The name reaches the
  system prompt, the timezone reaches journaling/quiet hours/routines, and both
  are editable afterwards in a new **Settings → Profile** tab. App-saved values
  override env config and propagate to live agents without reconnecting;
  invalid timezones are rejected with an actionable error.

### Fixed

- **MCP servers configured with a full shim path now start.** A command like
  `C:\Program Files\nodejs\npx.cmd` is matched by basename, so `resolveLaunch`
  and the candidate builder rewrite it to `node` + npm's `npx-cli.js` (or the
  cached package entry) with no shell and no console window, instead of
  reporting an unspawnable batch shim. The same basename matching covers full
  paths to `uv`/`uvx`, which keep their configured command when uncached.
- **Uploaded images are no longer silently removed before the model sees them.**
  History and attachment budgets previously measured image data URLs as raw
  text, so a normal screenshot could be dropped while leaving only “whats
  this.” Images are now normalized, measured as estimated vision tokens, and
  retained when those tokens fit.
- **Console windows no longer flash on launch.** Windows MCP servers were
  started through `npx` (which uses npm's spawner → `cmd.exe`) or `uvx` (a
  console app), each opening a visible console beside the app. `npx` packages
  now run their cached entry script with `node`, and `uvx` packages run their
  module through the same venv's windowless `pythonw.exe` — no shell, no
  console, stdio intact. Verified end-to-end against the real servers.
- **Chat no longer scrolls you back up.** Follow-the-bottom was decided from
  React state that a streaming delta could read stale, and the scroll container
  had global `scroll-behavior: smooth`, so every token started a new animated
  scroll. The decision is now a ref read synchronously in a layout effect, and
  only the explicit "Latest" jump animates — reading history is never
  interrupted.
- **Inline image previews render, including paths with spaces.** An assistant's
  absolute Windows path was being parsed as a web URL. Markdown images now
  resolve workspace paths safely through the confined `readGeneratedImage` IPC,
  encode spaces, and accept both absolute and relative paths.
- **Settings saves survive a version-mismatched build.** An unknown settings key
  is ignored instead of failing the whole save.

## 2.2.0 — 2026-09-23

### Added

- **Telegram channels** (Settings → Channels): route chat messages to a
  teammate, share its thread and history, answer tool approvals in chat, and
  transcribe or speak replies.
- **Version mismatch guard.** The window and background service exchange a build
  version and IPC contract on startup; a mismatch shows an "out of sync" notice
  with one-click restart instead of failing piecemeal.
- **Update resilience.** A stalled download reports its last percentage with an
  Open release link.

## 2.1.1 — 2026-09-23

### Fixed

- The Model settings tab no longer sends `contextWindow` / `maxTokens` to a
  backend that does not advertise them.

## 2.1.0 — 2026-09-23

### Added

- **Context-aware tool budget** — loaded tool groups ship whole while they fit
  and are dropped whole when they do not.
- **Context window / max output tokens** settings for endpoints that report no
  window.

## 2.0.0 — 2026-09-23

### Added

- Desktop app: teammates, projects, work review, plugins, and self-updating
  Windows builds.
- Composio plugins and developer tooling.
