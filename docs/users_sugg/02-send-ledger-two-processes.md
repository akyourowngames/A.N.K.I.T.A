# Problem: send ledger breaks silently with two processes on one profile

## Problem

The at-most-once guarantee for ChatGPT browser sends is really "at-most-once per
owner process", but nothing said so, and the failure when the assumption breaks
is silent, not loud.

`locks` in `src/integrations/chatgpt-browser/durable-profile.mjs` is a Map keyed
by file path that lives inside the owner process. Within one process, concurrent
queue / claim / dispatch calls serialize fine. But two processes on the same
profile directory each read the old journal, mutate in memory, and atomic-rename
their own copy over the file. Atomic rename protects each replacement, not the
read-modify-write across writers — so it is last-writer-wins: one process's
claim can silently overwrite the other's dispatch, and the loser keeps believing
its in-memory state is real, up to and including dispatching.

Source: launchgatecheck, Oct 16–17, 2026, on "How I built at-most-once sends
for my AI companion's ChatGPT tab". Status: agreed in thread (docs fix taken;
cross-process guard still open).

## Design

Make concurrent ownership loud, not silent. Two candidate mechanisms, in
order of preference from the thread:

1. **flock on an open file descriptor.** The lock dies with the process, so a
   crashed owner cannot wedge the profile behind a stale file the next instance
   has to decide whether to trust — which would just move the silent-vs-loud
   problem one level down.
2. **Journal revision counter checked before rename.** The loser aborts with an
   explicit error instead of overwriting.

An existence-checked lockfile is the wrong shape: it recreates the stale-file
trust problem.

Separately, name the boundary in the guarantee itself, not in a caveats
section: "At-most-once per owner process; concurrent owners need an external
coordinator." That wording travels with every copy of the README; a caveats
paragraph gets skipped.

## Solution

1. Put the boundary wording into the guarantee lines themselves (the
   `durable-profile.mjs` locks comment already says "per owner process", but
   the guarantee lines — "Commit precedes any action grant or receipt
   acknowledgement" — do not).
2. Add the cross-process claim: flock on an open fd, or a revision counter
   validated before rename. On conflict, the loser errors explicitly and never
   dispatches on stale state.
3. Write the fixture the thread specifies, asserting on the loser, not the
   winner: two processes open the same profile, each claims a different
   operation; after the winning rename lands, assert the losing process still
   believes its claim stands while the journal on disk no longer contains it —
   and that it is stopped before dispatch. That divergence is the real failure.

## Acceptance

- The fixture fails on today's code (the loser dispatches) and passes after
  the fix (the loser errors before dispatch).
- The guarantee wording names the per-owner boundary wherever the guarantee is
  stated, not only in a caveats section.
