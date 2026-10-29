# Multi-channel communication implementation plan

> **For agentic workers:** Use superpowers:executing-plans task by task. The user requested implementation of the existing proposal and delegated its open choices on 29 October.

**Goal:** One local channel core serving Telegram, Discord and Slack with shared policy, delivery, setup and terminal support.

**Architecture:** Dependency-free manifests describe setup and capabilities. Transports receive/send serialisable envelopes; a shared runtime owns queues, approval routing, progress and durable delivery. Desktop and daemon supply agent surface ports.

**Tech stack:** Existing Node/Electron/React stack, native fetch/WebSocket, no new dependencies or hosted services.

**Spec:** `docs/plans/2026-10-29-multi-channel-communication-plan.md`.

## Global constraints and decisions

- Order: extract Telegram, generic settings, Discord, Slack, documented long-tail integration, hardening.
- In-process adapters; native sockets; absorb the daemon inbox into the shared runtime.
- Preserve Telegram transport imports and its existing assertions apart from generic view/property name changes.
- Default-deny inbound policy; owner-only private approvals; channel turns never receive desktop browser credentials.
- Keep capability names: `typing`, `react`, `edit`, `upload`, `threads`, `buttons`, `voice`.
- Envelope keys follow the proposal. Retain platform-specific JSON metadata in `raw`; no engine closures in transport messages.
- Keep new work isolated from the main checkout's provider/speed changes.
- Run focused tests per task; run the serial whole suite once at integration because the requested plan requires it and this extraction crosses the app and daemon.
- External live sends need an approved test destination; fixture/live local transport checks do not establish real account acceptance.

## Review focus

1. Two chats/platforms sharing a teammate must not exchange approvals, files or histories (runtime/surface tests).
2. A connection dying after a send must not duplicate that send after reconnect/restart (outbox and transport tests).
3. Group replies or forged approval buttons must never grant owner permission (policy/runtime tests).
4. A corrupt/migrated settings file must retain recoverable credentials and reject unsafe overwrites (store tests).
5. Disconnect/cancel during pending approvals, retries or socket startup must settle without leaking timers or starting queued work (runtime/adapter tests).

## Task 1 — Contract, registry and safe settings migration

Files: `src/channels/core/contract.mjs`, `registry.mjs`, `store.mjs`; `src/channels/manifests/telegram.mjs`; `test/channels/contract.test.mjs`, `store.test.mjs`.

Interfaces: registry `get(id)`, `list()`, `validate(id, patch)`; store `get(id)`, `preview(id, patch)`, `update(id, patch)`, `telegram()` compatibility aliases; public settings omit every secret value.

- [ ] RED: test manifest validation, default-deny settings, secret stripping, fake registration/env resolution, atomic v1/v2 round trip, rollback and corrupt-file preservation.
- [ ] GREEN: implement descriptor validation and the generic store; keep unsupported saved channel entries rather than discarding them.
- [ ] Verify the new tests and existing desktop channel store assertions; commit.

## Task 2 — Shared inbox, policy and persistent outbox

Files: `src/channels/core/policy.mjs`, `inbox.mjs`, `outbox.mjs`; matching `test/channels/*`.

Interfaces: `sessionKey(ref)`, `ChannelInbox.enqueue(key, fn)`, cancellation outside queue; policy `allows(ref, settings)`, owner identity and single-use pairing; `ChannelOutbox.deliver(envelope, adapter)` returns per-part receipts.

- [ ] RED: test independent sessions, per-target single flight, cancel/stop, default denial, mentions/bots, owner identity, expired/reused pairing, multipart restart dedupe and no blind retry after unknown outcome.
- [ ] GREEN: bounded queues, durable sent/inflight/unknown states, typed failures/backoff/dead targets and single-writer transactions.
- [ ] Verify focused policy/inbox/outbox tests; commit.

## Task 3 — Telegram extraction, progress and agent surfaces

Files: `src/channels/core/runtime.mjs`, `progress.mjs`, `artifacts.mjs`, `surface.mjs`; `src/channels/telegram-adapter.mjs`; `desktop/electron/channels.mjs`, `channel-surface.mjs`; `src/automation/daemon.mjs`.

Interfaces: `ChannelRuntime` consumes registry/store, inbox/outbox, transport and surface; transport `start(ctx)`, `stop()`, `send(envelope)`; surface send/wait/cancel/approval/workspace/event port.

- [ ] RED: preserve the 12 desktop assertions and daemon inbox behaviour; add cross-channel target/history/approval/artifact isolation, owner-only approval and capability-gated progress cases.
- [ ] GREEN: reuse existing Telegram transport; adapters supply metadata from raw updates; replace duplicate desktop/daemon inbox policy with the shared runtime, retaining routine execution.
- [ ] Verify desktop channels, daemon/Telegram regression files and a local HTTP round trip; commit.

## Task 4 — Generic desktop and terminal setup

Files: `desktop/shared/wire.ts`, `desktop/electron/engine.mjs`, `desktop/renderer/src/components/ChannelsSettings.tsx`, `SettingsDialog.tsx`; `src/core/config.mjs`, `commands.mjs`, `cli.mjs`.

Interfaces: `ChannelsView.channels`, `testChannel(id, input)`, `saveChannelSettings(id, patch)`, `/channels`; fields and environment fallbacks come from registry manifests.

- [ ] RED: fake manifest appears and validates without new UI code; secrets are not returned or resubmitted; save/test, responsive keyboard-accessible forms and terminal discovery work.
- [ ] GREEN: render manifest fields using existing settings styles; keep the old Telegram test method as an alias.
- [ ] Verify setup tests, desktop build and browser fixture at desktop/narrow widths; commit.

## Task 5 — Discord transport

Files: `src/channels/discord.mjs`, `manifests/discord.mjs`; shared socket/HTTP helpers only where both adapters need them; `test/channels/discord.test.mjs`.

Interfaces: adapter contract from Task 3, manifest from Task 1; native Gateway and REST operations, message components and text approvals.

- [ ] RED: identify, heartbeat ACK loss, resume, fatal intent/auth close, group/bot metadata, button identity, cancel, upload and rate-limit/unknown-outcome cases.
- [ ] GREEN: implement against current official documentation; lazy startup only when enabled; redact credentials from errors.
- [ ] Verify adapter fixtures and shared runtime; record real-account acceptance separately; commit.

## Task 6 — Slack Socket Mode transport

Files: `src/channels/slack.mjs`, `manifests/slack.mjs`; `test/channels/slack.test.mjs`.

Interfaces: same runtime/registry, no typing capability; socket envelope acknowledgement and dedupe; Web API external upload flow.

- [ ] RED: app-token socket open, envelope ACK/replay, reconnect, threaded replies, owner text/buttons, cancellation, file flow and no typing requests.
- [ ] GREEN: implement current official raw HTTP/WebSocket APIs; no public inbound server.
- [ ] Verify adapter/runtime fixtures; record real workspace acceptance separately; commit.

## Task 7 — Long-tail integration, doctor and documentation

Files: `docs/guides/channels.md`, `docs/guides/channels/{telegram,discord,slack,bridges}.md`, verification script and capability matrix; README and both changelogs.

Interfaces: serialisable adapter/envelope contract, validated registry setup, store doctor and durable delivery records.

- [ ] Document Windows/no-always-on-service + same sender-policy criterion; bridge/relay/SDK integration contract and examples, not a separate hand-written adapter for every platform.
- [ ] Ship reproducible Slack app manifest, Discord intent/invite steps, permission/owner setup and recovery guidance.
- [ ] Verify local transport round trips, full affected tests/build and serial whole suite; record exact counts and remaining live-account gaps.
- [ ] Fresh whole-branch review, fix important findings with regression tests, commit; retain branch for review without merging or releasing.
