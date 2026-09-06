"""T2.4 — Mood / state timeline.

session_moods (session_id, valence -1..1, energy, note, created_at).
Valence via local fastembed similarity to affect anchors (no LLM);
optional LLM refinement happens in reflection (T2.2).
`zumba mood` renders a 30-day terminal chart; recall boosts recent mood
context so tone adapts.
"""

from __future__ import annotations

import time

from . import db as _db

POS_ANCHORS = ["happy excited grateful great wonderful love fantastic energized", "calm content peaceful satisfied good steady"]
NEG_ANCHORS = ["sad angry frustrated tired stressed anxious awful terrible drained", "worried down lonely bored irritated disappointed"]


def _cos(a, b) -> float:
    import math
    try:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (na * nb)
    except Exception:
        return 0.0


def score_mood(text: str) -> tuple[float, float]:
    if not (text or "").strip():
        return 0.0, 0.5
    try:
        from . import embedder as _emb
        v = _emb.embed_text(text[:2000])
        if not v:
            raise RuntimeError("no embedding")
        pos = max(_cos(v, _emb.embed_text(a)) for a in POS_ANCHORS)
        neg = max(_cos(v, _emb.embed_text(a)) for a in NEG_ANCHORS)
        valence = max(-1.0, min(1.0, (pos - neg) * 2.0))
        energy = max(0.0, min(1.0, 0.5 + (pos + neg - 1.0) * 0.5 + min(len(text) / 2000.0, 1.0) * 0.2))
        return float(valence), float(energy)
    except Exception:
        pass
    low = f" {(text or '').lower()} "
    pos_hit = sum(1 for w in ("great", "happy", "love", "excited", "awesome", "good", "glad") if w in low)
    neg_hit = sum(1 for w in ("sad", "angry", "tired", "stressed", "frustrated", "awful", "worried", "down") if w in low)
    if pos_hit == 0 and neg_hit == 0:
        return 0.0, 0.5
    valence = (pos_hit - neg_hit) / max(pos_hit + neg_hit, 1)
    return float(max(-1.0, min(1.0, valence))), 0.6 if pos_hit + neg_hit > 1 else 0.5


def ensure_schema(con) -> None:
    _db.ensure_tier2(con)


def record_mood(con, session_id: str = "", valence: float = 0.0, energy: float = 0.5, note: str = "", created_at=None) -> int:
    ensure_schema(con)
    try:
        cur = con.execute(
            "INSERT INTO session_moods(session_id, valence, energy, note, created_at) VALUES(?,?,?,?,?)",
            (session_id or "", max(-1.0, min(1.0, float(valence))), max(0.0, min(1.0, float(energy))),
             (note or "")[:400], float(created_at) if created_at else time.time()),
        )
        con.commit()
        return cur.lastrowid
    except Exception:
        return 0


def record_text_mood(con, session_id: str, text: str, note: str = "") -> int:
    v, e = score_mood(text)
    return record_mood(con, session_id, v, e, note or text[:120])


def recent_moods(con, days: int = 30, limit: int = 60) -> list[dict]:
    ensure_schema(con)
    try:
        cutoff = time.time() - days * 86400.0
        return [dict(r) for r in con.execute(
            "SELECT session_id, valence, energy, note, created_at FROM session_moods WHERE created_at>=? ORDER BY created_at DESC LIMIT ?",
            (cutoff, limit)).fetchall()]
    except Exception:
        return []


def mood_context(con, limit: int = 5) -> str:
    rows = recent_moods(con, days=14, limit=limit)
    if not rows:
        return ""
    rows = list(reversed(rows))
    avg = sum(r["valence"] for r in rows) / len(rows)
    tone = "upbeat" if avg > 0.3 else ("low" if avg < -0.3 else "steady")
    bits = "; ".join(f"{r['valence']:+.1f} ({(r['note'] or '')[:60]})" for r in rows[-3:])
    return f"Recent mood trend ({tone}, avg {avg:+.2f}): {bits}"


def render_chart(con, days: int = 30) -> str:
    rows = recent_moods(con, days=days, limit=60)
    if not rows:
        return "No mood data yet (moods record at session reflection)."
    rows = sorted(rows, key=lambda r: r["created_at"])
    import datetime as _dt
    lines = []
    for r in rows[-30:]:
        v = float(r.get("valence", 0.0))
        bar_n = int(round((v + 1.0) * 10))
        bar = "#" * bar_n + "-" * (20 - bar_n)
        d = _dt.datetime.fromtimestamp(float(r["created_at"])).strftime("%m-%d")
        lines.append(f"{d} [{bar}] {v:+.2f} {(r.get('note') or '')[:40]}")
    avg = sum(float(r.get("valence", 0.0)) for r in rows) / len(rows)
    return f"MOOD · last {days}d · n={len(rows)} · avg {avg:+.2f}\n" + "\n".join(lines)
