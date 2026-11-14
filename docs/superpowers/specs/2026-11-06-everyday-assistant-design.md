# ANKITA everyday assistant

## Approved objective

Implement the eight Jarvis-style upgrades proposed in this conversation, with
generally useful behavior reachable in the running product rather than unused
helpers: natural voice, reliable continuation, requests spanning apps, a daily
briefing, project-aware personal knowledge, selected context, phone/desktop
continuity, and reusable routines taught from successful tasks.

The user approved implementation. Existing voice, MCP, scheduling, pairing,
memory, capture, approvals and conversations are the foundation. Preserve the
earlier uncommitted skills work and unrelated user documents. Work on the current
feature branch; no publication or unrelated cleanup is authorized.

## Product behavior

### Today, the everyday entrypoint

Add a visible Today navigation item and an actual assistant page. Show actionable
unfinished work, upcoming schedules and failures, open project commitments,
recent results, and connected-service readiness. Every item links to its owner
conversation or an actual control. The page contains a request composer, Voice,
selected-context and Phone entrypoints. Empty states explain the next usable
action; no invented events, messages or calendar data.

The on-device briefing summarizes saved facts deterministically without a model
call. A separate explicit request can check connected calendar/inbox services
through existing tools and return sourced results in the same conversation. A
daily-brief routine is opt-in, editable and uses the existing scheduler and quiet
hours. Reuse configured services; never hardcode a school/work scenario.

### Durable tasks and cross-app follow-through

Persist the original request, owner/project, source surface, live status,
checklist and bounded evidence of requested/actually-started/settled actions.
Capture actual execution after approval through the shared tool host. Queued
approval is not an executed action. Record outcomes and uncertainties atomically
during work, not only at its end. Do not store credentials or duplicate unbounded
raw payloads. Checkpoint normal typed, voice, phone and supported channel tasks.

On restart mark nonterminal tasks interrupted, without running external writes.
Today and conversations expose review/resume. Resume uses the original goal,
confirmed receipts, unfinished checklist, existing conversation and fresh current
observations. Exact already-confirmed mutations are not executed again; uncertain
mutations require resolving effects instead of blind replay. Preserve ordinary
approval boundaries, cancellation and ownership. Completion requires receipts
supporting the original goal; discovery or planning alone is not completion.

Cross-app work stays one task with its dependencies/checkpoints; no special demo
recipes are required. Missing integrations are actionable setup states, not fake
success. Interrupted browser-provider turns use the existing continuation path
when available and retain their account/thread binding.

### Natural voice

Route unambiguous pause/status/continue/repeat/stop-speaking controls locally,
without spending a planner call or cancelling unrelated work. Distinguish ending
audio, stopping speech and cancelling a task. Ambiguous/mixed requests still go
to the planner. Expose useful report controls and actual interruption availability.

Improve the configured speech path with streaming/early preparation where the
provider and runtime support it; show real partial transcripts only when received.
Keep cancellation and stale-session checks throughout. Preserve speaker echo
protection: never enable unprotected full-duplex recording or claim acoustic echo
cancellation. Provide a useful fallback and truthful readiness/latency information.
Use existing configured providers; do not replace credentials or force a new vendor.

### Knowledge and selected context

Make personal/project facts, decisions and commitments searchable, editable and
forgettable from the app, retaining their sources. Surface contradictions rather
than silently choosing. Corrected/forgotten knowledge must stop appearing in later
turns. Supply bounded relevant knowledge to both typed and voice work; voice's
current memory-disabled worker must not silently miss it.

Reuse selected text, browser capture and attached documents as explicit context.
The user can review the source and remove it before sending "explain this" or
"turn this into tasks". Context belongs to one request, follows its task/handoff,
and must not become continuous screen surveillance or accidental global memory.

### Phone continuity

Reuse existing approved phone pairing, device credentials and assigned desktop
threads. Expose current history/tasks and reviewed context handoff, not a separate
assistant identity. Ship an accessible phone browser client/entrypoint if the
existing native-client-only bridge cannot reach the new flows. Respect device
assignment, revocation, TLS, approval ownership and bounded payloads. Pairing and
history must not expose another teammate's data or authority.

### Teach once

Successful tasks offer a visible "Save as routine" action. Save an editable,
named reusable instruction template with source-task evidence and user-entered
parameters; do not replay raw secret-bearing tool arguments or stale UI refs.
Running asks only for missing parameter values, then starts a normal tracked task
with the configured tools and approvals. Scheduling is a separate explicit choice.
Failed/uncertain tasks are not silently promoted into proven automations.

## Design decisions

- Extend the current desktop and phone bridge; no new standalone assistant app.
- Keep external account/device actions in connected MCP/services.
- Use existing dependencies when sufficient; review any necessary new dependency
  before installation. Configuration and runtime discovery replace environment guesses.
- The Today page uses existing theme variables, restrained hierarchy and accessible
  controls. Task results and useful actions take priority over decoration.
- No automatic replay of external writes after restart. Read/inspect first;
  distinguish prevented exact repeats from guarantees about arbitrary model intent.
- No claimed speed/call-saving percentage without measured paired evidence.

## Acceptance evidence

Each feature needs a reachable UI/command path, persistent state where relevant,
focused regression coverage and an executed end-to-end journey. Required journeys:
restart during a multi-step request and resume without repeating a completed write;
task using two tool families; local voice status/report controls with zero planner
calls; live configured speech round trip and supported fallback; Today facts and
actions; memory correction/forget reaching the next typed and voice turn; selected
context used once; paired phone history/context/task continuation and revocation;
successful task saved and run as a parameterized routine with normal approvals.

Run relevant suites serially, desktop typecheck/build and real renderer/native
checks. Use isolated test profiles and live services only within the user's
authorized task scope. Distinguish fixtures, real service runs and physical-device
acceptance. Keep the goal active if an explicit requirement remains unproven.
