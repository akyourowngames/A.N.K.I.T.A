# Everyday phone continuity — 2026-11-07

Implemented against the approved everyday-assistant spec and plan, without
commits, publication, new dependencies, or changes to the external native app.

## Reachable behavior

- Desktop Settings → Phone → Create pairing code now defaults to a phone-browser
  QR/link. The selector retains the native app's existing QR/link and v1 request.
- The same HTTPS listener serves a fixed HTML/CSS/ES-module allowlist at
  `/v1/ankita-companion/phone`. No request path becomes a filesystem path.
- After desktop owner approval, the phone shows recent assigned-conversation
  messages and saved work, including checklist, bounded receipts and selected
  context excerpts. Hidden/tool chat entries and arbitrary owner/thread selectors
  are excluded. Missing assignment is an actionable error.
- Selected text has named character/UTF-8 limits, a redacted server preview and a
  visible review checkbox. The server issues an expiring, device/owner/task-bound
  preview identity, consumed by one accepted request. Editing/removal invalidates
  the preview in the client. New requests without context have no new saved
  references; existing task context follows the original task on continuation.
- Review and continue routes through `assistant.resume` inside the normal phone
  run owner. Engine event/turn custody, tool approval, timeout, cancellation and
  revocation remain active. The server never accepts a caller-selected owner.
- The browser holds its token only in this tab's sessionStorage/in-memory state.
  Disconnect revokes it on the desktop; Forget clears local access. Stale
  responses cannot restore a forgotten connection. Reassignment cancels and
  removes old runs/approvals/previews before changing authority.

## Security boundaries

`desktop/electron/phone-pairing.mjs:559` validates Host against discovered
addresses/names, leaf-certificate SANs and the actual bound port. Browser Origin,
when present, must exactly match that served HTTPS origin. Arbitrary/null
origins, rebinding names, wrong ports and cross-site fetch metadata fail before
assets or pairing/auth operations. There is no wildcard CORS or cookie auth.
JSON/Bearer and one-time secret claim remain required on their existing paths.
Static responses disable framing, referrers, inline/remote scripts, camera,
microphone and geolocation. Browser DOM uses textContent for untrusted messages.

Production TLS verification was not disabled. The desktop still exports only
its public CA and fingerprint. Install/trust that saved public certificate on
the phone and compare the desktop fingerprint; do not bypass a browser warning.

Implementation pointers: fixed assets at `phone-pairing.mjs:57`; owner/task
projection at `:581`; preview binding at `:619`; common run custody at `:705`;
assigned history/tasks at `:837`; preview and continuation routes at `:852` and
`:871`. Client lifecycle generation at `desktop/phone-client/app.mjs:11` rejects
responses from an earlier connection.

## RED → GREEN evidence

- New endpoint tests first failed with phone page `401 !== 200` and history
  `404 !== 200`. They now pass alongside the original native protocol tests.
- Reassignment regression first returned old run events (`200 !== 404`). It now
  returns 404 for both old events and approvals, and clears the approval queue.
- Actual browser/Agent path exposed phone tasks incorrectly marked desktop
  (`'desktop' !== 'phone'`). Root fixed per-request surface propagation in the
  engine/task boundary and added its own core regression.
- A delayed successful pairing response reconnected a forgotten tab
  (`true !== false`). The client connection-generation guard now prevents it.
- Settings browser/app selector initially failed accessible-name lookup. An
  explicit label corrected keyboard/screen-reader naming. The older settings
  test also needed to discover Phone by keyboard instead of assuming a fixed
  number of navigation tabs after unrelated navigation additions.
- A long task initially exceeded a phone-sized response. Each task now has a
  shared 12,000-byte JSON-text excerpt budget and 20-item collection bounds, with
  a visible notice when additional saved details remain on the desktop.

## Executed checks

`rtk proxy node --test --test-concurrency=1 test/desktop/phone-pairing.test.mjs test/desktop/phone-browser.test.mjs`

Result: **12 tests, 12 pass, 0 fail** (13,242.2416 ms). This executes real HTTPS
requests with the generated CA and `rejectUnauthorized:true`, pairing approval,
token claim, native v1 sends, history/tasks isolation, wrong/absent TLS trust,
malicious origins/Host, fixed assets/traversal refusal, context bounds/single use,
assigned run approvals/cancellation/revocation/restart/reassignment and bounded
saved-task details. The final independent typecheck/module syntax/diff checks
also exited 0 after the response-budget change.

The browser test uses the real DesktopEngine, Agent, attachment processing,
task store and ToolHost. Only provider generation is a fixture at `streamTurn`;
approved writes really create isolated temporary files. Browser traces:

```text
PHONE_BROWSER_PAIR_HISTORY_OK: desktop approval, assigned history, 390px layout, no localStorage key
PHONE_BROWSER_CONTEXT_APPROVAL_OK: reviewed one-request text reaches real Agent, write waits for approval, saved receipt and context
PHONE_BROWSER_RESUME_OK: tab reload, original task/goal/context, fresh reviewed context, ordinary approval and real file receipt
PHONE_BROWSER_REVOKE_OK: actual cancellation, desktop revoke clears tab key, separate browser context has no access, phone disconnect revokes
```

The disposable browser profile uses a **test-only generated-leaf SPKI pin**,
with `ignoreHTTPSErrors:false`; it does not install a root into the user's OS.
Independent Node requests validate the actual CA chain and hostname. Delayed
claim interception also proxies through CA-verified Node HTTPS, not an insecure
fetch. This is not physical-device certificate-installation evidence.

`rtk proxy node scripts/verify-desktop-phone-ui.mjs` passed with
`NARROW_INVITE_OK`, `DEVICE_STATES_OK`, `EXPIRED_INVITE_OK`, `WIDE_INVITE_OK`,
`OFFLINE_STATE_OK`, `PHONE_SETTINGS_UI_OK`. Browser/native QR choices, responsive
layout, expiry/approval/revoke/offline states and keyboard discovery ran in the
actual React renderer with fixture IPC. Vite initially could not read its config
under the sandbox; the same check passed with explicit approved escalation.
Browser tests were coordinated serially with the root/voice Vite owners.

`rtk proxy node node_modules/typescript/bin/tsc --noEmit -p desktop/tsconfig.json`
and `rtk git diff --check` exited 0. New service/client modules pass `node --check`.
The 390px browser screenshot was visually reviewed: readable wrapping, visible
focus/control bounds and explicit context review, without horizontal overflow.
Optional screenshots remain outside the repository in the temporary directory.

## Rulings and remaining limits

- Ruling: additive same-listener browser routes preserve the native v1 schema,
  rather than changing its protocol version. Cost if wrong: older native clients
  do not expose the new browser-only screens, but their existing request still
  executes through the tested legacy path.
- Ruling: selected-context previews are short-lived in-memory capabilities;
  accepted requests persist bounded references in their existing task. Cost if
  wrong: an unsent preview must be reviewed again after expiry/restart.
- Ruling: test browser trust uses a disposable exact-leaf pin instead of changing
  the user's trust store. Cost: physical phone trust installation remains an
  explicit acceptance gap.
- Root integration completed: invitation `browserUrl/browserQr` wire fields,
  optional snapshot browserUrl, packaged phone-client include, resume attachments
  with bounded context merge, and per-request phone source attribution.
- Not exercised: a physical Android/iOS phone, its certificate-installation UI,
  real LAN/firewall reachability, a newly packaged desktop/ASAR, or a configured
  external model through the phone browser. These tests use local HTTPS and real
  runtime execution with provider responses supplied by fixtures.
- No full suite was run for this scoped change; the focused phone suite, real
  renderer path and typecheck cover its changed contracts. Root owns final
  whole-feature validation/build and the fresh final review.
- Literal review: routes/limits/polling/storage identifiers are named in the
  shared phone contract; UUID matching, static asset allowlist, security policy,
  default HTTPS port and errors are named service constants. Test addresses,
  model names, temporary paths and generated pins stay in test/script fixtures.
  UI copy, HTML attributes, CSS design values and standard HTTP statuses are
  intrinsic to their protocol/presentation roles.

**Confidence: 88/100.** Base 50 for the preserved native protocol; +20 real
HTTPS/security checks; +15 real browser/Agent/tool approval/context/resume
journey; +10 regression RED→GREEN evidence; +5 renderer and typecheck.
−4 physical phone/trust/firewall not tested; −3 new packaged desktop not tested;
−3 external model fixture instead of configured provider; −2 full-suite/fresh
whole-feature review owned by root. The next +5 needs physical-phone trusted-TLS
and packaged-desktop acceptance.
