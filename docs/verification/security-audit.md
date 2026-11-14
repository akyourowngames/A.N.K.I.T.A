# Final security and verification audit — 2026-11-10

Scope: PR #77 (`codex/context-subagent-fixes` against `ankita`), 186 changed
files. This is a local audit; no repository content was uploaded to a cloud
scanner.

## Static review

- No `eval`, dynamic code construction, `innerHTML`/`dangerouslySetInnerHTML`
  or shell-enabled process spawn was introduced.
- No real secret literals were found. The only matches are deliberate test
  fixtures such as `fixture-secret-do-not-persist`.
- No runtime dependency was added; the dependency diff is three patched
  versions (below).
- `git diff --check` passes.

## Dependency audit

`npm audit --omit=dev` initially reported three production advisories:

- **high**: `node-forge` 1.4.0 (used for phone-pairing certificate generation)
- **moderate**: `hono` and `@hono/node-server` (MCP HTTP gateway)

Patched to `node-forge` **1.4.3**, `hono` **4.13.18** and
`@hono/node-server` **1.19.19**. The high and one moderate advisory are gone.

One moderate `@hono/node-server` advisory remains (`serveStatic` path decoding).
No non-breaking fix exists in the parent `@modelcontextprotocol/node@2.1.1`
range (`^1.19.9`). The vulnerable `serveStatic` function is not used anywhere in
this repository; the gateway uses `toNodeHandler` plus localhost host/origin
validation. This is recorded as an accepted, unreachable advisory.

Development-only advisories (Vite, launch-editor) remain. They are not in the
packaged runtime and would require a `--force` dependency change; they were not
applied.

## Code review

- Desktop IPC is restricted to the application windows and each sender's main
  frame (`engine:invoke`). Assistant actions only run when their identifier is
  in `ASSISTANT_ACTIONS`.
- Phone pairing uses a 2048-bit RSA CA and leaf, SHA-256 signatures, an
  encrypted CA key via OS safe storage, expiring one-attempt codes, Host and
  Origin validation, no CORS/cookies and a request-size limit.
- Skill import uses fixed public origins, refuses redirects, bounds responses,
  requires a full commit and SHA-256, rejects links/support files, resolves the
  install root and creates the destination exclusively.
- Assistant task records use generated UUID identities, private file modes and
  bounded/redacted context.
- The phone client writes untrusted text with `textContent`, keeps its token in
  `sessionStorage`, sends it as a Bearer header and omits cookies.
- Browser context extraction excludes hidden controls and non-content elements,
  bounds DOM nodes and bytes, and labels references as untrusted.
- The new briefing action validates owner and schedule, creates a disabled
  draft, and the UI cannot auto-enable it.

## Verification

- Full serial repository run: **2,220 tests, 2,216 pass, 3 fail, 1 platform
  skip**. The three failures were merge-only test issues (two incomplete fake
  engines and tests still assuming chat was the default view instead of Today).
  They are fixed; the three files rerun **33/33**.
- Delegated gates: core assistant/skills/host **85/85**, desktop
  assistant/phone/voice **36/36**, phone-control **54/54**, voice/streaming
  **91/91**, isolated channel checkpoints **8/8**, model context **9/9**.
- Dependency-affected rerun after patching: phone pairing, MCP gateway, MCP
  manager, phone control and the fixed files **74/74**.
- `tsc --noEmit -p desktop/tsconfig.json` exit 0.
- `npm run desktop:build` exit 0; `npm run desktop:pack` exit 0.
- Live configured speech verification exit 0 (`firstChunkMs=491`, exact
  transcript, synthetic microphone, no speaker playback).

## Packaged application interaction

Launched `desktop/release/win-unpacked/Ankita.exe` with an isolated
`CONFIG_DIR` and user-data directory through Playwright's Electron driver:

- The packaged renderer loaded `index.html` from the app ASAR, title **Ankita**.
- Today rendered as the default view; the first-run GitHub onboarding modal was
  present.
- Clicked **Conversations**: the packaged app showed the Chief conversation,
  voice entrypoint, project picker, schedule and work-review controls.
- No renderer page errors were reported.
- Screenshots were captured in a temporary directory outside the repository.

## Remaining limits

- Physical microphone/headphone/speaker and Bluetooth audio were not exercised.
- Packaged-app onboarding/sign-in was not completed; interaction stayed on the
  local unauthenticated surfaces.
- Full original-goal semantic completion across multi-app work remains to be
  proven beyond receipt guards.
- The full serial suite was not rerun to completion after the final three test
  fixes and dependency patches; their affected files passed separately.
- No measured general real-model/phone speed or 25% call-saving claim.

**Confidence: 90/100.** +full serial run with the three failures identified and
fixed, +targeted reruns, +production dependency patches, +static/IPC/TLS/import
review, +packaged app launched and navigated, +live configured audio. −full
suite not rerun after the final fixes and dependency patches, −physical audio
and packaged sign-in untested, −one accepted unreachable moderate advisory,
−semantic-completion limit.
