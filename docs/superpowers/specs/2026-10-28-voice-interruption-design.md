# Voice interruption and report control

The owner approved the researched hybrid flow in chat and explicitly requested
implementation. Keep Sarvam speech and the existing Baseten planner. This changes
speech delivery, not delegated work or the approved dark-pearl design.

## Required behavior

- Speech start stops owned playback immediately, without waiting for the planner.
- A tentative interruption pauses output. Empty/no usable transcription resumes
  the interrupted report; real speech leaves it suspended by default.
- A genuine new request takes priority. Never automatically replay the interrupted
  report after that request. Other ready results remain available.
- The existing planner interprets natural language using report/job identities,
  queued results, completed spoken sentences and the unfinished sentence. No list
  of required skip words and no extra classifier model.
- A private session-scoped `voice_reports` tool offers status, next, dismiss,
  resume and repeat. It affects speech only; work cancellation stays in voice_jobs.
- Next selects an actual ready result. Resume starts at the unfinished sentence;
  repeat is an explicit request to start a chosen report over. Late controls from
  an earlier user turn cannot change the current playback selection.
- Reports are bounded in memory and remain in the existing saved job/conversation
  records. Ending voice closes all retained audio and invalidates controls.
- One player across parallel jobs. A newly selected result waits for the previous
  owned player to settle. Stale synthesis never becomes audible.
- Terminal and desktop/island use the same queue/control contract. Existing audio
  pause, permission, session ownership, task limits and typed-provider rules stay.

## Implementation decisions

Existing MP3 playback has no word alignment. Generate short report sentences as
separate cached clips, keep a completed-sentence cursor, and replay only the
unfinished sentence on resume. Do not claim exact words reached the user's ears.
The extra sentence may require a second TTS request; there is no extra classifier.

On an interruption, briefly hold ordinary queued output until the current planner
selects a speech action, starts substantive work, or produces its reply. Receipts
and permissions remain available. New conversational replies take priority over
older queued results. Starting substantive work releases that arbitration hold,
so other completed jobs are not silent for the duration of a long new task.

The planner's report control is private to the captured audio session and user-turn
token. It cannot cancel work, access another owner, revive ended sessions or let a
late previous request skip a newer report. Speech-only control turns update the
conversation but do not add a redundant spoken acknowledgment.

## Verification and limits

Test report A interrupted with B/C queued: a new request never restarts A; next
plays B; explicit resume skips A's finished sentence; repeat starts A over; empty
transcription restores A. Test stop/close, late synthesis, overlapping user turns,
stale planner controls, terminal and desktop adapters, private tool isolation and
capacity controls. Use real Meta decisions and Sarvam sentence clips in disposable
fixtures, explicitly distinguishing generated input/captured output from a physical
headset. Preserve unrelated pending edits and user documents. Update draft PR70
only; no merge, tag, release or new dependency.

Prior art: LiveKit turn/interruption handling
<https://docs.livekit.io/agents/logic/turns/>, ElevenLabs speech-context invalidation
<https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/multi-context-web-socket>,
and Pipecat's audio turn model <https://github.com/pipecat-ai/smart-turn>.
These patterns guide the design; no third-party detector is installed and Hindi/
English support in another project is not proof of Hinglish accuracy here.
