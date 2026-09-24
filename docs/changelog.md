# Changelog

Every notable change to Ankita is recorded here, newest first. The dated
releases mirror the entries in the root [`CHANGELOG.md`](../CHANGELOG.md) that
the release workflow publishes to GitHub; "Unreleased" collects work that is in
the tree but not yet packaged.

## Unreleased

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
