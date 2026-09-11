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

Return: {{"decisions": [{{"text": "..", "reason": ".."}}], "follow_ups": [{{"text":"..","index":0,"evidence":"exact user quote","expires_at":null,"dormant_at":null}}],
"importance": [{{"index": <episode-index-0-based>, "score": 1-10}}],
"mood": {{"valence": -1..1, "energy": 0..1, "note": ".."}}}}
Rules: decisions = choices made + why (skip chit-chat); follow_ups = user-endorsed unfinished tasks, not every assistant question.
For time-sensitive follow-ups, give absolute epoch expires_at and dormant_at using the original message timestamps.
For every follow-up provide the source exchange index and an exact quote from that user's message supporting the unfinished task.
Do not interpret an old 'tomorrow' relative to the current date. Ignore requests already completed, abandoned, cancelled or past their useful time.
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
                blob_lines.append(f"[{i}] source_timestamp={e.get('created_at', 'unknown')} U: {u}\n    A: {a}")
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
    importance = [{"index": i, "score": 5} for i, _ in enumerate(exchanges)]
    return {"decisions": [], "follow_ups": [], "importance": importance, "mood": {"valence": 0.0, "energy": 0.5, "note": "llm-unavailable"}} 


_GOAL_PROMPT = """Which of these follow-ups state a durable user goal (something to track with progress and a deadline)? Return JSON only: {{"goals": ["<goal title>", ...]}}. Empty list if none.

CANDIDATES:
{cands}"""


def _promote_goals(con, candidates: list[str]) -> int:
    cands = [c for c in candidates if (c or "").strip()]
    if not cands:
        return 0
    try:
        from . import llm as _llm
        out = _llm.chat_json(
            _GOAL_PROMPT.format(cands="\n".join(f"- {(c or '')[:300]}" for c in cands[:20])),
            system="You identify durable user goals. Valid JSON only.",
            max_tokens=400,
        )
        goals = (out or {}).get("goals") if isinstance(out, dict) else None
    except Exception:
        return 0
    n = 0
    for title in goals or []:
        title = str(title or "").strip()[:200]
        if not title:
            continue
        try:
            from . import goals as _goals
            dup = [g for g in _goals.list_goals(con, "active") if g.get("title", "").strip().lower() == title.lower()]
            if dup:
                continue
            _goals.create_goal(con, title, source="extracted", auto_plan=True, use_llm=False)
            n += 1
        except Exception:
            continue
    return n


def apply_reflection(con, exchanges: list[dict], reflection: dict, session_id: str = "", use_llm: bool = True) -> dict:
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
    n_goal = 0
    inserted: list[str] = []
    for f in reflection.get("follow_ups") or []:
        try:
            t = f if isinstance(f, str) else str(f.get("text") or f)
            if not t.strip():
                continue
            source_time = min((float(e['created_at']) for e in exchanges if e.get('created_at')), default=now)
            if isinstance(f, dict):
                index = f.get('index')
                if type(index) is not int or not 0 <= index < len(exchanges):
                    continue
                source = exchanges[index]
                evidence = f.get('evidence')
                user_text = str(source.get('user') or source.get('user_text') or '')
                if not isinstance(evidence, str) or not evidence.strip() or evidence not in user_text:
                    continue
                source_time = float(source.get('created_at') or source_time)
            # Re-reflection is not renewed consent. Keep the original clock.
            if con.execute('SELECT 1 FROM follow_ups WHERE text=? AND source_session=?', (t[:800], session_id)).fetchone():
                continue
            cur = con.execute(
                "INSERT INTO follow_ups(text, created_at, done_at, source_session) VALUES(?,?,NULL,?)",
                (t[:800], source_time, session_id),
            )
            from . import task_lifecycle
            task_lifecycle.seed(con, 'follow_up', {'id': cur.lastrowid, 'created_at': source_time})
            if isinstance(f, dict) and f.get('dormant_at') is not None:
                task_lifecycle.set_policy(con, 'follow_up', cur.lastrowid, f.get('expires_at'), f['dormant_at'], 'Session reflection')
            n_fup += 1
            if task_lifecycle.state(con, 'follow_up', cur.lastrowid) == 'active' and source_time >= now - 2 * 86400:
                inserted.append(t[:800])
        except Exception:
            continue
    if use_llm and inserted:
        try:
            n_goal = _promote_goals(con, inserted)
        except Exception:
            n_goal = 0
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
    exchanges = [dict(e) for e in exchanges[-30:]]
    for exchange in exchanges:
        if not exchange.get('created_at') and exchange.get('episode_id'):
            row = con.execute('SELECT created_at FROM episodes WHERE id=?', (exchange['episode_id'],)).fetchone()
            if row:
                exchange['created_at'] = row['created_at']
    reflection = reflect_transcript(exchanges, use_llm=use_llm)
    applied = apply_reflection(con, exchanges, reflection, session_id=session_id, use_llm=use_llm)
    return {"reflection": reflection, "applied": applied}


def open_follow_ups(con, limit: int = 20) -> list[dict]:
    ensure_schema(con)
    try:
        from . import task_lifecycle
        rows = [dict(r) for r in con.execute(
            "SELECT id, text, created_at, source_session FROM follow_ups WHERE done_at IS NULL ORDER BY created_at DESC LIMIT ?", (max(limit * 5, 100),)).fetchall()]
        active = [r for r in rows if task_lifecycle.eligible(con, 'follow_up', r)]
        con.commit()
        return active[:limit]
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
