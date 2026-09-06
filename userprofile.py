"""T2.1 — Structured user model (Letta human-block pattern).

user.md = authoritative profile: identity, projects, people, preferences,
goals, current-focus. user_facts table (key, value, confidence,
source_episode, updated_at) is written by consolidation; an LLM pass
maintains user.md from graph + table. Recall ALWAYS prepends user.md
(bounded) — profile is in context unconditionally, not query-gated.
"""

from __future__ import annotations

import time

PROFILE_CAP = 1800

SECTIONS = ("Identity", "Projects", "People", "Preferences", "Goals", "Current focus")


def load_profile_text(max_chars: int = PROFILE_CAP) -> str:
    try:
        import soul as _soul
        text = _soul.load_user()
    except Exception:
        text = ""
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0] + "\n<!-- profile truncated -->"
    return text


def profile_block(max_chars: int = PROFILE_CAP) -> str:
    text = load_profile_text(max_chars)
    if not text:
        return ""
    return "[user.md — who the user is; authoritative profile, always in context]\n" + text.strip()


def upsert_fact(con, key: str, value: str, confidence: float = 0.7, source_episode=None) -> None:
    from memory import db as _db
    _db.ensure_tier2(con)
    key = (key or "").strip().lower().replace(" ", "_")[:80]
    if not key or not (value or "").strip():
        return
    con.execute(
        "INSERT INTO user_facts(key, value, confidence, source_episode, updated_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, confidence=excluded.confidence, "
        "source_episode=excluded.source_episode, updated_at=excluded.updated_at",
        (key, value.strip()[:1000], float(confidence), source_episode, time.time()),
    )


def get_facts(con) -> list[dict]:
    from memory import db as _db
    _db.ensure_tier2(con)
    try:
        return [dict(r) for r in con.execute("SELECT key, value, confidence, updated_at FROM user_facts ORDER BY key").fetchall()]
    except Exception:
        return []


_USER_REWRITE_PROMPT = """Maintain the user's profile (user.md) from the memory graph + structured facts.
Sections: Identity, Projects, People, Preferences, Goals, Current focus.
Rules: concrete durable facts only, no chit-chat, keep each section to a few bullets, <1800 chars total.
Current user.md:
{current}

Structured facts:
{facts}

Graph facts:
{graph}

Return the full updated user.md markdown (frontmatter + sections)."""


def rewrite_user_md(con, use_llm: bool = True) -> str:
    from memory import db as _db
    _db.ensure_tier2(con)
    try:
        import soul as _soul
        current = _soul.load_user() or "(empty)"
    except Exception:
        current = "(empty)"
    facts = get_facts(con)
    fact_blob = "\n".join(f"- {f['key']}: {f['value']}" for f in facts[:60]) or "(none)"
    graph_blob = ""
    try:
        rows = con.execute(
            """SELECT e1.canonical_name AS s, r.type, e2.canonical_name AS t, r.fact
               FROM relations r JOIN entities e1 ON e1.id=r.source_id
               JOIN entities e2 ON e2.id=r.target_id
               WHERE r.invalid_at IS NULL ORDER BY r.created_at DESC LIMIT 60"""
        ).fetchall()
        graph_blob = "\n".join(f"- {r['s']} -[{r['type']}]-> {r['t']}: {r['fact']}" for r in rows) or "(none)"
    except Exception:
        graph_blob = "(none)"
    if use_llm:
        try:
            from memory import llm as _llm
            out = _llm.chat_text(
                _USER_REWRITE_PROMPT.format(current=current[:3000], facts=fact_blob[:3000], graph=graph_blob[:4000]),
                system="You maintain a user profile markdown file. Output markdown only.",
                max_tokens=1200,
            )
            if out and "## " in out:
                capped = out.strip()[:PROFILE_CAP]
                try:
                    import soul as _soul
                    _soul.user_path().write_text(capped, encoding="utf-8")
                except Exception:
                    pass
                return capped
        except Exception:
            pass
    merged = current
    if facts and "(none recorded yet)" in merged:
        lines = "\n".join(f"- {f['key']}: {f['value']}" for f in facts[:12])
        merged = merged.replace("(none recorded yet)", lines, 1)
    return merged


def extract_user_facts_from_relations(con, rels: list, episode_id=None) -> int:
    n = 0
    for r in rels or []:
        typ = str(r.get("type") or "").lower()
        fact = str(r.get("fact") or "")
        src = str(r.get("source") or "")
        if not fact:
            continue
        key = None
        if typ.startswith("prefers_") or typ in ("prefers", "likes", "dislikes", "uses", "works_on", "lives_in", "is"):
            key = f"{src}_{typ}".lower().replace(" ", "_")[:80] if src else typ
        elif "prefer" in fact.lower() or "my " in fact.lower() or " i " in f" {fact.lower()} ":
            key = f"fact_{abs(hash(fact)) % 10_000_000}"
        if key:
            try:
                upsert_fact(con, key, fact, float(r.get("confidence") or 0.6), episode_id)
                n += 1
            except Exception:
                continue
    try:
        con.commit()
    except Exception:
        pass
    return n
