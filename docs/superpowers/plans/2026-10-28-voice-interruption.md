# Voice interruption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Interrupt speech without forcing old reports to replay, and let the existing planner select the next speech action.

**Architecture:** Extend the shared single-player queue with bounded sentence cursors, suspended reports and turn tokens. Bind a private report-control tool into fresh voice workers; terminal and desktop supply the captured audio session and resolve false versus real interruptions.

**Tech Stack:** Existing Node ESM, Sarvam, Baseten, Electron and Node tests. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-28-voice-interruption-design.md`

## Global Constraints

- Owner approved hybrid flow and requested implementation; execute inline without a repeated permission handoff.
- Keep speech and delegated work lifecycles separate. No phrase list, classifier call or provider migration.
- Resume at unfinished sentence, not a claimed exact word. One owned player; stale sessions/tokens cannot act.
- Work in the existing isolated voice branch; preserve all user documents and original-checkout speed edits.
- Update draft PR70 only; no merge, tag, release or new dependency.

## Review Focus

1. A late former planner must not dismiss/resume a newer interrupted report.
2. Interrupt between TTS preparation, player startup and final sentence/gap; no completed report duplication.
3. More than one suspended report, report retention and session close must settle promises and release cached audio.
4. Permission prompts and manual mic pause must not be mistaken for a new request or cancel delegated work.
5. Speech-only controls must not create duplicate acknowledgments, while mixed speech/work requests still speak their real final result.

### Task 1: Suspended reports and sentence playback

**Files:** Modify `src/automation/voice-speech-queue.mjs`, `src/core/voice-session.mjs`, `src/automation/voice-task-policy.mjs`; test `test/automation/voice-speech-queue.test.mjs`, `test/core/voice-session.test.mjs`.

**Interfaces:** Queue `interrupt() -> token`, `acceptTurn(token)`, `falseInterruption(token)`, `finishTurn(token)`, `releaseTurn(token)`, `reportState()`, `controlReport(action,{id,turn})`. Report items accept sentence `parts` and a turn token. A shared report-item builder maps short sentences to cached preparation functions.

- [ ] Add failing tests: genuine interruption keeps A suspended while B plays; false interruption resumes only unfinished sentence; repeat/next/dismiss; stale turn; interrupt during prepare/gap; bounded retained reports and close; peak players one.
- [ ] Run `rtk proxy node --test --test-concurrency=1 test/automation/voice-speech-queue.test.mjs test/core/voice-session.test.mjs`; expect new behavior failures before implementation.
- [ ] Implement the bounded queue state machine and sentence-item builder, retaining single-clip callers.
- [ ] Run the same command to green and execute a disposable captured-player report round trip; commit.

### Task 2: Context-aware planner control

**Files:** Create `src/core/voice-report-control.mjs`; modify `src/core/voice-worker.mjs`, `src/automation/voice-task.mjs`, shared policy; test `test/core/voice-report-control.test.mjs`, worker/tool tests.

**Interfaces:** `createVoiceReportControl({queue,turn,signal}) -> {tool,context,handled}`; optional captured `speech:{queue,turn,signal}`. Worker outcome `speechHandled` suppresses duplicate speech only for successful speech-only controls; starts of substantive work release the arbitration hold.

- [ ] Add failing tests using real Agent/HTTP/file boundaries: contextual next/resume/repeat, no phrase dependency, private session tools, stale-token refusal, capacity allowance and mixed work retaining its report.
- [ ] Run `rtk proxy node --test --test-concurrency=1 test/core/voice-report-control.test.mjs test/core/voice-worker.test.mjs test/core/voice-worker-tools.test.mjs test/automation/voice-task.test.mjs`; expect missing control behavior.
- [ ] Bind the private tool and bounded current speech context into the existing planner turn, with no classifier; preserve cancellation, permissions and typed hosts.
- [ ] Run the same command to green; commit.

### Task 3: Terminal/desktop integration and evidence

**Files:** Modify `src/core/cli.mjs`, `desktop/electron/voice.mjs`; test existing CLI/desktop voice files; create `scripts/verify-voice-interruption.mjs`; update voice guide/hackathon evidence.

**Interfaces:** Both hosts capture one queue turn per utterance; empty/no transcript restores that turn, valid speech accepts it and supplies the private control. Completion resolves the matching hold atomically with report offering. Manual pause preserves the report; End closes speech, not work.

- [ ] Reproduce old A replay in desktop/CLI fixtures; cover false transcription, stale completion after another interruption, permission/manual pause, owner switch/End and speech-only versus mixed results.
- [ ] Run focused host checks RED then implement both adapters and run them GREEN.
- [ ] Run real Meta/Sarvam control/sentence fixture, desktop build/browser checks and serial full project tests; name physical/package gaps.
- [ ] Run one fresh branch review, resolve substantive findings in one tested pass, record rulings/deferred polish; update docs and draft PR70 without merging.
- [ ] Final task command: `rtk proxy node scripts/verify-voice-suite.mjs`; commit, preserve worktree, remove only this plan's ignored scratch workspace after recording evidence.
