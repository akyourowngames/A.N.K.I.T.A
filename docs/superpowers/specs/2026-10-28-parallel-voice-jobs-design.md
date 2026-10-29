# Parallel voice jobs

Owner instruction, 28 October: “i want parallel execution for voice only”. This
supersedes the previous one-agent-turn-at-a-time voice limitation and the offered
serial queue/busy policies. Continue in the existing isolated voice worktree and
update draft PR #70; do not merge, release, or alter typed-chat concurrency.

## Experience

Ankita accepts another spoken request while an earlier job is working. Each
utterance gets its own worker and task identity; status questions and cancellation
use the same Meta voice planner with a private job-control capability. Independent
research, conversation and file work can overlap. No second front-door model call
is added just to classify every utterance. Spoken replies stay at one/two sentences.

The microphone's phase describes the actual audio state, not whichever worker
updated last. Show the latest words and one current update, an active-job count,
and a compact list with an individual Stop button. Full panel and island share
the session/jobs. Keep the approved smooth dark pearl and its state motion.

One speaker owns playback. Completed reports from two jobs take turns with clear
task labels; they never cut each other off. A user's interruption stops audio,
not unrelated work. Obsolete progress is dropped; completion takes priority over
unstarted progress. End voice stops input/output while jobs finish into their
owning conversation. Stop one job does not stop the others; Stop all is explicit.

## Worker and history ownership

Use one fresh existing Agent per spoken job, with a captured owner, project,
workspace, config, Meta client and stable completed conversation context. Never
send two requests through one mutable Agent or temporarily change a typed Agent's
model. Reuse the normal tool host, tool verification, permissions and file effects.
These are interactive user delegations, not scheduled-browser jobs; do not weaken
the scheduler's background-worker guard or reuse its approval bypass.

The private `voice_jobs` capability lists bounded facts/results, waits for a named
earlier job, or cancels a named/all owning jobs. It exists only in voice workers;
normal typed agents do not gain it. Dependencies and cancellations are scoped to
the owning conversation. Unknown/ambiguous targets fail clearly. Worker results
are data, not instructions. Do not repeat completed work in a status answer.

Durable task IDs are allocated before execution, and status/results remain
separate. Complete task results are appended to the original conversation through
an idle delivery path, without interleaving two API tool transcripts or mutating
a running typed conversation. No extra LLM rewrite is required to deliver a result.
Deleting an owner cancels its jobs. App/CLI shutdown cancels all owned workers and
audio. Ending voice alone does not cancel them. Process restart recovery is not
promised; unfinished records must never be called successful.

## Conflicts and limits

Parallel does not mean simultaneous control of one shared object. A voice resource
broker holds canonical file/directory leases for each job's read/modify/write
sequence. Disjoint files can run together; conflicting paths wait. Path aliases,
case folding on Windows, parents/children and multi-file operations are considered.
Unknown shell effects take a conservative workspace lease. Shared browser/native
UI and opaque external actions use exclusive interaction/service leases rather
than interleaving screenshots and clicks. Existing permissions still apply.

Detect cyclic waits and fail/cancel the newest conflicting job clearly instead
of hanging both. Cancellation removes waiters and releases leases. Unfinished
owned shell children retain their relevant lease until termination is confirmed;
a launch receipt is not process completion. This coordination covers participating
voice jobs, not arbitrary external apps/processes or unmodified typed/scheduled
jobs. No OS-wide file lock or rollback of completed actions is claimed.

Concurrency and retained snapshots are bounded with named configuration defaults.
Capacity errors remain actionable; do not silently serialize all ordinary jobs.
Secrets, raw commands, file contents and raw tool results stay out of cross-window
progress. Preserve the separate large file-generation allowance and small optional
narration allowance. Failed optional narration stays silent and cannot delay work.

## Acceptance

- Hold job A inside a controlled tool/model; submit B through real voice flow and
  prove B starts/finishes before A is released. Typed model/history remain separate.
- Two same-tick completions keep their own reports and have maximum one audio player.
- Two file jobs performing read/modify/write on the same canonical path retain both
  changes; disjoint paths overlap. Cancellation/deadlock/alias cases do not hang.
- End voice, restart, owner switch/delete, permission waits, one/all cancellation,
  stale TTS, and app shutdown preserve captured ownership and existing safety.
- Main/island show multiple real jobs and keyboard-usable per-job controls, with
  reduced motion/fallback preserved. Terminal receives the same concurrency rules.
- Repeat real configured Meta/Sarvam/file checks. Generated mic/player fixtures
  remain explicitly distinct from the physical headset/three-take gate.
