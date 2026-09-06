# PLAN-GOALS — Proactive Goal System (Tier 3)

Goal engine on top of the existing memory graph: goals with auto-decomposed
steps, deadlines, autonomous reminders, and proactive web research that
prepares context for you before you ask. Zero new services — same embedded
SQLite (`~/.zumba/memory.db`), same Kilo LLM, same `tools/websearch.py`.

---

## 1. Data model (new tables in `memory/db.py`)

```sql
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',   -- active | paused | done | failed | archived
    priority INTEGER NOT NULL DEFAULT 3,     -- 1 (critical) .. 5 (whenever)
    deadline REAL,                           -- epoch; NULL = no deadline
    progress REAL NOT NULL DEFAULT 0.0,      -- 0..1, derived from steps
    source TEXT NOT NULL DEFAULT 'user',     -- user | extracted | proactive
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    details TEXT NOT NULL DEFAULT '{}'       -- json: research notes, recur, motivation
);
CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);

CREATE TABLE IF NOT EXISTS goal_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'todo',     -- todo | in_progress | done | skipped
    due_at REAL,                             -- per-step micro-deadline
    done_at REAL,
    notes TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_steps_goal ON goal_steps(goal_id, step_order);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id) ON DELETE CASCADE,
    step_id INTEGER REFERENCES goal_steps(id) ON DELETE CASCADE,
    fire_at REAL NOT NULL,
    message TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'chat',    -- chat | desktop | scheduled-brief
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | fired | snoozed | cancelled
    fired_at REAL,
    snooze_until REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_fire ON reminders(status, fire_at);

CREATE TABLE IF NOT EXISTS goal_research (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    findings TEXT NOT NULL DEFAULT '',       -- LLM-summarized research digest
    sources TEXT NOT NULL DEFAULT '[]',      -- json list of {title,url}
    created_at REAL NOT NULL
);
```

Migration follows the `_migrate_tier2` pattern → add `_migrate_tier3(con)`
called from `connect()` so old DBs upgrade in place.

## 2. New module: `memory/goals.py` (orchestrator)

Mirrors `briefing.py` / `reflection.py` style. Functions:

- `create_goal(con, title, deadline=None, priority=3, auto_plan=True) -> dict`
  - Inserts goal, then **LLM decomposition pass** (see below) into steps.
  - Steps get staggered `due_at` micro-deadlines: deadline ÷ steps, weighted
    by the LLM's suggested effort.
- `add_step / complete_step / skip_step / update_goal / pause / complete_goal`
  - `complete_step` recomputes `goals.progress` (done_steps / total, with
    skipped counted as done for momentum purposes).
- `active_goals(con)`, `overdue(con)`, `stalled(con, days=3)`
  - *stalled* = active goal whose next `todo` step is past `due_at` or that
    has had zero step activity in N days → feeds nags.
- `decompose(con, goal_id, use_llm=True)`
  - LLM prompt: given title/description/deadline, return
    `{"steps": [{"title","why","effort_days"}], "risks": [".."],
      "first_action": ".."}` — JSON via `memory/llm.chat_json` (same pattern
    as reflection). Heuristic fallback: split into 3 generic steps so the
    system never blocks on LLM failure (matches the codebase convention of
    graceful degradation).
- `research_goal(con, goal_id, use_llm=True)`
  - Proactive enrichment: builds 2–4 search queries from the goal title +
    steps → calls the existing `tools/websearch` engine → LLM distills a
    digest into `goal_research` with source URLs.
  - Triggered (a) once on goal creation, (b) manually via
    `zumba goal research <id>`, (c) by the proactive worker before a deadline.

## 3. Reminder engine: `memory/reminders.py`

- `schedule_natural(con, text, when_expr, goal_id=None)`
  - Parse natural time ("tomorrow 9am", "in 3 days", "friday", "every day")
    — start with a small regex parser (no new dependency), fall back to LLM
    parse via `chat_json` when regex fails.
- `due_reminders(con)` — all `pending` where `fire_at <= now`.
- `fire_due(con)` — mark fired + deliver: Rich panel in the chat REPL, and
  (`channel=desktop`) a Windows toast via a PowerShell one-liner
  (`[Windows.UI.Notifications]`), no dependency. Snooze support:
## 4. Proactive autonomous behavior: `memory/proactive.py`

The piece that acts without being asked. Design principle: **runs
opportunistically, cheap checks on a timer, LLM passes only when triggered**.

- `ProactiveWorker` — daemon thread started alongside the existing memory
  background worker in `chat_cmd` (and standalone via `zumba goal tick`).
- Tick loop (every ~5 min while chat is open; one pass when scheduled):
  1. Fire due reminders.
  2. **Deadline watch** — active goal with deadline within 48h and progress
     < 50% → urgency nag + suggest the single next step.
  3. **Stall watch** — goal with no step activity for 3+ days → gentle
     check-in, offer to re-plan or shrink the goal ("make it smaller").
  4. **Pre-research** — goal deadline within 7 days and no `goal_research`
     in the last 5 days → run `research_goal()` and present findings
     unprompted ("I looked ahead at your IELTS goal — here's what's new").
  5. **Win detection** — goal crossed 100% steps → celebration + archive
     prompt; goal past deadline with 0% for 7 days → propose `failed` or
     reschedule (never silently drops anything).
- Rate limiting: at most one proactive interruption per 30 min
  (`meta` key `proactive_last_nudge`), configurable via
  `zumba config set proactive_minutes 30` / `proactive off`.
- All nudges are also injected into the next system message so the LLM can
  weave them into conversation naturally instead of dumping panels.

## 5. Integration points (existing code, minimal diffs)

| File | Change |
| --- | --- |
| `memory/db.py` | Add tier-3 tables + `_migrate_tier3` |
| `main.py` | New `goal` typer + `/goal`, `/remind` in-chat commands; goals section in `compose_daily`; start `ProactiveWorker` in `chat_cmd`; reminder check at REPL loop top |
| `memory/briefing.py` | New `goals_digest(con)` — top 3 active goals w/ next steps + overdue flags — prepended to the daily brief |
| `memory/reflection.py` | Follow-up detection upgrade: when reflection extracts a follow-up that looks like a goal ("I want to…", "by <date>"), propose converting it to a goal |
| `memory/service.py` | Expose goal read-context in hybrid recall so chat knows about your goals |
| `mcpclient/builtin.py` | Goal tools exposed to the MCP agent loop so the LLM can create/complete goals during conversation |

### CLI

```powershell
python main.py goal add "Pass IELTS 7.5" --deadline 2026-12-01 --priority 1
python main.py goal list [--all]         # active w/ progress bars + next step
python main.py goal show <id>            # steps, research, reminders, timeline
python main.py goal step <id> done|add|skip
python main.py goal research <id>        # force proactive web research now
python main.py goal tick                 # run one proactive pass manually
python main.py goal remind "text" --at "friday 5pm" [--goal 3] [--every daily]
python main.py goal pause|resume|complete|fail <id>
python main.py daily --install-reminder  # existing scheduler; tick included
```

In-chat: `/goal add …`, `/goal list`, `/remind …` handled in the REPL's
chat-command layer next to `/vault` / `/web`.

  `remind me again in 2h` → `snoozed`.
- Recurring reminders: `details` json holds `recur: "daily"|"weekly"`;
  on fire, re-insert next occurrence.


## 6. Build order (4 PR-sized chunks)

1. **Schema + CRUD + CLI** — `db.py` tier-3, `goals.py` CRUD + decomposition,
   `goal` typer, pytest suite with mocked LLM (pattern: existing
   `tests/` memory tests).
2. **Reminders** — `reminders.py`, natural-time parsing (regex-first, LLM
   fallback), REPL firing, desktop toast, recurring.
3. **Proactive worker** — `proactive.py`, tick loop, deadline/stall watch,
   rate limiting, briefing integration.
4. **Research + agent tools** — `research_goal()` on websearch, reflection →
   goal promotion, MCP builtin goal tools, `goal tick` in Task Scheduler.

## 7. Non-goals / constraints

- No new dependencies (time parsing by regex+LLM; toasts via PowerShell).
- No always-on server process — the proactive loop lives in the chat session
  + scheduled `goal tick` (same philosophy as the daily brief).
- Goals are first-class rows, *linked* into the graph later (entity
  `type='goal'` + relations) — deferred to a follow-up so the read path can
  recall goals organically.

Great question. Let me walk through **how the whole thing actually works under the hood**, from the moment you type a goal to the moment it nudges you — no jargon, concrete flow.

---

## 1. You say "I want to pass IELTS 7.5 by December"

In chat, you type that. Two things happen **right now**, with today's code:
- The **memory extraction** pipeline already runs after every turn and stores it as an episode/fact.
- The **reflection** pass (session end) spots phrases like "I want to… / by <date>" and saves it as an **open follow-up**.

**The new system upgrades this step**: instead of just a follow-up string in a table, it recognizes this as a *goal* and creates a row in the `goals` table.

---

## 2. The LLM breaks your goal into steps (auto-decomposition)

`create_goal()` inserts the goal, then immediately calls the LLM **once** with a prompt like:

> *"Here's a goal: 'Pass IELTS 7.5 by Dec 1'. Break it into actionable steps with effort weights and risks. Return JSON."*

The LLM replies (via the same `chat_json` machinery your `reflection.py` already uses) with something like:

```json
{
  "steps": [
    {"title": "Take a diagnostic mock test", "effort_days": 1},
    {"title": "Daily 30-min listening practice", "effort_days": 40},
    {"title": "Weekly full-length mock + review", "effort_days": 8}
  ],
  "risks": ["Listening section is your weak point"],
  "first_action": "Book the diagnostic test this week"
}
```

That's saved into `goal_steps`. Then the system **stretches your deadline across the steps**: Dec 1 ÷ (~49 working days) → each step gets a `due_at` proportionally weighted by its `effort_days`. So step 1 is due this week, step 2 is due Nov 15, etc. Now you have micro-deadlines, not just one big scary date.

**Key detail:** if the LLM call fails, it falls back to 3 generic steps so the system *never* blocks. This mirrors the graceful-degradation convention in your codebase.

---

## 3. The background worker runs on a timer (the "automatic" part)

When chat is open, a background thread (same idea as your existing memory worker) ticks every ~5 minutes. **Each tick is a cheap SQL check first, LLM only if triggered.** The checks:

1. **Fire due reminders** — `SELECT ... WHERE status='pending' AND fire_at <= now()`. If matches, it prints a Rich panel in chat (or a Windows toast if `channel=desktop`).

2. **Deadline watch** — `SELECT goals WHERE deadline <= now+48h AND progress < 0.5`. If found, it nudges: *"Your IELTS deadline is in 2 days and you're 30% done — the next step is the diagnostic test. Want me to re-plan?"*

3. **Stall watch** — a goal with zero step activity for 3+ days → *"Haven't logged progress in a while, want to shrink this goal so it's easier?"* (This is the "make it smaller" anti-procrastination trick.)

4. **Pre-research** — goal deadline is within 7 days, and no `goal_research` row in the last 5 days → it **proactively web-searches**. It builds queries from the goal title + steps, calls your existing `tools/websearch.py`, then distills findings into `goal_research`. So when you open chat that day, it says: *"I looked ahead at your IELTS goal — there's a new official practice format this month, here's what changed."*

5. **Win / fail detection** — steps hit 100% → celebration + archive prompt; past deadline with 0% for 7 days → proposes *failed* or reschedules. **Nothing is silently dropped.**

**Rate limiting:** only one nudge per 30 min (stored in `meta`), so it doesn't spam you. You can turn it off with `proactive off`.

---

## 4. How it "remembers to remind you"

Reminders are rows in a table, not magic:

```
reminders(id, goal_id, fire_at, message, channel, status, snooze_until, ...)
```

- **Natural time** ("friday 5pm", "in 3 days", "every day") is parsed by a regex parser first, and falls back to the LLM if the regex can't figure it out.
- When `fire_at <= now()` and `status='pending'`, the worker marks it `fired` and delivers it.
- **Snooze** = set `status='snoozed'` + `snooze_until`; the next tick picks it up again.
- **Recurring** ("every day") = `details` json stores `recur: "daily"`, and every time it fires it re-inserts the next occurrence. So a daily gym reminder is just a reminder that re-arms itself.

---

## 5. The proactive part in plain terms

The three pieces that act *without you saying anything*:

| Trigger | Condition | What it does |
|---|---|---|
| Due reminder | `fire_at <= now`, pending | Delivers message (panel/toast) |
| Deadline nudge | deadline ≤ 48h, progress < 50% | Urgency message + next step |
| Pre-research | deadline ≤ 7d, no recent research | Web-searches, summarizes, tells you |
| Stall check-in | no activity 3+ days | Suggests shrinking the goal |
| Win/fail | 100% / abandoned | Celebr / proposes fail/reschedule |

Crucially, the nudge is also **injected into the next system message** — so instead of dumping ugly panels, the LLM can work "I noticed you mentioned the mock test, want to schedule it?" naturally into the conversation.

---

## 6. The CLI it gives you

```
goal add "Pass IELTS 7.5" --deadline 2026-12-01 --priority 1
goal list                     # progress bars + next step
goal show 3                   # steps, research, reminders
goal step 3 done              # check off a step → progress recomputes
goal research 3               # force a web-search pass now
goal tick                     # run one proactive pass manually (also scheduled daily)
goal remind "stretch break" --at "friday 5pm" --every daily
daily --install-reminder      # already exists; now also runs the tick
```

Plus in-chat `/goal ...` and `/remind ...` commands.

---

## A concrete end-to-end timeline

1. **Today 7pm** — You: *"I want to pass IELTS 7.5 by Dec 1."* → Goal created, LLM splits it into steps with micro-deadlines, and it instantly kicks off a **pre-research pass** (finds free practice resources, stores findings).
2. **Tonight 8pm** — Step 1's reminder fires: *"Book your diagnostic mock test (Suggested: this Saturday)."*
3. **Saturday** — You mark step 1 done in chat (`/goal step 1 done`). Progress jumps to ~20%.
4. **Nov 24** — You've gone quiet 3 days → gentle check-in: *"Want to re-plan? Your margin is thin."*
5. **Nov 28** — No research in 5 days + deadline in 3 days → worker re-searches, tells you *"A new listening test released — doing it now could lift your score."*
6. **Dec 2** — Steps hit 100% → *"You did it. Archive this goal?"*
