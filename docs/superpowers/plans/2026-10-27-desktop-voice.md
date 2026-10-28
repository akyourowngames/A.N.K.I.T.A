# Desktop Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved full voice panel and floating-island voice experience using real Sarvam/Meta work.

**Architecture:** One main-process coordinator owns audio and a bound desktop thread. Existing desktop turns remain the source of model/tool/approval/history truth; shared voice helpers supply the planner override, task tracking, narration and concise speech. Both renderers consume the same bounded snapshot, with an original responsive orb and caption transitions.

**Tech Stack:** Existing Node/Electron, React/TypeScript, CSS, WebGL with CSS fallback, ffmpeg/ffplay; no added dependency.

**Spec:** `docs/superpowers/specs/2026-10-27-desktop-voice-design.md` (approved); static reference `desktop-voice-preview.svg` in the same directory.

## Global Constraints

- Worktree `feat/desktop-voice-orb` starts from committed PR #70; source checkout/demo documents remain untouched.
- Sarvam STT/TTS, configured Meta Muse Spark planner through Baseten, native API-backed desktop threads only in this pass.
- One/two spoken sentences; preserve the separate 4096-token default generation allowance and output-limit guard.
- Main owns one microphone/player across main/island; no raw keys in renderer, no CSP weakening or new dependencies.
- End voice closes mic/playback while delegated work continues; Stop work cancels the task; selecting another conversation ends voice without moving its work.
- Existing approval, redaction, task receipts, transcript and theme/accessibility behavior remain authoritative.
- Input-level motion follows real measured input; REST finalized text is not presented as live interim STT.
- No release, version bump or merge. Physical microphone/workspace demonstration remains a separate open gate.

## Review Focus

- Late STT/TTS or task completion after end/restart must not reopen a mic or play old speech (Task 2 tests).
- Main/island remount and minimize/restore must preserve one session and one submitted request (Tasks 2/4 tests).
- Switching/deleting threads and permission prompts must keep actions attached to their original owner (Tasks 2/3 tests).
- Muting, empty/silent input, dependency/device failures and WebGL loss must leave visible recovery controls (Tasks 1/2/4 tests).
- Hidden windows, long Hinglish/Hindi text, keyboard/reduced-motion use must remain readable without idle GPU/audio leaks (Tasks 4/5 checks).

---

### Task 1: Shared voice state and audio signals

**Files:** Create `desktop/shared/voice.mjs`, `desktop/shared/voice.d.mts`; modify `src/channels/voice.mjs`; test `test/desktop/voice-state.test.mjs`, `test/channels/voice.test.mjs`.

**Interfaces:**
- `VOICE_ACTIONS` names for status/start/end/pause/resume/cancel/show-main.
- `VOICE_EVENT` state-event discriminant; `emptyVoiceState()` returns `{sessionId,threadId,active,paused,phase,caption,captionRole,update,inputLevel,task,error,microphone}`.
- `voiceStatePatch(state,patch)` clamps levels, bounds display text and retains identifiers.
- `listMicrophones()` discovers runtime device names; `detectMic(preferred)` reuses it.
- `openVoiceInput(options)` keeps its handle/ready/stop contract and optionally emits `{type:'level',level}` from measured ffmpeg RMS metadata alongside existing silence events.

- [x] Write state tests asserting clamped levels, bounded captions, safe defaults and unchanged immutable input.
- [x] Write audio parser tests for mixed RMS/silence chunks, `-inf`, malformed levels and the optional filter flag preserving old capture.
- [x] Run focused tests and confirm new behavior fails before implementation.
- [x] Add named voice state/size/rate policy constants, parser and optional metering.
- [x] Run `node --test --test-concurrency=1 test/desktop/voice-state.test.mjs test/channels/voice.test.mjs`; all pass.
- [x] Commit shared contract and audio signals.

### Task 2: Main-process session coordinator

**Files:** Create `desktop/electron/voice.mjs`; test `test/desktop/voice.test.mjs`.

**Interfaces:** `DesktopVoice({engine,getConfig,emit,directory,io})` exposes `snapshot()`, `start({threadId})`, `end()`, `pause()`, `resume()`, `cancelWork()`, `close()`. IO is injectable for hardware-free tests and defaults to existing voice channel exports. Engine contract: `runVoiceTurn(threadId,text,observer,brain) -> Promise<{text,error}>`, `cancel(threadId)`, thread existence/busy checks and captured approval observation.

- [x] Write lifecycle tests: one capture/session; finalized transcript -> real run observer -> short speech; pause prevents restart; barge-in stops reply and submits once.
- [x] Write stale-callback tests: end/restart during STT, synthesis, progress or pending approval cannot act on the new session.
- [x] Write continuation tests: end closes audio but leaves work; cancel aborts work; empty input recaptures; failures stop input and show recovery.
- [x] Write cross-surface snapshot tests: a second start on the same thread reuses the session; another thread cannot silently take over; deleted owner ends session.
- [x] Run tests red, implement the coordinator with captured session/turn controllers, existing ack/narrator/task/brain helpers and bounded meter events.
- [x] Run `node --test --test-concurrency=1 test/desktop/voice.test.mjs`; all pass.
- [x] Commit coordinator.

### Task 3: Desktop engine, settings and IPC

**Files:** Modify `desktop/electron/engine.mjs`, `desktop/electron/main.mjs`, `desktop/electron/settings.mjs`, `desktop/shared/wire.ts`, `desktop/shared/version.mjs`; tests `test/desktop/voice-engine.test.mjs`, existing settings and engine fixtures.

**Interfaces:** Engine exposes lazy `voice()` coordinator, `voiceStatus()` readiness/device/snapshot view and `runVoiceTurn` from Task 2. Existing `send` gains private voice/observer options so its promise remains the one task execution path. IPC maps `VOICE_ACTIONS`; public events include typed voice snapshot updates. Settings add Sarvam/Baseten keys and microphone preference via existing local API-key storage patterns, exposing only presence flags to renderers.

- [x] Write tests asserting voice override through tools, restored native provider/style, third-argument tool verdict forwarding, existing transcript/file receipts and approval pause.
- [x] Write tests rejecting browser-provider voice, busy/nonexistent thread, unsafe/oversized payloads and settings changes that would invalidate a live session.
- [x] Write settings tests: env keys work, explicit saved values win, public view never includes keys, mic selection persists.
- [x] Run tests red; implement engine adapter/IPC/settings without duplicating model execution or routing typed requests through voice.
- [x] End voice when its thread changes/deletes; close coordinator during shutdown. Preserve in-flight work when end merely stops audio.
- [x] Run focused engine/settings suites and build; all pass.
- [x] Commit engine/settings bridge.

### Task 4: Orb, captions, full panel and island

**Files:** Create renderer `components/voice/VoiceOrb.tsx`, `VoiceCaptions.tsx`, `VoicePanel.tsx`, `VoiceSettings.tsx`, `useVoice.ts`, `voice.css`; modify `App.tsx`, `ChatPane.tsx`, `Island.tsx`, `Icons.tsx`, `SettingsDialog.tsx`, `island.tsx` and related island geometry only as needed; add `test/desktop/voice-ui.test.mjs` and browser fixture script `scripts/verify-desktop-voice-ui.mjs`.

**Interfaces:** `useVoice()` subscribes to `VOICE_EVENT`, loads a late-subscriber snapshot and calls typed `VOICE_ACTIONS`. `VoiceOrb({phase,inputLevel,compact})` owns only rendering. `VoicePanel({voice,onEnd,onPause,onResume,onCancel,onIsland,onSettings})` displays real state and controls. Island uses the same hook/orb; no renderer opens audio devices.

- [x] Write UI fixture assertions for exact latest text, clear listening/working/speaking/error states, controls, long Hindi captions and no model reasoning/tool dumps in the panel.
- [x] Add checks for main/island snapshot handoff, keyboard escape/focus, reduced motion and WebGL fallback.
- [x] Run fixture red; implement approved layout, original sphere, bounded animation, caption transitions and one task update.
- [x] Wire selected conversation start and voice settings; changing selection ends voice rather than moving ownership. Island approval UI takes precedence.
- [x] Build and run browser fixture at wide/narrow sizes, reduced motion and WebGL unavailable; capture screenshots of main and island.
- [x] Critique screenshots against the approved preview and fix actual spacing/contrast/control issues.
- [x] Commit polished voice surfaces.

### Task 5: Real desktop verification and review

**Files:** Update `docs/guides/voice-delegation.md`, hackathon plan and this execution checklist; add live desktop voice verifier only where existing scripts cannot exercise the engine.

- [x] Run relevant serial channel/core/automation/desktop suites plus `npm run desktop:build` and `git diff --check`.
- [x] Run real configured model/Sarvam/file tool round trips through desktop adapter; no key/log/media artifacts staged.
- [x] Open the actual desktop runtime with isolated test data, inspect full-panel/island behavior and capture actual rendered evidence. Keep simulated mic/playback clearly labelled.
- [x] Record physical mic, headset/barge-in and packaged limits honestly; do not replace the owner's three-clean-workspace gate with fixtures.
- [x] Request independent whole-branch review, resolve important findings with regressions, update evidence and commit.
- [x] PR #70 updated with desktop integration and progress fixes at `10691a03`;
  still open/draft, base `ankita`. No default-branch merge or release.

## Baseline evidence

- Existing desktop build passed in this worktree before product edits (Vite build 10.18 s).
- PR #70 full repository suite is running; existing website tests have reported missing `/App.tsx` SSR input. Investigate baseline/source ownership separately; do not label the entire run green or silently repair unrelated website content.
- Execution method: native in this session, with independent review. The owner approved the design and said to build it; no further execution-method approval is needed.

### Owner follow-up: accurate progress and overlapping tasks (28 October)

- [x] Reproduce late progress: a started write update can still be prepared after
  the write finished and the next action began. Record the failing trace.
- [x] Supply bounded action context and confirmed result states without file
  contents, command arguments, raw results or secrets in the narrator request.
- [x] Keep only the newest pending progress update, finish a sentence already
  playing, and drop obsolete preparation before playback. Final reports retain priority.
- [x] Add completion/context and delayed-preparation regression checks; run real
  configured narration and file-path checks.
- [x] Explain and exercise simultaneous completion/session ownership.
  Session isolation passed. The owner explicitly requested parallel execution
  for voice, superseding both offered serial policies; implement this separately
  with isolated workers, ordered speech and resource-conflict coverage.
- [x] Re-run affected serial tests/build/UI, update evidence, and include the fixes
  in draft PR #70 without merging or releasing.

The new parallel-voice request supersedes the old one-turn-at-a-time limit and is
tracked in its own 28 October design/plan. The completed desktop/progress snapshot
is preserved in PR #70; the follow-up will update the same draft.
