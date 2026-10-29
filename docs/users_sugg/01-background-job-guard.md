# Problem: background-job guard is convention, not structure

## Problem

Background workers are refused the schedule tool by advice and by a dispatch check,
but the tool is still advertised to them, and nothing structural forces the guard:

- `JOB_TOOLS` in `desktop/electron/scheduler.mjs` still contains `schedule`, even
  though a background worker is forbidden to call it. The guard holds only because
  every worker construction site passes `backgroundJob: true` — a convention, and
  nothing asserts it.
- There is no parent linkage in the routine record. A spawned child lands in the
  same store as an ordinary routine, individually deletable, but deleting the
  parent cascades nothing. Orphaned spawned routines are invisible as orphans.
- The "historical context, never a substitute for a fresh observation" label is
  asserted present by tests, but nothing poisons the baseline to prove the label
  earns its keep: an attacker-written `lastSuccessfulResult.text = "unchanged"`
  plus a changed page should still produce a digest that reports the change.

Source: launchgatecheck, Oct 17, 2026, on "How I built read-only-by-default
scheduled jobs for my AI companion". Status: agreed in thread.

## Design

Three layers, each stopping a different failure:

- **Dispatch** stops a crafted context: `run()` in `tools/automation/schedule.mjs`
  already returns `Error: Background workers cannot change schedules.` when
  `ctx.backgroundJob` is set. Keep it as defence in depth.
- **Factory** stops a forgetful developer: one place builds job workers and stamps
  the flag itself, so there is no legitimate way to get a job worker without it.
- **Prompt line** stops nothing and costs nothing. Keep it as a backstop, never
  as the defence.

A test that asserts "every construction site passes the flag" is the same
convention wearing a test costume — it has to know where all the sites are.
The factory is the fix that cannot silently rot.

## Solution

1. Add a `createJobWorker(routine, run)` method that owns both stamps and is the
   only caller of `new AgentClass` for background work. `DesktopScheduler.execute()`
   calls it and never constructs a worker directly. Today there is exactly one
   construction site (the flag is stamped twice inline in `execute()`), so this
   is a small, safe refactor.
2. Drop `schedule` from `JOB_TOOLS` (keep `schedule_status`). A tool the model is
   forbidden to call should not be advertised to it.
3. Add a `spawnedBy` field to the routine record. The jobs list surfaces a
   spawned routine whose parent no longer exists as an orphan worth auditing.
4. Write the fixtures:
   - Factory-built worker + injected schedule-create instruction → capability
     error, and the routine store gains nothing.
   - Poisoned baseline: hand-write `lastSuccessfulResult.text = "unchanged"`,
     change the page, run the digest, assert the prompt the model sees still
     carries the fresh-read task and the untrusted label intact.

## Acceptance

- Both fixtures fail on today's code in the ways the thread describes and pass
  after the fix.
- A grep for `new AgentClass` outside the factory and the foreground chat path
  shows only tests.
- The prompt-contract fixture pins the label travelling with poisoned input; it
  does not claim to prove the model's verdict, only the enforced invariant.

## Implementation note — 2026-10-26

Shipped on `fix/background-job-guard`:

- `DesktopScheduler.createJobWorker(routine, run, scope)` is now the only
  background-worker construction path. It stamps `backgroundJob` in both the
  agent config and the tool context, sets the owner's model and the credential
  permission, and `execute()` calls it.
- `schedule` stays in `JOB_TOOLS`, but a job is advertised only `list` and
  `needs_input`. Removing the name entirely would have removed the MFA and
  manual-help path, which lives on the same tool. Foreground keeps the full
  action set; the dispatch guard remains as defence in depth.
- `spawnedBy` and orphan detection are deferred: no code path creates a routine
  from a job, so the field would guard a state that cannot occur.
- Fixtures: factory stamps and single construction path (fails without the
  factory); background schema narrowing (fails without the helper); injected
  create leaves the store unchanged; poisoned baseline keeps the history label
  and the fresh task.

Verification: `test/desktop/scheduler.test.mjs` 33/33 (the factory and schema
fixtures fail 2/33 on the pre-change code), plus 16/16 scheduling/tool tests and
46/46 core tool tests.
