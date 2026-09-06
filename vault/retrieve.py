"""THE ENGINE: hybrid vault retrieval with citations.

Pipeline: [optional HyDE] -> parallel pools (vector KNN over chunks +
hyp-questions + section summaries, BM25 over vault_fts, doc-title/summary
match) -> RRF -> cross-encoder rerank (skippable) -> small-to-big parent
expansion -> memory-KG graph boost -> budget pack with
[Title p.N SHeading] citations.
"""

from __future__ import annotations

import json
import os
import re
import time

from memory.db import match_vec


class VaultHit:
    __slots__ = ("kind", "text", "score", "meta")

    def __init__(self, kind, text, score, meta):
        self.kind = kind
        self.text = text
        self.score = score
        self.meta = meta


def top_k() -> int:
    try:
        return max(1, min(20, int(os.getenv("ZUMBA_VAULT_TOP_K", "6") or 6)))
    except Exception:
        return 6


def budget() -> int:
    try:
        return max(1000, int(os.getenv("ZUMBA_VAULT_BUDGET", "4000") or 4000))
    except Exception:
        return 4000


def _vector(con, qvec, table, id_col, limit):
    if not qvec:
        return []
    try:
        rows = con.execute(
            f"SELECT {id_col} AS rid, distance FROM {table} WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (match_vec(qvec), limit)).fetchall()
    except Exception:
        return []
    return [(r["rid"], 1.0 - float(r["distance"])) for r in rows]


def _fts(con, query, limit):
    toks = re.findall(r"[A-Za-z0-9_]{2,}", query or "")
    esc = " OR ".join(toks) if toks else ""
    if not esc:
        return []
    try:
        rows = con.execute(
            "SELECT rowid AS rid, bm25(vault_fts) AS s FROM vault_fts WHERE vault_fts MATCH ? ORDER BY s LIMIT ?",
            (esc, limit)).fetchall()
    except Exception:
        return []
    if not rows:
        return []
    best = min(float(r["s"]) for r in rows)
    return [(r["rid"], 1.0 / (1.0 + abs(float(r["s"]) - best))) for r in rows]


def _rrf(ranked_lists):
    from collections import defaultdict
    fused = defaultdict(float)
    k = 60
    for lst in ranked_lists:
        for rank, (rid, _s) in enumerate(lst):
            fused[rid] += 1.0 / (k + rank + 1)
    return fused


def _memory_entities() -> list[str]:
    try:
        from memory import db as _mdb
        con = _mdb.connect()
        try:
            rows = con.execute("SELECT canonical_name FROM entities LIMIT 200").fetchall()
            return [str(r["canonical_name"]) for r in rows if r["canonical_name"]]
        finally:
            con.close()
    except Exception:
        return []


def search(con, query, k: int = 0, doc_filter: str = "", rerank_on: bool | None = None) -> list[VaultHit]:
    from memory import embedder as _emb
    from vault import context as _ctx
    from vault import rerank as _rr

    q = (query or "").strip()
    if not q:
        return []
    k = k or top_k()
    queries = [q] + _ctx.hyde_expand(q)
    qvecs = []
    for qq in queries[:4]:
        try:
            v = _emb.embed_text(qq[:2000])
            if v:
                qvecs.append(v)
        except Exception:
            pass
    vec_ids, fts_ids, sec_ids = [], [], []
    for v in qvecs or [[]]:
        vec_ids += _vector(con, v, "vec_chunks", "chunk_id", 40)
        sec_ids += _vector(con, v, "vec_sections", "section_id", 10)
    fts_ids = _fts(con, q, 40)
    try:
        like = f"%{q[:60]}%"
        title_rows = con.execute(
            "SELECT id FROM docs WHERE status='ok' AND (title LIKE ? OR summary LIKE ?) LIMIT 5",
            (like, like)).fetchall()
    except Exception:
        title_rows = []
    fused = _rrf([vec_ids, fts_ids] + ([sec_ids] if sec_ids else []))
    if not fused and not title_rows:
        return []
    cands: list[tuple[int, float]] = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:40]
    try:
        ents = _memory_entities()
    except Exception:
        ents = []
    rows = []
    for cid, fs in cands:
        try:
            r = con.execute(
                """SELECT c.id, c.doc_id, c.section_id, c.ordinal, c.page, c.text,
                          c.context_line, c.hyp_questions, d.title, s.heading
                   FROM chunks c JOIN docs d ON d.id=c.doc_id
                   LEFT JOIN sections s ON s.id=c.section_id
                   WHERE c.id=?""", (cid,)).fetchone()
        except Exception:
            continue
        if not r:
            continue
        if doc_filter and doc_filter.lower() not in (str(r["title"] or "").lower()):
            continue
        boost = 0.0
        try:
            low = f" {(r['text'] or '').lower()} "
            for e in ents[:80]:
                if e and len(e) > 2 and e.lower() in low:
                    boost += 0.05
                    break
        except Exception:
            pass
        rows.append((r, fs + boost))
    if title_rows and len(rows) < k:
        try:
            for t in title_rows:
                s = con.execute("SELECT heading, summary FROM sections WHERE doc_id=? LIMIT 3",
                                (t["id"],)).fetchall()
                d = con.execute("SELECT title, summary FROM docs WHERE id=?", (t["id"],)).fetchone()
                if d:
                    rows.append(({"id": -int(t["id"]), "doc_id": t["id"], "section_id": None,
                                  "ordinal": -1, "page": 1, "text": d["summary"] or d["title"],
                                  "context_line": "", "hyp_questions": "[]",
                                  "title": d["title"], "heading": ""}, 0.01))
        except Exception:
            pass
    use_rerank = _rr.enabled() if rerank_on is None else bool(rerank_on)
    if use_rerank and rows:
        try:
            texts = [f"{dict(r).get('context_line','')} {dict(r).get('text','')}"[:2000] for r, _ in rows]
            order = _rr.rerank(q, texts, top_k=min(len(rows), max(k * 3, k)))
            rows = [rows[i] for i in order if 0 <= i < len(rows)]
        except Exception:
            pass
    hits: list[VaultHit] = []
    for r, fs in rows[: max(k * 4, k)]:
        d = dict(r)
        if int(d.get("id", 0)) < 0:
            hits.append(VaultHit("doc-summary", (d.get("text") or "")[:1500], fs,
                                 {"doc": d.get("title", ""), "doc_id": d.get("doc_id"),
                                  "citation": citation(d.get("title", ""), 1, "")}))
            continue
        sec_text = ""
        try:
            if d.get("section_id"):
                srow = con.execute("SELECT heading, summary FROM sections WHERE id=?",
                                   (d["section_id"],)).fetchone()
                if srow:
                    chunks = con.execute("SELECT text FROM chunks WHERE section_id=? ORDER BY ordinal",
                                         (d["section_id"],)).fetchall()
                    sec_text = "\n\n".join(c["text"] for c in chunks)[:2000]
                    d["_sec_heading"] = srow["heading"]
                    d["_sec_summary"] = srow["summary"]
        except Exception:
            pass
        body = sec_text or (d.get("text") or "")
        quote = (d.get("text") or "")[:280].replace("\n", " ")
        cite = citation(d.get("title", ""), int(d.get("page", 1)), str(d.get("heading") or ""))
        hits.append(VaultHit("chunk", f"{cite} :: {body[:1500]}\nquote: \"{quote}\"",
                             fs, {"id": d.get("id"), "doc": d.get("title", ""),
                                  "page": d.get("page", 1), "section": d.get("heading") or "",
                                  "citation": cite, "quote": quote}))
        if len(hits) >= k * 2:
            break
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


def citation(title: str, page: int, heading: str) -> str:
    h = f" §{heading[:60]}" if (heading or "").strip() else ""
    return f"[{title or 'doc'} p.{max(1, page)}{h}]"


def pack_context(hits: list[VaultHit], max_chars: int = 0) -> str:
    cap = max_chars or budget()
    lines = []
    used = 0
    for h in hits or []:
        block = f"[{h.kind}] {h.text}"
        if used + len(block) + 2 > cap and lines:
            break
        lines.append(block)
        used += len(block) + 2
    if not lines:
        return ""
    return "[VAULT CONTEXT] (document evidence — cite every claim like [Title p.N §Heading])\n" + "\n\n".join(lines)


def find(con, query: str, k: int = 0, doc_filter: str = "") -> list[dict]:
    out = []
    for h in search(con, query, k=k or top_k(), doc_filter=doc_filter):
        out.append({"kind": h.kind, "score": round(float(h.score), 4),
                    "meta": dict(h.meta or {}), "text": h.text[:800]})
    return out
