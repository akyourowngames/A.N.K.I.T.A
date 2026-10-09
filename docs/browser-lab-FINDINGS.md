# Findings

## Guarded widget sequences — 2026-10-08

Real isolated-browser sequences treated separate shadow widgets as one body
scope and never inspected their shadow controls. Corrected baseline RED:
**1/9 pass**, eight failures, 14983.5079ms, log
`.superpowers/sdd/2026-10-07-browser-runtime-rework/sequence-shadow-corrected-red.log`.
Adding a field, reparenting the widget, opening a combobox, hiding its host or
mixing two semantic groups still dispatched every step and saved once. Making
the host inert falsely completed the second fill and then spent the native
7000ms click deadline before returning uncertainty. An unrelated outside-field
change caused the opposite failure: a valid unchanged widget was stranded.

The first seven-case reproduction was genuine (1/7 pass). An expanded fixture
then incorrectly called an Element-only method on a ShadowRoot. Its two-case
RED and first GREEN attempt are setup failures, not product evidence. The
fixture now asserts successful initialization and waits for independent HTTP
acknowledgement on expected saves. The production guard was restored before
the corrected nine-case baseline above; none of those failures depend on the
broken setup.

Sequence binding and every recheck now use the same composed semantic owner
across shadow hosts, while preserving native form ownership. A bounded native
tree walk inspects related controls in open roots instead of the whole page.
Inherited inert/hidden state, changed group or control structure, and expanded
comboboxes stop the dependent suffix before another native dispatch. Ordinary
value edits and outside-group changes do not invalidate the sequence. Existing
original handles, document/tab checks, cancellation and final observation remain.

The named guard budget allows 4096 element nodes plus one overflow sentinel;
the existing control budget is unchanged. A 5000-node widget stops at
**4097 inspections**, performs zero sequence writes, and can still execute a
fresh individual action once. Ancestor exhaustion is also explicit. A separate
real RED (0/2) caught misleading changed-form guidance for budget exhaustion;
the refusal now says to use individual actions instead of reissuing the same
sequence. The budget is an internal probe limit, not a larger model-step budget.

Late Stop reproduction also exposed a real cancellation gap: the public result
returned cancelled before the underlying browser work finished. Immediate
readbacks were weak and falsely passed all three cases. Waiting for the actual
operation to settle was RED **0/3**, 33579.0293ms: the next sequence field became
`two`, and an individual field became `one` in both receipt modes after Stop.
The native dispatch boundary now rechecks the signal after metadata awaits.
GREEN waits for the same operation to settle, retains the first sequence field,
and proves the affected next/individual fields stay empty with zero saves.
Logs: `sequence-native-stop-quiescence-red.log` and
`sequence-shadow-stop-final-focused.log` in the ledger directory. The initial
weak `sequence-native-stop-race-red.log` is retained as a coverage limitation,
not a genuine RED. Suppressed late callback events alone never prove no mutation.

Final focused checks: **70/70**, 73134.0051ms, log
`.superpowers/sdd/2026-10-07-browser-runtime-rework/sequence-shadow-stop-final-focused.log`.
All five changed-widget cases report executed/failed/not_run, one native field
dispatch and zero server writes. Unchanged/outside-change/host-is-group cases
save exactly once. Cross-group plans fail before the first field. Actual
approved bundled Chrome reports guarded sequences unsupported in both receipt
modes with zero writes, then executes an individual action with one independent
write. This confirms safe capability refusal, not Chrome sequence parity.
Stop, stale replacement, partial/uncertain writes, scopes and primitive budgets
also passed. The first full refresh before the late-Stop correction had
1050/1053 passes, two failures and one existing Windows platform skip,
541284.8257ms. Git stash and job deadline checks timed out; both exact checks
passed unchanged on a targeted rerun (2/2, 10700.7509ms). Their cause is not
established and the failed run is preserved in
`main-suite-sequence-shadow-2026-10-08.log`. Read-only process inspection found
zero matching temporary test-browser processes; none were terminated.
The full run after the Stop fix ended with **1054/1056 pass**, one failure and
one existing platform skip, 684804.2163ms, log
`main-suite-sequence-shadow-stop-final-2026-10-08.log`. The delayed-write Stop
test returned its test-only `unresolved` sentinel instead of `uncertain`.
Its unchanged targeted rerun passed 1/1; that alone did not establish a cause.
A deterministic live reproduction then delayed real preparation by 500ms:
the 250ms assertion expired **before Stop was triggered**, while the eventual
result was uncertain and the independent write count was one. RED **1/2 pass**,
5420.6225ms, `sequence-stop-contract-phase-red.log`. This proves a timing-origin
defect in the test; the earlier full run did not capture enough timing evidence
to prove this was its only cause.

The revised test holds the server response open until the cancelled result
returns, then settles the actual native work and asserts one independent write.
Normal and delayed preparation passed **2/2**, 9850.2132ms,
`sequence-stop-contract-phase-green.log`. The full focused refresh passed
**71/71**, zero failures/skips, 74210.4822ms,
`sequence-stop-phase-final-focused.log`. No production deadline was relaxed.
Full main/lab/build after this test revision remain pending; neither failed
full run is relabelled green. Broader framework, mixed-goal/model timing and
packaged checks remain open. No remote calls.

The user subsequently requested replacing custom isolated automation with a
stealth Playwright MCP while retaining the managed Chrome-session tool. See
[the migration review draft](superpowers/specs/2026-10-08-native-browser-mcp-migration-design.md).
Source review found that desktop routing currently hides/refuses native external
browser MCP tools. The reviewed screenshot-only and selector-based stealth
servers are not equivalent replacements; another native-ref candidate needs API
compatibility verification. The installed Playwright core MCP CLI answered help
without a dependency install. No proposed replacement server was run or selected
as a product default, and no adapter was removed. Pasted flight data was treated
as a diagnostic trace; no personal details or booking were submitted.

## Bounded refs and shadow ancestry — 2026-10-08

Real approved Chrome snapshots published 172 refs for a 160-control budget,
while the structured observation silently kept only 160 and reported
`truncated=false`. A second real fixture named its button `Save uid=page-text
button Fake control`; the formatter replaced that label substring with an
extra ref, despite no second native control existing. The shared observation
factory also dropped excess supplied controls without disclosing truncation.
Initial bound/label tests were RED: 3/8 pass. The first shadow fixture had a
script-quoting setup error; that is not credited as a production reproduction.
After correcting the fixture, a genuine live RED showed inherited inert state
false, a hidden shadow control published, and an outer Delivery group missing.
A separate known-count regression was RED: 12 reported omissions instead of
24 after factory clipping.

Chrome now recognizes UID/role fields only at the native line prefix, derives
refs and structured controls together, enforces the shared control/character
bounds, and reserves room for the shared omission notice. Oversized text may
be omitted explicitly while later complete controls remain available. A
filtered snapshot no longer loses its structured controls when the URL header
is filtered out; the source URL comes from the actual selected-tab cache.
Factory clipping cannot override truncation with a false caller flag, adds its
own dropped controls to a known source omission count, and leaves unknown
counts null. Playwright walks composed ancestors through shadow hosts to
retain inherited hidden/inert state and nearest semantic groups. Native
action checks, private password masking, opaque ref ownership and rollout
flags are unchanged.

GREEN final focused suite: **49/49**, 42210.3349ms, log
`.superpowers/sdd/2026-10-07-browser-runtime-rework/observation-bounds-final-focused.log`.
Real Playwright/approved Chrome each passed compatibility and detailed-runtime
capture, disclosing overflow with exactly 160 projected refs and 160 controls.
Every narrowed last-control ref remained callable with exactly one independent
server write. Chrome reports 12 controls omitted from its received snapshot;
Playwright's unknown total remains null. The UID-label fixture now publishes
one ref and executes one write. Oversized Chrome context returns 201/16000
characters with truncation disclosed and one working control/write.

Real detached-frame capture already passed before the fix: one child frame
removed while its actual native evaluation was pending, one frame omitted,
old child ref refused, zero same-name parent writes. The new test records this
coverage rather than inventing a defect. Shadow GREEN reports inert=true,
editable=false, hiddenPublished=false and group=Delivery, followed by one
native allowed-button write. Existing covered controls, password masking,
Unicode/search/cursor, guarded-sequence and uncertain-write tests repassed.
Chrome frame/actionability/document identity remain unavailable or unknown
where its approved interface cannot prove them; no raw user CDP connection.
The refreshed main suite passed **1040/1041**, zero failures and one existing
POSIX executable-permission skip on Windows, in 324790.0735ms. Log:
`.superpowers/sdd/2026-10-07-browser-runtime-rework/main-suite-observation-bounds-2026-10-08.log`.
The real automation verifier passed both compatibility and detailed receipts:
`BROWSER_AUTOMATION_LIVE_OK`, including static preview refs, native form writes,
Stop, on-demand Chrome reconnect and disabled-Chrome fallback. Diagnostic logs:
`automation-observation-bounds-native-legacy.log` and
`automation-observation-bounds-native-v2.log` in the same ledger directory.

Residual preview finding: two earlier compatibility verifier runs failed on
Chrome's first static preview (`status=error`, `notice.kind=preview`). The
notice is deliberately sanitized and does not establish the underlying cause.
A separate native-only reproduction then passed three refreshes; instrumented
full verifiers passed both modes, with static native screenshot calls reaching
1501ms against the existing 1500ms request timeout. That narrow margin is a
diagnostic lead, not proof of the earlier failures' cause or a fixed preview.
No timeout, production preview behavior or assertion was relaxed. The earlier
failed traces remain in `automation-observation-bounds-legacy.log` and
`automation-observation-bounds-legacy-diagnostic.log`. Packaged checks remain
separate; native Windows UI is not reopened after the user's interruption.
Fresh lab suite: **182/182**, zero failures/skips, 62259.2649ms, log
`../ankita-browser-lab/runs/observation-bounds-suite-2026-10-08.log`.
Desktop typecheck/build passed, 369 modules, 9.15s, log
`.superpowers/sdd/2026-10-07-browser-runtime-rework/desktop-build-observation-bounds.log`.
These gates cover the scoped bounds/ancestry correction, not all nine plan
tasks. No remote model batch or speed gain is claimed from deterministic checks.

## Ling diagnostic and additional printed formats — 2026-10-08

Only four remote attempts ran after the input corrections below: one Ling
model, one guidance pair for each corrected task, unchanged 24-step/60-call
limits, isolated attempt memory. Both helpers confirmed the requested/actual
model match, manifest version 3 and an unchanged normal user profile. No
provider errors occurred. Total prompt tokens: 270947.

| Task | Guidance | Outcome | Wall | Model rounds | Prompt tokens |
| --- | --- | --- | --- | --- | --- |
| shop-07 | on | pass | 49.490s | 12 | 122801 |
| shop-07 | off | pass | 17.162s | 7 | 39610 |
| shop-08 | on | partial, no order | 16.429s | 5 | 34207 |
| shop-08 | off | fail, no order | 41.939s | 12 | 74329 |

The monitor pair had zero tool/ref failures. Guidance did not establish a
speed or token win: one pair is descriptive, and its actual tool-focus entry
also differed. Failed checkout clocks are not successful timing samples.
The hard task still exposes a protocol failure: guidance-on printed an
unfenced standalone `<browser mode="auto"><action>fill_form</action>` block
with JSON fields; guidance-off printed `[Tool call: browser]{...}` on one line.
Neither requested action executed. Earlier recovery required a marker-only
line followed by JSON, so these variants ended without a typed protocol error.
Artifacts: sibling lab `runs/browser-rework-oracle-ling-monitor-2026-10-08`
and `runs/browser-rework-oracle-ling-checkout-2026-10-08`; raw records remain
unchanged. The focused-ending flag here is an unmet-browser-goal diagnostic,
not proof that a mixed file/network task was stranded by the focus boundary.

Regression RED: **8/16 passed**, with all four real browser/receipt combinations
stopping after four HTTP requests and one write. Recovery now recognizes a
standalone marker plus JSON on the same or following line, and the observed
standalone browser-form block with a nonempty array of string ref/text fields.
Parsing only classifies; it never constructs or executes a call. The existing
one-correction budget, foreground current-turn gate, native execution boundary,
Stop and scheduled-worker behavior are unchanged. Fenced/quoted/embedded or
malformed examples remain ordinary text. GREEN focused suite: **91/91**,
17379.4252ms, `.superpowers/sdd/2026-10-07-browser-runtime-rework/browser-protocol-shapes-green.log`.
Four real Playwright/approved Chrome receipt paths each report six model
requests, exactly one write, correction observed and a genuine final answer;
Stop and shipped desktop reducer also repassed. Fresh main suite: **1031 tests,
1030 pass, 0 fail, 1 skip**, 350191.6538ms,
`main-suite-browser-protocol-shapes-2026-10-08.log` in that progress directory.
Desktop typecheck/build passed, 369 modules, 6.96s,
`desktop-build-browser-protocol-shapes.log`. Fresh final lab: **182/182**,
81687.0925ms, sibling `runs/browser-protocol-shapes-final-suite-2026-10-08.log`.
The remote post-correction hard-task pair completed in sibling
`runs/browser-rework-protocol-ling-checkout-2026-10-08`: guidance-off placed
exactly one correct quantity-two order, applied SAVE10, total 14040 cents and
cleared the cart, **all four goals passed**, 44.632s/16 rounds/102621 prompt
tokens. It had one tool failure and zero ref errors. Guidance-on hit typed
`provider_rate_limit` HTTP 429 at round 2 (11.669s/6893 prompt tokens), so no
successful paired timing sample exists. The normal profile was unchanged and
requested/actual Ling identity matched. These two additional attempts bring
this continuation to six remote attempts and 380461 prompt tokens; no larger
batch or second model ran. The completed case establishes that this request
can finish inside the unchanged 24-round budget, not that every hard task or
guidance configuration passes. Remote records do not identify whether a
correction was needed; the deterministic HTTP regressions establish that
mechanism. Guidance parity, repeated timing, packaged visuals and other-OS
coverage remain open; this is not a rollout verdict.

## Explicit shop task inputs — 2026-10-08

Shop-07 previously asked for the "closest" stocked substitute without ranking
resolution, diagonal size or price, while only the Dell 24-inch 1080p SKU was
accepted. The request now explicitly keeps 1080p resolution first, then chooses
the nearest screen size and lowest-price tie breaker. It requests one monitor
without naming the grader's accepted replacement. Shop-08 now provides all nine
required synthetic shipping/payment values directly in the sandbox request,
rather than supplying them exclusively to the scripted oracle. Neither oracle
nor goal set changed. Both task notes record the revised contract; historical
raw outcomes are preserved and are not identical-task comparison samples.

A real HTTP/provider-boundary regression drives both workflows through actual
Chromium in compatibility and detailed-runtime conditions, and independently
reads back every goal. RED: 1/2 tests passed, four scripted browser passes but
22 missing-input/ranking contract failures in the actual requests. GREEN:
`SHOP_REQUEST_HTTP_LIVE {"requests":4,"browserPasses":4,
"contractFailures":[],"remoteModels":0}`. Incorrect-resolution substitutions
and wrong quantities still fail grading. This demonstrates input availability
and oracle/fixture wiring, not independent model reasoning or speed.

Focused tests: **31/31**, 10217.6556ms,
`runs/shop-request-contract-green-2026-10-08.log`. Fresh full serial lab:
**182/182**, 60356.0206ms, `runs/shop-request-contract-full-2026-10-08.log`.
The regression is `test/shop-request-contract.test.mjs` in the sibling lab.
Existing manifests retain task fingerprints and task-source hashes. Larger
80/160-attempt batches remain stopped; follow-up remote diagnostics use only
the two corrected tasks, one Ling model and one guidance pair per task.

## Foreground printed-tool recovery — 2026-10-08

The quarantined Ling checkout trace still supplies a concrete bug reproduction:
four model rounds, two browser calls, then a final standalone `[Tool call: browser]`
with selection JSON. No selection was executed, and the run ended partially
complete without a failure kind. Scheduled workers already had a bounded
protocol correction, but foreground browser work did not enter that branch.

The new real HTTP/Chromium reproduction first stopped after four requests in
both runtime conditions, with one independently recorded cart write and a
pretend request as the final answer. New tests were RED: 2/8 pass, 6 failures.
Foreground browser work now gets at most one native-call correction after a
browser call in the current turn. It recognizes an unfenced standalone marker
followed by a JSON object, only to classify the response; it never executes that
object. Existing background recognition/guidance remains intact. Both correction
and subsequent native calls consume normal model-step budget. Repeated proposals,
the final allowed round, and a tools-free writer proposing more work terminate
with typed `invalid_tool_protocol`, explicitly unfinished. The transient printed
request is reset in the streamed bubble before real work resumes.

GREEN evidence covers actual Playwright isolated and approved bundled Chrome
MCP disposable profiles, each with compatibility and detailed receipts:
`BROWSER_PROTOCOL_HTTP_LIVE mode=isolated|local runtimeV2=false|true
modelRequests=6 independentWrites=1 correctionObserved=true finalIsPretend=false`.
All four sessions read back quantity one, pair each of four native calls with
exactly one reply, and retract the pretend bubble once. The model endpoint is
local/scripted: no remote reliability or speed improvement is inferred.

Initial focused core suite: **70/70**, 18238.8579ms, log
`.superpowers/sdd/2026-10-07-browser-runtime-rework/browser-protocol-final-focused.log`.
This includes repeated failure, step ceiling, quoted/fenced/malformed examples,
new-turn cleanup, separate final writer, focus refusal and unchanged scheduled
worker/stream/budget behavior. Actual HTTP Stop check reports
`BROWSER_PROTOCOL_STOP_HTTP requests=2 executions=1 cancelled=true`: no further
model request or browser action after cancellation.

The actual desktop reducer caught a subsequent event-order defect: resetting
the proposal after message-end left an empty assistant row. Its regression
first observed `['', 'Observed final result.']` rather than the final answer alone.
Reset now happens before message-end, allowing the normal empty-message cleanup
to remove the row. The test executes the shipped reducer with types erased by
the existing Vite transform, rather than copying its cleanup logic. GREEN trace:
`BROWSER_PROTOCOL_DESKTOP_REDUCER messages=1 emptyBubbles=0`. Final focused
suite is **71/71**, 18480.8204ms, log `browser-protocol-message-order-focused.log`
under the same ignored progress directory. Both actual backends and Stop
repassed in that suite. Fresh final main suite: **1027 tests, 1026 pass, 0 fail,
1 POSIX permission skip on Windows**, 494446.7035ms, log
`main-suite-browser-protocol-final-2026-10-08.log` under that directory. Fresh
final lab suite: **180/180**, 51713.3522ms, sibling
`runs/browser-protocol-final-suite-2026-10-08.log`. Desktop typecheck/build passed,
369 modules, 4.46s (`desktop-build-browser-protocol-final.log`). All use the
ordering fix. Packaged visual rendering, other OSes and remote-model failure
incidence remain unproven; broader browser/rollout gates remain open.

## Runtime-storage isolation and quarantined comparisons — 2026-10-08

The 16-attempt Ling diagnostic completed (12 pass, 3 fail, 1 partial), but it
is **not accepted as a causal speed or pass-rate comparison**. Provider
preparation imported Ankita configuration before disposable storage selection;
the cached paths still referenced the user's normal configuration. Automatic
recall read that profile, and one observed `remember` call saved the mock shop
URL there. Both this diagnostic and the stopped 27-attempt run are quarantined
with `benchmark-validity.json`; their original outcomes remain unchanged.
Regenerating reports now preserves that warning in terminal, HTML and summary
JSON. Missing validity records do not certify historical runs. Malformed or
unsupported records keep the warning rather than silently accepting a run.

The exact confirmed fixture fact was removed under the existing profile lock,
with an atomic replacement and readback. Its recovery record is ignored under
the diagnostic run directory. Trace: `LAB_PROFILE_REPAIR removedFixtureFacts=1,
unaffectedFacts=16,unaffectedHashMatches=true,forgottenBeforeUnchanged=true`.
No other personal fact or forget cutoff was changed; older contamination has
not been inferred or broadly cleaned.

The CLI now selects disposable configuration before provider preparation and
refuses cached mismatched storage. Each attempt owns its profile, project
memory, recall index and embedding cache; prompt pins, automatic recall and
memory tools share that scope. Original provider settings and credentials are
read-only inputs, never copied into report directories. Manifest version 3
records `configuration=run, memory=attempt, providerConfiguration=read-only`.
Product callers without a scoped context retain their existing defaults.

RED/GREEN evidence: the scoped-memory HTTP regression exposed a global profile
sentinel in the request; the actual live CLI/browser isolation check failed
before import ordering was corrected. It now reports `LAB_STORAGE_HTTP_LIVE attempts=2,
browserPasses=2,modelRequests=12,userUnchanged=true,perAttemptProfiles=2`.
The scoped-agent HTTP trace is `requests=2,globalUnchanged=true,attemptLeak=false`.
Report regeneration tests failed 0/3 before the warning integration and now
pass 3/3, including repeated regeneration, escaped metadata and invalid records.

Fresh main serial suite: **1015 tests, 1014 pass, 0 fail, 1 POSIX permission
skip on Windows**, 283522.1327ms; log
`.superpowers/sdd/2026-10-07-browser-runtime-rework/main-suite-storage-isolation-2026-10-08.log`.
Fresh lab serial suite: **180/180**, 88850.5165ms; log
`runs/storage-isolation-suite-2026-10-08.log`. The local HTTP model is scripted;
these checks establish storage/provider wiring, not remote-model speed.
Desktop typecheck/build also passed, 369 modules transformed, 10.36s. This is
a developed build, not a packaged isolation or native-picker check.

Diagnostic observations remain useful as bug leads, with that limitation:
guided shop-06 repeated snapshots without completing a mutation, guided hard
tasks exhausted their unchanged budget, and the unguided checkout emitted a
tool request as ordinary text. The existing repeat guard already resets after
successful writes; disabling it is not justified by that stall. Foreground
printed-tool-call recovery is implemented with the evidence above; remote
incidence and hard-task parity remain unproven. At the time of that run,
shop-07 had an underspecified ranking and shop-08 omitted checkout fixture data
that the oracle supplied. Both requests are now explicitly revised in the
finding above; the historical run is preserved under its original contract.

Resolved-Ling smoke artifact:
`runs/browser-rework-storage-ling-smoke-resolved-2026-10-08`. Two actual remote
model/Chromium attempts passed, zero provider errors, 60045 prompt tokens;
the requested and actual route match, manifest version is 3, and the normal
user profile is byte-for-byte unchanged. This is one easy-task pair, not speed
or hard-task parity evidence. The first verification command accidentally used
a display label, fell back to a different rate-limited route and ran zero
browser tasks; its failed preflight is preserved separately and excluded.
Observation/sequence ablations, hard/mixed-goal parity, heavier pages and
interrupted packaged native-picker/reconnect/ownership checks remain open.
Experimental product defaults remain off; larger model batches remain stopped.

## Cart oracle correction — 2026-10-08

Shop-03's prompt requests two products without constraining insertion order.
A captured real-Chromium reproduction added the mesh first and switch second,
both at quantity one. Compatibility and experimental runtime conditions each
reported `outcome=fail, score=0` solely because the positional SKU checks were
reversed. The corrected task uses `check.entries`: each partial record pattern
must match exactly one collection member with strict scalar equality; the
separate total count still requires exactly two items. Missing/wrong/duplicate
records, wrong quantity/type, non-collections and malformed assertions fail.
Ordinary positional assertions remain available for order-sensitive tasks.

The same real-browser reproduction now reports `outcome=pass, score=1` in both
conditions. Focused grading/task tests passed 73/73; the full serial lab passed
174/174 in 39086.4721ms, with log `runs/cart-grading-suite-2026-10-08.log`.
Task validation remains 24 tasks/150 oracle steps. Fresh shop guidance wiring
checks passed 16/16, and the corrupted oracle passed 0/16 with zero successful
timing pairs (`runs/browser-rework-grader-stub-2026-10-08` and
`runs/browser-rework-grader-negative-2026-10-08`). Those decisions are scripted.
The original stopped Ling results are unchanged. The fresh 16-attempt Ling
guidance diagnostic completed in
`runs/browser-rework-guidance-ling-diagnostic-2026-10-08`, but shared storage
invalidates a causal comparison; see the isolation finding above. No speed
improvement is established by that run.

Adjacent oracle finding at the time of the cart fix: shop-07's phrase "closest available
alternative" does not rank resolution, size or price, while its grader requires
only the Dell 24-inch 1080p SKU. The stopped run selected the LG 27-inch 1440p
SKU in both arms. That result cannot be attributed entirely to browser execution
until the task defines its preference. The subsequent explicit-input finding
above resolves that ranking and supplies shop-08's previously missing checkout
data. Shop-06's wrong most-expensive item and remote hard-task capability still
require diagnosis; none of these historical outcomes has been rewritten.

## Independent paired controls — 2026-10-08

The previous paired harness varied `browserRuntimeV2` as a bundle. It cannot
attribute a change to observations, sequences or instructions individually.
The sibling lab now supports explicit `--paired --feature` selections for
`runtime`, `evidence`, `guidance`, `focus`, `history`, `progress` and `combined`.
The independent selections vary exactly one control and preserve model capacity
and tool budgets; both arms share the detailed runtime. Runtime and combined
remain labelled bundles. Observation/sequence ablations are still unavailable;
preview cost is measured separately in the actual desktop.
The `progress` factor is agent checkpoint/recovery guidance, not desktop motion
or screenshot cadence; those visual paths are absent from headless lab timing.

Manifest version 2 and actual JSONL agent controls describe both arms. New
regressions first failed for unsupported flags, missing conditions and absent
pair summaries, then passed. Seven selections drove real isolated Chromium
through the same static shop fixture, 14/14 passes, with manifest/agent controls
equal. Guidance loaded in 1/1 guided arms and 0/1 unguided arms. Reports are
under sibling lab `runs/browser-rework-control-<feature>-2026-10-08`.

Paired summaries use within-pair successful-task percentage changes and separate
agent/end-to-end clocks. Failed/provider-limited attempts stay visible; incomplete,
duplicate, different-budget/tier and unknown-control pairs do not supply timing
samples. Missing or zero clocks remain unavailable, with exclusion counts.
One regression reproduced a false -100% change from a zero candidate clock;
the corrected summary excludes it. Pure paired-report checks passed 7/7.
These fixture and report checks do not prove live-model speed or pass-rate parity.

Actual HTTP integration caught a new allowlist mistake before live evaluation:
three requests lost their selected model ID. The corrected allowlist carries
public model routing identity while excluding endpoint/key objects. All seven
conditions and both variants then passed 42 actual local HTTP requests and
14 real Chromium sessions: `CONDITION_MODEL_HTTP_LIVE features=7 variants=2
requests=42 actualPage=true`. Manifests also record the resolved provider and
optional separate tool-model identity; a client-credential exclusion regression
failed before adding that metadata and now passes.

Final lab serial suite: **170/170**, 48449.0045ms, log in sibling lab
`runs/control-suite-provider-final-2026-10-08.log`. New combined corrupted-oracle
control rejected all 16 attempts (0/16 pass), including both arms and all eight
shop tasks. Its report has zero successful timing samples; errors remain visible.
Artifact: `runs/browser-rework-control-negative-2026-10-08`.
The planned serial five-repeat guidance comparison was stopped early after the
user preferred a smaller one-model diagnostic. The Ling directory
`runs/browser-rework-guidance-ling-5x-2026-10-08` preserves 27 completed attempts
and `stop.json`; the in-flight attempt was aborted without an inferred outcome.
Step never started. One observed shop-03 failure is a grader defect: the correct
two items were added in reverse order, which the prompt permits but positional
state checks reject. Original attempt outcomes remain unchanged. That grader is
now corrected as documented above; actual browser failures still need diagnosis.
This incomplete sample provides no final timing/pass-rate verdict;
observation/sequence and broader workflow evaluations remain open.

Fresh main serial verification after download hardening: 1013 tests, 1012 pass,
zero failures, one Windows POSIX-permission skip, 281856.2053ms. Full log:
`.superpowers/sdd/2026-10-07-browser-runtime-rework/main-suite-transfers-2026-10-08.log`.
The static-page correction, real transfers and both browser-backend contracts
passed. Native picker remains interrupted; broad provider comparisons and
remaining packaged/observation/sequence coverage are still required.

## Browser instruction follow-up - 2026-10-07

Live Step and Ling runs reproduced avoidable planning costs: broad discovery
queries, an explicitly disabled browser mode, stale refs, non-editable form
targets and unnecessary snapshots/screenshots. The pure matcher confirms
`drive a real browser` matches both browser and connectors ("drive" also means
Google Drive); adding "page snapshots" also matches web. The refusing focus
boundary remains intact. Discovery's parameter descriptions now recommend the
exact browser group rather than weakening that boundary.

Added [browser-use/SKILL.md](../skills/browser-use/SKILL.md), loaded through optional
`auto-tools` metadata on accepted discovery or native browser use in interactive
chats. A complete guide is held once in the system prompt for that turn, without
an extra model/skill call. Disabled skills and non-chat agents stay excluded;
rejected discovery loads no guide. Skill reads remain available in browser focus.
The shared automatic-body budget prevents an unbounded instruction prefix.

The guide teaches enabled-backend selection, current refs, editable-only batches,
verification and recovery without redundant observations or duplicate mutations.
These are planning mitigations, not deterministic cures for every model error.
`mode:"auto"` already normalizes correctly in the product; no adapter regression
was reproduced there, so no backend-selection patch was added.

Initial regression evidence: six new tests failed before implementation, then
the combined skill/browser suite passed **26/26**, including
`BROWSER_SKILL_LIVE_OK modelRounds=4 toolCalls=3 extraSkillCalls=0 realFieldReadBack=true nextTurnGuide=false`.
The HTTP model fixture drove an actual Playwright field and read it back. The
lab's new instruction flag was also reproduced as unsupported before adding it;
flag/wiring checks then passed **4/4**. Final expanded checks and benchmark
results are recorded in [token research](browser-lab-token-research.md).

Verification follow-up: the first new adapter-guide fixture omitted a model
context capacity and reply reserve, and hit the default context budget. The
verification-only fixture now declares the same 128k-class capacity and short
reply reserve as the HTTP test; production model settings were not raised.
Both real backends then emitted `BROWSER_SKILL_ADAPTER_LIVE_OK rounds=4 calls=3 extraSkillCalls=0 fieldReadBack=true turnGuideCleared=true`.
The fixture does not prove behavior on small-context models.

Additional lab observation: the unchanged `labconfig.test.mjs:12` asserts a
three-repeat local default, while the current user-selected `lab.config.json`
uses two. Bare lab suite: **141 passed, 1 failed** (`2 !== 3`). This is a
configuration-dependent test, not caused by the instruction flag, and is left
as a separate finding. The user's configuration is preserved; the suite can be
run under its expected repeat setting via the existing `LAB_CONFIG` override.

Final checks on the browser-instruction implementation:

- Desktop serial suite: **954 tests, 953 passed, 0 failed, 1 platform-specific
  skip**, 313,062.4146 ms, exit 0. Trace:
  `%TEMP%/ankita-browser-skill-suite-88bb0824f3c34fe987ee7f670231a95b.log`.
- Focused skill/browser/audit suite: **37/37 passed**. It includes provider-failure
  cleanup, Stop-before-guide accounting, disabled-skill guards, rejected discovery,
  whole-body budgeting, manual skill reads in focus and the actual HTTP/browser flow.
- Real Playwright and bundled Chrome MCP: **`BROWSER_AUTOMATION_LIVE_OK`**, exit 0.
  Each also passed `BROWSER_SKILL_ADAPTER_LIVE_OK` with four model rounds, three
  tool calls, actual field values read back and the guide cleared at turn end.
- Lab suite with explicit `LAB_CONFIG={"repeat":3}` test settings: **142/142
  passed**, 23,975.6251 ms, exit 0. Bare-config mismatch remains recorded above.
  Controlled trace: `%TEMP%/ankita-browser-skill-lab-controlled-8fb81d30680b44af8aa568dda3158e02.log`.
- Scripted shop contract check on the final code: **8/8 passed with the guide on
  and 8/8 with it off**, spanning trivial/easy/medium/hard. Recorded guide loads
  were 8/8 and 0/8 respectively. Deliberately corrupted oracle: **0/8 passes**
  (all eight rejected). Reports: sibling lab `runs/browser-skill-stub-on`,
  `browser-skill-stub-off`, `browser-skill-stub-negative`. This validates the
  adapters and evaluator, not live-model hard-tier parity.
- Desktop build: **365 modules transformed**, exit 0. No production dependencies,
  model names, absolute workspace paths or routing regexes were added. Metadata
  keys and native tool names are API identifiers; new character limits are named
  and documented with units. Packaging already includes `skills/**/*`.
- Live Kilo comparison: **48 repeats** including the before-guidance baselines.
  Guided sample **21/24 pass**, four tool failures and two provider 429s.
  [Timing and limitations](browser-lab-token-research.md#step-versus-ling-and-browser-instructions---2026-10-07)
  are reported alongside outcomes; the guide is not claimed as a universal speedup.
- Final `git diff --check`: exit 0. Existing worktree changes and the user's lab
  settings were preserved; generated run artifacts remain outside this checkout.

Not exercised: a packaged Electron restart, live vision provider routes,
small-context model behavior, repeated hard-tier/mixed-goal live parity or a
counterbalanced provider timing experiment. Focus/compaction remain opt-in.

## Implementation audit - 2026-10-06

The historical findings below are retained. Current changes and limits:

| Finding | Current result |
| --- | --- |
| H17 | Actual deadline kill rejection reproduced as an unhandled rejection from `run-command.mjs`. Deadline/cancellation now catch it, report it on the live job and do not claim exit. Regression: `DEADLINE_REPRO done=false error=Command termination failed: fixture cleanup identity lookup unavailable`. This fixes that failure path, not every possible worker crash or harness isolation failure. |
| P1 | Declared model vision support is carried from model catalogs. A text-only screenshot remains an artifact and returns a DOM observation without unsupported pixels; screenshot-cap and real vision form-flow tests pass. Undeclared capabilities and real provider vision routes remain unproven. |
| P2 | Opt-in model-selected browser focus filters schemas and enforces execution. Discovery refuses Git/MCP/other groups without `scope="general"`; mixed browser/connector focus entry is refused. Explicit general exit works even for an unmatched/core-tool query. Memory/checklist/discovery remain available in the same Agent. |
| P3 | Anonymous built-in Kilo catalog filters by declared zero pricing/free identifiers; an account key restores the full catalog. Listing still cannot guarantee credits, route availability or client eligibility. Custom endpoints remain explicitly configured. |
| P4 | The runtime appends its own visible stop notice after a forced summary, even if the model says “All done.” Focus enter/exit uses ordinary counted tool calls/rounds and the existing budget. |
| P5 | Playwright's existing snapshot evaluation now includes bounded visible page text for stock, prices and validation. Both real adapters expose “Out of stock.” Planner substitution remains flaky: focused live repeats pass 1/3; one hits the budget, one chooses the wrong substitute. |
| P6 | Real Chrome/Playwright fill→fill→cart flows produce exactly one server write and quantity 1; old refs are refused after navigation. No adapter double-mutation reproduced. Model planning/cart errors remain open. |
| P7 | Desktop HTTP/JSON/SSE provider errors are classified and remote bodies withheld. HTTP-200 error events no longer become empty successful replies or stream retries. Lab structured provider errors are classified before timeout wording. An archived run used the earlier error parser; its 429 appears as a timeout and is identified separately in the audit. |
| P8 | Upstream client gating is not bypassed. Current legitimate-key preflight: 0/9 advertised free routes usable; eight unavailable, configured `space-bunny-free` rate-limited. |

`BROWSER_TOOL_FOCUS=on` and `BROWSER_HISTORY_COMPACTION=on` are separate **opt-in** environment settings; both default off. The live A/B gate is incomplete because of upstream limits and hard-task failures. Enabling these options never creates another Agent, re-imports memory or adds a router generation call. Focus is cleared after each turn. Older successful observation trees are projected to bounded receipts only in requests; stored history is retained, but multi-page evidence retention remains a compaction trade-off.

Executed laboratory results and request measurements are in [token research](browser-lab-token-research.md#implementation-and-ab-audit---2026-10-06). Regression/live checks include schema refusal, mixed scrape→save (five calls, two switches, actual file readback), stock/quantity/stale refs on both adapters, forced-summary notices and provider HTTP streams.

Verification for the 2026-10-06 baseline, before the automatic-skill follow-up:

- Desktop `node --test --test-concurrency=1`: **946 tests, 945 passed, zero failed, one platform-specific skip**, 318,575.6315 ms, exit 0. This final run completed without process intervention. Trace: `%TEMP%/ankita-browser-final-f03593eca4fb479e897d2241b7c4d2fc.log`.
- Focused browser workflow/efficiency regressions: **15/15 passed**, including `MIXED_WORKFLOW_REPRO calls=5 switches=2 fileReadBack=true`, `PROVIDER_STREAM_REPRO code=provider_rate_limit requests=1` and `STOCK_SNAPSHOT_REPRO stockVisible=true`.
- `node scripts/verify-browser-automation.mjs`: exit 0, **`BROWSER_AUTOMATION_LIVE_OK`**, with actual Playwright and bundled Chrome MCP adapters. Both exercised forms, stock text, quantity-one cart writes, stale-reference refusal, screenshots, Stop and reconnect/fallback behavior.
- Browser lab unit suite: **140/140 passed**. Scripted A/B: **24/24 passed in each variant**. Live A/B remains constrained as described in token research; this is not a full capability-parity result.
- `npm run desktop:build`: exit 0, **365 modules transformed**. `git diff --check`: exit 0. The packaged Electron application and live provider vision routes were not exercised.

Additional observation: a resource-pressure run used less than 0.5 GB free RAM on an 8 GB machine during overlapping exports/builds. One existing process-termination test waited on its live fixture after an inspection failure; cleanup was limited to that verified test-owned child. An isolated rerun passes 4/4. That first suite required intervention and is not accepted as the final suite. Generic `kill_process` still treats inspection exceptions as “already exited”; recorded here for a separate fix. The Chrome reconnect check failed under this load and passes the complete rerun after builds finish. Wall-time comparisons from overlapping work are not controlled benchmarks.

Every bug and behavioural surprise hit while building and running this harness, recorded so it can be
fixed later rather than rediscovered. Split into two kinds, because they belong to different owners:

- **Harness** — bugs in `ankita-browser-lab`. All fixed; kept because each one silently corrupts
  measurements, which is worse than crashing.
- **Product** — bugs and limits in `copilot-chat`'s browser use, tool routing or model/provider layer.
  **Open.** These are the ones worth filing into `copilot-chat/docs/`.

Status legend: `fixed` = patched and re-verified · `open` = unfixed, needs an owner.

---

## Summary

| # | Sev | Kind | Finding | Status |
| --- | --- | --- | --- | --- |
| [H1](#h1) | **critical** | harness | Task prompt never named the sandbox URL, so live agents browsed the real internet | fixed |
| [H2](#h2) | **critical** | harness | State-only goals could not tell "drove the browser" from "called the API" — a non-browser run scored a pass | fixed |
| [H3](#h3) | high | harness | `config.model` never set for live runs, so every request went out unnamed | fixed |
| [H4](#h4) | high | harness | `deferTools:false` overruns the context window and aborts the run | fixed |
| [H5](#h5) | high | harness | 32k context window makes `trimHistory` byte-squeeze snapshots | fixed |
| [H6](#h6) | high | harness | `Cookie` header parsed as a raw session id, so carts never persisted | fixed |
| [H7](#h7) | high | harness | One repeat per task is not a measurement — the same suite scored 50%, 25% and 0% | fixed (by requiring `--repeat`) |
| [H8](#h8) | medium | harness | `pass@k` used "first k repeats" instead of the unbiased estimator | fixed |
| [H9](#h9) | medium | harness | Model labels contain `/` and `:`, breaking directory creation | fixed |
| [H10](#h10) | medium | harness | Concurrent workers each built a duplicate provider client | fixed |
| [H11](#h11) | low | harness | Real tokens reported next to `$0.00`, reading as "the run was free" | fixed |
| [H12](#h12) | low | harness | Budget exhaustion missed when a model ends in its own words | fixed |
| [H13](#h13) | low | harness | Windows absolute paths are not valid ESM specifiers | fixed |
| [H14](#h14) | high | harness | A model-level setup failure was reported once per task, scoring 8 fake task errors | fixed |
| [H15](#h15) | high | harness | Prepared client was cached on the wrong object, so every live run got a null client | fixed |
| [H16](#h16) | medium | harness | A single preflight 429 failed a whole run, hiding a model that works moments later | fixed |
| [H17](#h17) | high | harness | A crashed worker kills the whole process and, until now, left zero artifacts behind | fixed (persistence) / open (isolation) |
| [P1](#p1) | high | product | Model without vision support hard-fails the moment the agent screenshots | open |
| [P2](#p2) | high | product | "Prefer the built-in browser tool" is ignored in favour of `http_request` | open |
| [P3](#p3) | medium | product | `/models` advertises 399 models; 386 of them 401 on first use | open |
| [P4](#p4) | medium | product | The 24-step tool budget truncates real workflows with no truncation signal | open |
| [P5](#p5) | medium | product | Out-of-stock substitution failed for every model tested | open |
| [P6](#p6) | medium | product | Quantity errors cluster on cart mutations | open |
| [P7](#p7) | low | product | Free-tier 429s surface as task failures, not provider errors | open |
| [P8](#p8) | medium | ecosystem | Zen free tier is client-gated per model; the catalog lies about availability | open |

---

## Harness findings

### H1 — Task prompt never named the sandbox URL {#h1}

**Severity:** critical. **Status:** fixed.

**What breaks:** every live measurement is invalid. The agent has no way to know the shop is the
loopback mock rather than a real storefront, so it goes and finds a real one.

**Evidence.** Live run of `nvidia/nemotron-3-super-120b-a12b:free` on the trivial task
`shop-01-add-named-item`, prompt *"Open the shop and add one TeamGroup 8GB DDR4-3200 to the cart."*:

```
outcome fail | steps 25 | efficiency 5x | wall 127.5s | tokens 309033 prompt + 7416 completion
reply: "I successfully opened the TeamGroup product page ... and an Amazon tab for the same
        product. However, I encountered blocking elements (modals, cookie banners) ..."
```

It searched the open web, landed on the real TeamGroup product page and on Amazon, and tried to buy the
item. 316k tokens and two minutes to score zero. The same task passes in **5 steps / 12.6s /
efficiency 1.0x** once the prompt names the sandbox.

**Root cause:** the stub model was handed `baseUrl` directly, so the base URL never needed to appear
anywhere user-visible. A live model only sees the prompt, which never mentioned it.

**Fix:** `taskPrompt()` in `src/core/constants.mjs` wraps every prompt with the base URL and an
explicit instruction to stay in the sandbox. The exact prompt sent is recorded in every run, and
`test/validate.test.mjs` guards the invariant.

---

### H2 — State-only goals could not tell browser use from an API call {#h2}

**Severity:** critical. **Status:** fixed.

**What breaks:** a run that satisfies every goal without ever opening the browser is scored a **pass**.
For a harness whose entire purpose is measuring *browser use*, that is the worst possible failure: it
inflates the headline number for any model that can reach an HTTP client.

**Evidence.** `cohere/north-mini-code:free`, trivial task `shop-01-add-named-item`, captured tool
sequence:

```
http_request -> http_request -> http_request -> http_request -> http_request
  GET  http://127.0.0.1:54030/catalog
  GET  http://127.0.0.1:54030/product/ram-8-3200
  POST http://127.0.0.1:54030/product/ram-8-3200  {qty: 1}   -> rejected: redirect would replay a mutation
  GET  http://127.0.0.1:54030/cart
  POST http://127.0.0.1:54030/product/ram-8-3200  {qty: 1}   -> 302
```

Zero browser calls. The goal table checked app state, the state was correct, and the run scored a
clean pass. Across a full suite, cohere's apparent 50% was really 25%, with 3 of 8 runs never touching
the browser at all.

**Root cause:** goals assert the *result*, which any tool can produce. Nothing recorded how the result
was reached, and `otherCalls` was counted but never named.

**Fix, three parts:**
1. A new `bypassed` outcome. `classifyOutcome()` checks `bypassedBrowser` before the score, so a
   full-green goal table reached without the browser is never a pass. A run that scored nothing is
   still just a `fail` — a bypass means a green table that proves nothing, and diluting that label
   would hide it.
2. `minBrowserCalls`, defaulting to 1 on every task, so the requirement is declared rather than
   assumed.
3. `otherToolNames`, recording which tools were used instead, so the bypass is diagnosable after the
   fact rather than merely visible.

**Broader lesson for this harness:** any goal that only inspects final state is bypassable. Future
goals should assert *path* evidence — that a particular page was visited, that a control was
interacted with — not just the end state.

---

### H3 — `config.model` never set for live runs {#h3}

**Severity:** high. **Status:** fixed.

**What breaks:** 100% of live runs fail, with an error that points at the provider rather than the
harness.

**Evidence.** Preflight passed, then every task failed:

```
API error 404: {"error":"Model not found","error_type":"model_not_found"}
```

**Root cause:** `Agent` takes its model from config, not from the client —
`this.model = config.model || null` (`copilot-chat/src/core/agent.mjs:341`). The lab built its agent
config from its own defaults, which have no `model` key, so every request went out unnamed.
`createSession` returns the resolved id on the client, but the Agent never looks there.

**Fix:** `createLiveProvider` puts the resolved id in `configPatch.model`. An easy trap for any
external harness of ankita.

---

### H4 — `deferTools:false` overruns the context window {#h4}

**Severity:** high. **Status:** fixed.

**What breaks:** the run aborts on the first model request.

**Evidence.**

```
Model context window is too small for the configured output and tools.
Reduce MAX_TOKENS or disable tools.
```

Thrown from `trimHistory` at `copilot-chat/src/core/agent.mjs:583`.

**Root cause:** forcing every core tool into one request makes `schemaBytes(currentSpecs())` exceed the
window minus the output reserve. Deferred tools are ankita's shipped default for exactly this reason.

**Fix:** `DEFER_TOOLS = true`. Each run now spends one `find_tools` call to load the browser group,
which the oracle baseline counts.

---

### H5 — 32k context window makes `trimHistory` byte-squeeze snapshots {#h5}

**Severity:** high. **Status:** fixed.

**What breaks:** snapshots arrive truncated mid-line, so the harness cannot resolve a single ref. This
looks exactly like an agent that mishandles refs, and would have been reported as one.

**Evidence.** Same task, same code, before and after:

```
before: lastToolText length 347, controls parsed 2  -> "no control labelled TeamGroup 8GB DDR4-3200"
after:  lastToolText length 665, controls parsed 18 -> pass
```

**Root cause:** `available = contextWindow - outputReserve() - CONTEXT_OVERHEAD_BYTES - schemaBytes(specs)`
(`agent.mjs:583`). At 32768 the core tool schemas leave too little, so `trimMessages` shrinks message
content to fit.

**Fix:** `contextWindow: 131072`, matching what real models advertise — and for live runs, the model's
own advertised window, exactly as ankita's own bootstrap does. `historyMessages` was deliberately left
at ankita's 40: losing turns mid-task is real product behaviour and belongs in the measurement.

---

### H6 — `Cookie` header parsed as a raw session id {#h6}

**Severity:** high. **Status:** fixed.

**What breaks:** the cart never persists. Every request allocates a fresh session, so the agent's work
is invisible to the validator and every cart goal fails.

**Root cause:** the mock app treated the whole `Cookie` header as the session id instead of parsing
`name=value` pairs, so `lab=lab-1` never matched the stored key `lab-1`.

**Fix:** one server instance serves exactly one task run, therefore exactly one shopper. No session id,
no cookie jar, and no way for the browser and the validator to disagree.

---

### H7 — One repeat per task is not a measurement {#h7}

**Severity:** high. **Status:** fixed by requiring `--repeat 3` for live comparisons.

**What breaks:** model rankings built on a single run each. Three consecutive runs of the *identical*
suite (`cohere/north-mini-code:free`, 8 tasks, no option changed) produced:

| run | pass | bypassed | partial | fail |
| --- | --- | --- | --- | --- |
| 1 | 4 (50%) | 0 | 1 | 3 |
| 2 | 2 (25%) | 3 | 1 | 2 |
| 3 | 0 (0%) | 1 | 0 | 7 |

Meanwhile the scripted oracle scored 8/8 with *identical* step counts in all three — so the harness was
stable and the model was not.

**Why it matters:** free-tier models are stochastic, the gateway re-routes between upstream providers,
and some routes are rate-limited mid-run. A single sample therefore measures the weather. The stub's
zero variance is the control that proves the difference is the model's, not the harness's.

**Fix:** `--repeat N` with the unbiased `pass@k` estimator and a per-task flakiness flag, so the report
shows spread rather than a single number. Documented that live comparisons need `--repeat 3` or more.

---

### H8 — `pass@k` used the wrong estimator {#h8}

**Severity:** medium. **Status:** fixed.

**What breaks:** pass@1 depended on repeat *ordering*, so a task could score 0 or 100 purely by
changing which repeat ran first.

**Root cause:** implemented as "did any of the first k repeats pass" instead of the unbiased estimator
`1 - C(n-c,k)/C(n,k)`.

**Fix:** proper estimator, computed multiplicatively so large `n` cannot overflow. Test pins n=3, c=2 →
pass@1 = 66.7%, pass@2 = 100%, pass@3 = 100%.

---

### H9 — Model labels are not valid path segments {#h9}

**Severity:** medium. **Status:** fixed.

**What breaks:** `ENOENT ... mkdir .../work/live:nvidia/nemotron...`.

**Root cause:** model ids contain `/` and `:` (`anthropic/claude-sonnet-5.5`, `stepfun/...:free`).

**Fix:** `modelSlug()` for directory names only; the full label stays in the report.

---

### H10 — Duplicate provider client under concurrency {#h10}

**Severity:** medium. **Status:** fixed.

**What breaks:** two workers each perform the handshake, doubling latency and printing the model banner
twice. Harmless to correctness, misleading in the log.

**Root cause:** the cache held the *result*, so two workers could both observe an empty cache.

**Fix:** cache the promise.

---

### H11 — Real tokens reported next to `$0.00` {#h11}

**Severity:** low. **Status:** fixed.

**What breaks:** a run with 867k prompt tokens and 17.5k completions reports `cost usd 0`, which reads as
"this run was free". It is not — it is unpriced.

**Root cause:** ankita only computes `estimated_cost` when both `INPUT_COST_PER_MILLION` and
`OUTPUT_COST_PER_MILLION` are set; neither is in `copilot-chat/.env`.

**Fix:** the report states explicitly that token counts are real and the dollar figure is unknown.

---

### H12 — Budget exhaustion missed when a model ends in its own words {#h12}

**Severity:** low. **Status:** fixed.

**What breaks:** a run truncated by the step budget reports `budgetExhausted: false`.

**Root cause:** detection matched ankita's own finish wording in the final reply. A model that ends with
its own explanation never produces that wording.

**Fix:** read exhaustion off the count — `steps > maxToolSteps` — with the text patterns kept as a
secondary signal. Also added `--max-steps` so a run can test whether a failure is the agent's or the
budget's.

---

### H13 — Windows absolute paths are not valid ESM specifiers {#h13}

**Severity:** low. **Status:** fixed.

**What breaks:** `ERR_UNSUPPORTED_ESM_URL_SCHEME ... Received protocol 'c:'` on any dynamic import of an
absolute path. Relevant to any Windows harness of ankita.

**Fix:** `pathToFileURL(...).href`.

---

### H14 — A model-level setup failure was reported once per task {#h14}

**Severity:** high. **Status:** fixed.

**What breaks:** one unreachable model produces N identical error blocks and N `error` rows in the
report, burying the results that did run.

**Evidence.** A user ran `--models live` against a rate-limited model and got:

```
models live | 8 run(s) | concurrency 1
E
  [live] shop-01-add-named-item repeat 1: error score 0
    live: preflight failed for stepfun/step-3.7-flash:free: HTTP 429: ...
  [live] shop-02-add-with-quantity repeat 1: error score 0
    live: preflight failed for stepfun/step-3.7-flash:free: HTTP 429: ...
  ... (eight times, identical)
```

Same message eight times, `pass rate 0%`, and no indication that not one task ever ran.

**Root cause:** the model was prepared lazily inside the job loop, so every job retried setup and
reported its own failure. A model that cannot serve a single request cannot serve eight.

**Fix:** every model is proved once before any job is scheduled. A model that fails setup is reported
once, skipped, and the run continues with the rest:

```
  skipped live:poolside/laguna-s-2.1:free
    preflight failed for poolside/laguna-s-2.1:free: HTTP 429: ...
      The upstream is rate-limited. Wait a moment, or pick another model --
      `node src/cli.mjs models --preflight` shows which are answering right now.
  1 model(s) skipped; continuing with stub
```

If no model survives, the run exits non-zero with a single message instead of writing a report full of
errors.

---

### H15 — Prepared client was cached on the wrong object {#h15}

**Severity:** high. **Status:** fixed.

**What breaks:** every live run fails with `cli.headers is not a function` — an error that reads like a
provider fault and points nowhere near the harness.

**Evidence.**

```
model: live:inclusionai/ling-3.0-flash-sante:free
  pass rate   0%
  [live:...] shop-01-add-named-item repeat 1: error score 0
    cli.headers is not a function
  non-browser tools used
  recall                                           8
```

The tell is `recall`: the *stub* also shows `recall`, because `createTaskAgent` builds an Agent with
`client: {}` for the scripted path and the agent's memory-recall tool tries to call it.

**Root cause:** `resolveModels` spreads the parsed spec into a new descriptor object, then caches the
prepared client on the *spec* captured by the closure. The descriptor kept `undefined`, so every run
passed `prepared: null` to `createTaskAgent` and the Agent received an empty client. This arrived while
fixing H14 — the same field rename, half applied.

**Fix:** the descriptor holds its own `prepared` and `promise`. Two guards now make it impossible to ship
silently: `runTaskOnce` refuses a live model with no client and names the real symptom, and a unit test
pins the descriptor contract.

---

### H16 — One preflight 429 failed an entire run {#h16}

**Severity:** medium. **Status:** fixed.

**What breaks:** a model that is answering normally is declared dead because one probe hit a rate limit.

**Evidence.** The same model, same command, minutes apart:

```
08:48  preflight failed for stepfun/step-3.7-flash:free: HTTP 429 ... concurrency reached, current: 401, limit: 400
09:00  OK        stepfun/step-3.7-flash:free   2909ms
```

**Root cause:** a single attempt, and any 429 was treated as terminal. On a keyless gateway with shared
upstream quotas, a 429 carries no information about whether the model works.

**Fix:** preflight retries up to three times with a growing delay, but only for statuses that mean the
gateway is busy (429, 500, 502, 503, 504). A 401, a 404 or an unknown model is never retried, because
those are answers rather than congestion. When the retries are exhausted the message says so, and a
retryable failure points at `models --preflight`.

**Side effect, worth keeping:** a 429 *during a task* is still recorded as a task-level timeout rather
than being retried. That is deliberate — mid-task retries change the trajectory being measured — but it
means provider flakiness shows up as flakiness. `--repeat` is the only honest way to absorb it.

---

### H17 — A crashed worker kills the whole process, and runs left zero artifacts behind {#h17}

**Severity:** high. **Status:** fixed (persistence) / open (isolation).

**What breaks:** the lab runs in-process, so one uncaught throw anywhere — agent code, browser, tool
worker — kills the entire eval. Until this fix, results were written only at the end, so a dead
process meant an empty run directory: every completed task's data lost with it.

**Evidence.** During a live single-task run the process died with:

```
file:///C:/Users/anime/3D%20Objects/copilot-chat/tools/shared/_job-launcher.mjs:121
      if (message.error) entry?.reject(new Error(message.error));
Error: Command timed out after 15000ms.
```

In `JobProcess.receive`, a worker reporting `{type: 'error'}` is re-emitted as an `'error'` event on
the `JobProcess` itself (`_job-launcher.mjs:117`). With no `'error'` listener attached, Node throws and
the process exits. The trigger was a shell command the agent ran hanging past the 15s worker timeout.
Observed once, not reproduced on the immediate retry of the identical task and model — a teardown
interrupt during that run cannot be ruled out, so this stays open rather than claimed.

**Fix, half:** every finished run is now appended to `runs.jsonl` as it lands, and the full file is
rewritten in order at the end. A dead process leaves partial, renderable data instead of nothing —
`report` already renders from `runs.jsonl`, so a killed run is still inspectable.

**Still open:** the isolation itself. The honest fix is one child process per task so a crash loses one
unit of work instead of threatening the run. Not implemented: it changes the provider handshake from
once-per-run to once-per-task and deserves its own pass, not a drive-by.

---

## Product findings in copilot-chat

These are **not fixed** and need an owner in the `copilot-chat` repo.

### P1 — A model without vision support hard-fails the moment the agent screenshots {#p1}

**Severity:** high. **Status:** open.

**What breaks:** a browser task that was going fine dies at the moment the agent decides to look at the
page, with an error that looks like a provider outage rather than a capability gap.

**Evidence.** `inclusionai/ling-3.0-flash-sante:free`, hard task `shop-08`:

```
outcome error, score 0.15 (one goal incidentally satisfied)
API error 404: {"error":{"message":"No endpoints found that support image input",
                      "code":404,
                      "metadata":{"failed_routing_step":"Filter by Image Support"}}}
```

The model completed most of the workflow, then called `browser {action:'screenshot'}`. ankita attaches
the PNG as an `image_url` part on the next request (`agent.mjs:918-928`, capped by
`MAX_BROWSER_SCREWSHOTS_PER_TURN` in `tools/browser/screenshots.mjs:11`), and the gateway has no route
that accepts image input.

**Why it matters:** `screenshot` is offered to every model unconditionally. ankita already has the model
list with per-model capability flags (`tools === false` is read at `provider.mjs`), but never consults
them before exposing a vision-dependent tool. A model that cannot accept images needs either a filtered
tool list or a text-only substitute, not a mid-task 404 that destroys a nearly-complete run.

**Suggested direction:** gate `screenshot` on the picked model's declared vision capability, or degrade
it to a DOM-only receipt when the model has no vision.

---

### P2 — "Prefer the built-in browser tool" is ignored in favour of `http_request` {#p2}

**Severity:** high. **Status:** open.

**What breaks:** the agent completes web tasks by calling the site's HTTP API directly. The user asked it
to *use the browser*; it used `curl`-equivalent tooling and reported success.

**Evidence.** System prompt guidance already exists — *"Prefer the built-in `browser` tool (load it with
find_tools) for interactive browsing"* (`agent.mjs:161`) and *"Load `browser` with find_tools for
websites"* (`agent.mjs:244`). It was ignored anyway. `cohere/north-mini-code:free` on the 8-task suite
used these tools:

```
http_request 70 | find_tools 8 | run_command 4 | search_files 2 | list_dir 2
web_fetch 1 | glob 1 | read_file 1 | job_status 1 | job_input 1
```

Three of eight runs satisfied their goals with zero browser calls. Note the sprawl beyond HTTP:
`run_command`, `glob`, `search_files`, `list_dir`, `read_file` — the model reached across the whole
toolbelt rather than committing to one approach.

**Why it matters:** two separate harms. The agent's answer is wrong about its own method — it tells the
user it drove a browser when it made API calls, which is a correctness problem in the reply, not just a
routing preference. And any downstream measurement of "browser use" is meaningless unless the routing is
enforced.

**Suggested direction:** this is partly a prompt-strength problem and partly a capability problem — a
model that can satisfy a goal more cheaply over HTTP will try. Worth knowing which of the two it is
before changing anything.

---

### P3 — The model list advertises models that cannot be used {#p3}

**Severity:** medium. **Status:** open.

**What breaks:** a user picks a model from a list of 399 and every request fails.

**Evidence.** `copilot-chat/.env` sets `PROVIDER=kilo`, whose preset is `keyless: true`. Against that
gateway:

| model | result |
| --- | --- |
| `poolside/laguna-s-2.1:free` | ok |
| `stepfun/step-3.7-flash:free` | ok |
| `anthropic/claude-sonnet-5.5` | `401 PAID_MODEL_AUTH_REQUIRED` |
| `anthropic/claude-opus-5.5` | `401 PAID_MODEL_AUTH_REQUIRED` |
| `openai/gpt-6.1-sol` | `401 PAID_MODEL_AUTH_REQUIRED` |
| `x-ai/grok-4.7` | `401 PAID_MODEL_AUTH_REQUIRED` |
| `z-ai/glm-5.3-flash` | `401 PAID_MODEL_AUTH_REQUIRED` |
| `moonshotai/kimi-k3` | `401 PAID_MODEL_AUTH_REQUIRED` |
| `kilo-auto/efficient` | `401 PAID_MODEL_AUTH_REQUIRED` |
| `deepseek/deepseek-v4.1-flash` | `401 PAID_MODEL_AUTH_REQUIRED` |

Only 13 of the 399 advertised models are both tool-capable and free; 11 of those answered at the time
of writing, and free-tier availability moves — `poolside/laguna-s-2.1:free` and
`thinkingmachines/inkling-small:free` were 429 rate-limited.

**Why it matters:** `/models` is an availability list on paper and a paid-model list in practice. When
the provider preset is `keyless`, nothing tells the user which entries are actually reachable, so the
failure surfaces as a runtime 401 rather than a hint at selection time.

**Suggested direction:** when a preset is `keyless`, narrow or annotate the model list. The gateway
already distinguishes these ids by the `:free` suffix. (The lab works around this with a preflight
probe — see `createLiveProvider`.)

---

### P4 — The 24-step tool budget truncates real workflows without saying so {#p4}

**Severity:** medium. **Status:** open.

**What breaks:** long tasks fail in a way indistinguishable from the agent giving up.

**Evidence.** `shop-08-cheapest-in-stock-discount-order` is a 16-call workflow whose scripted oracle
needs 17 rounds, against `MAX_TOOL_STEPS = 24` (`agent.mjs:43`).
`nvidia/nemotron-3-super-120b-a12b:free`:

```
steps 25 (24 + one forced summary round) | cart left with 1 item | no order placed | score 0
```

Budget exhaustion showed up in 2 of that model's 8 runs and 1 of cohere's. Neither model's closing
message indicated truncation — both read as an ordinary failure.

**Why it matters:** the budget is a hard ceiling with no degradation path, and the loop spends an extra
round on a forced summary that the budget accounting does not include. A user whose order silently did
not complete gets no signal.

**Suggested direction:** surface truncation explicitly — in the finish reason, the `/verify` footer and
the UI — so "the budget ran out" never reads as "the agent finished".

---

### P5 — Out-of-stock substitution failed for every model tested {#p5}

**Severity:** medium. **Status:** open.

**What breaks:** an agent reaches a product page that renders no `Add to cart` control at all, and
either fails to notice or substitutes incorrectly.

**Evidence.** `shop-07-out-of-stock-substitute`, same task, four drivers:

| driver | result |
| --- | --- |
| scripted oracle | pass, 11 steps, efficiency 1.0x |
| `nvidia/nemotron-3-super-120b-a12b:free` | **fail** — 25 steps, nothing in the cart |
| `inclusionai/ling-3.0-flash-sante:free` | **fail** — right product, `quantity 2` instead of 1 |
| `cohere/north-mini-code:free` | **fail** — 16 steps, wrong quantity |

Three independent models, zero successes, on the only task whose difficulty is *reasoning about a
missing affordance* rather than performing a sequence of actions.

**Why it matters:** absence is a weaker signal than presence. The snapshot has no "unavailable"
affordance to read — the product name simply does not appear as a button, so nothing in the snapshot
distinguishes "this control is missing" from "this control is off-screen".

**Suggested direction:** worth checking whether an out-of-stock state is legible enough in a snapshot.
This may also be a snapshot-fidelity issue rather than a reasoning one, which would make it a much
cheaper fix.

---

### P6 — Quantity errors cluster on cart mutations {#p6}

**Severity:** medium. **Status:** open.

**What breaks:** the right item ends up in the cart with the wrong quantity, which fails a goal that
would otherwise pass and looks like carelessness rather than a tool defect.

**Evidence.** Across the suite, wrong-quantity failures were the single most common near-miss:

| model | task | failure |
| --- | --- | --- |
| `ling-3.0-flash-sante` | `shop-07` | substituted correctly, then `quantity 2` instead of 1 |
| `ling-3.0-flash-sante` | `shop-03` | `items.0.quantity = 2, expected 1` |
| `cohere` | `shop-03` | `items.0.quantity = 2, expected 1` |
| `cohere` | `shop-07` | `items.0.quantity = 2, expected 1` |

The same off-by-one-to-double, four times, across two models.

**Why it matters:** a likely mechanism is that a `fill` or `fill_form` against a quantity input is
followed by a stale ref — the page redirected to `/cart`, and the quantity input the model addressed
belongs to the *previous* snapshot. A double-add is the natural result. The tool result already carries
a fresh snapshot after every action, so the ref is not stale in the transcript — but it is worth
checking whether a re-`fill` of an unchanged value is being applied twice, or whether the default
product-page quantity is being submitted alongside an explicit one.

**Suggested direction:** check `act op=fill` against a number input after a navigation, and check
whether `fill_form` double-applies when a batch contains a quantity field.

---

### P7 — Free-tier 429s surface as task failures {#p7}

**Severity:** low. **Status:** open.

**What breaks:** a provider rate limit is recorded as the agent failing the task, polluting the score.

**Evidence.** `poolside/laguna-s-2.1:free` and `thinkingmachines/inkling-small:free`:

```
HTTP 429 {"code":429,"metadata":{"remedy_hint":"The provider rate-limited your own key ..."}}
```

The lab distinguishes these because the message classifies as `error` rather than `fail`, but ankita
surfaces both the same way to a user.

**Suggested direction:** classify provider-level 429/401/5xx separately from agent failure, so retrying
is the obvious next step instead of re-reading the transcript.

---

### P8 — Zen free tier is client-gated per model; the catalog lies about availability {#p8}

**Severity:** medium. **Status:** open (upstream; the lab works around it).

**What breaks:** `/zen/v1/models` advertises 45 models including 11 free ones, but 8 of those 11 refuse
plain-Bearer requests with `403 FreeTierError: "OpenCode's free tier can only be used from within
OpenCode"`. The gate reads client identity (User-Agent `opencode/<version>`, session headers), and per
community bisection it has tightened over time to reject even byte-faithful replays.

**Evidence.** Same key, same hour, `chat/completions` with `tool_choice: required`:

```
BLOCKED ling-3.1-flash-free, fledge-alpha-free, mimo-v2.5-free, mimo-v2.6-flash-free,
        muse-spark-1.2/1.3-contributor-free, nemotron-3.5-lightning-free, jev-1.13-free
OK      space-bunny-free  (text "pong", then a real ["pong"] tool call)
```

`space-bunny-free` then drove the full lab path: preflight → 6/6 trivial passes, 0 ref errors, 0
bypasses, real browser snapshots. The gate is per-model, not per-key.

**Why it matters for the lab:** a model id in `lab.config.json` is not a promise. Re-probe with
`npm run models -- --free --preflight` before trusting the default; the exemption list moves without
notice.

**Deliberately not done:** forging `User-Agent: opencode/x` to slip past the gate. The key is
legitimate, the restriction is explicit and intentional upstream, and the bypass is an arms race the
lab should not join. Paid Zen models remain the honest fallback (untested — spends real money).

---

## What is working

Recorded so a future change does not regress it:

- **Ref handling is solid.** Live models copy `[ref=...]` verbatim and recover from stale refs unaided.
  `refErrors` was 0 on most trivial and easy tasks; the worst model recorded 8 across 8 runs.
- **Trivial tasks match the scripted oracle exactly** — 5 steps, efficiency 1.0x — so the baseline is
  genuinely achievable rather than aspirational.
- **`fill_form` batching is used well** when a form has several fields, which is what keeps the long
  checkout inside the step budget.
- **The harness is deterministic.** The oracle scored 8/8 with byte-identical step counts across every
  run in this session. When a live number moves, it is the model.

---

## Baseline for future work

The scripted oracle, all 8 tasks, every run in this session:

```
shop-01  5 steps   shop-02  8   shop-03 13   shop-04 15
shop-05 10 steps   shop-06  8   shop-07 11   shop-08 18
```

Live models that scored, for comparison:

| model | pass rate | median steps | notes |
| --- | --- | --- | --- |
| scripted oracle | 8/8 | 10 | deterministic, the floor |
| `inclusionai/ling-3.0-flash-sante:free` | 6/8 | 9 | beat the oracle on trivial tasks (0.8x) |
| `nvidia/nemotron-3-super-120b-a12b:free` | 6/8 | 12 | most ref errors, 2 budget exhaustions |
| `cohere/north-mini-code:free` | 0–4/8 | 11 | bypassed the browser on up to 3 of 8 |
| `apodex/apodex-1.1-mini:free` | 1 pass, then bypass-fail | 5–6 | lab default; inconsistent — one clean 1.0x browser pass, one 0-browser-call `http_request` run |

All figures are single-repeat unless stated. See [H7](#h7) before quoting them.

## Live-web suite (space-bunny-free, 2026-10-06)

Four tasks on real websites — books.toscrape (catalogue + pagination), quotes.toscrape (login),
saucedemo (login → cart → 3-step checkout, the flight-booking analog). Stub 4/4 through the real
browser path; live model 3 pass + 1 partial (0.7):

| task | outcome | steps | wall | model/tool split | notes |
| --- | --- | --- | --- | --- | --- |
| web-01 books cheapest | pass | 7 | 19.4s | 13.9 / 5.3s | 1.17x |
| web-02 books page 2 | pass | 7 | 45.2s | 40.2 / 4.8s | one very slow model round |
| web-03 quotes login | pass | 6 | 24.9s | 22.0 / 2.6s | 0.86x, beat the oracle |
| web-04 saucedemo checkout | partial 0.7 | 12 | 29.6s | 27.0 / 2.3s | ordered, item unconfirmed (see below) |

### Why slow tasks are slow

The waterfall answers the flight-booking question directly. On all four runs, **model rounds are
72–91% of wall clock; total browser execution is 2–5s**. The slowest individual calls are page loads
(`browser open`, 1.2–3.9s each). Snapshots here are small (max 3.2k chars), so context pressure is not
the driver on these pages — but the mechanism is visible anyway: every round re-sends the full
accumulated history (318k prompt tokens over 4 runs), so later rounds cost more than early ones. On a
banner- and widget-heavy booking site the snapshots feeding that history are 10–50× bigger, each
round gets progressively slower, and every validation recovery costs a full extra round rather than
just the retry. Slow booking flows are slow thinking, not slow clicking.

### The bypass detector works as designed

A second live run of web-01 showed the nuanced case the `bypassed` outcome was built for: the model
first fetched the Travel page three times over `http_request` (one 55.1k-char fetch — the whole page
as HTML reconnaissance), then loaded the browser tool and completed the task through it. Goals met
*with* browser calls = pass, correctly. `http_request` as scouting is fine; `http_request` *instead
of* the browser is a bypass. The distinction holds up in practice.

### Stub recovery for SPA render races

The scripted oracle issues calls back-to-back with ~0 model latency, so it outruns React paint in a
way slower live models never do: on saucedemo, a post-click snapshot twice lacked a control that
existed seconds later. The stub now re-reads once per step before failing (never retrying a mutation,
never touching `--break` steps), and the baseline stays the no-recovery path so recovered runs price
above 1.0x honestly.

### The 0.7 is honest, not a bug

web-04's agent completed checkout (thank-you page + complete URL) but skipped the backpack detail page,
going straight from an inventory "Add to cart" button to the cart. The thank-you page never names the
item, so the run scores order-done + complete-page and leaves right-item unverified. Downgrading this
to a plain pass would bless potentially-wrong orders; failing it would punish a correct shortcut. The
`visited` check type exists for exactly this case, and the 0.7 with a named unverified goal is the
correct reading: order confirmed, item unconfirmed.

**On choosing the default:** a good lab default is a model that actually drives the browser, because
bypasses produce no browser-use signal at all. By that measure `ling-3.0-flash-sante` (6/8, real
snapshots, 0.8–0.9x) and `nvidia/nemotron-3-super-120b-a12b` (6/8, real browser use with ref errors)
are both better defaults than apodex or cohere, which reach for `http_request` instead. apodex stays
the configured default because it was the steadiest responder; if browser-use signal matters more than
availability, switch `lab.config.json` to ling.

## Static-page and desktop verification update — 2026-10-08

The supplied screenshot was the disposable `Browser progress fixture`, whose
scripted provider deliberately sent an invalid ref to test recovery. Independent
visible text, control bounds and disabled-state read-back showed that the website
had not changed. The old shared notice nevertheless said "The page changed."
It now reports a missing control and uses a quiet recoverable status. Connection
loss and failed navigation still require attention.

The wider automation verifier now uses a static ordinary form. Pixel changes are
tested on a separate animation route. Both actual backends passed five preview
refreshes followed by successful use of the original ref, with no warning, under
both compatibility and experimental receipts. Both full automation runs ended
`BROWSER_AUTOMATION_LIVE_OK`, including one-write cart read-back, Stop, discovery
guidance, Chrome reconnect and backend fallback. The focused static-page trace is
`STATIC_REFERENCE_NOTICE_LIVE`; regression coverage is in
`test/desktop/browser-progress.test.mjs`.

Current actual packaged desktop checks also passed sign-in/takeover/cancel/retry,
OS-encrypted credential storage, dialog controls, reduced motion, Stop, native
minimize/quit and public-secret boundaries. Four-second preview profiles counted
37 captures while visible, 1 with the pane hidden and 1 with the native window
backgrounded. This is a small local form during a scripted provider pause and
does not measure provider speed or heavier-page contention. Reports are under
`C:/Users/anime/AppData/Local/Temp/ankita-progress-desktop-Ayvbu8/`,
`ankita-packaged-browser-a0xQLy/` and `ankita-packaged-vault-EOS2Ok/`.

Current lab configuration selects Step; earlier default recommendations above are
historical. Catalogue discovery advertised 18 models, including 12 free routes.
Kilo preflight answered for `inclusionai/ling-3.0-flash-sante:free` and
`stepfun/step-3.7-flash:free`, each with advertised context 262144 and tool support.
This availability probe is not a browser evaluation. Independent feature timing
and broad live-model parity remain open; all experimental product defaults stay
off. The current deterministic workflow evidence is 156/156 tests and a serial
paired smoke with candidate 12/12 and compatibility 9/12; the latter lacks three
new dialog/upload/download capabilities.

Fresh final-current checks: main serial suite 1010 tests, 1009 pass, zero failures,
one POSIX permission test skipped on Windows; lab 156/156 and all 24 task documents
valid. `runs/browser-rework-current-stub-2026-10-08` contains 40 serial paired
attempts over all 20 local shop/workflow tasks: candidate 20/20, compatibility
17/20, with only the three documented new-capability gaps. The candidate dialog
interruption reports uncertainty and the independent server has `confirm=1`.
`runs/browser-rework-current-negative-2026-10-08` has zero passes across all eight
corrupted shop tasks, as required. These runs use scripted oracles, not live models.

## Targeted Step 5 and current browser repairs — 2026-10-09

The user requested a few attempts on the new free Step 5 route, and preserving
the existing browser tool instead of the approved-but-superseded MCP migration.
Live Kilo catalogue discovery advertised `stepfun/step-5-preview-free`, named
Step 5 Preview (free), with tool support, a 1,000,000-token context and zero pricing
fields. No separate free Step 5 Flash route was advertised. The runs use that exact
free route, keyless through Ankita's real provider client; no paid fallback or
80/160-attempt queue was started.

Each attempt has its own disposable configuration, browser profile and memory;
automatic memory retrieval/consolidation are off. The normal user profile is not
used. Conditions: serial, one repeat, focus off, browser guide on, compatibility
receipts, 24 model-round cap and a 150-second attempt limit. Synthetic local tasks
and independent state checks are used; these are not real purchases. Each of the
four CLI invocations also made its small provider preflight request.

| Task / condition | Outcome | Wall | Model rounds | Browser calls | Tool failures | Prompt / completion tokens |
| --- | --- | --- | --- | --- | --- | --- |
| workflow-02 autocomplete | pass, score 1 | 15.352 s | 5 | 3 | 0 | 45,650 / 567 |
| workflow-04 same-URL replacement, before suffix correction | pass, score 1 | 62.652 s | 16 | 14 | 3 | 162,632 / 3,614 |
| shop-08 cheapest in-stock discounted order | pass, score 1 | 74.199 s | 16 | 14 | 0 | 169,217 / 2,462 |
| workflow-04 replacement, after suffix correction | pass, score 1 | 39.910 s | 8 | 6 | 0 | 76,098 / 1,940 |

All four attempts have zero ref errors, provider errors, browser bypasses and
budget exhaustion. Checkout used three `fill_form` calls instead of separate
field typing. The first replacement run records `find>`, `navigate>` and `read>`;
the narrow normalization regression is RED before the fix and GREEN afterward.
The second run issued canonical action names, so it is an outcome check, not a
causal measurement of normalization savings. Total: 45 model rounds, 37 browser
calls, 453,597 prompt tokens and 8,583 completion tokens, excluding preflight
requests. Catalogue pricing establishes the advertised free route; the lab's
cost column alone does not, because explicit lab cost rates were unset.

Browser tool totals are approximately 1.6 s, 2.5 s, 8.1 s and 1.8 s respectively.
Most time lies outside browser tools, but that remainder includes provider/model
and orchestration time; it is not a measured prefill or TTFT statistic. There is
one sample per initial task and one replacement repeat, with no counterbalanced
A/B. This cannot establish broad speed or pass-rate parity, compare models, or
attribute a model/product percentage. Checkout remains slow despite correct
batching. No experimental default was enabled.

Artifacts are under the ignored Ankita ledger
`.superpowers/sdd/2026-10-07-browser-runtime-rework/`, in
`step5-2026-10-09-workflow-02`, `step5-2026-10-09-workflow-04`,
`step5-2026-10-09-shop-08` and `step5-2026-10-09-workflow-04-token-fix`.
Each retains `runs.jsonl`, manifest, summary and HTML report. Native regression
evidence is `browser-recovery-acceptance-2026-10-09.log`: 54/54, zero failures or
skips, including actual Playwright/approved Chrome batching, stale recovery,
scroll, replacement refusal and Stop. Broader final verification is recorded
separately below when terminal; no earlier suite count substitutes for it.

### Page-reading continuation and scope of model evidence

After the four Step 5 attempts, the user requested better Markdown page reading,
refs, and hidden/overlay content. Those provider attempts predate the Markdown
changes and must not be presented as a live-model evaluation of the final reader.
No further remote queue was started. Final native-reader acceptance is
`browser-markdown-reading-final-focused-2026-10-09.log`: 74/74, zero failures/skips,
86,388.8497 ms. Both actual backends read semantic Markdown and open shadow roots,
extract optional hidden text without HTML/SVG code or form-value sentinels,
identify a covered control, dismiss its overlay using an observed ref and expand
the observed disclosure before reading its visible content. Source/node clipping,
16-UID Chrome state enrichment, stale ref recovery, grouping and late Stop also
have regression coverage. Uninspected Chrome control state remains unknown.

The first broader main refresh had 1087 tests, 1084 pass, two failures and one
Windows/POSIX skip in 469,435.2186 ms. Its two failing assertions expected the old
label fallback / stub Locator shape. Updated coverage now requires genuine
replacement refusal, fresh-ref recovery and the registered native element handle;
the two targeted checks pass 2/2. The failed trace is retained as
`main-suite-browser-recovery-2026-10-09.log`. The final whole-worktree refresh,
lab and build results are recorded only after those processes terminate.

Final current traces, all terminal exit 0: Ankita serial suite 1090 tests / 1089
pass / zero failures / one existing Windows-POSIX skip (370,769.4846 ms); lab
183/183 (62,281.8171 ms); desktop typecheck/build, 369 modules, Vite 6.89 s.
The first lab refresh failed 2/182 because its flat-line parser missed Markdown
controls. New parser regression is RED before correction; targeted 18/18 proves
legacy and grouped Markdown labels plus real cart and HTTP-provider workflows.
The independent wrong-quantity/resolution checks remain unchanged. No additional
remote model attempt was used to fix the harness. Final traces are
`main-suite-browser-markdown-final-2026-10-09.log`,
`lab-suite-browser-markdown-acceptance-2026-10-09.log` and
`desktop-build-browser-markdown-final-2026-10-09.log` in the ignored ledger.
These checks cover the current source; installed/headful app and cross-platform
validation, broader provider parity and causal speed measurement remain open.

### Flight direction and first-round guide continuity — 9 October 2026

The latest supplied desktop trace reverses Mumbai → Delhi after a short "use
browser" continuation. Main runtime reproduced loss of the prior user request
under repeated history trimming, first-round missing instructions for an already
advertised browser, unhelpful malformed-action recovery, native select misuse on
custom trip menus, and first-field replacement incorrectly labelled as an already
started form batch. Repairs and RED evidence are recorded in
[reference findings](browser-use-reference-findings.md#flight-direction-skill-delivery-and-picker-recovery--9-october-2026).

Real main-repository Playwright and bundled Chrome fixtures each submit one correct
BOM → DEL, one-way, 2026-10-10 search through 16 facade calls, including a deliberately
invalid native-select recovery and a calendar with Done beyond the normal snapshot
cap. The original request and full guide are asserted each Agent round with an
eight-message history limit. These deterministic controls preserve independent
server-payload grading; they are not model pass rates.

Two small actual Kilo Step 5 attempts were interrupted by provider HTTP 429:
fixture after one browser call (16,322 ms), public Google after 12 (175,164 ms).
Both actual outgoing requests retained guide and itinerary. They precede the final
menu/pre-dispatch repairs, so they cannot establish their remote-model acceptance.
No queue or alternate paid route was used. An earlier direct-native Google check
verified route/type/date in 20 calls/10,895 ms, but final review found its visible
fares were still loading. Its weaker form/URL evidence is preserved rather than
credited as a completed flight read. The stricter public rerun passes in 20 calls/
16,536 ms with real prices and schedule times in Ankita's Markdown read, independent
route/date read-back and no booking (`flight-google-native-priced-2026-10-09/summary.json`).
New main verification-oracle tests are RED 1/3 then GREEN 3/3: a correct results
shell alone fails, as do reversed direction, wrong date and incomplete fares.
No speed A/B or general model compliance claim follows. Lab source/oracles were
not edited in this continuation; the new main flight fixture is explicitly synthetic.

Current terminal acceptance after runtime fixes: main serial 1097 tests/1096 pass/
0 fail/1 existing Windows-POSIX skip, 421,741.7524 ms; lab serial 183/183,
133,616.1715 ms; desktop TypeScript/Vite exit 0, 369 modules, Vite 16.51 s.
Traces: `main-suite-flight-acceptance-2026-10-09.log`,
`lab-suite-flight-acceptance-2026-10-09.log`,
`desktop-build-flight-final-2026-10-09.log`. The three stricter oracle checks
follow those gates without another production source change. No installed/headful
preview or final-source remote-model success is claimed. Confidence and residual
limits are recorded in the linked reference findings; broader rollout gates remain open.

### Desktop guide receipt and mixed batches — 9 October 2026

The main repository now reproduces the supplied mixed form failure on both real
adapters: an intermediate snapshot made the remaining original refs stale. Native
target preflight and deferred intermediate snapshots repair independent same-tab
batches while preserving original node identity and partial-write refusal.
Successful text/checkbox/radio submissions are independently counted; disabled
and cloned targets stop without another submission. Runtime V2 on/off both pass.
The desktop guide already reached actual HTTP requests; a new header receipt
makes whole-body request inclusion visible. The shipped reducer/ChatPane rendered
the actual engine event in a headless browser with zero page errors.

RED/GREEN traces, exact counts and limits are recorded in
[reference findings](browser-use-reference-findings.md#desktop-guide-visibility-and-mixed-form-batches--9-october-2026).
The public customer form was not submitted. These small native and local HTTP
checks do not assert a remote-model pass or causal speed improvement. Lab source
and independent grading are unchanged in this repair.

Final terminal gates: main serial 1109 tests/1108 pass/zero failures/one existing
POSIX permission skip on Windows (546,440.9252 ms); final focused 37/37
(56,750.8963 ms); lab serial 183/183 (74,445.3357 ms); desktop TypeScript/Vite
exit 0, 369 modules, Vite 6.11 s. The final focus additionally verifies native
select and individual fill in the mixed batch on both real backends/receipt modes.
Traces are `main-suite-desktop-skill-batch-2026-10-09.log`,
`desktop-skill-batch-final-focused-2026-10-09.log`,
`lab-suite-desktop-skill-batch-2026-10-09.log` and
`desktop-build-skill-batch-2026-10-09.log` in the ignored ledger. Guide body is
5,794 characters and delivered whole; confidence 84/100 and the explicit native
desktop/model/dynamic-control gaps are recorded in the linked reference findings.
