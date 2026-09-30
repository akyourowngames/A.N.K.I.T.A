# Browser / Playwright / Chrome — findings and verification record

Date: 2026-09-26. Scope: `copilot-chat` — `tools/browser/` (`browser.mjs`, `playwright.mjs`,
`chrome.mjs`, `session.mjs`, `pending.mjs`), `tools/filesystem/read-file.mjs`,
`tools/shared/_shared.mjs`, `desktop/electron/engine.mjs`,
`desktop/electron/browser-plugins.mjs`. This record preserves the original live
failure traces and documents subsequent fixes. Original code paths, line numbers,
environment paths, and proposals below describe the initial investigation, not
the current implementation. The latest verification is in Part K.

## Part K — model-selected credentials and Telegram upgrade (2026-09-27)

The user's Cirro screenshot reproduced a real defect: the old login detector
rejected its honeypot plus input-based submit control. Read-only live trace:
`An unambiguous username and sign-in button are required`. The first diagnostic
snapshot was truncated, not missing controls. Its full output includes Email,
Password and Sign In refs; preparation now reports `accepted:true` and
`formDetection:false`. No Cirro account was submitted or fabricated as a test.

`browser login` without fields can request the secure dialog independently of
any form detection. It returns private credential availability and a fresh
snapshot. The model chooses `credential_fields` refs mapped to username/password
slots and optional `submit_ref`; sequential username-first calls work on the
same origin/tab. Actual nodes, password input type, origin and form submission
targets are checked before filling. GET password submission remains prevented,
including a subsequent model click. Each call returns `filled` and page evidence;
the model verifies sign-in and continues the original task. No button-name or
logout-name heuristic gates the new runtime flow. Historical direct adapter
login tests remain, but those helpers are not called by desktop login.

Unsaved passwords remain main-process only, scoped to thread/origin/tab/page.
Consumption immediately clears the transient record even if a later click or
snapshot fails. Stop, turn end and expiry also clear it. Malformed model fields
are rejected without breaking display/history. Secure cards parse the receipt
through Agent's read-back and repeated-call notices. Snapshot input types are
visible, while password values remain hidden after a site toggles input type.

Telegram desktop and CLI paths now keep typing active, throttle interim tool
labels, acknowledge received/completed/failed states and send up to five
current-turn artifacts after final text. Reads enforce generated/downloaded
folders, canonical containment, MIME and 15 MiB limits; photo failure falls back
to document upload. `/cancel` bypasses task queues and pending approvals.
Incoming photos/docs/videos receive a deferred-support nudge. Voice stays
supported. CLI cancellation during typing/transcription cannot start the model;
desktop artifact receipts are captured from owned tool events, so another chat
sharing the teammate cannot contribute its files during final delivery.

The original plan's reaction emoji are unsupported by Telegram. The implemented
received/completed/failed reactions are 👀/👍/👎, from the
[official supported list](https://core.telegram.org/bots/api#reactiontypeemoji).

### Executed evidence

```text
New vault request/control tests: RED -> GREEN
Fresh-context review: 4 Important findings -> each regression RED -> GREEN
Combined affected gate: 74/74 pass, 0 fail, 0 skip; 30440.6514 ms
desktop:build: exit 0; 322 modules; 9.61 s; existing bundle-size advisory
PACKAGED_CHROME_RED_GREEN: shipped bridge -> 30 tools; empty PATH/npm cache
PACKAGED_VAULT_COLD_WARM_OK / CANCEL_STOP_OK / RETRY_TAKEOVER_OK
PACKAGED_MANAGED_BROWSER_ROUTING_OK / EMPTY_PAGE_OK
PACKAGED_PUBLIC_LOGIN_OK: real public practice site -> secure dialog
  -> model-selected refs -> Submit -> visible Log out -> original task resumes
PACKAGED_SECRET_BOUNDARY_OK: no password in events/model/config; no renderer errors
TELEGRAM_UPGRADE_LIVE_OK: 4 chat actions, 2 progress replies, 4 reactions, 1 file
  Real configured Bot API; scripted desktop engine/CLI agent; approved test chat
  CLI cancel sent stopped reply and suppressed the partial answer
BROWSER_AUTOMATION_LIVE_OK: both real browser backends; reconnect/fallback/actions
  Isolated: 9.2 FPS / 15 frames; Stop 3 ms; queue release 123 ms
  Chrome local: 4.8 FPS / 15 frames; Stop 20 ms; queue release 2251 ms
Final full suite: exit 0; 753 tests; 752 pass, 0 fail, 1 skip; 293065.7794 ms
```

Packaged artifacts and executable are in
`C:\Users\anime\AppData\Local\Temp\ankita-packaged-vault-k2IhF1` (executable under
`package\win-unpacked`; keep that entire folder together). The public-site
success screenshot was visually inspected. This is an unsigned directory build,
not an installed/published update. Primary test account source:
[Practice Test Automation](https://practicetestautomation.com/practice-test-login/).

Intermediate checks caught verifier-only receipt parsing errors caused by Agent
advisories, and the affected screenshot test caught an oversized browser schema.
Receipt parsing now handles those notices; compact schema descriptions preserve
screenshot pixels in the default context window. These failures were fixed and
the same gates rerun. Detailed rulings/review evidence are in
[the ledger](plans/vault-model-selection-telegram-implementation.md).

Limits: model decisions in the packaged verification are scripted; no actual
Cirro/X login, CAPTCHA completion, personal Chrome-session vault flow, native
macOS/Linux vault, installer/auto-update or live LLM decision is claimed. Vault
filling remains desktop Playwright only; approved Chrome can use its existing
session. Telegram transport was live, while inbound user polling was exercised
with fixtures rather than modifying the real bot cursor. Incoming media and
reaction handling remain deferred per the plan.
Group topics and real voice transcription/TTS were not live-tested; desktop
cancellation during pre-turn voice transcription remains uncovered.

## Part J — public login controls, blank navigation and managed routing (2026-09-27)

The user's public-site screenshots revealed gaps that Part I's controlled forms
did not cover. Its passing fixture checks did **not** establish that arbitrary
real-world sign-in screens worked.

### Live reproduction and root causes

```text
Practice Test Automation: forms=0, passwords=1, button=Submit, button.form=false
Before: prepareLogin -> Login form must submit to this origin
After: same public page -> prepareLogin accepted=true
X background browser: HTTP 403, response body=0 bytes, no controls/scripts
Before: Opened tab ...; live session Ready with a white screenshot
After: Navigation refused: HTTP 403; Needs attention; no white frame
Normal headed Chromium probe: HTTP 200; X username/Continue screen rendered
Discovery before: find_tools(browser) advertised external browser_navigate/snapshot
Discovery after: desktop schemas/prompt/results contain only managed browser tools
```

- A JavaScript login group need not be a native `<form>`. The detector binds the
  smallest local group containing exactly one username, password and recognized
  sign-in/Submit button. Actual element/container handles, exact origin, native
  form/submitter action checks and GET prevention still protect the fill path.
- A blank SPA is observed for visible content before the first snapshot. HTTP
  errors and pages that remain empty fail navigation; subsequent snapshot/read
  and preview calls cannot silently turn a refusal into Ready. A later actual
  render can recover. The live pane discards an old frame for a page-load failure.
- Desktop filters external Playwright/Chrome tools from MCP summaries, prompts,
  discovery and schemas, and blocks old calls before MCP execution. It activates
  the built-in browser for recovery; enabled backend selection remains in the
  session manager. Blocked calls no longer emit an external live-stage state.
  Non-browser MCP integrations and standalone CLI MCP behavior are preserved.
- Public packaged verification also exposed a late-preview race: an old tab's
  capture could restore a frame after a newer page-load error. Session generations
  now discard captures/results crossing operations or tab changes. A deterministic
  regression reproduced the old frame overwriting the error, then passed.
  MCP-name classification uses the existing protocol parser, including tool names
  containing `__`; those cannot bypass the managed-browser execution guard.

### Regression and live verification

Failed navigation also returns without awaiting another tab-metadata request.
A Chrome stub with a never-resolving tab list reproduced the blocked queue;
the same regression now returns the HTTP failure and settles immediately.

```text
New readiness/login regressions: RED 0/5 -> GREEN 5/5
External discovery regression: RED (advertised raw tools) -> GREEN
Agent/discovery/lifecycle/readiness gate: 47/47, 0 failures (includes preview race)
Packaged app: old MCP call refused -> built-in login -> original task resumes
Packaged HTTP 403 and empty HTTP 200: load-error panel, no white image or Ready
Fresh packaged app: BROWSER_VAULT_PACKAGED_OK
Public site: native dialog -> Submit -> visible Log out -> original task resumes
Built-in routing: old external call refused, no external live-stage events
Secret boundary: no fixture password in model/events/persistence; no renderer errors
Both real backends: BROWSER_AUTOMATION_LIVE_OK
  Playwright preview 8.3 FPS; 15 distinct frames; Stop returned 2 ms
  Chrome preview 3.9 FPS; 15 distinct frames; Stop returned 17 ms
  Reconnect and disabled-Chrome fallback passed
Final isolated full suite: 737 tests; 736 pass / 0 fail / 1 skip
  exit 0; duration 200519.4613 ms
```

The first full run reached 733 pass / 1 fail / 1 skip; the sole failure was
Windows `EPERM` deleting a closed disposable Chromium profile in
`test/tools/browser.test.mjs`. The same test passed alone. Cleanup now has bounded
retries and validates its temporary-directory parent. The cleanup rerun completed
734 pass / 0 fail / 1 skip. A later 737-test run overlapped packaged/browser
verification and hit two unchanged job-timing assertions (running vs done,
empty output before the job had started). No job implementation was changed;
The final full suite ran without those competing browser checks and passed both
previously failing job assertions; 736 passed, zero failed and one skipped.

The latest executable/ASAR is
`C:\Users\anime\AppData\Local\Temp\ankita-packaged-vault-j9bwsV\package\win-unpacked`.
It contains the complete runtime fixes above; keep the entire folder with the
executable. Artifacts in its parent include `public-login-success.png`,
`denied-page.png`, `blank-page.png` and the themed native dialog screenshots.
The real public test used the [site's published dummy account](https://practicetestautomation.com/practice-test-login/),
with saving disabled. A public redirect is observed through the periodically
refreshed live tab list; no assertion assumes the first cached tick is current.

`desktop:build` exited 0 (322 modules, 5.39s; existing bundle-size advisory).
Literal review: render timeout and HTTP boundary are named constants; protocol
parser, site policy and notice classification are shared helpers. DOM attributes,
ARIA names, protocol keys and UI text are interface invariants. No dependency
change, publication, installed upgrade or personal browser profile modification
is part of this follow-up.

Remaining coverage: X still refuses background Chromium and its username-first
flow needs manual interaction/approved local Chrome. No X account, CAPTCHA, real
LLM, native macOS/Linux, installer/auto-update or personal Chrome-session sign-in
is claimed here. External site acceptance cannot be guaranteed by a local test.

## Part I — packaged Chrome bridge and credential vault (2026-09-27)

The two plans in `docs/plans/` are implemented. Chrome MCP is now a pinned
production dependency and its self-contained build is unpacked beside ASAR.
Electron-owned MCP children use `ELECTRON_RUN_AS_NODE=1`; no npm/npx, system Node
or pre-existing cache is needed. The exact command still requires approval;
enabling records the plugin choice and connections start on demand.

Desktop isolated Playwright `browser login` now has a native themed Secure store
card/dialog, main-process async OS-encrypted exact-origin vault, metadata-only
Plugins management, cancellation, explicit retries, takeover and verified task
continuation. CLI/channels/Chrome cannot read or fill the vault. Native GET
submission, submitter overrides, cross-origin actions, signup/ambiguous forms,
disabled Playwright fallback and changed site policy are guarded. A visible
logout/sign-out control with no visible password input is required for success.
No password-bearing snapshot/error is returned from the login operation.

### Reproduced and corrected

```text
Baseline: 714 total / 713 pass / 0 fail / 1 skip
Chrome focused: 7/7 pass after RED npx-command/missing-runtime-helper tests
Vault: 3/3 pass after RED missing implementation
Login service: 3/3 pass after RED missing implementation
Final focused browser/login/context gates: 46/46 pass / 0 fail / 0 skip
Actual packaged legacy launch: exit=0, no initialize
Bundled packaged bridge: 1.10.1 -> 30 tools -> CDP page/snapshot
  PATH empty and npm cache empty
Both backends: BROWSER_AUTOMATION_LIVE_OK
  Playwright 9.1 FPS / Chrome 6.5 FPS; 15 distinct frames each
  Stop returned 3 / 13 ms; Chrome reconnect and disabled fallback passed
npm audit --omit=dev: 0 vulnerabilities
```

The fresh whole-change review found and corrected five issues with RED/GREEN
regressions. Independent live verification confirmed the two security fixes:

```text
Before submitter-method fix:
{"result":true,"passwordInServerQuery":true,"passwordInTabUrl":true}
After:
{"overrideLoginResult":false,"passwordInServerQuery":false,"passwordInTabUrl":false}
Before policy refresh fix:
{"blockedSiteLoginSucceeded":true,"submits":1}
After:
{"blockedAtPrepare":true,"blockedBeforeFillWithFreshPolicy":true,"submits":0,"passwordFilled":false}
Remaining review fixes: enabled-Playwright requirement, visible plain-text
  card errors/cancellation, sanitized save failure with explicit one-time retry.
Reviewer focused gates: 8/8 pass / 0 fail / 0 skip
```

The packaged verifier uses the actual executable, real local HTTP/SSE and IPC,
real Chromium and real Windows async OS encryption. It checks cold/warm login,
three appearances, autofocus/focus trap/eye toggle, metadata removal, Escape,
Stop, wrong-password retry, extra verification/takeover/hand-back, and no password
in model requests/public events/persisted app data. Final gates on settled source:

```text
npm test: 729 total / 728 pass / 0 fail / 1 skip
duration_ms: 232917.7214 (skip: POSIX executable-permission test on Windows)
npm run desktop:build: exit 0; 322 modules; 6.37s
git diff --check: exit 0

PACKAGED_CHROME_RED_GREEN: legacy exit=0, no initialize; bundled 1.10.1
  -> 30 tools -> CDP page/snapshot; PATH empty, npm cache empty
PACKAGED_VAULT_COLD_WARM_OK: real async OS encryption; secure dialog
  -> save -> one fill/submit -> confirmed sign-in -> original task resumes
PACKAGED_VAULT_MANAGEMENT_OK: Plugins metadata row and Remove via real IPC
PACKAGED_VAULT_CANCEL_STOP_OK: Escape/Stop resolve without fill or save
PACKAGED_VAULT_RETRY_TAKEOVER_OK: explicit Retry; verification/hand-back
PACKAGED_VAULT_ERRORS_OK: visible local denial; corrupt-file one-time retry
PACKAGED_SECRET_BOUNDARY_OK: no passwords in model/events/persisted app data;
  no renderer errors
BROWSER_VAULT_PACKAGED_OK

PACKAGED_RUNTIME_OK / PACKAGED_THEME_OK / PACKAGED_AGENT_HTTP_OK:
  actual executable/app.asar; mono/slate/graphite; 8 real HTTP/SSE model rounds
PACKAGED_SIDEBAR_RECOVERY_OK / PACKAGED_STAGE_OK / PACKAGED_BROWSER_LIVE_OK
PACKAGED_COMMAND_OK / PACKAGED_WORKER_CRASH_OK / PACKAGED_CHROMIUM_SETUP_OK
PACKAGED_DESKTOP_VERIFICATION_OK
```

Fresh tested app directory:
`C:\Users\anime\AppData\Local\Temp\ankita-packaged-vault-rlJWyX\package\win-unpacked`.
Secure-dialog screenshots and disposable profiles/config are in
`C:\Users\anime\AppData\Local\Temp\ankita-packaged-vault-rlJWyX`.
The broader verifier reused this exact build; its screenshots are in
`C:\Users\anime\AppData\Local\Temp\ankita-packaged-browser-5acjnD\screenshots`.
The build is local and unsigned; these traces do not assert a published release.

### Coverage limits

- Windows unpacked executable/ASAR and OS encryption are exercised; NSIS install,
  auto-update deployment, and signed macOS/Linux builds are not exercised here.
- Linux unavailable/basic_text and crypto/corrupt failures have stub-driven tests;
  native Linux secret-store and macOS Keychain prompts remain untested.
- Chrome private CDP is live; active personal-session permission prompts remain
  manual. Chrome still needs an installed browser; Playwright's Chromium binary
  remains a separate download. The MCP bridge itself is bundled.
- Model decisions are scripted and sites are disposable forms, not a live LLM,
  airline/Google login or real account. Sequential login screens/unsupported
  widgets and avatar-only evidence require manual interaction.
- Passwords necessarily exist briefly in dialog DOM and main-process callbacks;
  owned references/buffers are cleared, without promising JavaScript memory erasure.

See [the implementation ledger](plans/browser-packaged-vault-implementation.md)
for source-plan rulings and test commands.

## Part H — 2.4.3 release preflight

**Recorded 2026-09-26.** Package and lockfile versions are 2.4.3, with detailed
versioned changelogs and explicit remaining coverage limits. Runtime metadata
now declares Node 20+, matching the installed Playwright dependency; desktop
build prerequisites document Node 22.12+. These declarations are not evidence
of a separate Node 20 execution. Release CI uses Node 22.

```text
Initial local release gate: 713 total / 712 pass / 0 fail / 1 skip
duration_ms: 176987.0717
npm run desktop:build: exit 0; 319 modules; 6.28s
BROWSER_SIDEBAR_ERROR_OK: stale refs, navigation and action errors keep pixels/control; no page code or call logs
git diff --cached --check: exit 0
```

The rendered check used the built 2.4.3 renderer and stubbed IPC in real
Chromium. Its initialize fixture now reads the version from package.json so
release version bumps cannot produce a spurious compatibility banner. Part G
records the actual packaged executable and both backend live checks.

The first preflight reported **711 pass / 1 fail / 1 skip**: the process-kill
approval fixture refused `Cannot verify process PID 19444`. Live CIM inspection
identified that PID as an older Edge process, created at
`2026-09-26T13:19:58.288Z`, with parent PID 25764. A reused parent PID is the
inferred cause; the fixture root was already cleaned up, so its identity was
not captured afterward. The process safety guard was left unchanged. The
individual regression passed **1/1**, process/tree/worker suites passed **20/20**,
and the complete repeated gate passed as shown above. Mixed line endings in
the new worker runner were normalized to LF without a logic change.

A user-installed 2.4.3 upgrade remains uncovered. Part G and the release notes
retain external-site, provider, configured Chrome MCP, download and non-Windows
coverage limits. Publication checks are recorded below.

### Clean release runner exposed a command cleanup ordering bug

GitHub run `36258602272` completed **672 pass / 0 fail / 18 cancelled / 23
skipped**. The first cancelled test was the resolved Windows executable fixture;
its cleanup reported `Promise resolution is still pending but the event loop
has already resolved`. Native pipe close released the launch worker's reference
while a Stop request still awaited its termination reply. The new real-process
regression reproduced this locally, even with the local event loop remaining
alive long enough to receive the reply:

```text
Before: launcher Stop: closed=true, pending at unref=1; 0 pass / 1 fail
After: launcher Stop: closed=true, pending at unref=0; 1 pass / 0 fail
```

`tools/shared/_job-launcher.mjs` now releases the worker only when native close
and all pending termination acknowledgements have completed, in either order.
The regression runs a real native command and records the pending requests at
worker release. It preserves all process identity guards and existing deadlines.
The clean runner's skips reflect absent Chromium and optional Python packages;
local installed-browser coverage is recorded separately in Part G.

```text
Affected job/process/tool suites: 30 total / 30 pass / 0 fail / 0 cancelled
Final npm test: 714 total / 713 pass / 0 fail / 0 cancelled / 1 skip
duration_ms: 172485.1894
```

### Published release checks

The corrected [GitHub Windows release run](https://github.com/akyourowngames/A.N.K.I.T.A/actions/runs/36259156384)
succeeded using Node 22 and a clean `npm ci`. Its test output was **714 total /
691 pass / 0 fail / 0 cancelled / 23 skipped**, `duration_ms: 59223.27`, including
`launcher Stop: closed=true, pending at unref=0`. The optional Chromium/Python
skips are not reported as live coverage; local coverage is recorded above.

The stable [2.4.3 release](https://github.com/akyourowngames/A.N.K.I.T.A/releases/tag/v2.4.3)
is public and not a draft/prerelease. Its tag points to
`30b960d80c55dcf7f56abd7eee319edbc9525848`. The installer, portable executable,
blockmap and update manifest were downloaded from the published release.

```text
Ankita-2.4.3-setup-x64.exe: 114766818 bytes; GitHub SHA-256 and updater SHA-512 match
Ankita-2.4.3-portable-x64.exe: 114548135 bytes; GitHub SHA-256 matches
Ankita-2.4.3-setup-x64.exe.blockmap: 120501 bytes; GitHub SHA-256 matches
latest.yml: 349 bytes; GitHub SHA-256 matches
RELEASE_VERIFIED: stable v2.4.3; 4/4 assets; detailed notes match; manifest version, size and checksums match
```

The release body includes the full versioned changelog with documentation links
rooted at the release tag. The checks confirm published downloads and manifest
integrity, not an installed auto-upgrade or live provider/site completion.

## Part G — live-sidebar diagnostics, packaged verification, and command startup

**Implemented 2026-09-26.** This continuation prioritizes the user's screenshots
of raw Playwright call logs and a fresh snapshot leaking into the live pane.
Part F remains historical; the following coverage supersedes its unverified
packaged UI and advanced-interaction entries.

### Sidebar error reproduction and fix

Three new manager regressions initially reported **0 pass / 3 fail**, all with
`'error' !== 'ready'`: a recovered ref on each backend and a failed navigation.
The old catch handler copied the full error, including the recovery snapshot,
into `view.step` and marked every failure disconnected. The stage then rendered
that string as “Browser unavailable / Connection required” and disabled control.

`src/integrations/browser-errors.mjs:16` now creates fixed notices for reference,
navigation, connection, startup, preview and action failures. In
`tools/browser/session.mjs:94`, recoverable errors preserve the adapter, recovered
refs and a usable session; only dead connections/cancellation tear it down.
Snapshots and complete diagnostics remain in tool results for the assistant.
`desktop/renderer/src/components/BrowserStage.tsx:46` separates notices from
connection failures, retains good frames, continues frequent polling, and leaves
Take control enabled for page/action errors. A later successful action clears
the notice; preview recovery also clears its transient notice.

```text
Before: 0 pass / 3 fail — stale refs and page.goto both left status=error
After: 3 pass / 0 fail
Browser lifecycle + contract suites: 34 tests / 34 pass / 0 fail / 0 skip
BROWSER_SIDEBAR_ERROR_OK: stale refs, navigation and action errors keep pixels/control; no page code or call logs
```

The UI check used the built renderer with stubbed IPC, injected stale refs,
HTML/page-code markers, refs, ANSI fragments and navigation/click call logs.
It asserted retained pixels, enabled control, no leaked text, no reconnect
label, and functional Stop. The actual packaged check below additionally
exercised real Playwright recovery through the agent and IPC.

### Air India read-only investigation — remaining external failure

`scripts/probe-browser-navigation.mjs` accepts caller-supplied URLs and compares
read-only navigation in disposable profiles. No booking or personal data was
used. The exact supplied URL was
`https://www.airindia.com/in/en/book-flights/booking`:

```text
adapter: page.goto: net::ERR_HTTP2_PROTOCOL_ERROR
HTTP/1 (--disable-http2): Timeout 20000ms exceeded
full headless Chromium: net::ERR_HTTP2_PROTOCOL_ERROR
visible Chromium: status=404; title="404 - Page Not Found | Air India"
```

This does **not** establish a working booking URL or solve the site's background
browser rejection. No blanket HTTP/2 flag or automatic interaction replay was
added: the candidate flag failed this same repro. The short sidebar notice is
fixed; the network failure still remains in tool diagnostics. The transport
probe follows Chromium's [HTTP/2 switch definition](https://chromium.googlesource.com/chromium/src/+/8f718e9a/components/network_session_configurator/switches.cc)
and compares the background/visible behavior reported in the upstream
[Playwright issue](https://github.com/microsoft/playwright/issues/36001).
The site response and mode comparison above are local execution evidence,
not an inference that every HTTP/2 error has the same cause.

### Additional fixes earned during the confidence follow-up

- Real Chrome typing rejected `includeSnapshot`, and a key aimed at Alpha fired
  Beta's handler because Beta retained focus. Chrome now sends only supported
  typing arguments, explicitly focuses the registered UID without clicking,
  and refuses a key when focus is not confirmed. Three regressions went from
  **0/3** to **3/3**; real read-back confirms Alpha for both backends.
- Real runs cover native select/checkbox form batches, typing at the caret,
  ref-targeted Enter, hover and drag, plus earlier open/fill/click/read/capture,
  tab selection, reconnect, disabled-backend fallback and Stop. Cached Chrome
  MCP **1.8.0** was used; configured **1.10.1** remains untested.
- Cold Windows CreateProcess blocked the owner event loop. Shell discovery,
  native launch and tree work now run in a branded worker with acknowledged
  stdin/output and backpressure. PowerShell 7 selection remains intact.
  Two cold live samples returned in **119.7042 / 118.5902 ms**, heartbeat
  **6.8063 / 7.3692 ms**, while native first output still took
  **4353.7632 / 3573.9868 ms**. Startup timing assertions were not weakened.
- Input waits for launcher readiness before starting the existing native-write
  deadline. Blocked input, cancellation before readiness, EOF/output draining,
  shell spawn failure, inherited pipes and unrelated-worker import are covered.
- A terminated worker previously reported `job.done=true, native alive=true`.
  After identity-checked cleanup, the same repro reports
  **`job.done=true, native alive=false`**. Missing/changed identities refuse
  cleanup. Restricted process inspection failed; these two focused tests passed
  after rerunning with process permissions. Ordinary affected process suites
  previously passed **29/29** before adding the two crash regressions.

### Actual packaged app evidence

`scripts/verify-browser-desktop.mjs --keep-artifacts` built and launched the
actual Windows executable with `app.asar` and isolated configuration/user data.
The installed Electron/dependencies were used; no package was downloaded.

```text
PACKAGED_RUNTIME_OK: actual executable, app.asar, isolated config/user-data; ready=true, windows=1
PACKAGED_THEME_OK: mono, slate, graphite update real browser plugin cards
PACKAGED_AGENT_HTTP_OK: 8 actual HTTP/SSE model rounds; stale-ref recovery, form submitted/read back; PNG pixels serialized
PACKAGED_SIDEBAR_RECOVERY_OK: real stale-ref tool result keeps live pixels and control; snapshot/code excluded from sidebar
PACKAGED_STAGE_OK: live image, automatic sidebar collapse, Take control/Hand back, Stop
PACKAGED_BROWSER_LIVE_OK: shipped open -> fill_form -> click -> confirmed read -> screenshot
PACKAGED_COMMAND_OK: shipped launcher preserves stdin/EOF, output and shell exit code 7
PACKAGED_WORKER_CRASH_OK: failed launcher cleans its identity-checked shell and owned child
PACKAGED_CHROMIUM_SETUP_OK: shipped Playwright install --dry-run resolves its browser/cache paths (no download)
PACKAGED_DESKTOP_VERIFICATION_OK
```

Screenshots, including `browser-recovered-ref.png`, are retained under
`C:\Users\anime\AppData\Local\Temp\ankita-packaged-browser-yj5wH1\screenshots`.
The recovered pane was visually inspected: page pixels and control remain,
with a short notice and app theme colors. Model decisions are scripted; actual
HTTP/SSE, agent tool execution, browser, IPC and image serialization are real.

The current desktop build passed TypeScript and Vite: **319 modules**, **7.03 s**;
the existing chunk advisory remains (**531.09 kB**). The sandbox blocked esbuild
directory access; the same command passed after rerunning with build permissions.
Tracked diff whitespace checking passed. New notice strings are fixed UI copy,
and error regexes name diagnostic families; operational limits are constants,
protocol identifiers retain their API spellings, and fixture URLs/data remain
in tests/scripts. Profiles, executable paths and listening ports are discovered.

### Final project and browser gates

```text
rtk proxy npm test
tests 713; pass 712; fail 0; cancelled 0; skipped 1
duration_ms 192812.9434

rtk proxy node scripts/verify-browser-automation.mjs
Live Chrome MCP version=1.8.0; configured=1.10.1; cached executable only
isolated: recovered-ref view remains ready with pixels; no snapshot/code in sidebar state
isolated: preview 9.2 FPS; 15 distinct frames; screenshot=10662 bytes
isolated: native select/checkbox batch, typing, ref-targeted key, hover and drag confirmed
isolated: Stop returned in 1 ms; queue released in 122 ms
local: recovered-ref view remains ready with pixels; no snapshot/code in sidebar state
local: preview 6.7 FPS; 15 distinct frames; screenshot=72791 bytes
local: native select/checkbox batch, typing, ref-targeted key, hover and drag confirmed
local: Stop returned in 24 ms; queue released in 1098 ms
local: reconnect on demand after transport disconnect
auto: disabled Chrome falls back to enabled Playwright
BROWSER_AUTOMATION_LIVE_OK
```

The skip is the existing POSIX executable-permission fixture on Windows.
The original startup and empty-job-output failures are now green without
weakening their deadlines. This supersedes Part F's failed full gate.

### Residual coverage

- Configured Chrome MCP 1.10.1, cold package installation and personal-session
  Chrome permission dialogs remain uncovered. The required Sonatype pre-install
  tool is unavailable, so no unchecked dependency was installed.
- The Chromium installer was exercised with `--dry-run`; an actual download
  and missing-cache packaged setup remain unverified.
- No live LLM/vision provider or real airline/Google Flights transaction was
  exercised. The supplied Air India URL's background error and visible 404
  remain; other site challenges, payment and booking confirmation are unknown.
- Closed shadow roots, rare cross-origin frame navigation, custom Chrome widget
  filling and Chrome scrolling remain uncovered/limited. Native UID errors
  after validation remain bounded errors rather than automatically replayed
  mutations. Partial form work is not rolled back.
- Windows was the packaged/process platform tested. POSIX/macOS/Linux packaged
  paths remain unverified. A worker dying before its native identity is captured
  cannot be safely cleaned up by guessing its PID; the error reports refusal.
  Descendants behind an already vanished intermediary remain a tracking limit.
- Site latency and screenshot capture cost can still lower refresh rate;
  measured FPS is a local sample, not a display-refresh guarantee.

**Confidence: 90/100 for the implemented changes.** Ledger: +35 full suite,
+20 both real browser backends, +20 packaged agent/IPC/UI round trip,
+15 red-to-green regressions and process crash checks, +10 build/docs/literal
review; −3 configured Chrome version/cold setup/personal attachment, −3 live
provider and real-site completion (including the Air India failures), −2 actual
Chromium download and non-Windows packaging/process paths, −2 remaining frame,
widget and early-crash/vanished-intermediary branches. These deductions cover
the residual paths above. The next +5 requires the configured Chrome setup and
personal attachment path plus a real provider task with confirmed site results;
it cannot be earned by changing the score alone.


## Part F — stale refs, wasted calls, premature stopping, and screenshot vision

**Status: IMPLEMENTED 2026-09-26.** Original traces remain below as historical
evidence. The failed travel transcript supplied labels/DOM IDs as refs, used
unsupported `auto` mode, repeatedly snapshotted, and stopped without completing
the task. Verification uses disposable synthetic forms; it makes no bookings
and submits no personal information.

### Reproduced before changing the implementation

The first five tests in `test/tools/browser-automation.test.mjs` failed against
the previous implementation (**0 pass / 5 fail**):

```text
auto/open: Error: Unknown browser mode: auto
snapshot: page title and URL only; visible custom controls absent
act ref="combobox Where from?": Error: Stale ref; re-read the page with browser snapshot.
fill: Error: Stale ref; re-read the page with browser snapshot.
Chrome invalid-ref recovery: no fresh controls returned
```

Further red-to-green regressions captured the browser workflow stopping at round
6 after its third snapshot, PNG pixels absent from the next model request, a
select incorrectly sent to `locator.fill`, and an opaque configured credential
leaking in the new process-teardown diagnostic. The complete agent/form repro
also exposed schema budgeting that counted tools but omitted the real system
prompt and user-image cost: discovery exhausted the default window, and a later
screenshot was trimmed despite its attachment receipt.

### Changes and evidence

| Path | Change | Verification |
| --- | --- | --- |
| `tools/browser/pending.mjs`, `browser.mjs` | `auto` uses enabled-backend selection; exact opaque-ref guidance; `fill_form` schema, approval and value redaction | Public tool-entry tests; real disabled-Chrome fallback |
| `tools/browser/refs.mjs`, `session.mjs` | Shared snapshot/action limits and error contract; invalid refs produce fresh refs without executing or replaying a mutation; manager retains recovered refs | Real Playwright and Chrome stub tests; both real backends in live script |
| `tools/browser/playwright.mjs` | Visibility before limits; accessible labels/states, custom ARIA controls, open shadow roots and frames; exact unique re-render resolution within original frame; password hiding; label query | Real Chromium controls, frame fill, shadow controls, ambiguous replacements, password/query regressions |
| Both adapters | Successful open/action/form-fill returns next snapshot; all form refs prechecked; select/checkbox support in Playwright; native Chrome form filling | Both real backends complete local form with no separate snapshot calls |
| `tools/browser/chrome.mjs` | Tab-bound refs, no actionable static-text UID, native included snapshots avoid a separate MCP snapshot | Stub counts calls/UID mapping/cross-tab rejection; real cached Chrome form and explicit-tab round trips |
| `src/core/agent.mjs` | Successful interactions reset earlier browser-read repetition counts; actual prompt/user-image costs reserve context space | Snapshot-only guards remain green; complete live Playwright form through discovery and scripted model rounds |
| `tools/browser/screenshots.mjs`, `agent.mjs` | Workspace-bound PNG receipts become user-image content; text tool replies preserved; 15 MiB / three-image caps | External path, invalid PNG, wrong bytes and count tests; real capture arrives as pixels in next scripted model request |
| `src/integrations/mcp-client.mjs` | Await and observe asynchronous process teardown failures; redact configured secrets in diagnostics | Injected failure regression red-to-green; real Chrome Stop/disconnect/reconnect |
| `scripts/verify-browser-automation.mjs` | Runtime port, cached executable and disposable profiles; actual version printed; no downloads | `BROWSER_AUTOMATION_LIVE_OK` on both real backends |

The locator/action design follows [Playwright locators](https://playwright.dev/docs/locators)
and [actionability](https://playwright.dev/docs/actionability): resolve current
controls and require uniqueness, retaining normal auto-waiting. Chrome uses the
upstream [tool reference](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/tool-reference.md)
for snapshot UIDs, `includeSnapshot`, and `fill_form`. Neither adapter guesses a
selector or automatically repeats a mutation after a failed ref.

### Latest execution traces

Affected suites: **102 tests / 102 pass / 0 fail / 0 skip**, including core
browser workflow, context budget, tool loading/budget/loop, browser automation,
browser lifecycle, and browser contracts. Command:

```text
node --test --test-concurrency=1 test/core/tool-loading.test.mjs test/core/context-budget.test.mjs test/core/browser-workflow.test.mjs test/core/tool-loop.test.mjs test/core/tool-budget.test.mjs test/tools/browser.test.mjs test/tools/browser-automation.test.mjs test/tools/browser-lifecycle.test.mjs
AGENT_BROWSER_LIVE_OK: open -> act -> fill_form -> act -> read -> screenshot; one invalid-ref recovery; no separate snapshots
```

The model decisions in that agent test are scripted; the public tools, manager,
Playwright browser, ref propagation, form submission, read-back and screenshot
bytes are real. A live provider was not used.

```text
node scripts/verify-browser-automation.mjs
Live Chrome MCP version=1.8.0; configured=1.10.1; cached executable only
isolated: open -> fill -> fill -> click -> confirmed read; no separate snapshot calls
isolated: fill_form fills two fields and returns the next refs
isolated: invalid ref recovered with fresh refs and no mutation
isolated: preview 8.7 FPS; 15 distinct frames; screenshot=10532 bytes
isolated: explicit tab targets original form after another tab opens
isolated: Stop returned in 2 ms; queue released in 171 ms
local: open -> fill -> fill -> click -> confirmed read; no separate snapshot calls
local: fill_form fills two fields and returns the next refs
local: invalid ref recovered with fresh refs and no mutation
local: preview 5.5 FPS; 15 distinct frames; screenshot=72790 bytes
local: explicit tab targets original form after another tab opens
local: Stop returned in 19 ms; queue released in 2427 ms
local: reconnect on demand after transport disconnect
auto: disabled Chrome falls back to enabled Playwright
BROWSER_AUTOMATION_LIVE_OK
```

An earlier identical successful sample measured **9.0 FPS isolated / 6.3 FPS
Chrome**. These are local animated-page measurements, not a guaranteed refresh
rate. Stop's return and serial queue teardown are reported separately. The
configured Chrome pin is unchanged; cached **1.8.0** was used without installing
a package, so this is not verification of pinned **1.10.1**.

The desktop gate passed after the final code edits: `npm run desktop:build`
completed TypeScript checking and built **318 modules in 8.76 seconds**. Vite
reported its existing 529.76 kB chunk-size advisory. `git diff --check` passed.
The sandboxed run failed Git access and stalled process termination; those paths
passed when rerun with process permissions. The unrestricted full run reported
**695 total / 692 pass / 2 fail / 1 skip**: the activation fixture depended on the
machine's installed skill prompt size and now budgets that prompt explicitly
(subsequent affected suite: 102/102); the other failure was the already recorded
`jobs.test.mjs` 3-second job-start timing limit. A standalone job run reproduces
that timing failure. No job timing assertions were weakened.

**Final full gate:** `npm test` (`node --test --test-concurrency=1`) reported
**695 total / 692 pass / 2 fail / 0 cancelled / 1 skip**, duration **198694.9079 ms**.
The activation test passes with the corrected fixture. The remaining failures
are both in unchanged `test/tools/jobs.test.mjs`:

```text
line 25: performance.now() - start < 3000 failed (test duration 10596.6677 ms)
line 40: /first.*second/s did not match ''; job_wait had a 5000 ms deadline
```

The job source and assertions were not changed. A standalone run reported
**6 pass / 1 fail**, reproducing the first timing failure (test duration
26981.2747 ms); the output test passed in that standalone run. These failures
remain separate findings rather than browser fixes. The full gate is not green.
Final tracked diff and new browser-file whitespace checks passed.

### Remaining coverage and accepted limits

- Pinned Chrome MCP 1.10.1, cold package install, personal-session permission
  dialogs, packaged Electron Chromium download and rendered appearance remain
  untested in this continuation. No new package was installed: the Sonatype
  Guide skill requires its pre-install dependency check, and the corresponding
  MCP tooling is unavailable in this session.
- No real airline/Google Flights transaction, live model task choice or live
  vision-provider interpretation was exercised. CAPTCHA, site rejection and
  payment/booking confirmation still require actual site evidence.
- A snapshot may omit closed shadow roots, frames/controls beyond its limits,
  or a frame that navigates during inspection; `query` helps with control limits.
  Missing/ambiguous controls can still fail, with bounded recovery. Native
  upstream Chrome UID errors after validation are bounded errors; no mutation
  replay is attempted.
- The real action checks cover open, fill, form filling, click, read, screenshot,
  preview, explicit tab selection, Stop, reconnect and backend selection.
  Hover, drag, key presses, sequential typing, scrolling, custom-widget form
  fills in Chrome and cross-origin frame navigation were not exercised live.
- A successful action's follow-up snapshot can fail independently. Its receipt
  says the action completed and instructs inspection instead of repeating it.
  Partial form fills are reported; they are not rolled back.
- Screenshot attachment requires a vision-capable model and sufficient context;
  conservative history trimming can shed images. Raw external MCP browser tools
  expose artifacts/status rather than first-party live pixels. Composio's live
  travel/music catalog is unverified. Version changes still require exact-command
  approval, preserving the existing security boundary (Finding 11).
- An inner Chrome request timeout invalidates refs while keeping its transport;
  explicit Stop, dead transport and an outer session cancellation can tear it
  down. If OS process teardown fails, a redacted diagnostic is observed; that
  does not prove every descendant exited.

Literal review: introduced operational sizes/counts/timeouts are named constants
with units and reasons; ref/receipt contracts are shared. HTML/ARIA/MCP/API names
are protocol identifiers, unique result text is user guidance, and synthetic
hosts/paths/data remain test or verification-script fixtures. Runtime discovery
supplies the OS temp directory, executable, package version and listening port.

**Confidence: 80/100.** Ledger: +40 affected regression suites, +25 both real
browser backends, +15 real browser/agent request pipeline, +10 desktop build and
updated docs, +10 diff/literal review; −5 failing full-suite jobs gate, −5 pinned
Chrome version/cold startup, −5 live provider/real-site task decisions, −3
packaged desktop/setup/appearance, −2 remaining advanced interaction/frame
branches. Residual paths are listed above. The next +5 requires exercising the
configured Chrome version and its setup path after the dependency check becomes
available.

## 0. Environment trace (verified live)

```
node --version            -> v24.16.0
playwright pkg version    -> 1.63.0
chromium.executablePath() -> C:\Users\anime\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome.exe
EXISTS=true  SIZE=4508160
```

Raw launch probe (`chromium.launch({headless:true})` -> `newPage()` -> `goto('about:blank')`):

```
LAUNCH_OK 153.0.8010.12
PAGE_OK url=about:blank
CLOSE_OK
```

Takeaway: the binary exists and launches here, so any "can't access the binary file" report
is environmental (missing/corrupt download, packaged-app path, concurrent profile lock) or a
downstream misread (Finding 1) — not a broken launch path on this machine.

## 1. Full isolated screenshot flow trace (works — baseline for everything below)

Script: `new PlaywrightBrowserAdapter({profile: <tmp>})` against a local `127.0.0.1` page,
`ctx = { settings:{headless:true}, config:{allowPrivateHosts:true}, cwd:<tmp> }`. Output:

```
TMP=C:\Users\anime\AppData\Local\Temp\ankita-live-W6uYGF
SRV=55735
Opened tab 1: Live
http://127.0.0.1:55735/
SNAP=Live — http://127.0.0.1:55735/
[ref=1-0-0] button Save
PREVIEW_LEN=9987 PREFIX=data:image/jpeg;base64,/9j/4AA
SHOT=Screenshot saved: C:\...\ankita-live-W6uYGF\downloaded-images\browser-1790408851318.png
FILE_EXISTS=true SIZE=5794
ADAPTER_CLOSE_OK
```

Notes:

- `preview()` returns an inline JPEG data-URL (~10KB for a trivial page) — this is the only
  path where pixels actually reach the caller.
- `screenshot` writes a real PNG to disk and returns a bare path string. Both halves work;
  the break is what happens when the agent tries to *consume* that path (Finding 2).

## 2. Finding 1 — Screenshot succeeds but the agent can't view it ("looks like a binary file")

**Status: FIXED 2026-09-26 (hardened same day).** Both adapters' `screenshot` now return a structured receipt
`{type:'browser_screenshot', path, bytes, note}` (stringified by `session.mjs`), the note
tells the model the PNG is binary and must not be opened with `read_file`, and
`recentArtifacts` (`desktop/electron/workspace.mjs`) surfaces the file in the desktop
work-review artifacts. Hardening: `read_file` now redirects raster images
(`png/jpg/gif/webp/bmp/ico`) to artifacts + snapshot/read instead of the dead-end binary
error — so even a model that ignores the note gets a actionable next step; non-image
binaries keep the original guard. Verified: 32/32 across browser, lifecycle, workspace,
and tools suites; live Playwright open→screenshot→artifact round trip; Chrome-backend
receipt path driven through the manager with a stub MCP (temp→copy→stat→receipt, byte
count exact). Not covered: real `chrome-devtools-mcp` server run (package not installed
here) and rendered Electron panel.
**Latest coverage:** model-side screenshot wiring is now implemented: validated PNGs
are appended to the existing user message as `image_url` content, with text-only tool
messages and original attachments preserved. `test/core/browser-workflow.test.mjs`
checks the next request payload, including a real Playwright capture. Both real
adapters also produced receipts consumable by that attachment path (Part F).
This replaces the earlier save-only limitation. Actual interpretation by a live
vision provider and rendering in packaged Electron remain untested.
Original trace below for reference.

### Trace (reproduced live)

1. Capture to the real workspace folder:
   `SHOTFILE=C:\Users\anime\3D Objects\copilot-chat\downloaded-images\browser-1790408894150.png`
2. Agent-side read of that file:
   `READ_AS_AGENT=Error: C:\...\browser-1790408894150.png looks like a binary file.`

So the user-visible sequence is: browser reports success, then the follow-up view fails with
a binary-file error — exactly the reported "when it captures the img it shows can't access
the binary file".

### Code path

- Producer: `tools/browser/playwright.mjs:131-137` —
  `page.screenshot({ path: file, timeout: 10_000 })` then `return \`Screenshot saved: ${file}\``.
  Same shape in `tools/browser/chrome.mjs:141-151` (screenshot via MCP to a temp file,
  `copyFileSync` to `downloaded-images/`, return path).
- Consumer: `tools/filesystem/read-file.mjs:22-27` reads raw bytes and bails:
  `if (isBinary(buf)) return \`Error: ${p} looks like a binary file.\``.
- Guard: `tools/shared/_shared.mjs:122-126` — `isBinary` returns true on the first `0x00`
  byte in the first 8000 bytes. Every PNG contains null bytes, so *every* screenshot is
  guaranteed to hit this branch. The guard is correct for a text reader; the wiring is wrong.
- Wire: `tools/browser/session.mjs:84` sets `screenshot: null` on every action event, and
  `desktop/electron/engine.mjs:253` forwards `{ ...state, screenshot: null }` — the live
  frame only travels via `view()`/`preview()` data-URLs, never via the `screenshot` action.

### Root cause

`screenshot` is save-only (path string) while nothing in the agent loop converts that path
into viewable image content. The model is left holding a filesystem path it can only open
with a text-only reader that is designed to reject it.

### Original fix proposal (historical)

1. Preferred: return image content from the `screenshot` action — e.g. read the PNG back
   and append/return a `data:image/png;base64,...` payload (or route it through the same
   attachment pipeline the chat composer uses for pasted images), keeping the saved file
   as a side effect. Check size guards first: full-page PNGs here run 60–270KB on disk
   (see §6), preview JPEGs ~10KB–1.3MB on the wire per `engine.mjs` comment.
2. Alternative: keep `screenshot` save-only but change the contract — document that viewing
   goes through `view()`/BrowserStage preview, and have the tool response say so
   (`Screenshot saved: <path>. View it in the BrowserStage preview; read_file cannot open images.`).
3. Do NOT weaken `isBinary`/`read_file` — they are behaving correctly.

## 3. Finding 2 — Chrome adapter reports "No Chrome tab is open" when Chrome isn't connected

**Status: FIXED 2026-09-26** (with Findings 5, 6, 10 below). `#runOnce` fails fast via
`#ready()` when there is no connection and no `ensureConnected` to establish one;
`#preview` calls `#ready()` first too. The on-demand connect flow (with
`ensureConnected`) is unchanged. Regression test: null-MCP `run` and `preview` assert
`/Chrome is not connected/`.

### Trace (reproduced live, no MCP connected)

```
new ChromeBrowserAdapter(null).run({action:'screenshot'}) -> No Chrome tab is open
new ChromeBrowserAdapter(null).preview()                  -> No Chrome tab is open
```

Control (isolated adapter, never opened): `preview()` -> `No browser tab is open`,
`screenshot` -> `No browser tab is open`. The isolated messages are accurate; the Chrome
ones are misleading — there is no tab *because there is no connection*, a different problem
with a different remedy.

### Code path

- `tools/browser/chrome.mjs:36-37` `tabs()`: when `mcp.has(CHROME_MCP_ID)` is false it
  returns `[]` (or throws only if a stale cache exists).
- `tools/browser/chrome.mjs:57-65` `#page()`: empty tab list -> `throw new Error('No Chrome tab is open')`.
- The accurate error exists — `#ready()` (`chrome.mjs:24-26`):
  `'Chrome is not connected. Open Plugins → By Ankita and start the Chrome connection.'`
  — but `run()` only reaches `#call`/`#ready` *after* `#page()` has already thrown.

### Root cause

Tab resolution runs before the connection check, so the connection failure is masked as an
empty-tab failure.

### Original fix proposal (historical)

In `run()` and `#preview()`, call `this.#ready()` (or an explicit `mcp?.has(CHROME_MCP_ID)`
check) before `#page()`/`tabs()` so disconnected state surfaces the actionable message.
Keep `No Chrome tab is open` for the genuinely-connected-but-empty case. Add a unit test
mirroring `browser.test.mjs`'s Chrome adapter test with `mcp = null`.

## 4. Finding 3 — Chromium-binary failure path is fragile / unhelpful

**Status: FIXED 2026-09-26 (preflight).** `playwright.mjs` `#start()` now checks
`fs.existsSync(chromium.executablePath())` before launching; a missing download throws a
remedy covering both runtimes (desktop Plugins installer vs `npx playwright install
chromium`), while a present-but-broken binary keeps the original launch error. Positive
path covered by the live-Chromium suite test; the missing-binary branch is logic-reviewed
(not simulated). Packaged-app `installChromium()` verification remains open.

### Trace (fault-injected manager test, live)

Adapter whose `run({action:'screenshot'})` throws
`Executable does not exist at C:\x\chrome.exe`, driven through `BrowserSessionManager.run`:

```
SHOT_VIA_MANAGER=Error: Executable does not exist at C:\x\chrome.exe
LAST_STATUS=error STEP=Executable does not exist at C:\x\chrome.exe
```

The manager contract (`session.mjs:53,87-96`) converts all throws to `Error: <message>`
strings and parks `last.status='error'`. Nothing identifies this as a binary/install
problem or tells the user how to recover.

### Code path

- `tools/browser/playwright.mjs:48-65` `#start()`: missing `playwright` package ->
  `'Playwright is missing. Open Plugins → By Ankita to install it.'`; launch failure ->
  `\`Chromium could not start: ${error.message}. Open Plugins → By Ankita to download Chromium.\``.
  Both remediations are desktop-UI-only; the CLI (`chat.mjs`) has no install flow.
- `desktop/electron/browser-plugins.mjs:117-133` `installChromium()` spawns
  `process.execPath` + `<playwright>/cli.js install chromium` with `ELECTRON_RUN_AS_NODE`.
  `require.resolve('playwright/package.json')` from inside a packaged `app.asar` and the
  download target outside the bundle are both untested here — needs a packaged-app run.

### Root cause

Binary health is only discovered at launch, the error is stringly-typed, and the only
recovery path assumes the desktop Plugins UI.

### Original fix proposal (historical)

1. Pre-flight check in `#start()`: `fs.existsSync(chromium.executablePath())` before
   `launchPersistentContext`; on miss, throw a typed/distinct error carrying
   `{ code: 'CHROMIUM_MISSING', expectedPath }` plus a per-runtime hint (desktop: Plugins
   installer; CLI: `npx playwright install chromium`).
2. Preserve that code through `session.mjs` (currently stringified to `Error: ...`) or at
   least match on it for a tailored message.
3. Verify `installChromium()` from a packaged build (asar resolve + download size) and log
   the resolved `cli.js` path and exit code on failure.

## 5. Finding 4 — Hygiene: collisions, accumulation, flaky error status

**Status: FIXED 2026-09-26.** Shared `screenshotFile(cwd)` helper (`playwright.mjs`,
used by both adapters): unique `browser-<ms>-<rand8>.png` names, per-workspace
`downloaded-images/`, best-effort prune of our own `browser-*.png` beyond
`MAX_KEPT_SCREENSHOTS` (50), never touching other files. `VIEWPORT` hoisted to a named
const used by both launch and takeover-click bounds. Preview failures in `session.mjs`
`#view` keep the last good frame (status still reports the error; existing recovery test
unchanged and green). Regression tests: uniqueness + prune + non-target preservation,
viewport click bounds, frame retention on failed preview.

Evidence:

- Filenames are `browser-${Date.now()}.png` (`playwright.mjs:134`, `chrome.mjs:144`) —
  millisecond resolution; `batch` (up to 10 steps, `session.mjs:40-48`) and parallel
  managers can collide. Chrome's temp side (`ankita-browser-shot-<uuid>.png`) is safe;
  the final name is not.
- `downloaded-images/` in the repo already holds ~20 stale PNGs (browser captures up to
  ~269KB plus UI fixtures), i.e. captures accumulate with no pruning.
- `session.mjs:106-129` `#view()`: preview budget is 1500ms adapter-side
  (`playwright.mjs:210`, `chrome.mjs:171`) + 1800ms in `view()` (`session.mjs:116`); any
  slower frame flips `last.status` to `'error'` with `screenshot: null`. Transient slowness
  presents as breakage (the lifecycle test `a failed preview recovers its ready state`
  covers recovery, but the user still sees an error blip).
- `playwright.mjs:221` clamps takeover clicks to a hard-coded 1280x800, matching today's
  fixed viewport (`playwright.mjs:58`) — brittle if the viewport ever changes.

Original fix proposal (historical): unique final names (uuid/counter suffix); cap/prune
`downloaded-images/`; softer preview degradation (keep last good frame, `degraded` status);
derive input bounds from the context viewport.

## 6. Regression baseline (all green — keep as the gate)

```
browser.test.mjs (8/8, ~2.9s):
  plugin choices persist / site rules / approval scoping / disabled-mode refusal /
  batch serialization+halt / takeover gating / Chrome UID->ref mapping /
  real Chromium open+fill+stale-ref+preview+screenshot

browser-lifecycle.test.mjs (10/10, ~0.6s):
  disable routes to Playwright / stop cancels in-flight+queued / MCP cancellation /
  Chrome on-demand reconnect / preview-without-tempfile / preview-failure recovery /
  disabled-ref rejection / shared slow-preview capture
```

Extra probes: same-profile double-open succeeds (second context opens its own tab set —
no lock error on this machine); headed `open` (`headless:false`) succeeds here.

## Part B — Chrome CDP connect / disconnect / reattach findings

Scope: `tools/browser/chrome.mjs`, `tools/browser/session.mjs`,
`desktop/electron/browser-plugins.mjs`, `src/integrations/browser-plugins.mjs`,
`src/integrations/mcp-manager.mjs`, `src/integrations/mcp-client.mjs`. Method: live
fault-injection against stub MCP transports. The `chrome-devtools-mcp` package itself is
not installed here (`resolveNpxBin('chrome-devtools-mcp@1.10.1')` -> `null`), so
server-side behavior in this original section is cited from our client-side code,
not from a live server. Part F adds real server checks with cached 1.8.0; the
configured 1.10.1 pin is still not cached.

## 7. Finding 5 — one slow tool call kills the shared Chrome connection

**Status: FIXED 2026-09-26.** `session.mjs` teardown trigger narrowed: close + adapter
delete now happen only on explicit Stop (`signal.aborted`) or transport death
(`connection closed|disconnected|server exited`). Plain timeouts keep the adapter and its
connection and only `invalidate()` interaction state. Stop-detaches-transport semantics
(verified live, asserted by `scripts/verify-browser-chrome.mjs`) are preserved and locked
by a new test. Regression tests: timeout-keeps-adapter (fails on old code), Stop-detaches.

### Trace (reproduced live)

Stub MCP where `take_snapshot` sleeps past the adapter timeout, driven through
`BrowserSessionManager.run({action:'snapshot'})` with `local` enabled:

```
SNAPSHOT_VIA_MGR=Error: Browser request timed out after 15 seconds. Check the browser connection and try again.
CALLS=["list_pages","take_snapshot","DISCONNECT:ankita-chrome"]
MGR_HAS_ADAPTER_AFTER=false LAST_STATUS=error
```

One heavy page → the shared `ankita-chrome` MCP connection is disconnected and the whole
adapter (refs, epoch, pageId, cached tabs) is discarded. The next action pays a full `npx`
respawn plus up-to-25s init.

### Code path

- `tools/browser/session.mjs:87-92`: any error matching
  `/timed out|connection closed|disconnected|server exited/` → `adapter.close()` +
  `adapters.delete(mode)`.
- `tools/browser/chrome.mjs:181-186` `close()`: calls `mcp.disconnect(CHROME_MCP_ID)` —
  this tears down the process-wide shared connection, not just the session's handle.

### Root cause

A per-call timeout is treated as a dead transport. Timeouts are expected on heavy pages;
only `closed`/`exited`/`disconnected` prove the transport is gone.

### Original fix proposal (historical)

Narrow the teardown trigger to transport-death signals; on plain timeout keep the adapter
and connection, invalidate refs only, and surface a retryable message. If teardown stays,
make `ChromeBrowserAdapter.close()` not disconnect a connection it doesn't own (or take an
explicit `disconnectMcp` flag for full-teardown callers).

## 8. Finding 6 — background preview uses stale tabs, never re-lists

**Status: FIXED 2026-09-26.** `#preview` now calls `#ready()`, refreshes the tab list
(short timeout, overridable), and drops a cached `pageId` absent from the fresh list so
the active tab is used. Regression test seeds a dead tab and asserts preview succeeds on
the fresh one.

### Trace (reproduced live)

`run({action:'tabs'})` caches one tab then the tab is closed in real Chrome; the
background `view()` → `preview()` path reuses the dead entry:

```
CACHED_TABS=1 PAGEID=null → STALE_PREVIEW_ERR=Error: page not found, tab was closed
```

`session.mjs` `#view()` then parks `last.status='error'` with `screenshot: null`, so the UI
shows breakage until the next explicit action.

### Code path

- `tools/browser/chrome.mjs:168-170` `#preview()` → `#page()` uses `cachedTabs` as-is.
- Contrast `run()` (`chrome.mjs:85,100`), which always re-lists via `tabs()` first.

### Root cause

The preview path skips the tab refresh that the action path performs.

### Original fix proposal (historical)

Re-list (cheap `tabs()` with a short timeout) inside `#preview()` before resolving the
page; on an empty list report an idle/stopped state with a clear message instead of an
error, and keep the last good frame rather than nulling the screenshot.

## 9. Finding 7 — dead connection reported as ready; nothing prunes it

**Status: FIXED 2026-09-26 (pruning).** `McpClient` takes an `onExit` callback fired from
the stdio `close` handler; `McpManager.connect` passes one that deletes the record only
if it still points at that client (reconnect-safe) and notifies. A dead child therefore
stops passing `has()` → overview `ready` goes false and the next browser action goes
through `ensureConnected`. No active liveness probe added deliberately (every overview
call would pay a round trip). The `#connectChrome` early return is now trustworthy
because `has()` implies a live child. Regression test: node MCP server that connects
then exits is pruned within the poll window.

### Trace (reproduced live)

```
(await browserPluginOverview(store, { has: () => true })).local
-> {"id":"ankita-chrome",...,"enabled":true,"connection":"profile","ready":true,"reason":""}
```

A transport that claims `has()` but is dead still reports `ready: true` with no reason.

### Code path

- `src/integrations/browser-plugins.mjs:121`: `ready: Boolean(mcp?.has?.(CHROME_MCP_ID))` —
  pure map membership, zero liveness.
- `src/integrations/mcp-client.mjs:447-457`: on child `close`, pending calls are rejected
  but the record is never removed from `McpManager.servers`, so `has()` stays true.
- `desktop/electron/browser-plugins.mjs:94`: `if (this.mcp.has(CHROME_MCP_ID) && !reconnect)
  return this.overview()` — the fast path skips any health check, so a dead child is
  returned as healthy. The first real call then burns through a 5s `tabs` timeout plus the
  action timeout before the retry branch finally reconnects.

### Root cause

Liveness is never probed and dead records are never pruned; readiness is a stale boolean.

### Original fix proposal (historical)

Probe liveness for the local plugin in `overview` (e.g. `list_pages` with a short timeout,
cached for a few seconds); prune dead records (manager drops the entry when the client
emits close); make the `#connectChrome` early return verify instead of trusting `has()`.

## 10. Finding 8 — spawned server env drops APPDATA/LOCALAPPDATA on Windows

**Status: FIXED 2026-09-26.** `serverEnv()` keep-list gains `APPDATA` and `LOCALAPPDATA`
(linux-safe: undefined keys are skipped). Existing env test extended with save/restore
assertions.

### Trace (reproduced live)

```
Object.keys(serverEnv({})) -> CI,NO_COLOR,UV_NO_PROGRESS,PATH,PATHEXT,SystemRoot,windir,TEMP,TMP,USERPROFILE
ENV_HAS_APPDATA=false ENV_HAS_LOCALAPPDATA=false
```

### Code path

- `src/integrations/mcp-client.mjs:252-263` `serverEnv()`: `keep = ["PATH", "PATHEXT",
  "SystemRoot", "windir", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG"]`.

### Root cause (suspect, not end-to-end reproduced)

The `npx`-spawned `chrome-devtools-mcp` child never sees `%APPDATA%`/`%LOCALAPPDATA%`,
where npm/npx keep their caches — first-run download behavior under that env is suspect.
(Client-side `npmRoots()`/`resolveNpxBin()` read the parent env, so they are unaffected.)

### Original fix proposal (historical)

Add `APPDATA`/`LOCALAPPDATA` (and likely `ProgramFiles`) to the keep list on win32; then
re-run a cold `npx` install of the pinned package under `serverEnv()` to confirm.

## 11. Finding 9 — cold start races the 25s init timeout

**Status: FIXED 2026-09-26 (budget).** New `chromeInstallNeeded(args)` helper
(`src/integrations/browser-plugins.mjs`, resolver injectable) detects a missing npx-cache
entry; `#connectChrome` uses `CHROME_COLD_INSTALL_TIMEOUT_MS` (120s) for cold installs
and keeps 25s for warm handshakes (both now named consts). Unit-tested (cold/warm/empty).
No download progress hook (manager connect has none); pre-warming on enable remains a
possible follow-up.

### Trace (reproduced live)

`resolveNpxBin('chrome-devtools-mcp@1.10.1')` -> `null`; the npx cache holds 5 unrelated
entries. First-ever connect therefore downloads the package through `npx -y` inside the
`initTimeoutMs: 25_000` budget (`desktop/electron/browser-plugins.mjs:97`). On a slow
network this times out into a generic failure, and the retry branch disconnects/connects
from scratch rather than resuming.

### Original fix proposal (historical)

Pre-warm on enable (an `installChromium`-style prefetch for the MCP package with progress
via `onProgress`), and/or give the first-install attempt its own longer budget while
keeping 25s for warm connects.

## 12. Finding 10 — reconnect is always full teardown, even when the transport is fine

**Status: FIXED 2026-09-26 (cheap tier).** `run()` is now a wrapper over `#runOnce`:
read-only actions (`snapshot, read, tabs, screenshot`) get exactly one cheap retry
(invalidate + drop pageId/cache + re-list) on stale-tab-shaped errors; mutations and
`open` never replay. Transport-death still goes through the existing full
`ensureConnected` reconnect. Regression test: first `take_snapshot` fails with `No such
page`, retry succeeds with two tab listings.

### Code path

- `tools/browser/chrome.mjs:85-92`: on a matching error the retry always does
  `invalidate()` → `ensureConnected({...ctx, reconnect: true})` →
  `desktop/electron/browser-plugins.mjs:95` disconnects and respawns the server — even
  when the failure was a bad `pageId`/closed tab rather than a dead server.

### Root cause

No cheap retry (re-list tabs, re-resolve `pageId`, one direct retry) before the expensive
full reconnect.

### Original fix proposal (historical)

Two-tier retry: cheap (refresh tabs, drop `pageId`, retry once) then full reconnect only
if the error indicates transport death or the cheap retry also fails.

## 13. Finding 11 — version pin forces re-approval on every bump; active-tab tracking is text parsing

**Status: PARTIALLY FIXED 2026-09-26.** Tab tracking is mitigated by Finding 6's preview
refresh (stale `pageId` dropped on fresh lists). The version-bump re-approval is
**deliberately unchanged**: "changed command waits for fresh yes" is a security boundary
(`mcp-manager.mjs` reconcile), and auto-trusting version-only bumps would weaken it.
Recorded here as accepted design, not a bug to fix without explicit approval.

Two smaller items, code-read (matching the lifecycle test suite's passing behavior, so no
live repro attempted):

- `src/integrations/browser-plugins.mjs:102-107` pins `chrome-devtools-mcp@1.10.1`. Any
  bump changes the stored command → `configureChrome` removes/re-adds the record and the
  stored approval is void ("a changed command waits for a fresh yes",
  `mcp-manager.mjs:226-233`). Accepted design, but routine bumps cost every user a
  re-approval. Option: treat version-only bumps as trusted upgrades with a notice.
- `tools/browser/chrome.mjs:42-51` detects the active tab via `/\[selected\]/` on the
  MCP's text listing. Manual tab switches in Chrome leave the cached flag stale until the
  next `run()`; preview may capture the wrong tab. Option: refresh before preview
  (Finding 6's fix covers this) and expose the resolved tab id in view state.

## Historical full-suite gate (earlier 2026-09-26)

`node --test --test-concurrency=1`: **672 pass / 1 fail / 1 skip (674 total)**. The single
failure (`test/tools/jobs.test.mjs` "commands yield a live job", `performance.now()` 3s
budget exceeded) reproduces standalone and is unrelated to these changes (job-spawn timing
on this machine; none of the touched files are in that path). Pre-existing environment
flake, left untouched per no-scope-creep.

## Part D — live preview sidebar never opens for raw MCP browser tools (reported with screenshot)

Symptom: a teammate drives `mcp__playwright__browser_*` tools ("Ran Playwright code",
`.playwright-mcp/*.yml` snapshot refs) and the live browser sidebar never opens.

**Status: FIXED 2026-09-26.** Root cause: the panel auto-opens only on `browser-state`
events (`App.tsx`), which only `BrowserSessionManager` emits — raw MCP browser tools
bypass it entirely, and the prompt even steered the model toward them. Changes:
`desktop/electron/engine.mjs` exports `isRawBrowserTool`/`rawBrowserStep` and emits
`browser-state` (`mode: 'external'`, working on call, ready/error on result) for raw
browser MCP calls so the panel opens; `desktop/shared/wire.ts` mode union gains
`'external'`; `BrowserStage.tsx` labels it External, explains live pixels need the
built-in tool, and skips session polling for it; `recentArtifacts` surfaces image paths
named in raw MCP screenshot results; `BROWSER_HINTS` steers the model to prefer the
built-in `browser` tool. Verified: 67/67 desktop suite, 20/20 mcp-context + workspace,
37/37 image + browser suites, `tsc --noEmit` clean. Residual: no live pixels for raw MCP
tools (their screenshots surface as artifacts, not a live feed) — full parity would need
driving those sessions through the session manager.

## Part E — live booking transcript: wrong spellings + stale refs on every act (reported with transcript)

Symptom: end-to-end flight booking on Air India Express failed with `Unknown browser
mode: headless`, `Unknown browser action: click`, `target` ignored, and `Stale ref` on
nearly every interaction with a lively page.

**Status: FIXED 2026-09-26.** Three changes:
1. `normalizeBrowserArgs` (`tools/browser/pending.mjs`, no-import-cycle home): op names
   accepted as `action` (rewritten to `act`+`op`), `target`/`to_target` aliased to
   `ref`/`to_ref`, `headless`/`headful` aliased to `isolated`, recursive over batches.
   Applied at the tool entry (`browser.mjs` run/approval/display) and in session `#one`
   before validation, so direct manager callers are covered too. Approval bypass closed:
   aliases count as `act` for `needsApproval`.
2. `#act` marked-element fallback (`playwright.mjs`): when the epoch moved on (live
   prices, re-rendering dropdowns, timers), act on the still-uniquely-marked element
   instead of failing; genuinely gone/ambiguous elements still throw STALE. Same for
   drag destinations.
3. Schema descriptions document the aliases.
Verified: 30/30 browser + lifecycle (5 new tests, incl. a fallback test that fails on the
old code), tool-loop/loading green. Flake note: the live-Chromium test failed twice with
EPERM cleanup + 26s bodies; cause was 17 leaked chrome.exe from earlier live probes
hogging the box — killed, suite back to 3.5s. Lesson recorded: always close probe
browsers. ixigo bot-protection rate limits remain environmental, out of scope.

`node --test --test-concurrency=1`: **672 pass / 1 fail / 1 skip (674 total)**. The single
failure (`test/tools/jobs.test.mjs` "commands yield a live job", `performance.now()` 3s
budget exceeded) reproduces standalone and is unrelated to these changes (job-spawn timing
on this machine; none of the touched files are in that path). Pre-existing environment
flake, left untouched per no-scope-creep.

## Repro commands (all read-only, no source changes)

- `node --test test/tools/browser.test.mjs`
- `node --test test/tools/browser-lifecycle.test.mjs`
- Save-then-read: `PlaywrightBrowserAdapter.run({action:'screenshot'})` ->
  `read-file.mjs run({path})` -> `looks like a binary file` (§2).
- No-MCP Chrome: `new ChromeBrowserAdapter(null).run({action:'screenshot'})` ->
  `No Chrome tab is open` (§3).
- Binary-missing shape: fault-injecting adapter through `BrowserSessionManager.run` (§4).
- Timeout blast radius: stub MCP with hung `take_snapshot` through manager with `local`
  enabled -> `DISCONNECT:ankita-chrome` + adapter dropped (§7).
- Stale-tab preview: `run({action:'tabs'})`, close the tab, `preview()` ->
  `page not found` (§8).
- Dead-but-ready: `browserPluginOverview(store, { has: () => true })` -> `ready: true` (§9).
- Spawn env gap: `Object.keys(serverEnv({}))` lacks `APPDATA`/`LOCALAPPDATA` (§10).
- Cold start: `resolveNpxBin('chrome-devtools-mcp@1.10.1')` -> `null` (§11).

## Part C — "book a flight / play something" refused despite a working, enabled browser

**Status: FIXED 2026-09-26.** `tools/catalog.mjs`: `browser` gains intent keywords
(`book, booking, flight, flights, ticket, tickets, travel, hotel, play, music, song,
video, youtube, listen`), `web` gains (`flight, flights, ticket, tickets, booking`),
`connectors` gains (`flight, flights, hotel, travel, music, spotify, youtube`).
`tools/find-tools.mjs` miss branch adds a static tip routing booking/shopping/playback to
the `browser` group. Verified live: `book a flight from Mumbai to Delhi` →
`[browser,web,connectors]` (was `[]`); `play some music` / `play a song on youtube` →
`[browser,connectors]`; whole-word matching confirmed (`display settings`, `sing along`
do not route to browser). Suites: tool-loop + tool-loading (35/35), mcp-store +
mcp-context + composio-http (35/35). Regression test added in
`test/core/tool-loop.test.mjs`. Residual: genuinely missing capabilities (e.g. food
delivery) still miss and fall to the tip text; Composio backend catalog contents for
travel/music unverified.
Original symptom below for reference.

Symptom: asking the agent to book a flight (Mumbai → Delhi) or play something gets "I can't
do that, I don't have the capability" — even though the browser tool exists and both
backends are enabled on this machine. All traces below reproduced live.

## 14. Finding 12 — the browser is registered and enabled, but invisible to the model

### Trace (reproduced live)

```
BROWSER_IN_CORE=false      <- the model does not start with it
BROWSER_REGISTERED=true    <- it exists, deferred behind find_tools
STORE_FILE=C:\Users\anime\.copilot-chat-cli\browser.json (exists)
isolated.enabled=true, headless=true; local.enabled=true, connection=active, port=9222
```

### Code path

- `tools/index.mjs:27-47` `CORE`: file tools, `run_command`, jobs, `http_request`,
  `find_tools` — no `browser`. `tools/catalog.mjs:60-64` holds the `browser` category as
  deferred, so the model only ever sees its one-line summary in the prompt
  (`src/core/agent.mjs:197`) until it calls `find_tools` with a matching word.

### Root cause

The refusal is a discovery failure, not a missing capability: a working, enabled browser
sits one `find_tools("browser")` call away, and the model never makes that call because
nothing in the request maps to it (Finding 13).

## 15. Finding 13 — flight/play intent matches zero categories, so find_tools dead-ends

### Trace (reproduced live)

```
matchCategories('book a flight from Mumbai to Delhi') => []
matchCategories('book flight tickets')                => []
matchCategories('play some music')                    => []
matchCategories('play something')                     => []
matchCategories('play a song on youtube')             => []
matchCategories('order food')                         => []
```

And the end-to-end miss text the model actually receives:

```
Q=book a flight from Mumbai to Delhi
Nothing matched "book a flight from Mumbai to Delhi". Everything you can load right now:
  git / process / personal / skills / browser / web ...
```

### Code path

- `tools/find-tools.mjs:27-42` `matchCategories()`: plain whole-word keyword match only.
- `tools/catalog.mjs:60-74`: `browser` keywords are `browser, playwright, chrome,
  click website, fill form, browse interactively`; `web` keywords are `web, search,
  google, internet, online, browse, website, url, link, docs, ...` — neither list contains
  `book, flight, ticket, travel, play, music, song, video, watch, listen, youtube, open`.
- So even `play a song on youtube`, which the browser could do trivially, matches nothing —
  not even the adjacent `browser`/`web` groups.
- The miss branch (`find-tools.mjs:106-118`) answers with a 3-hop flow (load `mcp` group →
  `mcp_manage search` → ask user → install), while the TOOL EXECUTION POLICY in the same
  prompt (`agent.mjs:233-247`) says "if you cannot determine something, say so plainly" and
  "stop calling tools and answer now." The model takes the early exit and refuses instead
  of attempting discovery.
- Grep across all of `tools/` for `flight|music|song|youtube|spotify` returns exactly one
  hit: a code comment ("in flight", `recall.mjs:84`). No travel/media tool exists anywhere,
  so the miss text is also factually inviting a registry search for something the model
  could have done in-browser.

### Root cause

Two stacked gaps: (a) no intent→browser routing — no keyword, skill, or prompt line maps
"book X / play Y" to "drive a website with the browser tool"; (b) the miss path's remedy
is higher-friction than the policy's permission to stop, so the model stops.

### Original fix proposal (historical)

1. Add intent keywords to the `browser` category (`book, booking, flight, flights,
   ticket, tickets, travel, hotel, play, music, song, video, watch, listen, youtube,
   open`) and `ticket, booking, flight` style terms to `web`, so `find_tools` loads the
   browser group instead of dead-ending. Pure `catalog.mjs` change; verify with the
   existing `matchCategories` unit tests plus new cases.
2. Strengthen the miss branch: when nothing matches, suggest the single most-likely group
   (or ask one clarifying question) instead of jumping to the 3-hop registry/install flow.
3. Optional: a short skill or prompt line — "booking, shopping, and media playback mean
   driving the site in the browser tool" — so the model bridges intent→browser even when
   it already has the group loaded. Note `agent.mjs:222` already says "for interactive
   websites, load `browser`", but nothing connects booking/playback requests to that line.

## 16. Finding 14 — connectors keywords exclude travel/music apps, hiding Composio fallbacks

### Code path

- `tools/catalog.mjs:104-108`: `connectors` keywords are `gmail, email, slack, notion,
  calendar, drive, sheets, docs, jira, linear, asana, github, twitter, x, connected apps,
  ...` — no `flight, hotel, travel, music, spotify, youtube`.
- `tools/connectors/composio.mjs:35-40`: `composio action="search"` *can* search the app
  catalog for whatever the backend offers — but `find_tools("book a flight")` never loads
  `connectors`, so the model never runs that search.

### Root cause

Even if the Composio backend offers travel/music toolkits, the keyword gate keeps the
model from ever looking.

### Original fix proposal (historical)

Add travel/media terms to the `connectors` keywords (or make the miss branch suggest
`composio action="search" <query>` directly for service-shaped requests), then verify what
the backend catalog actually returns for `flight`/`music` before promising the capability.

## Scheduled authentication and owned-browser cleanup — 2026-09-28

The scheduled worker reuses the built-in browser contract and its private
model-selected credential refs. It has a separate persistent Chromium profile;
foreground Chrome and chat retain their independent connections.

- Fixed expected cleanup disconnects being reported as job network failures:
  close the network guard before closing its Chromium context. The regression
  failed with `false !== true` before the fix and passed afterwards. The real
  navigation suite passed `2/2`, including pre-dispatch redirect/POST/frame/Fetch
  interception and this shutdown ordering.
- Rejected stale refs that cannot have performed an action can return fresh refs
  to the worker. Uncertain action/network failures stop without replaying a
  mutation. Audits contain fixed error notices, not raw snapshots or field values.
- Actual Windows Electron development and unsigned unpacked app checks passed
  username-first authentication, same-origin iframe password fill, hidden CSRF,
  control replacement, expired sessions and a repeated run: exactly two posts,
  zero wrong credentials and zero query leaks. MFA produced
  `skipped-needs-foreground`, with no guessed code or extra submission.
- Real Playwright and Chrome isolation round trips produced
  `LIVE_JOB_BACKENDS_OK: Playwright + Chrome; posts=2; saved-login=1; shared connection preserved`.
  Foreground tabs survived scope close. Chrome remains excluded from desktop
  scheduled jobs per the user's backend decision.

The app verifier's model responses are scripted HTTP/SSE fixtures; its browser,
vault, UI and scheduler are real. Public anti-bot/OAuth/passkey flows are not
covered by those fixtures. Separate real-provider results, exact commands and
remaining limits are in the [assistant scheduling ledger](plans/assistant-scheduling-security-implementation.md).

### Live-provider findings and hardening

- A worker advertised Chrome while its runtime permitted isolated Chromium. The
  real model selected `mode=local` and failed. Background schemas now advertise
  only isolated Chromium; foreground Chrome retains its original choices.
- A real model selected a text field and a button in `fill_form`. Before the fix,
  the first value changed and the button then failed. Whole-batch target preflight
  now rejects the call with fresh refs and zero field writes. A separate regression
  changes a second control after the first write and proves the resulting error
  stays incomplete rather than recoverable.
- Live attempts also omitted the login URL, guessed a password and printed a
  pretend tool call as final text. Missing login URLs now bind the actual selected
  tab; saved-password fills stay private, including shown-password controls.
  Printed tool markup requests one bounded native-tool correction, and repeats
  or exhausted tool loops cannot produce successful job receipts.
- Review reproduced Chrome's nonthrowing dialog-interruption response and custom
  ARIA toggle support. Real MCP checks now show `CHROME_CUSTOM_TOGGLE_OK` and
  `CHROME_INTERRUPTED_FORM_OK`; an interrupted batch is never reported fully filled.
- Concurrent guard/scheduler cleanup previously closed the same context twice
  (`2 !== 1`). Cleanup now detaches captured resources and shares a pending close;
  reopening waits for cleanup. The focused hardening suite passed `16/16` in
  `.commandcode/scheduled-browser-hardening.log`.

## Scheduled completion and watched-tab selection — 2026-09-28

The supplied Instagram run stopped at 63,472 recorded tokens against a
model-chosen 60,000-token daily ceiling. Regular desktop tasks now record usage
while running until completion; explicitly bounded tasks and Heartbeat retain
their configured limits. Stop, no-progress detection and human-input boundaries
remain available. The details and editor show the actual execution prompt.

Watching another job tab previously retargeted the worker and invalidated its
refs. A real Chromium reproduction read `/one` instead of `/two`. Independent
preview selection now preserves the worker's selected page and original refs;
completion proof captures that worker page independently of the watched frame.
The same live reproduction passed after the fix, including a click using the
original ref and distinct watched/proof screenshots.

A live model put a submit button into `credential_fields`, and the schema
rejection stopped its scheduled run. This now returns fresh refs and fixed
guidance before vault access or any fill. The rebuilt app's two complex login
runs deliberately reproduce that mistake, then correct the native call and
complete exactly two posts; origin and uncertain-action failures still stop.

The rebuilt unsigned Windows packaged app completed both complex login runs
with exactly two posts, survived navigation to Plugins while running, exceeded
the old token ceiling and remained enabled. Real-provider results, commands,
artifact paths and uncovered public-site behavior are recorded in the
[scheduled completion verification](plans/scheduled-job-completion-fixes.md).
