"""PLAN-GOALS — Proactive autonomous worker.

Cheap SQL checks on a timer; LLM passes only when triggered. Runs as a
daemon thread beside the memory worker while chat is open, plus one-shot
via `zumba goal tick` (scheduled like the daily brief).

Rate limit: at most one proactive nudge per N minutes (meta key
`proactive_last_nudge`; `proactive_minutes` config, `proactive off` switch).
Nudges also return system-message text so the LLM weaves them in naturally.
"""

from __future__ import annotations

import threading
import time

from . import db as _db

_thread: threading.Thread | None = None
_lock = threading.Lock()
_stop = threading.Event()


def enabled(con=None) -> bool:
    try:
        from core.store import config_get
        if str(config_get("proactive", "on")).strip().lower() in ("off", "0", "no"):
            return False
    except Exception:
        pass
    return True


def interval_minutes() -> int:
    try:
        from core.store import config_get
        return max(1, min(120, int(config_get("proactive_minutes", "30") or 30)))
    except Exception:
        return 30


def _last_nudge(con) -> float:
    try:
        return float(_db.get_meta(con, "proactive_last_nudge", "0") or 0)
    except Exception:
        return 0.0


def _mark_nudge(con, now: float) -> None:
    try:
        _db.set_meta(con, "proactive_last_nudge", str(now))
        con.commit()
    except Exception:
        pass


def _rate_ok(con, now: float) -> bool:
    try:
        return (now - _last_nudge(con)) >= interval_minutes() * 60
    except Exception:
        return True


def tick(con, use_llm: bool = True, force: bool = False, now: float = 0) -> dict:
    """One proactive pass. Returns {fired, nudges[], system_note}."""
    _db.ensure_tier3(con)
    now = now or time.time()
    out: dict = {"fired": [], "nudges": [], "system_note": ""}
    try:
        from . import reminders as _rem
        out["fired"] = _rem.fire_due(con, now=now, deliver=True)
    except Exception:
        out["fired"] = []
    if not enabled(con):
        return out
    nudges: list[str] = []
    try:
        from . import goals as _g
        for g in _g.overdue(con, now=now):
            if float(g.get("progress") or 0) >= 1.0:
                continue
            ns = _g.next_step(con, g["id"])
            nxt = f" Next step: {ns['title'][:120]}." if ns else ""
            nudges.append(f"OVERDUE: '{g['title'][:100]}' ({int(float(g.get('progress') or 0)*100)}%).{nxt}")
            break
        if not nudges:
            for g in _g.active_goals(con, limit=20):
                try:
                    dl = float(g.get("deadline") or 0)
                except Exception:
                    dl = 0.0
                if dl and 0 < dl - now <= 48 * 3600 and float(g.get("progress") or 0) < 0.5:
                    ns = _g.next_step(con, g["id"])
                    nxt = f" Suggested next step: {ns['title'][:120]}." if ns else ""
                    nudges.append(f"DEADLINE: '{g['title'][:100]}' due within 48h at"
                                  f" {int(float(g.get('progress') or 0)*100)}%.{nxt}")
                    break
        if not nudges:
            for g in _g.stalled(con, days=3, now=now):
                nudges.append(f"STALLED: '{g['title'][:100]}' quiet 3+ days. Offer to re-plan or shrink it.")
                break
        try:
            for g in _g.active_goals(con, limit=20):
                try:
                    dl = float(g.get("deadline") or 0)
                except Exception:
                    dl = 0.0
                if dl and 0 < dl - now <= 7 * 86400 and (now - _g.last_research_at(con, g["id"])) > 5 * 86400:
                    r = _g.research_goal(con, g["id"], use_llm=use_llm)
                    if r.get("researched"):
                        nudges.append(f"RESEARCHED: fresh findings for '{g['title'][:100]}'")
                    break
        except Exception:
            pass
        try:
            for g in _g.list_goals(con, "all"):
                done_recent = str(g.get("status")) == "done" and (now - float(g.get("completed_at") or 0)) < 7 * 86400
                if float(g.get("progress") or 0) >= 1.0 or done_recent:
                    nudges.append(f"WIN: '{g['title'][:100]}' hit 100% — celebrate + archive?")
                    break
                try:
                    dl = float(g.get("deadline") or 0)
                except Exception:
                    dl = 0.0
                if dl and now - dl > 7 * 86400 and float(g.get("progress") or 0) <= 0:
                    nudges.append(f"ABANDONED?: '{g['title'][:100]}' past deadline 7d at 0% — fail or reschedule?")
                    break
        except Exception:
            pass
    except Exception:
        pass
    if nudges and (force or _rate_ok(con, now)):
        if not force:
            _mark_nudge(con, now)
        out["nudges"] = nudges[:2]
        out["system_note"] = ("[PROACTIVE — weave in naturally, do not dump verbatim]\n" + "\n".join(nudges[:2]))[:1200]
    return out


def start(con_factory=None, period_s: float = 300.0) -> None:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()

        def _loop():
            while not _stop.wait(period_s):
                try:
                    if con_factory is not None:
                        con = con_factory()
                    else:
                        con = _db.connect()
                    try:
                        tick(con, use_llm=True)
                    finally:
                        try:
                            con.close()
                        except Exception:
                            pass
                except Exception:
                    pass

        _thread = threading.Thread(target=_loop, daemon=True, name="zumba-proactive")
        _thread.start()


def stop() -> None:
    _stop.set()
