# More channels: adapter, relay or bridge

Telegram, Discord and Slack are shipped source connectors. Other platforms are
an extension contract, not an installed integration or a listener opened by
default. Apply two questions before adding one: **can it run on Windows without
a separate always-on service, and can unknown senders keep the same default-deny
policy?** Failure of either question requires an explicit relay/bridge decision.

| Platform/group | Chosen route | Why / gate |
| --- | --- | --- |
| Telegram, Discord, Slack | Owned manifest + thin transport | Outbound connections, platform sender IDs and private owner approvals are available locally. |
| WhatsApp calling | On hold | The repo's [22 October audit](../../research/2026-10-22-skills-and-whatsapp-calling.md) found a separate non-Windows helper requirement. Do not treat messaging access as calling support. |
| WhatsApp Cloud messaging, Teams, Google Chat, LINE, Viber | Optional public relay using an SDK | Webhook-first deployments need an accepted hosted endpoint, authenticated events and capability metadata. No relay is deployed here. |
| Signal/WhatsApp through Matrix bridges | Optional Matrix hub | A homeserver and bridge processes are separate always-on services. Preserve original sender/room IDs and advertise only the fidelity the bridge actually retains. |
| Mattermost, IRC, Rocket.Chat, XMPP, Zulip via matterbridge | Optional bridge hub | One authenticated bridge integration can cover a family; sender identity and unknown-send receipts must survive relay mapping. Not included in the current registry. |
| Private scripts or another agent | Local adapter using the same serialisable envelope | Use a trusted in-process event source today. A generic authenticated webhook/WebSocket server requires a separate approved network/security scope. |

The latter rows are architectural choices, not claims of tested platform support.
[Matterbridge's API](https://github.com/42wim/matterbridge/wiki/API) supplies a stream
and optional bearer authentication; its [capability differences](https://github.com/42wim/matterbridge/wiki/Features)
mean an upload, edit or button must never be promised solely because the original
platform supports it. A relay that supplies only a display name cannot authorize
an owner. Preserve a verified immutable sender ID, or keep it read-only/disabled.

## In-process adapter contract

Manifests are JSON data registered in `src/channels/core/registry.mjs`. They
declare `id`, `label`, `connect`, `capabilities`, `required`, `fields` and a bundled
lazy `runtime` module/export. Supported field kinds are string, secret, bool,
list, enum, int and float; use shared fields for policy rather than reimplementing
it. Secret defaults must be empty. A saved settings patch cannot install code or
change runtime module paths. A newly registered descriptor automatically appears
in Settings and `/channels`, validates patches and resolves its declared env keys.

An adapter implements:

```js
// Protocol sketch, not a network endpoint. Inject your authenticated source.
class Adapter {
  constructor({ manifest, source }) { this.manifest = manifest; this.source = source; }
  start(ctx) {
    // ctx = { settings, signal, receive(envelope), status(partialStatus) }
    // Set this.ready synchronously to a Promise<{account}>.
    // Return the connection lifetime; abort/stop must settle ready and lifetime.
    return this.source.run(ctx);
  }
  stop() { return this.source.stop(); }
  send(envelope, options) { return this.source.send(envelope, options); }
}
```

Required inbound keys:

```js
{
  channel, chatId, messageId, senderId, senderName, text,
  media: [], replyTo: null, threadId: null,
  raw: { isGroup, serverId, mentioned, bot, webhook, system }
}
```

All fields must be JSON serialisable. Session keys use `channel:chatId`; platform
IDs are strings. Never forward credentials, signed response URLs, functions or
SDK objects in `raw`. Source authentication establishes the sender metadata;
message text is untrusted content and cannot establish authority.

Outbound envelopes include `parts`, optional `files`, `replyTo`, `threadId` and a
stable `intent`. Every send/upload returns `{ messageId, parts: [messageId] }`
with real platform-accepted IDs. A file receipt may be a real platform file ID.
Only declare `typing`, `react`, `edit`, `upload`, `threads`, `buttons` or `voice`
when implemented. `assertAdapter` checks required capability methods. Buttons
carry the request ID and answer; the shared runtime separately checks owner,
private conversation and a currently pending request. Plain-text approval works
without buttons.

Use `DeliveryError` with `rate_limited`, `transient`, `permanent` or `unknown`.
Only an explicit rejection before acceptance may be retried. Return the actual
`retryAfterMs`; do not shorten it. Timeout after a write is unknown, not transient.
Socket/poll acknowledgements and resume cursors advance only after
`ctx.receive()` settles; a durable-inbox failure must remain replayable. ACKs do
not wait for the agent turn, because the runtime queues accepted work first.

The runtime owns policy, per-conversation queues, shared agent permits, approvals,
progress, cancellation and the durable outbox. An SDK adapter must enter through
that runtime; it may not execute the agent from its webhook handler directly.
See `test/channels/transport-roundtrip.test.mjs` for runnable native socket/HTTP
examples, and `test/desktop/channel-settings.test.mjs` for a fake manifest proving
that registration does not require channel-specific UI code.
