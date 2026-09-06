"""PLAN-GOALS: natural-time parsing, reminders lifecycle, proactive tick."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory.db as db


def _con(tmp_path, monkeypatch):
    home = tmp_path / "rhome"
    home.mkdir()
    monkeypatch.setattr(db, "memory_home", lambda: home)
    monkeypatch.setattr(db, "memory_db_path", lambda: home / "memory.db")
    con = db.connect()
    db.ensure_tier3(con)
    return con


def test_parse_natural_cases():
    from memory import reminders as _rem
    base = 1786000000.0
    assert _rem.parse_natural("in 3 days", base=base, use_llm=False) == base + 3 * 86400
    assert _rem.parse_natural("in 2h", base=base, use_llm=False) == base + 7200
    assert _rem.parse_natural("remind me again in 2h", base=base, use_llm=False) == base + 7200
    tmr = _rem.parse_natural("tomorrow 9am", base=base, use_llm=False)
    assert tmr and tmr > base and tmr - base < 3 * 86400
    fri = _rem.parse_natural("friday 5pm", base=base, use_llm=False)
    import datetime as _dt
    assert fri and _dt.datetime.fromtimestamp(fri).weekday() == 4
    assert _rem.parse_natural("blarg zzz qq", base=base, use_llm=False) is None
    assert _rem.detect_recur("gym every day") == "daily"


def test_schedule_fire_snooze_cancel(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import reminders as _rem
    r = _rem.schedule(con, "stretch", "in 2h", use_llm=False)
    assert r["scheduled"]
    assert _rem.due_reminders(con, now=time.time()) == []
    fired = _rem.fire_due(con, now=r["fire_at"] + 1)
    assert len(fired) == 1 and fired[0]["message"] == "stretch"
    r2 = _rem.schedule(con, "water", "in 2h", use_llm=False)
    s = _rem.snooze(con, r2["id"], "remind me again in 2h", use_llm=False)
    assert s["snoozed"]
    assert _rem.cancel(con, r2["id"])["cancelled"]
    con.close()


def test_recurring_rearms(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import reminders as _rem
    r = _rem.schedule(con, "gym", "in 2h", every="daily", use_llm=False)
    assert r.get("recur") == "daily"
    _rem.fire_due(con, now=r["fire_at"] + 1)
    pend = _rem.pending(con)
    assert len(pend) == 1 and pend[0]["id"] != r["id"]
    con.close()


def test_tick_deadline_stall_win_and_ratelimit(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import goals as _g, proactive as _pro
    now = time.time()
    g1 = _g.create_goal(con, "Urgent demo", deadline=now + 24 * 3600, use_llm=False)
    out = _pro.tick(con, use_llm=False, force=True, now=now)
    assert any("DEADLINE" in n for n in out["nudges"])
    _g.complete_step(con, _g.goal_steps(con, g1["id"])[0]["id"])
    g2 = _g.create_goal(con, "Quiet habit", use_llm=False)
    con.execute("UPDATE goal_steps SET due_at=? WHERE goal_id=?", (now - 10, g2["id"]))
    con.execute("UPDATE goals SET created_at=? WHERE id=?", (now - 4 * 86400, g2["id"]))
    con.commit()
    out2 = _pro.tick(con, use_llm=False, force=True, now=now)
    assert any("STALLED" in n or "DEADLINE" in n for n in out2["nudges"])
    for s in _g.goal_steps(con, g1["id"]):
        _g.complete_step(con, s["id"])
    out3 = _pro.tick(con, use_llm=False, force=True, now=now)
    assert any("WIN" in n for n in out3["nudges"])
    monkeypatch.setattr(_pro, "interval_minutes", lambda: 30)
    _pro.tick(con, use_llm=False, force=False, now=now)
    out4 = _pro.tick(con, use_llm=False, force=False, now=now)
    assert out4["nudges"] == []
    con.close()


def test_goal_tools_visible_and_kill_switch_safe(monkeypatch):
    import mcpclient.builtin as _b
    names = [t["function"]["name"] for t in _b.visible_tools()]
    assert any(n.endswith("__goal_add") for n in names)
    assert any(n.endswith("__remind_add") for n in names)
