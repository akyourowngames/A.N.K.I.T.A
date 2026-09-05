"""Consolidation ("sleep-time" compute): community detection + summaries
(GraphRAG global memory), note auto-linking (A-Mem), and core-block rewriting
(MemGPT/Letta) that tighten long-term memory between interactions.
"""

from __future__ import annotations

import time

from . import graph, llm


def rebuild_communities(con) -> int:
    """Run community detection and generate a summary per detected community."""
    id_of, edges = graph.build_graph(con)
    if not edges:
        return 0
    communities = graph.detect_communities(id_of, edges)
    con.execute("DELETE FROM community_members WHERE community_id IN (SELECT id FROM communities WHERE level=0)")
    con.execute("DELETE FROM communities WHERE level=0")
    count = 0
    ent_id_by_canon = {}
    for r in con.execute("SELECT id, canonical_name FROM entities").fetchall():
        ent_id_by_canon[r["canonical_name"]] = r["id"]
    for members, level in communities:
        ent_ids = [ent_id_by_canon[m] for m in members if m in ent_id_by_canon]
        if not ent_ids:
            continue
        cur = con.execute(
            "INSERT INTO communities(label, level, summary, created_at, updated_at) VALUES(?,?,?,?,?)",
            (None, level, "", time.time(), time.time()),
        )
        cid = cur.lastrowid
        for eid in ent_ids:
            con.execute("INSERT OR IGNORE INTO community_members(community_id, entity_id) VALUES(?,?)", (cid, eid))
        summary = _community_summary(con, ent_ids)
        if summary:
            con.execute("UPDATE communities SET summary=? WHERE id=?", (summary, cid))
        count += 1
    return count


_COMMUNITY_PROMPT = """Write a concise summary of this cluster of related knowledge. Synthesize what they share, the key facts, and the overall theme. This summary will be used to answer high-level "global" questions.

ENTITIES:
{entities}

Return a short paragraph summary."""


def _community_summary(con, ent_ids) -> str:
    names = []
    for eid in ent_ids[:25]:
        r = con.execute("SELECT canonical_name, type, description FROM entities WHERE id=?", (eid,)).fetchone()
        if r:
            names.append(f"- {r['canonical_name']} [{r['type']}]: {r['description'][:180]}")
    if not names:
        return ""
    try:
        return llm.chat_text(_COMMUNITY_PROMPT.format(entities="\n".join(names)), max_tokens=400)
    except Exception:
        return ""


def link_notes(con, new_note_id: int | None = None) -> int:
    """A-Mem style linking: connect each note to the most similar others."""
    if new_note_id is not None:
        ids = [new_note_id]
    else:
        ids = [r["id"] for r in con.execute("SELECT id FROM notes").fetchall()]
    added = 0
    all_rows = con.execute("SELECT id, embedding FROM notes WHERE embedding IS NOT NULL").fetchall()
    if len(all_rows) < 2:
        return 0
    emb = {r["id"]: r["embedding"] for r in all_rows}
    targets = [new_note_id] if new_note_id is not None else list(emb.keys())
    for nid in targets:
        if nid not in emb:
            continue
        for other, sim in _cosine_all(emb[nid], emb)[:5]:
            if other == nid or sim < 0.55:
                continue
            con.execute(
                "INSERT OR IGNORE INTO note_links(source_id, target_id, strength) VALUES(?,?,?)",
                (nid, other, float(sim)),
            )
            added += 1
    return added


def _cosine_all(vec_bytes, emb: dict):
    import numpy as np

    from . import db

    vq = np.array(db.unpack_vec(vec_bytes), dtype=np.float32)
    results = []
    for nid, b in emb.items():
        if not b:
            continue
        v = np.array(db.unpack_vec(b), dtype=np.float32)
        denom = float(np.linalg.norm(vq) * np.linalg.norm(v)) or 1.0
        results.append((nid, float(np.dot(vq, v) / denom)))
    results.sort(key=lambda t: t[1], reverse=True)
    return results


_core_keys = ["user_profile", "preferences", "projects", "goals", "facts"]

_CORE_PROMPT = """You are maintaining the long-term "core memory" blocks of a personal assistant. Given the global facts currently stored about the user, produce a tight, structured set of core memory blocks that capture the stable, high-value knowledge.

GLOBAL FACTS (entities + relations):
{facts}

Update these blocks: user_profile, preferences, projects, goals, facts.
Return JSON: {{"user_profile": "..", "preferences": "..", "projects": "..", "goals": "..", "facts": ".."}} — each a compact bullet list of concrete, durable facts. Omit a key entirely if there is nothing durable for it."""


def rewrite_core(con, summary_limit: int = 4000):
    facts = _global_facts(con, summary_limit)
    if not facts.strip():
        return 0
    try:
        out = llm.chat_json(_CORE_PROMPT.format(facts=facts), system="You are a memory editor that outputs valid JSON only.", max_tokens=1200)
    except Exception:
        return 0
    if not isinstance(out, dict):
        return 0
    n = 0
    now = time.time()
    for key in _core_keys:
        val = (out.get(key) or "").strip()
        if val:
            con.execute(
                "INSERT INTO core_blocks(key, content, updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at",
                (key, val, now),
            )
            n += 1
    return n


def sweep_contradictions(con) -> int:
    """LLM-review the active fact graph; invalidate older facts contradicted
    by newer ones. Returns the number of facts invalidated."""
    from . import extraction

    rows = con.execute(
        """SELECT r.id, r.created_at, e1.canonical_name AS s, r.type, e2.canonical_name AS t, r.fact
           FROM relations r JOIN entities e1 ON e1.id=r.source_id
           JOIN entities e2 ON e2.id=r.target_id
           WHERE r.invalid_at IS NULL ORDER BY r.id"""
    ).fetchall()
    if len(rows) < 2:
        return 0
    facts = [
        {"id": r["id"], "text": f"{r['s']} -[{r['type']}]-> {r['t']}: {r['fact']}"} for r in rows
    ]
    ids = extraction.sweep_contradictions(facts)
    now = time.time()
    n = 0
    for fid in ids:
        cur = con.execute("UPDATE relations SET invalid_at=? WHERE id=? AND invalid_at IS NULL", (now, fid))
        n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return n


def _global_facts(con, limit: int) -> str:
    lines = []
    for r in con.execute(
        """SELECT e1.canonical_name AS s, r.type, e2.canonical_name AS t, r.fact, r.confidence
           FROM relations r JOIN entities e1 ON e1.id=r.source_id
           JOIN entities e2 ON e2.id=r.target_id
           WHERE r.invalid_at IS NULL ORDER BY r.confidence DESC, r.created_at DESC"""
    ).fetchall():
        lines.append(f"{r['s']} -[{r['type']}]-> {r['t']}: {r['fact']} (conf {r['confidence']})")
        if sum(len(x) for x in lines) > limit:
            break
    for r in con.execute(
        """SELECT canonical_name, type, description FROM entities
           WHERE importance >= 0.6 OR access_count >= 3 LIMIT 40"""
    ).fetchall():
        lines.append(f"ENTITY {r['canonical_name']} [{r['type']}] :: {r['description']}")
    return "\n".join(lines)