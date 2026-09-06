"""Vault orchestrator: ingest + retrieve + status + CLI helpers."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from vault import db as _db

_cache: dict = {}
_lock = threading.Lock()


def enabled() -> bool:
    return os.getenv("ZUMBA_NO_VAULT", "") != "1"


class Vault:
    def __init__(self, con=None):
        self._own = con is None
        self._con = con

    def _open(self):
        return self._con if self._con is not None else _db.connect()

    def close(self):
        if self._own and self._con is not None:
            try:
                self._con.close()
            except Exception:
                pass
            self._con = None

    def add(self, targets: list[str], use_llm: bool = True) -> dict:
        from vault import ingest as _ing
        con = self._open()
        files = _ing.iter_files(targets)
        ok, dup, failed = 0, 0, []
        ids = []
        try:
            for f in files:
                try:
                    r = _ing.ingest_file(con, f, use_llm=use_llm)
                except Exception as exc:
                    failed.append(f"{f}: {exc}")
                    continue
                if r.get("stored"):
                    ok += 1
                    ids.append(r.get("doc_id"))
                elif r.get("reason") == "duplicate":
                    dup += 1
                else:
                    failed.append(f"{f}: {r.get('reason')}")
        finally:
            if self._own:
                con.close()
        return {"files": len(files), "ingested": ok, "duplicates": dup,
                "failed": failed, "doc_ids": ids}

    def find(self, query: str, k: int = 0, doc_filter: str = "") -> list[dict]:
        from vault import retrieve as _ret
        con = self._open()
        try:
            return _ret.find(con, query, k=k, doc_filter=doc_filter)
        finally:
            if self._own:
                con.close()

    def context_block(self, query: str, k: int = 0) -> str:
        from vault import retrieve as _ret
        con = self._open()
        try:
            hits = _ret.search(con, query, k=k or _ret.top_k())
            return _ret.pack_context(hits)
        finally:
            if self._own:
                con.close()

    def ask(self, query: str, k: int = 0, use_llm: bool = True) -> str:
        from vault import retrieve as _ret
        block = self.context_block(query, k=k)
        if not block:
            return "ERROR: nothing in the vault answers that yet — add files with `zumba vault add <path>`."
        if not use_llm:
            return block
        try:
            from memory import llm as _llm
            return _llm.chat_text(
                "Answer ONLY from this document evidence. Cite every claim like [Title p.N]. "
                "If the evidence is insufficient, say so.\n\nQUESTION: " + query[:800] +
                "\n\nEVIDENCE:\n" + block[:12000],
                system="You answer strictly from cited document evidence.",
                max_tokens=1200).strip()
        except Exception as exc:
            return block + f"\n(LLM unavailable: {exc})"

    def doc(self, ref: str) -> str:
        con = self._open()
        try:
            try:
                did = int(str(ref).strip())
                row = con.execute("SELECT * FROM docs WHERE id=?", (did,)).fetchone()
            except Exception:
                row = None
            if row is None:
                like = f"%{str(ref).strip()[:80]}%"
                row = con.execute("SELECT * FROM docs WHERE title LIKE ? OR path LIKE ? LIMIT 1",
                                  (like, like)).fetchone()
            if row is None:
                return f"ERROR: no vault doc matching '{ref}'."
            d = dict(row)
            secs = con.execute("SELECT heading, level, summary FROM sections WHERE doc_id=? ORDER BY id",
                               (d["id"],)).fetchall()
            n_chunks = con.execute("SELECT COUNT(*) FROM chunks WHERE doc_id=?", (d["id"],)).fetchone()[0]
            lines = [f"{d['title']} ({d['kind']}, {d['n_pages']}p, {n_chunks} chunks, {d['status']})",
                     (d["summary"] or "(no summary yet)")[:800], "", "Outline:"]
            for s in secs[:30]:
                lines.append(f"{'  ' * max(0, int(s['level']) - 1)}- {s['heading'] or '(untitled)'}")
            return "\n".join(lines)
        finally:
            if self._own:
                con.close()

    def read_section(self, doc: str, section: str) -> str:
        con = self._open()
        try:
            like = f"%{doc.strip()[:80]}%"
            try:
                did = int(str(doc).strip())
                drow = con.execute("SELECT id, title FROM docs WHERE id=?", (did,)).fetchone()
            except Exception:
                drow = None
            if drow is None:
                drow = con.execute("SELECT id, title FROM docs WHERE title LIKE ? LIMIT 1", (like,)).fetchone()
            if drow is None:
                return f"ERROR: no vault doc matching '{doc}'."
            slike = f"%{section.strip()[:80]}%"
            srow = con.execute("SELECT id, heading FROM sections WHERE doc_id=? AND heading LIKE ? LIMIT 1",
                               (drow["id"], slike)).fetchone()
            if srow is None:
                return f"ERROR: no section matching '{section}' in '{drow['title']}'."
            chunks = con.execute("SELECT text FROM chunks WHERE section_id=? ORDER BY ordinal",
                                 (srow["id"],)).fetchall()
            body = "\n\n".join(c["text"] for c in chunks)[:8000]
            return f"{drow['title']} § {srow['heading']}\n\n{body}"
        finally:
            if self._own:
                con.close()

    def forget(self, ref: str) -> dict:
        con = self._open()
        try:
            try:
                did = int(str(ref).strip())
            except Exception:
                like = f"%{str(ref).strip()[:80]}%"
                row = con.execute("SELECT id FROM docs WHERE title LIKE ? LIMIT 1", (like,)).fetchone()
                did = row["id"] if row else None
            if not did:
                return {"forgot": False, "reason": "not found"}
            for t in ("chunks", "sections"):
                con.execute(f"DELETE FROM {t} WHERE doc_id=?", (did,))
            try:
                con.execute("DELETE FROM vec_chunks WHERE chunk_id NOT IN (SELECT id FROM chunks)")
                con.execute("DELETE FROM vec_sections WHERE section_id NOT IN (SELECT id FROM sections)")
                con.execute("DELETE FROM vault_fts WHERE rowid NOT IN (SELECT id FROM chunks)")
            except Exception:
                pass
            con.execute("DELETE FROM docs WHERE id=?", (did,))
            con.commit()
            return {"forgot": True, "doc_id": did}
        finally:
            if self._own:
                con.close()

    def status(self) -> dict:
        con = self._open()
        try:
            def c(sql):
                try:
                    return con.execute(sql).fetchone()[0]
                except Exception:
                    return 0
            return {"docs": c("SELECT COUNT(*) FROM docs WHERE status='ok'"),
                    "failed": c("SELECT COUNT(*) FROM docs WHERE status!='ok'"),
                    "sections": c("SELECT COUNT(*) FROM sections"),
                    "chunks": c("SELECT COUNT(*) FROM chunks"),
                    "watch": _db.watch_paths(),
                    "database": str(_db.vault_db_path())}
        finally:
            if self._own:
                con.close()

    def reindex(self, use_llm: bool = True) -> dict:
        con = self._open()
        try:
            paths = [r["path"] for r in con.execute("SELECT path FROM docs").fetchall() if r["path"]]
            con.execute("DELETE FROM chunks")
            con.execute("DELETE FROM sections")
            con.execute("DELETE FROM docs")
            try:
                con.execute("DELETE FROM vec_chunks")
                con.execute("DELETE FROM vec_sections")
                con.execute("DELETE FROM vault_fts")
            except Exception:
                pass
            con.commit()
        finally:
            if self._own:
                con.close()
        return self.add(paths, use_llm=use_llm)


def get_vault():
    with _lock:
        if "v" not in _cache:
            _cache["v"] = Vault()
        return _cache["v"]


def docish(query: str) -> bool:
    low = f" {(query or '').lower()} "
    keys = ("doc", "file", "pdf", "contract", "lease", "email", "report", "section",
            "page", "clause", "summar", "what does", "find the", "according to", "quote")
    if any(k in low for k in keys):
        return True
    return "?" in (query or "") and len((query or "").split()) > 4
