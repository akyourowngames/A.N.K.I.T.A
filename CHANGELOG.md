# Changelog

All notable changes to Ankita are documented here. This project adheres to
[Semantic Versioning](https://semver.org/), and releases are cut from the
version in `package.json` (see [docs/guides/releasing.md](docs/guides/releasing.md)). A fuller,
continuously updated narrative lives in [docs/reference/changelog.md](docs/reference/changelog.md).

## [Unreleased]

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
