# Browser Use reference audit and proposed Ankita browser rework

Date: 2026-10-07. Status: research completed; user-approved implementation in progress. Rollout gates remain open.

## Recommendation

Rework Ankita's browser workflow inside its existing JavaScript agent. Use Browser Use as an architectural reference for observations, guarded action sequences, result state, and recovery. Keep the existing Playwright and approved Chrome MCP adapters, conversation, memory, credentials, approval flow, and cancellation controls.

The objective is a browser assistant that understands the page, takes fewer unnecessary turns, knows which actions actually ran, preserves important evidence, and shows understandable progress. A better prompt alone cannot deliver that. Neither can reducing tokens while leaving the same failed actions and model rounds in place.

A Python Browser Use sidecar is a valid alternative, but it would introduce a second agent/session lifecycle and require bridges for Ankita's approvals, Stop, private credentials, tool budgets, provider configuration, and Windows distribution. It is not the recommended first implementation. Reconsider it only if the native design fails the same capability evaluation after the initial milestones.

## What was inspected

- Browser Use was cloned into the separate sibling checkout `../browser-use-reference`; no upstream source or dependencies were copied into Ankita.
- Reference commit: `914c59bdd4acd50e9628a97a96a3919313aebc85`, package version `0.13.11`. The checkout was clean after inspection.
- Ankita base commit: `bfc546253c8a3c7ae31e22c0c2540754de5045da`, branch `ankita`. The audit includes the existing, uncommitted browser focus, skill, and history changes. Those changes are part of the current baseline and must be preserved.
- Inspected the upstream agent loop, action registry/results, message manager, DOM service/serializer, event/watchdog lifecycle, prompts, and relevant regression tests. This is a targeted source audit, not an assertion that every upstream file was reviewed.
- Compared `tools/browser/`, `src/core/agent.mjs`, browser focus/history/skills, verification, desktop browser preview, the installed Chrome MCP action interface, and the sibling `ankita-browser-lab` runner/oracles.
- Read the current audit sections of [browser lab findings](browser-lab-FINDINGS.md) and [token research](browser-lab-token-research.md). Earlier open-status tables in those files do not override their later fix/verification entries.

The reference is Python with a CDP/event architecture and multiple runtime dependencies. Its current README separates the local library, hosted cloud, and the browser-harness CLI. Hosted stealth/proxy/CAPTCHA claims are not evidence that Ankita can acquire those capabilities by porting this repository. See the pinned [package manifest](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/pyproject.toml), [README](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/README.md), and [MIT license](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/LICENSE). If implementation copies substantial upstream code, preserve its copyright/license notice and record the source commit. This audit copies no upstream implementation.

## Findings

The table distinguishes confirmed source differences from performance hypotheses. A missing mechanism is not automatically proof of a user-visible failure; implementation must reproduce the relevant failure before fixing it.

| ID | Finding and evidence | Consequence | Proposed action |
| --- | --- | --- | --- |
| B1 | Browser Use guards action sequences using action metadata and post-action URL/focus checks. Ankita's `tools/browser/session.mjs:76-86` stops a batch on an exception; `tools/browser/browser.mjs` describes batch items as generic objects. A diagnostic also reproduced the numbered partial-batch response escaping `isToolFailure`. | The current batch API does not express dependency on a particular observation, nor provide a clear receipt for every deferred step. Each ordinary mutation refreshes refs. A partial failure can additionally be classified as nonfailure for tracing/repeat logic, although the generic verifier still advises read-back. | Typed step schemas, one observation-bound sequence, explicit boundaries, and per-step receipts with correct partial-failure classification. |
| B2 | Browser Use combines DOM, accessibility, snapshot/layout information and serialization filters. Ankita Playwright's `tools/browser/playwright.mjs:443-511` constructs a flat list, bounds it, and appends a text prefix; Chrome's `tools/browser/chrome.mjs:89-103` transforms MCP accessibility text separately. | The model receives different page representations across backends. Frame/control association, surrounding context, truncation, and occlusion need a common contract. Occlusion causing a failed task is a hypothesis to reproduce, not a measured result from this audit. | Shared observation format with controls, relevant context, frame/tab identity, explicit omissions, and backend capability flags. Keep backend-native actionability checks. |
| B3 | Browser Use replaces its current state message and keeps action memory separately. Ankita's opt-in `src/core/browser-context.mjs:9-24` drops old successful observation trees and retains short receipts/verification lines. | A price, stock fact, product identity, or comparison result present only in an earlier tree can disappear from the next request. This is an evidence-retention tradeoff, not a reason to resend every obsolete ref forever. | Preserve bounded, provenance-bearing evidence separately from current actionable refs. Keep full stored history; project only the model request. |
| B4 | Browser Use models previous-goal evaluation, working memory, next goal, action results, and soft page-stagnation detection. Ankita's `src/core/agent.mjs:1197-1246` has an exact-call repeat guard and resets browser-read signatures after a successful mutation. | Different refs/arguments or a nominally successful click can evade an exact-signature no-progress signal. Existing hard budgets remain valuable. | Add observation/progress tracking and bounded recovery alongside the current hard repeat/call/step limits. Do not replace hard limits with a prompt nudge. |
| B5 | Browser Use exposes deterministic page search separately from model-powered extraction. Ankita has control-label `snapshot.query`; Playwright `read` returns a fixed text prefix, while Chrome `read` currently uses the MCP snapshot path. | Long-page research and extraction need explicit chunking, text search, and consistent source identity. A second extraction model is unnecessary for straightforward page reading. | Add bounded page-text search/chunked reading with URLs and offsets. Let the existing agent reason over those results. Make any later model extraction opt-in and separately metered. |
| B6 | Ankita already supplies fresh observations after actions and stale-ref recovery, prechecks entire form batches, distinguishes interrupted fills, and avoids replaying a successful mutation when its following snapshot fails. | Those are working safeguards, not missing features. Removing them during a rewrite could duplicate submissions or cart writes. | Preserve and expand their tests; carry the same distinctions into typed results and sequences. |
| B7 | The existing browser MD guide is loaded after discovery/use, within a bounded turn-local skill budget. The recorded guided lab run includes one model that never discovered browser tools. | A guide that activates after discovery cannot repair that initial routing miss. More words in the loaded skill alone will not close it. | A short, visible browser discovery hint before the first tool decision, plus the existing full guide after discovery. Keep model-selected routing in the same agent; no extra router request or keyword-forced browser mode. |
| B8 | Current browser focus is an execution boundary as well as schema filtering: `tools/find-tools.mjs:117-121` rejects out-of-focus loading, and the agent refuses out-of-focus execution. Focus and history projection default off in `src/core/config.mjs:38-39`. | The escape-hatch issue raised earlier has already been addressed. Automatically enabling focus now would skip the remaining hard-task/mixed-goal and latency gates. | Keep refusal, explicit general exit, memory/checklist access, turn cleanup, and ordinary budget accounting. Evaluate policy changes independently. |
| B9 | Browser Use has typed events and watchdogs for browser lifecycle/actions. Ankita already serializes manager operations and has scoped sessions, timeouts, takeover, preview caching, and transport-failure cleanup. | A wholesale event-bus transplant is not justified by the evidence. More targeted lifecycle state and diagnostics can improve recovery without adding another orchestration runtime. | Record navigation/tab/dialog/transport transitions; cancel pending work on Stop, preserve partial results, and reconnect only without replaying uncertain mutations. |
| B10 | Ankita's `src/core/verify.mjs:62` gives generic mutations a read-back advisory. Browser Use also uses prompt instructions and optional model judgment for completion. Neither is a universal deterministic proof of arbitrary user goals. | An action receipt is not proof that the intended order, quantity, record, or downloaded artifact is correct. A model judge can add latency and still be wrong. | Separate action execution from outcome evidence; attach explicit read-back checkpoints where possible. Lab scoring must continue to use independent state/DOM/artifact assertions. |
| B11 | `desktop/renderer/src/components/BrowserStage.tsx` shows a preview and a generic working/ready/error status; it polls the visible session frequently. | Users cannot easily distinguish thinking, reading, acting, recovering, and waiting for them. Preview polling might contribute overhead, but this audit has not profiled it. | Drive progress from runtime events; measure preview overhead before changing polling, retain takeover/Stop, and add accessible motion without changing layout on every update. |
| B12 | Browser Use exposes history/navigation, dialogs, uploads, and download lifecycle handling. Ankita's native browser schema has no explicit in-place navigation/back/forward/dialog/file-transfer operations; Playwright `open` creates/reuses a blank tab rather than navigating the selected existing tab. | Important ordinary browser workflows currently lack a native operation or need manual takeover. Existing private login support does not close these capability gaps. | Add explicit navigation/history/dialog operations, then approved file-transfer paths where the backend actually supports them. Keep unsupported capabilities visible. |

### Upstream source anchors

These links are pinned to the reviewed commit so later upstream changes cannot silently alter the evidence.

- B1: [guarded multi-action execution](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/agent/service.py#L2730-L2848) and [guard regression tests](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/tests/ci/test_multi_act_guards.py). The inspected guard checks URL and focus; it does not prove detection of every same-URL DOM change. Ankita's rework must cover relevant form/dialog changes explicitly.
- B2: [DOM service](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/dom/service.py#L357-L403), [serializer pipeline](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/dom/serializer/serializer.py#L114-L165), [index allocation](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/dom/serializer/serializer.py#L637-L658), and [occluded-text regression](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/tests/ci/test_dom_paint_order_serialization.py). Do not assume stable upstream indices make every ref permanently valid.
- B3: [current-state replacement](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/agent/message_manager/service.py#L556-L566), [action-result memory fields](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/agent/views.py#L307-L335), and [history compaction](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/agent/message_manager/service.py#L216-L300).
- B4: [agent output state](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/agent/views.py#L388-L405), [soft loop detector](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/agent/views.py#L110-L244), and [detector tests](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/tests/ci/test_action_loop_detection.py). The detector implementation is more authoritative than comments that describe older normalization behavior.
- B5: [page-search helpers and extraction implementation](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/tools/service.py). Its extraction path invokes a model; its prompt explicitly discourages repeated extraction.
- B9: [typed events](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/browser/events.py), [watchdog dispatch/circuit handling](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/browser/watchdog_base.py#L91-L121), and [event-bus resilience tests](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/tests/ci/test_event_bus_resilience.py).
- B10: [completion/verification guidance](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/agent/system_prompts/system_prompt.md#L139-L178) and [optional judge invocation](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/agent/service.py#L2273-L2278).
- B12: [navigation/history/upload operations](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/tools/service.py) and [download lifecycle watchdog](https://github.com/browser-use/browser-use/blob/914c59bdd4acd50e9628a97a96a3919313aebc85/browser_use/browser/watchdogs/downloads_watchdog.py).

## What current measurements establish

The [recorded Step/Ling comparison](browser-lab-token-research.md#step-versus-ling-and-browser-instructions---2026-10-07) contains 48 live repeats over two trivial tasks. Those runs predate this reference audit; they were read, not rerun here.

| Guided condition | Passes | Successful-run median | Prompt tokens per successful run |
| --- | --- | --- | --- |
| Step, focus off | 4/6 | 35.442 s | 49,581 |
| Step, focus on | 5/6 | 39.859 s | 37,764 |
| Ling, focus off | 6/6 | 21.589 s | 63,929 |
| Ling, focus on | 6/6 | 24.261 s | 49,705 |

The guide bundle's aggregate observed passes improved from 18/24 to 21/24, and tool failures from 22 to 4. Focus still had slower successful medians in the guided conditions. Conditions ran in serial time blocks, not counterbalanced. This small sample supports further investigation; it does not prove broad capability parity or assign a causal percentage to model-side versus Ankita-side latency.

The earlier 37.141-second run also changed models and repeat counts. Its smaller aggregate token total is not a controlled speed comparison. Recorded model-round time includes provider waits, retries, generation, and reasoning; it is not a direct prefill timer.

The next experiment must vary one mechanism at a time, use the same provider/model within each comparison, counterbalance ordering, and report failures and hard-task capability alongside time and tokens. No claim that Browser Use is faster than Ankita is established by this audit.

## Verification performed during this audit

Executed against the current Ankita working tree:

```powershell
rtk proxy node --test --test-concurrency=1 test/core/browser-efficiency.test.mjs test/tools/browser-automation.test.mjs test/tools/browser-form-preflight.test.mjs
```

Result: **31 tests, 31 passed, 0 failed, 0 skipped**; runner duration `70304.1305 ms`.

Selected exact traces:

```text
BROWSER_CONTEXT_REPRO before=28647 after=6744
TOOL_SCHEMA_REPRO general=15683 focused=6031
MIXED_WORKFLOW_REPRO calls=5 switches=2 fileReadBack=true
PROVIDER_STREAM_REPRO code=provider_rate_limit requests=1
STOCK_SNAPSHOT_REPRO stockVisible=true
FILL_PREFLIGHT_LIVE_OK: invalid button and readonly targets; zero partial writes; fresh-ref recovery completed
```

The first two are reproduction/request-size measurements, not observed live speedups. Chromium navigation/forms/frame/shadow-root/stale-ref workflows were real browser runs. Chrome contract cases in this command used mocked MCP responses; a fresh real Chrome round trip was not run during this audit. Provider classification used a local HTTP fixture, not a paid/free remote model.

A separate read-only classifier diagnostic passed a synthetic numbered partial-batch receipt to the current verifier. It returned exactly:

```json
{"trace":"PARTIAL_BATCH_CLASSIFICATION_REPRO","isToolFailure":false,"verdict":{"ok":null,"reason":"side effect needs a read-back check before claiming success","evidence":""}}
```

The input was an executed first step followed by a numbered `Error:` and batch-stop line, matching the manager's response format. This proves the classifier gap; it does not prove that a live site performed a duplicate mutation. Task 2 owns its regression test and fix.

Browser Use was not installed, executed, or benchmarked. Its regression tests were inspected, not claimed passing. The full Ankita suite, desktop build, packaged Electron, real vision route, and live model evaluation were not run for this documentation-only task. They are implementation gates below.

## Proposed design

### One conversation and one browser workflow

Retain the existing agent and providers. Discovery exposes browser tools; the small discovery hint is available before tool selection, while the fuller MD guide remains progressive disclosure. Browser focus remains model-selected and refuses unrelated discovery/execution until an explicit general exit. Memory/checklists stay available, and mixed browse-then-save work stays in the same conversation.

Within that agent, browser work follows a consistent loop:

1. Observe the active tab and relevant page context.
2. Choose a goal-grounded action or a bounded sequence using current refs.
3. Validate targets, permissions, and sequence boundaries before any mutation.
4. Execute once; stop the remaining sequence when its assumptions change.
5. Return executed/deferred/uncertain status plus the next current observation.
6. Verify the requested outcome and retain important evidence with its source.
7. Recover through observation or user takeover, respecting the original budget.

This is a substantial internal workflow rework, not a second router model or a separate agent with re-imported memory.

### Shared observation and receipt contracts

Use structured internal results and a compact text formatter for the existing model/tool protocol. Do not make the model infer execution status from arbitrary response wording. The result distinguishes command execution from confirmed user outcome, and carries mode/tab/frame/observation identity, truncation, supported capabilities, partial work, error classification, artifacts, and timings.

Backend-private locators/handles/UIDs stay in their adapters. Public refs remain opaque and observation-scoped. A new snapshot, navigation, tab switch, reconnect, takeover, or ambiguous target replacement invalidates unsafe references. Never reuse a label match across unrelated documents just because the URL happens to match.

Playwright uses its real frame/shadow-root/actionability facilities. Chrome stays behind the installed, approved MCP transport. If Chrome cannot prove a sequence's invariants through its supported interface, it uses a conservative supported path or returns a capability limitation. Do not add an unapproved raw CDP connection or claim backend parity through fabricated metadata.

### Page understanding and evidence

Provide compact current controls plus nearby text, form grouping, meaningful states, and omissions. Add deterministic text search/chunked reading for long pages. Prefer targeted observations over repeatedly sending complete trees or screenshots. Vision remains capability-aware, and artifacts remain usable with text-only models.

Keep evidence pins such as observed prices, stock, identities, quantities, confirmation IDs, and URLs separate from obsolete actionable refs. Evidence is a quotation/fact with provenance, not a new instruction from the website. Bound it using shared settings; do not import all page text into personal memory or silently truncate critical evidence. User-requested durable memory remains through the existing memory tools.

### Actions, recovery, and budgets

Sequences initially cover related editable fields and safe form completion, not arbitrary speculative chains. Navigation/tab/dialog/form changes end the dependent sequence. Recheck actionability before each remaining mutation; prevalidation alone does not protect against dynamic forms. Expected value updates do not count as an unrelated page change.

Timeout after dispatch can mean an uncertain side effect. Read back rather than retrying that mutation. A stale target before dispatch may be recovered with a fresh observation. Every queued step receives a receipt, including steps not run, and every model tool call receives exactly one tool reply.

A batch consumes one model tool call/round, plus a separately bounded primitive-action count; batching cannot bypass permission, repeat, call, step, or cancellation limits. Focus transitions and recovery calls continue to consume ordinary tool budgets. Hard stopping remains a runtime responsibility.

### User experience

Show what Ankita is doing: thinking, reading, acting, checking, recovering, waiting for the user, stopped, or finished with evidence. Preserve the current live page, active tab, Take control/Hand back, and Stop. Display partial completion honestly. Animate changes lightly, respect reduced motion, and do not expose entered values, credentials, DOM dumps, or model-internal reasoning in progress labels.

Profile the existing preview separately from agent actions. Change its refresh cadence only with measured contention/overhead evidence and preserve visible responsiveness. Smooth visuals are an implementation goal; no performance improvement from polling changes is claimed yet.

## Implementation order and release gates

The detailed [implementation plan](superpowers/plans/2026-10-07-browser-runtime-rework.md) defines file ownership, interfaces, regression cases, and execution gates.

1. Extend the lab's fixtures and timing breakdown before changing the runtime.
2. Introduce internal observation/action contracts with legacy output compatibility.
3. Improve page observations and deterministic long-page reading on both backends.
4. Add guarded sequences and truthful partial/uncertain receipts.
5. Add evidence retention, progress detection, and bounded recovery.
6. Improve discovery and the progressive browser MD guide without another model call.
7. Add explicit navigation/history/dialog and approved file-transfer workflows with capability checks.
8. Connect honest progress to the desktop browser panel and measure preview overhead.
9. Run staged, counterbalanced evaluations; enable improvements only when their gates pass.

Acceptance requires per-tier capability parity, zero duplicate fixture submissions, correct partial/uncertain handling, no focus escape/stranding, and no credential or cancellation regressions. Speed claims require a same-model paired experiment with end-to-end wall time and model/tool overhead recorded separately. A token-only win is insufficient. Provider errors must remain visible and be reported separately rather than dropped to make results look better.

Roll back an individual experimental mechanism when it regresses those gates. Keep focus/history optimizations opt-in until their existing broader parity gates pass. Do not publish or change the desktop release version as part of research.

## Implementation evidence — 2026-10-07

- B1 partial-batch reporting: reproduced with live Chromium. One form submission completed before a stale second target. Before, `isToolFailure=false` and mutation verdict was unknown. After, `isToolFailure=true`, verdict is false, and the server still counts exactly one write. Regression: `test/tools/browser-contracts.test.mjs`.
- Structured detailed adapter results now distinguish failed-before-dispatch, uncertain dispatch, partial work and successful execution. They share the existing adapter execution path and preserve screenshot receipts. `BROWSER_RUNTIME_V2` defaults off. DOM metadata/capability parity and guarded aggregate sequences are still in progress.
- Current focused browser verification: 63/63 passed across contracts, verification, form preflight, lifecycle, Stop and job scopes. Real Chromium was exercised; Chrome timeout/partial-form contracts used mocks. Live approved Chrome and packaged desktop remain untested in this continuation.
- Lab: 151/151 tests passed. Added eight workflow tasks, seeded adjacent paired experiments, independent server mutation counters, explicit tool/file evidence, separate variant pass@k, and agent/evaluator/cleanup timings. Saved manifests contain allowlisted configuration and no provider keys.
- Workflow baseline: 6/8 passed. Long-page search is unsupported; a fast popup workflow observes only the original tab. Both failures remain visible. Existing shop baseline was 8/8; corrupted oracle was 0/1.
- Four paired shop smoke runs passed after contract integration. They verify compatibility only. Some fixture runs overlapped tests; no runtime or model speed claim is made. Same-model serial counterbalanced evaluation, remaining workflows, desktop changes and broad rollout checks remain required.

## Audit confidence (research only)

Implementation continuation (2026-10-08): bounded page-text search and reading now
pass the eight-task local workflow suite (8/8, previously 6/8). Long-text evidence
is found at offset 28013; known popup links expose the new tab before the next
fast turn. A real same-URL reload cursor regression failed before invalidation and
passes afterward (reading suite 7/7). Native Chromium observations now include
form groups, masked field values, inert/disabled/readonly state and current
center-point hit testing. Child-frame outer occlusion remains unknown. Chrome
probes its approved MCP catalogue for the text helper, binds cursors to tabs and
text, and explicitly reports document identity unavailable. Chrome contracts
here are mocked; broad live Chrome, desktop and provider speed gates remain open.

Further implementation checks: guarded native form sequences passed one-write
and same-URL replacement fixtures; one final observation followed three primitives.
Stop after a delayed successful server write now returns `uncertain` promptly with
`retrySafe=false`. Aggregate batch receipts include every deferred primitive.
Captured comparison quotes survived actual HTTP request projection from two pages
with one model request. State tracking ignores changing refs, retains hard runtime
limits and never calls an observed change independent goal verification. Evidence
and progress switches are separately opt-in. Initial exact browser discovery and
the updated progressive MD guide passed the real scripted four-model-round,
three-tool-call form flow without an auxiliary guide/router call. Explicit native
navigation/history passed live Chromium and mocked Chrome contracts. Remaining
dialog, file, desktop and broad provider gates are recorded in the implementation
ledger and plan; these fixture results establish capability, not model speed.

Native dialog and transfer continuation: confirm/prompt handling now waits for an
explicit decision; the triggering action is uncertain and is never replayed.
Real Chromium confirms zero writes on dismissal and one on acceptance. A prompt
during a guarded sequence leaves the remaining steps untouched. Real bundled
Chrome initially lost attention because its global tab list omitted the open
prompt; page-specific probes now preserve it. The dialog/native suite passed 5/5
with one independently counted Chrome write. Prompt input is hidden in previews.

Isolated transfers require a selected/allowlisted file independently of generic
tool approval, reject changed tabs and unsafe workspace paths, and read back
selection filename/size. Completed downloads save sanitized, bounded workspace
artifacts; pending cancellation and Stop save none. Transfers passed 6/6 live
fixture/contract checks. Native browser temporary disk use before completion is
not byte-capped; the completion deadline and session cleanup are documented.
Chrome transfer capability remains explicitly unavailable pending proof of its
host-file roots and completion lifecycle. The desktop chooser authority test
passed 1/1; native picker/packaged UI verification is still pending.

Full-suite milestone (not final-current): 988 tests, 984 pass, 3 fail, 1 skip.
Two prompt-contract failures were corrected and focused checks passed. The
unchanged job-tree recursion failure passed its isolated rerun (2/2) and remains
an intermittent finding for the final full run. Desktop build passed. New lab
workflows, desktop progress/profile, and paired provider timing still remain;
no speedup or enabled rollout defaults are claimed.

Desktop progress continuation: public labels and primitive counts now show the
active phase without exposing page questions or entered prompt replies. Partial
work remains recoverable rather than a goal-success claim. Private dialog controls
bind native Chromium events and keep takeover until Hand back. A static-page test
reproduced a misleading "page changed" notice caused by an invalid reference;
the corrected notice reports the missing control and uses a quiet recovery state.
Focused progress/lifecycle/contracts checks passed 36/36, and the desktop build
passed with 369 modules.

Actual developed and packaged Electron checks used seven local HTTP/SSE model
rounds, exercised all phases, manual prompt handling with one independent write,
Stop, reduced motion, native minimize and normal quit. The minimize check found
a Windows island closability setting blocking shutdown after services drained;
quit now releases that setting. Native background visibility reduced a four-second
preview sample from 40 captures to 1. Packaged samples were visible 37, hidden
pane 1, background 1; visible capture median 42.34ms, no observed long rendering
tasks. Reports and screenshots are under the ignored disposable artifacts
`C:/Users/anime/AppData/Local/Temp/ankita-progress-desktop-Ayvbu8/`.
The preview trace measures a small local form during a scripted provider pause;
it does not establish real-model speed or heavy-page performance.

Lab transfer/navigation/dialog fixtures now bring the full deterministic suite
to 156/156. Serial paired workflow smoke has candidate 12/12, compatibility 9/12;
the three compatibility failures are explicit unsupported new workflows. All
experimental defaults stay off. The same actual archive also passed the wider
desktop verifier (eight HTTP/SSE rounds, command/worker cleanup and live stage),
and the secure sign-in verifier (native OS encryption, cold/warm login, cancel,
retry, takeover, corrupt-store preservation and no secret leaks). The shipped
Chrome bridge completed its page/snapshot round trip with empty PATH/cache.
Native file picker, packaged reconnect/scoped ownership, final full verification
and independent provider comparisons remain recorded gates.

Fresh main serial verification now passes: 1010 tests, 1009 pass, zero failures,
one POSIX permission test skipped on Windows, duration 315930.1837ms. The previous
job-tree failure did not recur. The static-page regression confirms unchanged
visible text/layout and a usable original control after five preview refreshes.
Both real backend automation runs, with compatibility and experimental receipts,
ended `BROWSER_AUTOMATION_LIVE_OK`. Fresh lab checks passed 156/156 and validated
all 24 task documents. Live-model timing and remaining packaged edge coverage
remain separate gates; provider availability probes are not performance evidence.

Download-copy continuation found three gaps with failing regressions: a growing
source wrote 77 temporary bytes past a 16-byte limit; same-size replacements were
published; real file symlinks were followed. Bounded copying and stable opened
source checks now refuse these. The growth regression wrote only 16 bytes and
published none. Focused transfer/native checks passed 10/10, including actual
Chromium transfers and bundled Chrome's unsupported-transfer contract. Desktop
build passed (369 modules). A fresh serial full run after this hardening passed
1013 tests: 1012 pass, zero failures, one POSIX permission skip on Windows,
281856.2053ms. Log: `.superpowers/sdd/2026-10-07-browser-runtime-rework/main-suite-transfers-2026-10-08.log`.

Actual packaged native-chooser verification is available in
`scripts/verify-browser-file-picker-desktop.mjs`. The Windows helper first timed
out; the next run confirmed a real native host call and disabled owner, then was
interrupted by the user's physical Escape key. Both disposable app roots closed
normally. Native selection/cancel/late-Stop coverage remains pending rather than
counting the interrupted run as a pass. No further Computer Use input was issued.

Independent lab controls now accept paired `evidence`, `guidance`, `focus`,
`history` and `progress` comparisons. Each varies only its existing control in
a common detailed runtime. The default `runtime` remains a bundled comparison;
`combined` explicitly varies all controls. Observation/sequence isolation is
still unsupported rather than inferred from the runtime label. Complete
per-variant configurations and actual agent controls are recorded without keys.
All seven control selections completed a real isolated-Chromium fixture pair
(14/14 passes); guidance was loaded once per guided arm and zero times in the
instruction-free arms. These scripted decisions are wiring checks, not speed
evidence. Paired report regression tests also retain failed/provider-limited,
incomplete, duplicated, different-budget/tier and unknown-control attempts;
successful speed samples use separate within-pair agent/end-to-end clocks.
The lab README documents commands and these limits. Live-provider evaluations
and the remaining packaged/observation/sequence gates still remain open.

Final lab full suite passed 170/170, including an actual 42-request HTTP/14-session
Chromium check for every condition's selected model and guide loading. That check
first reproduced three unnamed requests from an over-restrictive new config
allowlist; carrying public model identity fixes the routing without serializing
client credentials. Manifests now record primary provider/model and optional
tool-model identity. The combined negative control rejected 16/16 attempts, with
zero successful timing pairs. The planned five-repeat Ling/Step guidance
comparison was stopped early at the user's request: 27 completed Ling attempts
are preserved, the in-flight attempt has no inferred outcome, and Step never
started. One observed shop-03 failure is a grader defect: its prompt requires
two cart items but its checks also require an unspecified insertion order.
The grader correction now passes the same reversed-order real-Chromium
reproduction in compatibility and experimental conditions: score 0 before,
score 1 after. Lab verification is 174/174, scripted shop pairs 16/16 and
corrupted shop pairs 0/16. The 16-attempt Ling guidance diagnostic completed,
but it and the stopped sample are quarantined for shared-memory contamination
and establish no causal speed or pass-rate verdict. Shop-07's
undefined "closest alternative" preference is a separate recorded oracle risk;
remaining browser and whole-plan gates are open.

Live CLI isolation uncovered an initialization-order defect: provider preparation
cached user runtime paths before disposable configuration selection. One confirmed
fixture memory write was reversed with other facts and forget cutoff preserved.
The CLI now selects storage first and refuses cached mismatches; each attempt
owns all memory files, including prompt pins and automatic retrieval. Original
provider settings remain read-only rather than being copied into artifacts.
Manifest version 3 documents that policy. Both historical reports now preserve
their quarantine when regenerated; raw outcomes are unchanged. The actual local
HTTP/Chromium isolation round trip passed two attempts over 12 model requests
with separate profiles and unchanged simulated user data. Main full verification
passed 1014/1015 with one Windows platform skip and zero failures; lab passed
180/180. A resolved-Ling remote smoke pair passed 2/2 with no provider errors
and the normal profile unchanged. This one easy-task pair is not speed or
hard/mixed-goal parity evidence; remaining packaged coverage is still pending.
No production rollout or speed claim follows.

Foreground native-call recovery now covers an observed early-completion failure
from the Ling checkout diagnostic. The same local HTTP/browser reproduction was
RED in both receipt modes and is GREEN on actual isolated Playwright and approved
bundled Chrome MCP using disposable profiles. One counted correction requests a
native tool call; printed JSON is never executed and completed cart writes stay
at one. Quoted/fenced/malformed examples and unrelated new turns do not trigger
the foreground guard. Repeated proposals, exhausted step budget and a final
tools-free writer proposing more work produce `invalid_tool_protocol` with
unfinished work. Focus/Stop boundaries and scheduled worker behavior remain.
Focused checks passed 71/71, including four actual six-request browser sessions
and a real HTTP cancellation check. The actual desktop reducer also reproduced
an empty row when reset arrived after message-end; the corrected ordering leaves
one final answer and zero empty rows. Final main suite passed 1026/1027 with
one POSIX permission skip and zero failures; final lab passed 180/180, desktop
typecheck/build passed (369 modules, 4.46s). Packaged bubble rendering, other OSes
and remote failure incidence remain separate gates; this earns no speed claim.

**Confidence: 88/100 for the findings and proposed architecture, not for an unimplemented speedup.** Evidence credit: pinned upstream source, current local source comparison, independent lab state checks and real developed/packaged runtime traces. Deductions: 8 points for no new broad same-model provider experiment; 4 points for incomplete heavy-page, packaged scope and file-picker coverage. Guarded Chrome sequences remain explicitly unsupported without native identity proof.

## Current browser repair — 9 October 2026

The user superseded the MCP replacement design and requested repairs while
preserving both existing adapters. No adapter, tool or browser server was removed
or installed. The pinned Browser Use source above remains a reference for guarded
work and observation identity, rather than a replacement agent.

| Reproduced issue | Correction | Current evidence |
| --- | --- | --- |
| `tab:"auto"` became an invalid tab on Playwright and invalidated current Chrome refs. | Normalize automatic tab selection to the existing omitted-tab policy, recursively for batches. | Actual isolated and approved Chrome fixture edits retain the current tab and accept its observed refs. |
| A Playwright ref could follow a same-label replacement or copied `data-ankita-ref` onto a different control. Both negative cases dispatched the wrong click before correction. | Check document identity and a non-clonable per-adapter DOM symbol; remove label fallback and bind ordinary actions to the observed native element. | Both negative controls refuse the old ref with zero wrong clicks; a fresh ref completes. |
| Managed Chrome explicitly rejected scroll. | Add fixed host-owned scrolling through the approved MCP interface and an observed native UID; share the CSS-pixel default with Playwright. | Both actual backends move an overflowing fixture and return fresh refs. Chrome's test viewport is explicitly bounded so the page actually overflows. |
| Step 5 emitted `find>`, `navigate>` and `read>`, producing three unknown-action failures. | Strip a trailing token delimiter only when the result is an already registered browser action/alias. Unknown names remain unknown. | The unit reproduction fails before correction and passes after; actual `find>` read-back succeeds on both backends. |

The external pasted review overstated two current problems. `fill_form` already
works on both backends without `BROWSER_RUNTIME_V2`; the Chrome test proves one
native form fill for six fields, with no separate `type_text` or `take_snapshot`
during that call. Existing stale-ref recovery already throws rather than claiming
execution. Four scripted-agent cases, across both real backends and both receipt
modes, prove failed/zero-dispatch stale work followed by one correctly saved form
per case. Chrome guarded sequences remain unsupported; ordinary batching works.

The automatically loaded MD guide now prefers independent batched fields, treats
autocomplete selection as a separate committed-value boundary, and warns against
inventing hosts or retrying a DNS failure by changing only its path. The complete
guide fits the automatic skill budget. Compact schema descriptions preserve the
small-context browser discovery regression; simply adding more prompt text had
made that existing test fail and was corrected before acceptance.

Evidence is retained under the ignored ledger
`.superpowers/sdd/2026-10-07-browser-runtime-rework/`: original
`browser-recovery-red-2026-10-09.log` (5/12 pass),
`browser-action-token-red-2026-10-09.log` (0/1 pass), and final
`browser-recovery-acceptance-2026-10-09.log` (54/54 pass, zero failures/skips,
93,628.8146 ms). The latter includes native Chrome, native Playwright, guarded
sequence boundaries, late Stop, automatic instructions and the actual agent loop.

The four small Step 5 attempts and their independent task outcomes are recorded
in [lab findings](browser-lab-FINDINGS.md#targeted-step-5-and-current-browser-repairs--2026-10-09).
Autocomplete and checkout pass; checkout uses three batched fills. The replacement
repeat passes in 39.910 s/8 rounds/zero tool failures, compared with its preceding
62.652 s/16 rounds/three failures. One repeat is not a controlled speed study, and
the repeat did not emit a malformed suffix, so it does not independently prove
that normalization caused its lower wall time. The deterministic native tests
prove normalization itself.

Remaining gates: actual travel-site DNS/HTTP2/CAPTCHA acceptance, provider timing
attribution, broad hard/mixed-goal parity, packaged desktop/native file-picker
coverage for these changes, and replacement during the native Locator-based drag
path. Refs still change between observations by design; no stable-ref/diff feature
or universal observed-URL provenance validator was added. Experimental defaults
remain off and no overall browser-performance completion claim follows.

### Markdown page reading and overlay refs — 9 October continuation

The user clarified that page reading, Markdown element structure and hidden or
overlay-covered content are the priority. This extends the approved page-observation
work rather than introducing a replacement browser or model-owned Node runtime.
Primary research: [Playwright's current snapshot contract](https://playwright.dev/mcp/snapshots),
[ARIA hierarchy](https://playwright.dev/docs/aria-snapshots),
[actionability](https://playwright.dev/docs/actionability), and MDN's distinction
between [rendered innerText](https://developer.mozilla.org/en-US/docs/Web/API/HTMLElement/innerText)
and [DOM textContent](https://developer.mozilla.org/en-US/docs/Web/API/Node/textContent).
These support structured current refs and separating readable DOM evidence from
interaction availability; they do not establish private Codex REPL internals.

- Both adapters render control refs as Markdown lists. Playwright retains form
  groups; Chrome retains native accessibility indentation. The opaque ref grammar
  and observation/document guards are preserved, with legacy transcript parsing.
- Default `read` now returns bounded Markdown for headings, paragraphs, lists,
  links, basic tables and open shadow roots. `find` remains a literal DOM-text
  search so Markdown punctuation does not alter its query semantics.
- `filter:"all"` opts read/find into labelled hidden DOM text and closed disclosure
  content. It does not generate actionable refs or bypass an overlay, and excludes
  scripts/styles/templates/form values. Both HTML and SVG code are excluded.
- Observed controls report covered/offscreen/inert/hidden states where the backend
  proves them. Chrome enrichment resolves at most 16 UIDs per snapshot; the rest
  remain unknown, with targeted snapshots available. A provisional 160-UID probe
  made a large-page case take 25.277 s; the bounded version's same case took 5.555 s.
  These local test timings include startup and are not a provider latency A/B.
- Native `<summary>`/Chrome `DisclosureTriangle` targets now receive actual refs.
  Both live fixtures dismiss an observed overlay, see the covered flag clear,
  expand a disclosure through its fresh ref, and read its newly visible content.
- DOM source work is bounded by shared character/node/depth budgets, and omission
  flags are tested. Read evidence preserves source/chunk identity. Chrome still
  reads the main document; cross-frame limitations remain disclosed.

The first code-exclusion test was too weak because Markdown escaping changed its
underscore-bearing sentinels. A strengthened assertion then reproduced SVG code
leakage on both backends (`browser-hidden-code-exclusion-strengthened-red-2026-10-09.log`,
12/16 pass). Normalizing DOM tag names makes SVG script/style exclusions match
HTML. This is a captured defect, not a guarantee about every DOM representation.
Current terminal acceptance and whole-worktree checks are recorded below.

### Final verification of the current reader

All processes below terminated with exit code 0, after production source settled:

| Check | Exact outcome | Ignored ledger trace |
| --- | --- | --- |
| Focused native/agent/sequence/reader checks | 74/74, zero failures/skips; 86,388.8497 ms | `browser-markdown-reading-final-focused-2026-10-09.log` |
| Whole Ankita serial suite | 1090 tests; 1089 pass, zero failures, one existing POSIX permission skip on Windows; 370,769.4846 ms | `main-suite-browser-markdown-final-2026-10-09.log` |
| Whole browser lab serial suite | 183/183, zero failures/skips; 62,281.8171 ms | `lab-suite-browser-markdown-acceptance-2026-10-09.log` |
| Desktop typecheck/build | exit 0; 369 modules, Vite 6.89 s | `desktop-build-browser-markdown-final-2026-10-09.log` |

The lab's first refresh failed 2/182 because its oracle parser expected flat ref
lines. A new Markdown/group/state regression fails before the parser change;
compatibility parsing preserves legacy rows and exact labels without altering
independent outcome checks. Targeted 18/18 includes actual HTTP-provider fixtures
with four completed browser tasks, no contract failures and zero remote models.
The final 183/183 above includes that correction. Lab-owned changes are limited to
`../ankita-browser-lab/src/harness/snapshot.mjs` and its snapshot test.

Literal/whitespace review: numeric source/probe policies are named with units and
rationale; Markdown/HTML/ARIA tokens are protocol grammar, not environment
assumptions. Production has no new inline host, model, port or workspace path.
New fixture roots/ports are discovered. CRLF-aware whole-diff and owned-file
trailing-whitespace checks are clean. No release or installed-app update occurred.

**Confidence: 84/100 for this tested repair and reader scope.** Ledger: 50 base,
+20 actual backends/independent read-back, +20 current full suites, +10 build/docs
and reproduced regression evidence; −5 Chrome frame text/partial state coverage,
−4 untested replacement during Locator drag, −4 no current packaged/headful or
other-OS check, −3 no remote-model test of the Markdown extension or causal timing
A/B. Closed shadow roots, unloaded content and canvas-only text remain outside
DOM extraction. The next +5 needs current packaged Chrome and complex frame/drag
round trips; the broader nine-task rollout and speed gates remain open.

### Flight direction, skill delivery and picker recovery — 9 October 2026

The supplied desktop trace requested Mumbai → Delhi but eventually followed the
page's Delhi → Mumbai defaults. It also submitted action markup containing query
tags, searched local files for a page's Done button, and treated uncommitted airport
text as selection. The pasted conversation is diagnostic data, not authorization
to reserve a ticket or submit its passenger details; no such data entered tests.

Reproduced runtime defects and repairs:

- History protected only the latest user message, so the original itinerary could
  disappear behind a short "use browser" continuation. RED loses it at synthetic
  round 3; bounded recent-user anchors preserve it through 18 trimmed rounds.
  Three requests share a 4,096-byte prior-request bound and yield on byte pressure.
- Persistent browser discovery exposed the tool on a continuation's first round,
  but the full guide appeared only after that round used a tool. It now loads before
  the first decision for advertised tools. Disabled skills remain excluded. There
  is no additional model/skill call; automatic delivery need not show a skill card.
- Malformed action/query markup still executes nothing, but the error now explains
  canonical separate JSON fields and page snapshots rather than local file search.
- A real Step 5 Google attempt tried native select on a custom ARIA trip-type menu.
  Both adapters now validate native select before dispatch and return fresh refs
  plus click/option guidance for custom menus. Chrome reuses its existing preflight
  probe rather than adding another native round trip.
- A direct public-site probe exposed input replacement between fill preflight and
  action binding. Playwright had incorrectly marked the batch started before any
  dispatch, discarding reference-specific fresh-snapshot recovery. Accounting now
  starts in the actual dispatch callback; a zero-write replacement remains
  recoverable, while genuine partial writes retain the existing refusal to replay.

The full guide adds sequential airport commitment, requested route/date/trip checks
before submission and on results, native/custom-menu distinctions, targeted Done
lookup, results retention, and search-versus-booking accuracy. Its whole body still
fits the existing automatic instruction budget; no flight route/model/site is
hardcoded into production. Both native adapters remain available.

Current flight fixture evidence: actual Playwright and bundled Chrome MCP each
submit exactly one BOM → DEL, one-way, 2026-10-10 search. The calendar deliberately
places Done beyond 160 controls; a targeted snapshot finds it. Scripted Agent
requests assert the complete guide and original itinerary on every round with an
eight-message history cap. The oracle reads the actual server payload rather than
trusting the assistant's completion text. These are synthetic fares, not a live
airline booking or an arbitrary-model pass.

Small Kilo Step 5 attempts used the advertised keyless free-only route in disposable
profiles and retained request/guide booleans in actual outgoing requests. Fixture:
HTTP 429 after one browser call, 16,322 ms. Google Flights: HTTP 429 after 12 browser
calls, 175,164 ms. Neither is a pass. They precede the final native-menu and
pre-dispatch accounting fixes. No long queue, paid fallback, account credentials,
passenger data, reservation or payment was used. A preliminary local verifier
assertion expected a nonexistent mapped free flag and made zero model generations;
it was corrected to use the actual keyless free-only catalogue gate.

Captured RED traces are `flight-intent-skill-red-2026-10-09.log` (10/13 pass),
`flight-action-guidance-red-2026-10-09.log` (0/1),
`flight-custom-select-red-2026-10-09.log` (0/2), and
`flight-preflight-race-red-2026-10-09.log` (zero-dispatch replacement lacked fresh
recovery). The ignored ledger contains raw traces; final acceptance follows below.

Earlier Google Flights form/URL evidence after recovery repair:
`flight-google-native-final-2026-10-09/summary.json` reports `pass:true`, 20 facade
calls, 10,895 ms, current origin Mumbai and destination New Delhi, One way, and
exactly `2026-10-10` decoded from the observed results URL. The verifier never
constructs the site's opaque search payload. Final review found its visible text
still said Loading prices, so this older artifact proves form/URL commitment only,
not a complete flight-information read. It remains in the ledger; stricter evidence
below supersedes that weak pass criterion.

Earlier bounded public probes and their failures remain in the ledger. They
exposed startup/picker animation timing and the pre-dispatch accounting defect.
The final native verifier waits for specific observed UI transitions, takes fresh
refs when controls are missing, and explicitly recovers only a proven reference
failure before dispatch. No blanket production sleep, speculative ref retargeting,
or automatic replay was added. Generic readiness across every site's hydration
and asynchronous replacement remains an open limitation.

Regression follow-up: the first whole-suite refresh had 1097 tests, 1094 pass,
two failures and one existing Windows skip (`main-suite-flight-final-2026-10-09.log`,
442,086.1702 ms). These were introduced here, not pre-existing failures: first-turn
activation called schema construction unnecessarily, and verbose select description
bytes excluded the browser group from a small-window request. Activation now uses
the existing native tool-name catalogue/accepted discovery state without building
schemas; compact schema prose is restored. The unchanged schema-count and managed
desktop routing assertions then passed in 46/46 focused checks
(`flight-regression-correction-2026-10-09.log`, 22,960.0351 ms). Real native HTML
select smoke checks also pass on both adapters with independently read Business
values (`flight-native-select-valid-2026-10-09.log`).

Final terminal gates after the runtime corrections:

| Check | Result | Trace in ignored ledger |
| --- | --- | --- |
| Main serial suite | 1097 tests, 1096 pass, 0 fail, 1 existing POSIX permission skip on Windows; 421,741.7524 ms | `main-suite-flight-acceptance-2026-10-09.log` |
| Browser lab serial suite | 183/183, no failures/skips; 133,616.1715 ms | `lab-suite-flight-acceptance-2026-10-09.log` |
| Desktop TypeScript and Vite build | exit 0, 369 modules, Vite 16.51 s | `desktop-build-flight-final-2026-10-09.log` |

The final-review oracle regression reproduces the old false positive: a correct
route/date/results URL with Loading prices still passed (RED 1/3). The shared
verification-only helper now requires both rendered prices and departure/arrival
times; reversed routes, wrong dates and incomplete fares still fail (GREEN 3/3,
258.9003 ms, `flight-results-evidence-green-2026-10-09.log`). These three checks
follow the whole-suite gates without another production source change. The model
verifier also requires priced schedule evidence in a model-visible browser result,
rather than trusting a narrative or host-only read-back. Its English/currency
patterns are test-oracle scope, not universal flight-site parsing capability.

Stricter actual public Google check: `flight-google-native-priced-2026-10-09/summary.json`
and `flight-google-native-priced-console-2026-10-09.log`, terminal exit 0:
`pass:true`, 20 facade calls, 16,536 ms, Mumbai to New Delhi, One way, exact date
`2026-10-10`, `priced:true`, `scheduled:true`, `toolReadVerified:true`. A bounded
test-only wait observes actual visible fares before the native Markdown read;
the reader's returned text contains prices and schedule times, and independent
current form/URL read-back confirms the original itinerary. No purchase occurred.
This remains scripted native evidence, not a final-source Step 5 success, speed
A/B or proof of a supplier checkout/payment flow.

The running Electron paths point to this checkout and its disabled-skill list is
empty. Restart Ankita to load the changed main-process engine; the running user
app was not closed. The screenshot's No page open label beside a populated preview
is adjacent UI evidence and was not reproduced/repaired in this scoped change.

Literal/whitespace gate: bounded history policies and select/action guidance are
named/shared; no production flight host/model/route/date was introduced. Fixture
ports and disposable profiles use runtime discovery. CRLF-aware diff checking and
owned trailing-whitespace checking pass: `DIFF_CHECK=PASS`,
`OWNED_TRAILING_WHITESPACE=0`; changed reusable verifier syntax also passes.

**Confidence: 82/100.** Base 50 +20 actual both-backend fixtures/recovery/value
read-back +20 main/lab and stricter oracle checks +10 desktop build/docs;
−8 final autonomous Step 5 end-to-end blocked by provider 429,
−5 no current installed/headful/other-OS or preview-label verification,
−3 generic site hydration/replacement readiness remains unproven,
−2 supplier checkout/payment was outside this search-only verification.
Next +5 requires a final-source Step 5 Google search after the provider limit
clears and a relaunched desktop interaction check. Recent request retention is
bounded to three user messages and may yield under context pressure; it is not
permanent goal memory. The broader default-rollout and causal speed gates remain open.

## Desktop guide visibility and mixed form batches — 9 October 2026

The user runs `desktop:dev` / `desktop:start`. The supplied Google Forms trace
contains a mixed text/checkbox/radio batch, guessed tab IDs derived from refs,
and a form exceeding the per-call field limit. Passenger/contact data in earlier
transcripts was diagnostic only; this repair sends no customer form or personal
data to a provider. All submission checks below use disposable synthetic forms.

### Reproduced causes and repairs

- The actual desktop engine already delivered the entire automatic guide. A local
  HTTP model captured four requests, three after accepted discovery containing
  the whole body, with real browser field read-back and no extra skill/router
  call. The missing piece was visible evidence: no engine event or header status
  existed. The new `skills-loaded` event reports only names after prompt trimming,
  once per turn. The shipped reducer scopes it per teammate, clears it at the
  next turn/clear, and ChatPane displays `Instructions loaded: browser-use`.
  This means request inclusion, not model compliance or provider acknowledgement.
- A real mixed batch filled its first fields, then each intermediate snapshot
  invalidated the remaining refs. Both Playwright and bundled Chrome reproduced
  this. A host-only context now permits only distinct-ref, same-backend/tab
  `fill_form` and click/fill/select batches. Read-only native preflight checks all
  current targets before the first write and each next step before dispatch.
  Intermediate snapshots are deferred; original node/UID bindings survive until
  the final snapshot. Native identity still refuses a cloned replacement. No
  label fallback, ref guessing, automatic replay or rollback was added.
- Disabled later targets now stop before even the first text edit. Replacing a
  later checkbox after an earlier fill stops before that checkbox or Save, keeps
  the completed fill, and returns fresh refs. Chrome's detached-node check
  initially said `No fields changed` after a completed step. The read-only
  preflight receipt now says `This target check made no edits`, preserving the
  partial batch's earlier receipts and typed reference recovery.
- Malformed `fields` objects no longer crash batch eligibility before ordinary
  schema validation. The guide says to use actual `tabs` IDs rather than ref
  segments, split oversized forms at the advertised limit, inspect an existing
  form instead of reopening it, and execute only unfinished steps after failure.
  The complete guide remains inside its automatic instruction budget.

Duplicate refs, navigation, dynamic keyboard/drag plans and mixed tabs/backends
retain ordinary snapshots. Dynamic picker transitions require separate observed
steps. Preflight is a live bounded target observation; it does not take a full
new snapshot that would silently retarget the caller's existing refs. Standalone
`fill_form` retains its existing whole-form editability check and fresh resulting
snapshot. Runtime V2 is not required for this repair.

### Before/after evidence

Traces are in `.superpowers/sdd/2026-10-07-browser-runtime-rework/` (ignored):

| Trace | Terminal result and evidence |
| --- | --- |
| `desktop-skill-batch-red-2026-10-09.log` | 0/5; real guide present, visible receipt absent; both adapters invalidate remaining mixed-batch refs |
| `desktop-skill-batch-focused-2026-10-09.log` | 33/33; both real adapters, receipt modes on/off, existing partial/Stop/form checks |
| `desktop-batch-boundary-red-2026-10-09.log` | 4/6; Chrome stops safely but falsely claims no field changes after the first fill |
| `desktop-batch-boundary-green-2026-10-09.log` | 6/6, 31,220.9406 ms; one exact independently recorded submission per adapter/receipt variant; disabled/replaced controls produce zero extra submissions |
| `batch-validation-red-2026-10-09.log` | 0/1; malformed fields trigger `step.fields?.map is not a function` before normal validation |
| `batch-validation-skill-green-2026-10-09.log` | 20/20, 4,607.4937 ms; malformed input, readonly partial messaging, disabled/trimmed/stopped guide receipts, whole-body budgeting, real HTTP and native form checks |
| `desktop-skill-renderer-live-2026-10-09.log` | 1/2; test-only renderer path incorrectly retained URL-encoded spaces; no production change was needed |
| `desktop-skill-renderer-acceptance-2026-10-09.log` | 2/2, 7,993.0964 ms; platform-native file URL resolution; actual engine receipt renders in shipped ChatPane, clears on next turn, zero page errors |

Exact live markers: `DESKTOP_SKILL_DELIVERY_LIVE modelRequests=4 guideRequests=3
realFieldReadBack=true extraSkillCalls=0` and `DESKTOP_SKILL_RENDERER_LIVE
actualEngineReceipt=true visibleHeader=true clearsOnNextTurn=true pageErrors=0`.
Both `MIXED_BATCH_FORM_LIVE` modes and both runtime flags record `writes=1`;
blocked/replaced `BATCH_PREFLIGHT_REFUSAL_LIVE` variants record `extraWrites=0`.
These are actual native browser and HTTP round trips with scripted model choices,
not an arbitrary-model or public Google Forms success rate.

Electron's imported main-process source is cached until relaunch. Vite alone
refreshes renderer modules. Relaunch source dev after the changes; build then
relaunch `desktop:start` for its renderer. No running user desktop window was
closed or controlled. The live renderer check uses the shipped source in
headless Chromium and a test-only capture inbox bridge; native Electron IPC and
installed EXE rendering remain uncovered. No remote model retries, paid fallback,
external customer submissions, profile migration, dependency installs or source
purge occurred in this repair.

### Final gates for this repair

| Check | Terminal result | Trace in the ignored ledger |
| --- | --- | --- |
| Full main serial suite | 1109 tests, 1108 pass, zero failures, one existing POSIX executable-permission skip on Windows; 546,440.9252 ms | `main-suite-desktop-skill-batch-2026-10-09.log` |
| Final focused tests | 37/37, zero skips/failures; 56,750.8963 ms | `desktop-skill-batch-final-focused-2026-10-09.log` |
| Browser lab serial suite | 183/183, zero skips/failures; 74,445.3357 ms | `lab-suite-desktop-skill-batch-2026-10-09.log` |
| Desktop TypeScript/Vite build | exit 0, 369 modules, Vite 6.11 s | `desktop-build-skill-batch-2026-10-09.log` |

The final focused run follows a nonfunctional minimum-cardinality constant hoist
and header comment. It also extends the actual mixed-form server oracle to verify
`act fill` and native `act select`, alongside `fill_form`, checkboxes, radio and
Save, on both real backends with runtime V2 on/off. Each successful variant records
one exact payload, including the independently read note and Business selection.
The whole browser guide is 5,794 characters and passes whole-body budget checks.

Owned literal audit: batch cardinality and operation/state policies are named
and commented, the probe and scoped preflight receipt are shared, and no new
production host, port, timeout, environment path, model, route or date was added.
Protocol event/operation discriminants, structural zero-based indices and the
named header display template follow the existing wire/UI contract; tests keep
independent expected labels and synthetic values. CRLF-aware diff and owned
trailing-whitespace checks pass (`DIFF_CHECK=PASS`, `OWNED_TRAILING_WHITESPACE=0`).

**Confidence: 84/100.** Base 50 +20 actual both-backend native form/ref/value and
desktop HTTP/renderer checks +20 whole main/lab and final focused tests +10
desktop build, documented traces and literal audit; −7 no final remote-model or
customer-form run, −5 no headful native Electron IPC/installed-release/other-OS
check, −4 arbitrary dynamic dependent controls, between-check replacement timing
and causal speed improvement remain unproven. Dependent pickers or buttons that
only become usable after earlier edits need separately observed calls; a rejected
batch is never assumed atomic or automatically replayed. Next +5 requires a
relaunched native desktop and small final-source free-model form flow. This
repair does not establish every supplier/form or broader default-rollout gate.

## 2.5.1 release preparation — 9 October 2026

The requested patch version is 2.5.1 in both package and lockfile root records.
The changelog covers all pending root-repository product work; dependency records
are unchanged. Local settings, generated media, binaries, logs and evidence dumps
are excluded from the staged source.

A disposable empty Playwright cache reproduced the old CI setup failure (0/1,
`release-ci-browser-red-2026-10-09.log`). Release CI now downloads Chromium using
the lockfile's installed Playwright CLI after `npm ci`, before requiring the
serial suite. Release metadata/CI tests failed 6/7 before the setup correction
and pass 7/7 afterwards; final run 245.0609 ms in
`release-2.5.1-contract-final.log`. Sonatype's server was unavailable in this
session, so no Sonatype security check is claimed and dependency versions were
not upgraded.

The 2.5.1 TypeScript/Vite build exits 0 (369 modules, 7.08 s). The Windows unpacked
build exits 0; EXE file version is 2.5.1, product version 2.5.1.0. Archive checking
compares the full browser guide plus 22 runtime modules with current source bytes,
and confirms the renderer receipt, unpacked Chrome bridge and capture helper.
Exact markers in `release-2.5.1-content-audit.log`:

```text
PACKAGED_RELEASE_CONTENTS version=2.5.1 sourceFiles=23 byteIdentity=true rendererSkillReceipt=true nativeBridge=true captureHelper=true
STAGED_RELEASE_AUDIT files=107 artifacts=0 potentialCredentials=0 trailingWhitespace=0 literalReviewLines=4267
```

The first audit used forward-slash paths with Windows ASAR extraction and failed
to locate the guide; the archive inventory showed it present. Platform-normalized
verification paths fixed the script without changing packaging or production
source. This is archive/resource verification, not an installed, headful native
Electron run. Public workflow completion, tag identity, all release assets and
the downloaded manifest/installer SHA-512 remain publication gates to check after
pushing this prepared source; the existing browser confidence ledger still applies.
