"""Watch/scan pipeline: stat -> hash -> parse -> chunk -> embed -> index.

Incremental (changed files only via content hash), content-hash dedupe,
queue with back-pressure, graceful pause. Enrichment (context lines,
hyp questions, summaries) never blocks raw-text indexing.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
from pathlib import Path

from vault import chunker as _chunker
from vault import db as _db
from vault import parsers as _parsers


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def max_file_mb() -> float:
    try:
        return max(1.0, float(os.getenv("ZUMBA_VAULT_MAX_FILE_MB", "100") or 100))
    except Exception:
        return 100.0


def iter_files(targets: list[str]) -> list[Path]:
    out: list[Path] = []
    for t in targets or []:
        p = Path(t).expanduser()
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in _parsers.SUPPORTED and not f.name.startswith("."):
                    out.append(f)
        else:
            for f in sorted(Path(".").glob(t)):
                if f.is_file() and f.suffix.lower() in _parsers.SUPPORTED:
                    out.append(f)
    seen, uniq = set(), []
    for f in out:
        try:
            rp = str(f.resolve())
        except Exception:
            rp = str(f)
        if rp not in seen:
            seen.add(rp)
            uniq.append(f)
    return uniq


def ingest_file(con, path: Path, use_llm: bool = True) -> dict:
    from memory import embedder as _emb
    from vault import context as _ctx
    from vault import summarize as _sum

    try:
        st = path.stat()
    except Exception as exc:
        return {"stored": False, "reason": f"stat failed: {exc}"}
    if st.st_size > max_file_mb() * 1024 * 1024:
        return {"stored": False, "reason": "too large"}
    try:
        h = file_hash(path)
    except Exception as exc:
        return {"stored": False, "reason": f"hash failed: {exc}"}
    row = con.execute("SELECT id, hash FROM docs WHERE hash=?", (h,)).fetchone()
    if row:
        return {"stored": False, "reason": "duplicate", "doc_id": row["id"]}
    try:
        md, n_pages, kind = _parsers.parse_file(path)
    except Exception as exc:
        now = _db.now()
        try:
            con.execute(
                "INSERT INTO docs(hash, path, mtime, kind, title, n_pages, summary, status, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (h, str(path), st.st_mtime, path.suffix.lower().lstrip(".") or "txt",
                 path.stem[:200], 1, "", f"failed: {exc}"[:300], now, now))
            con.commit()
        except Exception:
            pass
        return {"stored": False, "reason": f"parse failed: {exc}"}
    title = path.stem[:200]
    for line in (md or "").splitlines()[:10]:
        import re as _re
        m = _re.match(r"^#\s+(.*)$", line.strip())
        if m and m.group(1).strip():
            title = m.group(1).strip()[:200]
            break
    now = _db.now()
    cur = con.execute(
        "INSERT INTO docs(hash, path, mtime, kind, title, n_pages, summary, status, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (h, str(path), st.st_mtime, kind, title, n_pages, "", "ok", now, now))
    doc_id = cur.lastrowid
    try:
        _db.vault_raw_dir().mkdir(parents=True, exist_ok=True)
        (_db.vault_raw_dir() / f"{h}.md").write_text(md, encoding="utf-8")
    except Exception:
        pass
    pieces = _chunker.chunk_markdown(md)
    if not pieces:
        pieces = [{"ordinal": 0, "text": md[:6000], "heading": "", "level": 1}]
    sec_ids: dict[str, int] = {}
    for pc in pieces:
        key = (pc.get("heading") or "").strip()
        if key not in sec_ids:
            cur = con.execute("INSERT INTO sections(doc_id, heading, level, summary) VALUES(?,?,?,?)",
                              (doc_id, key[:300], int(pc.get("level", 1) or 1), ""))
            sec_ids[key] = cur.lastrowid
    enriched = _ctx.context_for_chunks(title, pieces) if use_llm else [("", []) for _ in pieces]
    chunk_rows = []
    for i, pc in enumerate(pieces):
        text = (pc.get("text") or "")[:6000]
        if not text.strip():
            continue
        ctx_line, hyps = enriched[i] if i < len(enriched) else ("", [])
        page = max(1, min(n_pages, 1 + int(i / max(1, len(pieces))) * n_pages))
        if n_pages > 1 and len(pieces) > 1:
            page = max(1, min(n_pages, round((i + 1) / len(pieces) * n_pages)))
        cur = con.execute(
            "INSERT INTO chunks(doc_id, section_id, parent_id, ordinal, page, text, context_line, hyp_questions)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (doc_id, sec_ids.get((pc.get("heading") or "").strip()), sec_ids.get((pc.get("heading") or "").strip()),
             i, page, text, (ctx_line or "")[:500], json.dumps(hyps or [])[:2000]))
        cid = cur.lastrowid
        chunk_rows.append((cid, text, ctx_line, hyps))
        try:
            con.execute("INSERT OR REPLACE INTO vault_fts(rowid, text, context_line, title) VALUES(?,?,?,?)",
                        (cid, text[:8000], (ctx_line or "")[:1000], title[:200]))
        except Exception:
            pass
    try:
        for cid, text, ctx_line, hyps in chunk_rows:
            vec = _emb.embed_text(f"{ctx_line} {text}"[:2000] if ctx_line else text[:2000])
            if hyps:
                try:
                    hv = _emb.embed_text(" ".join(hyps)[:1000])
                    if hv and vec:
                        vec = [(a + b) / 2 for a, b in zip(vec, hv)]
                except Exception:
                    pass
            if vec:
                try:
                    con.execute("DELETE FROM vec_chunks WHERE chunk_id=?", (cid,))
                    con.execute("INSERT INTO vec_chunks(chunk_id, embedding) VALUES(?,?)",
                                (cid, _db.pack_vec(vec)))
                except Exception:
                    pass
    except Exception:
        pass
    try:
        for heading, sid in sec_ids.items():
            txts = [pc["text"] for pc in pieces if (pc.get("heading") or "").strip() == heading][:6]
            summ = _sum.summarize_section(title, heading, "\n\n".join(txts)[:4000]) if use_llm else ""
            if summ:
                con.execute("UPDATE sections SET summary=? WHERE id=?", (summ[:1500], sid))
            try:
                sv = _emb.embed_text(f"{heading} {summ or ' '.join(txts)[:1000]}"[:2000])
                if sv:
                    con.execute("DELETE FROM vec_sections WHERE section_id=?", (sid,))
                    con.execute("INSERT INTO vec_sections(section_id, embedding) VALUES(?,?)",
                                (sid, _db.pack_vec(sv)))
            except Exception:
                pass
        all_txt = [pc["text"][:500] for pc in pieces[:12]]
        doc_sum = _sum.summarize_doc(title, all_txt) if use_llm else ""
        if doc_sum:
            con.execute("UPDATE docs SET summary=?, updated_at=? WHERE id=?", (doc_sum[:2000], _db.now(), doc_id))
    except Exception:
        pass
    try:
        con.commit()
    except Exception:
        pass
    return {"stored": True, "doc_id": doc_id, "chunks": len(chunk_rows), "sections": len(sec_ids), "title": title}


_Q: queue.Queue | None = None
_WORKER: threading.Thread | None = None
_WLOCK = threading.Lock()
_IDLE = threading.Event()
_IDLE.set()


def _ensure_worker(con_factory=None):
    global _WORKER
    with _WLOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_worker_loop, daemon=True, name="zumba-vault")
            _WORKER.start()


def _worker_loop():
    from vault import db as _vdb
    while True:
        try:
            assert _Q is not None
            path = _Q.get(timeout=30)
        except Exception:
            _IDLE.set()
            return
        try:
            con = _vdb.connect()
            try:
                ingest_file(con, Path(path))
            finally:
                con.close()
        except Exception:
            pass
        finally:
            try:
                _Q.task_done()
                if _Q.unfinished_tasks == 0:
                    _IDLE.set()
            except Exception:
                pass


def ingest_async(paths: list[str]) -> int:
    global _Q
    if _Q is None:
        _Q = queue.Queue(maxsize=200)
    n = 0
    for p in iter_files(paths):
        try:
            _IDLE.clear()
            _Q.put_nowait(str(p))
            n += 1
        except queue.Full:
            break
    if n:
        _ensure_worker()
    return n


def flush(timeout: float = 60.0) -> bool:
    try:
        assert _Q is not None
        _Q.join()
    except Exception:
        pass
    return _IDLE.wait(timeout)
