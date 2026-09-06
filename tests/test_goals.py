"""PLAN-GOALS: schema, CRUD, decomposition, progress, research, promotion."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory.db as db


def _con(tmp_path, monkeypatch):
    home = tmp_path / "ghome"
    home.mkdir()
    monkeypatch.setattr(db, "memory_home", lambda: home)
    monkeypatch.setattr(db, "memory_db_path", lambda: home / "memory.db")
    con = db.connect()
    db.ensure_tier3(con)
    return con


def test_schema_upgrade_in_place(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"goals", "goal_steps", "reminders", "goal_research"} <= tables
    con.close()


def test_create_goal_heuristic_steps_no_llm(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import goals as _g
    r = _g.create_goal(con, "Pass IELTS 7.5", deadline=time.time() + 30 * 86400,
                       priority=1, use_llm=False)
    assert r["created"] and r["steps"] == 3
    steps = _g.goal_steps(con, r["id"])
    assert len(steps) == 3 and all(s["due_at"] for s in steps)
    dues = [s["due_at"] for s in steps]
    assert dues == sorted(dues)
    g = _g.get_goal(con, r["id"])
    assert g["priority"] == 1 and g["status"] == "active" and g["progress"] == 0.0
    con.close()


def test_decompose_mocked_llm(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import goals as _g
    import memory.llm as _llm
    monkeypatch.setattr(_llm, "chat_json", lambda *a, **k: {
        "steps": [{"title": "Mock test", "why": "baseline", "effort_days": 1},
                  {"title": "Practice daily", "why": "reps", "effort_days": 10}],
        "risks": ["time"], "first_action": "book mock"})
    r = _g.create_goal(con, "Learn guitar", deadline=time.time() + 20 * 86400, use_llm=True)
    assert r["steps"] == 2 and r["first_action"] == "book mock"
    assert any("Mock test" in s["title"] for s in _g.goal_steps(con, r["id"]))
    con.close()


def test_progress_counts_skipped(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import goals as _g
    r = _g.create_goal(con, "Tidy room", use_llm=False)
    steps = _g.goal_steps(con, r["id"])
    _g.complete_step(con, steps[0]["id"])
    _g.skip_step(con, steps[1]["id"])
    g = _g.get_goal(con, r["id"])
    assert abs(float(g["progress"]) - 2 / 3) < 0.01
    _g.complete_step(con, steps[2]["id"])
    assert _g.get_goal(con, r["id"])["status"] == "done"
    con.close()


def test_overdue_and_stalled(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import goals as _g
    now = time.time()
    r = _g.create_goal(con, "Old task", deadline=now - 100, use_llm=False)
    assert any(g["id"] == r["id"] for g in _g.overdue(con, now=now))
    r2 = _g.create_goal(con, "Quiet task", use_llm=False)
    con.execute("UPDATE goal_steps SET due_at=? WHERE goal_id=?", (now - 10, r2["id"]))
    old = now - 4 * 86400
    con.execute("UPDATE goals SET created_at=? WHERE id=?", (old, r2["id"]))
    con.commit()
    assert any(g["id"] == r2["id"] for g in _g.stalled(con, days=3, now=now))
    con.close()


def test_research_mocked_websearch(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import goals as _g
    import tools.websearch as _web
    monkeypatch.setattr(_web, "search", lambda *a, **k: (
        [{"title": "IELTS guide", "url": "https://ielts.example/g", "snippet": "practice daily"}], ""))
    import memory.llm as _llm
    monkeypatch.setattr(_llm, "chat_text", lambda *a, **k: "Do mocks weekly. Practice daily.")
    r = _g.create_goal(con, "Pass IELTS", use_llm=False)
    out = _g.research_goal(con, r["id"], use_llm=True)
    assert out["researched"] and "mocks" in out["findings"].lower()
    assert con.execute("SELECT COUNT(*) FROM goal_research WHERE goal_id=?", (r["id"],)).fetchone()[0] == 1
    con.close()


def test_reflection_promotes_goal(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import reflection as _ref
    monkeypatch.setattr("memory.llm.chat_json", lambda *a, **k: {"goals": ["Pass IELTS 7.5 by December"]} if "CANDIDATES" in str(a[0] if a else "") else {"decisions": [], "follow_ups": ["Pass IELTS 7.5 by December"], "importance": [], "mood": {"valence": 0.0, "energy": 0.5, "note": "ok"}})
    out = _ref.reflect_session(con, [{"user": "I want to pass IELTS 7.5 by December",
                                      "assistant": "Noted", "episode_id": None}],
                               session_id="s-g", use_llm=True)
    assert out["applied"].get("goals_proposed", 0) >= 1
    from memory import goals as _g
    assert any("IELTS" in g["title"] for g in _g.list_goals(con, "active"))
    assert "hello there friend" not in " ".join(g["title"] for g in _g.list_goals(con, "active"))
    con.close()


def test_briefing_digest_and_recall_context(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import briefing as _br, goals as _g
    _g.create_goal(con, "Ship demo", deadline=time.time() + 2 * 86400, use_llm=False)
    assert "Ship demo" in _br.goals_digest(con)
    assert "Ship demo" in _br.compose_daily(con, use_llm=False)
    assert "Ship demo" in _g.goal_context(con)
    from memory.service import Memory
    m = Memory(con=con)
    monkeypatch.setattr("memory.service.retrieval.search", lambda con, q, top_k=8, max_bytes=6000, **kw: [])
    text, _ = m.recall_with_hits("anything")
    assert "Ship demo" in text
    con.close()
