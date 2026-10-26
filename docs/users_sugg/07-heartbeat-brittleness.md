# Problem: heartbeat silence is brittle, and empty updates still reach chat

## Problem

Three gaps in the quiet-heartbeat design (`desktop/electron/scheduler.mjs`,
`src/automation/job-policy.mjs`):

1. **Silence is an exact string match, and it is brittle.** The check is one
   line: a heartbeat run is quiet only if the summary trims to exactly
   `HEARTBEAT_OK`. There is no versioning on the marker. If a model decides
   to be helpful and appends a sentence after it, the silence breaks and a
   non-update reaches chat. The only guard is the prompt telling the model
   to "reply exactly HEARTBEAT_OK".
2. **Partial silence is not handled.** Anything that is not exactly
   `HEARTBEAT_OK` is treated as a real update and delivered — including an
   empty summary, which literally becomes "Job finished without a summary."
   and still lands in chat. There is no semantic "is this actually signal"
   gate on non-quiet summaries.
3. **A long quiet streak leaves the next run working off stale state.** When
   a heartbeat produces a useful update, the run record stores
   `lastNotifiedSummary`, and the next heartbeat's prompt gets "Previous
   useful heartbeat update: ..." prepended — but only as text, only from
   useful runs. A long quiet streak means the next heartbeat reasons from a
   stale summary, with no structured state to fall back on.

Answered, not problems: there is no key to expire (HEARTBEAT_OK is never
stored, so no stale "healthy" marker can survive a crash), and missed runs
outside the 30-minute catch-up window are honestly marked `missed`. Jitter
is not needed — one routine per machine, one Electron process, no fleet.

Source: ai_adam, baumgaerben, ywnigcsmku2m, Oct 10–12, 2026, on "How I built
a quiet heartbeat for my AI assistant". Status: agreed in thread (structured
field and substance gate both named as TODOs).

## Design

Treat the heartbeat as a contract with a versioned structured payload, not as
a string the model must reproduce exactly. Keep the skipped-busy rule as it
is — it is the part commenters praised most — and add the missing gates
around it.

## Solution

1. Move the match onto a structured field: a heartbeat payload with a
   `type: "heartbeat"` field and a version field (the commenters' `hb_v`
   pattern) so the consumer stays backward-compatible when the schema
   migrates, instead of matching on the model's summary string.
2. Add a substance gate: an empty or metadata-only non-quiet summary does
   not become a chat update. It is recorded as quiet (or flagged for the
   run log), never delivered as "Job finished without a summary."
3. Carry a structured `last_known_state` across quiet streaks instead of a
   text summary from the last useful run, so the next heartbeat after a
   long silence reasons from state, not from stale prose.

## Acceptance

- Fixture: model appends a sentence to `HEARTBEAT_OK` → still quiet under
  the structured match.
- Fixture: empty summary → no chat update.
- Fixture: long quiet streak → next heartbeat's prompt carries structured
  last-known state, not a stale text summary.
