# Issue #12: local desktop and server speech

The former desktop implementation opened headless Chrome and polled Web Speech. The API returned an empty placeholder. Both now use `core.speech`, with a reusable faster-whisper CPU worker, bounded audio (60 seconds / 10 MB), and cancellation. The worker is isolated because this Windows installation crashes in PyTorch DLL loading when it shares a process with Qt. Worker failure is reported as a recoverable voice error.

## Run

```powershell
python desktop/run.py --hands-free
python desktop/run.py --hands-free --lang hi --mic-device 1
python desktop/run.py --hands-free --wake-word "Hey Ankita" --barge-in
python desktop/run.py --text-only
```

Without `--hands-free`, click the microphone to begin. Use headphones for `--barge-in`: signal activity interrupts playback before transcription finishes, then the captured utterance becomes the next turn. There is no acoustic echo cancellation in the desktop capture path, so barge-in is disabled by default. Turning the mic off cancels capture and playback. Closing the window signals controller shutdown; voice-triggered close is executed on the Qt event thread.

On first use, wait for “Loading local speech model...” to become “Listening” before speaking. The model stays loaded for subsequent turns. Cold loading has a visible elapsed timer.

Wake activation and natural-language stop/exit intent use the configured chat model with an eight-second request timeout. They use no keyword classifiers. If intent recognition fails, ordinary mode sends the original transcript to chat; wake mode reports the error and waits. The wake option is an LLM-gated speech mode, not an always-on low-power wake engine. STT itself needs no network once the model is cached. Hindi is preserved, without the former online translation step.

The intent gate returns only an action. The original STT transcript always supplies the user message, even if a model unexpectedly returns an answer or rewritten text. This prevents classifier-generated answers from appearing as user speech.

## Settings and diagnostics

`ZUMBA_STT_LANG=auto` is shared by desktop, CLI diagnostics, server and web uploads. `--lang` overrides it in that process. `ZUMBA_STT_MODEL` selects a cached Whisper model or local model directory (default `tiny`; this PC uses multilingual `base`). Leave `ZUMBA_MIC_DEVICE` empty to use the Windows default input. Device IDs can change when hardware is connected; list devices before selecting one.

Leave `ZUMBA_VAD_THRESHOLD` empty for an RMS gate that adapts to ambient input, starting at 0.003 and bounded between 0.002 and 0.012. An explicit numeric value overrides adaptation. Speech onset needs three active frames within five frames, allowing brief gaps. One second of silence ends an utterance; “Transcribe now” finishes earlier. The signal gate detects activity; Whisper recognizes words and the LLM interprets their meaning.

For Hindi and English, set `ZUMBA_STT_LANGUAGES=hi,en` with auto language selection. Whisper chooses from those configured languages using its audio probabilities, rather than silently switching a short question to Portuguese or another language. A fixed `--lang` takes precedence.

```powershell
python desktop/mic_test.py --download-model
python desktop/mic_test.py --list-devices
python desktop/mic_test.py --seconds 6 --lang auto
python desktop/mic_test.py --file tests/fixtures/stt-six-seconds.wav --lang en
python main.py doctor
```

The fixture contains synthetic English speech generated offline with Windows System.Speech, padded to exactly six seconds at 16 kHz mono. Expected text: “Hello Ankita. Please tell me what time it is.” No personal microphone recording is included.

`requirements-desktop.txt` records the already installed faster-whisper 1.2.1 and sounddevice 0.5.5 versions. The Sonatype dependency check could not complete because its connector lacked authentication; these versions were not certified safe by that check. Repeat that dependency check manually when the connector is authenticated.

## API and browser

POST a `file` multipart field to `/api/voice/stt` for JSON `{transcript, language}`. Add `?stream=true` for SSE `start`, `partial`, `done`, or `error` events. Partials are emitted as recognition progresses after upload. Desktop captures an utterance and decodes it once, emitting partial segments during that decode. It no longer schedules repeated snapshot jobs ahead of final recognition. Invalid audio returns 400, oversized uploads 413, unavailable recognition 503. Stream errors are explicit events.

`/ws/voice` accepts base64 `audio_chunk_b64` fragments of one encoded recording followed by `{finish:true}`; it emits the same recognition events. Send the resulting transcript to the chat API for an answer. `/api/voice/config` exposes the shared language and recognizer configuration.

Browser input uses MediaRecorder on HTTPS or localhost. Clicking the mic again finishes recording, with an automatic stop after 59 seconds. Tracks are released on completion, failure and unmount. Audio is recognized by the server rather than a browser vendor's speech service.

Cloud fallback is opt-in: set `ZUMBA_STT_CLOUD_URL` to an OpenAI-compatible transcription endpoint, with `ZUMBA_STT_CLOUD_KEY` and `ZUMBA_STT_CLOUD_MODEL`. The server attempts local inference first; only a local recognition failure triggers an upload to that configured endpoint. Leave the URL empty to keep recognition local. No cloud fallback was called during validation.

## Verification

```powershell
python -m pytest tests/test_desktop.py tests/test_local_stt.py -q
# Include the cached-model integration check:
$env:ZUMBA_TEST_LOCAL_STT = '1'
python -m pytest tests/test_desktop.py tests/test_local_stt.py -q
```

These cover local transcript/language handling, silence and invalid audio, microphone speech onset and release, cancellation, semantic wake/exit routing, API errors, streaming, WebSocket transcription, cloud opt-in, native-worker failure and the six-second offline fixture. GUI tests render offscreen. Real microphone speech quality and acoustic feedback require a live user test.

## Voice-routing correction (September 14)

The reported input substitution was reproduced against the live model: the old intent gate returned answers in its `text` field, and the controller used that field as user input. The gate now exposes only `action`, and the controller always forwards the unchanged STT transcript. Regression tests inject fabricated classifier answers and verify they cannot reach the user-message channel.

Transient post-tool provider failures now get a bounded text-answer recovery attempt using existing results, without executing tools again. Plain chat uses bounded retries as well. An exhausted provider failure is displayed as an error and is not saved as an assistant answer in cross-chat memory. Provider availability remains outside the application’s control.

Validation: 42 focused tests passed, with the optional full cached-model fixture test skipped in that run. The cached multilingual model separately transcribed the six-second fixture correctly. Live English questions and a Hindi identity question preserved their inputs and received answers; one real upstream 503 occurred during the initial Hindi check, followed by a successful retry check. The four corrupted desktop exchanges were removed from session history and the chat log; other saved conversations were retained.

Implementation references: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [sounddevice stream usage](https://python-sounddevice.readthedocs.io/en/0.5.5/usage.html).

## Desktop mic controls and stage diagnostics (September 14)

Home and Chat share a persistent control panel. “MIC OFF · Enable” means capture is disabled; “MIC ON · Mute” means continuous listening is enabled. A separate indicator distinguishes actual capture from pauses for model loading, transcription, replies, and playback. Muting cancels capture and playback; rapid off/on clicks invalidate the previous capture so its transcript cannot become a new turn. “Transcribe now” submits the current recording without waiting for silence.

The panel shows the input device, live RMS meter, threshold, recorded duration, last recognized words, current stage with elapsed time, and a bounded timestamped stage history. Stages cover device lookup, model loading, opening the mic, listening, recording, transcription, intent classification, context, tool connection, model requests/retries, tool execution, speech generation, playback, and reopening the mic. Empty recognition, device silence, capture failure, and playback failure are visible; the last error remains available after listening resumes. Diagnostics stay in memory and do not write audio or transcript logs to disk.

The Home animation now fits the remaining window space, keeping the controls visible at 1280 × 720. Recognition uses a lighter cached multilingual base model on this PC: the six-second fixture took 5.86 seconds and 3.92 seconds in two warm runs, with a 15.69-second initial load. These timings vary with CPU and memory pressure. The free Kilo chat model and Hindi/English language restriction are unchanged.

Validation: 50 focused tests passed, with one separate opt-in fixture test skipped. A full fixture run through desktop capture, real base recognition, real Kilo routing/reply, and actual speaker playback preserved the whole question and finished without an error. That first cold round trip took 72.7 seconds including 20.9 seconds loading STT, 19.5 seconds connecting tools, and playback; this is not an end-to-end low-latency claim. A separate Qt run opened the real Windows-default Airdopes 181 Pro input, received 32 audio frames, and verified that mute released capture. Real user Hindi/English speech accuracy still needs a live user check.
