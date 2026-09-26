# Changelog

Every notable change to Ankita is recorded here, newest first. The dated
releases mirror the entries in the root [`CHANGELOG.md`](../../CHANGELOG.md) that
the release workflow publishes to GitHub; "Unreleased" collects work that is in
the tree but not yet packaged.

## Unreleased

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

- Release preflight on 2.4.3: **712 passed, 0 failed, 1 skipped (713 total)**,
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
- Latest full gate: **712 passed, 0 failed, 1 skipped (713 total)**. The
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
