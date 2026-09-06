"""T2.6 — Preference learning.

Style corrections ("shorter", "no tables") -> extraction emits prefers_*
typed relations -> consolidation folds active preferences into soul.md
Voice section via the propose/accept flow. Tone converges, user in control.
"""

from __future__ import annotations

_STYLE_PROMPT = """Does this exchange state a preference about how the assistant should behave (brevity, detail, tone, format, emojis, code style)? Return JSON only: {"prefs": [{"type": "prefers_<name>", "fact": "<plain instruction>"}]}. Empty prefs list if none."""


def detect_corrections(user_text: str) -> list[dict]:
    try:
        from . import llm as _llm
        out = _llm.chat_json(
            _STYLE_PROMPT + "\n\nEXCHANGE:\n" + (user_text or "")[:2000],
            system="You detect assistant style preferences. Valid JSON only.",
            max_tokens=400,
        )
        prefs = (out or {}).get("prefs") if isinstance(out, dict) else None
        result = []
        for p in prefs or []:
            if isinstance(p, dict) and p.get("type") and p.get("fact"):
                result.append({"source": "user", "target": "assistant_style", "type": str(p["type"])[:60], "fact": str(p["fact"])[:300], "confidence": 0.85})
        return result
    except Exception:
        return []


def active_preferences(con, limit: int = 20) -> list[dict]:
    try:
        rows = con.execute(
            """SELECT r.type, r.fact, MAX(r.created_at) AS ts FROM relations r
               WHERE r.invalid_at IS NULL AND (r.type LIKE 'prefers\\_%' ESCAPE '\\' OR r.type='prefers')
               GROUP BY r.type, r.fact ORDER BY ts DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        try:
            rows = con.execute(
                "SELECT type, fact FROM relations WHERE invalid_at IS NULL AND type LIKE 'prefers%' LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []


def propose_voice_update(con=None, prefs: list | None = None) -> str:
    prefs = prefs if prefs is not None else (active_preferences(con) if con is not None else [])
    if not prefs:
        return ""
    lines = []
    for p in prefs[:8]:
        fact = str(p.get("fact") or p.get("type") or "").strip()
        if fact and fact not in lines:
            lines.append(f"- {fact}")
    if not lines:
        return ""
    try:
        from identity import soul as _soul
        cur = _soul.load()
        voice_add = "Style preferences learned from corrections:\n" + "\n".join(lines)
        if cur and voice_add.splitlines()[1] in cur:
            return ""
        if "## Voice" in cur:
            new = cur.replace("## Voice", "## Voice\n" + "\n".join(lines), 1)
        else:
            new = (cur.rstrip() + "\n\n## Voice\n" + "\n".join(lines)) if cur else ""
        if not new:
            return ""
        return _soul.propose_update(new)
    except Exception:
        return ""
