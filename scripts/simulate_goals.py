"""PLAN-GOALS end-to-end simulation (plan §timeline, compressed).

Stages: create -> kickoff -> step done -> stall nudge -> pre-research ->
win. Uses an isolated temp DB, mocked LLM + websearch (deterministic),
real CRUD/reminder/proactive code paths. Asserts every stage.
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

tmp = Path(tempfile.mkdtemp(prefix="goals-sim-"))

import memory.db as db

db.memory_home = lambda: tmp
db.memory_db_path = lambda: tmp / "memory.db"

from memory import goals as G
from memory import proactive as P
from memory import reminders as R

con = db.connect()
db.ensure_tier3(con)

import memory.llm as LLM

LLM.chat_json = lambda *a, **k: {
    "steps": [{"title": "Diagnostic mock test", "why": "baseline", "effort_days": 1},
              {"title": "Daily listening practice", "why": "weak point", "effort_days": 40},
              {"title": "Weekly full mock + review", "why": "exam fitness", "effort_days": 8}],
    "risks": ["Listening section is the weak point"],
    "first_action": "Book the diagnostic test this week"}
LLM.chat_text = lambda *a, **k: "New listening format released. Do a mock now."

import tools.websearch as WEB

WEB.search = lambda *a, **k: (
    [{"title": "Official IELTS practice update", "url": "https://ielts.example/new",
      "snippet": "new listening format"}], "")

NOW = time.time()
ok = []


def stage(name, cond, detail=""):
    assert cond, f"SIM FAIL at {name}: {detail}"
    ok.append(name)
    print(f"  [ok] {name}" + (f" — {detail}" if detail else ""))


print("GOALS SIMULATION (isolated DB: %s)" % tmp)

# 1. Today 7pm — goal created, LLM decomposes, micro-deadlines stagger.
r = G.create_goal(con, "Pass IELTS 7.5", deadline=NOW + 30 * 86400, priority=1, use_llm=True)
gid = r["id"]
steps = G.goal_steps(con, gid)
stage("1.create+decompose", r["created"] and len(steps) == 3, f"#{gid} {len(steps)} steps")
stage("1.micro-deadlines", all(s["due_at"] for s in steps) and
      [s["due_at"] for s in steps] == sorted(s["due_at"] for s in steps))
stage("1.first-action", "diagnostic" in (G.get_goal(con, gid)["details"] or "").lower())

# 2. Tonight 8pm — kickoff reminder exists for the first step.
pend = R.pending(con)
stage("2.kickoff-reminder", any(p.get("goal_id") == gid for p in pend),
      f"{len(pend)} pending")
first_due = steps[0]["due_at"]
fired = R.fire_due(con, now=first_due + 1)
stage("2.kickoff-fires", any(f.get("goal_id") == gid for f in fired))

# 3. Saturday — step 1 done, progress jumps.
G.complete_step(con, steps[0]["id"])
g = G.get_goal(con, gid)
stage("3.progress", abs(float(g["progress"]) - 1 / 3) < 0.01, f"{int(float(g['progress'])*100)}%")

# 4. Quiet 4 days — stall check-in (deadline watchdog quiet: 30d out).
old = NOW - 4 * 86400
con.execute("UPDATE goals SET created_at=? WHERE id=?", (old, gid))
con.execute("UPDATE goal_steps SET due_at=? WHERE goal_id=? AND status!='done'",
            (NOW + 20 * 86400, gid))
con.execute("UPDATE goal_steps SET done_at=? WHERE goal_id=? AND status='done'", (old, gid))
con.commit()
out = P.tick(con, use_llm=False, force=True, now=NOW)
stage("4.stall-nudge", any("STALLED" in n for n in out["nudges"]), str(out["nudges"]))

# 5. 3 days to deadline, research stale — pre-research runs unprompted.
con.execute("UPDATE goals SET deadline=? WHERE id=?", (NOW + 3 * 86400, gid))
con.execute("DELETE FROM goal_research WHERE goal_id=?", (gid,))
con.commit()
out = P.tick(con, use_llm=True, force=True, now=NOW)
stage("5.pre-research", any("RESEARCHED" in n for n in out["nudges"]),
      str(out["nudges"]))
assert con.execute("SELECT COUNT(*) FROM goal_research WHERE goal_id=?",
                   (gid,)).fetchone()[0] >= 1

# 6. All steps done — win + archive prompt.
for s in G.goal_steps(con, gid):
    if s["status"] != "done":
        G.complete_step(con, s["id"])
out = P.tick(con, use_llm=False, force=True, now=NOW)
stage("6.win", any("WIN" in n for n in out["nudges"]), str(out["nudges"]))
stage("6.status-done", G.get_goal(con, gid)["status"] == "done")

# Recall + briefing surfaces know the goal (use a fresh active goal).
r2 = G.create_goal(con, "Ship portfolio site", use_llm=False)
assert "Ship portfolio" in G.goal_context(con)
from memory import briefing as BR
assert "Ship portfolio" in BR.goals_digest(con)
stage("7.surfaces", True, "recall context + daily digest")

con.close()
print(f"\nSIMULATION GREEN — {len(ok)} stages: " + ", ".join(ok))
