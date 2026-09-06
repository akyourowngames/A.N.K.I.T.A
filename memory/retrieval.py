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


def _importance_factor_episode(con, ep_id: int) -> float:
    try:
        row = con.execute("SELECT importance FROM episodes WHERE id=?", (ep_id,)).fetchone()
        imp = float(row["importance"]) if row and row["importance"] is not None else 5.0
        return 0.5 + imp / 10.0
    except Exception:
        return 1.0


def _importance_factor_entity(row) -> float:
    try:
        imp = float(row["importance"]) if row and row["importance"] is not None else 0.5
        return 0.7 + imp
    except Exception:
        return 1.0


def build_extended_graph(con):
    id_of, edges = graph.build_graph(con)
    id_of = dict(id_of)
    edges = list(edges)
    try:
        ep_links = con.execute("SELECT episode_id, entity_id, salience FROM episode_entities").fetchall()
        ent_canon = {r["id"]: r["canonical_name"] for r in con.execute("SELECT id, canonical_name FROM entities").fetchall()}
        for l in ep_links:
            try:
                ent_name = ent_canon.get(l["entity_id"])
                if ent_name not in id_of:
                    continue
                ep_key = f"ep:{int(l['episode_id'])}"
                if ep_key not in id_of:
                    id_of[ep_key] = len(id_of)
                edges.append((id_of[ent_name], id_of[ep_key], float(l["salience"] or 0.5)))
            except Exception:
                continue
    except Exception:
        pass
    try:
        for l in con.execute("SELECT source_id, target_id, strength FROM note_links").fetchall():
            try:
                a, b = f"note:{int(l['source_id'])}", f"note:{int(l['target_id'])}"
                if a not in id_of:
                    id_of[a] = len(id_of)
                if b not in id_of:
                    id_of[b] = len(id_of)
                edges.append((id_of[a], id_of[b], float(l["strength"] or 0.5)))
            except Exception:
                continue
    except Exception:
        pass
    return id_of, edges


def search(con, query, top_k=8, use_ppr=True, max_bytes=6000, time_range=None, as_of=None):
    """Return a list of MemoryHit sorted by fused relevance.

    V2 (HippoRAG 2 passages-in-graph + importance + temporal):
    - PPR seeds include episode/note passage nodes too, with per-node reset
      probabilities weighted by importance (T2.2) + recency.
    - time_range=(start_ts, end_ts) filters episodes/relations by created_at.
    - as_of=cutoff filters relations by valid_at (bi-temporal read path).
    """
    q = query.strip()
    if not q:
        return []
    qv = embedder.embed_text(q)

    # Channel ids are namespaced so they never collide in the fusion dict.
    def _ns(prefix, pairs):
        return [(f"{prefix}:{rid}", s) for rid, s in pairs]

    # 1. Evidence channels (episode text is always FTS+vector indexed
    # synchronously at ingest, so raw-text recall never waits on enrichment).
    vec_ep = _ns("ep", _vector(con, qv, "vec_episodes", "episode_id", top_k * 3))
    vec_ent = _ns("ent", _vector(con, qv, "vec_entities", "entity_id", top_k * 3))
    vec_rel = _ns("rel", _vector(con, qv, "vec_relations", "relation_id", top_k * 3))
    vec_note = _ns("note", _vector(con, qv, "vec_notes", "note_id", top_k * 3))
    fts_ep = _ns("ep", _fts(con, q, "fts_episodes", "rowid", top_k * 2))
    fts_rel = _ns("rel", _fts(con, q, "fts_relations", "rowid", top_k * 2))
    fts_note = _ns("note", _fts(con, q, "fts_notes", "rowid", top_k * 2))

    # 2. PPR v2: passages-in-graph. Seeds = entities + episodes + notes,
    # per-node reset weighted by importance + recency.
    import time as _t
    ppr_rel: dict = {}
    ppr_ep: dict = {}
    ppr_note: dict = {}
    if use_ppr:
        id_of, edges = build_extended_graph(con)
        if id_of:
            import math as _m

            def _rec_w(ts, half=14.0):
                try:
                    age = max(0.0, (_t.time() - float(ts)) / 86400.0)
                    return 0.5 + 0.5 * _m.pow(0.5, age / half)
                except Exception:
                    return 1.0

            seeds: dict = {}
            for key, score in vec_ent[:5]:
                try:
                    eid = int(str(key).split(":", 1)[1])
                except Exception:
                    continue
                row = con.execute("SELECT canonical_name, importance, updated_at FROM entities WHERE id=?", (eid,)).fetchone()
                if row and row["canonical_name"] in id_of:
                    w = float(score) * _importance_factor_entity(row) * _rec_w(row["updated_at"])
                    k = id_of[row["canonical_name"]]
                    seeds[k] = max(seeds.get(k, 0.0), w)
            for key, score in (vec_ep + fts_ep)[:6]:
                try:
                    ep_id = int(str(key).split(":", 1)[1])
                except Exception:
                    continue
                nkey = f"ep:{ep_id}"
                if nkey in id_of:
                    try:
                        r = con.execute("SELECT created_at FROM episodes WHERE id=?", (ep_id,)).fetchone()
                        w = float(score) * _importance_factor_episode(con, ep_id) * _rec_w(r["created_at"] if r else _t.time())
                    except Exception:
                        w = float(score)
                    seeds[id_of[nkey]] = max(seeds.get(id_of[nkey], 0.0), w)
            for key, score in (vec_note + fts_note)[:5]:
                try:
                    n_id = int(str(key).split(":", 1)[1])
                except Exception:
                    continue
                nkey = f"note:{n_id}"
                if nkey in id_of:
                    seeds[id_of[nkey]] = max(seeds.get(id_of[nkey], 0.0), float(score))
            if seeds:
                ppr = graph.personalized_pagerank(id_of, edges, seeds)
                ent_rows = con.execute("SELECT id, canonical_name FROM entities").fetchall()
                ent_idx = {r["id"]: r["canonical_name"] for r in ent_rows}
                as_of_f = None
                try:
                    as_of_f = float(as_of) if as_of is not None else None
                except Exception:
                    as_of_f = None
                rel_rows = con.execute(
                    "SELECT id, source_id, target_id, weight, valid_at FROM relations WHERE invalid_at IS NULL"
                ).fetchall()
                for r in rel_rows:
                    if as_of_f is not None:
                        try:
                            va = r["valid_at"]
                            if va is not None and float(va) > as_of_f:
                                continue
                        except Exception:
                            pass
                    s_name = ent_idx.get(r["source_id"])
                    t_name = ent_idx.get(r["target_id"])
                    s_val = ppr.get(id_of.get(s_name), 0.0) if s_name else 0.0
                    t_val = ppr.get(id_of.get(t_name), 0.0) if t_name else 0.0
                    score = float(r["weight"] or 1.0) * (0.5 * s_val + 0.5 * t_val)
                    if score > 0:
                        ppr_rel[r["id"]] = score
                for k, v in ppr.items():
                    name = next((kk for kk, vv in id_of.items() if vv == k), None)
                    if not name:
                        continue
                    if name.startswith("ep:"):
                        try:
                            ppr_ep[int(name[3:])] = float(v)
                        except Exception:
                            pass
                    elif name.startswith("note:"):
                        try:
                            ppr_note[int(name[5:])] = float(v)
                        except Exception:
                            pass

    # 3. Fuse channels; fold PPR in as an additive relation/episode/note weight.
    fused = _rrf([vec_ep, vec_ent, vec_rel, vec_note, fts_ep, fts_rel, fts_note])
    for rid, s in ppr_rel.items():
        fused[f"rel:{rid}"] = fused.get(f"rel:{rid}", 0.0) + s * 2.0
    for eid, s in ppr_ep.items():
        fused[f"ep:{eid}"] = fused.get(f"ep:{eid}", 0.0) + s * 1.5
    for nid, s in ppr_note.items():
        fused[f"note:{nid}"] = fused.get(f"note:{nid}", 0.0) + s * 1.5

    # 4. Materialize hits (with recency weighting: newer statements win).
    import math
    import time as _time

    def _recency(ts, half_life_days=14.0, cap=0.8):
        try:
            age_days = max(0.0, (_time.time() - float(ts)) / 86400.0)
            return 1.0 + cap * math.pow(0.5, age_days / half_life_days)
        except Exception:
            return 1.0

    t_start, t_end = None, None
    try:
        if time_range is not None:
            t_start, t_end = float(time_range[0] or 0), float(time_range[1] or 0)
            if not t_start:
                t_start = None
            if not t_end:
                t_end = None
    except Exception:
        t_start, t_end = None, None
    try:
        as_of_f = float(as_of) if as_of is not None else None
    except Exception:
        as_of_f = None

    def _in_range(ts) -> bool:
        try:
            f = float(ts)
        except Exception:
            return True
        if t_start is not None and f < t_start:
            return False
        if t_end is not None and f > t_end:
            return False
        return True

    mapped = []
    for key, score in sorted(fused.items(), key=lambda kv: kv[1], reverse=True):
        ks = str(key)
        if ks.startswith("rel:"):
            rid = int(ks[4:])
            row = con.execute(
                """SELECT r.fact, r.type, r.created_at, r.valid_at, r.invalid_at, r.confidence,
                          e1.canonical_name AS s, e2.canonical_name AS t
                   FROM relations r JOIN entities e1 ON e1.id=r.source_id
                   JOIN entities e2 ON e2.id=r.target_id
                   WHERE r.id=? AND r.invalid_at IS NULL""",
                (rid,),
            ).fetchone()
            if row:
                if not _in_range(row["created_at"]):
                    continue
                if as_of_f is not None and row["valid_at"] is not None:
                    try:
                        if float(row["valid_at"]) > as_of_f:
                            continue
                    except Exception:
                        pass
                try:
                    imp_w = 0.7 + float(row["confidence"] or 0.5)
                except Exception:
                    imp_w = 1.0
                weighted = float(score) * _recency(row["created_at"]) * imp_w
                mapped.append(MemoryHit("relation", f"{row['s']} -[{row['type']}]-> {row['t']}: {row['fact']}", weighted, {"id": rid}))
            continue
        if ks.startswith("ent:"):
            rid = int(ks[4:])
            ent = con.execute("SELECT name,type,description,updated_at,importance FROM entities WHERE id=?", (rid,)).fetchone()
            if ent:
                weighted = float(score) * _recency(ent["updated_at"], cap=0.4) * _importance_factor_entity(ent)
                mapped.append(MemoryHit("entity", f"{ent['name']} [{ent['type']}]: {ent['description']}", weighted, {"id": rid}))
            continue
        if ks.startswith("ep:"):
            rid = int(ks[3:])
            try:
                ep = con.execute("SELECT user_text, assistant_text, created_at, importance FROM episodes WHERE id=?", (rid,)).fetchone()
            except Exception:
                ep = con.execute("SELECT user_text, assistant_text, created_at FROM episodes WHERE id=?", (rid,)).fetchone()
            if ep:
                if not _in_range(ep["created_at"]):
                    continue
                try:
                    imp = float(ep["importance"]) if "importance" in ep.keys() and ep["importance"] is not None else 5.0
                except Exception:
                    imp = 5.0
                weighted = float(score) * _recency(ep["created_at"], cap=0.4) * (0.5 + imp / 10.0)
                mapped.append(MemoryHit("episode", f"U: {ep['user_text']}\nA: {ep['assistant_text']}", weighted, {"id": rid}))
            continue
        if ks.startswith("note:"):
            rid = int(ks[5:])
            note = con.execute("SELECT title, content, updated_at FROM notes WHERE id=?", (rid,)).fetchone()
            if note:
                if not _in_range(note["updated_at"]):
                    continue
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