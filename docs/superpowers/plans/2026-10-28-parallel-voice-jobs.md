# Parallel voice jobs implementation

Binding design: `docs/superpowers/specs/2026-10-28-parallel-voice-jobs-design.md`.
Owner explicitly requested parallel voice execution. Execute inline; no repeated
permission handoff. Base: `10691a03`, completed desktop/progress snapshot in draft
PR #70. No merge or release. Preserve user-created poem/report files.

## Interfaces and review focus

- `VoiceResourceBroker.acquire(jobId, resources, {signal,onWait})`, `release(jobId)`:
  job-scoped canonical path/interaction leases, cancellation and cyclic-wait errors.
- `VoiceSpeechQueue.offer({key,jobId,kind,prepare,signal,beginPlayback})`, interrupt,
  drain/close: one player, latest progress, completion priority, no stale playback.
- `VoiceJobs.submit({ownerId,transcript,...})`, list/result/wait/cancel/close:
  fresh worker per request, existing runVoiceTask persistence, captured context.
- Existing ToolHost receives optional voice-only resource/start hooks and private
  runtime tools. With no hooks/tools, typed/scheduled behavior stays unchanged.
- Shared desktop voice snapshot adds bounded jobs; cancel accepts validated task ID
  or explicit all. Existing single-task snapshot remains compatible.
- Desktop and CLI audio loops dispatch without waiting for worker completion.
  Main/island stay one audio session; terminal uses its existing capture/device flow.

Review cancellation after each await, stale session ownership, same-file aliases,
deadlock and lingering children, tool approval order, private tool isolation,
typed-history delivery races and completed reports queued during user speech.

### Task 1: Resource broker and one speaker

- [x] Write failing tests for disjoint/shared canonical paths, read/write sequences,
  parent/child aliases, cancellation, cycles and opaque interaction serialization.
- [x] Write failing speech tests for simultaneous completion, latest progress,
  interrupted/ended sessions, ordering and no overlap during preparation/playback.
- [x] Implement bounded shared primitives with injected IO and named policy values.
- [x] Run their serial tests and a disposable file/audio-ownership round trip; commit.

Task 1 evidence: **13/13** serial tests pass, no skips. Initial missing primitives
failed 11 tests; dangling-alias and duplicate-report regressions each failed before
their fixes. `node scripts/verify-voice-parallel-primitives.mjs` returned
`VOICE_PARALLEL_PRIMITIVES_OK`: independent file work peaked at **2**, a shared-file
increment ended at **2**, peak players **1**, two distinct reports retained. The
player in this check is simulated; no physical microphone or speaker was used.

### Task 2: Isolated voice workers and controls

Completed: fresh Agents/private tools/resource gates preserve permissions and
isolate histories. Worker/resource/host checks passed **116/116**, including a real
temporary file and a real tracked child confirmed stopped. The earlier manager-only
checkpoint was **64/64**; host/audio/UI wiring is now complete.

- [x] Fail tests proving two requests cannot share mutable history/client/abort state.
- [x] Add voice-only private job-control specs/execution and optional resource/start
  hooks to the existing Agent/ToolHost; test unmodified typed path and permissions.
- [x] Implement bounded job manager, durable IDs, status/results/dependencies,
  individual/all cancellation and process/resource cleanup. Protect active records.
- [x] Run worker/tool-host/core regressions and real file concurrency checks; commit.

### Task 3: Desktop parallel voice and job UI

- [x] Fail a controlled capture test where B must finish while A stays blocked.
- [x] Adapt DesktopVoice/engine to isolated workers, one speaker and idle history
  delivery; keep continuous request acceptance while work is running.
- [x] Add bounded jobs and validated cancellation payloads; keep one audio owner and
  reject stale callbacks after owner switch/delete/end/restart.
- [x] Add active-job rows and per-job/Stop all controls in panel/island with keyboard,
  error/permission priority, reduced-motion/fallback and existing orb preserved.
- [x] Run desktop serial/build/browser/native fixtures; record exact evidence; commit.

### Task 4: Terminal parity

- [x] Fail real CLI fixtures for overlapping jobs, short status/cancel turns,
  queued nonoverlapping reports and unchanged typed provider/history afterward.
- [x] Reuse shared job/resource/speech primitives with fresh workers; dispatch
  spoken work without awaiting it, preserve capture/barge-in and end/exit semantics.
- [x] Keep finished results in the original conversation using an idle mailbox;
  Ctrl+C/cancel and process shutdown clean up their exact owned work.
- [x] Run CLI/core/channel/automation checks and live isolated file tasks; commit.

### Task 5: Evidence and draft PR

- [x] Run affected serial suites/build/whitespace checks. Keep any unrelated full-run
  failure visible rather than saying the whole repository is green.
- [x] Run real Meta/Sarvam/file parallel round trips with synthetic mic/player,
  explicitly test both colliding and disjoint work, and retain physical limits.
- [x] Request one fresh review for this new parallel scope, resolve substantive
  findings with regressions, and record rulings/deferred polish.
- [ ] Update guide/hackathon evidence and PR #70. Feature push only; no merge/release.

Final evidence: **928/928** affected serial checks; desktop build and both-view
browser check pass, zero page errors. Three real Meta/Sarvam/file jobs prove
independent and conflicting work; one fresh review, seven substantive fixes, ten
RED→GREEN regressions. Full details, decisions and remaining limits: hackathon
plan §18i. The same draft PR is the only intended publication.
