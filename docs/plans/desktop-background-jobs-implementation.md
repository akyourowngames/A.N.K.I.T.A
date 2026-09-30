# Desktop background jobs implementation

Plan: [desktop-background-jobs-plan.md](desktop-background-jobs-plan.md).
Implemented scope: P0–P2. P3 (watches, heartbeat nudges, true-Quit sidecar and
Today digest) remains deferred. User-facing guide: [Scheduled desktop jobs](../guides/desktop-jobs.md).

## Scope and decisions

- **Desktop only.** No edits or connections to the sibling mobile application.
  Hosting, IPC, permissions, UI and credentials belong to Electron. Shared cron,
  routine storage and browser contracts remain usable by existing CLI code.
- User selected **isolated Chromium for background jobs** on 2026-09-27. Chrome
  background parity in the original plan is superseded. New/updated local-mode
  routines are rejected; legacy local jobs settle as needing foreground. The
  existing Chrome backend remains available for foreground work.
- Existing branch `ankita` had uncommitted browser/vault/Telegram work. This
  implementation depends on it and preserves it in the same workspace; no
  release, push or unrelated mobile change is included in this task.
- Runtime checks enforce the same routine permission before tools, navigation
  redirects and Fetch/XHR dispatch. The network guard attaches to this job's own
  Chromium socket, discovered from its private profile. It does not attach to
  user Chrome or spawn an external browser MCP for a job.
- Three-minute active execution excludes a separate one-hour approval deadline.
  Background browser command timers defer to these scheduler-owned deadlines.
- Chat creates disabled drafts; proposed changes and enable requests open the
  permission sheet. Human Save activates them. Runtime Always applies only to
  that routine. A step grant does not authorize later writes.
- Restarted runs are interrupted, never replayed. Overlap records busy; bounded
  catch-up runs once; old fires record missed. Only receipt delivery retries.
- Terminal receipts replace resolved approval cards; the redacted run audit
  retains the approval decision. The original plan's separate greyed historical
  approval-card UI is not added. Single-flight fires do not supersede an active
  waiting run; they record skipped-busy.

## Implementation map

| Phase | Delivered |
|---|---|
| P0 | Additive legacy normalization; timezone/DST cron fire search; Daemon dispatch/chain/drain reuse; serial fresh Agent workers; runtime ownership; durable, queued, idempotent owner-chat delivery |
| P1 | `schedule*` IPC and event contract; chat draft/update/review flow; readonly `schedule_status`; routine sheet; jobs pill; inline approvals and receipts; owner warning/re-home support |
| P2 | Scoped Chromium/profile isolation; full browser actions and batch step gates; saved-only vault access; request interception; proof limits/retention; cancellation/budgets/deadlines; Watch live; tray hosting and opt-in startup |

Primary files: `desktop/electron/scheduler.mjs`, `src/automation/job-policy.mjs`,
`src/automation/scheduler-ownership.mjs`, `src/automation/cron.mjs`,
`tools/browser/session.mjs`, `tools/browser/job-network-guard.mjs`,
`desktop/electron/engine.mjs`, `desktop/electron/main.mjs`, and the renderer's
`RoutineSheet`, `JobsPill`, `JobCard` and chat/store wiring.

Named defaults: 20-second tick, one job at a time, 30-minute catch-up, three active
minutes per run, one-hour approval deadline, 30 delivered audits/proofs per
routine, 256 KiB encoded proof ceiling, 32 site rules, and daily 48 runs / 50,000
tokens / 60 active minutes. Proof URLs omit credentials, queries and fragments.
Copied proof receipts have the same cap; compact delivery IDs remain for dedupe.

## Reproduce → fix evidence

| Failure reproduced | Change and passing check |
|---|---|
| Redirect reached denied destination despite Playwright routing | Private Chromium Fetch interception before dispatch; actual GET 302, POST 307, popup and cross-site iframe redirects reach safe routes but **zero denied requests** |
| Popup remained unguarded with page-only interception | Attach and pause new page/iframe targets before execution; same real popup repro passes |
| Browser command timeout expired while approval was pending | Background command wait has no competing deadline; fake-clock approval wait beyond 300 seconds passes, plus actual inline approval round trip |
| Foreground completion/cancel declined job approval or disconnected Chrome | Routine approvals excluded from thread cancellation; shared connection preserved while scopes exist; regressions and both real browser adapter checks pass |
| Token ceiling allowed another side effect | Usage failure and runtime pre-step checks stop before mutation; scheduler regression passes |
| Yearly cron search blocked for approximately 11,285 ms | Calendar-day search with actual timezone candidates; yearly/leap-day/impossible cron child-process gate passes below 1,500 ms |
| Empty/truncated lock could not recover | Stale malformed recovery with exclusive guard and atomic heartbeat; regression passes |
| Four separate processes each acquired a recovered dead-owner lock | Deliberately staggered unlink reproduced `acquired, acquired, acquired, acquired`; serialize dead-owner check/delete under the recovery guard; exactly **one acquired** after fix |
| Copied proof receipts grew past history cap | Per-routine copied-receipt retention plus durable delivered IDs; pruning and old-run dedupe regression passes |
| Recovery relaunch exited without releasing ownership | Relaunch uses normal Quit/drain; actual Electron IPC shutdown exits and leaves no scheduler lock |
| Inline approval landed below a welcome hero/viewport | Welcome hidden while pending; bottom-aware scroll includes approval; actual screenshot/bounds check places all buttons above composer |
| Pause changed storage but left Enabled checked; another Save could undo Pause | State-changing buttons update the form after IPC success and surface errors; actual app repro `true !== false` becomes `JOB_EDIT_CONTROLS_OK` |
| Watch live added a duplicate foreground browser card | Foreground transcript excludes job-scoped previews; actual repro `1 !== 0` becomes a zero-card assertion while the live stage still shows real pixels |

## Automated and build gates

- Baseline proactive/daemon suites: **40 passed, 0 failed**.
- Full suite before the final cross-process recovery regression:
  `npm test` → **789 tests; 788 passed, 0 failed, 1 skipped**;
  `duration_ms 185046.9565`.
- Final ownership + desktop scheduler regression gate:
  `node --test test/automation/scheduler-ownership.test.mjs test/desktop/scheduler.test.mjs`
  → **18 passed, 0 failed**; includes four actual child processes and cooperative
  takeover, budgets, orphan delivery, draft review and foreground separation.
- Real request guard gate:
  `node --test test/tools/browser-job-navigation.test.mjs` → **1 passed, 0 failed**,
  `duration_ms 6531.2982`; GET/POST/popup/frame redirects plus a denied Fetch POST.
- `npm run desktop:build` → exit **0**, TypeScript and Vite build passed;
  **327 modules**, build **9.76s**. Vite still reports its existing large entry
  chunk warning (557.58 kB); it is not a failed build gate.
- `git diff --check` → exit **0**.
- Final full-suite rerun after the process-race fix:
  `npm test` → **790 tests; 789 passed, 0 failed, 1 skipped**;
  `duration_ms 210180.6699`. The skipped test checks executable permissions on
  POSIX and is skipped on Windows. Subsequent UI-only fixes use the desktop build
  plus the actual application regression harness below.
- Final UI build: `npm run desktop:build` → exit **0**, **327 modules**, **5.53s**,
  entry chunk **558.00 kB** with the same size warning. After hoisting ownership
  sidecar suffixes, the ownership/scheduler gate again passed **18/18**.
- Literal review: runtime durations, budget/retention/proof ceilings, protocol
  deadlines, sidecar suffixes and debug-endpoint discovery are named constants.
  Storage roots derive from configured paths; the browser port is allocated by
  Chromium. Remaining action/status/property strings are contract values;
  user-facing copy and repository-relative imports/resources describe the app's
  own layout. Synthetic URLs/models/form values exist only in tests/verifiers.
  This task adds no dependency, provider URL, machine path or runtime model pin.

## Actual application round trips

`node scripts/verify-desktop-background-jobs.mjs --keep-artifacts` launches the
actual development Electron app with disposable settings, real Agent and real
headless Chromium. Its HTTP/SSE provider is scripted so assertions are repeatable.
It tests the actual renderer/IPC, not a mocked component tree.

Development trace (exit 0):

```text
DESKTOP_JOB_POST_OK: actual Agent + 6 HTTP/SSE rounds + real headless Chromium + one confirmed form submission + screenshot proof
INLINE_APPROVAL_OK: routine grant persisted; no foreground approval modal; composer remains enabled
CHAT_JOB_ISOLATION_OK: foreground model reply completed while the browser worker was held in a separate turn
TRAY_RELOAD_DELIVERY_OK: close hid the app; job finished in tray; two idempotent proof cards restored after renderer reload
RECOVERY_RELAUNCH_OK: real IPC quit path released scheduler ownership
DESKTOP_BACKGROUND_JOBS_OK: packaged=false; requests=13; posts=2
```

Artifacts: `%TEMP%/ankita-desktop-jobs-7LGz6h` (`inline-approval.png`,
`job-watch-live.png`). The packaged command is the same with `--packaged`; it
builds and starts a disposable `win-unpacked/Ankita.exe` using installed dependencies.
Packaged trace passed all the same gates with **13 provider requests / 2 posts**;
artifacts `%TEMP%/ankita-desktop-jobs-RjENoY`. Screenshots were visually inspected;
the approval uses the existing desktop appearance with visible buttons/composer.
The ownership-fix packaged rerun also exited **0**, with **13 provider requests /
2 posts**, including relaunch ownership release. Artifacts:
`%TEMP%/ankita-desktop-jobs-RuFnfu`. Final UI regression runs are recorded below.

Final development and packaged runs after UI fixes both exited **0**, with
**13 provider requests / 2 posts** and all earlier gates plus:

```text
JOB_EDIT_CONTROLS_OK: Pause and Resume update both durable state and the form
JOB_MANAGEMENT_OK: Pause all stays paused after Save; Delete removes the routine
RECOVERY_RELAUNCH_OK: real IPC quit path released scheduler ownership
```

The live-stage assertion also confirms **zero duplicate foreground browser
cards** while showing a real job screenshot. Final artifacts:
`%TEMP%/ankita-desktop-jobs-U6tRhF` (development) and
`%TEMP%/ankita-desktop-jobs-2lFIJJ` (packaged). The updated live screenshot was
visually inspected. Early verifier attempts had ambiguous label/summary locators;
those fixture selectors were corrected to the observed controls before these
successful runs. They were test-harness failures, separate from the reproduced
Pause and duplicate-card application bugs.

The unpacked fixture lacks publisher `app-update.yml` and logs an updater ENOENT;
the verifier does not test installer update distribution. Code signing is disabled
only for this disposable verification package. It installs/downloads no dependency.

## Real browsers and a real hosted model

`node scripts/verify-job-browser-isolation.mjs` → exit **0**:

```text
SAVED_JOB_LOGIN_OK: real isolated Chromium; selected refs filled; no password prompt or secret receipt
JOB_BROWSER_ISOLATION_OK: isolated; real form submission + preview; user tab survives scope close
JOB_BROWSER_ISOLATION_OK: local; real form submission + preview; user tab survives scope close
LIVE_JOB_BACKENDS_OK: Playwright + Chrome; posts=2; saved-login=1; shared connection preserved
```

Chrome here exercises the shared adapter/scoped-tab contract, not an enabled
Chrome background schedule. Vault selection uses a synthetic saved credential
service and a real page; it proves private field filling, not public-account login
or OS encryption (those have their separate packaged vault verifier).

`node scripts/verify-desktop-job-provider.mjs` reads the configured desktop
provider without copying its credentials to disk. A child process isolates all
memory, browser state and job files. The real hosted model decides the browser
calls, and the fixture accepts only local synthetic submissions. Exit **0**:

```text
LIVE_PROVIDER_STEP: 1
LIVE_PROVIDER_STEP: 2
LIVE_PROVIDER_STEP: 3
LIVE_PROVIDER_STEP: 4
LIVE_PROVIDER_JOB_OK: provider=kilo; model=poolside/laguna-s-2.1:free; browserSteps=4; posts=1; screenshot=true
```

This proves one real model-driven task, with the exact text submitted once and
confirmation/proof. It does not establish reliable automation of every public
site, CAPTCHA, payment or multi-factor flow. No real account action or external
message/post was sent.

Protocol reference used for the private guard:
[Target auto-attach](https://chromedevtools.github.io/devtools-protocol/tot/Target/#method-setAutoAttach)
and [Fetch request interception](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/#event-requestPaused).

## Remaining checks and operational limits

- Real OS lock/unlock was not triggered on the user's session. Locked-visible-job
  behavior is regression-tested; the native event-to-state bridge is read/reviewed.
- Startup at sign-in settings are wired, but an actual Windows sign-out/reboot was
  not performed. Notifications are wired; their OS display/interaction is not part
  of the packaged harness. Minimize is wired; actual close-to-tray is exercised.
- macOS/Linux tray, startup and native events were not exercised. Tests and the
  packaged round trip ran on Windows; this is not a cross-platform release claim.
- Signed NSIS install/update/reboot and Quit during updater installation were not
  exercised; normal Quit/recovery IPC shutdown is exercised.
- Killing a process precisely while it owns the short `.recovery` critical section
  can leave that sidecar. Recovery then refuses ownership rather than risking
  two schedulers. After checking that both hosts are stopped, removing the stale
  `.recovery` sidecar permits another attempt. This rare crash window is not
  auto-reaped or fault-injected in this task.
- A large screenshot can be omitted instead of resized; the URL/text receipt still
  arrives. Delivery IDs grow with completed runs to preserve deduplication.
- Changing the configured timezone requires restarting the scheduler/app; it is
  resolved once for the host, as specified in the plan. Actual sleep/catch-up uses
  the tested nominal-fire calculation; physical sleep was not induced.
- Receipt persistence failure from disk exhaustion/permissions and pathological
  process crashes between separate delivery files are not fault-injected. The
  normal durable retry/reload path is covered; no browser action is replayed.

## Confidence ledger

**Confidence: 91/100.** Base 50; +15 regression/full-suite evidence; +10 real
browser contracts/request gates; +10 actual development app; +10 packaged app;
+5 hosted model task = 100. −2 real OS lock/notification/minimize/sleep not induced;
−2 boot/login launch not exercised; −2 macOS/Linux not exercised; −1 signed installer
update path; −1 rare recovery/disk/crash windows; −1 public-site login/CAPTCHA flows
outside the local verification task = 91. The deferred P3 work and user-selected
Chrome restriction are explicit scope decisions, not claims of implemented parity.
