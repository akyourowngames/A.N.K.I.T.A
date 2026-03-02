Got it. Here's the plan:

---

## 🧠 ANKITA Self-Improvement Engine

### Core Idea
ANKITA keeps a **living memory of what worked and what didn't.** Every task she runs gets logged. Every failure gets analyzed. Every success becomes a pattern. Over time she gets smarter on your specific machine, your specific habits, your specific failures — not just generic AI knowledge.

---

### Three Components

**1. Attempt Logger**
Every single task ANKITA runs gets written to `.ankita/feedback/attempts.jsonl`. Each entry captures: the task text, which agent handled it, what tools were called, whether it succeeded or failed, the error message if it failed, and a timestamp. This is the raw data everything else learns from. Zero filtering — log everything.

**2. Rating System**
After every response, you can say `good` / `bad` / `rate 4/5` in chat — or there's a thumbs up/down button in the GUI. That rating gets attached to the attempt log entry. Auto-detection also runs in parallel: if ANKITA's reply contains phrases like "I couldn't", "failed", "error", "I wasn't able to" — it's automatically flagged as a failure without you doing anything.

**3. Pattern Learner**
A background job (runs on DreamAgent idle cycle) reads the last 50 attempts, finds patterns — "FileAgent fails on this machine when using relative paths", "CodeAgent succeeds when it reads the error before retrying", "user always says X and means Y" — and writes them to `patterns.json` as named rules with confidence scores.

---

### How It Actually Makes ANKITA Smarter

**Before routing** — Supervisor reads `patterns.json` and injects the top 3 relevant patterns as context into the agent's system prompt. Agent knows what worked before before it even starts.

**Before executing** — if a similar task failed before, agent gets a warning: "Last time you tried this, X failed because Y. Try Z instead."

**After failing** — Hydra Protocol now also writes to the failure log with the error + what the backup agent did differently. Over time ANKITA builds a machine-specific failure map.

**After you rate bad** — triggers an immediate re-analysis of that task. ANKITA figures out what she should have done differently and writes it as a pattern with high confidence so she never repeats it.

---

### Data Structure

```
.ankita/feedback/
├── attempts.jsonl      ← every task, auto-logged, append-only
├── ratings.jsonl       ← your manual good/bad ratings
├── patterns.json       ← learned rules with confidence scores
└── failure_map.json    ← specific errors → specific fixes
```

**Pattern example:**
```json
{
  "id": "p_001",
  "trigger": "open file notepad",
  "rule": "use full absolute path not relative",
  "confidence": 0.92,
  "learned_from": 7,
  "agent": "FileAgent"
}
```

---

### Integration Points — exactly where it plugs in

**`orchestrator.py`** — after Supervisor routes, before agent runs: inject relevant patterns + failure warnings into agent system prompt. 4 lines added.

**`agent_runtime.py`** — after `run_turn()` completes: call `FeedbackEngine.log_attempt()`. 3 lines added.

**`proactive.py` / `dream_agent.py`** — DreamAgent idle cycle now also runs `FeedbackEngine.analyze_recent()` to extract patterns from last 50 attempts. Existing hook, zero new threads.

**`gui.py`** — add 👍 👎 buttons below every ANKITA response. On click: `FeedbackEngine.log_rating()`. 20 lines.

**`chat.py`** — detect "good" / "bad" / "that was wrong" as rating commands before routing to agent. 10 lines.

**`supervisor.py`** — before making routing decision, read `patterns.json` top patterns and inject as context. 5 lines.

---

### What You'll Actually See

Day 1 — ANKITA starts logging silently. You notice nothing.

Day 3 — she's made 200+ attempts. DreamAgent synthesizes first patterns. She starts avoiding the mistakes she made on day 1.

Day 7 — you say "open my project" and she already knows you mean VS Code + your specific folder because she's seen you do it 12 times and it's a high-confidence pattern now.

Day 30 — she's a completely different assistant than day 1. Tuned entirely to you, your machine, your workflow. That's Jarvis.

---

### Confidence Score System

Every pattern starts at 0.5. Each time it leads to a success → +0.1. Each failure → -0.2. Below 0.2 → pattern deleted. Above 0.9 → promoted to "core rule" injected every single time regardless of task similarity.

---

### What Coder Claude needs to build

5 files total. `feedback_engine.py` is the only new standalone file. Everything else is 3-10 line additions to existing files. Zero new dependencies — pure Python, `json`, `pathlib`, keyword matching. No vector DB, no ML, no overhead.

---

Paste this to Coder Claude. It has everything it needs.