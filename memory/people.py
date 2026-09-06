"""T2.7 — Relationship view: `zumba memory people`.

Person entities ranked by interaction recency/frequency (episodes join),
last-mentioned date, top facts. The twin knows who matters.
"""

from __future__ import annotations


def people_overview(con, limit: int = 20) -> list[dict]:
    try:
        persons = con.execute(
            "SELECT id, name, canonical_name, description, updated_at FROM entities WHERE type='person' OR type='people' OR canonical_name='user' LIMIT 500"
        ).fetchall()
    except Exception:
        return []
    out = []
    for p in persons:
        eid = p["id"]
        try:
            mentions = con.execute("SELECT COUNT(*) AS n FROM episode_entities WHERE entity_id=?", (eid,)).fetchone()["n"]
        except Exception:
            mentions = 0
        try:
            last_ep = con.execute(
                """SELECT MAX(e.created_at) AS ts FROM episodes e
                   JOIN episode_entities ee ON ee.episode_id=e.id WHERE ee.entity_id=?""", (eid,)).fetchone()
            last_ts = last_ep["ts"] if last_ep else None
        except Exception:
            last_ts = None
        last_ts = float(last_ts) if last_ts else float(p["updated_at"] or 0)
        try:
            facts = con.execute(
                """SELECT fact FROM relations WHERE invalid_at IS NULL AND (source_id=? OR target_id=?) ORDER BY created_at DESC LIMIT 3""",
                (eid, eid)).fetchall()
            top = [r["fact"] for r in facts]
        except Exception:
            top = []
        out.append({"id": eid, "name": p["canonical_name"] or p["name"], "mentions": int(mentions or 0),
                    "last_mentioned": last_ts, "description": (p["description"] or "")[:200], "top_facts": top})
    out.sort(key=lambda d: (d["last_mentioned"] or 0, d["mentions"]), reverse=True)
    return out[:limit]


def render_people(rows: list[dict]) -> str:
    if not rows:
        return "No people recorded yet."
    import datetime as _dt
    lines = []
    for i, r in enumerate(rows, 1):
        try:
            d = _dt.datetime.fromtimestamp(float(r["last_mentioned"])).strftime("%m-%d") if r["last_mentioned"] else "-"
        except Exception:
            d = "-"
        facts = (" :: " + "; ".join(r["top_facts"][:2])) if r["top_facts"] else ""
        lines.append(f"{i}. {r['name']} — {r['mentions']} mentions, last {d}{facts}")
    return "\n".join(lines)
