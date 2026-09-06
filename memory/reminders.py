"""PLAN-GOALS — Reminder engine.

Natural-time parsing (regex-first, LLM fallback), due firing, snooze,
recurring re-arm, Windows desktop toast via a PowerShell one-liner
([Windows.UI.Notifications], no new dependency). No new services.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import time

from . import db as _db

RECUR = ("daily", "weekly")


def ensure_schema(con) -> None:
    _db.ensure_tier3(con)


def _now() -> float:
    return time.time()


def parse_natural(text: str, base: float = 0, use_llm: bool = True) -> float | None:
    """Parse 'tomorrow 9am', 'in 3 days', 'friday 5pm', 'in 2h' -> epoch.

    Regex-first (no dependency); LLM fallback via chat_json when regex fails.
    Returns None when unparseable.
    """
    base = base or _now()
    t = f" {(text or '').strip().lower()} "
    if not t.strip():
        return None
    now = _dt.datetime.fromtimestamp(base)
    m = re.search(r"\bin\s+(\d+)\s*(h|hr|hrs|hour|hours)\b", t)
    if m:
        return base + int(m.group(1)) * 3600
    m = re.search(r"\bin\s+(\d+)\s*(m|min|mins|minute|minutes)\b", t)
    if m:
        return base + int(m.group(1)) * 60
    m = re.search(r"\bin\s+(\d+)\s*(d|day|days|w|week|weeks)\b", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        return base + n * (7 * 86400 if unit.startswith("w") else 86400)
    m = re.search(r"\btomorrow(?:\s+at)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", t)
    if m:
        hh, mm, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "")
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        return _dt.datetime(now.year, now.month, now.day, hh % 24, mm % 60).timestamp() + 86400
    m = re.search(r"\btoday(?:\s+at)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", t)
    if m:
        hh, mm, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "")
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        ts = _dt.datetime(now.year, now.month, now.day, hh % 24, mm % 60).timestamp()
        return ts if ts > base else ts + 86400
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, name in enumerate(days):
        m = re.search(rf"\b{name}(?:\s+at)?\s*(\d{{1,2}})?(?::(\d{{2}}))?\s*(am|pm)?\b", t)
        if m:
            hh = int(m.group(1) or 9)
            mm = int(m.group(2) or 0)
            ap = (m.group(3) or "")
            if ap == "pm" and hh < 12:
                hh += 12
            if ap == "am" and hh == 12:
                hh = 0
            delta = (i - now.weekday()) % 7
            day = now + _dt.timedelta(days=delta)
            ts = _dt.datetime(day.year, day.month, day.day, hh % 24, mm % 60).timestamp()
            if delta == 0 and ts <= base:
                ts += 7 * 86400
            return ts
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if m:
        hh, mm, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        ts = _dt.datetime(now.year, now.month, now.day, hh % 24, mm % 60).timestamp()
        return ts if ts > base else ts + 86400
    if use_llm:
        try:
            from . import llm as _llm
            out = _llm.chat_json(
                f'Now (epoch {int(base)} = {now.strftime("%Y-%m-%d %H:%M %A")}). Parse this reminder time to an epoch timestamp. '
                f'Expression: "{text[:200]}". Return JSON: {{"epoch": <number or null>}}',
                system="You parse reminder times. Valid JSON only.",
                max_tokens=150,
            )
            if isinstance(out, dict) and out.get("epoch"):
                return float(out["epoch"])
        except Exception:
            pass
    return None


def detect_recur(text: str, every: str = "") -> str:
    t = f" {(every or '')} {(text or '')} ".lower()
    if "daily" in t or "every day" in t:
        return "daily"
    if "weekly" in t or "every week" in t:
        return "weekly"
    return ""


def schedule(con, message: str, when_expr: str, goal_id=None, step_id=None,
             channel: str = "chat", every: str = "", fire_at: float = 0,
             use_llm: bool = True) -> dict:
    ensure_schema(con)
    message = (message or "").strip()
    if not message:
        return {"scheduled": False, "reason": "empty message"}
    ts = float(fire_at) if fire_at else 0.0
    if not ts:
        ts = parse_natural(when_expr or "", use_llm=use_llm) or 0.0
    if not ts or ts <= _now() - 60:
        if ts and ts <= _now() - 60:
            return {"scheduled": False, "reason": "time is in the past"}
        return {"scheduled": False, "reason": f"could not parse time: '{when_expr}'"}
    recur = detect_recur(f"{message} {when_expr}", every)
    now = _now()
    cur = con.execute(
        "INSERT INTO reminders(goal_id, step_id, fire_at, message, channel, status, created_at)"
        " VALUES(?,?,?,?,?,'pending',?)",
        (goal_id, step_id, ts, message[:500], channel or "chat", now),
    )
    rid = cur.lastrowid
    if recur:
        try:
            con.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"recur:{rid}", recur),
            )
        except Exception:
            pass
    con.commit()
    return {"scheduled": True, "id": rid, "fire_at": ts, "recur": recur}


def schedule_natural(con, text: str, when_expr: str, goal_id=None, use_llm: bool = True) -> dict:
    return schedule(con, text, when_expr, goal_id=goal_id, use_llm=use_llm)


def schedule_goal_kickoff(con, goal_id: int) -> dict:
    try:
        from . import goals as _g
        ns = _g.next_step(con, goal_id)
        g = _g.get_goal(con, goal_id)
        if not ns or not g:
            return {"scheduled": False}
        first_due = float(ns.get("due_at") or 0)
        msg = f"Goal kickoff: {ns.get('title','')[:120]} (goal: {g.get('title','')[:80]})"
        if first_due and first_due > _now():
            return schedule(con, msg, "", goal_id=goal_id, step_id=ns.get("id"), fire_at=first_due,
                            use_llm=False)
        return schedule(con, msg, "in 2 days", goal_id=goal_id, step_id=ns.get("id"), use_llm=False)
    except Exception as exc:
        return {"scheduled": False, "reason": str(exc)}


def due_reminders(con, now: float = 0) -> list[dict]:
    ensure_schema(con)
    now = now or _now()
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM reminders WHERE status IN ('pending','snoozed') AND"
            " ((status='pending' AND fire_at<=?) OR (status='snoozed' AND snooze_until IS NOT NULL"
            " AND snooze_until<=?)) ORDER BY fire_at", (now, now)).fetchall()]
    except Exception:
        return []


def _recur_of(con, rid: int) -> str:
    try:
        row = con.execute("SELECT value FROM meta WHERE key=?", (f"recur:{rid}",)).fetchone()
        return str(row["value"]) if row else ""
    except Exception:
        return ""


def fire_due(con, now: float = 0, deliver: bool = True) -> list[dict]:
    ensure_schema(con)
    now = now or _now()
    fired = []
    for r in due_reminders(con, now):
        try:
            con.execute("UPDATE reminders SET status='fired', fired_at=? WHERE id=?", (now, r["id"]))
            recur = _recur_of(con, r["id"])
            if recur in RECUR:
                nxt = now + (86400 if recur == "daily" else 7 * 86400)
                cur = con.execute(
                    "INSERT INTO reminders(goal_id, step_id, fire_at, message, channel, status, created_at)"
                    " VALUES(?,?,?,?,?,'pending',?)",
                    (r.get("goal_id"), r.get("step_id"), nxt, r.get("message", ""),
                     r.get("channel", "chat"), now),
                )
                try:
                    con.execute(
                        "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (f"recur:{cur.lastrowid}", recur),
                    )
                except Exception:
                    pass
            con.commit()
        except Exception:
            continue
        item = dict(r)
        item["status"] = "fired"
        if deliver and str(r.get("channel", "chat")) == "desktop":
            try:
                desktop_toast(str(r.get("message", ""))[:200])
            except Exception:
                pass
        fired.append(item)
    return fired


def snooze(con, reminder_id: int, duration: str = "in 2h", use_llm: bool = True) -> dict:
    ensure_schema(con)
    try:
        row = con.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        if not row:
            return {"snoozed": False, "reason": "no such reminder"}
        ts = parse_natural(duration or "in 2h", use_llm=use_llm)
        if not ts:
            return {"snoozed": False, "reason": f"could not parse '{duration}'"}
        con.execute("UPDATE reminders SET status='snoozed', snooze_until=? WHERE id=?", (ts, reminder_id))
        con.commit()
        return {"snoozed": True, "until": ts}
    except Exception as exc:
        return {"snoozed": False, "reason": str(exc)}


def cancel(con, reminder_id: int) -> dict:
    ensure_schema(con)
    try:
        cur = con.execute("UPDATE reminders SET status='cancelled' WHERE id=? AND status IN ('pending','snoozed')",
                          (reminder_id,))
        con.commit()
        return {"cancelled": cur.rowcount > 0}
    except Exception as exc:
        return {"cancelled": False, "reason": str(exc)}


def pending(con, limit: int = 20) -> list[dict]:
    ensure_schema(con)
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM reminders WHERE status IN ('pending','snoozed') ORDER BY fire_at LIMIT ?",
            (limit,)).fetchall()]
    except Exception:
        return []


def desktop_toast(message: str, title: str = "Zumba") -> bool:
    try:
        from tools import shelltool
        if not shelltool.enabled():
            return False
        safe = (message or "").replace("'", "''")[:250]
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null; "
            f"$t = [Windows.UI.Notifications.ToastTemplateType]::ToastText02; "
            f"$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($t); "
            f"$x.GetElementsByTagName('text')[0].AppendChild($x.CreateTextNode('{title}')) | Out-Null; "
            f"$x.GetElementsByTagName('text')[1].AppendChild($x.CreateTextNode('{safe}')) | Out-Null; "
            f"$n = [Windows.UI.Notifications.ToastNotification]::new($x); "
            f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Zumba').Show($n)"
        )
        res = shelltool.run(ps, timeout_s=15)
        return (res.get("exit_code") or 1) == 0
    except Exception:
        return False


def render_pending(rows: list[dict]) -> str:
    if not rows:
        return "No pending reminders."
    lines = []
    for r in rows:
        try:
            ft = _dt.datetime.fromtimestamp(float(r.get("fire_at") or 0)).strftime("%m-%d %H:%M")
        except Exception:
            ft = "?"
        g = f" (goal #{r['goal_id']})" if r.get("goal_id") else ""
        lines.append(f"#{r['id']} [{r.get('status')}] {ft}{g}: {(r.get('message') or '')[:150]}")
    return "\n".join(lines)
