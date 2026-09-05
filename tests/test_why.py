"""Tests for /why memory provenance (LLM mocked where needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory.db as db


class _Hit:
    def __init__(self, kind, text, score, meta):
        self.kind = kind
        self.text = text
        self.score = score
        self.meta = meta


def _mem(tmp_path, monkeypatch):
    home = tmp_path / "whyhome"
    home.mkdir(exist_ok=True)
    monkeypatch.setattr(db, "memory_home", lambda: home)
    monkeypatch.setattr(db, "memory_db_path", lambda: home / "memory.db")
    from memory.service import Memory

    return Memory(con=db.connect())


def test_recall_with_hits_passthrough(tmp_path, monkeypatch):
    m = _mem(tmp_path, monkeypatch)
    hits = [_Hit("relation", "Atlas is a mobile app", 0.92, {"id": 7}),
            _Hit("entity", "Atlas [project]: mobile app", 0.31, {"id": 3})]
    monkeypatch.setattr("memory.service.retrieval.search", lambda con, q, top_k=8, max_bytes=6000: hits)
    text, prove = m.recall_with_hits("what is Atlas?", top_k=5, max_bytes=3500)
    assert "[relation] Atlas is a mobile app" in text
    assert len(prove) == 2
    assert prove[0] == {"kind": "relation", "score": 0.92, "meta": {"id": 7}, "snippet": "Atlas is a mobile app"}
    m.close()


def test_recall_still_returns_text(tmp_path, monkeypatch):
    m = _mem(tmp_path, monkeypatch)
    monkeypatch.setattr("memory.service.retrieval.search", lambda con, q, top_k=8, max_bytes=6000: [])
    out = m.recall("anything")
    assert isinstance(out, str)
    m.close()


def test_why_render_with_and_without_hits():
    import main

    sid = "why-test-session"
    main._why_store(sid, "what is Atlas?", "[relation] Atlas is a mobile app",
                    [{"kind": "relation", "score": 0.92, "meta": {"id": 7}, "snippet": "Atlas is a mobile app"}])
    rendered = main._why_render(sid)
    assert "what is Atlas?" in rendered
    assert "relation" in rendered and "0.92" in rendered and "id=7" in rendered

    main._why_store("why-empty", "hi", "", [])
    assert "nothing recalled" in main._why_render("why-empty").lower()
    assert "nothing recalled" in main._why_render("why-never-seen").lower()
