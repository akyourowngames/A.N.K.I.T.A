# Everyday assistant implementation evidence

Work started 2026-11-06; checkpoint updated 2026-11-07. The full eight-part goal
remains active. This is an evidence ledger, not a claim that every feature ships.
The approved scope is `docs/superpowers/specs/2026-11-06-everyday-assistant-design.md`.

## Current implemented paths

- `src/assistant/{tasks,task-run}.mjs`: original goals, owner/project, bounded
  checkpoints, actual-start/settled receipts, persistent checklists, atomic writes,
  process-lifetime recovery, exact completed-write guards and unresolved-write
  review. Raw tool arguments/UI references are not stored; hashes identify exact
  repeats. Recovery receives bounded historical evidence and fresh observations.
- `src/core/{agent,tool-host}.mjs`: ordinary foreground requests use the injected
  store. Admission is saved before actions; start is saved after normal approval.
  Denials never become started effects. Failed admission prevents native and MCP
  execution. Subagents share the original task with separate provider-call IDs.
- `desktop/electron/{assistant,assistant-actions,engine,main,channel-surface}.mjs`:
  typed/voice/phone-backed engine requests and private channel requests use the
  same checkpoints. Today/resume/manual-outcome-review and personal memory CRUD
  have authenticated application-window dispatch. Resume validates the owner and
  original project/workspace. Browser-provider recovery still needs integration.
- `src/core/{cli,local-commands,commands}.mjs`: `ankita work list`,
  `ankita work show <task-id>` work before provider boot; `--resume-task <task-id>`
  restores the goal/project/workspace and uses ordinary tool permissions.
- `desktop/renderer/src/components/TodayPage.tsx`: visible Today navigation,
  deterministic local briefing, unfinished/recent requests, Continue/review,
  upcoming schedules, explicit connected-app check draft, voice/chat entrypoints,
  searchable editable/forgettable personal facts, preferences, goals, commitments.
  Calendar/inbox remain explicitly unqueried until the user asks through chat.
  The full-App check reproduced an existing draft being erased by the new entry;
  it now seeds the per-surface draft store before the lazy composer mounts,
  appending an explicit check while preserving existing draft text/files.
- Opt-in daily briefing schedule: the shared action creates a paused job draft,
  each run injects fresh saved commitments plus the explicit not-checked
  external-source notice, and the finished briefing is posted directly instead
  of paying for a second delivery rewrite. The Today UI control for that draft
  is still the remaining reachability gap.
- `src/core/voice-worker.mjs`: only explicit foreground profile context enables
  normal bounded fresh retrieval; private control-only workers avoid recall.
  Corrected facts reach subsequent typed and voice decisions.
- Local voice controls and report UI have their separate detailed evidence in
  `docs/findings/everyday-voice-controls.md`. Both App and Island pass onSpeech.

## Executed checks at this checkpoint

New storage/execution/desktop checks (before the added voice-memory case):

```text
node --test --test-concurrency=1 test/core/assistant-tasks.test.mjs test/core/assistant-task-execution.test.mjs test/desktop/everyday-assistant.test.mjs
tests 17; pass 17; fail 0; duration_ms 5851.2871
```

These cover real native file effects; controlled MCP effects; admission failure;
denied versus started work; ownership, corruption and live-process leases;
bounded/redacted history; unresolved writes blocking further changes; scoped
delegation receipts; Today with zero additional model requests; and stored edits.
New behavior was exercised failing before implementation. The bounded-recovery
test initially also had a missing test import, corrected before its final run.

Real CLI process termination and restart:

```text
node --test test/core/assistant-cli.test.mjs
ASSISTANT_CLI_RESTART_OK original_goal=kept completed_write=blocked remaining_file=saved attempts=2
tests 2; pass 2; fail 0; duration_ms 2657.6598
```

The normal CLI talks to a local HTTP model fixture, saves a real file, is killed
while its next decision is pending, then starts as a new process. The repeated
completed write is blocked and the remaining real file is saved. This is process
and filesystem evidence, not a live-model quality benchmark. A fixture provider
name was corrected before the successful run.

Current retrieval/voice-worker/CLI gate:

```text
node --test --test-concurrency=1 test/desktop/everyday-assistant.test.mjs test/core/assistant-cli.test.mjs test/core/voice-worker.test.mjs test/core/voice-worker-tools.test.mjs
tests 23; pass 23; fail 0; duration_ms 8236.951
```

The voice-memory regression first failed with an empty current-memory result,
then passed with the edited violin goal and no stale piano goal. That check uses
real retrieval/Agent/worker plumbing, a scripted final decision and no audio.

Shared core/desktop regression gate:

```text
node --test --test-concurrency=1 test/core/tool-host.test.mjs test/core/agent-audit.test.mjs test/core/subagents.test.mjs test/core/subagent-workspace-mutations.test.mjs test/core/subagent-messaging.test.mjs test/core/voice-worker.test.mjs test/core/voice-worker-tools.test.mjs test/desktop/desktop.test.mjs test/desktop/voice-engine.test.mjs
tests 87; pass 87; fail 0; duration_ms 20171.6767
```

Renderer/control round trip before full-App navigation assertions:

```text
node --test test/desktop/assistant-ui.test.mjs
tests 1; pass 1; fail 0; duration_ms 7352.3664
```

Real React Today controls call the actual dispatcher and task/profile stores.
Continue forwards the original task identity; edit/forget writes real isolated
  files; the narrow page stays within its viewport. Resume execution is separately
covered through the real engine and CLI. The extended full-App acceptance then
passed: Today is the default and sole selected navigation item; Chat retains a
draft across Today; the external check appends its text. Final extended run:
`tests 1; pass 1; fail 0; duration_ms 6375.4825`. An earlier harness route used one
Vite module identity for two HTML entries; it was corrected before the actual
draft-loss failure was reproduced and fixed.

```text
npm run desktop:build
TypeScript exit 0; 417 modules transformed; built in 11.29s
```

Briefing schedule regression:

```text
node --test --test-name-pattern "opt-in daily briefing" test/desktop/everyday-assistant.test.mjs
tests 1; pass 1; fail 0
```

Re-run focused gates after the briefing fix: desktop assistant/phone/voice
**36/36**, core assistant/skills **46/46**, `check-skills` **12 checked, 0 errors**,
and `tsc --noEmit -p desktop/tsconfig.json` exit **0**.

Later changes require a final rerun. No dependencies were added. No user data,
credentials, releases or external accounts were changed for these checks.

## Remaining acceptance gaps — goal is not complete

- Finish full-App navigation/draft acceptance and inspect actual rendered images.
- Complete source-backed project context editing/deletion, current commitments
  and deterministic daily facts; expose the paused briefing-schedule draft in
  the Today UI (its engine/IPC and fresh-fact execution are done).
- Add reviewed selected-text/document/browser context across task/handoff flows.
- Add teach-once parameterized routines with source evidence, reachable editor,
  normal tracked execution and separate opt-in scheduling.
- Extend paired phone history/tasks/context, a usable entrypoint and owner/revoke
  acceptance. Existing phone-run requests already enter the shared engine path.
- Complete browser-provider task recovery and daemon channel checkpoint coverage.
- Completion receipts presently prevent obvious false completion (denied,
  uncertain, unfinished checklist), but full original-goal semantic completion
  acceptance across typed multi-app work remains to be proven.
- Streaming/early speech preparation, live configured speech-provider round trip,
  physical microphone/headphone/speaker checks and latency evidence remain.
- No measured general real-model/phone speed or 25% call-saving claim. Local
  voice controls have separate zero-planner-call evidence only.
- Fresh whole-change review, final focused gates, whitespace/literal audit and
  packaged/native UI acceptance remain. Full repository suite has not been run.
