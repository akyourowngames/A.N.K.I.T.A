"""Entity resolution: map a freshly-extracted entity/relation name onto an
existing canonical entity, using exact/alias match, vector similarity, and an
LLM merge decision when there is genuine ambiguity.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from . import db, embedder, llm


def _top_candidates(con: sqlite3.Connection, name: str, k: int = 5) -> list[dict]:
    """Vector-sim candidates from the index by embedding the name."""
    vec = embedder.embed_text(name)
    if not vec:
        return []
    match = db.match_vec(vec)
    try:
        rows = con.execute(
            "SELECT entity_id, distance FROM vec_entities WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (match, k),
        ).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        ent = con.execute("SELECT id,name,type,description FROM entities WHERE id=?", (r["entity_id"],)).fetchone()
        if ent:
            out.append({"id": ent["id"], "name": ent["name"], "type": ent["type"], "score": 1.0 - float(r["distance"])})
    return out


def resolve_entity(con: sqlite3.Connection, name: str, known: dict | None = None) -> int | None:
    """Return an existing entity id the name should map to, or None if it's new."""
    name = (name or "").strip()
    if not name:
        return None
    # Exact / alias match.
    row = con.execute("SELECT entity_id FROM aliases WHERE alias=?", (name,)).fetchone()
    if row:
        return row["entity_id"]
    row = con.execute("SELECT id FROM entities WHERE canonical_name=?", (name,)).fetchone()
    if row:
        return row["id"]

    # Vector candidates — ask the LLM whether any of the top candidates is the
    # same real-world entity (catches aliases, abbreviations, case/punct drift
    # like "ankita" vs "A.N.K.I.T.A.").
    cand = [c for c in _top_candidates(con, name, k=3) if c["score"] >= 0.5]
    for top in cand:
        if top["score"] >= 0.92:
            return top["id"]
        decision = _merge_decision(name, top)
        if decision:
            return decision
    return None


_MERGE_PROMPT = """Entity resolution. Is the new name a reference to the same real-world entity as the candidate?

NEW NAME: {name}
CANDIDATE: {cand_name} ({cand_type}) :: {cand_desc}

Consider aliases, abbreviations, and that user phrasing varies. If they are the same entity return true, else false.

Respond JSON: {{"same": true|false, "reason": ".."}}"""


def _merge_decision(name: str, cand: dict) -> int | None:
    try:
        out = llm.chat_json(
            _MERGE_PROMPT.format(name=name, cand_name=cand["name"], cand_type=cand.get("type", ""), cand_desc=(cand.get("description") or "")[:400]),
            system="You perform precise entity resolution decisions. Answer with valid JSON only.",
            max_tokens=200,
        )
    except Exception:
        return None
    if out and out.get("same"):
        return cand["id"]
    return None