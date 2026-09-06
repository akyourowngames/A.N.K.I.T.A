"""PLAN-GOALS — Proactive goal engine (Tier 3).

Goals with LLM auto-decomposed steps, staggered micro-deadlines, progress
derived from steps, proactive web research. Mirrors briefing.py /
reflection.py style: LLM first, heuristic fallback so the system never
blocks (graceful degradation convention).
"""

from __future__ import annotations

import json
import time

from . import db as _db

STATUSES = ("active", "paused", "done", "failed", "archived")
STEP_STATUSES = ("todo", "in_progress", "done", "skipped")

_DECOMPOSE_PROMPT = """Break this goal into actionable steps. Return JSON only.

GOAL: {title}
DESCRIPTION: {desc}
DEADLINE: {deadline}

Return: {{"steps": [{{"title": "..", "why": "..", "effort_days": <number>}}],
"risks": [".."], "first_action": ".."}}
Rules: 3-7 concrete steps in dependency order; effort_days = rough working days each;
first_action = the single smallest thing to do this week."""


def ensure_schema(con) -> None:
    _db.ensure_tier3(con)


def _now() -> float:
    return time.time()


def _details(con, goal_id: int) -> dict:
    try:
        row = con.execute("SELECT details FROM goals WHERE id=?", (goal_id,)).fetchone()
        return json.loads(row["details"] or "{}") if row else {}
    except Exception:
        return {}


def _save_details(con, goal_id: int, details: dict) -> None:
    try:
        con.execute("UPDATE goals SET details=?, updated_at=? WHERE id=?",
                    (json.dumps(details), _now(), goal_id))
    except Exception:
        pass


def create_goal(con, title: str, description: str = "", deadline=None, priority: int = 3,
                source: str = "user", auto_plan: bool = True, use_llm: bool = True) -> dict:
    ensure_schema(con)
    title = (title or "").strip()
    if not title:
        return {"created": False, "reason": "empty title"}
    try:
        priority = max(1, min(5, int(priority or 3)))
    except Exception:
        priority = 3
    try:
        dl = float(deadline) if deadline is not None else None
    except Exception:
        dl = None
    now = _now()
    cur = con.execute(
        "INSERT INTO goals(title, description, status, priority, deadline, progress, source,"
        " created_at, updated_at, details) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (title[:300], (description or "")[:2000], "active", priority, dl, 0.0, source, now, now, "{}"),
    )
    gid = cur.lastrowid
    con.commit()
    steps: list[dict] = []
    first_action = ""
    risks: list[str] = []
    if auto_plan:
        plan = decompose(con, gid, use_llm=use_llm)
        steps = plan.get("steps", [])
        first_action = plan.get("first_action", "")
        risks = plan.get("risks", [])
        if first_action or risks:
            _save_details(con, gid, {"first_action": first_action, "risks": risks})
            con.commit()
    try:
        if str(source) == "user":
            from . import reminders as _rem
            _rem.schedule_goal_kickoff(con, gid)
    except Exception:
        pass
    try:
        if str(source) == "user":
            _research_async(con, gid, use_llm=use_llm)
    except Exception:
        pass
    return {"created": True, "id": gid, "steps": len(steps), "first_action": first_action}


def _research_async(con, goal_id: int, use_llm: bool = True) -> None:
    import os as _os
    import threading as _th

    if _os.getenv("PYTEST_CURRENT_TEST"):
        return

    def _bg():
        own = None
        try:
            own = _db.connect()
            research_goal(own, goal_id, use_llm=use_llm)
        except Exception:
            pass
        finally:
            try:
                if own is not None:
                    own.close()
            except Exception:
                pass

    _th.Thread(target=_bg, daemon=True, name="zumba-goal-research").start()


def heuristic_steps(title: str) -> list[dict]:
    t = (title or "").strip()
    return [
        {"title": f"Define done for: {t}", "why": "a concrete finish line", "effort_days": 1},
        {"title": f"First working pass at: {t}", "why": "momentum over perfection", "effort_days": 5},
        {"title": f"Review and finish: {t}", "why": "close it out", "effort_days": 2},
    ]


def decompose(con, goal_id: int, use_llm: bool = True) -> dict:
    ensure_schema(con)
    row = con.execute("SELECT id, title, description, deadline FROM goals WHERE id=?", (goal_id,)).fetchone()
    if not row:
        return {"steps": [], "risks": [], "first_action": ""}
    steps: list[dict] = []
    risks: list[str] = []
    first_action = ""
    if use_llm:
        try:
            from . import llm as _llm
            dl = ""
            try:
                import datetime as _dt
                dl = _dt.datetime.fromtimestamp(float(row["deadline"])).strftime("%Y-%m-%d") if row["deadline"] else "none"
            except Exception:
                dl = "none"
            out = _llm.chat_json(
                _DECOMPOSE_PROMPT.format(title=row["title"][:300], desc=(row["description"] or "")[:1000], deadline=dl),
                system="You break goals into actionable steps. Valid JSON only.",
                max_tokens=800,
            )
            if isinstance(out, dict):
                for s in (out.get("steps") or [])[:8]:
                    if not isinstance(s, dict) or not str(s.get("title") or "").strip():
                        continue
                    try:
                        eff = max(0.5, float(s.get("effort_days", 2)))
                    except Exception:
                        eff = 2.0
                    steps.append({"title": str(s["title"])[:200], "why": str(s.get("why") or "")[:300], "effort_days": eff})
                risks = [str(r)[:200] for r in (out.get("risks") or []) if str(r).strip()][:5]
                first_action = str(out.get("first_action") or "")[:300]
        except Exception:
            steps = []
    if not steps:
        steps = heuristic_steps(row["title"])
    try:
        con.execute("DELETE FROM goal_steps WHERE goal_id=?", (goal_id,))
    except Exception:
        pass
    try:
        dl = float(row["deadline"]) if row["deadline"] else None
    except Exception:
        dl = None
    total_eff = sum(max(0.5, float(s.get("effort_days", 2))) for s in steps) or 1.0
    now = _now()
    span = max(86400.0, (dl - now)) if dl and dl > now else 14 * 86400.0
    cursor = now
    for i, s in enumerate(steps):
        share = max(0.5, float(s.get("effort_days", 2))) / total_eff
        cursor += span * share
        due = min(cursor, dl) if dl else cursor
        con.execute(
            "INSERT INTO goal_steps(goal_id, step_order, title, status, due_at, notes, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (goal_id, i, s["title"][:200], "todo", due, str(s.get("why") or "")[:300], now, now),
        )
    _recompute(con, goal_id)
    con.commit()
    return {"steps": steps, "risks": risks, "first_action": first_action}


def _recompute(con, goal_id: int) -> float:
    try:
        rows = con.execute("SELECT status FROM goal_steps WHERE goal_id=?", (goal_id,)).fetchall()
    except Exception:
        return 0.0
    total = len(rows)
    if not total:
        prog = 0.0
    else:
        done = sum(1 for r in rows if str(r["status"]) in ("done", "skipped"))
        prog = done / total
    try:
        con.execute("UPDATE goals SET progress=?, updated_at=? WHERE id=?", (prog, _now(), goal_id))
    except Exception:
        pass
    return prog


def get_goal(con, goal_id: int) -> dict | None:
    ensure_schema(con)
    try:
        row = con.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def list_goals(con, status: str = "active") -> list[dict]:
    ensure_schema(con)
    try:
        if status == "all":
            rows = con.execute("SELECT * FROM goals ORDER BY priority ASC, deadline ASC").fetchall()
        else:
            rows = con.execute("SELECT * FROM goals WHERE status=? ORDER BY priority ASC, deadline ASC",
                               (status,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def active_goals(con, limit: int = 10) -> list[dict]:
    return list_goals(con, "active")[:limit]


def goal_steps(con, goal_id: int) -> list[dict]:
    ensure_schema(con)
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM goal_steps WHERE goal_id=? ORDER BY step_order", (goal_id,)).fetchall()]
    except Exception:
        return []


def next_step(con, goal_id: int) -> dict | None:
    try:
        row = con.execute(
            "SELECT * FROM goal_steps WHERE goal_id=? AND status IN ('todo','in_progress')"
            " ORDER BY step_order LIMIT 1", (goal_id,)).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def add_step(con, goal_id: int, title: str, due_at=None) -> dict:
    ensure_schema(con)
    if not get_goal(con, goal_id):
        return {"added": False, "reason": "no such goal"}
    title = (title or "").strip()
    if not title:
        return {"added": False, "reason": "empty title"}
    try:
        order = con.execute("SELECT COALESCE(MAX(step_order),-1)+1 FROM goal_steps WHERE goal_id=?",
                            (goal_id,)).fetchone()[0]
    except Exception:
        order = 0
    now = _now()
    try:
        due = float(due_at) if due_at else None
    except Exception:
        due = None
    cur = con.execute(
        "INSERT INTO goal_steps(goal_id, step_order, title, status, due_at, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (goal_id, int(order or 0), title[:200], "todo", due, now, now),
    )
    _recompute(con, goal_id)
    con.commit()
    return {"added": True, "id": cur.lastrowid}


def complete_step(con, step_id: int) -> dict:
    ensure_schema(con)
    try:
        row = con.execute("SELECT * FROM goal_steps WHERE id=?", (step_id,)).fetchone()
        if not row:
            return {"done": False, "reason": "no such step"}
        now = _now()
        con.execute("UPDATE goal_steps SET status='done', done_at=?, updated_at=? WHERE id=?",
                    (now, now, step_id))
        prog = _recompute(con, int(row["goal_id"]))
        con.commit()
        try:
            _maybe_celebrate(con, int(row["goal_id"]), prog)
        except Exception:
            pass
        return {"done": True, "goal_id": int(row["goal_id"]), "progress": prog}
    except Exception as exc:
        return {"done": False, "reason": str(exc)}


def complete_step_by_order(con, goal_id: int, order: int) -> dict:
    try:
        row = con.execute("SELECT id FROM goal_steps WHERE goal_id=? AND step_order=?",
                          (goal_id, order)).fetchone()
        if not row:
            rows = con.execute("SELECT id FROM goal_steps WHERE goal_id=? ORDER BY step_order",
                               (goal_id,)).fetchall()
            if order < 0 or order >= len(rows):
                return {"done": False, "reason": "no such step"}
            return complete_step(con, rows[order]["id"])
        return complete_step(con, row["id"])
    except Exception as exc:
        return {"done": False, "reason": str(exc)}


def skip_step(con, step_id: int) -> dict:
    ensure_schema(con)
    try:
        row = con.execute("SELECT * FROM goal_steps WHERE id=?", (step_id,)).fetchone()
        if not row:
            return {"done": False, "reason": "no such step"}
        now = _now()
        con.execute("UPDATE goal_steps SET status='skipped', done_at=?, updated_at=? WHERE id=?",
                    (now, now, step_id))
        prog = _recompute(con, int(row["goal_id"]))
        con.commit()
        return {"done": True, "progress": prog}
    except Exception as exc:
        return {"done": False, "reason": str(exc)}


def _maybe_celebrate(con, goal_id: int, progress: float) -> None:
    if progress < 1.0:
        return
    try:
        con.execute("UPDATE goals SET status='done', completed_at=?, updated_at=? WHERE id=? AND status='active'",
                    (_now(), _now(), goal_id))
        con.commit()
    except Exception:
        pass


def update_goal(con, goal_id: int, title=None, description=None, deadline=None, priority=None) -> dict:
    ensure_schema(con)
    g = get_goal(con, goal_id)
    if not g:
        return {"updated": False, "reason": "no such goal"}
    sets, vals = [], []
    if title is not None and str(title).strip():
        sets.append("title=?")
        vals.append(str(title)[:300])
    if description is not None:
        sets.append("description=?")
        vals.append(str(description)[:2000])
    if deadline is not None:
        try:
            sets.append("deadline=?")
            vals.append(float(deadline) if deadline else None)
        except Exception:
            pass
    if priority is not None:
        try:
            sets.append("priority=?")
            vals.append(max(1, min(5, int(priority))))
        except Exception:
            pass
    if not sets:
        return {"updated": False, "reason": "nothing to update"}
    sets.append("updated_at=?")
    vals.append(_now())
    vals.append(goal_id)
    try:
        con.execute(f"UPDATE goals SET {', '.join(sets)} WHERE id=?", vals)
        con.commit()
        return {"updated": True}
    except Exception as exc:
        return {"updated": False, "reason": str(exc)}


def set_status(con, goal_id: int, status: str) -> dict:
    ensure_schema(con)
    if status not in STATUSES:
        return {"updated": False, "reason": f"status must be one of {STATUSES}"}
    try:
        now = _now()
        if status == "done":
            con.execute("UPDATE goals SET status='done', completed_at=?, updated_at=? WHERE id=?",
                        (now, now, goal_id))
        else:
            con.execute("UPDATE goals SET status=?, updated_at=? WHERE id=?", (status, now, goal_id))
        con.commit()
        return {"updated": con.total_changes > 0}
    except Exception as exc:
        return {"updated": False, "reason": str(exc)}


def overdue(con, now: float = 0) -> list[dict]:
    ensure_schema(con)
    now = now or _now()
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM goals WHERE status='active' AND deadline IS NOT NULL AND deadline<?"
            " ORDER BY deadline", (now,)).fetchall()]
    except Exception:
        return []


def stalled(con, days: int = 3, now: float = 0) -> list[dict]:
    ensure_schema(con)
    now = now or _now()
    out = []
    try:
        for g in active_goals(con, limit=50):
            steps = goal_steps(con, g["id"])
            if not steps:
                continue
            acted = max([float(s.get("done_at") or 0) for s in steps] + [float(g.get("created_at") or 0)])
            past_due = any(str(s.get("status")) in ("todo", "in_progress") and s.get("due_at")
                           and float(s["due_at"]) < now for s in steps)
            if past_due or (now - acted) > days * 86400.0:
                out.append(g)
    except Exception:
        pass
    return out


def last_research_at(con, goal_id: int) -> float:
    try:
        row = con.execute("SELECT MAX(created_at) AS ts FROM goal_research WHERE goal_id=?",
                          (goal_id,)).fetchone()
        return float(row["ts"] or 0) if row else 0.0
    except Exception:
        return 0.0


def research_goal(con, goal_id: int, use_llm: bool = True) -> dict:
    ensure_schema(con)
    g = get_goal(con, goal_id)
    if not g:
        return {"researched": False, "reason": "no such goal"}
    steps = goal_steps(con, goal_id)
    queries = [g["title"][:150]]
    for s in steps[:3]:
        queries.append(f"{g['title'][:80]} {s['title'][:80]}")
    queries = queries[:4]
    all_sources: list[dict] = []
    blobs: list[str] = []
    try:
        from tools import websearch as _web
        for q in queries[:3]:
            try:
                res, _note = _web.search(q, backend="auto", limit=4)
            except Exception:
                res = []
            for r in res or []:
                all_sources.append({"title": r.get("title", "")[:150], "url": r.get("url", "")})
                blobs.append(f"- {r.get('title','')}: {r.get('snippet','')[:200]} ({r.get('url','')})")
    except Exception:
        pass
    findings = ""
    if use_llm and blobs:
        try:
            from . import llm as _llm
            out = _llm.chat_text(
                f"Distill this web research for the goal '{g['title'][:150]}' into 5-8 actionable bullets "
                f"(facts + what to do next). Keep under 1200 chars.\n\n" + "\n".join(blobs)[:6000],
                system="You distill research into actionable briefs.",
                max_tokens=800,
            )
            if out:
                findings = out.strip()[:2000]
        except Exception:
            findings = ""
    if not findings:
        findings = "\n".join(blobs[:10])[:2000] or "(no web results)"
    try:
        seen, uniq = set(), []
        for s in all_sources:
            if s.get("url") and s["url"] not in seen:
                seen.add(s["url"])
                uniq.append(s)
        con.execute("INSERT INTO goal_research(goal_id, query, findings, sources, created_at) VALUES(?,?,?,?,?)",
                    (goal_id, queries[0][:300], findings, json.dumps(uniq[:12]), _now()))
        con.commit()
    except Exception:
        pass
    return {"researched": True, "sources": len(all_sources), "findings": findings[:500]}


def goal_context(con, max_chars: int = 1500) -> str:
    goals = active_goals(con, limit=5)
    if not goals:
        return ""
    lines = []
    for g in goals:
        ns = next_step(con, g["id"])
        nxt = f" → next: {ns['title'][:100]}" if ns else " → all steps done"
        dl = ""
        try:
            if g.get("deadline"):
                import datetime as _dt
                dl = f" (due {_dt.datetime.fromtimestamp(float(g['deadline'])).strftime('%Y-%m-%d')})"
        except Exception:
            pass
        lines.append(f"- #{g['id']} {g['title'][:120]} [{int(float(g.get('progress') or 0) * 100)}%]{dl}{nxt}")
    block = "[GOALS — active; weave into conversation naturally]\n" + "\n".join(lines)
    return block[:max_chars]


def render_list(goals: list[dict], con=None) -> str:
    if not goals:
        return "No active goals. Add one: goal add \"Title\" --deadline YYYY-MM-DD"
    lines = []
    for g in goals:
        pct = int(float(g.get("progress") or 0) * 100)
        bar = "#" * (pct // 10) + "-" * (10 - pct // 10)
        dl = ""
        try:
            if g.get("deadline"):
                import datetime as _dt
                dl = f" due {_dt.datetime.fromtimestamp(float(g['deadline'])).strftime('%m-%d')}"
        except Exception:
            pass
        nxt = ""
        if con is not None:
            try:
                ns = next_step(con, g["id"])
                nxt = f" → {ns['title'][:70]}" if ns else " → done"
            except Exception:
                pass
        flag = ""
        try:
            if g.get("deadline") and float(g["deadline"]) < _now() and g.get("status") == "active":
                flag = " OVERDUE"
        except Exception:
            pass
        lines.append(f"#{g['id']} [{bar}] {pct}% P{g.get('priority', 3)}{dl}{flag}\n    {g['title'][:150]}{nxt}")
    return "\n".join(lines)


def render_show(con, goal_id: int) -> str:
    g = get_goal(con, goal_id)
    if not g:
        return f"ERROR: no goal #{goal_id}."
    lines = [f"#{g['id']} {g['title']} [{g['status']}] P{g.get('priority', 3)} {int(float(g.get('progress') or 0)*100)}%"]
    if g.get("description"):
        lines.append(str(g["description"])[:400])
    try:
        det = json.loads(g.get("details") or "{}")
        if det.get("first_action"):
            lines.append(f"First action: {det['first_action']}")
        if det.get("risks"):
            lines.append("Risks: " + "; ".join(det["risks"][:3]))
    except Exception:
        pass
    lines.append("Steps:")
    for s in goal_steps(con, goal_id):
        mark = {"todo": "○", "in_progress": "◐", "done": "✓", "skipped": "–"}.get(s["status"], "○")
        lines.append(f"  {mark} {s['id']}: {s['title'][:120]}")
    try:
        rr = con.execute("SELECT query, findings, created_at FROM goal_research WHERE goal_id=? ORDER BY id DESC LIMIT 2",
                         (goal_id,)).fetchall()
        if rr:
            lines.append("Research:")
            for r in rr:
                lines.append(f"  - {r['query'][:100]}: {(r['findings'] or '')[:200]}")
    except Exception:
        pass
    try:
        rms = con.execute("SELECT id, message, fire_at, status FROM reminders WHERE goal_id=? AND status IN ('pending','snoozed')"
                          " ORDER BY fire_at LIMIT 5", (goal_id,)).fetchall()
        if rms:
            lines.append("Reminders:")
            for r in rms:
                import datetime as _dt
                try:
                    ft = _dt.datetime.fromtimestamp(float(r["fire_at"])).strftime("%m-%d %H:%M")
                except Exception:
                    ft = "?"
                lines.append(f"  - #{r['id']} [{r['status']}] {ft}: {r['message'][:100]}")
    except Exception:
        pass
    return "\n".join(lines)
