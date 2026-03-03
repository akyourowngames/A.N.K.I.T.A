# 🧠 PlannerAgent — Full Implementation Plan
### "The Brain That Thinks Before Ankita Acts"

---

## The Problem It Solves

Right now Ankita's Supervisor reads a request and instantly picks agents — in 256 tokens, with no deep thinking. For simple tasks this is perfect. For complex multi-step tasks it breaks because:

- It under-routes (picks 1 agent when 4 are needed)
- It doesn't detect dependencies ("save it" only works AFTER "write it")
- It can't handle conditionals ("only send if tests pass")
- It has no awareness of what "done" actually means for the full request

PlannerAgent fixes this by adding a **dedicated thinking layer** that sits between the Supervisor and the Orchestrator — only activating when a task genuinely needs it.

---

## Architecture: Where PlannerAgent Lives

```
User Request
     │
     ▼
┌─────────────────┐
│   Supervisor    │  ← still the first gate (fast, cheap)
│  (256 tokens)   │  detects: "is this multi-step?"
└────────┬────────┘
         │
    Multi-step?
    ┌────┴─────┐
   YES         NO
    │           │
    ▼           ▼
┌──────────┐  [existing specialist routing — unchanged]
│ Planner  │
│  Agent   │  ← NEW: dedicated thinking agent
│(1500 tok)│  reads full request, outputs structured PLAN
└────┬─────┘
     │
     ▼ PLAN: [{agent, task, depends_on, condition}]
     │
     ▼
┌─────────────────────────────┐
│       Orchestrator          │
│  _run_plan() — NEW method   │  executes plan step by step
│  respects depends_on order  │  handles conditionals
│  passes baton between steps │
└─────────────────────────────┘
```

---

## Part 1 — Supervisor Changes (`agents/supervisor.py`)

### What Changes
The Supervisor gets one new job: detect if a request needs planning. If yes, return `"agents": ["PlannerAgent"]`. That's it. It doesn't plan itself — it just knows when to hand off.

### Multi-Step Detection Triggers

The Supervisor routes to PlannerAgent when the request contains ANY of:

**Explicit chaining words:**
- "and then", "after that", "once done", "then", "finally", "also", "next"

**Implicit multi-step verbs (3+ distinct action verbs):**
- research + write + save + send = 4 verbs → PlannerAgent
- search + open = 2 verbs → still direct routing (not complex enough)

**Conditional language:**
- "if", "only if", "only when", "unless", "depending on"

**Reference words that imply a prior step:**
- "save it", "send it", "open it", "run it", "commit it" in the same sentence as a production verb

**Explicit planning keywords:**
- "plan", "steps", "workflow", "pipeline", "end to end", "full flow", "automate"

### Supervisor Prompt Addition

Add this section to `_SUPERVISOR_SYSTEM_PROMPT`:

```
PLANNER DETECTION (CHECK FIRST):
Route to PlannerAgent if the request:
  - Has 3+ distinct action verbs (research + write + save + send)
  - Contains chaining words: "and then", "after that", "then", "once done"
  - Contains conditionals: "if tests pass", "only if", "unless"
  - Is a full workflow: "end to end", "full pipeline", "automate this"
  - Has 4+ implied steps when read carefully

Route DIRECTLY (skip PlannerAgent) if:
  - Single clear action: "play music", "what's the weather", "open Chrome"
  - Two-step assembly line already handled: "write poem and save" → ContentAgent+FileAgent
  - Pure conversation or follow-up

EXAMPLES:
- "research laptops, write a report, save it, email Raj" → PlannerAgent (4 steps)
- "fix the bug, run tests, if pass commit to github" → PlannerAgent (conditional)
- "write a poem and save it" → ContentAgent+FileAgent (simple, no planner needed)
- "play lo-fi" → MusicAgent (single step)
```

### Token Budget
Raise Supervisor max_tokens from **256 → 400**. The extra 144 tokens gives it room to reason about whether planning is needed without slowing it down.

---

## Part 2 — PlannerAgent (`agents/planner.py`) — New File

### What It Is
A standalone agent with a single purpose: read the full user request + conversation history and output a structured execution plan as JSON.

It does NOT execute anything. It does NOT call tools. It only thinks and plans.

### Its System Prompt (The Brain)

```
You are A.N.K.I.T.A's PlannerAgent — the mission architect.

Your ONLY job: decompose a complex request into a precise, ordered execution plan.

You output a JSON plan. Nothing else.

AVAILABLE AGENTS AND WHAT THEY DO:
- WebAgent: search, research, compare, fact-check, scrape, Reddit, StackOverflow
- ContentAgent: write essays, reports, emails, poems, scripts, any text content  
- FileAgent: read, write, edit, save, delete files. Opens files after saving.
- SystemAgent: launch apps, control volume/wifi/bluetooth, take screenshots
- CodeAgent: write code, fix bugs, run code, git operations, refactor
- TerminalAgent: raw shell commands, ping, curl, git, tasklist
- CommsAgent: send WhatsApp messages
- CronAgent: schedule tasks, set reminders, recurring jobs
- MusicAgent: play/pause/search music
- ScreenAgent: visual tasks, click elements, read screen
- IntegrationAgent: Google Sheets, YouTube, Figma
- WatchdogAgent: monitor pages, track prices, watch files

PLAN FORMAT:
Output ONLY valid JSON:
{
  "goal": "one sentence describing what the user ultimately wants",
  "steps": [
    {
      "id": 1,
      "agent": "WebAgent",
      "task": "search for best budget laptops under 50000 INR, get top 5 with specs",
      "depends_on": [],
      "condition": null,
      "artifacts_out": ["search_results"]
    },
    {
      "id": 2,
      "agent": "ContentAgent", 
      "task": "write a comparison report from the search results",
      "depends_on": [1],
      "condition": null,
      "artifacts_out": ["report_text"]
    },
    {
      "id": 3,
      "agent": "FileAgent",
      "task": "save the comparison report as laptop_report.md on Desktop",
      "depends_on": [2],
      "condition": null,
      "artifacts_out": ["file_path"]
    },
    {
      "id": 4,
      "agent": "CommsAgent",
      "task": "send laptop_report.md to Raj on WhatsApp",
      "depends_on": [3],
      "condition": null,
      "artifacts_out": []
    }
  ]
}

RULES:
1. Each step's task must be SPECIFIC — include what data to pass from previous steps
2. depends_on = list of step IDs that must complete before this one runs
3. condition = null for unconditional, or a string like "only if step 2 exit_code == 0"
4. artifacts_out = what this step produces that the next step needs
5. Never plan more than 8 steps
6. Never include unnecessary steps — minimum steps to achieve the goal
7. If two steps have NO dependency between them, they can run in parallel (same depends_on value)
8. Always end the plan — never leave the user's ultimate goal unfinished
```

### Token Budget
PlannerAgent gets **1500 tokens** — generous enough to reason carefully about complex multi-step tasks. This is a one-time cost before execution begins.

### Input to PlannerAgent
- Full user request text
- Last 6 turns of conversation history (same `_extract_clean_history` already used everywhere)
- Current context: any files open, any previous results in this session

---

## Part 3 — Orchestrator Changes (`agents/orchestrator.py`)

### 3A — Detect PlannerAgent Routing

In `Orchestrator.run()`, after Supervisor returns routing:

```
if agent_names == ["PlannerAgent"]:
    return self._run_planned_task(user_text, messages)
```

### 3B — New Method: `_run_planned_task()`

This is the main new piece of the orchestrator. Here's the complete logic in plain English:

**Step 1 — Call PlannerAgent**
Make an LLM call to PlannerAgent with the full user text + conversation history. Get back the JSON plan. Parse it. Log it to audit.

**Step 2 — Show the plan to the user (optional but great UX)**
Before executing, print a brief human-readable preview:
```
📋 Plan: 4 steps
  1. WebAgent → search laptops
  2. ContentAgent → write report  
  3. FileAgent → save report
  4. CommsAgent → send to Raj
```
This makes Ankita feel transparent and intelligent, not like a black box.

**Step 3 — Build the execution queue**
Sort steps by `depends_on`. Steps with empty `depends_on` can start immediately. Steps that depend on others wait.

**Step 4 — Execute step by step**
For each step in order:
- Look up the agent from SPECIALIST_MAP
- Build the task string: step's `task` field + inject artifacts from prior completed steps
- Run it through the existing `_run_specialist()` (reuse everything: BATON PASS, TELEPATHY, HYDRA, Token Guardian — all of it still works)
- Extract artifacts from the result
- Store artifacts in a `step_results` dict keyed by step ID
- If the step has a `condition` — evaluate it before running the next step

**Step 5 — Condition Evaluation**
When a step has `condition: "only if step 2 exit_code == 0"`:
- Check the prior step's result for success/failure
- If condition is NOT met — skip the step, log why, continue to next
- Tell the user which step was skipped and why

**Step 6 — Fan-In at the end**
After all steps complete, call the existing `_synthesize()` with all results to produce one clean final reply to the user.

### 3C — Artifact Injection Between Plan Steps

When step 3 (FileAgent) runs, it needs the output of step 2 (ContentAgent). The orchestrator handles this by building a rich task string for each step:

```
Original task: "save the comparison report as laptop_report.md on Desktop"

Enriched task (what actually gets sent to FileAgent):
"save the comparison report as laptop_report.md on Desktop

[STEP 2 OUTPUT - ContentAgent]:
--- PREVIOUS AGENT OUTPUT ---
[ContentAgent]: Here is the comparison report...
CONTENT:
# Best Budget Laptops Under 50K INR
...
:END_CONTENT
--- END CONTEXT ---"
```

This is exactly the same `_build_prior_context_block()` that already exists — PlannerAgent just chains it across more steps, not just 2-3.

### 3D — Parallel Step Support

When two steps have the same `depends_on` value, they can run in parallel. Reuse the existing `_fan_out_parallel()` with `ThreadPoolExecutor`. No new code needed — just group steps by their `depends_on` level and call the right execution path.

Example:
```json
Step 3: agent=FileAgent, depends_on=[2]
Step 4: agent=CommsAgent, depends_on=[2]  ← same depends_on = parallel
```
Steps 3 and 4 both depend on step 2 but not on each other → run them simultaneously.

---

## Part 4 — Escalation Matrix Update (`agents/orchestrator.py`)

Add PlannerAgent to the HYDRA fallback chain. If PlannerAgent fails to produce a valid plan (JSON parse error, empty response, LLM error):

```
"PlannerAgent": ("GeneralAgent", 
    "PlannerAgent failed to produce a plan. 
     Handle this request directly as best you can,
     completing all implied steps yourself.")
```

This means even if planning fails, Ankita still tries to help — it just falls back to GeneralAgent with the full request.

---

## Part 5 — SPECIALIST_MAP Update (`agents/specialists.py`)

Add PlannerAgent to the registry so the orchestrator can look it up:

```python
PlannerAgent = SpecialistAgent(
    name="PlannerAgent",
    tool_names=set(),       # No tools — pure reasoning agent
    system_prompt=_PLANNER_SYSTEM_PROMPT
)

SPECIALIST_MAP["PlannerAgent"] = PlannerAgent
```

Note: `tool_names=set()` because PlannerAgent never calls tools. It only thinks. The empty tool set means the LLM gets zero tool specs injected, keeping its context clean for pure reasoning.

---

## Part 6 — Audit Trail

Every plan gets written to `.ankita/audit.jsonl` with a special entry type:

```json
{
  "type": "plan",
  "ts": 1234567890,
  "user_request": "research laptops...",
  "plan": { ...full plan JSON... },
  "steps_executed": 4,
  "steps_skipped": 0,
  "total_time_ms": 12400
}
```

This feeds into the FeedbackEngine so patterns can be learned — e.g., "when user asks for research+report+email, PlannerAgent produces 4 steps and all succeed → this is a reliable pattern."

---

## Files to Create / Modify

| File | Action | What Changes |
|---|---|---|
| `agents/planner.py` | **CREATE** | New file — PlannerAgent class + system prompt |
| `agents/supervisor.py` | **MODIFY** | Add multi-step detection rules + raise max_tokens to 400 |
| `agents/orchestrator.py` | **MODIFY** | Add `_run_planned_task()`, handle PlannerAgent routing |
| `agents/specialists.py` | **MODIFY** | Add PlannerAgent to SPECIALIST_MAP |

That's it. 4 files. No new dependencies. No new API keys. No new pip installs.

---

## Real Examples: Before vs After

### Example 1 — Research + Report + Email

**Request:** `"research best budget laptops under 50k, write a comparison report, save it to desktop, and WhatsApp it to Raj"`

**Before:** WebAgent searches. Done. Report never written. Raj never notified.

**After:**
```
📋 Executing 4-step plan...

Step 1/4 — WebAgent: searching budget laptops...
  ✅ Found 5 laptops with specs and prices

Step 2/4 — ContentAgent: writing comparison report...
  ✅ Report written (847 words)

Step 3/4 — FileAgent: saving report...
  ✅ Saved → C:\Users\Krish\Desktop\laptop_report.md

Step 4/4 — CommsAgent: sending to Raj...
  ✅ Sent to Raj on WhatsApp

Done! Researched 5 laptops, wrote a report, saved it, and sent it to Raj.
```

---

### Example 2 — Code + Test + Conditional Commit

**Request:** `"fix the null pointer bug in auth.py, run the tests, and only commit to GitHub if they pass"`

**Before:** CodeAgent fixes bug. Done. Tests never run. No commit decision made.

**After:**
```
📋 Executing 3-step plan (1 conditional)...

Step 1/3 — CodeAgent: fixing null pointer in auth.py...
  ✅ Bug fixed — added null check on line 47

Step 2/3 — TerminalAgent: running pytest...
  ✅ 23 passed, 0 failed (exit_code=0)

Step 3/3 — [CONDITION: only if tests pass ✅] — CodeAgent: committing to GitHub...
  ✅ Committed — "fix: null pointer in auth.py"

Done! Fixed the bug, all 23 tests passed, committed to GitHub.
```

If tests had FAILED:
```
Step 3/3 — [CONDITION: only if tests pass ❌ — tests failed] — SKIPPED
Done! Fixed the bug but 3 tests failed. Skipping commit — review test_auth.py.
```

---

### Example 3 — Morning Briefing Automation

**Request:** `"every morning at 8am: check trending tech news, write a 5-bullet briefing, save it, and read it aloud"`

**Before:** CronAgent schedules something vague. Nothing useful happens at 8am.

**After:**
```
📋 Plan: 1 CronAgent wrapper + 4-step daily pipeline

Step 1/1 — CronAgent: scheduling daily 8am pipeline...

Daily pipeline at 8:00 AM:
  1. WebAgent → fetch trending tech news
  2. ContentAgent → write 5-bullet briefing
  3. FileAgent → save as morning_brief_[date].md
  4. SystemAgent → voice_control → read aloud

✅ Scheduled! Every morning at 8:00 AM, Ankita will brief you.
```

---

### Example 4 — Parallel Steps

**Request:** `"search Python jobs and JavaScript jobs at the same time, then merge the results into one file"`

**Before:** WebAgent searches Python jobs. Done. JavaScript never searched. No merge.

**After:**
```
📋 Executing 3-step plan (2 parallel)...

Steps 1a + 1b — [PARALLEL] WebAgent × 2:
  1a. Searching Python jobs... ✅
  1b. Searching JavaScript jobs... ✅ (ran simultaneously)

Step 2 — FileAgent: merging results into jobs_combined.md...
  ✅ Saved → Desktop/jobs_combined.md

Done! Searched both in parallel, merged into one file.
```

---

## What Stays Unchanged

Everything that already works keeps working exactly as before:

- Simple requests → Supervisor routes directly → same as today (zero overhead)
- BATON PASS + TELEPATHY → PlannerAgent just feeds more steps into the same chain
- HYDRA escalation matrix → still fires if any step fails
- Token Guardian → still guards every individual agent call
- Conversation history → still passed to every agent
- Memory injection → still fires before every agent speaks
- Audit log → extended to include plan entries
- FeedbackEngine → learns from plan successes/failures

PlannerAgent is purely **additive**. It slots into the existing architecture without touching any existing logic.

---

## Implementation Order

**Phase 1 — Foundation (do this first)**
1. Create `agents/planner.py` with PlannerAgent class and full system prompt
2. Add PlannerAgent to SPECIALIST_MAP in `specialists.py`
3. Add `_run_planned_task()` skeleton to orchestrator (returns a stub for now)

**Phase 2 — Supervisor Trigger**
4. Add multi-step detection rules to Supervisor prompt
5. Raise Supervisor max_tokens to 400
6. Test: verify Supervisor correctly routes complex requests to PlannerAgent

**Phase 3 — Execution Engine**
7. Build full `_run_planned_task()` in orchestrator
8. Implement artifact injection between plan steps
9. Implement conditional step logic
10. Implement parallel step grouping

**Phase 4 — Polish**
11. Add plan preview output (the 📋 display)
12. Add plan entry to audit log
13. Add PlannerAgent to HYDRA escalation matrix
14. End-to-end test with 5 real complex scenarios

---

## Success Criteria

PlannerAgent is working correctly when:

- "research X, write report, save, email" → all 4 steps complete, zero follow-ups needed
- "fix bug, run tests, only commit if pass" → conditional correctly evaluated
- "search X and Y simultaneously then merge" → parallel steps run at the same time
- Simple "play music" → PlannerAgent NOT triggered (Supervisor routes directly)
- PlannerAgent LLM failure → falls back to GeneralAgent, user still gets a response
- All existing tests still pass (no regression)

---

*PlannerAgent doesn't make Ankita smarter — it makes her complete. The intelligence was already there in each specialist. This gives it a mind that thinks end-to-end before the first hand moves.*