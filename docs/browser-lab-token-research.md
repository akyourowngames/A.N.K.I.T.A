# Browser-agent token cost: our problem + what the ecosystem measured

## Implementation and A/B audit - 2026-10-06

The sibling `ankita-browser-lab` imports the actual Agent and browser adapters. Added `--tool-focus on|off`, per-run request/schema/history bytes, actual focus transition counts, provider error codes and aggregate diagnostics. Both variants explicitly use the same request history projection; this isolates the focus experiment from that switch. Each variant schedules eight shop tasks with three independent repeats and concurrency one. Reports remain in the lab's `runs/` folder.

| Experiment | Result |
| --- | --- |
| Scripted focus on | 24/24 pass; all tiers 100%; zero ref errors, failures, bypasses or budget exhaustion; one transition/task. |
| Scripted focus off | 24/24 pass; all tiers 100%; zero ref errors, failures, bypasses or budget exhaustion; zero transitions/task. |
| Live `space-bunny-free`, on | 19/24 pass: trivial 6/6, easy 9/9, medium 4/6, hard 0/3. Three ordinary failures, one partial checkout, one provider 429. The archived parser mislabeled that 429 as a timeout. 1,823,289 prompt tokens; 46,358 completion tokens; 7,463,483 request bytes; 2,036,502 schema bytes. |
| Live same model, off | 7/24 pass; 17 classified provider-rate-limit errors. Trivial 6/6, easy 1/9, remaining tiers unavailable. 498,212 prompt tokens are **not** comparable with the full on workload because most runs could not generate. |
| Available matched trivial tier | Both 6/6, 44 model requests each. On 237,369 prompt tokens versus off 381,745 (**37.8% lower**); request bytes 964,873 versus 1,517,350 (**36.4% lower**); schema bytes 319,140 versus 889,198 (**64.1% lower**). These are small-tier observations, not full-suite capability parity. |
| HTTP history reproduction | History projection 28,647 → 6,744 UTF-8 bytes (**76.5%**). This is the **history portion**, not the total request or a tokenizer measurement. Stored messages, tool IDs/pairing, current refs, error results and non-browser receipts remain unchanged. |
| Schema reproduction | General schemas 15,589 → focused 5,937 bytes (**61.9%**). This fixture compares deferred catalogs before focus; actual live schema totals above include all initial/discovery requests. |
| Mixed workflow | A scripted model drives real Playwright, reads the page, explicitly exits focus, writes through the actual file tool and reads back the file. Five calls, two transitions; no extra Agent, memory handoff or uncounted switch. |

Run directories: `runs/focus-on-current`, `runs/focus-off-current`, `runs/focus-stub-on-current`, `runs/focus-stub-off-current`. Legitimate-key free-route preflight after the experiment: **0/9 usable** (eight unavailable, selected route 429); no client identity spoofing or paid fallback.

The on run's median wall time is 37.1 s; the off run's 28.2 s median is dominated by failed provider calls. Even the matched-tier model-time totals (122,568 ms on, 152,818 ms off) were collected amid overlapping Windows builds and briefly overlapping provider runs. The machine reached <0.5 GB free RAM. Neither total proves a production speedup or separates prefill from generation. The waterfall shows slow opens up to 8.7 s and model rounds up to 14.9 s; provider timing does not expose actual prefill duration.

The reported “unmet goals ending focused” count is a diagnostic, not proven mode stranding. All eight shop goals are browser goals; a budget failure in focus does not establish that an unavailable file tool caused it. The separate mixed-tool regression exits cleanly; live mixed-goal stranding and switch thrashing still require an available provider. On transitions are consistently one/task; no observed thrashing. Successful pure browsing may finish focused, and the runtime clears focus for the next turn.

**Rollout decision:** browser focus and request-only history compaction default **off** until full live pass-rate parity, multi-page evidence retention and a controlled per-tier timing check pass. Opt in independently with `BROWSER_TOOL_FOCUS=on` and `BROWSER_HISTORY_COMPACTION=on`. No aggregate token-only pass criterion, cache-marker assumption, task-specific routing regex or separate router model call was added.

## Investigation of the 17-28-41 slowdown

The user reported that `runs/2026-10-06T17-28-41` is slower than `09-57-34` and `10-03-25`. Directly re-reading each original `runs.jsonl` confirms the elapsed-time regression. The comparison changes the model and repeat count, so it does not isolate the focus implementation:

| Recorded run | Model | Completed repeats / tasks | Reported wall p50 | Mean model time per task | Mean tool time per task | Mean prompt tokens per task | Mean completion tokens per task |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 09-57-34 | `apodex/apodex-1.1-mini:free` | 6 / 2 | 18.931 s | 14.168 s | 2.395 s | 60,214 | 595.5 |
| 10-03-25 | `space-bunny-free` | 6 / 2 | 17.228 s | 17.004 s | 3.088 s | 68,536 | 542.5 |
| 17-28-41 | `stepfun/step-3.7-flash:free` | 4 / 2 | 37.141 s | 39.581 s | 2.737 s | 40,001 | 927 |

All three recorded every task outcome as pass. Latest elapsed time is **1.96x / 2.16x** the earlier reported p50s. Prompt savings normalized by repeat count are **33.6% / 41.6%**, not the 55.7% reduction obtained by comparing 160,005 tokens over four repeats with 361,285 over six. Different tokenizers also limit cross-model token comparisons. Completion tokens per task increased **55.7% / 70.9%**. Larger snapshots are additional source text, not independent evidence of better capability.

The latest run spends **158,324 ms in model rounds out of 171,534 ms elapsed (92.3%)**. Mean model-round time is **5.459 s**, compared with **2.024 s / 2.218 s** earlier; browser/tool time is broadly similar. One latest round takes **21,389 ms**, followed by a **178 ms** browser action. Two first-round `find_tools` calls fail and recover on the following discovery round; their own execution takes just 7 ms / 5 ms, but failed discovery adds model work. The archived records omit discovery arguments, so their exact requested groups cannot be reconstructed. These timings include provider waiting/retries and generation; they do not identify prefill, queueing or reasoning individually.

**Decision:** the new token measurement is not accepted as a speed improvement. Preserve the opt-in defaults. Compare the same model, same tasks and equal independent repeats serially; report successful-run latency separately from upstream errors and require pass-rate parity before rollout. Original run artifacts are retained unchanged.

## Step versus Ling and browser instructions - 2026-10-07

Executed eight conditions: two models, focus on/off, before/after the browser
instruction bundle. Each condition used the same two trivial shop tasks with
three independent repeats, concurrency one, and history projection enabled in
both focus variants (**48 live repeats**). The bundle adds the general
`browser-use/SKILL.md` and clearer discovery parameter descriptions, not a
task-specific planner. The before/after comparison therefore measures that
bundle, not the Markdown body in isolation. The new `--browser-skill on|off`
control permits an isolated instruction-body comparison on the same code.

Kilo's keyless free gateway advertised and served
`inclusionai/ling-3.0-flash-sante:free`; this is the zero-priced Sante variant of
Ling 3.0 Flash, not the paid base route. Step used
`stepfun/step-3.7-flash:free`. The user's existing lab model/config was not
overwritten, and no paid fallback or client-identity bypass was used. Eligibility
and pricing must still be checked against the [current Kilo catalog](https://api.kilo.ai/api/gateway/models).

Successful-run medians below use the conventional even-sample median (mean of
the two middle values), rather than the lab report's lower-order p50. A balanced
mean gives equal weight to each task's successful repeats, so a condition with
more short-task successes does not appear artificially faster. All failures
remain counted in the pass denominator.

| Model | Instructions | Focus | Pass / runs | Provider errors | Tool failures | Successful median | Balanced successful mean | Prompt tokens / success |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Step 3.7 | Before | Off | 4/6 | 1 | 2 | 36.919 s | 36.007 s | 57,381 |
| Step 3.7 | Before | On | 5/6 | 0 | 2 | 36.962 s | 38.940 s | 37,232 |
| Ling 3.0 Sante | Before | Off | 4/6 | 1 | 4 | 17.736 s | 17.923 s | 61,139 |
| Ling 3.0 Sante | Before | On | 5/6 | 0 | 14 | 18.264 s | 21.622 s | 52,045 |
| Step 3.7 | Guided | Off | 4/6 | 1 | 0 | 35.442 s | 40.056 s | 49,581 |
| Step 3.7 | Guided | On | 5/6 | 1 | 0 | 39.859 s | 39.815 s | 37,764 |
| Ling 3.0 Sante | Guided | Off | 6/6 | 0 | 1 | 21.589 s | 21.851 s | 63,929 |
| Ling 3.0 Sante | Guided | On | 6/6 | 0 | 3 | 24.261 s | 26.988 s | 49,705 |

Run directories (each includes `runs.jsonl`, `summary.json` and `report.html`):
`latency-review-step-off`, `latency-review-step-on`, `latency-review-ling-off`,
`latency-review-ling-on`, `browser-skill-step-off`, `browser-skill-step-on`,
`browser-skill-ling-off`, `browser-skill-ling-on`, all under the sibling lab's
`runs/` directory. Totals before/after: **18/24 → 21/24 passes**, **22 → 4 tool
failures**, and **2 → 2 provider errors**. These are observed sample counts,
not a statistically established improvement or a full-tier capability gate.

The browser guide activated in 22/24 guided repeats. One Step 429 happened before
discovery; another Step repeat called `list_dir`/`read_file`, produced no browser
calls and failed the cart goal with an empty reply. That routing failure remains
open: automatic loading on discovery cannot guide a model that never discovers
the browser. The other provider error happened after the guide had loaded.
Focused guided repeats entered once each when discovery ran (Step 5/6, Ling
6/6); no switch thrashing or unmet goals ending focused was recorded. Disabled
backend requests and mixed discovery refusals did not recur in the guided sample,
but three Ling stale-ref errors and one select-option timeout did. An earlier
driver hypothesis was rejected: `mode:"auto"` is already normalized correctly.

Mean model-round time on successful runs was **4.77–5.14 s for Step vs
2.13–2.30 s for Ling** before the bundle, and **5.92–5.94 s vs 2.70–2.92 s**
after it. This supports model/provider dependence in the observed round latency;
it does not separate queueing, prefill, generation, transport retries or model
reasoning. The conditions ran serially in time blocks, not counterbalanced.
No builds or simultaneous model runs overlapped the measurements. Small samples,
free-service variability, tokenizers and successful-subset selection prevent an
exact model-side/app-side percentage. **No 50/50 attribution or universal speedup
is established.** Focus saves tokens on these guided tasks, but its successful
median is slower for both models. Keep focus and compaction opt-in/default off.

The guide is intentionally general and uses progressive disclosure: metadata
first, full instructions only on accepted browser discovery/use, retained once
for that turn within a whole-body budget. This follows [OpenAI's skills pattern](https://learn.chatgpt.com/docs/build-skills)
and the high-signal, just-in-time approach in [Anthropic's context guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
Current refs and avoiding redundant observations are adapted to Ankita's own
contract from [Playwright's snapshot guidance](https://github.com/microsoft/playwright.dev/blob/main/mcp/snapshots.mdx).
Success plus tool/model timing remains the acceptance criterion, following
[Anthropic's tool evaluation guidance](https://www.anthropic.com/engineering/writing-tools-for-agents).

Final contract controls on the same code: **8/8 scripted shop tasks pass with
instructions on and 8/8 off**, covering trivial through hard; actual prompt guide
loads are 8/8 and 0/8 respectively. The corrupted-oracle negative control records
**0/8 passes**, so the evaluator still rejects failed workflows. Reports are
`browser-skill-stub-on`, `browser-skill-stub-off` and
`browser-skill-stub-negative`. These scripted results are not live model
capability evidence. Full implementation checks, traces and the unchanged
local-config test mismatch are in [findings](browser-lab-FINDINGS.md#browser-instruction-follow-up---2026-10-07).

Why a flight-booking task is slow, what everyone else found, and what maps onto ankita.
Numbers first, vendor claims last.

---

## 1. The problem, measured in this lab

A 12-round task sends **~120k prompt tokens for ~900 completion tokens** — a ~130:1 ratio. Every
model round re-sends:

1. the system prompt + full tool schemas (fixed cost, every round), and
2. the **entire conversation history**, where each browser tool result carries a **complete fresh
   snapshot** of the page.

Cost therefore grows roughly quadratically in rounds: round N re-sends all N−1 previous snapshots.
Measured splits from live runs:

| run | wall | model rounds | browser execution |
| --- | --- | --- | --- |
| books cheapest | 19.4s | 13.9s (72%) | 5.3s |
| books page 2 | 45.2s | 40.2s (89%) | 4.8s |
| quotes login | 24.9s | 22.0s (88%) | 2.6s |
| saucedemo checkout | 29.6–44.6s | 27–42s (91%) | 2–2.3s |

Snapshots here are small (1–3k chars), yet model time still dominates. On a banner- and
widget-heavy booking site the snapshots feeding history are 10–50× bigger, each round gets
progressively slower, and every validation recovery costs a full extra model round instead of just
the retry. **Slow booking flows are slow thinking, not slow clicking.**

The lab already records everything needed to verify any fix: `snapshotChars` per call, per-round
model/tool milliseconds in the `rounds` waterfall, token counts per run, and a slowest-calls table
in both reports. Change → `npm run eval` → compare reports.

---

## 2. What the ecosystem measured

Independent numbers only; vendor self-reports are flagged as such.

### The harness itself can cost more than the browsing

- **nsosio/web-agent-bench** — the same browser CLI costs **2.7k tokens/step on a minimal API loop
  vs 35k inside Claude Code**. The harness (system prompt, tool schemas re-sent every turn) is a
  ~13× multiplier, larger than the browser work itself.
  `https://github.com/nsosio/web-agent-bench`

### Full snapshots re-sent every round are O(n) growth

- **moc-com/browser-automation-token-benchmark** — MCP embeds the full accessibility tree in every
  action response. File-based CLI snapshots (write once, reference by id) give **O(1) per-action
  cost, 37–84% less** per multi-step workflow. "Every click on a complex page silently consumes
  10,000+ tokens via MCP. The same click via CLI? Just 35."
  `https://github.com/moc-com/browser-automation-token-benchmark`

### Snapshot format efficiency: 51–79% with no capability loss

- **WebClaw vs Playwright MCP** (measured on Wikipedia, GitHub, Hacker News) — compact format is
  **51–79% smaller**: label only links/buttons (245 refs vs 789 on the same page), W3C
  accessible-name order (short display text before verbose `title`), compressed table rows,
  `interactiveOnly` mode that strips all static text.
  `https://dev.to/kuroko1t/how-accessibility-tree-formatting-affects-token-cost-in-browser-mcps-n2a`

### Screenshots are the most expensive tokens on the page

- **D2Snap paper** (arxiv 2508.04412) — 42% of raw DOMs exceed 128K context; downsampled DOM fits at
  16.5% mean utilisation and **beats the screenshot baseline by 8%**. Screenshot-only grounding
  scores 63%.
  `https://arxiv.org/html/2508.04412v1`
- **Nadir blog** — Playwright MCP burns **114k vs ~3k** for agent-browser on the identical page;
  Anthropic computer-use adds 735 tokens overhead plus 2,000–5,000 per screenshot; **unpruned
  history alone pushes a 10-step task past 150,000 tokens** — within noise of our measured 155k.
  `https://getnadir.com/blog/browser-agent-token-cost-screenshots-accessibility-tree`

### History handling is the consensus lever

- **GitHub's gh-aw token guide** — up to **62% saved** in production agentic workflows via MCP
  pruning, deterministic-tools-first (shell steps produce structured output the agent reads instead
  of agentic fetching), planner/executor model split (frontier model plans, small models execute at
  ~10–20× lower cost), bound reads on large files, and prompt caching with stable instructions first.
  `https://github.com/github/gh-aw/blob/main/.github/aw/token-optimization.md`
- **Stagehand** — hybrid accessibility-tree trimming; structured, cache-able `act`/`observe`/
  `extract` primitives. (Vendor claim: 80% more token-efficient; treat as directional.)
  `https://www.stagehand.dev/`
- **BrowserGym / AgentLab** (arxiv 2412.05467) — leaves observation formatting to the agent
  implementation (filter elements, drop attributes, text-format the AX tree); notes AX trees can
  exceed 100k tokens with raw DOM past 1M.
  `https://arxiv.org/html/2412.05467`

### Two honest caveats

- Some viral numbers don't transfer: one "129× smaller" claim compares a *focused question* against
  a full snapshot — a different task, not a free lunch.
- Nobody publishes model-vs-tool **latency** splits the way this lab's waterfall does. Token counts
  are everywhere; measured round timing is rare. That instrument is worth keeping.

---

## 3. What maps onto ankita, in order

ankita already banked the biggest single win: it drives the accessibility tree, not
screenshots-by-default (the literature agrees that's the 80–95% step down from raw HTML). What
remains is *what gets re-sent and how often*:

1. **Measure the harness tax first.** nsosio's 13× finding says the system prompt + full tool
   catalogue per round may dwarf the snapshots. ankita ships the whole core tool set into context
   (we hit this directly: `deferTools:false` overruns the window). Deferred groups + a lean
   browsing-only tool set is the cheapest large win on the table.
2. **Screenshot policy.** Unprompted screenshots at ~2–5k tokens each, on tasks the DOM already
   solves. On-demand or error-recovery-only. Nearly free, per D2Snap + Nadir.
3. **WebClaw-style format efficiency.** Label interactive nodes only, W3C name order, compress
   repetitive rows. Proven 51–79%, no stable-identity problem, no capability loss.
4. **History compaction.** Keep the latest snapshot full; replace older tool results with one-line
   receipts. Kills the quadratic term while keeping 100% of current-page information.
5. **Prompt caching.** If Kilo/Zen honor cache markers, the static prefix (system prompt, schemas,
   early history) costs ~10%. Nearly free *if* supported — verify before assuming.
6. **Snapshot diffing.** Biggest theoretical win, most machinery (ankita refs renumber every
   snapshot, so diffing needs a stable element-identity layer first). Evidence over plain
   compaction is thin — keep last.
7. **Fewer rounds.** `fill_form` batching, no redundant `read` after an action that returned a
   snapshot, the 10-step `batch` action. Each round has fixed overhead regardless of size.

One trade-off governs all of it: every compression risks dropping something the model needed, which
costs extra rounds — the very thing being cut. There is an optimum, and it is measurable with the
loop in section 1.

## Verification update — 2026-10-08

Request bytes remain an efficiency measure rather than proof of model prefill or
end-to-end speed. Both real backend automation runs passed with compatibility
and experimental receipts. Five preview captures left a static form's original
control ref usable without an error; the earlier "page changed" screenshot came
from a deliberately invalid-reference recovery test and has been corrected.
The ordinary test form no longer contains an animation clock; pixel freshness
uses a separate fixture.

A separate actual packaged preview profile measured 37 captures in four visible
seconds, versus 1 with the pane hidden and 1 with the native window backgrounded.
The pre-fix hidden-window trace had 40 captures despite native minimization. Host
window visibility now bounds background capture cadence without throttling
explicit automation evidence. Visible capture median was 42.34ms. One IPC
calibration call per condition is not a latency distribution; the scripted
provider pause and small form do not establish real-model speed or heavy-page
performance. Exact reports and uncovered paths are recorded in the reference
findings and progress ledger.

Fresh Kilo catalogue/preflight found the requested Ling free route and the Step
free route usable, with advertised 262144-token contexts and tool support. No
inference about browser success follows from that preflight. Independent serial
counterbalanced feature comparisons, mixed-goal capability parity and paired
end-to-end timing remain required before changing experimental defaults.

The paired harness now separates evidence retention, guidance, focus, history
compaction and progress controls through `--paired --feature <name>`, with a
common detailed runtime and equal budgets. `runtime` and `combined` remain
explicit bundles; observations/sequences are not yet independently controlled.
Manifest version 2 records both conditions, and each run records actual agent
configuration and guide loads. Seven real Chromium fixture pairs passed 14/14
and matched those settings; no live provider was called for this check.

Reports now calculate successful within-pair percentage changes by model,
feature and tier, separately for agent and end-to-end clocks. Failures and
provider errors stay in all-attempt results and exclusion counts. Incomplete,
duplicate, different-budget/tier and unknown-control pairs supply no timing
sample; absent or zero clocks stay unavailable. Seven regression checks cover
these rules, including a reproduced false -100% result from a zero clock. This
prevents misleading comparisons, but does not itself earn a speed claim.

The final lab suite passed 170/170, including 42 actual local HTTP requests over
14 real Chromium sessions. A reproduced config-allowlist mistake dropped model
identity from requests; the corrected path preserves it and records the primary
provider and optional tool model without client credentials. The new combined
corrupted-oracle control failed all 16 attempts as intended and supplies no
successful timing sample. Five independent paired repeats across all eight
shop tasks were scheduled serially for the current Ling and Step free routes,
with guidance as the only varying control. The user then preferred a smaller
one-model diagnostic: the run was stopped with 27 completed Ling attempts
preserved, one in-flight attempt aborted without an inferred outcome, and Step
never started. `runs/browser-rework-guidance-ling-5x-2026-10-08/stop.json` records
the reduced scope; the manifest retains the original 80 planned Ling attempts.
Shop-03 also rejects a valid reversed cart insertion order that its prompt does
not constrain. Do not rewrite the original outcomes or treat this partial sample
as pass-rate parity or a speed claim. Fix grading and browser failures first;
a one-repeat, eight-task baseline/candidate screen needs 16 complete attempts,
with further repetitions reserved for unresolved failures or noisy timings.

### Cart grading correction and reduced diagnostic

Live reversed-order shop-03 reproduction scored zero in both compatibility and
experimental runtime conditions despite the correct two quantity-one cart items.
The lab now supports validated `check.entries` assertions: each scalar record
pattern must identify exactly one member, independently of collection position.
Exact total counts still reject extras. The identical browser reproduction now
scores one in both conditions, with 73/73 focused and 174/174 full lab tests;
the full log is `runs/cart-grading-suite-2026-10-08.log` (39086.4721ms).
Updated shop wiring pairs pass 16/16 and corrupted pairs 0/16. Historical Ling
outcomes were not rescored. The 16-attempt one-model guidance diagnosis completed
under `runs/browser-rework-guidance-ling-diagnostic-2026-10-08`, but it and the
stopped run are quarantined for shared runtime-memory contamination.
No causal timing verdict is available. Shop-07's underspecified alternative ranking
is recorded in findings; its fixture/prompt/checks remain unchanged.

### Storage isolation is a prerequisite for timing comparisons

Live provider preparation previously imported normal runtime paths before the
lab chose its disposable config directory. Automatic personal recall therefore
crossed attempts, and one diagnostic wrote a mock-shop memory into the normal
profile. That exact confirmed note was repaired without changing other facts or
the forget cutoff. Historical JSONL outcomes remain intact; an explicit validity
record keeps an unsuitable-comparison warning in regenerated reports and JSON.
The raw 16 outcomes (12 pass, 3 fail, 1 partial) are bug leads, not causal evidence
for guidance, speed, reliability, or token savings.

The corrected CLI selects storage before provider preparation and guards cached
path mismatches. Profile pins, automatic recall and tools now use the same
per-attempt memory context; original provider settings remain read-only inputs.
Manifest version 3 records this policy. Two real Chromium attempts over 12 local
HTTP model requests passed with independent profiles and an unchanged simulated
user profile. The main full suite passed 1014/1015 with one POSIX permission skip
and zero failures; the lab full suite passed 180/180. Those local scripted model
checks do not measure provider latency. A resolved-Ling smoke pair also passed
2/2 with no provider errors and the normal profile unchanged, but only covers
one easy task. Larger batches remain stopped at the user's request.

### Printed proposals must not prematurely end active browser work

A captured Ling checkout reply printed a tool marker/selection JSON after two
browser calls and ended early. A local HTTP/real-browser reproduction failed
the same way in compatibility and detailed runtime conditions. Foreground work
now shares the existing one-correction budget, with stricter standalone,
unfenced JSON recognition after a browser call in the current turn. The JSON
is classified as data and never executed. The model must issue a native call;
completed writes are not replayed, and normal step/focus/Stop limits still apply.
Repeated proposals or budget exhaustion are typed unfinished failures rather
than successful replies. Ordinary replies incur no extra model request.

Four actual browser sessions (isolated Playwright/approved bundled Chrome, each
in both receipt modes) completed the scripted HTTP case with six model requests,
one cart write and observed quantity one. Focused core checks passed 71/71;
the Stop round trip made no third request or second browser action. This proves
the runtime recovery contract, not that a remote model will obey it or that
overall wall time improves. No new provider batch or rollout was started.
The shipped desktop reducer independently exposed an empty row from resetting
after message-end. The corrected order resets before normal empty-row cleanup;
the same reducer now retains only the final answer. Final main suite after that
change passed 1026/1027 with one POSIX permission skip and no failures; final
lab passed 180/180 and desktop build passed (369 modules, 4.46s). All model
endpoints for this protocol fix were local/scripted; remote failure frequency,
hard/mixed-goal parity and packaged rendering still require separate evidence.

### Small corrected-task diagnostic and format coverage

After disclosing monitor preferences and synthetic checkout inputs in the lab
requests, four isolated Ling attempts completed, using 270947 prompt tokens.
Both monitor attempts passed, but guidance-on took 49.490s/12 rounds/122801
prompt tokens versus 17.162s/7 rounds/39610 without guidance. Neither checkout
attempt placed an order. Their shorter clocks cannot count as speed wins.
Provider errors were zero and the normal profile was unchanged; a single pair
per task does not establish statistical capability parity or a model comparison.

The two checkout replies supplied new concrete protocol shapes: same-line
`[Tool call: browser]{...}` and a standalone XML-like browser fill_form block.
Recognition now includes those bounded forms without executing the printed
payload, raising the correction cap, or making another request on ordinary
answers. Actual browser regressions first failed 8/16; the focused suite now
passes 91/91 with exactly one cart write per real backend/receipt case. A fresh
checkout pair then finished: guidance-off passed all four independently graded
goals in 44.632s/16 rounds; guidance-on was interrupted by provider HTTP 429 at
round 2. The normal 24-round ceiling was sufficient for the completed case.
There is no successful paired timing sample or proof that the remote success
used the correction. Fresh main tests passed 1030 with one Windows/POSIX skip,
lab passed 182/182 and desktop build passed. Six total targeted remote attempts
used 380461 prompt tokens with the normal user profile unchanged. The original
80/160-attempt batches remain stopped; guidance parity and statistical speed
claims remain unearned.

### Step 5 small repair diagnostic — 2026-10-09

Four requested free-route attempts used `stepfun/step-5-preview-free` through
Kilo, serially with focus off and the browser guide on. All independently graded
tasks passed: autocomplete 15.352 s/5 rounds; replacement 62.652 s/16 rounds;
checkout 74.199 s/16 rounds; replacement repeat 39.910 s/8 rounds. Initial
replacement had three malformed action-name failures (`find>`, `navigate>`,
`read>`); the repeat had none after a regression-backed normalization fix, but
did not itself emit malformed names. See [the full method and artifacts](browser-lab-FINDINGS.md#targeted-step-5-and-current-browser-repairs--2026-10-09).

The four attempts used 453,597 prompt and 8,583 completion tokens, excluding small
preflights. Browser tools account for approximately 1.6–8.1 seconds per attempt;
the remaining wall time has not been separated into provider/model and product
components. This is not a model comparison or a latency A/B. The checkout's three
form batches prove the faster interaction primitive is being used, while its
74.199-second clock shows that fewer form calls alone do not guarantee fast
completion. No token-only performance claim or experimental-default change follows.
