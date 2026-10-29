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

## Implementation note — 2026-10-26

Phases 1–2 implemented:

- A versioned `heartbeat-card` payload with a parser and a substance gate.
  `HEARTBEAT_OK` remains a fallback, and a marker followed by extra text is
  still silence.
- Empty and boilerplate-only answers stay out of chat; they no longer become
  "Job finished without a summary."
- Bounded structured state (`heartbeatState`) replaces `lastNotifiedSummary`.
  The next check receives that state plus the card contract, and the old prose
  result is no longer prepended to heartbeat prompts.
- Delivery policy: dedupe key with a six-hour cooldown, four proactive
  messages per local day (urgent exempt), quiet hours, and a bounded held
  backlog flushed as one digest after the block clears.
- A heartbeat card is parsed before the chat-length cap, so a detailed card
  never leaks raw JSON into chat.
- New settings: `HEARTBEAT_DAILY_LIMIT` and `HEARTBEAT_COOLDOWN_MINUTES`.

Verified with `test/automation/heartbeat.test.mjs` (7/7) and
`test/desktop/scheduler.test.mjs` (39/39), including the three acceptance
fixtures above. Not covered: a live model round trip; Phase 3 (adaptive
cadence, local pre-checks, feedback buttons) remains open.

### Live-test follow-up — 2026-10-26

A real desktop run exposed three gaps the simulated checks had not covered:

- **Blind checks.** Inside a job, `schedule(list)` returned names and times but
  no status (the fallback path prints `describeRoutine`), so "tell me if a job
  failed" could only ever answer silence. Background workers now receive the
  scheduler context; the tool still advertises only `list` and `needs_input`,
  so the read is scoped and mutation stays blocked. Regression test asserts a
  failed job's `lastStatus` reaches the worker.
- **Unexplained silence.** A quiet run stored an empty summary, so the job card
  said only "quiet". The decision reason is now persisted (`lastReason`) and the
  card shows "Checked — nothing to report", "Checked — already reported",
  "Held for quiet hours" or "Held — daily limit reached".
- **UTC shown as local time.** The creation reply read `nextRunAt` (UTC) and
  presented it as local. `schedule` add/update now return `nextRunLocal` in the
  job's zone, and the tool description tells the model to quote it.

Also clarified in the tool schema: a heartbeat prompt states the objective and
what counts as notable, not reply text — the app owns the output contract, and a
scripted reply format conflicts with it (the live model had written one).

Verified: heartbeat 8/8, schedule tool 9/9, scheduler 41/41; the status test was
confirmed red with the context removed, then green with it restored. Still not
covered: a live model round trip through the desktop app.

### Budget follow-up — 2026-10-26

The same live job then stopped after five checks with `stopped-budget` at
54,328 tokens, because it inherited the generic 50,000-token job ceiling
(~12,100 tokens per check). Heartbeats now carry their own gate sized for a
full day of five-minute checks — 300 runs, 15,000,000 tokens, 900 active
minutes — because the owner pays for their own model usage; the gate stops a
runaway loop, not a normal cadence. A heartbeat that reaches the gate pauses
and resumes with the next day. Budgets equal to a default automation wrote
(the generic 48/50k/60 and the earlier 60/1.2M/60) are treated as untouched
and migrate on load; an owner-raised ceiling is kept. Verified: the focused
heartbeat and scheduler suites, 51/51, including migration of both earlier
defaults, a raised ceiling and next-day resume. Not yet covered: observing a
delivered check after the raise.

### Recovery wording — 2026-10-26

The first check after the raise (16:30) delivered its own 16:00
`stopped-budget` receipt as a current outage, said monitoring would stay
degraded until a reset, and quoted 50,000 tokens — while the live list already
showed `enabled: true`, no pause reason and the raised gate. The heartbeat
state now names the job it belongs to; the output contract says a failed
receipt for itself is its previous check, that an enabled job without a pause
reason is running normally, and that only limits the list shows may be quoted.
Verified: heartbeat suite 10/10. Not yet covered: a live check wording the
recovery correctly.
