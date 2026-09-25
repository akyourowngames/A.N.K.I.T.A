# Ankita Verification Stage — implementation plan

Status: implemented in the working tree. Automated tests pass; the live email
send check has not been run.
Scope lock: v1 covers **side-effect tools** (mutations: send/upload/create/post/edit)
plus **corrective `write_todos` errors**. Whole-loop claim scanning is v2.

Reference bugs: audit of `src/agent.mjs` tool loop, `tools/write-todos.mjs`,
`tools/_shared.mjs` (`capOutput`), `src/mcp-client.mjs` (`formatToolResult`),
`tools/composio.mjs`. The failure transcript (email "sent with PDF" that had
`attachmentList: []`, plus 5 wasted `write_todos` rounds) reproduces against
this repo's exact code paths and error strings.

---

## 1. Goal

Make it structurally hard for Ankita to claim a side effect happened without
evidence. Today the loop returns the model's final text verbatim
(`sendTurn`, `src/agent.mjs:933-943`) and grounding is prompt advice only
("Ground every claim in a tool result", `agent.mjs:200`). v1 adds:

1. A **machine-readable tool envelope** for mutations — `{ok, summary, evidence}` —
   so "sent with attachment" requires `attachmentList.length > 0`, not a vibe.
2. A **read-back rule for mutations** — after send/upload/create, one verification
   call (fetch the message, check the file) before the model may claim success.
3. **Corrective `write_todos` errors** — include the rendered list + valid IDs,
   ending the 5-round guessing loop seen in the transcript.
4. **Evidence protection in `capOutput`** — never truncate away the fields a
   verification check needs.

### Locked decisions

| Decision | Choice |
| --- | --- |
| Scope | **Side-effect tools first.** Read-only tools unchanged. Whole-loop final-answer claim scanning is v2. |
| Signal shape | **Envelope appended to existing string results**, not a new protocol. Zero breaking changes to tool `run()` signatures or history format. |
| Enforcement | **Runtime + prompt, both.** Runtime attaches verdicts the model can see; prompt gains a read-back rule. Neither alone is enough (prompt-only is today's bug). |
| Composio | **No approval-gate change in v1.** Verification applies to its results like any other mutation; the trusted-exception policy is unchanged. |
| Deps | Keep **zero runtime dependencies**. |

---

## 2. Why this shape

The audit found four distinct defects, each fixed by one plan item — no grand
rewrite:

- **Defect A — unverified final answer.** `sendTurn` returns model text the
  moment tool calls stop; `writeReply`/`finishForced` are tools-free. Fix: §5
  read-back rule + §6 verdict footer, so the evidence is in context *and* the
  model is told to use it.
- **Defect B — success-shaped failure.** MCP `isError` normalization
  (`src/mcp-client.mjs:271`) only catches explicit `isError: true`. A 200-OK
  payload with `error_count: 1` or `attachmentList: []` reads as success.
  Fix: §5 per-tool success criteria evaluated by the runtime, not the model.
- **Defect C — stringly-typed errors.** Every failure is an `"Error: ..."`
  string; the loop even computes `success` for telemetry (`agent.mjs:995`) and
  discards it. Fix: §5 reuses that signal and surfaces it to the model.
- **Defect D — punitive `write_todos` errors.** `cannot replace or reorder…`,
  `unknown todo ID: s5`, `cannot remove existing` (`tools/write-todos.mjs:50,61,71`)
  never show the valid state, costing 5 rounds in the transcript. Fix: §7.
- **Risk E — truncation hides evidence** (`tools/_shared.mjs:6-16` head+tail cut
  can remove `error_count` / empty lists from large JSON). Fix: §8.

---

## 3. File layout

```
src/
  verify.mjs                # NEW — success criteria registry + verdict builder
  agent.mjs                 # EDIT — attach verdicts, read-back prompt rule
tools/
  _shared.mjs               # EDIT — evidence-aware capOutput
  write-todos.mjs           # EDIT — corrective errors
test/
  verify.test.mjs           # NEW
  write-todos.test.mjs      # NEW (or extend; check existing coverage first)
docs/
  verification-plan.md      # THIS FILE
```

No new config keys in v1. No changes to tool `run()` signatures, history
format, `MAX_TOOL_STEPS`, repeat guard, two-model turns, or approval gates.

---

## 4. `src/verify.mjs` spec (new)

```js
export function verdictFor(toolName, args, resultText) // -> null | { ok, reason, evidence }
export function isMutation(toolName, args)             // -> boolean
export function verificationFooter(verdict)            // -> string
```

Details:

- `isMutation`: centralises what the loop today decides ad hoc. Default:
  anything `needsApproval(name, args)` OR `!isReadOnly(name, args)` counts as a
  mutation. `mcp__*` tools defer to `mcp.needsApproval(name)`. Pure readers
  (`read_file`, `search_files`, `skill`, `recall`, …) return `false` and get no
  verdict (zero added tokens on the read path).
- `verdictFor`: small registry of per-tool success criteria, evaluated against
  the result *text* (tools keep returning strings — no signature changes):
  - Gmail send via Composio/MCP: `ok` requires an attachment claim in args to
    be matched by evidence in the result (e.g. attachment filename or
    non-empty attachment list present). Missing → `{ok:false, reason:'no
    attachment evidence in tool result — fetch the sent message and check
    before claiming it was attached'}`.
  - Drive upload/create: `ok` requires a file ID / link in the result.
  - Generic fallback for any other mutation: `ok:null` (unknown — runtime does
    not assert), but the footer still carries the read-back reminder when the
    result is short enough; no verdict line when there is nothing to check.
  - Explicit `"Error…"/"Not run:"/"denied"/"cancelled"` prefixes → `{ok:false}`
    reusing the existing `traceAgent` success regex from `agent.mjs:995`
    (extract it to `verify.mjs` and import it in both places so they can't drift).
- `verificationFooter({ok:true})` → `\n[verified: <evidence snippet>]`.
  `verificationFooter({ok:false})` → `\n[UNVERIFIED: <reason>. Do not claim
  success — verify with a read-back call (fetch the message/file) or report the
  limitation.]`.
- Budget: verdict lines are short (<200 chars). They ride inside the existing
  `capOutput` budget, appended *after* truncation so they are never cut (§8).

---

## 5. `src/agent.mjs` wiring

1. **Attach verdicts in `run()`** (the single seam around `agent.mjs:979-1007`):
   after `result = await this.runToolCall(call)`, compute
   `verdictFor(call.function.name, args, result)` (args already parsed in
   `runToolCall`; re-parse cheaply or thread through — prefer threading to avoid
   double-parse drift). Append `verificationFooter` to the tool message when
   non-null. `traceAgent` `tool_result` gains `verified: verdict?.ok ?? null`.
2. **Read-back rule in `buildSystemPrompt`** (next to the existing "zero exit
   code" block, `agent.mjs:201-206`):
   ```
   A tool result marked [UNVERIFIED] means the side effect is unconfirmed.
   Do not tell the user it succeeded. Either run a read-back check (fetch the
   sent message, open the created file, list the directory) and confirm from
   that result, or say plainly what remains unconfirmed.
   Claiming an attachment/upload/delivery without evidence is a failure, even
   if the tool call itself returned no error.
   ```
3. **No other loop changes.** Budgets, repeat guard, barriers, cancellation,
   `finishForced`/`writeReply` all untouched. A verification read-back is just
   another model-chosen tool call inside the existing budget.

---

## 6. `tools/_shared.mjs` — evidence protection (edit)

`capOutput(value, maxBytes)`: before truncating, extract and preserve a small
set of verification-critical patterns (`error_count`, `success_count`,
`attachmentList`, `"isError"`, `"ok"`) up to ~500 chars, appended after the
`[output truncated]` marker. Rationale: today's head+tail cut can remove the
exact middle chapter that proves failure; the preserved slice guarantees the
model (and `verdictFor`) can still see it. Pure function, fully unit-testable,
no callers change.

---

## 7. `tools/write-todos.mjs` — corrective errors (edit)

Each of the three error sites gains the current valid state:

- `cannot replace or reorder existing todos; use updates with stable IDs.` →
  append `render(current)` (the same checklist the success path returns) so the
  model sees IDs, order, and statuses.
- `unknown todo ID: <id>.` → append `Available IDs: <id1>, <id2>, …`.
- `cannot remove existing todos.` → append `render(current)` + hint to use
  `status: cancelled` instead of dropping the item.

Cap the appended rendering at ~2000 chars (reuse `capOutput`) so a 100-item
list can't blow the context. Expected effect: the transcript's 5-round failure
becomes a 1-round correction.

---

## 8. Tests

**`test/verify.test.mjs` (new):**
1. `isMutation`: readers false (`read_file`, `skill`, `recall`); writers true
   (`write_file`, `edit_file`); `mcp__*` defers to server hints.
2. `verdictFor`: Gmail-send result with attachment evidence → `ok:true`;
   result with `attachmentList: []` + attachment in args → `ok:false` with
   read-back reason; `"Error: …"` → `ok:false`; reader result → `null`.
3. Success-regex parity: every string the `traceAgent` regex calls failure,
   `verdictFor` calls `ok:false` (import the shared helper — test asserts one
   source of truth).
4. Footer: `ok:false` footer contains `UNVERIFIED` + `read-back`; appended
   *after* truncation (simulate a capped result, assert footer intact).
5. Agent integration (stub client, no network): a turn whose tool returns an
   unverified mutation result produces a tool message containing the footer;
   `tool_result` trace carries `verified: false`.

**`test/write-todos.test.mjs` (new or extend):**
- Reorder attempt error contains the current item IDs; unknown-ID error lists
  valid IDs; remove attempt error suggests `cancelled`; appended rendering is
  capped.

**`capOutput` tests (extend existing):**
- A large JSON result with `error_count` in the middle preserves the evidence
  slice after truncation.

Style: `node:test` + `node:assert/strict`, no network, no model calls — same
pattern as `test/skills.test.mjs`.

---

## 9. Verification

```bash
node --test "test/verify.test.mjs"
node --test "test/write-todos.test.mjs"
node --test "test/*.test.mjs"
```

Live checks (Kilo free tier, as with the skills live test):
- `-p "send a test email to myself with <file> attached"` → expect the turn to
  contain a read-back fetch and either confirmed attachment evidence or an
  honest "unconfirmed" report — never a bare success claim on an empty
  `attachmentList`.
- `write_todos` misuse prompt → single corrective round, not five.
- `/usage` sanity: verdict lines add negligible tokens; read path unchanged.

---

## 10. Risks / mitigations

| Risk | Mitigation |
| --- | --- |
| Verdict heuristics misjudge a tool's result text | Conservative defaults: unknown → `ok:null`, no assertion; criteria only where the shape is known (Gmail/Drive first). False `UNVERIFIED` costs one read-back call, not a failure. |
| Extra tokens per mutation | Footer <200 chars, mutations only; readers pay zero. |
| Double arg-parse drift | Thread parsed args from `runToolCall` into the verdict call rather than re-parsing. |
| `capOutput` evidence slice leaks secrets | Patterns are structural keys + counts only, never values adjacent to `token/key/secret`-named fields; keep an exclusion for those keys. |
| Prompt bloat | One rule block (~6 lines) next to the existing zero-exit-code block it extends. |

---

## 11. Future (out of v1, noted only)

- Whole-loop final-answer claim scan (success verbs vs tool evidence → forced
  verification round instead of returning).
- `allowed-tools`-style per-skill verification hooks (e.g. a skill declares its
  own "done means…" criteria).
- Daemon/Telegram: verification digests for unattended side effects.
- Structured `{ok,…}` results for Composio meta-tools upstream (needs broker
  cooperation; v1 parses text).

---

## 12. Build order

1. `src/verify.mjs` (shared success helper + `isMutation` + `verdictFor` + footer).
2. `src/agent.mjs`: use shared helper in `traceAgent`, attach footers in `run()`,
   add read-back prompt block.
3. `tools/_shared.mjs`: evidence-preserving `capOutput`.
4. `tools/write-todos.mjs`: corrective errors.
5. `test/verify.test.mjs` + todos/capOutput tests → full suite → live turns.
