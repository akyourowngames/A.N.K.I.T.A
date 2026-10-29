# Desktop audio responsiveness and feedback — 29 October 2026

## Observed problem and bounded scope

The owner reported hangs opening Voice settings/testing speakers, then reported
speaker audio being recognized as another user request. These are real runtime
bugs. Work continues on PR71 in its clean tracked worktree; separate dirty source
checkout changes and personal text files are excluded. Existing voice jobs remain
parallel. No thread-per-job redesign, dependency addition, release or merge.

Reproduction: two concurrent `DesktopVoice.status()` calls, real installed
ffmpeg/ffplay and Windows Core Audio, with a 20ms main-thread heartbeat. Before:
`AUDIO_STATUS_BASELINE {"wallMs":11916,"maxMainThreadPauseMs":8208,"heartbeatTicks":3,"callers":2}`.
Audio endpoint queries/switches used synchronous PowerShell/C# compilation in
Electron's main thread; executable probes were synchronous too. Main and island
also requested hardware scans just to observe voice state. The orb already caps
GPU work and pauses hidden animation; no speculative orb/thread changes were made.

## Implementation

- One lazy Node worker owns blocking executable/Core Audio probes and switching.
  Main-thread calls await results. Scans are single-flight and cloned per caller;
  five-second cache, explicit Refresh invalidation, routing/event invalidation.
  App/island observers use `voiceSnapshot`, so normal startup creates no scan.
- Async End handles dependency discovery and in-flight routing without allowing a
  replacement session to steal output. Worker shutdown rejects new probes/routes.
  Routing receipts retain previous roles and changed roles outside the worker,
  survive worker restart, and remain available if restoration needs retry.
- Speakers/unknown outputs close capture before playback, wait 300ms after player
  completion for output/room echo, then resume. Headphone interruption requires a
  Windows endpoint form factor and fresh actual-output monitor confirmation.
  No brand names, microphone name keywords or spoken phrase blacklist determine
  safety. Non-Windows/unknown classification conservatively uses turn-taking.
- Native `IMMNotificationClient` notifications run in one hidden helper during
  private-output sessions: no polling/repeated compilation. Any device/default
  change or monitor failure immediately interrupts speech, stops capture,
  invalidates overlapping/pending transcript by revision and enables protection
  until the next session. End removes the monitor before restoring output.
- Native PROPVARIANT union includes a BLOB member to give correct ABI size on
  x64/x86. The former undersized structure returned empty numeric properties;
  the corrected live probe reports Realtek/virtual speakers=1, headset=5,
  headphones=3. Type definitions follow Microsoft's
  [form-factor documentation](https://learn.microsoft.com/en-us/windows/win32/coreaudio/pkey-audioendpoint-formfactor)
  and [SDK header](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/mmdeviceapi.h).

## Evidence

- New pending-dependency/routing tests failed before async integration, passed
  after. Speaker echo regression failed with “microphone must close before sound
  leaves speakers” before the guard, then passed. A real worker CPU fixture
  demonstrates main-thread timers continue and concurrent calls share one scan.
- Initial after sample: wall9341ms, main pause192ms, 234 heartbeat ticks, warm1ms.
  Later repeatable script: `AUDIO_PERFORMANCE_OK {"wallMs":3840,"maxMainThreadPauseMs":31,"heartbeatTicks":121,"callers":2,"warmStatusMs":1,"workerRequests":1}`.
  Cold hardware scan still takes seconds; it is background work, not eliminated.
- Actual Electron main, imported after app.whenReady in a disposable profile:
  `AUDIO_PERFORMANCE_OK {"runtime":"electron","wallMs":4799,"maxMainThreadPauseMs":99,"heartbeatTicks":143,"callers":2,"warmStatusMs":2,"workerRequests":1}`.
  An initial direct ESM harness awaited app.whenReady before module evaluation
  completed and was stopped; using the ready callback resolved that fixture-only
  startup deadlock. These are separate local runs, not a controlled hardware SLA.
- Real Sarvam + laptop mic + ffplay speaker session:
  `SPEAKER_ECHO_GUARD_LIVE_OK {"output":"Speakers/Headphones (Realtek Audio)","played":1,"transcripts":0,"jobs":0,"listeningResumed":true}`.
  The fixture asserts capture is closed before sound, then checks resumed input
  for 700ms. It does not call a planner or execute user tools.
- Real native default change after monitor registration:
  `OUTPUT_CHANGE_WATCH_LIVE_OK {"initialIsolated":true,"changes":2}`.
  All original role defaults were restored afterwards. Controlled controller
  tests also cover changes during speech and pending transcription.
- Real output switch, forced worker termination, receipt recovery and exact
  role-default read-back: `WORKER_RESTORE_RECOVERY_LIVE_OK`.
- Final affected serial group: **115 tests, 115 pass, 0 fail, 0 skip**,
  18609.0396ms. Includes channel/native selection, worker, voice lifecycle,
  parallel jobs, IPC, state and UI contracts. A stale speech test originally
  asserted the next sentence before its playback; it now waits for both actual
  sentences. The initial intermediate group was 101/102; fixed reruns passed.
- Desktop typecheck/build: **403 modules**, exit0. Full main/island renderer
  fixture: `DESKTOP_VOICE_UI_OK`, **0 page errors**; remount, parallel rows,
  ownership, reduced motion, WebGL fallback, keyboard and recovery checks pass.
  Settings-only 1280/620/390px fixture also passed after the snapshot split.
- Review found startup-only output isolation, lost worker receipts and failed
  restore retry. All addressed. Restore retry was RED (receipt count0 instead
  of1), then GREEN. Final review reports no Critical/Important findings;
  independent 46/46 checks before retry hardening and 4/4 worker checks after.

Shared worker operation strings were hoisted after that group; focused worker
and live discovery reruns are recorded in the PR. Full project suite deliberately
not repeated at the owner's request. Packaging patterns include both worker and
shared files; no new packaged-app launch was performed.

## Limits and follow-up

This fixes the demonstrated audio UI blocking and feedback path; it is not a
whole-app low-end hardware certification. Physical headset hot-unplug, non-Windows
hardware, ASAR worker startup and long sessions on other machines remain untested.
Native notifications have scheduling latency; this is protected turn-taking plus
device monitoring, not full acoustic echo cancellation. Speaker interruption is
intentionally unavailable while audio plays. A complete app/process crash can
still prevent restoration before a routing receipt reaches its owner; normal
worker restart after receipt delivery is covered. Restart desktop dev to load
main-process changes. No full suite, merge or release in this follow-up.
