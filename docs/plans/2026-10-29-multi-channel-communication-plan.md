# Multi-channel communication — plan

Date: 2026-10-29. Status: implemented in source on 29–30 October; real-account
acceptance remains open. Branch: `feat/multi-channel-communication`.
Completed source tasks are tracked in [the execution plan](../superpowers/plans/2026-10-29-multi-channel-implementation.md);
checks, compatibility rulings and remaining gates are recorded in the
[verification matrix](../verification/multi-channel-communication.md).

Phase 0 decision record (29 October, user delegated the open choices): Telegram →
Discord → Slack; in-process adapters with serialisable envelopes; native
WebSocket/fetch without extra dependencies or hosted services; absorb the daemon
inbox into the shared core. The generic webhook is an integration contract and
documented escape hatch, not an automatically exposed network listener.
Supersedes [telegram-channel-upgrade-plan.md](telegram-channel-upgrade-plan.md) for the
channel *architecture*; that plan's locked scope (progress replies, ack reactions,
send-first files) is shipped and stays as prior art, and
[vault-model-selection-telegram-implementation.md](vault-model-selection-telegram-implementation.md)
remains the record of what actually landed.

Locked scope: **one shared channel core** (queue, policy, progress, delivery) ·
**Telegram extracted onto it with no behaviour change** · **Discord, then Slack** ·
**every other platform reached through a documented escape hatch, not a new adapter by hand**.

## 0. Decision in one paragraph

ANKITA already talks to Telegram. It does so through four copies of the same logic,
and the store, wire types, engine and settings UI are hard-wired to the string
`telegram`. Before adding a second chat app, extract the parts that are the same for
every chat app (per-chat queue, single-flight turn, approval routing, progress
projection, multipart delivery, retry, access policy) into one core, and reduce a
chat app to a *descriptor* (settings + secrets + capability flags) plus a small
transport. Then Telegram is moved onto that core with the existing tests proving
parity, and Discord and Slack are added as transports that add no new policy code.
WhatsApp and the long tail are reached through a bridge or a webhook SDK, chosen by a
written criterion, rather than by writing an adapter per platform.

## 1. Why now

Two concrete reasons, both visible in the working tree:

1. **Adding a channel today costs four edits.** Telegram knowledge lives in
   `src/channels/telegram.mjs`, `desktop/electron/channels.mjs`,
   `src/automation/daemon.mjs` and `src/core/cli.mjs` + `src/core/config.mjs`. A second
   channel cloned from that pattern multiplies the same four places, and the four places
   already disagree with each other (see §1.3).
2. **The seams are telegram-shaped, not channel-shaped.** `ChannelsView` is
   `{ telegram: … }`, the store validates a `TelegramPatch`, and the engine literally
   refuses any other name. These are not hard problems, but they are the exact places
   where "just add Discord" turns into a fork of the settings screen.

## 2. Current state (verified)

### 2.1 What exists

| Piece | Path | Responsibility |
| --- | --- | --- |
| Telegram transport | `src/channels/telegram.mjs` (206 lines) | Raw HTTPS long-poll, `updateToJob`, `splitMessage`, `parseChatIds`, `TelegramBot` |
| Progress projection | `src/channels/telegram-progress.mjs` (73 lines) | 4 s typing heartbeat, 5 s beat throttle, 👀/👍/👎 acks, artifact push (5 files, 15 MB cap, 10 MB photo cap) |
| Desktop bridge | `desktop/electron/channels.mjs` (497 lines) | `ChannelStore` (single JSON, atomic 0600 write), `TelegramChannel` (poll loop → one teammate), `ChannelManager` |
| Engine hooks | `desktop/electron/engine.mjs` | Event fan-out `:328`, construction `:362`, `getChannels` `:621`, `saveChannelSettings` `:623`, `testTelegramChannel` `:632`, `stopAll` `:1416` |
| Renderer contract | `desktop/shared/wire.ts:35-41` | `ChannelStatus`, `TelegramChannelPreferences`, `ChannelsView` |
| Settings UI | `desktop/renderer/src/components/SettingsDialog.tsx` | Flat `ChannelDraft` of Telegram fields; `channel: 'telegram'` hard-coded |
| CLI inbox | `src/automation/daemon.mjs` | `handleJob` `:476`, `pollInbox` `:569`, own approvals + confirm timeout |
| Alert sender | `src/automation/notify.mjs:52-70` | ntfy / Discord webhook / Pushover, outbound only |
| Paired surface | `desktop/electron/phone-pairing.mjs:268` | TLS server, 8-char codes, hashed device keys, per-device runs, approval forwarding |
| Tests | `test/desktop/desktop-channels.test.mjs` (12 tests) + `scripts/verify-telegram-upgrade.mjs` | Stub-level behaviour plus a live round trip |

### 2.2 Structural gaps

1. **Duplication across four files** (above). No single source of truth for "what a
   channel does".
2. **Telegram-shaped contracts**: store payload, `validateTelegramPatch`,
   `ChannelsView`, and `if (channel !== 'telegram') throw new Error('Unknown channel')`
   at `engine.mjs:624`.
3. **No capability flags.** Slack has no typing indicator; `TelegramProgress.typing()`
   would silently no-op or 400 rather than "this platform cannot do that".
4. **One global `activeChat`/`activeJobs` per bridge**, so two channels would contend
   for one slot.
5. **No delivery ledger.** `splitMessage` and artifact push both send multiple parts;
   a restart mid-send can resend.
6. **No per-channel access policy** beyond allowlist + owner chat.

### 2.3 What must not regress

Progress beats, ack reactions, artifact push, approval text (`y`/`a`/`n`), cancel, and
the desktop-only tool boundary `browserCredentialAllowed = surface === 'desktop'`
(`engine.mjs`). All of these have live evidence in the existing ledger and are treated
as contracts by this plan.

## 3. What the reference projects do (verified counts)

### 3.1 OpenClaw — plugin per channel, one Gateway

TypeScript, MIT. One local **Gateway** is the control plane for sessions, tools, events
and channel connections; Control UI, CLI and TUI are clients of it.

- Every channel is a plugin under `extensions/<id>/` with `openclaw.plugin.json`
  declaring `categories: ["channels"]`, `channels: ["telegram"]`, a `configSchema`,
  `activation.onStartup` (lazy) and a `doctorContract` for config repair and state
  migrations.
- `docs/channels/` contains **49 documents: 32 channel pages and 17 cross-cutting
  pages**. The cross-cutting set is the interesting part — `access-groups.md`,
  `bot-loop-protection.md`, `group-messages.md`, `groups.md`, `channel-routing.md`,
  `pairing.md`, `troubleshooting.md`, plus three Matrix-specific and one Discord-specific
  behaviour page. Policy is documented once and shared by all 32 channels.
- Channel pages follow a fixed template: setup, access control, message behaviour,
  threads/sessions, media, events, transports, troubleshooting.
- Security: inbound is untrusted; DM senders must be paired before they reach the agent;
  `allowFrom` per channel; group mention policy; shared bot-loop protection; DMs share
  the agent's main session while each group gets its own.
- Install story: `openclaw channels add --channel <id>` / `openclaw plugins install
  @openclaw/<id>`, with hot reload applied to a running Gateway.
- It also ships an **A2A channel** (agent-to-agent JSON-RPC), i.e. a channel with no chat
  product behind it at all.

### 3.2 Hermes Agent — one gateway process, five platforms, heavy policy

Python, MIT (Nous Research). A single gateway process serves Telegram, Discord, Slack,
WhatsApp, Signal and the CLI. The value is in what `gateway/` contains besides protocol
code: `delivery.py` + `delivery_ledger.py`, `dead_targets.py`, `bot_loop_guard.py`,
`pairing.py`, `owner_identity.py`, `whatsapp_identity.py`, `channel_directory.py`,
`platform_registry.py`, `platform_activation.py`, `authz_mixin.py`, `response_filters.py`,
`stream_consumer*.py`, per-surface session routing.

The caution is the size: `gateway/` holds roughly 200 files, `run.py` alone is
274,903 bytes, and ~60 `hermes_state_*.py` modules sprawl beside it. That is what a
channel layer becomes when policy is added without a shared core.

### 3.3 nanobot — the cleanest contract

Python, MIT (HKUDS). Each channel is a self-contained package
`nanobot/channels/<name>/` with `manifest.py` (dependency-free descriptor),
`runtime.py` (lazy SDK import), `validation.py`, `tests/`, optional `webui/`.

- `ChannelPlugin` carries `name`, `display_name`, `runtime="pkg.mod:Class"`,
  `setup` (`ChannelFieldSpec` kinds: string, secret, bool, list, enum, int, float;
  `required`, `official_url`, `validator`, `verifies_connection`), `dependencies`,
  `default_enabled`, `capabilities`.
- `BaseChannel` requires only `start`/`stop`/`send`; `_handle_message(...)` pushes into
  the bus. `InboundMessage.session_key = "{channel}:{chat_id}"`.
- `registry.py` discovers packages with `pkgutil` and imports a runtime **only when the
  channel is enabled**, so a missing SDK never breaks startup.
- `docs/channel-package-guide.md` opens with an ownership table — one source of truth per
  concern: runtime behaviour in `runtime.py`, requirements in `dependencies`, writable
  settings/types/defaults/secrets/validation in `setup`, discovery plus lazy target in
  `PLUGIN`, UI fields in `webui/`, user-facing copy in locale JSON.
- Naming is enforced: package dir = manifest name = config section = runtime import path.
- It also documents a real failure mode we must avoid: `is_allowed()` reads
  `allow_from` with `getattr`, which **fails silently for a plain dict** and denies every
  message. Config objects must be validated types, not loose maps.
- ~22 channel packages. `telegram/runtime.py` alone is 95 KB — the mass belongs in the
  adapter, never in the core.

### 3.4 The pattern, once

> Declarative per-channel descriptor (settings schema + required secrets + capability
> flags + lazy runtime target) + a thin adapter implementing a narrow contract + one
> shared runtime that owns sessions, access policy, approvals, progress and delivery.

ANKITA today has the middle of that and neither end.

## 4. Existing SDKs and bridges — why we do not simply take one

The question is fair: 32 channels in OpenClaw and 22 in nanobot suggests somebody must
have packaged this. Four families exist, and each trades something specific.

| Family | Example | Platforms | License / health | Fit for ANKITA |
| --- | --- | --- | --- | --- |
| Unified bot SDK | **Chat SDK** (`chat`, v4.43.0) + `@chat-adapter/*` | Slack, Teams, Google Chat, Discord, Telegram, GitHub, Linear, WhatsApp, more | MIT, active, roughly 2.4k stars | Strongest match on *shape* — threads, cards, buttons, streaming, files, a capability catalog. But **webhook-first**: `create-chat-sdk` scaffolds a webhook route, Slack's adapter is "webhooks, OAuth, slash commands", state is Redis/Postgres. Wrong deployment model for a local desktop app with no inbound port |
| Unified bot framework | **Bottender** | Messenger, LINE, Slack, Telegram, Viber — **no Discord, no WhatsApp** | MIT, v1 stable, 2023-era | Missing both target platforms; its own README warns install fails on Windows without `windows-build-tools` + `node-gyp` |
| Chat bridge / relay | **matterbridge** | Discord, IRC, Matrix, Mattermost, MS Teams, Nextcloud Talk, Rocket.Chat, Slack, Telegram, Twitch, XMPP, Zulip, WhatsApp (whatsmeow multidevice), more; third-party bridges via its API | Apache-2.0, single Go binary | One integration reaches many chat apps, but it relays *chat to chat*. ANKITA would be writing bridge-to-a-bridge plus a second state store |
| Omnichannel inbox | **Chatwoot** | live chat, email, Facebook, Instagram, Twitter, WhatsApp, Telegram, LINE, SMS | MIT, support-desk product | Inserts a self-hosted service (app + Postgres + Redis) between the user and their own assistant, and models *human agents*, not one local agent |

Two verified facts settle it:

1. **None of the three reference projects uses a unified SDK.** OpenClaw, Hermes and
   nanobot each hand-roll thin adapters and share the policy layer instead. The reason is
   visible in OpenClaw's own capability table: differences are not cosmetic — Discord can
   read pre-join history, Telegram cannot read it at all, LINE has no history reader,
   Slack's introduction path excludes DMs. A lowest-common-denominator SDK either exposes
   those differences anyway or hides them and behaves wrongly.
2. **Deployment model decides fit, not API surface.** A webhook SDK assumes a public
   endpoint. ANKITA long-polls Telegram and holds an outbound socket for Discord, behind
   an app that opens no inbound port.

**Decision: adopt Chat SDK's ideas now, its dependency later (if ever).**

- Take the **adapter catalog** concept: capability metadata as dependency-free *data*,
  importable by a settings screen and a CLI. That is exactly the capability-gated
  manifest in §5, and an independent project arriving at the same shape is evidence the
  design is right.
- Keep the door open: if ANKITA ever gains a hosted relay with a public endpoint, the
  long tail (Teams, Google Chat, LINE, Viber, WhatsApp Cloud API) can be served by `chat`
  plus adapters *behind the same `ChannelRuntime`*, because the runtime only ever sees
  normalised envelopes (§5.2).
- Adopt an SDK for a platform only when (a) the platform genuinely cannot be reached
  without a public webhook, **and** (b) a relay is acceptable to the user, **and**
  (c) the SDK ships capability metadata so gating stays data.
- **Matrix + mautrix bridges** is the other serious long-tail option (integrate once, get
  WhatsApp/Signal/Telegram bridges). Cost: an always-on homeserver plus one bridge
  process per platform, with uneven fidelity for buttons, threads and edits. Phase 5
  option B, not Phase 1.

## 5. Target architecture

### 5.1 File layout (additive — nothing is moved out from under an importer)

```text
src/channels/
  core/contract.mjs     envelope shapes, capability set, assertAdapter(), manifest validation
  core/policy.mjs       allowlist, owner, group policy, pairing codes, bot-loop guard, timeout bounds
  core/inbox.mjs        per-chat FIFO + cancel lane + single-flight (replaces activeChat/activeJobs)
  core/outbox.mjs       ordered multipart delivery, per-part receipts, bounded retry, unknown-outcome class
  core/progress.mjs     capability-gated typing/beats/acks (generalised from telegram-progress.mjs)
  core/artifacts.mjs    capability-gated file push (generalised from sendTurnArtifacts)
  core/runtime.mjs      ChannelRuntime: binds adapters to a Surface port; owns jobs, approvals, cancel
  manifests/telegram.mjs  descriptor: fields, required, capabilities, defaults, docsUrl
  manifests/discord.mjs
  manifests/slack.mjs
  telegram.mjs          unchanged transport (four existing importers keep working)
  discord.mjs           new transport only — no policy, no progress, no queue
  slack.mjs
```

`src/channels/telegram.mjs` deliberately stays put; the extraction must not break
`src/automation/daemon.mjs`, `src/core/cli.mjs`, `scripts/verify-telegram-upgrade.mjs`
or the test harness for reasons unrelated to channels. A symmetrical rename to
`adapters/telegram.mjs` is optional cleanup at the very end, with the import sites
updated in the same commit.

### 5.2 The adapter contract

```js
// start/stop/send are required. Everything else is optional; absence = capability off.
{
  manifest: { id, label, capabilities, fields, required, docsUrl, connect },
  start(ctx),                  // must not resolve until stopped; pushes into ctx.receive(envelope)
  stop(),
  send(envelope),              // resolves { messageId, parts: [platformIds] } or throws a typed failure
  typing(ref), react(ref, key), edit(ref, text), upload(ref, file), buttons(ref, rows)
}
```

Normalised envelopes, all JSON-serialisable by rule:

```text
Inbound  { channel, chatId, messageId, senderId, senderName, text, media[], replyTo, threadId, raw }
Outbound { channel, chatId, parts[], replyTo, threadId, files[], buttons[], intent }
```

Serialisability is a deliberate constraint, not a style preference: it keeps adapters as
plain data-in/data-out objects, so a bridge can later run out of process (§4) without a
rewrite. No closures into engine internals cross the boundary.

`session_key = "{channel}:{chatId}"` (nanobot's convention) — group chats get their own
session, so a Discord guild and a Telegram DM never share turn state.

### 5.3 The Surface port (the seam to the agent)

| Port method | Existing call today |
| --- | --- |
| `send(target, text, { surface })` | `engine.send(teammateId, text, null, { surface: 'channel' })` |
| `onEvent(fn)` | engine event sink → `channels.handleEngineEvent` (`engine.mjs:328`) |
| `respondApproval(requestId, answer)` | `engine.respondApproval` |
| `cancel(target)`, `waitForTurn(target)` | `engine.cancel`, `engine.waitForTurn` |
| `workspaceFor(target)` | `engine.agents.get(id) ?? engine.agentFor(id)`, then `.cwd` (`channels.mjs:329`) |

`DesktopSurface` wraps the desktop engine; `DaemonSurface` wraps the CLI agent. That is
how the duplicate `handleJob`/`pollInbox` in `src/automation/daemon.mjs` is retired
instead of copied a third time, and why desktop and CLI finally behave the same.

### 5.4 Capability matrix (the table that replaces `if (channel === …)`)

| Capability | Telegram | Discord | Slack |
| --- | --- | --- | --- |
| typing indicator | yes | yes | **no** |
| reaction ack | yes (👀/👍/👎) | yes | yes |
| edit message | no (today) | yes | yes |
| file upload | yes | yes | yes |
| thread / topic | yes | yes | yes |
| approval buttons | no (text `y`/`a`/`n`) | yes | yes |
| voice reply | yes | yes | yes |

Every consumer asks `caps.has('…')`. `core/progress.mjs` becomes "send typing if the
capability exists, otherwise send nothing"; Slack earns no indicator instead of throwing.
Text `y`/`a`/`n` remains the universal approval fallback so no platform is ever blocked
on rendering buttons.

## 6. Configuration and settings become data

A manifest is the only place that knows a channel's settings:

```js
// src/channels/manifests/discord.mjs (shape; values are constants with units + reasons)
export const manifest = {
  id: 'discord',
  label: 'Discord',
  docsUrl: '…',
  capabilities: ['typing', 'react', 'edit', 'upload', 'threads', 'buttons', 'voice'],
  required: ['botToken', 'applicationId'],
  fields: {
    botToken:      { kind: 'secret', env: 'DISCORD_BOT_TOKEN', label: 'Bot token' },
    applicationId: { kind: 'string', env: 'DISCORD_APPLICATION_ID', label: 'Application ID' },
    allowFrom:     { kind: 'list',   label: 'Allowed users and servers' },
    mentionPolicy: { kind: 'enum',   values: ['mention', 'open', 'allowlist'], default: 'mention' },
    progressBeats: { kind: 'bool',   default: true },
  },
};
```

One descriptor drives five consumers — this is nanobot's ownership table applied:

| Consumer | Reads |
| --- | --- |
| validation | `fields`, `required`, `kind` |
| settings screen | `fields`, `kind`, `label` → inputs are generated, no new UI code per channel |
| engine save/verify | `manifest.validate(patch)`, `manifest.verify(input)` |
| env / config fallback | `fields[].env` → `config.mjs` stops growing a hand-written key list |
| runtime | `capabilities` |

Store migration is part of this phase, not a later cleanup: today's file is
`{ telegram: {…} }`; v2 is `{ version: 2, channels: { telegram: {…} } }`. The migration
must be atomic (write-temp + rename, as the current store already does), test-covered in
both directions, and it must never silently drop a token. `store.telegram()` survives as
a thin alias during the transition.

Wire and UI: `ChannelsView` becomes `{ channels: Record<ChannelId, ChannelPreferences> }`.
The app is not a public API, so take the breaking change rather than carrying a shim
forever; delete `if (channel !== 'telegram') throw` and validate through the manifest.
`testTelegramChannel` becomes `testChannel(id, input)` with the old name aliased, and
`/channels` is added to `src/core/commands.mjs` so status and connect are reachable
without the settings window.

## 7. Security model (built in Phase 1, before a second platform can be reached)

The risk is not the protocol. It is that a chat bot is a door to the computer running
ANKITA. Therefore:

| Rule | Why |
| --- | --- |
| Allowlist required to answer at all; empty allowlist = answer nobody | A default-open bot on a public platform is an open shell |
| Pairing codes for unknown senders, modelled on `phone-pairing.mjs` (short code, 2-minute life, single use, wrong guesses burn it) | Borrowed from OpenClaw's `pairing approve`; ANKITA already has the code-and-hash pattern |
| Approvals route to the **owner** chat only, never to a group or a newly paired device | A stranger must never be able to confirm a tool call |
| Group policy per channel: `mention` \| `open` \| `allowlist`, default `mention` | Prevents ambient replies in a busy server |
| Bot-loop guard: ignore messages authored by a bot, cap consecutive bot↔bot replies | OpenClaw and Hermes both ship this; without it two assistants can ping-pong |
| `surface: 'channel'` stays a first-class surface, and `browserCredentialAllowed = surface === 'desktop'` is locked by a test | Channel turns must never reach saved browser credentials |
| Per-turn tool budget and `confirmTimeout` bounds live in `core/policy.mjs` with units | One place to reason about cost and consent |

Pairing can ship disabled behind a manifest flag, but the code exists before Discord
exists, not after.

## 8. Delivery semantics

`core/outbox.mjs` owns what the current code does inline and lossily:

- **Ordering**: one queue per `session_key`; parts of one reply never interleave with
  another reply.
- **Per-part receipts**: `splitMessage` and artifact push both send several platform
  messages; the outbox records which parts were accepted, so a retry resumes instead of
  duplicating.
- **Typed failures**: `rate_limited` (retry after the platform-provided delay),
  `transient` (bounded retry with backoff), `permanent` (surface the error, never loop),
  `unknown` (sent-then-timed-out — do *not* blind-retry a user-visible message; mark and
  let policy decide). This is Hermes' `delivery_ledger` idea in one file.
- **Dedupe key**: `channel:chatId:messageId:part`, so a resumed turn cannot double-send.
- **Dead targets**: a chat that returns permanent failures is marked and skipped until
  re-verified, instead of failing every future turn.

Constants (backoff, caps, part sizes, heartbeat intervals) live in `core/contract.mjs`
and manifests with units and a stated reason, per the repo's no-hardcoding rule.

## 9. Phases

Each phase is independently mergeable and ends with evidence, not intentions.

### Phase 0 — Decisions (no code)

Record in this document: which platforms and in what order; in-process adapters
(Option A) vs a pairing-protocol server (Option B); raw WebSocket vs an SDK per platform;
and whether the CLI daemon inbox is absorbed in Phase 1 or deferred. Freeze the envelope
shape (§5.2) and the capability names (§5.4), because everything downstream derives from
them.

### Phase 1 — Extract the core, Telegram only, zero behaviour change

Adds `src/channels/core/*` and `src/channels/manifests/telegram.mjs`; rewrites
`desktop/electron/channels.mjs` into host glue over `ChannelRuntime`; leaves
`src/channels/telegram.mjs` untouched.

- `ChannelStore` becomes generic, with the v1 → v2 migration (§6) plus a rollback path.
- `TELEGRAM_DEFAULTS` / `validateTelegramPatch` move into the Telegram manifest as
  `fields`; `parseChatIds` stays adapter-side because it parses a Telegram-specific input
  format.
- `ChannelManager` keeps its name and public view; internally it configures the runtime.
- Policy lands now (§7), pairing included but switchable.
- `core/inbox.mjs` replaces the single `activeChat`/`activeJobs` so two channels cannot
  contend for one slot.

**Exit criteria**

1. `node --test test/desktop/desktop-channels.test.mjs` — 12/12 pass, with only import and
   name updates. Any changed *assertion* is a behaviour change and needs its own
   justification in the commit message.
2. New `test/channels/policy.test.mjs`, `inbox.test.mjs`, `outbox.test.mjs` (stub-based,
   no network).
3. `node scripts/verify-telegram-upgrade.mjs <approved-chat-id>` live: typing heartbeat,
   progress beats, ack reactions, one image, and cancellation still observed. The script's
   own counters (`actions`, `progress`, `reactions`, `files`) are the evidence — quote the
   numbers in the ledger.

### Phase 2 — Settings become data (§6)

Manifest-driven form, generic save/verify IPC, `/channels` command, env keys from
manifests, `ChannelsView` reshaped.

**Exit criteria:** a test registers a fake manifest and asserts that (a) the settings view
exposes its card, (b) a patch for it validates, (c) its env key resolves — all with no UI
code written for it. Telegram's card is pixel-identical in behaviour.

### Phase 3 — Discord

Transport `src/channels/discord.mjs`: Gateway v10 over the platform WebSocket (identify,
heartbeat, resume), REST over `fetch` (send, react, typing, multipart upload, edit),
threads via message references, approvals as message components.

Platform facts to confirm at implementation time, not assume: the Message Content intent is
privileged and must be enabled for the application, and the bot must be invited to the test
guild.

**Exit criteria:** stub WebSocket tests for identify / heartbeat / reconnect-and-resume /
intent-missing; allowlist denial; approval via button **and** via `y`; `/cancel`; one file
upload. Then a live run in a private guild: one text turn, one approval, one file.

### Phase 4 — Slack (Socket Mode)

`apps.connections.open` WebSocket, `chat.postMessage`, `reactions.add`, `files.uploadV2`,
`thread_ts`, Block Kit buttons. Slack is the first platform without a typing indicator,
which is what proves the capability gate end to end.

**Exit criteria:** the same test matrix as Phase 3 minus typing; the app manifest JSON
committed at `docs/guides/channels/slack.md` so setup is reproducible rather than
remembered.

### Phase 5 — Reaching the long tail without writing an adapter per platform

Choose per platform, in writing, between: (a) a manifest + transport we own; (b) a public
relay running Chat SDK adapters behind the same runtime (§4); (c) a bridge hub
(Matrix + mautrix, or matterbridge) treated as one channel; (d) the generic webhook /
WebSocket channel, which also gives other agents and scripts a first-class way to drive
ANKITA.

Criterion, applied to each platform: **can it run on Windows with no separate always-on
service, and can an unknown sender be held to the same policy?** If no to either, it is a
relay or bridge decision, not an adapter.

The repo's own research already answers this for one platform: WhatsApp calling is on hold
and the Windows helper situation is documented in
[2026-10-22-skills-and-whatsapp-calling.md](../research/2026-10-22-skills-and-whatsapp-calling.md).
Do not re-litigate; build on it.

### Phase 6 — Hardening, docs, and the QA matrix

Persisted delivery ledger (§8), dead targets, bot-loop guard, config doctor (OpenClaw's
`doctorContract` idea — ANKITA needs one anyway for the v1 → v2 migration), per-platform
docs at `docs/guides/channels/<id>.md`, a `docs/guides/channels.md` index, README and
CHANGELOG updates, and a capability × platform matrix filled with evidence rather than
ticks.

## 10. Why this order

- **Telegram first** because it is the only path with live evidence today. Extracting the
  core while a real round trip proves parity is the cheapest possible time to do it.
- **Discord second** because it needs no public endpoint (outbound gateway socket), its
  threads and buttons map directly onto ANKITA's approval gate, and it is the platform
  whose audience already owns the desktop.
- **Slack third** because it needs an app manifest and, in a workspace, an admin. Its
  missing typing indicator is a feature of the plan: it proves the capability gate.
- **Everything else through a criterion**, because the fourth and fifth adapters are where
  a channel layer turns into Hermes' 200 files.

## 11. Verification plan

Per the repo's rules, a phase is not done until it is executed.

| Level | How |
| --- | --- |
| Unit, per phase | `node --test test/channels/<file>.test.mjs` — stub transports, no network, no real credentials |
| Regression | `node --test test/desktop/desktop-channels.test.mjs` — the 12 existing tests are the parity net for Phase 1 |
| Migration | round-trip test: v1 file → v2 → read back → identical tokens and settings; plus a corrupted-file path |
| Live, Telegram | `node scripts/verify-telegram-upgrade.mjs <approved-chat-id>`, quoting the counter values |
| Live, Discord / Slack | a private guild / test workspace: one text turn, one approval, one file, then `/cancel` mid-turn |
| Adversarial | unknown sender denied, group message without mention ignored, bot-authored message ignored, approval from a non-owner refused, expired pairing code refused |
| Whole suite | `npm test` (the repo's `node --test --test-concurrency=1`) before declaring any phase complete |

Report format: changed files, test counts, exact outputs, and a confidence ledger.

## 12. Risks

| Risk | Mitigation |
| --- | --- |
| **Reachability**: a chat bot is a door into the host machine | Policy in Phase 1, owner-only approvals, allowlist default-deny, `surface: 'channel'` credential boundary locked by test |
| **Approval fatigue**: four platforms × progress beats is four times the noise | Beats become a per-manifest setting with one throttle implementation, not four |
| **Rate limits** differ per platform (chat actions, per-message edit windows, tiered REST) | Throttles are named constants with units in `core/contract.mjs`; adapters report `rate_limited` and the outbox waits the platform-stated delay |
| **Scope creep toward 30 platforms** | A written criterion per platform (§9 Phase 5); breadth is a documentation goal, not an adapter goal |
| **Suite drift** during the Phase 1 rewrite | Existing assertions are frozen; a changed assertion is a behaviour change and is called out |
| **Bridging instead of integrating** (Matrix/matterbridge) hides fidelity loss | Capability flags per bridge channel; anything unsupported is reported, never faked |
| **Silent policy failure** (nanobot's `getattr` on a dict) | Settings are validated typed objects, never loose maps; allowlist resolution has its own tests |

## 13. Deliberately not in this plan

- A Hermes-style full gateway process rewrite.
- OpenClaw-style breadth (32 platforms) as a deliverable.
- An in-app channel marketplace or third-party plugin loading at runtime.
- WhatsApp calling (already on hold in the repo's research notes).
- Any change to the browser, voice, or computer-use paths.
- Hosted infrastructure of any kind. If a relay ever happens, it is a later, explicit
  decision (§4), not a quiet dependency.

## 14. Open questions (need a decision before Phase 1)

1. **Platform order** — proposed: Telegram → Discord → Slack → generic webhook, with
   WhatsApp gated on the §9 Phase 5 criterion. Different priority?
2. **Option A vs B** — in-process adapters with a JSON-serialisable boundary (proposed), or
   committing now to a paired-surface protocol server reusing `phone-pairing.mjs`?
3. **Raw WebSocket vs SDK** — no new dependencies (proposed, matches `TelegramBot`'s
   framework-free style and Node's global `WebSocket`), or `discord.js` /
   `@slack/socket-mode` for batteries-included reconnects?
4. **CLI daemon inbox** — absorb `src/automation/daemon.mjs`'s Telegram inbox into the
   shared core in Phase 1 (bigger diff, removes a permanent duplicate), or leave it until
   after Discord ships?

## 15. References

Local, verified while writing this:

- `src/channels/telegram.mjs`, `src/channels/telegram-progress.mjs`
- `desktop/electron/channels.mjs`, `desktop/electron/engine.mjs`,
  `desktop/electron/phone-pairing.mjs`
- `desktop/shared/wire.ts`, `desktop/renderer/src/components/SettingsDialog.tsx`
- `test/desktop/desktop-channels.test.mjs`, `scripts/verify-telegram-upgrade.mjs`
- `src/automation/daemon.mjs`, `src/automation/notify.mjs`, `src/core/config.mjs`,
  `src/core/cli.mjs`
- [telegram-channel-upgrade-plan.md](telegram-channel-upgrade-plan.md),
  [vault-model-selection-telegram-implementation.md](vault-model-selection-telegram-implementation.md),
  [../research/2026-10-22-skills-and-whatsapp-calling.md](../research/2026-10-22-skills-and-whatsapp-calling.md)

External, checked at source rather than from summaries:

- OpenClaw — `docs/channels/index.md` (49 channel documents), `docs/channels/pairing.md`,
  `extensions/telegram/openclaw.plugin.json`, `docs/gateway/security`
- Hermes Agent — `gateway/` inventory and `README.md`
- nanobot — `docs/channel-package-guide.md`, `nanobot/channels/plugin.py`,
  `nanobot/channels/base.py`, `nanobot/bus/events.py`, `nanobot/channels/registry.py`
- Chat SDK — `vercel/chat` README, `npm view chat` (v4.43.0, MIT),
  `@chat-adapter/slack`, `@chat-adapter/catalog`
- matterbridge — README + LICENSE (Apache-2.0)
- mautrix-whatsapp — README (whatsmeow-based, requires a Matrix homeserver)
- Bottender — README (MIT, v1 stable, platforms listed, Windows install warning)
- Chatwoot — README (MIT, channel list)







