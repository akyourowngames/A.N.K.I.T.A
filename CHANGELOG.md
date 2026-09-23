# Changelog

All notable changes to Ankita are documented here. This project adheres to
[Semantic Versioning](https://semver.org/), and releases are cut from the
version in `package.json` (see [docs/releasing.md](docs/releasing.md)).

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
