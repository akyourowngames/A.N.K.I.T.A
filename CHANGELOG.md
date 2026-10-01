# Changelog

All notable changes to Ankita are documented here. This project adheres to
[Semantic Versioning](https://semver.org/), and releases are cut from the
version in `package.json` (see [docs/guides/releasing.md](docs/guides/releasing.md)). A fuller,
continuously updated narrative lives in [docs/reference/changelog.md](docs/reference/changelog.md).

## [Unreleased]

### Added

- **Keyless Composio sign-in — no API key, nothing to host.** Connecting an app
  now runs a browser OAuth 2.1 + PKCE flow: discovery, dynamic client
  registration as a public client (no secret issued), a single-use
  `http://127.0.0.1:<port>/callback` loopback redirect, and a PKCE S256 code
  exchange. There is no public callback URL, domain, certificate or broker to
  stand up. The access token is written to the OS vault; the grant file holds
  only a `grantId`, endpoint, apps and timestamps — never the token, verifier or
  refresh token. Revoking deletes both in one step. `COMPOSIO_API_KEY` and
  `COMPOSIO_BROKER_URL` keep working until the deprecation window closes.
- **MCP approval tiers replace the trusted-server bypass.** Tool calls now
  resolve a four-level gate — auto-allow, ask once, always ask, deny — instead of
  the old read-only-hint rule, and a connection's `trusted` flag no longer skips
  it. Composio meta-tools are classified by the worst action they enclose, so
  `COMPOSIO_MULTI_EXECUTE_TOOL` wrapping `GMAIL_SEND_EMAIL` always asks while
  read-only catalog discovery stays frictionless. Resolution order is blocklist →
  explicit tool rule → per-app rule → locked app defaults → heuristic (a
  heuristic can never deny). Overrides, a blocklist and allowed/asked/denied
  counters persist to `mcp-tiers.json`, and `gmail` ships locked to *always ask*.
- **`composio` tier controls.** New `tiers`, `allow`, `always` and `deny` actions
  inspect and change the gate. They are refusal-guarded: a call that loosens
  protection can never run under auto-approve, so an unattended scheduled job
  cannot quietly grant itself a lower tier for every later session.
- **Real integration icons in Plugins.** Every Composio app row renders the
  toolkit's real brand mark from its logo URL, with the curated mark or a
  monogram as the offline/unknown fallback.
- **Deprecation notice on `composio status`** naming the exact variable to
  replace, derived from the version in `package.json` rather than hardcoded, and
  worded so it never promises a switch the build does not offer yet.

### Changed

- Plugins **Saved sign-ins** is now a first-class browser-vault section instead of
  a stray disclosure: a section head with a live count and a framed card that
  states it is what the built-in browser and Chromium fill from. Each row shows
  the site, username, when it was last saved and a Remove action, with loading,
  empty and error states.
- Scheduled-task surfaces are grouped by state (needs attention, running,
  upcoming, paused) with a summary line, count badge and stat tiles. Run receipts
  read as plain status labels with relative times, and the scheduler no longer
  uses the success color — state is carried by theme tokens and motion that
  honours `prefers-reduced-motion`.

### Fixed

- **A scheduled task and its run result could appear in another teammate's
  conversation.** The jobs panel and routine sheet are now scoped to the selected
  thread, matching the chat pane.
- The OAuth flow sends the RFC 8707 `resource` indicator on both the authorization
  and token requests, which the MCP authorization spec requires and servers use to
  bind the token audience. The endpoint allowlist also accepts the sibling
  `login.composio.dev` host the live Composio metadata points at.

## [2.4.4] - 2026-09-30

### Added

- Scheduled desktop results now come from the owning teammate's model as normal
  chat replies. The scheduled worker's text and browser screenshot remain
  expandable evidence beneath the reply. The writing pass has no tools, waits
  for an active chat turn and retries delivery without rerunning the job.
- Desktop scheduled browser jobs: timezone-aware cron, independent serial workers
  and Chromium profiles, editable settings, a compact jobs pill, live viewing
  and proof receipts in the owning teammate's chat. The model's `schedule` tool
  creates active tasks from chat, updates the same task and returns compact
  widgets with the next run; a thin upcoming list replaces the creation form.
- Idle heartbeat tasks use owner/project context and proactive briefing
  instructions, skip busy teammates and suppress uneventful replies. Chat-created
  tasks browse autonomously in isolated Chromium; existing scoped tasks retain
  their approvals. Creation retries are idempotent and lifecycle guards resolve
  model-supplied task names before checking active workers. Names are scoped to
  the owning teammate; ambiguous matches are rejected. A shared typed update
  schema and flat-argument normalization prevent silent empty updates, and
  conflicting values return an actionable error.
- Scheduled workers advertise isolated Chromium only and separate execution
  instructions from job-creation guidance. Saved username/password steps use
  private credential refs; an omitted login URL binds the actual selected tab.
  Generic unattended password fill/type is rejected, including shown passwords.
- Browser form batches preflight every target before writing. Invalid buttons,
  readonly controls and stale refs return fresh refs without partial writes;
  failures after filling starts remain incomplete and are never replayed.
  Chrome retains custom toggle support and reports dialog-interrupted batches
  as incomplete. Concurrent Chromium cleanup shares one owned-context close.
- Printed pretend tool calls trigger one bounded model correction in a job;
  repeated malformed requests and exhausted tool loops produce incomplete
  receipts instead of successful jobs. Printed JSON is never executed directly.
- Secret scrubbing at session, journal, memory, routine, job-log, tool-log,
  diagnostic and export boundaries; deterministic shaped/context/encoded
  detection with a 50-sample regression corpus. Explicit save intent encrypts
  named secrets with the OS vault and persists references. Detected desktop
  pastes remain protected in later unlabeled echoes; short prefixed password
  labels are supported. Privacy settings include an explicit disable warning.
- Idempotent first-launch migration covers transcript/export folders, job state,
  teammate previews and legacy daemon logs while excluding provider/vault
  configuration. Text diagnostics rotate within a bounded disk budget.
- Ctrl/Cmd+K command palette searches app commands, enabled skills/manifest
  actions and scheduled jobs, with keyboard navigation, focus restoration,
  live registry refresh and protection against launching stale search results.
- Real Chromium login verification covers username-first flow, password iframe,
  CSRF, control replacement, expired sessions and MFA handoff in the actual
  development and packaged Windows app. Live model scheduling is checked
  separately from scripted provider/browser verification.
- Routine-scoped inline approvals, optional bounded execution and approval deadlines,
  opt-in daily run/token/minute budgets, saved-only sign-in, late/missed-run reporting,
  delivery-only retry and retained redacted run audits. Background jobs use
  isolated Chromium only; Chrome remains a foreground backend. No mobile wiring.
- Desktop tray hosting with Show, Pause all and Quit, a first-close notice,
  opt-in startup at sign-in, and a shared scheduler ownership lock that prevents
  desktop/CLI double firing and supports cooperative CLI takeover.
- Actual development and packaged Windows job verifiers exercise browser
  submissions, inline approvals, concurrent chat, live viewing, tray completion,
  reload/idempotent delivery and recovery shutdown. A separate verifier can run
  the same browser task through the currently configured provider.
- Secure browser sign-in for desktop Playwright: a compact **Secure store** chat
  card opens the native **Secure credentials store** dialog. Website is locked;
  username/password fields, show/hide, optional saving, Escape/Cancel and a focus
  trap follow the existing appearance. Saved sign-ins can be removed in Plugins.
- A main-process vault uses asynchronous Electron OS encryption, exact website
  origins and atomic owner-only files. Only account metadata leaves the vault;
  plaintext is cleared after filling. Unavailable encryption and Linux
  `basic_text` refuse persistence. CLI, channels and Chrome cannot use the vault.
- `browser login` can request the secure dialog before any form appears. The
  model selects observed refs through `credential_fields` (private username/
  password slots) and optional `submit_ref`, including username-first steps and
  input-based submit controls. Each call returns a fresh snapshot to the model
  to finish sign-in and continue the original task. One-time credentials are
  scoped to thread/origin/tab/page and cleared on password use, Stop, turn end
  or expiry. Password values stay hidden even when a site toggles input type;
  exact-origin, bound-node and native GET submission guards remain enforced.
- Telegram desktop and CLI channels show a typing heartbeat and throttled tool
  progress, acknowledge messages with supported received/completed/failed
  reactions, and send up to five current-turn image artifacts after the final
  text reply. Reads enforce workspace/folder/type/15 MiB limits; photo failures
  fall back to documents. `/cancel` bypasses approval and task queues. Incoming
  photos/documents/videos receive a not-supported nudge; voice notes still work.
- A disposable packaged verifier reproduces the old Chrome launch failure and
  checks bundled CDP, real OS encryption, cold/warm login, theme/focus/eye controls,
  cancellation, retries, takeover and password-free model/events/persistence.

### Fixed

- Resolved the README merge blocks while retaining desktop setup, security and
  CLI sign-in guidance. Skill tests now discover the installed catalog instead
  of assuming two skills. Windows launcher crash cleanup checks only its root
  PID before applying the creation-identity guard, avoiding a full process-table
  scan. Command tests now follow a cold shell past the initial yield and wait
  for final output and exit status before asserting that a later background job
  is the only active one.
- Scheduled browser tasks no longer stop on accumulated input-token totals, the
  old three-minute deadline, fixed tool counts or the foreground search ceiling. Regular desktop jobs run until
  completion; usage remains recorded, Stop and no-progress detection remain
  active, and explicit limits are optional. Heartbeats keep bounded defaults.
- Watching another job tab changes only the preview, preserving the worker's
  selected page and snapshot refs. App navigation and foreground browsing remain
  independent. Saved completion URLs and screenshots follow the worker's page.
  Task details/editor now show the full execution prompt; model
  guidance requests clear objectives, steps, evidence and output. Fresh workers
  receive the last successful result for comparisons across failed runs/reloads.
- A malformed model-selected credential field now returns fresh controls and
  correction guidance before vault access or filling. Scheduled workers can
  correct the native call and continue; origin checks and uncertain actions
  remain enforced. Packaged tests exercise the rejection and correction twice.
- Job navigation intercepts redirects before network dispatch, including POST,
  popups and embedded frames; Fetch/XHR requests also pass the runtime permission
  gate. Approval waits no longer inherit foreground browser command timeouts.
- Foreground chat cancellation preserves job approvals and shared Chrome
  connections. Budget checks stop a worker before its next browser side effect;
  yearly cron searches no longer block the main process for seconds.
- Pause/Resume keeps the routine form's Enabled checkbox synchronized, so a
  later Save cannot silently reverse the action. Job control errors stay in the
  sheet, and watching a job no longer adds a duplicate foreground browser card.
- Stale truncated ownership locks recover, heartbeats replace atomically,
  copied proof receipts obey the per-routine retention cap, and recovery relaunch
  drains the scheduler before quitting and releases its ownership.
- Secure login no longer depends on detecting a unique form or a button-name
  whitelist. Cirro's honeypot and input-based **Sign In** no longer block the
  secure dialog. Model-selected controls are validated before filling, and
  selection failures return to the model without an automatic credential loop.
- Playwright waits for a blank SPA to render before returning its first snapshot.
  HTTP refusals and pages that stay empty are load failures, with **Needs attention**
  and a concise message instead of a white **Ready** preview. A later real render
  can recover; snapshots cannot conceal a refused request.
- Desktop tool discovery, prompts and schemas exclude external Playwright/Chrome
  MCP browser tools. Old browser MCP calls are blocked at execution and activate
  the built-in browser, preserving enabled backend choices, refs, secure login and
  live preview. Blocked external calls cannot replace the live stage state.
- Packaged Chrome connections launch the pinned, shipped `chrome-devtools-mcp`
  bridge from `app.asar.unpacked` with the packaged executable in Node mode.
  No system Node, npm/npx, runtime download or pre-existing npm cache is needed.
  This fixes the second GUI instance exiting with code 0 before MCP initialize.
- The bridge version comes from the production dependency pin; all connection
  modes use the same runtime. Explicit command approval and on-demand reconnect
  remain in place. Runtime metadata now matches the bridge's Node requirements.
- Desktop IPC is restricted to the main application frame; contract is bumped
  to 7. Compact browser guidance preserves room for deferred tools/screenshots.

Verification and platform limits: [browser findings](docs/browser-screenshot-findings.md)
and the [credential/Telegram ledger](docs/plans/vault-model-selection-telegram-implementation.md).
Desktop jobs: [implementation and verification](docs/plans/desktop-background-jobs-implementation.md).

## [2.4.3] - 2026-09-26

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
  [browser guide](docs/guides/browser-use.md), implementation plan, real Chrome
  and Playwright benchmark script, desktop UI verification script, and
  [security audit record](docs/guides/audit-verification.md).

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
  [browser findings](docs/browser-screenshot-findings.md).
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

## [2.4.2] - 2026-09-25

### Added

- **Skills in Plugins.** Browse installed workflows, read their instructions, and
  enable or disable each skill. Choices persist across desktop restarts and update
  active chats before their next reply.

### Fixed

- Desktop chats now load packaged skills. Disabled skills are absent from the
  model's skill catalogue and cannot be run through the skill tool.
- Session checklists remain visible between turns and after reopening a chat;
  the agent is reminded to update their statuses before finishing work.

### Changed

- Reorganized source, tools, tests, scripts, and documentation into focused
  directories, with imports and release packaging updated for the new paths.

## [2.4.1] - 2026-09-24

### Fixed

- Image previews work when a Windows workspace is reached through a junction,
  while canonical path checks still keep previews inside the workspace.
- The Windows release checks now use a deterministic Git line-ending fixture,
  and a failing test suite stops publication.

## [2.4.0] - 2026-09-24

### Added

- **A free model for new desktop installs.** First-time users start with Kilo's
  keyless `poolside/laguna-s-2.1:free`. Existing desktop settings and explicit
  provider configuration keep their chosen provider. Kilo's free endpoint is
  subject to availability and rate limits.
- **Live plan near the composer.** The agent's `write_todos` checklist appears
  above the message box with a progress count and current step. Expand it to see
  each status; updates arrive with the conversation and restore when reopened.

### Changed

- File search and glob respect Git ignore rules and bound the amount of work in
  large folders. Inspection runs off the main agent loop, and partial results
  say when a limit was reached.

### Fixed

- **A tool loop can no longer run away with a request.** The loop's only exit was
  the model choosing to stop, so a model that kept declaring calls was allowed 100
  consecutive tool rounds, and spending that budget wrote the string
  `(stopped: too many tool calls in a row)` into the transcript as if the assistant
  had said it. The loop is now bounded by `MAX_TOOL_STEPS` (default 24, clamped
  1-200) and stops early when the same call repeats with identical arguments in
  three separate rounds - counted once per round, so identical parallel calls still
  batch. Either way the model gets one final tools-free turn to report what it
  completed, what is uncertain and what is left, so a stopped request ends with an
  answer instead of a canned failure. The system prompt states the matching policy:
  stop once the request is answered rather than continuing to research.
- Project tasks no longer silently discard older items or accept duplicate open
  tasks. Malformed or conflicting project state is left intact instead of being
  overwritten.
- Cancelling a Windows command stops its child processes even when the root
  process has already exited.

## [2.3.0] - 2026-09-24

### Added

- **Attachments in the composer.** The `+` button now attaches images and files
  (click, drag-and-drop, or paste). Images go to vision-capable models as image
  parts; text and code files are folded into the prompt as labelled blocks. Up
  to 8 files per message, 10 MB per image, 200 KB per text file.
- **Documents and scans actually reach the model.** PDFs, Word, Excel, and
  PowerPoint files attach as extracted text; PDF parsing now decodes
  hex-encoded and UTF-16 strings, so documents that previously came back empty
  yield their text. A scanned PDF (no text layer) is rendered to page images in
  the main process and sent to a vision model, with on-demand OCR as the
  fallback when reading fails. Page images count against the same context
  budget as text, and history trimming drops image parts before a turn can
  overrun the window.
- **Image tools.** `image_generate` creates original images, `unsplash_search`
  and `pixabay_search` find stock photos, and `image_download` saves a chosen
  result. Generated and downloaded images preview inline and appear in Work
  review → Artifacts. Configure in **Settings → Images**.
- **First-launch profile setup.** After the provider connects, new users are
  asked for a display name and timezone (skippable). The name feeds the
  assistant's instructions and the timezone drives journaling, reminders and
  quiet hours; both live on in a new **Settings → Profile** tab and apply to
  live chats without reconnecting.

### Fixed

- **MCP servers configured with a full shim path now start.** A server whose
  command is an absolute path such as `C:\Program Files\nodejs\npx.cmd`
  (the Playwright reload failure) is matched by basename and launched via
  `node` + the underlying script, instead of being rejected as an
  unspawnable batch shim. Uncached `uvx` tools likewise keep their configured
  command instead of being rewritten to bare `uvx`.
- **Uploaded images are actually sent to the model.** Image attachments are
  normalized before sending, budgeted by estimated vision tokens instead of
  raw upload bytes, and preserved through history trimming. Scanned-PDF page
  images use compressed JPEGs; when pages do not all fit, the leading pages
  are kept with an explicit omission note instead of rejecting the document.
- **PDF attachments no longer forward binary gibberish.** Compressed and
  binary streams are excluded from text-operator scanning, raw PDF source is
  no longer used as fallback text, and long non-prose output is treated as a
  missing text layer. Unreadable PDFs use rendered page images or OCR instead.
- MCP servers no longer flash console windows on launch: `npx` packages run via
  their cached entry script and `uvx` packages via the venv's windowless
  `pythonw.exe`.
- The chat no longer scrolls back up while you read history during a stream.
- Inline image previews render, including absolute Windows paths with spaces.
- Multimodal history no longer throws "exceeds the model context budget" when
  an attachment's image parts push a turn past the window: images are counted
  at attach time and dropped (after text is clipped) when trimming.

## [2.2.0] - 2026-09-23

### Added

- **Channels (Telegram bridge).** Settings → Channels connects the app to a
  chat service so you can reach your agent from anywhere, starting with
  Telegram. Paste a bot token, pick the teammate that answers, and allow-list
  chat ids (an unknown chat is told its own id so you can add it). While
  enabled, the bridge runs with the app and routes each message to that
  teammate, sharing the same thread and history as the desktop. Tool approvals
  are asked and answered in the chat, voice notes are transcribed when a Groq
  key is set, and replies can be spoken back. Channel settings live in
  `~/.copilot-chat-cli/desktop-channels.json`.
- **Version mismatch guard.** The window and the background service now
  exchange a build version and an IPC contract on startup. If they differ - a
  stale or half-applied build - the app shows an "Ankita is out of sync" notice
  with a one-click **Restart** (or **Restart & update**) instead of failing
  piecemeal with errors like "Unknown desktop setting".
- **Update resilience.** Downloads that stop making progress are reported as
  paused with the last percentage and an **Open release** link, and a check no
  longer restarts an in-flight download.

### Fixed

- Desktop settings saves no longer hard-fail on a key this build does not know;
  unknown keys are ignored, so a newer window can still save against an older
  backend.

### Changed

- Releases are published deterministically from `package.json` on the default
  branch: the tag is created, then the installer, blockmap, portable exe and
  `latest.yml` are uploaded together (auto-update metadata always present).

## [2.1.1] - 2026-09-23

### Fixed

- The Model settings tab no longer sends `contextWindow` / `maxTokens` to a
  backend that does not advertise them, which previously blocked every save
  with "Unknown desktop setting: contextWindow" on a version-mismatched build.

## [2.1.0] - 2026-09-23

### Added

- **Context-aware tool budget.** Loaded tool groups (a `find_tools` category or
  an MCP server) ship whole while they fit the context window and are dropped
  whole when they do not, so a small window or a long memory recall never
  hard-fails a turn. The output reserve scales with the window when `MAX_TOKENS`
  is unset.
- **Context window / max output tokens** settings, so OpenAI-compatible
  endpoints that report no window can be declared.

## [2.0.0] - 2026-09-23

### Added

- Desktop app: teammates, projects, work review, plugins, and self-updating
  Windows builds.
- Composio plugins and developer tooling.
