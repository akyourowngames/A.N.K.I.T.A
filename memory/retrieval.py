"""Retrieval: hybrid recall over the memory graph.

Pipeline (no LLM in the retrieval loop):
  1. Query embedding (vector) + keyword (FTS5) + entity match candidates.
  2. Personalized PageRank expansion seeded by matched entities (HippoRAG).
  3. Reciprocal-rank fusion of the evidence channels.
  4. Context packing into a token budget with provenance.
"""

from __future__ import annotations

import sqlite3

from . import db, embedder, graph


class MemoryHit:
    __slots__ = ("kind", "text", "score", "meta")

    def __init__(self, kind: str, text: str, score: float, meta: dict):
        self.kind = kind
        self.text = text
        self.score = score
        self.meta = meta


def _vector(con, q, table, id_col, limit):
    match = db.match_vec(q)
    try:
        rows = con.execute(
            f"SELECT {id_col} AS rid, distance FROM {table} WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (match, limit),
        ).fetchall()
    except Exception:
        return []
    return [(r["rid"], 1.0 - float(r["distance"])) for r in rows]


def _fts_query(q: str) -> str:
    """Sanitize user text into a safe FTS5 OR-query of word tokens."""
    import re

    tokens = re.findall(r"[A-Za-z0-9_]{2,}", q)
    return " OR ".join(tokens) if tokens else ""


def _fts(con, q, table, id_col, limit):
    esc = _fts_query(q)
    if not esc:
        return []
    try:
        rows = con.execute(
            f"SELECT {id_col} AS rid, bm25({table}) AS score FROM {table} WHERE {table} MATCH ? ORDER BY score LIMIT ?",
            (esc, limit),
        ).fetchall()
    except Exception:
        return []
    if not rows:
        return []
    best = min(float(r["score"]) for r in rows)
    return [(r["rid"], 1.0 / (1.0 + abs(float(r["score"]) - best))) for r in rows]


def _rrf(ranked_lists):
    from collections import defaultdict

    fused = defaultdict(float)
    k = 60
    for lst in ranked_lists:
        for rank, (rid, _s) in enumerate(lst):
            fused[rid] += 1.0 / (k + rank + 1)
    return fused


def search(con, query, top_k=8, use_ppr=True, max_bytes=6000):
    """Return a list of MemoryHit sorted by fused relevance."""
    q = query.strip()
    if not q:
        return []
    qv = embedder.embed_text(q)

    # Channel ids are namespaced so they never collide in the fusion dict.
    def _ns(prefix, pairs):
        return [(f"{prefix}:{rid}", s) for rid, s in pairs]

    # 1. Evidence channels.
    vec_ep = _ns("ep", _vector(con, qv, "vec_episodes", "episode_id", top_k * 3))
    vec_ent = _ns("ent", _vector(con, qv, "vec_entities", "entity_id", top_k * 3))
    vec_rel = _ns("rel", _vector(con, qv, "vec_relations", "relation_id", top_k * 3))
    fts_ep = _ns("ep", _fts(con, q, "fts_episodes", "rowid", top_k * 2))
    fts_rel = _ns("rel", _fts(con, q, "fts_relations", "rowid", top_k * 2))
    fts_note = _ns("note", _fts(con, q, "fts_notes", "rowid", top_k * 2))

    # 2. PPR expansion seeded by top entity matches -> boost related relations.
    ppr_rel = {}
    if use_ppr:
        id_of, edges = graph.build_graph(con)
        if id_of:
            seeds = {}
            for key, score in vec_ent[:5]:
                try:
                    eid = int(str(key).split(":", 1)[1])
                except Exception:
                    continue
                row = con.execute("SELECT canonical_name FROM entities WHERE id=?", (eid,)).fetchone()
                if row and row["canonical_name"] in id_of:
                    seeds[id_of[row["canonical_name"]]] = max(seeds.get(id_of[row["canonical_name"]], 0.0), float(score))
            if seeds:
                ppr = graph.personalized_pagerank(id_of, edges, seeds)
                # Map entity id -> canonical name -> index.
                ent_rows = con.execute("SELECT id, canonical_name FROM entities").fetchall()
                ent_idx = {r["id"]: r["canonical_name"] for r in ent_rows}
                rel_rows = con.execute(
                    "SELECT id, source_id, target_id, weight FROM relations WHERE invalid_at IS NULL"
                ).fetchall()
                for r in rel_rows:
                    s_name = ent_idx.get(r["source_id"])
                    t_name = ent_idx.get(r["target_id"])
                    s_val = ppr.get(id_of.get(s_name), 0.0) if s_name else 0.0
                    t_val = ppr.get(id_of.get(t_name), 0.0) if t_name else 0.0
                    score = float(r["weight"] or 1.0) * (0.5 * s_val + 0.5 * t_val)
                    if score > 0:
                        ppr_rel[r["id"]] = score

    # 3. Fuse channels; fold PPR in as an additive relation weight.
    fused = _rrf([vec_ep, vec_ent, vec_rel, fts_ep, fts_rel, fts_note])
    for rid, s in ppr_rel.items():
        fused[f"rel:{rid}"] = fused.get(f"rel:{rid}", 0.0) + s * 2.0

    # 4. Materialize hits (with recency weighting: newer statements win).
    import math
    import time as _time

    def _recency(ts, half_life_days=14.0, cap=0.8):
        try:
            age_days = max(0.0, (_time.time() - float(ts)) / 86400.0)
            return 1.0 + cap * math.pow(0.5, age_days / half_life_days)
        except Exception:
            return 1.0

    mapped = []
    for key, score in sorted(fused.items(), key=lambda kv: kv[1], reverse=True):
        ks = str(key)
        if ks.startswith("rel:"):
            rid = int(ks[4:])
            row = con.execute(
                """SELECT r.fact, r.type, r.created_at, e1.canonical_name AS s, e2.canonical_name AS t
                   FROM relations r JOIN entities e1 ON e1.id=r.source_id
                   JOIN entities e2 ON e2.id=r.target_id
                   WHERE r.id=? AND r.invalid_at IS NULL""",
                (rid,),
            ).fetchone()
            if row:
                weighted = float(score) * _recency(row["created_at"])
                mapped.append(MemoryHit("relation", f"{row['s']} -[{row['type']}]-> {row['t']}: {row['fact']}", weighted, {"id": rid}))
            continue
        if ks.startswith("ent:"):
            rid = int(ks[4:])
            ent = con.execute("SELECT name,type,description,updated_at FROM entities WHERE id=?", (rid,)).fetchone()
            if ent:
                weighted = float(score) * _recency(ent["updated_at"], cap=0.4)
                mapped.append(MemoryHit("entity", f"{ent['name']} [{ent['type']}]: {ent['description']}", weighted, {"id": rid}))
            continue
        if ks.startswith("ep:"):
            rid = int(ks[3:])
            ep = con.execute("SELECT user_text, assistant_text, created_at FROM episodes WHERE id=?", (rid,)).fetchone()
            if ep:
                weighted = float(score) * _recency(ep["created_at"], cap=0.4)
                mapped.append(MemoryHit("episode", f"U: {ep['user_text']}\nA: {ep['assistant_text']}", weighted, {"id": rid}))
            continue
        if ks.startswith("note:"):
            rid = int(ks[5:])
            note = con.execute("SELECT title, content, updated_at FROM notes WHERE id=?", (rid,)).fetchone()
            if note:
                weighted = float(score) * _recency(note["updated_at"], cap=0.4)
                mapped.append(MemoryHit("note", f"{note['title']}: {note['content']}", weighted, {"id": rid}))

    mapped.sort(key=lambda h: h.score, reverse=True)
    mapped = mapped[: top_k * 2]
    packed = []
    used = 0
    for h in mapped:
        if h.kind == "relation" and h.score < 0.01:
            continue
        size = len(h.text) + 2
        if used + size > max_bytes and packed:
            break
        packed.append(h)
        used += size
    return packed[:top_k]