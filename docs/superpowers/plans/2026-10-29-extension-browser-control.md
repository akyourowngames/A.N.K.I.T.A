# Persistent Extension Browser Control Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task, with a fresh whole-change review at completion.

**Goal:** Pair Ankita's browser companion once, automatically reconnect across process restarts, and use existing-profile browser actions without a repeated remote-debugging connection prompt.

**Architecture:** Extend the existing authenticated companion loopback service with a separate browser-control grant and a bounded command broker. A local hidden MCP gateway feeds the existing browser facade; the extension executes packaged DOM operations and uses Chrome's debugger only for explicit deeper operations. Persist pairing credentials and the remembered OS-assigned port, while making transport sessions and in-flight commands process-local.

**Tech Stack:** Existing Node/Electron, MCP SDK, React and Manifest V3 extension APIs. No new dependencies.

**Spec:** `docs/findings/2026-10-29-extension-browser-control.md`.

## Global constraints and rulings

- One pairing survives desktop/browser/extension-worker restarts in either startup order. Unpair revokes it; disconnect pauses it.
- Preserve capture-only grants, browser site rules, action approvals, protected ChatGPT tabs and job ownership. No replay of uncertain writes.
- Named constants own limits and timing; no machine-specific paths or new provider settings.
- Ruling: reuse the helper's existing authenticated loopback discovery instead of adding a native messaging installer in this change. The remembered local port plus extension startup/alarm reconnect avoids another installation component. Cost: reconnection after a suspended worker can wait for the browser's next alarm; measure and disclose that limit. Native messaging remains a future discovery option, not a shipped claim.
- Keep checks focused as the user requested; do not run the full suite.

## Review focus

- A capture-only pairing must not become browser control permission.
- Restarted workers or desktop processes must not execute old writes again.
- Wrong origins, helpers, sessions and stale command results must be rejected.
- Independent jobs must retain their own tabs, documents and element references.
- Reconnection must preserve an explicit disconnect/revocation and never block startup.

## Task 1: Durable pairing and command broker

Files: helper control protocol, `desktop/electron/browser-control.mjs`, `companion-capture.mjs`, focused broker/capture tests.

- [ ] Write and run failing tests for control opt-in, restart using the same token/port, origin/session isolation and lost-response non-replay.
- [ ] Implement bounded authenticated connect/poll/result commands, a private MCP endpoint, durable separate control grants and revocation.
- [ ] Run focused tests over real HTTP and record results.

## Task 2: Extension connection and page execution

Files: helper background/popup/manifest, reconnect controller and packaged page operations; focused extension tests.

- [ ] Write and run failing tests for retry, process restarts, explicit disconnect and page-reference invalidation.
- [ ] Implement one background connection, startup/alarm reconnect, persisted pairing state, popup status/unpair, packaged page snapshots and supported actions.
- [ ] Exercise a real extension against a local form fixture, including a worker restart.

## Task 3: Existing browser tools and desktop setup

Files: extension browser adapter, browser plugin configuration, Electron setup/engine integration, shared wire types and browser settings.

- [ ] Write and run failing tests for extension mode dispatch, site/protected-page checks, per-job tabs and setup state.
- [ ] Wire the hidden MCP transport into the existing browser facade and add one-time setup, connection status, pause/resume and unpair controls.
- [ ] Run affected browser tests and the desktop build. Verify the settings view and actual MCP browser round trips.

## Task 4: Completion evidence

- [ ] Verify desktop and browser startup order, disconnect/revoke behaviour, no duplicate side effects and no credential leakage.
- [ ] Update the browser guide, research status and changelog with exact results and uncovered paths.
- [ ] Review introduced literals, run diff checks and request a fresh review. Fix important findings with regression checks.
- [ ] Commit only task files; exclude personal text files, recordings and credentials. No merge or release.

## Execution ledger

- Research baseline: runtime has no browser-command receiver. Existing pairing already persists capture credentials and port, but does not grant or expose browser control. Branch `feat/extension-browser-control` starts at the reviewed voice work; personal untracked text files remain untouched.
