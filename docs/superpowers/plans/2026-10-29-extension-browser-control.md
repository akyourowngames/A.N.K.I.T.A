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

- [x] Write and run failing tests for control opt-in, restart using the same token/port, origin/session isolation and lost-response non-replay.
- [x] Implement bounded authenticated connect/poll/result commands, a private MCP endpoint, durable separate control grants and revocation.
- [x] Run focused tests over real HTTP and record results.

## Task 2: Extension connection and page execution

Files: helper background/popup/manifest, reconnect controller and packaged page operations; focused extension tests.

- [x] Write and run failing tests for retry, process restarts, explicit disconnect and page-reference invalidation.
- [x] Implement one background connection, startup/alarm reconnect, persisted pairing state, popup status/unpair, packaged page snapshots and supported actions.
- [x] Exercise a real extension against a local form fixture, including a worker restart.

## Task 3: Existing browser tools and desktop setup

Files: extension browser adapter, browser plugin configuration, Electron setup/engine integration, shared wire types and browser settings.

- [x] Write and run failing tests for extension mode dispatch, site/protected-page checks, per-job tabs and setup state.
- [x] Wire the hidden MCP transport into the existing browser facade and add one-time setup, connection status, pause/resume and unpair controls.
- [x] Run affected browser tests and the desktop build. Verify the settings view and actual MCP browser round trips.

## Task 4: Completion evidence

- [x] Verify desktop and browser startup order, disconnect/revoke behaviour, no duplicate side effects and no credential leakage.
- [x] Update the browser guide, research status and changelog with exact results and uncovered paths.
- [x] Review introduced literals, run diff checks and request a fresh review. Fix important findings with regression checks.
- [x] Commit only task files; exclude personal text files, recordings and credentials. No merge or release.

## Execution ledger

- Research baseline: runtime has no browser-command receiver. Existing pairing already persists capture credentials and port, but does not grant or expose browser control. Branch `feat/extension-browser-control` starts at the reviewed voice work; personal untracked text files remain untouched.

- Tasks 1-3: implemented and covered by failing-then-passing focused regressions. Real HTTP/MCP, actual extension, existing Chrome and Playwright round trips passed; renderer build transformed 405 modules.
- Final review: fresh reviewer identified delivered-command cancellation, post-attachment target races, Enter/modifier encoding, revoked-access recovery and worker-owned state loss. All were fixed with regressions; page/keyboard paths also ran in real Chromium.
- Additional regressions: desktop/popup pause agreement, simultaneous atomic configuration writes, capture/control code independence, ordinary HTTP IDs and keeping unrelated browsers open on disconnect.
- Verification before final rerun: 70/70 focused checks; then 3/3 actual extension/page/native Chrome checks and 20/20 broker/capture/action checks after further hardening. Final consolidated output is recorded in the findings receipt.
- Final: no deferred minor review findings. Native messaging/store publication and packaged/multi-platform acceptance remain stated limits, not deferred claims of working behaviour.
- Integration: separate browser branch on top of the still-open voice PR #71; use a stacked PR so this review contains only browser work. No merge or release.
- Final consolidated verification: 73 tests passed, 0 failed (58.806s), including actual extension and native Chrome round trips, real Playwright form work and both CSP entry points. The later shared-copy refactor rechecked 16/16 broker/reconnect/actual-extension cases. Diff and main syntax checks passed. No full-suite run, per user instruction.
