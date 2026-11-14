# Everyday voice controls — 2026-11-06

Implemented the controls portion of the everyday-assistant voice brief. Streaming
speech remains separate coordinator work; this report does not claim that goal is
complete.

## Behavior and changed paths

- `desktop/shared/voice.mjs`, `.d.mts`: whole-utterance local control vocabulary,
  bounded public report targets/turns, actual headphone interruption availability,
  and the `voiceSpeechControl` action. Public state excludes report text/audio.
- `desktop/electron/voice.mjs`: status reads real voice jobs/results without a
  planner; pause listening, stop speaking, continue/repeat/skip report run before
  delegation. Mixed requests such as “pause Spotify” retain normal planning.
  A continuation without a speech target remains a planner request. Temporary mic
  pauses retain the unfinished report for the Resume microphone button.
- `desktop/electron/voice-actions.mjs`: validates action payload shape and bounds;
  the audio owner checks session, interruption turn and report existence. Speech
  controls never cancel a task or approve pending work. Speaker capture gating
  and headphone route-change protection remain in place.
- `desktop/renderer/src/components/voice/{VoicePanel.tsx,useVoice.ts,voice.css}`:
  separate Stop speaking, Continue/Repeat/Skip report controls, truthful speaker
  fallback/headphone interruption copy, and an explicit paused-microphone hint.
  Suspended speech remains selectable ahead of other queued reports.
- Regression coverage: `test/core/voice-commands.test.mjs`,
  `test/desktop/{voice.test.mjs,voice-state.test.mjs,voice-controls-ui.test.mjs}`.

Control/action strings live in shared named protocol constants. Phrase maps are
deliberately exact vocabulary, not substring patterns. New status labels/error
copy and the spoken-status row limit are named constants. Public queue-state
strings are the existing queue protocol; CSS dimensions are presentation values.
Reviewed the owned diff for introduced literals and ran the whitespace gate.

## Executed evidence

Before implementation, the focused new checks produced `tests 4`, `pass 1`,
`fail 3`: local matcher/method were missing and a status question made a second
planner request. After implementation that same command produced `pass 4`,
`fail 0`. The browser checks first failed because Stop speaking did not exist.
An additional queue-focus regression failed when a queued report hid Continue;
it passed after prioritizing the suspended report. Spoken microphone pause also
reproduced a missing report resumption, then passed after retaining its tentative
interruption. A bare continuation without reports reproduced swallowed work,
then passed after leaving that request to the planner.

Focused regression command:

```text
node --test --test-concurrency=1 test/core/voice-commands.test.mjs test/desktop/voice-state.test.mjs test/desktop/voice.test.mjs test/desktop/voice-engine.test.mjs test/desktop/voice-ui.test.mjs test/core/voice-report-control.test.mjs test/automation/voice-speech-queue.test.mjs
tests 124; pass 124; fail 0; duration_ms 31446.9465
```

One additional spoken-control integration regression was then added and executed:

```text
node --test --test-concurrency=1 --test-name-pattern="spoken stop, continue" test/desktop/voice.test.mjs
tests 1; pass 1; fail 0; duration_ms 2226.7399
```

It records one original planner request while spoken stop, continue, skip and
repeat operate on its real report, with zero work cancellations.

Renderer/service-boundary command:

```text
node --test --test-concurrency=1 test/desktop/voice-controls-ui.test.mjs
tests 3; pass 3; fail 0; duration_ms 22900.3675
```

These use real React components, `useVoice`, `runVoiceAction`, `DesktopVoice`,
`VoiceJobs`, disk task receipts and the speech queue, with injected microphone,
speech synthesis/player and task execution. Both normal and compact panels
complete Stop/Continue/Skip/Repeat and mic pause/resume; a third case checks report
selection with concurrent results. Controls add zero planner calls. Screenshots
were inspected at 1000×900 and 480×650; captures live in the system temporary
folder under `ankita-voice-controls-review`, outside the repository.

```text
node node_modules/typescript/bin/tsc --noEmit -p desktop/tsconfig.json
exit 0
git diff --check
exit 0
```

## Coordinator integration and remaining limits

The coordinator wired `onSpeech={voice.speech}` into both existing VoicePanel callers:
`desktop/renderer/src/App.tsx` and
`desktop/renderer/src/components/Island.tsx`. Those callers are outside this
subtask's edit ownership. The hook accepts `(action, id?)` and captures the current
session/turn. Main already dispatches `Object.values(VOICE_ACTIONS)` through the
existing dispatcher; no new main-process wiring is needed.

Spoken controls still wait for the existing transcription service, and any new
spoken status still needs speech synthesis; “local” means zero planner calls.
Speakers intentionally cannot hear interruptions during playback. A paused
microphone cannot hear resume. Local control vocabulary is English; unmatched
language/mixed requests remain with the normal planner. Status covers this voice
conversation's actual voice jobs. Other everyday-task sources need coordinator
integration. No live provider/key checks, physical microphone/headset trials,
packaged-desktop check or full-repository suite were performed.

**Confidence: 92/100.** +125 focused regressions; +3 renderer/service round trips;
+typecheck, whitespace gate and visual review; −physical audio/cloud untested;
−packaged desktop/full suite untested; −full-app caller acceptance remains coordinator-owned.
