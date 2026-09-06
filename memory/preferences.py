"""T2.6 — Preference learning.

Style corrections ("shorter", "no tables") -> extraction emits prefers_*
typed relations -> consolidation folds active preferences into soul.md
Voice section via the propose/accept flow. Tone converges, user in control.
"""

from __future__ import annotations

import re

PREF_PATTERNS = [
    (re.compile(r"\b(shorter|be concise|less verbose|keep it brief)\b", re.I), "prefers_brevity", "Give shorter, terser answers."),
    (re.compile(r"\bno tables\b", re.I), "prefers_no_tables", "Avoid tables; use prose or bullets."),
    (re.compile(r"\bmore detail|longer|elaborate|in depth\b", re.I), "prefers_detail", "Give fuller explanations with detail."),
    (re.compile(r"\bno emoji|without emoji|stop.*emoji\b", re.I), "prefers_no_emoji", "Avoid emojis."),
    (re.compile(r"\bbullet|bullets|list it\b", re.I), "prefers_bullets", "Prefer bullet lists."),
    (re.compile(r"\bcode first|show.*code|just.*code\b", re.I), "prefers_code_first", "Lead with code, minimal prose."),
    (re.compile(r"\bformal\b", re.I), "prefers_formal", "Use a formal tone."),
    (re.compile(r"\bcasual|chill|relaxed\b", re.I), "prefers_casual", "Use a casual tone."),
]

_STYLE_ENTITY_NAMES = ("user", "User", "USER")


def detect_corrections(user_text: str) -> list[dict]:
    out = []
    for rx, typ, desc in PREF_PATTERNS:
        if rx.search(user_text or ""):
            out.append({"source": "user", "target": "assistant_style", "type": typ, "fact": desc, "confidence": 0.85})
    return out


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
        import soul as _soul
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
