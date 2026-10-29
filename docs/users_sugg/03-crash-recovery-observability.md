# Problem: crash recovery has no observability or reconcile provenance

## Problem

The crash-recovery state machine is sound in the single-owner case, but four
things around it are unpinned or invisible:

1. **The claim-to-dispatch window is unpinned.** The existing fixture in
   `test/integrations/chatgpt-operation-store.test.mjs` pins the
   dispatched→uncertain crash only. `recover()` also demotes claimed rows to
   uncertain, but nothing pins that path — and the destination matters: a
   claimed row that crashes pre-dispatch has arguably already spent its one
   send in spirit, so `uncertain` (held for a human) is the right bin and
   `rejected` (retryable) would be wrong.
2. **The coarseness is unpinned as a property.** `recover()` deliberately
   cannot distinguish crash-before-dispatch from crash-after-dispatch-without-
   receipt, so it bins both as uncertain. That indistinguishability is the
   design, not a limitation — but nothing pins it, so a future change could
   start guessing from evidence it does not have.
3. **The fail()/recover() asymmetry is unpinned.** `fail()` distinguishes
   (claimed→rejected, dispatched→uncertain) because its caller witnessed the
   flow; `recover()` coarsens both to uncertain because it runs blind at
   restart. The day someone "harmonizes" them, one direction or the other
   becomes a bug.
4. **Uncertain rows are invisible, and reconciles leave no trace.** An
   uncertain row that never reconciles surfaces nowhere, so under-delivery
   gets mistaken for a system with no failures. And after `accept()`
   reobserves and closes an uncertain row, the ledger records no who and no
   evidence — months later, "uncertain → accepted" is a row an auditor cannot
   reconstruct.

Source: launchgatecheck, Oct 17, 2026, on "How I built at-most-once sends
for my AI companion's ChatGPT tab". Status: agreed in thread.

## Design

Pin destinations, not just non-replayability. Pin coarseness as a property.
Make the human side of the state machine as traceable as the crash side.

Note the honest caveat from the thread: the precision in `fail()` lives in
caller discipline, not in `fail()` itself — it is sound only because the
bridge is the only live caller. The fixtures below are what pin which call
path means what.

## Solution

1. Fixture: queue → claim → fresh store instance → `recover()` → assert the
   outcome is `uncertain` specifically (not just non-replayable),
   `claim()` returns null, `dispatch()` returns false, `dispatchedAt` unset.
2. Fixture: two crashed journals, one crashed after claim but pre-dispatch,
   one after dispatch with no receipt — assert both bin to uncertain
   identically.
3. Fixture: crash at one point, run both paths — assert `fail()` and
   `recover()` bin differently, and that difference is intentional.
4. Observability: an uncertain row that never reconciles surfaces somewhere
   (a count, a stale-uncertain sweep) instead of sitting invisible.
5. Provenance: `accept()` records who reconciled the row and on what
   evidence, not just the state flip.

## Acceptance

- All three fixtures green; the coarseness and asymmetry fixtures fail if
  either mapping is "harmonized".
- A stale uncertain row is visible in the jobs list or logs without digging.
- A reconciled row shows its reconciler and evidence on inspection.
