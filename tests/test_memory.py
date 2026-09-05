"""Tests for the zumba memory package (LLM mocked)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory.db as db
from memory import graph, retrieval


@pytest.fixture()
def mem_db(tmp_path, monkeypatch):
    """Redirect the memory DB into a temp dir for the test."""
    home = tmp_path / "memhome"
    home.mkdir()
    monkeypatch.setattr(db, "memory_home", lambda: home)
    monkeypatch.setattr(db, "memory_db_path", lambda: home / "memory.db")
    con = db.connect()
    yield con
    con.close()


def test_schema_created(mem_db):
    for t in ["episodes", "entities", "aliases", "relations", "episode_entities",
              "notes", "note_links", "communities", "community_members", "core_blocks",
              "vec_entities", "fts_episodes"]:
        assert mem_db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0


def test_vec_roundtrip(mem_db):
    v = [0.1, -0.2, 0.3] * 128  # 384 dims
    blob = db.pack_vec(v)
    assert db.unpack_vec(blob) == pytest.approx(v)
    mem_db.execute("INSERT INTO vec_entities(entity_id, embedding) VALUES(1, ?)", (blob,))
    row = mem_db.execute(
        "SELECT entity_id, distance FROM vec_entities WHERE embedding MATCH ? ORDER BY distance LIMIT 1",
        (db.match_vec(v),),
    ).fetchone()
    assert row["entity_id"] == 1
    assert row["distance"] == pytest.approx(0.0, abs=1e-5)


def test_pagerank_hub_ranks_higher():
    id_of = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4}
    edges = [(0, 1, 1.0), (0, 2, 1.0), (0, 3, 1.0), (1, 4, 1.0)]
    ranks = graph.personalized_pagerank(id_of, edges, seeds={1: 1.0})
    assert ranks[0] > ranks[4]


def test_detect_communities_two_clusters():
    id_of = {n: i for i, n in enumerate("abcde")}
    edges = [(0, 1, 1.0), (1, 2, 1.0), (2, 0, 1.0), (3, 4, 1.0), (0, 3, 0.1)]
    comms = graph.detect_communities(id_of, edges)
    assert comms
    all_members = set().union(*(m for m, _ in comms))
    assert all_members == {"a", "b", "c", "d", "e"}


def test_reinforce_and_decay(mem_db):
    now = db.now()
    mem_db.execute(
        "INSERT INTO entities(id, name, canonical_name, type, created_at, updated_at, last_access, decay) VALUES(1,'x','x','t',?,?,?,1.0)",
        (now, now, now),
    )
    graph.reinforce(mem_db, [1])
    row = mem_db.execute("SELECT access_count, decay FROM entities WHERE id=1").fetchone()
    assert row["access_count"] == 1
    assert row["decay"] == pytest.approx(1.0)  # capped at 1.0
    # Age the entity, then decay.
    mem_db.execute("UPDATE entities SET last_access=? WHERE id=1", (db.now() - 10 * 86400.0,))
    graph.apply_time_decay(mem_db, half_life_days=5.0)
    row = mem_db.execute("SELECT decay FROM entities WHERE id=1").fetchone()
    assert row["decay"] < 1.0
def test_fts_query_sanitized():
    from memory.retrieval import _fts_query

    assert _fts_query('what game?? is "Ankit" building?') == "what OR game OR is OR Ankit OR building"
    assert _fts_query("!!!") == ""


def test_rrf_fusion_prefers_consistent_ids():
    from memory.retrieval import _rrf

    fused = _rrf([[(1, 0.9), (2, 0.8), (3, 0.7)], [(1, 0.9), (4, 0.5)], [(2, 0.8)]])
    assert fused[1] == max(fused.values())


def test_retrieval_search_finds_seeded_fact(mem_db):
    now = db.now()
    e1 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, description, created_at, updated_at) VALUES('Ankit','Ankit','person','A developer',?,?)",
        (now, now),
    ).lastrowid
    e2 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, description, created_at, updated_at) VALUES('A.N.K.I.T.A.','A.N.K.I.T.A.','project','A Godot game',?,?)",
        (now, now),
    ).lastrowid
    rel = mem_db.execute(
        "INSERT INTO relations(source_id, target_id, type, fact, valid_at, created_at) VALUES(?,?,?,?,?,?)",
        (e1, e2, "builds", "Ankit is building the game A.N.K.I.T.A.", now, now),
    ).lastrowid
    ep = mem_db.execute(
        "INSERT INTO episodes(session_id, kind, user_text, assistant_text, hash, created_at) VALUES('s','chat','I am building a game called A.N.K.I.T.A.','Nice!','h1',?)",
        (now,),
    ).lastrowid

    from memory import embedder

    for eid in (e1, e2):
        v = embedder.embed_text("Ankit A.N.K.I.T.A. game developer Godot")
        mem_db.execute("INSERT INTO vec_entities(entity_id, embedding) VALUES(?,?)", (eid, db.pack_vec(v)))
    v = embedder.embed_text("Ankit is building the game A.N.K.I.T.A. builds")
    mem_db.execute("INSERT INTO vec_relations(relation_id, embedding) VALUES(?,?)", (rel, db.pack_vec(v)))
    v = embedder.embed_text("I am building a game called A.N.K.I.T.A. Nice!")
    mem_db.execute("INSERT INTO vec_episodes(episode_id, embedding) VALUES(?,?)", (ep, db.pack_vec(v)))
    mem_db.execute("INSERT INTO fts_episodes(rowid, user_text, assistant_text) VALUES(?,?,?)", (ep, "I am building a game called A.N.K.I.T.A.", "Nice!"))
    mem_db.execute("INSERT INTO fts_relations(rowid, fact, type) VALUES(?,?,?)", (rel, "Ankit is building the game A.N.K.I.T.A.", "builds"))
    mem_db.commit()

    hits = retrieval.search(mem_db, "what game is Ankit building?", use_ppr=False)
    assert hits
    texts = " ".join(h.text for h in hits).lower()
    assert "a.n.k.i.t.a." in texts or "ankit" in texts
    assert hits[0].kind in ("relation", "entity", "episode")
def test_memory_ingest_dedupes_and_captures(mem_db, monkeypatch):
    from memory.service import Memory

    m = Memory(con=mem_db)
    monkeypatch.setattr("memory.service.extraction.should_remember", lambda u, a: False)
    r1 = m.ingest_episode("hello there friend", "Hi!", session_id="s")
    r2 = m.ingest_episode("hello there friend", "Hi!", session_id="s")
    assert r1["stored"] and not r1["extracted"]
    assert not r2["stored"] and r2["reason"] == "duplicate"
    assert mem_db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 1


def test_memory_ingest_full_pipeline_with_mock_llm(mem_db, monkeypatch):
    from memory.service import Memory

    m = Memory(con=mem_db)
    monkeypatch.setattr("memory.service.extraction.should_remember", lambda u, a: True)
    monkeypatch.setattr(
        "memory.service.extraction.extract_graph",
        lambda u, a, known=None: (
            [{"name": "Bob", "type": "person", "description": "The user"},
             {"name": "Rust", "type": "technology", "description": "A systems language"}],
            [{"source": "Bob", "target": "Rust", "type": "learns", "fact": "Bob is learning Rust", "confidence": 0.9}],
        ),
    )
    monkeypatch.setattr(
        "memory.service.extraction.decide_writes",
        lambda facts, existing: [{"index": 0, "op": "ADD", "target_id": None, "reason": "new"}],
    )
    monkeypatch.setattr("memory.service.consolidation.link_notes", lambda con, nid=None: 0)

    r = m.ingest_episode("I started learning Rust", "Great choice!", session_id="s")
    assert r["extracted"] and r["entities"] == 2 and r["relations"] == 1
    assert mem_db.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 2
    assert mem_db.execute("SELECT COUNT(*) FROM relations WHERE invalid_at IS NULL").fetchone()[0] == 1
    assert mem_db.execute("SELECT COUNT(*) FROM aliases").fetchone()[0] == 2
    assert mem_db.execute("SELECT COUNT(*) FROM episode_entities").fetchone()[0] == 2


def test_write_decision_update_invalidates_old_fact(mem_db, monkeypatch):
    from memory.service import Memory

    m = Memory(con=mem_db)
    now = db.now()
    e1 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('Bob','Bob','person',?,?)", (now, now)
    ).lastrowid
    e2 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('JS','JS','technology',?,?)", (now, now)
    ).lastrowid
    old = mem_db.execute(
        "INSERT INTO relations(source_id, target_id, type, fact, valid_at, created_at) VALUES(?,?,?,?,?,?)",
        (e1, e2, "learns", "Bob is learning JS", now, now),
    ).lastrowid

    monkeypatch.setattr(
        "memory.service.extraction.decide_writes",
        lambda facts, existing: [{"index": 0, "op": "UPDATE", "target_id": old, "reason": "superseded"}],
    )
    n = m._reconcile_relations(
        mem_db,
        [{"source": "Bob", "target": "JS", "type": "learns", "fact": "Bob switched to learning Rust", "confidence": 0.9}],
        {"Bob": e1, "JS": e2},
        episode_id=None,
    )
    assert n == 1
    assert mem_db.execute("SELECT invalid_at IS NOT NULL FROM relations WHERE id=?", (old,)).fetchone()[0] == 1
    assert mem_db.execute("SELECT COUNT(*) FROM relations WHERE invalid_at IS NULL").fetchone()[0] == 1


def test_forget_invalidates_but_keeps_history(mem_db):
    from memory.service import Memory

    m = Memory(con=mem_db)
    now = db.now()
    e1 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('Bob','Bob','person',?,?)", (now, now)
    ).lastrowid
    e2 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('X','X','thing',?,?)", (now, now)
    ).lastrowid
    mem_db.execute(
        "INSERT INTO relations(source_id, target_id, type, fact, valid_at, created_at) VALUES(?,?,?,?,?,?)",
        (e1, e2, "likes", "Bob likes X", now, now),
    )
    mem_db.commit()
    r = m.forget("Bob")
    assert r["forgot"]
    assert mem_db.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 1  # history kept
    assert mem_db.execute("SELECT COUNT(*) FROM relations WHERE invalid_at IS NULL").fetchone()[0] == 0


def test_stats_and_clear(mem_db):
    from memory.service import Memory

    m = Memory(con=mem_db)
    s = m.stats()
    assert s["episodes"] == 0 and s["entities"] == 0
    m.clear()
    assert m.stats()["entities"] == 0


# ---- regression tests: todo.txt fixes ----


def test_normalize_repairs_mojibake():
    from output import normalize_text

    apostrophe = "â€™"
    emdash = "â€" + chr(0x94)
    text = f"I{apostrophe}m sorry for the mix{emdash}up"
    assert normalize_text(text, allow_emoji=True) == "I\u2019m sorry for the mix\u2014up"
    assert normalize_text(text, allow_emoji=False) == "I'm sorry for the mix-up"
    you_are = "Youâ€™re"
    assert "Krish" in normalize_text(f"{you_are} Krish {emdash} hello", allow_emoji=False)


def test_capture_async_worker_processes_queue(mem_db, monkeypatch):
    from memory.service import Memory

    m = Memory(con=mem_db)
    calls = []
    monkeypatch.setattr(m, "ingest_episode", lambda u, a, session_id="", kind="chat": calls.append((u, a)) or {"stored": True})
    m.capture_async("hello", "hi", session_id="s")
    assert m.flush(timeout=10.0) is True
    assert calls == [("hello", "hi")]


def test_sweep_contradictions_invalidates_older(mem_db, monkeypatch):
    from memory import consolidation

    now = db.now()
    e1 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('user','user','person',?,?)", (now, now)
    ).lastrowid
    e2 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('Krish','Krish','person',?,?)", (now, now)
    ).lastrowid
    e3 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('Ankit','Ankit','person',?,?)", (now, now)
    ).lastrowid
    old = mem_db.execute(
        "INSERT INTO relations(source_id, target_id, type, fact, valid_at, created_at) VALUES(?,?,?,?,?,?)",
        (e1, e3, "is", "user is Ankit", now, now),
    ).lastrowid
    new = mem_db.execute(
        "INSERT INTO relations(source_id, target_id, type, fact, valid_at, created_at) VALUES(?,?,?,?,?,?)",
        (e1, e2, "is", "user is Krish", now + 1, now + 1),
    ).lastrowid
    mem_db.commit()
    # Non-contradicting fact must survive.
    e4 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('Godot','Godot','tool',?,?)", (now, now)
    ).lastrowid
    mem_db.execute(
        "INSERT INTO relations(source_id, target_id, type, fact, valid_at, created_at) VALUES(?,?,?,?,?,?)",
        (e1, e4, "uses", "user uses Godot", now, now),
    )
    mem_db.commit()

    monkeypatch.setattr(
        "memory.extraction.sweep_contradictions",
        lambda facts: [old],
    )
    n = consolidation.sweep_contradictions(mem_db)
    assert n == 1
    assert mem_db.execute("SELECT invalid_at IS NOT NULL FROM relations WHERE id=?", (old,)).fetchone()[0] == 1
    assert mem_db.execute("SELECT invalid_at IS NULL FROM relations WHERE id=?", (new,)).fetchone()[0] == 1
    assert mem_db.execute("SELECT invalid_at IS NULL FROM relations WHERE fact='user uses Godot'").fetchone()[0] == 1


def test_recency_breaks_ties_toward_newer_fact(mem_db):
    now = db.now()
    e1 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('U','U','person',?,?)", (now, now)
    ).lastrowid
    e2 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('L','L','city',?,?)", (now, now)
    ).lastrowid
    e3 = mem_db.execute(
        "INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('D','D','city',?,?)", (now, now)
    ).lastrowid
    r_old = mem_db.execute(
        "INSERT INTO relations(source_id, target_id, type, fact, valid_at, created_at) VALUES(?,?,?,?,?,?)",
        (e1, e2, "lives in", "U lives in L", now - 100 * 86400.0, now - 100 * 86400.0),
    ).lastrowid
    r_new = mem_db.execute(
        "INSERT INTO relations(source_id, target_id, type, fact, valid_at, created_at) VALUES(?,?,?,?,?,?)",
        (e1, e3, "lives in", "U lives in D", now, now),
    ).lastrowid
    from memory import embedder

    v = embedder.embed_text("U lives in L")
    mem_db.execute("INSERT INTO vec_relations(relation_id, embedding) VALUES(?,?)", (r_old, db.pack_vec(v)))
    mem_db.execute("INSERT INTO vec_relations(relation_id, embedding) VALUES(?,?)", (r_new, db.pack_vec(v)))
    mem_db.commit()

    hits = retrieval.search(mem_db, "where does U live", use_ppr=False)
    rels = [h for h in hits if h.kind == "relation"]
    assert rels
    # The newer fact must outrank the identically-scored older one.
    assert rels[0].meta["id"] == r_new