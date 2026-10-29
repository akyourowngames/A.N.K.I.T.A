# Multi-channel communication: verification record

29 October 2026. Branch: `feat/multi-channel-communication`, based on
`origin/ankita` at `812b1b6889d308edc5ca39a8d0cde4b735fd3d05`. Work is isolated
from unrelated changes in the main checkout. No version bump or release.

## Implemented behavior

- One descriptor registry, recoverable v1/v2 store, policy, inbox, progress,
  approvals and durable outbox; desktop/terminal/daemon host ports.
- Telegram compatibility facade plus native Discord Gateway and Slack Socket
  Mode adapters, loaded lazily. No added dependency or public server.
- Descriptor-generated settings, secret-safe drafts/test/save, `/channels`, env
  fallback, doctor and short-lived sender-bound pairing.
- Isolated additional-platform/group histories, four shared host permits,
  private owner-only approval, bot-loop guards and workspace artifact containment.
- SDK/bridge route is documented at [bridges](../guides/channels/bridges.md).
  It is an extension contract, not a fourth shipped channel.

## Evidence matrix

Local round trips use real loopback HTTP and native Node WebSocket clients with
test servers. Agent/provider responses are deterministic fixtures. They prove
packet routing and runtime behavior, not external service permissions or model
quality. No messages were sent to real accounts during this build.

| Behavior | Telegram | Discord | Slack |
| --- | --- | --- | --- |
| Text/final reply | `telegram-adapter.test.mjs`, local HTTP, one turn | `transport-roundtrip.test.mjs`, native socket + HTTP, one turn | Same native socket + HTTP check, one turn |
| Typing | Local Bot API `sendChatAction` | Local REST HTTP 204 | Absent capability; replay test asserts no typing request |
| Work updates/reactions | Existing 12 desktop cases + daemon upgrade cases; local HTTP counts two reactions | Shared runtime tests + local REST reaction | Shared runtime + local `reactions.add` |
| File upload | Existing multipart/containment/fallback cases | Native round trip multipart file | Native round trip ticket → byte upload without auth → completion |
| Edit | Not advertised | Native round trip PATCH | Native round trip `chat.update` |
| Owner buttons/text | Text owner policy/runtime + daemon cases | Request-bound buttons over native socket; generic text owner tests | Block Kit button over native socket; generic text owner tests |
| Threads | Existing Bot API topic options retained | Origin thread/channel plus message references; REST fixture | Fixture asserts parent `thread_ts` on replies/files |
| Reconnect/replay | Cursor commits after acceptance; local auth abort | Identify/resume/ACK-loss/fatal intent fixtures | Fresh socket URL/ACK/replay fixtures |
| Stop/cancel | Desktop/daemon/runtime cases | Generic owned cancellation and socket handshake stop | Generic owned cancellation and socket handshake stop |
| Speech | Existing channel voice staging tests | Not advertised | Not advertised |

Observed traces:

```text
TELEGRAM_CHANNEL_HTTP_OK: real HTTP; sender/bot policy; typing; 2 reactions; 1 final reply; clean stop.
DISCORD_LOCAL_ROUNDTRIP_OK: native socket; HTTP; one turn; final reply; owner button; edit; upload; clean shutdown.
SLACK_LOCAL_ROUNDTRIP_OK: native socket; HTTP; one turn; final reply; owner button; edit; upload; clean shutdown.
CHANNEL_SETTINGS_UI_OK: generated card; secret-safe edits; drafts survive status; save/test; keyboard; 1280/620/390; zero renderer errors.
```

The settings component was also captured and visually inspected at 1100px with
Slack selected. It uses current app theme tokens, keyboard tabs, responsive
forms and reduced-motion support. This was a browser component fixture, not a
packaged Electron window. Desktop typecheck/Vite build passed with **408 modules**.

## Reproduced and fixed during implementation

| Before | Regression | After |
| --- | --- | --- |
| Waiting channel turn changed the active desktop budget | runtime wait/budget test | Wait before claiming/budget mutation |
| More than four channel turns ran at once | runtime pool test | Four shared host permits |
| Unknown reply accepted a group approval | daemon owner-private case | Only configured private owner may answer |
| Replay ran the same input twice | daemon/runtime inbound tests | Durable inbound claim precedes dispatch |
| Retry-after of 60 seconds became 30 seconds | outbox delay case | Platform delay remains 60 seconds |
| Missing receipt recorded as sent | outbox missing-receipt case | Unknown once; second attempt performs no send |
| Public manifest could include a nonempty secret default | contract secret-default case | Descriptor rejected before use |
| Concurrent setup created two runtimes | host concurrent-create case | One shared creation promise |
| Concurrent saves started while another stop was pending | host reconnect ordering case | Saves serialize per channel |
| Late auth restored an account after shutdown | runtime auth/stop case | Old generation cannot update state |
| Telegram cursor advanced before durable acceptance | local adapter cursor case | Cursor advances only after acceptance |
| Telegram stop waited for auth timeout | real local hanging HTTP request | Authentication is aborted promptly |
| Always approval missed an isolated desktop agent | desktop channel-surface approval case | Grant applies only to that channel agent |

## Compatibility rulings

The 12 existing desktop Telegram behaviors remain asserted. References to the
public view changed from `.telegram` to `.channels.telegram`. Credential fixtures
use unique values: a public schema legitimately contains the words `token` and
`secret`, so searching its JSON for those dictionary words was no longer a valid
leak test. Fake file/text sends now return realistic message IDs; their assertions
are unchanged. A photo fallback fixture now uses an explicit permanent rejection:
an untyped exception is an unknown outcome and must not be sent again as a file.

Default-deny sender rules, private owner/group separation and bot-loop protection
are intentional security changes to the former inbox behavior. Telegram private
desktop history routing remains shared with its selected teammate; groups and
additional platforms are isolated. Slack uses the official external upload flow:
`files.uploadV2` in the proposal was an SDK helper, not a raw API method.

## Remaining acceptance gates

- No approved private Discord server or Slack workspace/destination was provided;
  real-account text/approval/file/cancel/reconnect checks remain open.
- The earlier external Telegram script was not rerun against a user's account.
  New loopback evidence does not replace that acceptance check.
- No packaged installer or physical speech/hardware check was performed for this
  channel change. No desktop voice behavior was intentionally modified.
- Terminal/Desktop should not simultaneously host the same bot. The receipts
  prevent duplicates, but platform consumer contention is not a supported mode.
- A crash after inbound acceptance is at-most-once: unfinished work is visible in
  diagnostics but not automatically executed again. Check work before retrying.
- WhatsApp/bridge/relay services and large Discord sharded bots remain outside
  this source implementation. Channel agent workspaces may still collide when
  users deliberately ask separate conversations to edit the same file; channel
  session isolation is not a general filesystem transaction system.

Full-suite results and final review disposition are appended after integration
checks complete.
