# Multi-channel communication: verification record

Implemented 29 October; review fixes and final checks 30 October 2026.
Branch: `feat/multi-channel-communication`, based on
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
- Channel work currently requires an API provider. ChatGPT Browser is explicitly
  blocked with setup guidance; isolated browser-only channel sessions and their
  tool budget are outside this implementation.
- Terminal/Desktop should not simultaneously host the same bot. The receipts
  prevent duplicates, but platform consumer contention is not a supported mode.
- A crash after inbound acceptance is at-most-once: unfinished work is visible in
  diagnostics but not automatically executed again. Check work before retrying.
- WhatsApp/bridge/relay services and large Discord sharded bots remain outside
  this source implementation. Channel agent workspaces may still collide when
  users deliberately ask separate conversations to edit the same file; channel
  session isolation is not a general filesystem transaction system.

## Final checks, 30 October

| Check | Observed result |
| --- | --- |
| Final affected checks: 30 files across channels, desktop setup/provider, daemon and terminal | **246/246 pass**, 0 failures, 72.317 seconds |
| `node scripts/verify-channels.mjs` | **18/18 pass**, local-only; native Discord/Slack sockets and HTTP plus Telegram HTTP |
| Desktop typecheck + Vite build | **408 modules**, app and island assets built, 18.51 seconds |
| Browser-generated setup | Fake card appears without custom UI code; secret drafts survive status/save/test; keyboard and 1280/620/390 widths; no renderer errors |
| Initial whole serial suite, before final review fixes | **1879 total: 1875 pass, 3 fail, 1 skipped**, 1002.319 seconds; not claimed green |
| Task-related full-run failure | Daemon voice fixture returned an array length instead of platform message IDs. Corrected fixture; **2/2 pass**, and included in final 246/246 |
| Remaining two full-run failures | Unchanged base `812b1b6` reproduced both provider-load errors in `test/desktop/desktop.test.mjs`: **6 pass, 2 fail**. Tests read machine settings containing a provider the base does not support. User settings were not edited. |
| Final whitespace/literal review | `git diff --check` clean; protocol keys and interface copy are data, timings/limits/URLs are named constants or injected parameters |

The whole serial suite was not rerun after the final fixes: the final affected
checks cover their changed paths, while the two demonstrated baseline failures
remain reported. No assertion that the entire repository is green is made.

## Fresh review and fixes

The read-only whole-branch review of `219747c9` found four Important issues and no
Critical issues. Each was reproduced before fixing:

1. One replayed owner text `y` approved two queued requests. Shared durable
   control receipts now precede approval/cancel/pairing effects. Regression:
   `one replayed owner text answer cannot approve the next queued permission`.
   A replayed cancel cannot stop a later request, and an owner's `/cancel` takes
   priority over the pending-approval parser.
2. A configured ChatGPT Browser produced a misleading missing-provider error.
   Startup and agent lookup now give explicit API-model guidance before opening
   a channel connection. This is a deliberate API-only guard, not browser-channel
   support. Existing API-backed Telegram behavior remains covered by 12 cases.
3. Cached isolated agents retained an old client/model after settings changed.
   Provider/model/config/teammate/skill changes invalidate those caches; their
   histories restore independently. Active or queued channel work blocks provider
   changes; provider reconnect closes/reopens enabled channel connections.
   Regression covers a changed client/model and preserved conversation, plus the
   active-turn guard.
4. Daemon stop during Discord auth could start Slack afterward. The daemon now
   invalidates/joins host shutdown and checks stop before each startup await.
   Regression proves only Discord was started and Slack remains stopped.

Fixes were verified by the final 246/246 affected checks; no second independent
review was requested. The reviewer set aside external account/installer checks,
physical speech, approved conversation-key semantics, a fourth connector and
filesystem transactions. Ruling: these remain the explicit acceptance gaps and
scope limits above. The two baseline suite failures were independently reproduced
rather than silently set aside.
