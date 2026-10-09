# Ankita browser runtime rework implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use subagent-driven development only if delegation is explicitly authorized. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver reliable, efficient, observable browser work in Ankita with better page understanding, guarded actions, retained evidence, and clear desktop progress.

**Architecture:** Adapt the reviewed Browser Use mechanisms inside the existing JavaScript agent. Keep Playwright isolated sessions and the approved Chrome MCP connection. Structured internal observations/results feed the existing textual tool protocol and optional UI progress. No Python sidecar, extra router request, or memory re-import in this proposal.

**Tech Stack:** Node ESM, existing Playwright and chrome-devtools-mcp dependencies, Node's serial test runner, Electron/React/TypeScript renderer, existing sibling ankita-browser-lab.

**Spec:** [Reference findings and proposed design](../../browser-use-reference-findings.md#proposed-design), reviewed upstream commit `914c59bdd4acd50e9628a97a96a3919313aebc85`.

**Status:** Approved by the user for implementation. Work is in progress; the nine tasks and rollout gates below remain the completion contract.

**8 October steering:** The user requested replacing custom isolated-page
automation with native stealth Playwright MCP tools and keeping the managed
browser tool for the user's Chrome session. A concrete source review and proposed
migration are in [the review draft](../specs/2026-10-08-native-browser-mcp-migration-design.md).
The design was subsequently approved, then superseded by the instruction below.
No replacement default or completed gate is implied.

**9 October steering:** The user explicitly requested preserving the current
browser tool and repairing batch edits, refs and recovery instead of purging it.
Continue this plan against both existing adapters. The immediate fixes and their
live evidence are recorded in [reference findings](../../browser-use-reference-findings.md#current-browser-repair--9-october-2026).
Use the catalogue-advertised free Step 5 route for a few targeted model tasks,
not the cancelled 80/160-attempt queues. Experimental defaults remain off; these
repairs do not establish completion of every rollout gate below.

**9 October page-reading clarification:** Prioritize Markdown page structure,
readable hidden/overlay content and reliable refs within Task 3. Retain opaque
observation-scoped targets and expose non-rendered DOM text only as labelled
read-only evidence. Loaded DOM text is distinct from clickable state. Chrome
metadata enrichment is bounded; unknown states and frame limitations are explicit.
No arbitrary model JavaScript, new browser server or Node agent is introduced.

## Global constraints

- Read AGENTS.md and RTK.md; preserve the dirty working tree and existing browser improvements. Start from the current working tree, not just committed HEAD.
- One agent/conversation, existing memory and providers. Browser focus remains a refusing execution boundary with an explicit general exit.
- Preserve approval, private credential login, navigation/network policy, background-job scopes, screenshot artifacts, Stop, takeover, and exactly one tool reply per declared call.
- No raw CDP connection to the user's Chrome. Use the existing approved MCP interface and capability detection.
- No inline production magic values. Share operation metadata, bounds, units, status values, error codes, and protocol version through named constants/configuration.
- Any feature switch is declared in `src/core/config.mjs`, defaults off while experimental, and is measured separately. Reuse existing focus/history switches; never silently turn them on.
- No new dependency is expected. If a later feasibility result requires one, apply dependency review before installation and present its concrete tradeoff.
- Do not transplant Browser Use prompts, model restrictions, timing defaults, telemetry, cloud assumptions, or arbitrary script execution wholesale.
- For substantial copied upstream implementation, preserve MIT attribution and pinned source provenance. Native implementations of the proposed interfaces should be the default.
- Bugs require a captured failing reproduction before changing behavior. Every implementation milestone has regression and real-browser checks; static/source assertions do not replace behavioral verification.
- Commits, pushes, model spending beyond approved evaluation, and releases are separate actions. No release is part of this plan-review task.

## Review focus

| Risky input/path | Owning tasks and required evidence |
| --- | --- |
| Stale/cross-tab/cross-frame refs, same-URL reloads, reconnect, ambiguous replacement | Tasks 2-4: refusal before mutation, fresh observation, correct invalidation on both backends. |
| Dynamic forms, autocomplete, dialogs, navigation during batches, timeout after dispatch | Tasks 3-5: executed/uncertain/deferred receipts; exactly one fixture write; no automatic replay. |
| Long pages, hidden/covered controls, shadow roots, detached frames, oversized evidence | Tasks 1, 3, 5: explicit truncation, provenance, accurate control states, bounded observations and evidence. |
| Malicious page text, credentials, uploads/downloads, disabled browser, background jobs | Tasks 2-7: existing permission and credential tests; content stays data; unsupported capabilities fail closed. |
| Small context, text-only models, discovery misses, focus switches, repeated calls, Stop | Tasks 5-9: request pairing/context checks, capability-aware vision, bounded recovery, no focus escape, UI/runtime cancellation evidence. |

Finding ownership: B1 → Tasks 2/4; B2 → 3; B3/B4 → 5; B5 → 3; B6 → 2/4; B7 → 6; B8 → 5/6/9; B9 → 2/4/7; B10 → 5/9; B11 → 8; B12 → 7. Task 1 establishes the shared measurement/oracle baseline; Task 9 owns rollout evidence for every finding.

## Interface decisions to implement

Create the following contracts in `tools/browser/contracts.mjs` and `tools/browser/contracts.d.mts`. These are proposed names/shapes; changes require updating the owning tests and this plan together.

```ts
type BrowserObservation = {
  version: number;
  id: string;
  mode: 'isolated' | 'local';
  tabId: string;
  url: string;
  documentId: string | null; // Unknown is explicit; never fabricate a CDP identity.
  controls: BrowserControl[];
  context: BrowserTextChunk[];
  omissions: { truncated: boolean; frames: number | null; controls: number | null };
  capabilities: BrowserCapabilities;
};

type BrowserControl = {
  ref: string;
  frameId: string;
  role: string;
  name: string;
  states: Record<string, string | boolean>;
  editable: boolean | null;
  actionable: boolean | null;
};

type BrowserTextChunk = {
  sourceUrl: string;
  frameId: string;
  start: number; // Character offset in the bounded page-text source.
  end: number;
  text: string;
  observationId: string;
};

type BrowserCapabilities = {
  guardedSequences: boolean;
  pageTextSearch: boolean;
  chunkedRead: boolean;
  documentIdentity: boolean;
  dialogs: boolean;
  downloads: boolean;
  uploads: boolean;
};

type BrowserStepReceipt = {
  index: number;
  status: 'executed' | 'failed' | 'uncertain' | 'not_run';
  errorCode?: string;
  retrySafe: boolean;
};

type BrowserActionResult = {
  status: 'executed' | 'failed' | 'uncertain' | 'partial' | 'not_run';
  action: string;
  observation: BrowserObservation | null;
  steps: BrowserStepReceipt[];
  evidence: BrowserEvidence[];
  artifacts: BrowserArtifact[];
  error: { code: string; message: string; recovery: string } | null;
  timings: Record<string, number>; // Milliseconds; measured segments only.
};

type BrowserEvidence = {
  id: string;
  kind: 'observed_text' | 'field_value' | 'url' | 'artifact';
  sourceUrl: string;
  observationId: string;
  text: string;
};

type BrowserArtifact = {
  kind: 'screenshot' | 'download';
  path: string;
  bytes: number | null;
};
```

- Adapter `observe(args, ctx)` returns a `BrowserObservation`. Adapter `execute(args, ctx)` returns a `BrowserActionResult`. Existing adapter `run(args, ctx)` remains a text/legacy-artifact facade over the same execution, not a second execution.
- Manager `run(args, ctx)` preserves its current public return contract. Inside its serialized queue it consumes detailed results, updates progress, then formats once. Existing screenshot receipts retain the fields consumed by `src/core/agent.mjs` and desktop artifacts.
- `renderBrowserResult(result, options)` produces the compact model-facing text. Its result must still distinguish failures for existing verification consumers until those consumers accept structured status directly.
- `validateSequence(steps, observation, capabilities)` rejects unsupported/nested/login/cross-observation steps before any mutation. `executeSequence(plan, executor, ctx)` returns a receipt for every submitted step and one final observation where available.
- `projectBrowserContext(messages, evidence, options)` preserves stored history and tool pairing. Evidence is turn/task state owned by the current agent, not personal memory.
- `recordBrowserProgress(previous, result, action)` returns observed change and recovery guidance. Unknown state does not become verified progress.

## Task 1 — Expand the lab baseline and diagnostics

**Files:** modify sibling lab `src/metrics/collect.mjs`, `src/metrics/aggregate.mjs`, `src/run/runner.mjs`, `src/run/ankita.mjs`, `src/run/models/stub.mjs`, `src/tasks/load.mjs`, `src/core/args.mjs`, `src/cli.mjs`, `src/core/constants.mjs`; create `src/run/experiment.mjs`, `src/apps/workflow.mjs`, `test/experiment.test.mjs`, `test/workflow.test.mjs`, and these task documents under `tasks/workflow/`: `workflow-01-navigation.json`, `workflow-02-autocomplete.json`, `workflow-03-dialog.json`, `workflow-04-same-url-replacement.json`, `workflow-05-new-tab.json`, `workflow-06-long-text.json`, `workflow-07-comparison-evidence.json`, `workflow-08-browse-save.json`.

- [ ] Record current config, Ankita tree revision/dirty state, adapter, provider/model ID, guide/focus/projection flags, context capacity, budgets, machine pressure, and suite composition in each experiment manifest. Keep keys/tokens out of artifacts.
- [ ] Capture a baseline before implementation. Reuse the eight shop tasks across all tiers and existing external-web tasks; deterministic local fixtures are the causal reliability gate, external sites are supplementary.
- [ ] Add a workflow fixture with independent server state for a form, a submit counter, modal, autocomplete, same-URL replacement, new-tab action, long text beyond the first read chunk, and a delayed reply after one successful submission. Tests assert fixture state directly.
- [ ] Register separate tasks for navigation-interrupted sequences, ambiguous replacements, hidden/covered controls, multi-page comparison evidence, long-page extraction, and browse-then-save. Preserve negative-control scoring.
- [ ] Implement deterministic paired ordering using a recorded seed and alternating baseline/candidate order within each task/model/repeat block. Do not schedule competing Chromium runs on this machine for timing comparisons.
- [ ] Add per-round time-to-first-event, provider retries, request/schema/history sizes, browser observation/action/preview time, recovery count, executed/deferred primitive counts, duplicate submissions, and partial outcomes. Mark unavailable provider-prefill metrics as unavailable.
- [ ] Separate agent completion time from evaluator read-back/cleanup time. Retain both instead of silently changing the historic wall-time definition.
- [ ] Prove experiment ordering, failure inclusion, provider-error classification, fixture write counts, and negative controls with lab tests. No model call is required for these tests.
- [ ] Run `rtk proxy node --test --test-concurrency=1` in the lab with the documented test-default repeat configuration isolated from the user's `lab.config.json`. The existing repeat-default mismatch is a known environment issue; report it if not isolated.
- [ ] Run `rtk proxy node src/cli.mjs tasks:validate`, then the existing stub shop suite and corrupted-oracle negative control. Test new fixture state/oracles independently; execute new workflow stub tasks as their required operations become available. Record missing baseline capabilities explicitly rather than calling those failures harness defects or passes. Stub passes prove fixtures/harness, not model intelligence.

**Exit:** reproducible manifests and valid independent oracles; no runtime optimization has been credited with a speedup yet.

## Task 2 — Introduce structured internal browser contracts

**Files:** create `tools/browser/contracts.mjs`, `contracts.d.mts`, `operations.mjs`, `test/tools/browser-contracts.test.mjs`; modify `browser.mjs`, `pending.mjs`, `refs.mjs`, `session.mjs`, `playwright.mjs`, `chrome.mjs`, `src/core/config.mjs`, `src/core/verify.mjs`; extend `test/tools/browser.test.mjs`, `test/core/browser-efficiency.test.mjs`.

- [ ] Write failing tests for truthful executed/uncertain/partial status, unknown capabilities, stable serialization, screenshot compatibility, and one execution through both detailed and legacy facades. Reproduce the audit's partial-batch classifier result and assert it becomes a failure/partial outcome without discarding the executed first step.
- [ ] Move operation enums/metadata and repeated limits into shared named constants. Define `browserRuntimeV2` / `BROWSER_RUNTIME_V2` in layered configuration and test loading it; default false before parity gates.
- [ ] Introduce the contracts while preserving existing tool names/actions and approval/read-only classification. Keep private backend handles outside serialized observations.
- [ ] Preserve a failure signal consumed by `isToolFailure` and `verdictFor`; numbered partial-batch text must not be accidentally reported as an ordinary success. Structured consumers use explicit status.
- [ ] Distinguish failure before dispatch from uncertain outcome after dispatch. Every error has a recovery instruction that does not suggest blind mutation replay.
- [ ] Keep screenshot artifact/image handling and text-only-model fallback unchanged in behavior. Test actual model request pairing and artifact shape, not only formatter strings.
- [ ] Verify disabled modes, scope permissions, credential redaction, cancellation, and existing private login regressions with the affected tests.
- [ ] Execute a real Chromium open/fill/read-back through the public tool path and the existing real Chrome verification script before claiming both backends migrated.

**Exit:** a single execution path per adapter with backward-compatible public outputs, typed internal state, and explicit capability limitations.

## Task 3 — Rework page observations and deterministic reading

**Files:** create `tools/browser/observations.mjs`, `tools/browser/page-find.mjs`, `test/tools/browser-observations.test.mjs`, `test/tools/browser-reading.test.mjs`; modify `playwright.mjs`, `chrome.mjs`, `refs.mjs`, `browser.mjs`; extend `test/tools/browser-automation.test.mjs`, `scripts/verify-browser-automation.mjs`.

- [ ] Reproduce the selected observation gaps on Task 1 fixtures: covered controls, form context, values/states, content after the current prefix, detached frames, and duplicated labels. Capture baseline snapshots before changing serialization.
- [ ] Normalize both backend observations into controls plus source-linked context. Keep opaque refs, frame/tab ownership, current epoch, and honest truncation/omission metadata.
- [ ] Prefer relevant form/context groups and visible/actionable controls. Expose disabled/readonly state rather than accidentally treating every visible element as an editable target. Preserve useful noninteractive stock/validation text.
- [ ] Playwright must retain real shadow-root/frame handling and recheck normal actionability. Use bounded probes; do not collect every attribute/listener on a framework-heavy page.
- [ ] Chrome must use the bundled MCP's supported snapshot/evaluation operations. Probe capabilities, reject unsupported combinations, and represent unavailable identity/actionability information as unknown.
- [ ] Add `find` as bounded case-insensitive page-text search with contextual chunks, and `read` chunk/cursor arguments. Define shared text/chunk/match limits with units; return continuation/truncation explicitly. Preserve no-argument read behavior through the compatibility formatter.
- [ ] Cursors are scoped to the source observation/document; navigation or source change refuses a stale cursor and returns recovery guidance. Do not return selectors or text-match guesses as actionable refs.
- [ ] Test password masking, malformed queries/cursors, Unicode offsets, long pages, frames, and unavailable capabilities. Deterministic reading performs no auxiliary model request.
- [ ] Run the observation/reading/automation suites and real Playwright plus real Chrome fixtures. Compare content correctness and backend capability differences, not byte-identical trees.

**Exit:** consistent model-facing observations and page reading with bounded cost, source identity, and explicit omissions.

## Task 4 — Implement observation-bound guarded sequences

**Files:** create `tools/browser/sequence.mjs`, `test/tools/browser-sequence.test.mjs`; modify `operations.mjs`, `browser.mjs`, `session.mjs`, `playwright.mjs`, `chrome.mjs`, `refs.mjs`; extend form-preflight, job-scope, lifecycle, and tool-budget tests.

- [ ] Reproduce current batch behavior and the proposed invariants with Task 1 forms. Write failing tests before enabling new sequence behavior.
- [ ] Replace generic step objects with a bounded typed schema. Reject nested batches, credential login steps, mixed backend/tab ownership, unknown operations, and invalid refs before mutation.
- [ ] Start with one current observation and related editable-field operations. Reuse the existing all-fields preflight, then revalidate immediately before each mutation because a prior field can change the form.
- [ ] Establish metadata boundaries for navigation, tab switch, close, submit, and operations that may trigger a dialog. After each primitive, inspect the relevant supported state. Stop the dependent suffix on changed document/tab, dialog, detached/changed target, cancellation, or uncertain result.
- [ ] Expected input-value changes alone do not invalidate the plan. Changes to the target identity/form structure or required autocomplete selection do. Avoid full DOM capture between every ordinary field fill when a bounded guard suffices.
- [ ] Playwright may retain verified private handles within one sequence; publish fresh opaque refs only after the sequence. Chrome may suppress optional intermediate snapshots only if its UID/action contract and guard probes are proven live. Otherwise use its native fill_form path or refuse the unsupported chain before writing.
- [ ] Never bind a stale ref to a guessed replacement in another document. Fresh recovery observations guide a new model decision; no automatic retry of the failed mutation.
- [ ] Return every step's status, including unexecuted suffixes, and preserve partial successes when the last action/snapshot fails. Produce one final observation where possible.
- [ ] Count a sequence as one model tool call plus its primitive actions. Add a named per-turn primitive cap derived from existing limits; apply it before dispatch and expose exhaustion honestly. Test that batching cannot bypass approval, Stop, scope, repeat, or call budgets.
- [ ] Run both backend contracts and live fixtures. Require exactly one server-side submission/cart increment under delayed replies, navigation, dialogs, snapshot failure, and cancellation.

**Exit:** useful batching reduces avoidable observations/rounds while preserving fresh-state and exactly-once dispatch discipline. Do not claim exactly-once external transaction delivery; uncertain remote effects still require read-back.

## Task 5 — Preserve evidence and detect stalled browser work

**Files:** create `src/core/browser-progress.mjs`, `test/core/browser-progress.test.mjs`; modify `src/core/browser-context.mjs`, `agent.mjs`, `verify.mjs`, `config.mjs`; extend `test/core/browser-efficiency.test.mjs`, `tool-budget.test.mjs`, `stream-recovery.test.mjs` and mixed-goal lab tasks.

- [ ] Write a failing multi-page comparison test in which a source fact disappears under the current request projection, and a stalled-page test using changing refs/arguments. Keep full stored history as the independent reference.
- [ ] Accumulate bounded observed evidence with URL/observation provenance from typed results and explicit read-back. Retain task-critical comparison facts when obsolete control trees are projected away.
- [ ] Do not parse a website's instructions into system directives, invent semantic facts with regex, or put every observed value into personal memory. Model-selected evidence must be grounded in a captured chunk; unsupported claims remain unverified.
- [ ] Project latest controls plus relevant evidence and compact receipts into requests. Preserve tool-call IDs/replies, failures, user messages, memory/checklists, screenshot capability behavior, and the actual model context budget.
- [ ] Fingerprint relevant page/progress state, not only tool arguments. Distinguish repeated reading with no new evidence from legitimate pagination, quantity changes, or observation after a completed mutation.
- [ ] Add bounded recovery guidance/counts without replacing current hard repeat/step/call limits. Transport failure, invalid input, stale target, uncertain mutation, provider error, and user denial remain distinct.
- [ ] Keep execution receipt separate from goal verification. A click or fill can be executed without proving the requested checkout, quantity, or record. Read-back checkpoints provide explicit evidence; final text must disclose unresolved outcomes.
- [ ] Test small context, multiple turns, focus enter/exit, browse-then-save, snapshot failures, Stop, and no duplicated submission during recovery. Demonstrate no extra summary/router model call on the ordinary browser path.
- [ ] Run focused core tests, then real fixture workflows on both backends. Keep evidence projection opt-in until broad live parity passes.

**Exit:** reduced obsolete context without loss of required facts, and fewer wasted recovery rounds without weakening runtime termination.

## Task 6 — Improve model guidance and initial discovery

**Files:** modify `skills/browser-use/SKILL.md`, `src/core/agent.mjs`, `src/core/skills.mjs` only where necessary, `tools/find-tools.mjs`, `docs/guides/browser-use.md`; extend `test/core/browser-skill.test.mjs`, `browser-workflow.test.mjs`, `browser-efficiency.test.mjs` and lab discovery tasks.

- [ ] Reproduce the no-browser-discovery path with a scripted model fixture, then include a live discovery task in Task 9. A fixture proves prompt availability, not that every model obeys it.
- [ ] Add a short pre-discovery affordance in the existing system/tool description: use exact browser discovery for interactive page work and restore general access for nonbrowser goals. No extra model routing request or keyword classifier.
- [ ] Keep the full MD guide turn-local and bounded after accepted discovery/use. Preserve disabled-skill and non-chat behavior; no full-body injection into every unrelated task.
- [ ] Update the guide for structured observations, targeted read/find, supported sequences, uncertainty, evidence, and verification. Avoid model-specific prompts or fixed website recipes.
- [ ] Keep out-of-focus group loading/execution refusing, explicit general exit, memory/checklist continuity, counted focus calls, and per-turn cleanup. Test rejection does not activate extra groups/skills.
- [ ] Run guided/unguided scripted workflows, the no-extra-call assertion, disabled-guide cases, and negative controls. Reserve claims about reliability/speed for the live evaluation.

**Exit:** the model can see how to start browser work and receives concise operational guidance when applicable, in the same session.

## Task 7 — Complete ordinary navigation, dialog, and file workflows

**Files:** modify `tools/browser/operations.mjs`, `contracts.mjs`, `browser.mjs`, `session.mjs`, `playwright.mjs`, `chrome.mjs`, `src/integrations/browser-plugins.mjs` only if supported capability discovery needs it; create `test/tools/browser-navigation.test.mjs`, `browser-dialogs.test.mjs`, `browser-transfers.test.mjs`; extend job navigation/scope tests and the lab workflow fixture/tasks.

- [ ] Capture baseline behavior for navigation in the selected tab, back/forward, an alert/confirm/prompt, an upload, and a completed/canceled download. Label absent operations as capability gaps.
- [ ] Keep `open` compatible. Add explicit `navigate`, `back`, and `forward` operations that act on the requested tab, invalidate old refs/cursors, honor navigation/network policy, and return a current observation. Verify redirects and same-URL reloads.
- [ ] Expose dialog attention with supported dialog metadata. Add `handle_dialog` accept/dismiss and optional prompt input with existing mutation approval/redaction. Never treat a confirm dialog as permission to perform the underlying sensitive action.
- [ ] Add upload only for an explicitly user-selected/authorized file, never a path invented from page content. Resolve canonical containment and existing permissions before dispatch, preserve private credential boundaries, and verify the page's resulting file selection.
- [ ] Implement Playwright download lifecycle in the owned session: pending/completed/canceled/failed state, safe destination in the authorized workspace, sanitized filename, bounded transfer wait, and artifact existence/size read-back. Do not infer a completed download from clicking its link.
- [ ] Probe the approved Chrome MCP's supported operations and file-root restrictions. Do not inspect the user's general Downloads directory or create a raw CDP bridge to obtain missing events. Where completion cannot be proven, report the capability limitation and offer existing manual takeover/import behavior.
- [ ] Add concrete lab navigation, dialog, and transfer tasks under `tasks/workflow/`: `workflow-09-history.json`, `workflow-10-dialog.json`, `workflow-11-upload.json`, `workflow-12-download.json`. Extend the stub oracle only for supported operations and preserve independent artifact/state checks.
- [ ] Test traversal/symlink containment, malicious filenames, changed tabs, user cancellation, dialogs after dispatch, partial transfers, redirect policy, and unsupported Chrome capabilities. Record real versus mocked coverage.
- [ ] Execute safe local fixtures through both real backends. Unsupported capability is tested and documented; it is not reported as successful feature parity.

**Exit:** ordinary browser operations have explicit semantics and verified capability reporting; files and dialogs cannot bypass permissions or mutation uncertainty.

## Task 8 — Make the live browser experience understandable and smooth

**Files:** modify `tools/browser/session.mjs`, `desktop/electron/engine.mjs`, `desktop/shared/wire.ts`, `desktop/renderer/src/components/BrowserStage.tsx`, relevant browser-stage styles in `desktop/renderer/src/styles.css`; create `desktop/shared/browser-progress.mjs`, `desktop/shared/browser-progress.d.mts`, and `test/desktop/browser-progress.test.mjs` for behavioral state mapping. Read actual engine event wiring before editing it.

- [x] Add bounded runtime progress events with phase, public action label, step counts, recoverability, and observed outcome. No credentials, entered text, DOM dumps, or model-internal reasoning in these events.
- [x] Extend BrowserSessionView additively so existing consumers continue to work. Verify foreground/scoped background event ownership and takeover behavior.
- [x] Present thinking, reading, acting, checking, recovering, waiting-for-user, stopped, and finished states; display partial outcomes without a false success indicator.
- [x] Preserve live preview, tab selection, Take control/Hand back, keyboard access, and Stop. Add subtle transitions that respect reduced motion and do not shift panel layout during each event.
- [x] Profile preview capture/IPC/render cost with the agent running, with the pane hidden, and with the window backgrounded. Tune shared named polling limits only if the trace demonstrates contention; do not conflate preview time with model latency.
- [x] Test presenter/state/event behavior and run `rtk proxy npm run desktop:build`. Live-check the developed desktop with actual runtime events; mock animation timers alone are insufficient.
- [ ] Check a packaged Electron build for Stop during action/recovery, manual sign-in, dialog attention, reconnect, long progress labels, reduced motion, and teammate/background ownership. Record which checks were real and which were fixtures.

Task 8 evidence (2026-10-08): progress/lifecycle/contracts 36/36; developed and
actual packaged local HTTP/SSE workflows passed, including native prompt choices,
Stop, reduced motion, native minimize/quit and static-page recovery. Preview
four-second samples were visible 37, hidden pane 1, background 1. The same archive
passed eight-round desktop and encrypted sign-in verifiers. Public scope ownership
has manager regression coverage; packaged background selection, broken-transport
UI reconnect, native file picker and heavier-page profiling remain open. The full
trace and disposable artifact paths are recorded in the progress ledger and
`docs/browser-use-reference-findings.md`; no live-model speed claim is made.

**Exit:** the user understands current progress and can intervene; visuals remain responsive without increasing agent overhead materially.

## Task 9 — Evaluate, stage rollout, and document coverage

**Files:** update `docs/browser-use-reference-findings.md`, `docs/browser-lab-FINDINGS.md`, `docs/browser-lab-token-research.md`, `docs/guides/browser-use.md`; lab reports/manifests go under its ignored run/artifact directory, not source control. Update configuration defaults only after the corresponding gate passes.

- [x] Run all affected regression suites serially and the full Ankita suite. Execute `rtk proxy node scripts/verify-browser-automation.mjs` for real Playwright and bundled Chrome. Record actual counts, backend traces, and any pre-existing failures/skips.
- [ ] Run the desktop build, developed-desktop workflows, and packaged-desktop checks. Confirm changed screenshot/credential/background contracts still work.
- [x] Validate the lab's task documents and full deterministic stub suite, including negative controls, before spending model calls.
- [ ] Use working provider/model routes from current configuration/catalog discovery. Compare baseline/candidate on the same model, provider, context capacity, budget, backend, fixtures, and machine. Include the previously tested Ling/Step families only if their routes actually work at evaluation time.
- [ ] Recommended evaluation parameter: five independent paired repeats per task/model/condition, serial browser concurrency, with counterbalanced order recorded in the manifest. These are experiment parameters, not hardcoded production limits. Expand repeats when results remain ambiguous.
- [ ] First evaluate observation, sequence, evidence, guidance, and preview changes separately; then the combined candidate. Keep focus/history A/B independent so switch costs are visible.
- [ ] Report pass rate per tier, paired successful-task wall time, all-attempt completion/timeouts, provider errors, prompt/completion tokens, model rounds, tool/observation/preview time, duplicate submissions, stale-ref errors, recovery counts, focus switches, unmet mixed goals, and primitive actions.
- [ ] Label a focused unfinished mixed goal as diagnostic rather than automatic proof of stranding. Inspect whether an explicit general exit was needed and possible; measure actual mode-stranding separately.
- [ ] Capability gates: deterministic fixture expectations all pass, no duplicate submissions, no unauthorized mutation/focus escape, and no lost required evidence. Live pass rates must not regress per tier; compare failures individually. Small samples do not establish statistical equivalence.
- [ ] Performance gate: claim speed improvement only when paired end-to-end time improves with capability gates intact. Recommended material-win target is at least ten percent paired median improvement on the main workflow set, with no reproducible trivial-task regression. Report uncertainty and the slowest rounds. A token drop without a wall-time win is not a speed result.
- [ ] Keep provider failures visible in all-attempt results and report provider-limited comparisons as inconclusive. Never silently filter slower failed attempts or infer prefill savings from total model-round duration.
- [ ] Enable only mechanisms whose gates passed; keep unresolved experiments opt-in. An experimental switch off restores compatibility behavior without resetting user files/config or rolling back unrelated work.
- [ ] Record exact tested commit/tree, command outputs, reports, supported/unsupported capabilities, residual risks, and a confidence ledger. Review introduced literals and run `rtk proxy git diff --check`.

**Exit:** a reviewable implementation with earned reliability/speed claims and a concrete rollback path. Publishing a release requires a separate user request and the normal release gates.

## Verification command map

Commands below are implementation gates, not results from this planning task. Run from Ankita's root except the lab commands, which run from the sibling lab root.

| Task | Focused command |
| --- | --- |
| 1 | `rtk proxy node --test --test-concurrency=1 test/experiment.test.mjs test/workflow.test.mjs test/validate.test.mjs test/collect.test.mjs` (lab) |
| 2 | `rtk proxy node --test --test-concurrency=1 test/tools/browser-contracts.test.mjs test/tools/browser.test.mjs test/core/browser-efficiency.test.mjs` |
| 3 | `rtk proxy node --test --test-concurrency=1 test/tools/browser-observations.test.mjs test/tools/browser-reading.test.mjs test/tools/browser-automation.test.mjs` |
| 4 | `rtk proxy node --test --test-concurrency=1 test/tools/browser-sequence.test.mjs test/tools/browser-form-preflight.test.mjs test/tools/browser-job-scope.test.mjs test/tools/browser-lifecycle.test.mjs test/core/tool-budget.test.mjs` |
| 5 | `rtk proxy node --test --test-concurrency=1 test/core/browser-progress.test.mjs test/core/browser-efficiency.test.mjs test/core/tool-budget.test.mjs test/core/stream-recovery.test.mjs` |
| 6 | `rtk proxy node --test --test-concurrency=1 test/core/browser-skill.test.mjs test/core/browser-workflow.test.mjs test/core/browser-efficiency.test.mjs` |
| 7 | `rtk proxy node --test --test-concurrency=1 test/tools/browser-navigation.test.mjs test/tools/browser-dialogs.test.mjs test/tools/browser-transfers.test.mjs test/tools/browser-job-navigation.test.mjs test/tools/browser-job-scope.test.mjs` |
| 8 | `rtk proxy node --test --test-concurrency=1 test/desktop/browser-progress.test.mjs` and `rtk proxy npm run desktop:build`, followed by developed/packaged desktop checks |
| 9 | `rtk proxy node --test --test-concurrency=1`, `rtk proxy node scripts/verify-browser-automation.mjs`, `rtk proxy npm run desktop:build`, and `rtk proxy git diff --check` |

Lab harness gates use `rtk proxy node src/cli.mjs tasks:validate`, `rtk proxy node src/cli.mjs eval --model stub --tasks shop`, and the corresponding command with `--break`. New workflow oracle tasks run once their operations exist. Live evaluation uses `--model live` with the configured route and recorded paired experiment settings; do not paste a stale model ID or secret into commands.

## Deferred capabilities and boundary decisions

- Browser uploads/downloads are advertised as unsupported until Task 7 proves user-selected file permission, workspace containment, canceled/partial transfer handling, and artifact read-back for that backend. An unsupported Chrome path remains explicit; the contract never opens arbitrary filesystem access through browser tools.
- Coordinate-only vision actions, direct arbitrary JavaScript, CAPTCHA bypass/stealth, cloud browsers, saved replay scripts, and a separate Python agent are outside the initial rework. Evaluate them against concrete remaining tasks rather than importing them automatically.
- Same-URL DOM changes and popup/dialog boundaries need more than upstream URL/focus checks. Chrome sequence acceleration stays unavailable where the approved MCP cannot prove the relevant state/UID invariants.
- No universal completion oracle is promised. Runtime verifies observable checkpoints; the lab independently verifies its task goals. Model judgment is not substituted for either.

## Plan review checklist

These checks review specification completeness, not implementation completion.

- [x] Every B1-B12 finding has an owning task, evidence type, and acceptance gate.
- [x] The plan defines shared statuses and compatible failure handling.
- [x] Backend capability differences are explicit; mocked tests are not described as live checks.
- [x] Sequence boundaries, partial receipts, dispatch uncertainty, action counts, and cancellation are specified.
- [x] The plan preserves existing memory/approval/credential/focus/screenshot contracts.
- [x] No speed claim is based only on fewer tokens or source inspection.
- [x] Planned tests exercise behavior and independent state, not merely copied implementation strings.
- [x] User review is required before implementation; no automatic commit, push, dependency install, or release is included.
