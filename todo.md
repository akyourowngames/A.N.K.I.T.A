Now I have a deep picture of the entire system. Let me build the complete plan.Now I have everything I need. Here's the complete bulletproof plan:

---

# 🔥 ANKITA — Complete New Upgrades Master Plan

*Everything new. No repeats from previous sessions.*

---

## TIER 1 — BRAIN UPGRADES (Intelligence Layer)

### 🧠 Upgrade 1: ContextAgent — The Memory Synthesizer
**What it is:** A new specialist agent that runs *before* the Supervisor on every message. Its job: scan the last 10 turns, extract entities (names, files, URLs, tasks), inject a clean `CONTEXT_BLOCK` into the Supervisor's routing decision.

**Why:** Right now the Supervisor routes on the raw user text alone. If Krish says "finish that" after a long coding session, the Supervisor has no idea what "that" is. ContextAgent reads history and builds: `"CONTEXT: user was debugging main.py, last error was ModuleNotFoundError at line 47, last agent was CodeAgent"` — so the Supervisor routes correctly.

**Files:** New `agents/context_agent.py`, modify `orchestrator.py` to call it before Supervisor routing. No new tools needed — pure LLM reasoning.

**Protocol:**
- Run before every Supervisor call (lightweight — 1 LLM call, max 200 tokens)
- Output: `CONTEXT_BLOCK` with: active_agent, active_file, active_task, last_result, pending_follow_up
- Inject into Supervisor system prompt dynamically
- Cache for 30 seconds to avoid redundant calls

---

### 🧠 Upgrade 2: FeedbackAgent → Self-Healing Supervisor
**What it is:** The FeedbackEngine exists and collects data, but `get_injected_patterns()` is called nowhere in the Supervisor prompt dynamically. Wire it in.

**The gap:** `feedback_engine.get_injected_patterns()` returns learned rules, but `supervisor.py` never calls it. The patterns sit in `patterns.json` unused.

**Fix:** In `SupervisorAgent.route()`, at prompt construction time, call `get_injected_patterns()` and prepend it to the system prompt. ANKITA literally gets smarter after every 5 interactions automatically — it's already built, just not connected.

**Files:** Modify `agents/supervisor.py` — inject patterns at runtime. 10 lines of code. Massive impact.

---

### 🧠 Upgrade 3: DreamAgent → Proactive Task Suggestions
**What it is:** DreamAgent currently generates "epiphanies" from memory. Upgrade it to also generate *actionable proactive suggestions* based on patterns.

**New behavior during idle:**
- Scan recent interactions for incomplete tasks ("Krish started writing a report but never finished")
- Check cron jobs for upcoming deadlines
- Check if any watchdog alerts fired but weren't acknowledged
- Push a morning briefing at 9 AM without being asked: "Good morning! 3 things: your report is half-done, BTC watchdog triggered twice overnight, you have a cron reminder in 2 hours."

**Files:** Modify `proactive.py` `_check_dream()` method. Add `_morning_briefing()` method. Connect to CornService to check upcoming jobs.

---

## TIER 2 — NEW AGENT POWERS

### ⚡ Upgrade 4: NavigatorAgent — Maps + Location Intelligence
**What it is:** A completely new specialist for location, maps, navigation, and nearby searches. Currently there's a `GOOGLE_MAPS_API_KEY` in `.env.example` but no dedicated agent.

**Capabilities:**
- "Navigate to X" → Google Maps route + estimated time
- "Find coffee near me" → Places API + ranked list with ratings
- "How far is X from Y" → distance + travel time by mode
- "What's traffic like on Delhi–Gurgaon highway right now" → live traffic
- "Show me restaurants near Connaught Place under ₹500" → filtered search
- Route planning with multiple stops

**Tools to build:** `maps_op(action, origin, destination, query, mode)` in a new `tools/maps_ops.py`. Register in engine.py. Add `NavigatorAgent` to `specialists.py` and `SPECIALIST_MAP`.

**Files:** New `tools/maps_ops.py`, modify `tools/engine.py`, `agents/specialists.py`, `agents/supervisor.py` routing rules.

---

### ⚡ Upgrade 5: TaskAgent — Smart To-Do + Reminders System
**What it is:** ANKITA has CronAgent for scheduling but no concept of a *task list*. TaskAgent manages a persistent `tasks.json` with priorities, deadlines, and status tracking.

**Capabilities:**
- "Add task: finish the API integration by Friday, priority high"
- "What are my pending tasks?" → formatted list with priority colors
- "Mark that as done"
- "What's overdue?" → tasks past deadline
- "Remind me 30 minutes before each task's deadline" → auto-creates cron jobs
- "Summarise my week" → what was completed, what's pending
- Integrates with CronAgent: creating a task with a deadline auto-schedules a cron reminder

**Tools to build:** `task_op(action, title, priority, deadline, tags, status)` in `tools/task_ops.py`.

**Files:** New `tools/task_ops.py`, modify `tools/engine.py`, new `TaskAgent` in `agents/specialists.py`.

---

### ⚡ Upgrade 6: ReportAgent — Automated PDF/HTML Report Builder
**What it is:** Right now ContentAgent writes text and FileAgent saves it. But there's no agent that builds *structured, formatted reports* with sections, charts, tables, and exports to PDF.

**Capabilities:**
- "Build a report on my disk usage" → pulls `disk_analysis` data, formats into a PDF report with charts
- "Generate a weekly activity report" → pulls from FeedbackEngine stats + memory + task completions
- "Create a project status report for ANKITA" → reads codebase structure, recent git commits, test results
- Export to both `.pdf` and `.md` simultaneously
- Include actual data tables, not just text

**This is different from ContentAgent** — ContentAgent writes essays. ReportAgent builds *structured data documents* with real metrics from tool calls.

**Files:** New `ReportAgent` in `agents/specialists.py` with a tool set of `disk_analysis`, `git_op`, `read_file`, `list_files`, `write_file`, plus a new `generate_pdf` tool in `tools/report_ops.py`.

---

## TIER 3 — EXISTING AGENT KILLER UPGRADES

### 🚀 Upgrade 7: WebAgent — Research Memory + Citation System
**Current gap:** WebAgent searches, reads, and returns results — but never *remembers* what it researched. If Krish asks "what did we find about Python frameworks last week?" the answer is gone.

**Upgrade:**
- After every `deep_research` call, automatically `remember('research: <topic> | <key_findings> | <sources>')` 
- Before any research, `recall('research')` to check if it was done recently — avoid redundant searches
- Add a `CITATION BLOCK` to every research response: numbered `[1]`, `[2]` source references at the bottom
- Add `compare_and_decide` protocol: when asked "which is better, X or Y", WebAgent always builds a structured comparison table before answering — never a freeform paragraph

**Files:** Modify `_WEB_SYSTEM_PROMPT` in `agents/specialists.py`. No new tools needed.

---

### 🚀 Upgrade 8: SystemAgent — PC Health Dashboard
**Current gap:** SystemAgent can check CPU/RAM/battery individually but has no concept of a *health overview* or *proactive alerts*.

**Upgrade:**
- New `health_dashboard` action in `system_health` tool: returns a structured snapshot — CPU%, RAM%, disk%, battery%, top 5 processes, network latency to Google
- Add `DAILY_HEALTH_PROTOCOL`: at 9 AM (via cron), SystemAgent auto-runs health_dashboard and pushes results to ProactiveEngine if anything is concerning (CPU > 80%, RAM > 85%, disk > 90%, battery < 20%)
- `ANOMALY DETECTION`: if the same process is eating >40% CPU for 3+ consecutive checks, push an alert: "Chrome has been using 45% CPU for 15 minutes. Kill it?"
- Add `startup_programs` action: list all apps that run on startup, with option to disable them

**Files:** Modify `_SYSTEM_SYSTEM_PROMPT` in `agents/specialists.py`. Extend `system_health` tool in `tools/system_ops.py`.

---

### 🚀 Upgrade 9: CodeAgent — Git Commit Intelligence
**Current gap:** CodeAgent can run git commands via TerminalAgent but has no native git awareness. It doesn't know what branch it's on, what's uncommitted, or what the last commit message was.

**Upgrade:**
- Add `git_op` to `_CODE_TOOLS` (it's currently only in `_TERMINAL_TOOLS`)
- Add `GIT CONTEXT PROTOCOL`: before working on any code file, call `git_op(action='status')` to understand the current state
- Add `COMMIT HYGIENE RULES` to prompt: after any successful code edit + test pass, suggest a commit with a smart message derived from what changed
- Add `BRANCH STRATEGY`: if the change is large (>3 files), suggest creating a branch first
- Add `DIFF BEFORE EDIT`: before editing a file, call `diff_files` to understand current state vs what needs to change

**Files:** Modify `_CODE_TOOLS` set and `_CODE_SYSTEM_PROMPT` in `agents/specialists.py`. One-line tool addition.

---

### 🚀 Upgrade 10: WatchdogAgent — Full Prompt Rewrite
**Current status:** Marked as NOT STARTED. The WatchdogAgent has no real prompt — it's a stub.

**Full capabilities to implement:**
- WATCHDOG TYPES: price alerts (crypto/stocks), keyword monitor (web page changes), file monitor (notify when file is modified), process monitor (alert if a process crashes), URL uptime monitor (ping every N minutes)
- Natural language setup: "alert me if BTC drops below 80k" → parse target, threshold, direction
- Natural language status: "what am I watching?" → clean formatted table of all active watchdogs
- Edit/delete: "remove the BTC alert" → find by keyword, confirm, delete
- Alert format: "🔔 BTC Alert: Dropped to $78,400 (threshold: $80,000). Action?"

**Files:** Full rewrite of `_WATCHDOG_SYSTEM_PROMPT` in `agents/specialists.py`. Extend `watchdog_manager.py` with more watcher types.

---

## TIER 4 — INFRASTRUCTURE UPGRADES

### 🔧 Upgrade 11: Session Intelligence — Conversation Compression
**Current gap:** `SessionManager.compress_if_needed()` exists but the compression is basic — it just truncates. Long sessions lose critical context.

**Upgrade:** Replace truncation with *intelligent summarization*. When session exceeds 48k tokens:
1. Take the oldest 50% of messages
2. Run a dedicated `SummarizerAgent` LLM call: "Summarize these turns into a compact context block preserving: active tasks, key decisions, file paths, agent actions taken"
3. Replace the old messages with a single `[COMPRESSED CONTEXT]` block
4. Preserve the last 20 turns verbatim for recency

**Files:** Modify `session_manager.py`. Add a `_compress_smart()` method.

---

### 🔧 Upgrade 12: HiveMind — Progress Streaming
**Current gap:** When HiveMind delegates a long task (deep research, report generation), the user sees nothing for 30-60 seconds then gets the full response. No feedback.

**Upgrade:** Add a `progress_queue` to HiveMind. While a drone is running, push progress events every ~5 seconds: "WebAgent: searching... (3/8 sources found)", "ContentAgent: writing section 2/5...". The GUI/Telegram interface polls this queue and shows live status updates.

**Files:** Modify `agents/hive.py` to add progress callbacks. Modify `gui.py` and `telegram_bot.py` to show progress indicators.

---

### 🔧 Upgrade 13: Supervisor — Confidence Scoring
**Current gap:** The Supervisor routes to agents but never expresses *confidence*. If it's 60% sure WebAgent is right vs FileAgent, it just picks one silently.

**Upgrade:** Add `confidence` field to routing JSON output: `{"agents": ["WebAgent"], "parallel": false, "confidence": 0.72, "reasoning": "..."}`. When confidence < 0.65, the Orchestrator activates *dual routing*: run both the primary and the fallback agent, then synthesize. This eliminates wrong-agent errors on ambiguous requests.

**Files:** Modify `agents/supervisor.py` system prompt to output confidence. Modify `agents/orchestrator.py` to read it and activate dual routing below threshold.

---

### 🔧 Upgrade 14: Memory — Semantic Deduplication
**Current gap:** ChromaDB memory grows unbounded. After months of use, `recall('music preferences')` returns 50 entries — most are duplicates or contradictions ("Krish likes lofi" appears 30 times).

**Upgrade:** Before every `remember()` call, check if a semantically similar memory already exists (cosine similarity > 0.85). If yes, *update* the existing entry instead of appending. Add a `memory_consolidate` command that runs during DreamAgent idle time: merge duplicates, resolve contradictions ("Krish likes lofi" × 30 → single entry with recency timestamp).

**Files:** Modify `memory.py`. Add `deduplicate()` and `consolidate()` methods. Add `memory_consolidate` tool to engine.py.

---

## Implementation Order

| Priority | Upgrade | Effort | Impact |
|---|---|---|---|
| 🔴 **1** | Upgrade 2: Wire FeedbackEngine → Supervisor | 10 lines | Immediate self-improvement |
| 🔴 **2** | Upgrade 9: git_op in CodeAgent + Git Context | 20 lines | Daily dev use |
| 🔴 **3** | Upgrade 10: WatchdogAgent full prompt | 1 hour | Complete a stub agent |
| 🟠 **4** | Upgrade 1: ContextAgent | 2 hours | Fixes "finish that" failures |
| 🟠 **5** | Upgrade 7: WebAgent research memory + citations | 30 min prompt | Better research output |
| 🟠 **6** | Upgrade 8: SystemAgent health dashboard | 1 hour | Proactive health monitoring |
| 🟡 **7** | Upgrade 5: TaskAgent | 3 hours | Brand new capability |
| 🟡 **8** | Upgrade 4: NavigatorAgent | 3 hours | Brand new capability |
| 🟡 **9** | Upgrade 13: Supervisor confidence scoring | 2 hours | Eliminates wrong-agent misroutes |
| 🟡 **10** | Upgrade 14: Memory deduplication | 2 hours | Memory health |
| 🔵 **11** | Upgrade 3: DreamAgent proactive suggestions | 2 hours | Ambient intelligence |
| 🔵 **12** | Upgrade 6: ReportAgent | 4 hours | Premium feature |
| 🔵 **13** | Upgrade 11: Session compression intelligence | 2 hours | Long-session stability |
| 🔵 **14** | Upgrade 12: HiveMind progress streaming | 3 hours | UX polish |

---

**Start with 1, 2, 3** — they're tiny code changes with immediate visible impact. Then 4 and 5 which fix the most common daily friction. Then the new agents. Everything here is net-new — nothing overlaps with what's already been done.