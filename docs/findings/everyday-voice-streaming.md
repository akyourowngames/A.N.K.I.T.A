# Everyday voice streaming — 2026-11-07

Implemented supported early speech delivery in the desktop voice conversation.
This extends the existing local voice controls; it does not claim physical audio
acceptance or streaming recognition.

## Reachable behavior

- Reports, progress narration and local spoken status use the configured Sarvam
  model, language and speaker with its documented HTTP binary MP3 endpoint.
  Preparation waits for the first actual chunk, then the existing speech queue
  sends chunks into the native player's stdin while the response is still open.
  The queue also prepares the following sentence during current playback.
- Repeating a completed report reuses its audio. An interrupted sentence reopens
  its stream; already delivered sentences retain their cursor. Ending voice,
  interrupting a report or losing the native player aborts the owned cloud
  request. Late chunks and old sessions cannot publish delivery state or play.
- Speaker playback still closes capture before audio reaches the player and
  retains the echo-settle delay. Headphone interruption and route-change guards
  are preserved. No AEC or unprotected speaker full-duplex is claimed.
- Unsupported stream HTTP status/content type before the first audio uses the
  working buffered Sarvam request. Authentication/rate-limit failures stay
  errors; partial-stream failures never replay the phrase through fallback.
  Hosts injecting only buffered IO retain that runtime with an explicit fallback.
- Main and compact voice panels display observed streaming/buffered/cached
  delivery and measured request-to-first-chunk milliseconds. Recognition still
  uses the completed recorded clip; copy says words appear after a pause. No
  invented interim text or speedup percentage is shown. Cached receipt clips and
  the explicit speaker-test button retain their existing buffered behavior.

## Owned changes and integration

`src/channels/voice.mjs` adds `synthesizeSarvamStream` and `playMp3Stream`, plus
abort propagation for buffered Sarvam synthesis. Both transports retain the
configured model/speaker and the existing bounded text chunker. Node streams,
fetch and the installed native audio binaries suffice; no dependency was added.

`src/channels/voice-stream-clip.mjs` prepares a replayable clip descriptor, keeps
complete audio only for bounded report history, and couples prepared requests to
both the queue and current native player. `src/core/voice-session.mjs` now passes
the per-sentence queue signal as the optional second synthesis argument.

`desktop/electron/voice.mjs` consumes these helpers in real report/progress/status
speech. `desktop/shared/voice.mjs` and `.d.mts` expose only a bounded `delivery`
object with mode, capability-fallback reason and nonnegative first-chunk timing;
private audio, provider errors and credentials do not cross IPC.
`desktop/renderer/src/components/voice/VoicePanel.tsx` renders the observed state.
No App/Island/main/engine/worker wiring or settings change is required.

## Provider contract checked

Official primary documentation was read before implementation:

- [HTTP TTS streaming guide](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api/http-stream)
  and [REST stream reference](https://docs.sarvam.ai/api-reference/text-to-speech/convert-stream):
  one POST with configured text/model/language/speaker, subscription-key header
  and binary MP3 bytes. The existing smaller per-request cap is retained.
- [Realtime STT guide](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming):
  interim transcripts require the realtime WebSocket endpoint and its audio/event
  protocol. This task preserves the configured recorded-clip path and does not
  relabel final-only transcription as streaming.

## Executed evidence

Test-first baseline: the six new provider/player/clip checks produced `tests 6;
pass 0; fail 6` because streaming APIs were absent. Three desktop consuming-path
checks then produced `tests 3; pass 0; fail 3` before desktop integration. The
same checks pass after implementation. Further cases cover source failure,
already-cancelled buffering, next-sentence stream preparation, completed repeat
cache and player cancellation of a separately prefetched request.

Focused command (serial, existing and new speech/queue/session/control paths):

```text
rtk proxy node --test --test-concurrency=1 test/channels/voice-streaming.test.mjs test/channels/voice.test.mjs test/core/voice-stream-clip.test.mjs test/core/voice-session.test.mjs test/desktop/voice-streaming.test.mjs test/desktop/voice-state.test.mjs test/desktop/voice.test.mjs test/automation/voice-speech-queue.test.mjs test/core/voice-report-control.test.mjs
tests 162; pass 162; fail 0; duration_ms 20579.9376
```

Renderer/service boundary (real React, hook, dispatcher and DesktopVoice, with
injected microphone/synthesis/player/planner):

```text
rtk proxy node --test --test-concurrency=1 test/desktop/voice-controls-ui.test.mjs
tests 4; pass 4; fail 0; duration_ms 13690.6239
```

Both normal and compact panels complete speech controls and microphone pause /
resume with zero added planner requests. The fourth check exercises real event
delivery for streaming timing, runtime buffering and provider fallback copy.

```text
rtk proxy node node_modules/typescript/bin/tsc --noEmit -p desktop/tsconfig.json
exit 0
rtk git diff --check
exit 0
```

### Live configured speech journey

```text
rtk proxy node scripts/verify-voice-streaming.mjs
credentialsPresent: sarvam=true, baseten=true, groq=true
desktopReport: done
delivery: mode=streaming, fallback="", firstChunkMs=567
chunks=4, bytes=21315, firstConsumedMs=26
streamedIntoNativeDecoder=true, decodedWavBytes=42710
transcript="Voice streaming is ready."
microphone="injected synthetic input", speakers="never played", ok=true
exit 0
```

The real desktop capture/delegate/task/report path sent a synthetic phrase to
the configured Sarvam service. Actual native streaming player stdin was routed
to an ffmpeg WAV decoder, and configured Sarvam STT transcribed that generated
audio. No person's speech was recorded and no audio played through speakers.
`firstChunkMs` measures the real provider request to first chunk;
`firstConsumedMs` starts when native decoding begins after preparation and is
not an end-to-end latency claim. Temporary audio and task files were removed.
The first sandbox request failed with `fetch failed`; the successful run used
the required approved escalation, without exposing credentials.

## Remaining acceptance limits

Provider streaming and native decoding are real; microphone/headphone/speaker
hardware is injected. Physical hearing quality, Bluetooth routing, real acoustic
interruptions, packaged installer behavior and the full repository suite remain
uncovered. Baseten/Groq credentials were presence-checked only in this speech
journey; this is no claim of a new planner or alternate-vendor speech check.
Speech recognition remains recorded-clip REST with no live partial transcripts.
No comparative latency improvement is claimed from this single live sample.

Literal review: service endpoint, capability statuses, MIME validator, request
timeout and private clip identity are named documented constants. Existing
speech setup/empty-text errors are shared. Public mode strings and HTTP/stream
arguments are protocol values; visible text is named copy. Fixture request,
phrase, sample rate and wait bounds are isolated in the live verifier/tests.

**Confidence: 93/100.** +real configured streamed speech/native decode/STT round
trip; +focused cancellation/queue/lifecycle and renderer/service regressions;
+desktop typecheck and whitespace review; −physical audio/installer untested;
−full suite unrun; −recognition intentionally remains buffered.
