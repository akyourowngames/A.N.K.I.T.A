# Changelog

Every notable change to Ankita is recorded here, newest first. The dated
releases mirror the entries in the root [`CHANGELOG.md`](../CHANGELOG.md) that
the release workflow publishes to GitHub; "Unreleased" collects work that is in
the tree but not yet packaged.

## Unreleased

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
