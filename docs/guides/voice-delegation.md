# Voice in and out (Sarvam)

## Desktop voice

Choose a conversation, then **Voice** in its header. The full panel shows an
original dark-pearl orb, the latest finalized words and one work update. Use
**Continue in island** to minimize the app and keep the same voice session in the
floating companion. **Open conversation** returns to that session's owner.

- **Pause microphone** stops recording; **Resume microphone** starts it again.
- **End voice** stops microphone and speech. Already delegated work continues
  in the original conversation, with its report and saved task steps.
- Each job row has its own **Stop** button. **Stop all** cancels all voice jobs
  in that conversation; ordinary typed and scheduled work keep their own controls.
- Selecting another conversation ends voice. Existing permission prompts still
  require an answer and take priority over the island's voice view.

Open **Settings → Voice** for Sarvam/Baseten keys and discovered audio devices.
On Windows, select **Speakers**, save, then use **Test speakers** to hear a short
real Sarvam reply. The test uses the same saved output routing as voice, without
starting a planner or job. A successful player exit does not establish audibility;
if nothing is heard, choose another output. Laptop speakers were heard in the
29 October owner test; Airdopes Hands-Free was not. Its physical headset path
remains unconfirmed. Automatic mode keeps the existing system/HFP routing.
Other systems use their system output.

Speaker and unknown-output playback uses turn-taking: the microphone closes
before audio plays and reopens after a short buffer/echo drain. This prevents
Ankita's own reply from becoming another job. Windows-reported headphones/headsets
retain voice interruption only after native monitoring confirms the actual output.
Changing or disconnecting audio devices stops current speech and overlapping
recording, then protects the rest of that session; start a new session to confirm
headphones again. If device classification or monitoring is unavailable, voice
uses protected turn-taking. This is not acoustic echo cancellation; speaking over
a speaker reply is intentionally not recorded. Pause/End/Stop controls still work.

Device discovery and routing run in one lazy background worker, shared across the
main app and island. Reopening settings within five seconds reuses a scan; Refresh
forces a new scan. Normal app startup only reads voice state and does not launch
audio probes. A cold OS scan can still take seconds, but it no longer blocks the
main process. Independent voice jobs retain their existing concurrency limits;
this change does not create another worker/thread per job.

An explicit speaker choice temporarily changes Windows output during voice/test
playback. Console, music and call defaults are restored separately afterwards;
later manual changes are respected. Setup changes and speaker tests wait until
voice ends. Settings follow changes from the island too. Restart desktop dev after
updating the main-process audio code; a renderer refresh alone is insufficient.
Existing environment keys work too. Saved desktop values override them.
Keys use the app's existing private local API-key settings file; this is not a
promise of encrypted storage. Public settings expose presence flags only.
Voice uses Sarvam and the configured voice planner; typed-chat settings stay
separate. ChatGPT Browser conversations do not support this desktop voice path.

The orb follows measured microphone RMS while recording. Its speaking motion
shows actual playback state, not a claimed output-audio measurement. Captions
appear after REST transcription completes; there are no fabricated interim words.
Motion respects reduced-motion settings and stops in hidden windows. WebGL loss
uses a static CSS fallback.

The final orb is smooth dark pearl with a soft silver edge, the owner's final
28 October choice. There is no mesh or liquid distortion. Listening follows the
mic level; recognition and working have distinct moving rim lights; speaking
gently pulses; a completed task flashes once. Failed work cannot show that success
pulse. Both surfaces share the material and state cues. Rendering is capped at
30 frames per second and 640 pixels per axis; reduced motion stays still and hidden
cues pause, including fallback. No reference image or new dependency ships.

Repeatable checks, from a source checkout:

```bash
node --test --test-concurrency=1 test/desktop/voice-state.test.mjs test/desktop/voice.test.mjs test/desktop/voice-engine.test.mjs test/desktop/voice-ui.test.mjs
npm run desktop:build
node scripts/verify-desktop-voice-ui.mjs
node scripts/verify-desktop-voice.mjs --env /path/to/your/local/.env
```

For an audio/settings-only change, use the focused desktop/audio tests and
`node scripts/verify-desktop-voice-ui.mjs --settings-only` after the desktop build.
That fixture checks real field geometry, saved speaker/test IPC actions, live
session locking, and 1280/620/390-pixel layouts. Audio is stubbed in that browser
fixture; use **Test speakers** for real playback.

Measure real device-scan responsiveness without speech or cloud requests:

```bash
node scripts/verify-desktop-audio-performance.mjs
```

Add `--env /path/to/local/.env --play` for a quiet-room check with a real microphone,
Sarvam reply and speaker playback. It uses a discovered non-private output, creates
no planner work, restores output choices and checks that no feedback reached
transcription. The script prints timing/receipt fields, never API keys. See the
[record and limits](../plans/2026-10-29-desktop-audio-performance.md).

The last script uses real configured Sarvam/Meta services and file tools inside
Electron with disposable app data. Microphone/VAD are generated fixtures and the
MP3 player handoff is captured without speaker playback. This does not prove
physical headset duplex, interruption accuracy, packaged deployment or the
owner's three-clean-workspace gate. In a generated Hinglish take, Sarvam heard
“Markdown” as “mark count”; the simpler saved-poem request tests the file path,
not recognition of that technical noun.

Desktop voice was built in a separate worktree from PR #70, then added to the same
PR under the owner's instruction to include all pending work. On 29 October the
owner reported the voice flow working and approved integrating PR #70. The app
version stays unchanged; this does not publish a new packaged release. Starting
voice is done in the app; the island continues that session and can retry it after
an error. The owner's acceptance is not a measured three-run microphone record.

Verification record, 28 October: focused channel/desktop/settings/native-control
checks passed **175/175**; the desktop build, browser main/island fixture and real
Sarvam/Meta/file Electron check passed. The last full tracked-source run reported
**1635 tests: 1633 pass, 1 fail, 1 skip**. Its only failure was Windows `EPERM`
during the unchanged browser-observations fixture's temporary-folder cleanup;
both observations passed, and rerunning that same file passed **2/2**. This is
not an all-suite-green claim. At that earlier checkpoint the pull request stayed
draft for physical acceptance; the owner subsequently approved integration on
29 October. A minor polish gap remains: the collapsed island uses its ordinary
status text; expand it to see the actual voice phase and caption.

Earlier parallel follow-up: **928/928** affected serial checks, no skips; desktop
build and both-view browser checks pass with zero page errors. Three real
Meta/Sarvam/file jobs prove independent completion, shared-file waiting and one
player. The fresh review found seven substantive issues, now covered by ten
failing-before/passing-after regressions. Physical and packaged limits above remain.

### Checked final replies and tool visibility

Before a final voice reply appears or plays, the active voice planner checks it
against the original request and actual requested/started/result receipts. If
work was skipped or the reply overclaims it, the same worker gets one chance to
finish the remaining work. Completed actions are retained. A second unsupported
ending, an unavailable check, or a spent work budget ends honestly as unfinished.
Discovery, a checklist or memory lookup alone cannot prove external work finished.
This applies across native and connected tools, rather than matching music words.

Fresh workers copy already-discovered tool groups without sharing their mutable
state or inheriting focus. Other groups remain available through discovery; the
normal permissions, context limits and enabled-plugin settings still apply.

The check adds one compact model request for each candidate final reply, including
conversation. Its usage is counted. The deadline covers token preparation and the
request; cancellation drops late replies. Oversized requests fail safely, while an
overlong report gets one chance to become concise instead of being silently clipped
for approval. Older context/results can be omitted or clipped with explicit flags.
The checker can still misjudge meaning; it is not a guarantee that every claim is true.

Repeatable live checks use the configured Meta key and disposable browser profiles:

```bash
node scripts/verify-voice-tool-execution.mjs --env /path/to/your/local/.env
node scripts/verify-voice-tool-execution.mjs --env /path/to/your/local/.env --youtube-only
```

The default check uses a silent local media player in both browser backends, a
real file/read-back and a conversation. The optional public YouTube check can fail
on login, ads, network or playback restrictions; it independently inspects the video
state rather than trusting the spoken report. Neither proves sound in a headset.
See the [29 October repair record](../plans/2026-10-29-voice-tool-execution.md).

### Accurate work updates and overlapping tasks

Work updates are generated, not a fixed script. The short initial acknowledgement
is cached. Each generated update now receives safe action names, file/program
basenames, and the observed starting/completed/failed/submitted states. File bodies,
full paths, command arguments and raw results stay out of this extra model request.
Saving a file and requesting an editor launch are different facts: a launch receipt
does not prove the window opened. The model is explicitly told this distinction.

Only the latest unplayed update is kept. If a step finishes while its speech is
still being prepared, that preparation is cancelled. A sentence already playing
finishes cleanly; permission and final reports take priority over queued updates.
Very quick steps may have no spoken update rather than a late, incorrect one.
Narration has its own small output allowance and a three-second deadline; a slow
optional update is skipped without delaying the task or final report.

Voice now accepts another request while earlier jobs work. Each request gets a
fresh worker, its own cancellation and captured conversation/workspace. The same
Meta planner can check live jobs, retrieve a report, wait for needed findings or
stop a named job. Typed-chat concurrency and provider selection are unchanged.
`VOICE_MAX_PARALLEL_JOBS` defaults to **4** (configurable **1–8**), with one extra
status/stop-only turn when all ordinary workers are occupied.

Independent files run together. Conflicting file paths wait for the job holding
them, including read/modify/write sequences and known path aliases. Structured
Git operations protect their enclosing repository, even from a subdirectory. Browser/native
app actions and opaque connected interactions share exclusive access. Shell
commands hold the workspace and app access conservatively; a tracked command still
running after its report retains that access until it exits or is confirmed stopped.
Long-lived shell-launched apps can therefore keep later app/file jobs waiting.
These guards coordinate participating voice jobs, not arbitrary external programs
or unchanged typed/scheduled jobs. They do not undo actions already completed.

All reports use one speaker. Interrupted reports can wait their turn; progress
cannot play after its step becomes obsolete. Ending voice keeps results in the
original conversation and prevents its old session from speaking over a replacement.
Completed results enter a typed conversation only when it is idle, as complete
request/report pairs. Worker tool steps stay in their separate task records.
Terminal permissions briefly pause capture and take typed yes/no answers.
Typed and voice requests share one prompt owner, so an answer cannot go to a
different background request. Ctrl+C stops active voice work; with none running, it ends voice.
Clearing/loading a terminal chat keeps earlier work's results in its own saved
`voice-<owner>` conversation rather than appending them to the new chat.

If a successful planner response has neither text nor actions, voice retries that
unexecuted decision once, keeping the existing tool receipts and remaining actions
available. It does not restart the task or append an empty assistant turn. The
recovery budget is one across the entire request. A second blank decision reports
a distinct provider-empty error; access, quota and output-limit failures keep their
own errors. Ordinary typed requests retain their existing policy. The earlier
report-only recovery could strand work after a blank intermediate decision; the
28 October follow-up replaces it.

A failed read-only source with other useful results is shown as **Partial result**,
with the failed step preserved. A failed write, denied action or planner error
remains failed. Open a job row for its result, gap and completed-action count.
Request names wrap to two lines, and the list scrolls within reserved space so
work updates and controls cannot overlap at shorter window heights.

Additional repeatable checks:

```bash
node scripts/verify-voice-suite.mjs
node scripts/verify-voice-parallel-primitives.mjs
node scripts/verify-parallel-voice.mjs --env /path/to/your/local/.env
node scripts/verify-voice-second-request.mjs --env /path/to/your/local/.env
node scripts/verify-voice-second-request.mjs --env /path/to/your/local/.env --inject-empty
```

The live parallel check uses real Sarvam STT/TTS, Meta planning and file tools.
An intentionally held first file proves an independent job finishes and a
conflicting edit waits without losing the poem. It captures three actual MP3
handoffs with peak one player. Generated input receives explicit fixture filenames
after STT; this is not a physical microphone or perfect filename-recognition claim.

The second-request check uses two real concurrent Meta workers, actual web search
and disposable files. `--inject-empty` discards one unexecuted model decision after
the research save, then checks that read-back still finishes. This is controlled
fault injection over real services, not a claim that Baseten emitted the injected
blank reply. Neither version records the microphone or launches an editor.

## Interrupting a spoken report

Speaking stops the current audio immediately after the existing echo guard. Once
transcription arrives, the same Meta planner uses the interrupted report, the
sentences already delivered and the ready results to decide what you mean. There
is no list of trigger phrases and no extra classifier request.

- A new question or task leaves the old report suspended. It is not reread after
  the new reply; its work and saved result remain available.
- A noise-only interruption with no transcript resumes the unfinished sentence.
  Completed sentences are not repeated. Audio has no word alignment, so the
  interrupted sentence can restart.
- Ask naturally to continue, repeat, skip the spoken result or hear the next ready
  report. Skipping speech never cancels work. Only an explicit work cancellation
  uses the separate job control.
- Ambiguous words depend on context: “okay, then what?” can mean continue or move
  on. No system can guarantee every interpretation; the planner can ask when the
  intended choice is unclear. This build does not infer intent from loudness.
- Pausing the microphone preserves the report. End voice closes audio and its
  speech controls while delegated work continues in its original conversation.

Terminal, app and island share the same report rules and one player. Cached short
sentence clips track delivery, with at most one following sentence prepared ahead.
A late older planner cannot change a newer interruption's speech selection.
The planner also states whether it still owes a separate answer: skipping a report
and asking a question preserves that answer. Missing that decision keeps the reply
audible. Checking job status or finding tools alone does not add a redundant
confirmation; real work and cancellation still keep their result. A cancelled
speech choice is checked again after the owned player stops.

Repeatable cloud check:

```bash
node scripts/verify-voice-interruption.mjs --env /path/to/your/local/.env
```

The 28 October run passed six generated English/Hinglish requests through real
Sarvam STT/TTS and Meta speech controls. The expanded 29 October check also covers
skipping a report while asking a separate question. Ambiguous “okay, then what?”
may cause a selection or a short clarification; the prompt asks for clarification
when the choice is unclear, without a phrase list. These are sampled decisions,
not a universal interpretation guarantee. During repeats, one planner reply stayed
empty after its recovery attempt and one generated Hinglish phrase was misheard;
the check failed honestly. A clearer code-switched next-report fixture was used
without changing production recognition. Another repeat had the correct next-report
transcript but the planner chose resume. Intent decisions remain probabilistic;
this is a known acceptance risk, not a perfect-language claim. Output was captured sentence MP3
handoffs with peak one player. Physical echo, real interruptions and a packaged
app remain separate checks. With your headset, interrupt a report with a new
question, then ask to continue the earlier report; also test a cough and mic pause.

## Terminal voice

Ankita can listen and answer out loud in Hindi, Hinglish or English. Speech-to-text
and text-to-speech run through **Sarvam AI**, which handles code-switched Hinglish far
better than an English-first recogniser.

Voice capture, pause detection, barge-in and playback already existed. What changed for
the hackathon is the engine behind them, plus a fix to the startup gate that used to
demand a Groq key even when voice ran elsewhere. The old engines are still installed:

| Layer | Default (unchanged) | This build | Back to old |
|---|---|---|---|
| Ears | Groq Whisper | Sarvam `saaras:v4` | `STT_PROVIDER=groq` |
| Voice | Edge TTS (keyless) | Sarvam `bulbul:v4-flash` | `TTS_PROVIDER=edge` |

## One-time setup

Two keys go in `.env`, never in chat and never in git:

```
SARVAM_API_KEY=...        # dashboard.sarvam.ai — ₹100 of free credit, never expires
STT_PROVIDER=sarvam
TTS_PROVIDER=sarvam
```

Check what the app actually resolved:

```bash
node chat.mjs --config
```

You want `STT_PROVIDER sarvam`, `TTS_PROVIDER sarvam`, and `SARVAM_API_KEY (set)`.
That screen prints only whether a key exists, never the value.

## Test 1 — no microphone (30 seconds)

### Faster voice-only replies

Keep your usual typed-chat settings and add these local settings:

```dotenv
VOICE_PROVIDER=baseten
VOICE_MODEL=meta-models/muse-spark-open-1026
BASETEN_API_KEY=...
VOICE_SILENCE_MS=800
```

The voice planner uses low reasoning effort. It reserves enough output tokens for
reasoning before the spoken answer. A short acknowledgement is prepared when voice
mode starts, then played from memory while the planner works. It means "I heard you",
not "the work is done". The answer still takes time to plan and speak.

The 800 ms pause is local to this demo setup; the shipped default stays 1200 ms.
If it cuts off a natural pause, increase it again. Missing Baseten credentials stop
voice mode with a message; they do not silently select a non-Meta planner.

If a key was exposed in chat, rotate it in the provider dashboard and replace it
locally. Never paste it into a conversation.

### Modal DeepSeek planner (opt-in, not faster today)

The same voice-only slot can point at a self-hosted Modal deployment:

```dotenv
VOICE_PROVIDER=modal
MODAL_BASE_URL=https://<workspace>--<deployment>.us-west.modal.direct/v1
MODAL_PROXY_TOKEN_ID=...
MODAL_PROXY_TOKEN_SECRET=...
```

The two proxy parts are joined into one bearer token for you. `MODAL_MODEL`
defaults to `deepseek-ai/DeepSeek-V4.1-Flash-1017`; `MODAL_REASONING_EFFORT`
defaults to `low` because this deployment rejects `minimal` with HTTP 400.

Measured 2026-10-28: on short prompts without tools Modal was faster (408 ms vs
657 ms to first token), but on a real voice turn carrying 30 tool schemas it was
slower (3,414 ms vs 2,593 ms transcript to player). Keep Baseten unless the Modal
deployment gains prefix caching or more prefill capacity. Full numbers and the
re-run commands are in
[docs/voice-planner-benchmark-2026-10-28.md](../voice-planner-benchmark-2026-10-28.md).

### Speech round trip

```bash
node scripts/verify-sarvam-voice.mjs
```

This speaks a Hinglish line, converts the audio to exactly the 16 kHz mono WAV the
microphone recorder writes, transcribes it back, then speaks a reply in the chosen
voice. It prints a table of timings, the transcript and the chosen reply language, and
exits non-zero if the words did not survive.

Use it after any change to the voice code, and once before filming.

## Test 2 — with your microphone (the real gate)

```bash
npm start
```

Then, inside the app:

1. `/voice` — starts hands-free listening.
2. Say: **"Ankita, VS Code kholo aur mera workspace set up karo."** Pause. The pause
   sends the turn; you do not press Enter.
3. The transcript prints as `yourname › Ankita, VS Code kholo...` **before** anything
   runs. Read it. If it is wrong, press Ctrl+C immediately, then re-record. Displaying
   the transcript does not itself pause execution or prove that the words are correct.
4. A saved voice-task card appears. Its steps come from real tool calls. The normal
   action approval prompt still decides whether work may proceed; `/auto off` enables
   those prompts if your setup currently approves automatically.
5. Ankita speaks the final report. A declined or failed action is reported as failed,
   even if the planner claims success. The record remains available after a restart.
6. Say `exit` to leave voice mode, or talk over the final reply to interrupt it (barge-in).

Three clean runs in a row is the gate before any filming. A take that shows a misheard
word is never usable, however good the rest looks.

### Other voice commands

| Command | What it does |
|---|---|
| `/voice` | Hands-free loop: pause to send, barge-in, spoken replies |
| `/task` | List saved voice requests (separate from shell-process jobs) |
| `/task <id>` | Show the transcript, steps, status and final report for one request |
| `/say <text>` | Speak one line aloud — the fastest way to judge the voice |
| `/speak on` / `/speak off` | Read every typed reply aloud |
| `--voice` | Start straight into the voice loop |

`/say` is the quickest sound check: it skips transcription entirely, so if it sounds
wrong the problem is the voice, not the ears.

### Full service check without a microphone

```bash
node scripts/verify-voice-delegation.mjs
```

This runs three generated Hinglish requests through Sarvam, the Meta planner, real
file-writing and reading tools, saved task records, and a generated spoken report.
It checks the key command words and reads the file back. It uses a temporary folder
and automatically approves only its own test file writes. `--planner-only` skips
speech services; `--play` plays the prepared audio so you can judge the voice.

This is a service check, not a recording of a person speaking. It never clears the
physical mic/VS Code gate. Its acknowledgement timing measures selecting prepared
audio from memory, not when sound reaches your ear.

### The three-run mic gate

Start Ankita, enter `/voice`, then say the workspace request above. Repeat it with
three different folder names so each take does real work. A clean take requires:

- The transcript matches the command you spoke.
- VS Code opens and the requested files really appear.
- The final voice report agrees with the visible result and sounds clear in Hinglish.
- The saved request shows the actual completed steps.

If a take fails, fix the cause and restart the count. Keep one English backup take.
Do not film a mishearing or substitute the generated-audio check for this gate.

## What "working" looks like

- Transcript appears within about a second, and the command words (VS Code, workspace,
  folder names) are right.
- The reply is spoken in a natural Indian voice, and Hindi replies use the Hindi voice.
- Nothing hangs: every failure prints a line and leaves you in the app.

Times measured on this machine, per call: speech out **0.8–1.5 s**, text back
**0.25–0.5 s**. A demo take costs about ₹0.40; 60 takes stay inside the free ₹100.

## When it goes wrong

| What you see | Meaning | Fix |
|---|---|---|
| `voice needs SARVAM_API_KEY ...` | No key for the selected engine | Add the key, run `/voice` again — no restart needed |
| `Sarvam STT 403: key rejected` | Key deleted, rotated or wrong | New key in `.env` |
| `Sarvam STT 429` | More than 60 requests a minute | Wait a moment; it retries once on its own |
| `VOICE_PROVIDER=baseten needs BASETEN_API_KEY` | Missing planner key | Save the key locally, then enter voice mode again |
| `403: API error 403` | Planner rejected the key/model route | Check the key and pinned model; the failed request stays saved |
| `The model hit its output limit ...` | A generated answer or file did not fit the allowance | Restart after this update; default `BASETEN_MAX_TOKENS` is now 4096. If explicitly set smaller, increase it before retrying |
| Voice task is `cancelled` | Work was stopped | Read its partial steps before retrying |
| `no microphone found` | Windows cannot see a mic | Check Settings → Privacy → Microphone, or set `MIC_DEVICE` |
| Transcript is right but silent | Speaker or Bluetooth routing | Desktop: Settings → Voice → Speakers, save, then Test speakers; try laptop output first. Terminal: `/say hello` |
| Wrong word, again and again | Recognition, not the code | Speak a bit slower; add the word to `SARVAM_KEYTERMS` |
| `Edge TTS handshake failed: HTTP 403` | The backup voice service rejected this connection | Keep Sarvam configured; the result still prints if both voices fail |

## Known limits, stated plainly

- **Words can be misheard.** "Ankita" came back as "Anpeta" once despite keyword hints;
  a later test phrase "demo note" was also misheard. The final generated-audio check
  preserved "workspace" and "file" in all three takes and now checks those words.
  The transcript is shown first for visibility, not as proof it is correct.
- **The detected language label drifts** on Hinglish — the same clip was labelled Hindi,
  Hindi, then Punjabi. The words were always right. The spoken reply therefore follows
  the reply's own writing, not the label.
- **Audio leaves the machine** when you speak. Sarvam's retention terms are not
  documented on the pages consulted, so do not claim otherwise in public material.
- **Recording over 30 seconds** is outside the documented limit for the REST
  endpoint; the app sends one utterance at a time, so this only matters if the pause
  detection is disabled.
- **Voice jobs run in parallel.** Keep speaking while earlier work runs, or ask
  for status and a specific cancellation. Say `exit` to end audio while work
  continues; Ctrl+C stops active voice jobs. Typed chat retains its own turn policy.
  Participating voice jobs coordinate shared files/apps; external work does not.
- **Saved tasks are bounded.** The latest 20 are kept under the configured user
  storage folder; `VOICE_TASK_LIMIT` changes that count. Configured keys and
  credential-shaped text are hidden in the saved records. Raw tool arguments and
  results are not copied into those records.
- **Progress speech is optional.** Updates are spaced by
  `VOICE_JOB_SPEAK_MIN_INTERVAL_MS` (2500 ms by default). The voice model writes a short
  update from your request and the actual action, without receiving file contents or
  the conversation's memory. It does not read tool labels aloud. These optional model
  calls use extra provider usage and run alongside the work.
- **Sentences finish cleanly.** A line already playing finishes before an approval or
  final report; `VOICE_SPEECH_GAP_MS` adds a 300 ms pause. Outdated speech still being
  prepared is dropped. Ctrl+C stops speech immediately; a stuck progress player has
  a 15-second ceiling. Slow preparation cannot hold a completed job open.
- **Long work gets a reminder.** Every `VOICE_JOB_WAIT_UPDATE_MS` (10000 ms by default),
  active work can generate a brief update saying it is still underway. No reminder
  runs while waiting for approval. Updates never promise an invented finish time.
  A failed, late or overlong narration response is skipped; the final report remains.
- **Voice mode is quiet on screen.** Internal reasoning, raw arguments and repeated
  counters are hidden by default. The transcript, spoken updates and final report
  remain. `/task <id>` shows the recorded steps; `VOICE_VERBOSE=on` restores debugging
  output. Typed chat keeps its existing display.
- **Replies stay brief.** Voice asks the model for one or two short sentences:
  the answer or work result, with essential failures and permissions. Longer requested
  content belongs in its file or artifact. If the model rambles, final speech still
  stops after two sentences, including Hindi sentence endings. The full result stays
  printed and saved. Typed chat and `/say` keep their existing settings.
- **Files have a separate allowance from speech length.** The planner can use up to
  `BASETEN_MAX_TOKENS` (4096 by default) for reasoning and tool arguments, including
  file contents. The old 1024-token default could stop a save before it produced a
  write request. A cut-off request now fails clearly and is never executed partly.
- **Reply preparation overlaps.** The chosen microphone is discovered once per voice
  session and refreshed after a device failure. Final speech preparation and
  interruption-input startup run together. A three-turn service check measured
  2.16–3.02 seconds from transcript to audio-player handoff, compared with
  3.61–4.69 seconds before. This skips real recording/playback and does not include
  pause detection, transcription or physical headset latency.

To check generated English/Hinglish updates without opening the microphone:

```bash
node scripts/verify-voice-delegation.mjs --narration-only
```

To measure real model/speech preparation without recording or playing audio:

```bash
node scripts/verify-voice-latency.mjs
```

To check a longer Markdown save using real tools in temporary folders:

```bash
node scripts/verify-voice-delegation.mjs --planner-only --long-report
```

The microphone startup is simulated in that check; repeat the live headset test
before claiming a speech-to-ear timing. The full generated-speech/file check most
recently passed two takes and misheard a command noun on the third, so the physical
three-clean-take gate remains open.

Add `--play` only after leaving any other listening voice session, so Ankita does not
mistake the test speaker audio for a new request. A running terminal needs restarting
to load code changes.
