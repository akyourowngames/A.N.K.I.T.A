"""T2.2 — Session-end reflection (Generative Agents pattern).

On chat exit (after mem.flush()), ONE LLM pass over the session:
- Decisions made + reasons -> notes with kind=decision
- Open follow-ups -> follow_ups table (powers daily briefing)
- Importance score 1-10 (poignancy) -> stored on episodes, feeds retrieval
- Mood/energy read -> session_moods (T2.4)
Cheap (1 call), runs in the background worker thread.
"""

from __future__ import annotations

import json
import time

from . import db as _db

REFLECTION_PROMPT = """Review this chat session and extract durable memory. Return JSON only.

SESSION:
{session}

Return: {{"decisions": [{{"text": "..", "reason": ".."}}], "follow_ups": [".."],
"importance": [{{"index": <episode-index-0-based>, "score": 1-10}}],
"mood": {{"valence": -1..1, "energy": 0..1, "note": ".."}}}}
Rules: decisions = choices made + why (skip chit-chat); follow_ups = open tasks/promises/questions left hanging;
importance = poignancy 1-10 per exchange (identity/preference/decision=8-10, chit-chat=1-3);
mood = user's emotional tone this session."""


def ensure_schema(con) -> None:
    _db.ensure_tier2(con)


def reflect_transcript(exchanges: list[dict], use_llm: bool = True) -> dict:
    if not exchanges:
        return {"decisions": [], "follow_ups": [], "importance": [], "mood": {}}
    if use_llm:
        try:
            from . import llm as _llm
            blob_lines = []
            for i, e in enumerate(exchanges[-30:]):
                u = str(e.get("user") or e.get("user_text") or "")[:400]
                a = str(e.get("assistant") or e.get("assistant_text") or "")[:400]
                blob_lines.append(f"[{i}] U: {u}\n    A: {a}")
            out = _llm.chat_json(
                REFLECTION_PROMPT.format(session="\n".join(blob_lines)[:8000]),
                system="You are a session reflection engine. Valid JSON only.",
                max_tokens=1200,
            )
            if isinstance(out, dict):
                return {
                    "decisions": out.get("decisions") or [],
                    "follow_ups": out.get("follow_ups") or [],
                    "importance": out.get("importance") or [],
                    "mood": out.get("mood") or {},
                }
        except Exception:
            pass
    return heuristic_reflect(exchanges)


def heuristic_reflect(exchanges: list[dict]) -> dict:
    import re as _re
    decisions, followups, importance = [], [], []
    for i, e in enumerate(exchanges):
        u = str(e.get("user") or e.get("user_text") or "")
        a = str(e.get("assistant") or e.get("assistant_text") or "")
        low = f" {u.lower()} "
        score = 3
        if _re.search(r"\b(decided|decision|go with|let's|ship|use \w+ for)\b", low):
            score = 8
            decisions.append({"text": u[:300], "reason": "explicit decision phrasing"})
        if _re.search(r"\b(i am|my name is|i live|i work|i prefer|remember that)\b", low):
            score = max(score, 8)
        if _re.search(r"\b(thanks|haha|nice|ok|cool)\b", low) and len(u.split()) < 5:
            score = 2
        if _re.search(r"\b(todo|follow up|tomorrow|next|remind|will do|need to|must)\b", low):
            followups.append(u[:300])
        if len(u.split()) > 30:
            score = max(score, 6)
        importance.append({"index": i, "score": score})
    mood = {"valence": 0.0, "energy": 0.5, "note": "heuristic"}
    try:
        from .mood import score_mood as _sm
        texts = " ".join(str(e.get("user") or "") for e in exchanges[-10:])
        v, _ = _sm(texts)
        mood = {"valence": v, "energy": 0.5, "note": "heuristic-affect"}
    except Exception:
        pass
    return {"decisions": decisions, "follow_ups": followups, "importance": importance, "mood": mood}


def apply_reflection(con, exchanges: list[dict], reflection: dict, session_id: str = "") -> dict:
    ensure_schema(con)
    now = time.time()
    n_dec = n_fup = n_imp = 0
    for d in reflection.get("decisions") or []:
        try:
            text = d if isinstance(d, str) else str(d.get("text") or "")
            reason = "" if isinstance(d, str) else str(d.get("reason") or "")
            if not text.strip():
                continue
            content = text[:500] + (f" (why: {reason[:200]})" if reason else "")
            con.execute(
                "INSERT INTO notes(title, content, keywords, tags, kind, description, embedding, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (text[:60], content, "[]", '["decision"]', "decision", reason[:300], None, now, now),
            )
            n_dec += 1
        except Exception:
            continue
    import re as _re
    _GOAL_RX = (
        _re.compile(r"\bi want to\b", _re.I),
        _re.compile(r"\bmy goal is\b", _re.I),
        _re.compile(r"\bi (need|have|must) to\b.{0,60}\bby\b", _re.I),
        _re.compile(r"\bby\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|monday|next|\d)", _re.I),
    )
    _GOAL_DIRECT_RX = (
        _re.compile(r"\bi want to\b.{0,80}\bby\b", _re.I),
        _re.compile(r"\bmy goal is\b", _re.I),
        _re.compile(r"\bi (need|have|must) to\b.{0,60}\bby\b", _re.I),
    )
    n_goal = 0

    def _promote(title: str) -> None:
        nonlocal n_goal
        title = (title or "").strip()[:200]
        if not title:
            return
        try:
            from . import goals as _goals
            dup = [g for g in _goals.list_goals(con, "active")
                   if g.get("title", "").strip().lower() == title.lower()]
            if dup:
                return
            _goals.create_goal(con, title, source="extracted", auto_plan=True, use_llm=False)
            n_goal += 1
        except Exception:
            pass
    for f in reflection.get("follow_ups") or []:
        try:
            t = f if isinstance(f, str) else str(f.get("text") or f)
            if not t.strip():
                continue
            con.execute(
                "INSERT INTO follow_ups(text, created_at, done_at, source_session) VALUES(?,?,NULL,?)",
                (t[:800], now, session_id),
            )
            n_fup += 1
            try:
                if any(rx.search(t) for rx in _GOAL_RX):
                    _promote(t)
            except Exception:
                pass
        except Exception:
            continue
    for e in exchanges or []:
        try:
            u = str(e.get("user") or e.get("user_text") or "")
            if u.strip() and any(rx.search(u) for rx in _GOAL_DIRECT_RX):
                _promote(u)
        except Exception:
            continue
    imp_list = reflection.get("importance") or []
    ep_ids = [e.get("episode_id") for e in exchanges]
    for item in imp_list:
        try:
            idx = int(item.get("index"))
            score = max(1.0, min(10.0, float(item.get("score"))))
            if 0 <= idx < len(ep_ids) and ep_ids[idx]:
                con.execute("UPDATE episodes SET importance=? WHERE id=?", (score, ep_ids[idx]))
                n_imp += 1
        except Exception:
            continue
    mood = reflection.get("mood") or {}
    try:
        if isinstance(mood, dict) and mood:
            from .mood import record_mood as _rec
            _rec(con, session_id=session_id, valence=float(mood.get("valence", 0.0)),
                 energy=float(mood.get("energy", 0.5)), note=str(mood.get("note", ""))[:300])
    except Exception:
        pass
    try:
        con.commit()
    except Exception:
        pass
    return {"decisions": n_dec, "follow_ups": n_fup, "importance_set": n_imp, "goals_proposed": n_goal}


def reflect_session(con, exchanges: list[dict], session_id: str = "", use_llm: bool = True) -> dict:
    ensure_schema(con)
    reflection = reflect_transcript(exchanges, use_llm=use_llm)
    applied = apply_reflection(con, exchanges, reflection, session_id=session_id)
    return {"reflection": reflection, "applied": applied}


def open_follow_ups(con, limit: int = 20) -> list[dict]:
    ensure_schema(con)
    try:
        return [dict(r) for r in con.execute(
            "SELECT id, text, created_at, source_session FROM follow_ups WHERE done_at IS NULL ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
    except Exception:
        return []


def complete_follow_up(con, fid: int) -> bool:
    ensure_schema(con)
    try:
        cur = con.execute("UPDATE follow_ups SET done_at=? WHERE id=? AND done_at IS NULL", (time.time(), fid))
        con.commit()
        return cur.rowcount > 0
    except Exception:
        return False
