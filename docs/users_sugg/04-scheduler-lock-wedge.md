# Problem: scheduler lock can wedge forever

## Problem

Three holes in scheduler ownership, all in `src/automation/scheduler-ownership.mjs`
and the surrounding policy in `src/automation/job-policy.mjs`:

1. **PID reuse.** The claim written into the lock file is
   `{ pid, host, token, heartbeat }` — no process start time, no cmdline.
   `alive()` is literally `process.kill(pid, 0)`, so after a reboot or a
   long-dead owner, a recycled PID belonging to an unrelated process reads as
   alive, and recovery never fires: the stale branch requires both
   `!alive(owner.pid)` and a heartbeat past `LOCK_STALE_MS` (2 minutes).
2. **Orphaned .recovery sidecar.** The sidecar in `acquire()` is created with
   `'wx'` and deleted in the `finally` block. A `finally` only runs for exits
   the process survives — a SIGKILL or power loss between sidecar creation and
   lock deletion leaves `.recovery` behind for good. The next attempt hits
   EEXIST on the sidecar, which is caught and skipped, and since the dead
   owner's lock file still exists, recovery never runs. Every future attempt
   throws `OWNERSHIP_ERROR` until someone deletes the sidecar file by hand.
3. **Wedged owner.** Takeover is cooperative by design: `acquire({ takeover: true })`
   writes a `.takeover` request file and polls up to `TAKEOVER_WAIT_MS` (15s)
   for the owner to step down. A wedged owner (PID alive, never heartbeating)
   just burns the deadline and the requester throws. There is no way to tell
   wedged apart from busy — the heartbeat carries no progress information.

Already handled, for the record: EPERM counts as alive in `alive()` (only ESRCH
counts as dead), so a root-owned CLI run against a user-owned desktop lock
backs off instead of stealing it.

Source: arhancanli, Oct 13, 2026, on "How I built a scheduler that can never
double-fire". Status: agreed in thread (PID reuse and sidecar on the TODO
list; progress timestamp named as the right first step).

## Design

Keep takeover cooperative — never forcibly steal a live owner. Make staleness
decidable from recorded facts instead of from a PID number alone.

## Solution

1. Capture the process start time at claim (or gate on the command line) and
   compare it in `alive()`. A recycled PID with a different start time is not
   the owner.
2. Give the sidecar its own staleness rule: write the holder's PID and
   timestamp into it at creation, and let a later process claim the sidecar
   itself when its holder is dead.
3. Put a progress timestamp in the heartbeat — last job tick, not just
   "timer fired" — so a wedged owner (no ticks) becomes distinguishable from
   a busy one (ticks recent) before anyone reaches for a force flag.

## Acceptance

- Fixture: lock left by a dead owner whose PID has since been recycled →
  recovery fires instead of deferring to the stranger process.
- Fixture: sidecar orphaned by a SIGKILL → the next attempt recovers instead
  of throwing `OWNERSHIP_ERROR` forever.
- Fixture: wedged owner → heartbeat shows no recent job ticks, distinct from
  a busy owner.
