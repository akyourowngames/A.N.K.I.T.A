"""Vault retrieval: known-question hit, vocab mismatch via hyp index,
small-to-big parent expansion, budget, rerank parity, citations."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

from vault import db as _db


def _con(tmp_path, monkeypatch):
    home = tmp_path / "vhome"
    home.mkdir()
    monkeypatch.setattr(_db, "vault_home", lambda: home)
    monkeypatch.setattr(_db, "vault_db_path", lambda: home / "vault.db")
    monkeypatch.setattr(_db, "vault_raw_dir", lambda: home / "raw")
    con = _db.connect()
    return con, home


def _seed(con, monkeypatch, ctx_lines=True):
    from vault import chunker as _ch
    md = ("# Lease Agreement 2026\n\n## Pet Policy\n\nTenants may keep one small dog "
          "with a refundable pet deposit of two hundred dollars. Cats are also allowed.\n\n"
          "## Rent\n\nMonthly rent is one thousand dollars due on the first.")
    pieces = _ch.chunk_markdown(md, target_tokens=28, overlap=6)
    assert len(pieces) >= 2, pieces
    now = _db.now()
    con.execute(
        "INSERT INTO docs(hash, path, mtime, kind, title, n_pages, summary, status, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("h-seed", "lease.md", now, "md", "Lease Agreement 2026", 2, "Lease about pets and rent.", "ok", now, now))
    doc_id = con.execute("SELECT id FROM docs WHERE hash='h-seed'").fetchone()["id"]
    sec_ids: dict[str, int] = {}
    for pc in pieces:
        key = (pc.get("heading") or "").strip()
        if key not in sec_ids:
            cur = con.execute("INSERT INTO sections(doc_id, heading, level, summary) VALUES(?,?,?,?)",
                              (doc_id, key[:300], 1, f"Section about {key}." if key else ""))
            sec_ids[key] = cur.lastrowid
    from memory import embedder as _emb
    for i, pc in enumerate(pieces):
        ctx_line = f"This chunk is from the {pc['heading']} section of the Lease Agreement 2026." if ctx_lines else ""
        hyps = (["Can I have a dog?", "What is the pet deposit?"] if "dog" in pc["text"]
                else ["How much is the rent?"] if "rent" in pc["text"].lower() else [])
        sid = sec_ids.get((pc.get("heading") or "").strip())
        cur = con.execute(
            "INSERT INTO chunks(doc_id, section_id, parent_id, ordinal, page, text, context_line, hyp_questions)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (doc_id, sid, sid, i, 1 + (i // 2), pc["text"], ctx_line, json.dumps(hyps)))
        cid = cur.lastrowid
        vec = _emb.embed_text(f"{ctx_line} {pc['text']}"[:2000])
        if hyps:
            hv = _emb.embed_text(" ".join(hyps))
            if hv and vec:
                vec = [(a + b) / 2 for a, b in zip(vec, hv)]
        con.execute("DELETE FROM vec_chunks WHERE chunk_id=?", (cid,))
        con.execute("INSERT INTO vec_chunks(chunk_id, embedding) VALUES(?,?)",
                    (cid, _db.pack_vec(vec)))
        con.execute("INSERT OR REPLACE INTO vault_fts(rowid, text, context_line, title) VALUES(?,?,?,?)",
                    (cid, pc["text"][:8000], ctx_line[:1000], "Lease Agreement 2026"))
    con.commit()
    return doc_id


def test_known_question_hits_right_chunk(tmp_path, monkeypatch):
    con, _ = _con(tmp_path, monkeypatch)
    _seed(con, monkeypatch)
    from vault import retrieve as _ret
    hits = _ret.search(con, "can I keep a dog in the flat?", k=3, rerank_on=False)
    assert hits and any("dog" in h.text.lower() for h in hits)
    con.close()


def test_vocab_mismatch_solved_by_hyp_index(tmp_path, monkeypatch):
    con, _ = _con(tmp_path, monkeypatch)
    _seed(con, monkeypatch)
    from vault import retrieve as _ret
    hits = _ret.search(con, "what is the refundable pet deposit amount?", k=3, rerank_on=False)
    assert hits and any("two hundred" in h.text.lower() for h in hits)
    con.close()


def test_small_to_big_returns_parent_section(tmp_path, monkeypatch):
    con, _ = _con(tmp_path, monkeypatch)
    _seed(con, monkeypatch)
    from vault import retrieve as _ret
    hits = _ret.search(con, "pet policy dog", k=2, rerank_on=False)
    assert hits and "Pet Policy" in hits[0].text
    con.close()


def test_citations_and_budget(tmp_path, monkeypatch):
    con, _ = _con(tmp_path, monkeypatch)
    _seed(con, monkeypatch)
    from vault import retrieve as _ret
    hits = _ret.search(con, "rent", k=6, rerank_on=False)
    assert hits
    assert all(h.meta.get("citation", "").startswith("[Lease Agreement 2026 p.") for h in hits)
    block = _ret.pack_context(hits, max_chars=500)
    assert block.startswith("[VAULT CONTEXT]") and len(block) <= 3000
    con.close()


def test_rerank_parity_mocked(tmp_path, monkeypatch):
    con, _ = _con(tmp_path, monkeypatch)
    _seed(con, monkeypatch)
    from vault import retrieve as _ret
    off = _ret.search(con, "dog rent lease", k=3, rerank_on=False)
    monkeypatch.setattr("vault.rerank.rerank", lambda q, texts, top_k=6: list(range(min(top_k, len(texts)))))
    on = _ret.search(con, "dog rent lease", k=3, rerank_on=True)
    assert [h.meta.get("id") for h in off] == [h.meta.get("id") for h in on]
    con.close()


def test_docish_and_kill_switch(monkeypatch):
    from vault import service as _svc
    assert _svc.docish("what does my lease say about pets?") is True
    assert _svc.docish("hello") is False
    monkeypatch.setenv("ZUMBA_NO_VAULT", "1")
    assert _svc.enabled() is False
    import mcpclient.builtin as _b
    names = [t["function"]["name"] for t in _b.visible_tools()]
    assert not any("__vault_" in n for n in names)
    monkeypatch.delenv("ZUMBA_NO_VAULT", raising=False)
