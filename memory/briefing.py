"""T2.5 — Proactive `zumba daily` briefing.

One composed generation from: open follow-ups, community summaries,
on-this-day episode resurfacing (bi-temporal data finally used read-side),
mood trend, dates extracted from graph. /brief in chat.
Optional --install-reminder registers a Windows Task Scheduler job via shell.
"""

from __future__ import annotations

import datetime as _dt
import time


def on_this_day(con, limit: int = 5) -> list[dict]:
    try:
        rows = con.execute(
            "SELECT id, user_text, assistant_text, created_at FROM episodes ORDER BY created_at DESC LIMIT 500").fetchall()
    except Exception:
        return []
    today = _dt.datetime.now()
    out = []
    for r in rows:
        try:
            d = _dt.datetime.fromtimestamp(float(r["created_at"]))
        except Exception:
            continue
        if d.year == today.year:
            continue
        if (d.month, d.day) == (today.month, today.day):
            out.append(dict(r))
            if len(out) >= limit:
                break
    return out


def community_digest(con, limit: int = 3) -> list[str]:
    try:
        rows = con.execute("SELECT summary FROM communities WHERE summary!='' ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [r["summary"][:400] for r in rows if r["summary"]]
    except Exception:
        return []


def date_lines(con, limit: int = 8) -> list[str]:
    try:
        rows = con.execute(
            """SELECT fact FROM relations WHERE invalid_at IS NULL AND
               (fact LIKE '%20__%' OR fact LIKE '%Jan%' OR fact LIKE '%Feb%' OR fact LIKE '%Mar%' OR
                fact LIKE '%Apr%' OR fact LIKE '%May%' OR fact LIKE '%Jun%' OR fact LIKE '%Jul%' OR
                fact LIKE '%Aug%' OR fact LIKE '%Sep%' OR fact LIKE '%Oct%' OR fact LIKE '%Nov%' OR
                fact LIKE '%Dec%' OR fact LIKE '%deadline%' OR fact LIKE '%expires%' OR fact LIKE '%due%')
               ORDER BY created_at DESC LIMIT ?""", (limit,)).fetchall()
        return [r["fact"][:200] for r in rows]
    except Exception:
        return []


def compose_daily(con, use_llm: bool = True) -> str:
    from . import reflection as _ref, mood as _mood
    followups = _ref.open_follow_ups(con, limit=10)
    communities = community_digest(con)
    otd = on_this_day(con)
    mood_ctx = _mood.mood_context(con)
    dates = date_lines(con)
    parts = []
    if followups:
        parts.append("OPEN FOLLOW-UPS:\n" + "\n".join(f"- {f['text'][:200]}" for f in followups))
    else:
        parts.append("OPEN FOLLOW-UPS:\n- (none)")
    if communities:
        parts.append("COMMUNITIES:\n" + "\n".join(f"- {c[:300]}" for c in communities))
    if otd:
        bits = []
        for e in otd:
            try:
                yr = _dt.datetime.fromtimestamp(float(e["created_at"])).year
            except Exception:
                yr = "?"
            bits.append(f"- [{yr}] U: {(e['user_text'] or '')[:160]}")
        parts.append("ON THIS DAY:\n" + "\n".join(bits))
    if mood_ctx:
        parts.append("MOOD:\n- " + mood_ctx)
    if dates:
        parts.append("DATES:\n" + "\n".join(f"- {d}" for d in dates))
    raw = "\n\n".join(parts) or "(nothing to brief yet)"
    if use_llm:
        try:
            from . import llm as _llm
            out = _llm.chat_text(
                "Write a short morning briefing (bullets, warm, actionable) from this memory digest. "
                "Lead with follow-ups, then dates, then memory resurfaces. Keep under 1200 chars.\n\n" + raw[:6000],
                system="You write concise daily briefings.",
                max_tokens=800,
            )
            if out:
                return out.strip()
        except Exception:
            pass
    head = f"DAILY BRIEF · {_dt.datetime.now().strftime('%Y-%m-%d')}\n\n"
    return head + raw


def install_reminder(task_name: str = "ZumbaDaily", time_hhmm: str = "08:00") -> dict:
    try:
        import shelltool
        if not shelltool.enabled():
            return {"ok": False, "reason": "shell disabled"}
        hh, mm = (time_hhmm.split(":") + ["00"])[:2]
        cmd = (
            f"$a = 'python \"{__import__('pathlib').Path(__file__).resolve().parent.parent / 'main.py'}\" daily'; "
            f"schtasks /Create /TN {task_name} /TR \"$a\" /SC DAILY /ST {int(hh):02d}:{int(mm):02d} /F"
        )
        res = shelltool.run(f"schtasks /Create /TN {task_name} /TR \"python main.py daily\" /SC DAILY /ST {int(hh):02d}:{int(mm):02d} /F")
        _ = cmd
        return {"ok": res.get("exit_code") == 0, "output": (res.get("stdout") or res.get("stderr") or "")[:500]}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
