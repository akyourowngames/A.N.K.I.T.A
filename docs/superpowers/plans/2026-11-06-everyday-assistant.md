# Everyday assistant implementation plan

> Use the executing-plans workflow for integration, with independent audits and
> fresh review. Preserve previous skills changes and unrelated user files.

**Goal:** Implement every approved everyday-assistant behavior in reachable app flows.
**Architecture:** Existing engine/tool host with durable work checkpoints; Today
and knowledge UI; safe parameterized routines; configured voice improvements;
existing phone pairing with shared task/context/history access.
**Tech stack:** Current Node/Electron/React/MCP stack.
**Spec:** ../specs/2026-11-06-everyday-assistant-design.md

## Constraints and interfaces

- No dead modules: every capability has engine/IPC/UI or CLI integration plus a
  real consuming-path test. Use one shared contract for action names and limits.
- Durable tasks have owner, project, original goal, state, started/settled action
  receipts and bounded/redacted recovery context. Tool start is after approval.
- Resume/teach must never silently replay uncertain actions or stale UI refs.
- Voice controls preserve running work unless cancellation is explicitly requested.
- Phone uses assigned threads and existing authentication; no cross-owner access.
- New UI retains themes, keyboard access, mobile sizing and existing chat drafts.
- Existing profile data and credentials must survive failed writes and restarts.

## Work and progress ledger

This file records the whole scope across goal turns. A checked task needs current
evidence in docs/findings/everyday-assistant.md; tests alone do not prove reachability.

- [ ] 1. Durable work: test-first task store and shared execution lifecycle,
  engine/voice/channel integration, original-goal continuation and replay guards.
- [ ] 2. Today: real aggregate snapshot, default/reachable navigation, ask/voice,
  unfinished/recent/upcoming actions, deterministic briefing and editable opt-in
  connected-service briefing schedule.
- [ ] 3. Knowledge: source-backed personal/project search/edit/forget, commitments,
  and bounded current knowledge delivered into typed and voice work.
- [ ] 4. Context: review selected text/browser/document sources, one-request scope,
  meaningful "this" actions and persisted task/handoff context.
- [ ] 5. Voice: local controls and visible report actions, supported streaming/early
  speech path, truthful fallback/readiness, real configured service verification.
- [ ] 6. Teach once: completed-task routine drafting, editable parameters, normal
  tracked execution, separate scheduling and explicit permissions.
- [ ] 7. Phone: authenticated assigned-thread history/tasks/context handoff,
  usable phone entrypoint and tested revocation/ownership boundaries.
- [ ] 8. Acceptance: paired multi-app/restart/routine/knowledge/context/phone/voice
  journeys, focused suites, build, rendered UI and fresh whole-change review.

## Audit findings before implementation

- Voice already runs independent jobs and supports report sentence cursors, but
  simple spoken status/pause/continue currently spend a model turn.
- Voice workers explicitly disable normal memory recall; add bounded knowledge
  through captured context rather than assuming parent recall reaches them.
- Saved voice records are audit summaries, not executable restart checkpoints.
  Shared tool host onToolStart is the authoritative after-approval boundary.
- Desktop has chat/projects/plugins but no daily assistant page or personal memory
  manager. Phone pairing already sends work into assigned desktop conversations.
- Existing skill changes from the preceding task remain part of the working tree.

## Review focus

### 2026-11-07 progress checkpoint

Concrete progress: durable task store plus real Agent/ToolHost/desktop/CLI/voice
integration; Today and personal memory controls; fresh voice knowledge; local
voice controls. Exact evidence and all remaining scope are in
`docs/findings/everyday-assistant.md`. No whole task above is checked yet because
its full acceptance contract is broader than this milestone.

Ruling: Foreground tasks are persisted only when their real host injects the task
store. This keeps standalone/third-party Agents from silently writing a user's
profile; desktop and CLI inject it by default. Cost if wrong: an omitted host
would lack recovery, so every supported consuming surface must be checked.

Ruling: An unresolved interrupted write blocks further mutations, including ones
with different arguments. Fresh reads remain available to establish what happened.
Cost if wrong: some independent remaining work waits for an explicit review;
blind duplicate effects are avoided.

Ruling: Today's deterministic briefing labels calendar/inbox as not checked and
offers an explicit normal-chat check. Cost if wrong: it cannot claim externally
complete daily information; the opt-in scheduled external briefing is still due.

Ruling: Continue restores only the same project/workspace for desktop tasks; the
explicit CLI --resume-task restores the saved workspace under the local owner's
normal permissions. Cost if wrong: a moved/deleted workspace needs user repair.

Ruling: Switch independent remaining phone and speech work to fresh scoped
implementers under dispatching-parallel-agents/subagent-driven-development,
while root keeps shared assistant/routine integration. File ownership excludes
engine/main/App/wire for both implementers. Cost if wrong: integration review
must catch interface drift; no unreviewed parallel edit is treated as finished.

Phone implementer: `/root/phone_continuity`; owns phone service/shared contract,
PhonePairingSettings, new static phone client, phone tests/report. Speech
implementer: `/root/voice_streaming`; owns voice provider/session/playback/control
and settings modules, voice tests/report. Both must preserve existing control
safety and report exact root-owned integration deltas. No commits/publication.

Approval-pending versus actually-started actions; restart/duplicate prevention;
task/phone ownership; secrets in checkpoints/templates/context; provider failures;
uncertain task completion; stale voice/control callbacks; UI actions with real
effects; errors/empty sources represented truthfully; context-budget growth.
