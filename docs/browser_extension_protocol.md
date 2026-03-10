# Browser Extension Protocol

This document defines the Phase 1 localhost bridge contract for ANKITA browser automation.

## Overview

- Python side: `browser_bridge.py`
- Tool entrypoint: `browser_automation`
- Transport: local HTTP on `127.0.0.1`
- Default port: `8766`
- Extension role: connect, poll for commands, execute DOM actions, return structured results
- Extension implementation: `browser_extension/`

## Endpoints

### `GET /health`

Returns bridge status.

Example response:

```json
{
  "ok": true,
  "service": "browser_bridge",
  "connected_extensions": 1,
  "extensions": [],
  "pending_commands": 0
}
```

### `POST /extension/register`

Registers or refreshes an extension client.

Example request:

```json
{
  "name": "ankita-browser-extension",
  "version": "0.1.0",
  "capabilities": ["tabs", "dom", "snapshot", "screenshot"],
  "active_tab": {
    "tab_id": 123,
    "url": "https://example.com"
  }
}
```

Example response:

```json
{
  "ok": true,
  "client_id": "ext-1234abcd",
  "bridge": {
    "service": "browser_bridge",
    "connected_extensions": 1,
    "extensions": [],
    "pending_commands": 0
  }
}
```

### `POST /extension/heartbeat`

Keeps the extension marked as live and can update active-tab metadata.

### `GET /extension/next?client_id=<id>&timeout_sec=20`

Long-polls for the next pending command.

Example response with work:

```json
{
  "ok": true,
  "command": {
    "command_id": "cmd-1234567890",
    "action": "run_steps",
    "session_id": "browser-abcd1234",
    "steps": [
      {"type": "goto", "url": "https://example.com"},
      {"type": "extract", "target": {"tag_name": "body"}, "mode": "text"}
    ]
  }
}
```

Example response when idle:

```json
{
  "ok": true,
  "command": null
}
```

### `POST /extension/result`

Returns the command result to ANKITA.

If an artifact contains `data_url`, the bridge stores it under `.cache/browser_bridge/<command_id>/`
and replaces the inline data with a filesystem path before returning it to ANKITA.

Example request:

```json
{
  "client_id": "ext-1234abcd",
  "command_id": "cmd-1234567890",
  "ok": true,
  "session_id": "browser-abcd1234",
  "url": "https://example.com",
  "title": "Example Domain",
  "steps": [
    {"index": 0, "type": "goto", "ok": true},
    {"index": 1, "type": "extract", "ok": true, "output": "Example Domain"}
  ],
  "artifacts": []
}
```

### `POST /command`

Used by ANKITA or local tooling to enqueue a command for the extension.

Example request:

```json
{
  "command": {
    "action": "snapshot",
    "session_id": "browser-abcd1234"
  },
  "wait_for_result": true,
  "timeout_sec": 30
}
```

## Recommended Command Shapes

### `start_session`

Attach to an active tab or open a new one.

```json
{
  "action": "start_session",
  "session_id": "browser-abcd1234",
  "url": "https://example.com"
}
```

### `run_steps`

Execute a batch on the current tab.

```json
{
  "action": "run_steps",
  "session_id": "browser-abcd1234",
  "steps": [
    {"type": "goto", "url": "https://example.com"},
    {"type": "wait_for", "target": {"text": "Example Domain"}},
    {"type": "extract", "target": {"tag_name": "body"}, "mode": "text"}
  ]
}
```

### `snapshot`

Return current tab metadata plus visible headings, buttons, links, and fields.

### `close_session`

Detach or close the controlled session.

## Phase 2 Guidance

- Keep the extension executor deterministic.
- Let ANKITA continue planning through `browser_automation`.
- Prefer DOM actions over screen coordinates.
- Use simulation mode for checkout flows unless explicitly allowed to perform real finalization.
- Current extension implementation supports:
  - `start_session`
  - `run_steps`
  - `snapshot`
  - `close_session`
  - `list_sessions`
- Current `run_steps` implementation supports:
  - `goto`
  - `reload`
  - `back`
  - `forward`
  - `new_tab`
  - `switch_tab`
  - `close_tab`
  - `screenshot`
  - `snapshot`
  - DOM-side `click`, `fill`, `press`, `select`, `hover`, `wait_for`, `extract`, `scroll`, `check`, `uncheck`
