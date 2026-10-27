# Desktop voice for Ankita

Status: design for review; product implementation has not started.

## Owner request and authorization

The owner wants the terminal voice work published as a pull request, with all
pending committed heartbeat/phone-pairing work included, no merge or new release.
That is PR #70. This separate worktree/branch starts from its committed head.
Generated `poem.txt` and `php-vulnerabilities-2026.md` remain in the source checkout
and are excluded from both streams.

The owner now explicitly requests desktop integration before the earlier calendar
gate. They chose both a separate full voice panel inside the app and compatibility
with the floating island: a strong animated orb, words appearing/disappearing with
motion, and polished controls. This authorizes the desktop work stream; it does not
mean the earlier three-clean-workspace demonstration passed. That evidence gap stays
recorded. No existing app chrome, protected reference artwork or brand assets are
replaced.

## Purpose

Make the judge's first voice interaction immediately understandable: Ankita hears
the request, visibly works, and gives a short spoken answer. The same session follows
the owner into the floating companion while they use other apps. A beautiful orb
must convey real state, not hide a stalled model, muted microphone or failed task.

## The visible experience

Start voice from a clearly labelled microphone button in the selected conversation.
The selected teammate/project remains the owner of the request. A focused panel
fills the conversation area while preserving the app's navigation. It contains:

- A restrained header: teammate identity, return to chat, and Continue in island.
- One large, original pearl/glass orb with ice-blue and lilac currents. This is the
  memorable visual; the rest of the panel stays quiet.
- A plain phase label: Getting ready, Listening, Transcribing, Working, Speaking,
  Permission needed, Paused or an actionable error. Text accompanies every color.
- The latest actual request or short response in a stable, large two-line region.
  Words enter with a short masked fade/lift; the prior sentence exits as the next
  arrives. The whole command/result is retained in chat and accessible via View
  conversation. Do not animate internal reasoning or raw tool dumps into this view.
- At most one current work update and a small factual task receipt. Show observed
  actions/results; no invented plan, percentage or guessed finish time.
- Clearly named mic pause/resume, End voice, and (during work) Stop work controls.
  Keyboard focus is visible. Escape returns to chat and ends mic/playback, with the
  same work-continuation rule as End voice.

Initial copy is short, for example “Go ahead. I’m listening.” The initial screen
does not need a dashboard of provider/model/token settings. Problems name the next
action: select a microphone, allow OS microphone access, or open Voice settings.

Sarvam REST transcription supplies a finalized utterance, not live partial words.
The UI must not pretend to stream words while the owner is still talking. The
waveform/orb reacts to actual measured input level; finalized words animate when
the transcription arrives. Speaking motion follows real playback state, and may
use a measured playback envelope when available. No invented output-volume meter
is described as a real signal.

## Visual system (builder choices, not extra owner requirements)

- Keep existing companion type and appearance settings; use the existing system
  font stack, larger type for the latest words, and compact normal-case controls.
- Base palette: canvas `#0E0F11`, surface `#141518`, ink `#F5F6F8`, companion blue
  `#7AA2FF`, ice `#AAE2FF`, lilac `#BFA9FF`. Error/success inherit existing semantic
  theme tokens. Light appearance remains readable through the same theme system.
- Center alignment for orb/captions; left alignment for task details and errors.
  Generous empty space, no decorative statistics, no nested card grid.
- An original WebGL shader is preferred for the fluid sphere, with a static/CSS
  fallback if WebGL fails. No new rendering dependency is required. Bound resolution
  and frame rate, stop hidden animation, and respect reduced motion. The small island
  rendering uses the same visual component, not a second unrelated effect.
- Text transitions finish quickly and never delay STT, tools or playback. Reduced
  motion shows the complete new text without word-by-word movement. Screen readers
  receive complete sentences rather than repeated announcements for each word.

The orb is visually informed by audio-reactive state visualization in ElevenLabs'
official Orb documentation, https://ui.elevenlabs.io/docs/components/orb. This is
an original Ankita implementation, not a new ElevenLabs voice dependency.

## Floating island

Continue in island minimizes the main app and lets the existing island appear.
The full panel's state remains owned by the same session. A compact capsule shows
the small orb, phase and latest meaningful line. Expand reveals pause/resume,
End voice, Stop work and return-to-app controls. An approval takes precedence over
the decorative voice surface and shows the existing approval UI.

Opening the app restores the full voice panel. Neither renderer opens another mic,
repeats a turn, restarts playback or loses the pending result. Starting voice from
the island uses its explicitly selected conversation; never pick an arbitrary
teammate silently. Existing normal island mascot/chat behavior returns when voice
ends. This is compatibility with the island, not a replacement of all island views.

## Interaction and work rules

- One voice session owns one thread at a time. It shares the existing desktop
  engine's model/tool/approval/file-history path and terminal voice task records.
- Builder choice after design review: selecting a different conversation ends
  microphone/playback; delegated work and results stay with the original thread.
  Voice never silently moves to another teammate. Returning from the island restores
  its owning thread. Deleting that owner uses the existing confirmed deletion flow,
  including task cancellation, rather than leaving work without a conversation.
- Sarvam remains STT/TTS; Baseten's configured Meta planner remains voice-only.
  Native typed chat settings are restored after every turn, including cancellation.
  Replies stay within the existing two-sentence speech cap. File generation retains
  the separate output budget and safe output-limit failure behavior.
- Initially retain terminal duplex behavior: listening during capture and final
  speech (barge-in), mic paused during model/tool work. Make that pause visible.
  Concurrent spoken side questions during tool execution are not promised here.
- Cached acknowledgement, optional generated action updates and waiting updates
  retain their ordered playback, spacing, cancellation and no-overclaim rules.
- Pause mic is sticky for subsequent listening; it does not cancel work. Stop work
  cancels the active model/tool request and pending speech, then leaves voice ready
  for a new request unless paused. End voice stops recording/playback and closes
  voice UI; already delegated work continues in the existing chat/approval path.
  During work, the UI explains this distinction in one short line.
- Closing the app fully stops audio children and cancels turns through normal
  shutdown. Minimizing or switching between main/island does not end the session.
- Every async operation carries a captured session/turn identity. Ending, cancelling,
  starting another session, changing/deleting a thread or late synthesis must not
  resurrect audio, overwrite the new session or replay an old approval.

## Desktop bridge and audio ownership

The main process owns one voice coordinator. Reuse the tested voice channel and
voice-session/task/narrator helpers rather than copying the terminal loop verbatim.
The coordinator drives capture/transcription/playback and bounded secret-free state
events. Existing ffmpeg/ffplay runtime detection is used; missing dependencies get
an actionable setup state. Browser renderers never receive API keys or raw arbitrary
file paths for execution. Audio level events are bounded/rate-limited and ephemeral;
raw microphone recordings are removed after transcription.

Add typed voice state/control IPC and a snapshot for late subscribers. Main and
island use the same snapshot and request ownership. The engine preserves actual
tool results and approval semantics, saves the full transcript, and exposes the
durable task result. Voice events do not create a duplicate typed request. Config
and secret redaction follow existing desktop settings/storage conventions.

Voice settings provide service readiness, microphone choice, and Sarvam/Baseten
credential configuration using existing secure settings patterns; ordinary voice
controls do not expose implementation jargon. Existing locally configured env keys
work without pasting them again. A missing key opens the relevant setup view.
No new dependency or weakening of CSP is planned.

The first pass targets native API-backed desktop conversations (the owner's current
Kilo setup, plus existing Copilot/Groq-compatible paths). ChatGPT Browser conversations
must show an explicit unsupported/setup state until their native-tool/history bridge
is intentionally integrated; they must not quietly route through the browser model
or mutate that provider. This is a stated limitation, not claimed parity.

## Acceptance and evidence

1. Existing all-pending PR test/build results are recorded independently. This
   worktree starts from committed source, and baseline desktop build is checked.
2. New unit/engine tests cover one session across both surfaces, real state changes,
   missing services/device failures, short voice style, actual tools/task receipts,
   approval, cancellation, end-voice-with-work-continuing and stale callbacks.
3. Main/island renderer tests cover keyboard controls, error recovery, long text,
   narrow windows, reduced motion and remount/snapshot recovery. No decorative
   progress is asserted as real work.
4. Desktop build and relevant serial suites pass; runtime screenshots show the
   actual rendered main panel and island, rather than only the concept mockup.
5. Live configured-service runs exercise speech -> Meta -> file tools -> short
   report. Automated audio fixtures do not prove physical headset behavior. The
   owner completes the remaining microphone/workspace gate before filming.
6. No release/tag/version bump or merge is performed. Integration goes to its own
   reviewable branch; PR #70 remains the committed terminal/pending-work snapshot.

## Non-goals

No voice vendor migration, cloned voice, new scheduler, fabricated concurrent chat,
always-listening wake word, full desktop redesign, auto-execution bypass, automatic
publishing, or claim that the physical three-take gate has passed. Provider outages,
speech misrecognition and very large generation limits remain visible errors.
