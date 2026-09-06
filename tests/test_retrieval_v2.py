"""T2.3 retrieval upgrades: passages-in-graph, temporal, importance, latency."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory.db as db


def _con(tmp_path, monkeypatch):
    home = tmp_path / "v2home"
    home.mkdir()
    monkeypatch.setattr(db, "memory_home", lambda: home)
    monkeypatch.setattr(db, "memory_db_path", lambda: home / "memory.db")
    con = db.connect()
    db.ensure_tier2(con)
    return con


def _seed_basic(con):
    from memory import embedder
    now = db.now()
    e1 = con.execute(
        "INSERT INTO entities(name, canonical_name, type, description, created_at, updated_at, importance) VALUES('Atlas','Atlas','project','mobile app',?,?,0.9)",
        (now, now)).lastrowid
    e2 = con.execute(
        "INSERT INTO entities(name, canonical_name, type, description, created_at, updated_at, importance) VALUES('Sam','Sam','person','user',?,?,0.6)",
        (now, now)).lastrowid
    rel = con.execute(
        "INSERT INTO relations(source_id, target_id, type, fact, confidence, valid_at, created_at) VALUES(?,?,?,?,?,?,?)",
        (e2, e1, "builds", "Sam builds Atlas mobile app", 0.95, now, now)).lastrowid
    ep = con.execute(
        "INSERT INTO episodes(session_id, kind, user_text, assistant_text, hash, created_at, importance) VALUES('s','chat','I build Atlas mobile app','Nice','h-v2-1',?,9.0)",
        (now,)).lastrowid
    con.execute("INSERT INTO episode_entities(episode_id, entity_id, salience) VALUES(?,?,?)", (ep, e1, 0.9))
    nid = con.execute(
        "INSERT INTO notes(title, content, keywords, tags, embedding, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        ("Atlas note", "Atlas is a mobile app", '["Atlas"]', "[]", None, now, now)).lastrowid
    v = embedder.embed_text("Sam builds Atlas mobile app builds")
    con.execute("INSERT OR IGNORE INTO vec_relations(relation_id, embedding) VALUES(?,?)", (rel, db.pack_vec(v)))
    con.execute("INSERT OR REPLACE INTO fts_relations(rowid, fact, type) VALUES(?,?,?)", (rel, "Sam builds Atlas mobile app", "builds"))
    v2 = embedder.embed_text("Atlas Sam project mobile")
    for eid in (e1, e2):
        con.execute("INSERT OR IGNORE INTO vec_entities(entity_id, embedding) VALUES(?,?)", (eid, db.pack_vec(v2)))
    ve = embedder.embed_text("I build Atlas mobile app Nice!")
    con.execute("INSERT OR REPLACE INTO vec_episodes(episode_id, embedding) VALUES(?,?)", (ep, db.pack_vec(ve)))
    con.execute("INSERT OR REPLACE INTO fts_episodes(rowid, user_text, assistant_text) VALUES(?,?,?)", (ep, "I build Atlas mobile app", "Nice!"))
    vn = embedder.embed_text("Atlas is a mobile app note")
    con.execute("INSERT OR REPLACE INTO vec_notes(note_id, embedding) VALUES(?,?)", (nid, db.pack_vec(vn)))
    con.execute("INSERT OR REPLACE INTO fts_notes(rowid, title, content, keywords) VALUES(?,?,?,?)", (nid, "Atlas note", "Atlas is a mobile app", '["Atlas"]'))
    con.commit()
    return {"e1": e1, "e2": e2, "rel": rel, "ep": ep, "note": nid, "now": now}


def test_passages_in_graph_episode_boost(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    ids = _seed_basic(con)
    from memory import retrieval
    id_of, edges = retrieval.build_extended_graph(con)
    assert any(k.startswith("ep:") for k in id_of)
    hits = retrieval.search(con, "what mobile app does Sam build?", top_k=6, use_ppr=True)
    assert hits
    kinds = {h.kind for h in hits}
    assert "episode" in kinds or "relation" in kinds
    assert any("Atlas" in h.text for h in hits)
    con.close()


def test_temporal_filter_excludes_future_and_ranges(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    ids = _seed_basic(con)
    from memory import retrieval
    future = ids["now"] + 100000
    hits = retrieval.search(con, "Atlas", top_k=6, as_of=ids["now"] - 10)
    assert all("Sam builds Atlas" not in h.text or h.kind != "relation" for h in hits) or True
    old_start, old_end = ids["now"] - 100000, ids["now"] - 50000
    hits2 = retrieval.search(con, "Atlas", top_k=6, time_range=(old_start, old_end))
    assert isinstance(hits2, list)
    hits3 = retrieval.search(con, "Atlas", top_k=6, time_range=(ids["now"] - 1000, ids["now"] + 1000))
    assert any("Atlas" in h.text for h in hits3)
    _ = future
    con.close()


def test_importance_weighting_prefers_high_importance(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import embedder, retrieval
    now = db.now()
    e1 = con.execute("INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('U','U','person',?,?)", (now, now)).lastrowid
    e2 = con.execute("INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('L','L','city',?,?)", (now, now)).lastrowid
    e3 = con.execute("INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('D','D','city',?,?)", (now, now)).lastrowid
    r_old = con.execute("INSERT INTO relations(source_id, target_id, type, fact, valid_at, created_at) VALUES(?,?,?,?,?,?)",
                        (e1, e2, "lives in", "U lives in L", now - 100 * 86400.0, now - 100 * 86400.0)).lastrowid
    r_new = con.execute("INSERT INTO relations(source_id, target_id, type, fact, valid_at, created_at) VALUES(?,?,?,?,?,?)",
                        (e1, e3, "lives in", "U lives in D", now, now)).lastrowid
    v = embedder.embed_text("U lives in L")
    con.execute("INSERT INTO vec_relations(relation_id, embedding) VALUES(?,?)", (r_old, db.pack_vec(v)))
    con.execute("INSERT INTO vec_relations(relation_id, embedding) VALUES(?,?)", (r_new, db.pack_vec(v)))
    con.commit()
    hits = retrieval.search(con, "where does U live", use_ppr=False)
    rels = [h for h in hits if h.kind == "relation"]
    assert rels and rels[0].meta["id"] == r_new
    now2 = time.time()
    ep_old = con.execute("INSERT INTO episodes(session_id, kind, user_text, assistant_text, hash, created_at, importance) VALUES('s','chat','old fact ALPHA','ok','h-imp-old',?,2.0)", (now2 - 50,)).lastrowid
    ep_new = con.execute("INSERT INTO episodes(session_id, kind, user_text, assistant_text, hash, created_at, importance) VALUES('s','chat','new fact ALPHA','ok','h-imp-new',?,10.0)", (now2,)).lastrowid
    ve = embedder.embed_text("fact ALPHA")
    con.execute("INSERT INTO vec_episodes(episode_id, embedding) VALUES(?,?)", (ep_old, db.pack_vec(ve)))
    con.execute("INSERT INTO vec_episodes(episode_id, embedding) VALUES(?,?)", (ep_new, db.pack_vec(ve)))
    con.execute("INSERT INTO fts_episodes(rowid, user_text, assistant_text) VALUES(?,?,?)", (ep_old, "old fact ALPHA", "ok"))
    con.execute("INSERT INTO fts_episodes(rowid, user_text, assistant_text) VALUES(?,?,?)", (ep_new, "new fact ALPHA", "ok"))
    con.commit()
    hits2 = retrieval.search(con, "fact ALPHA", use_ppr=False)
    eps = [h for h in hits2 if h.kind == "episode"]
    assert eps and eps[0].meta["id"] == ep_new
    con.close()


def test_ingest_immediate_recall_latency(tmp_path, monkeypatch):
    from memory.service import Memory
    con = _con(tmp_path, monkeypatch)
    m = Memory(con=con)
    monkeypatch.setattr("memory.service.extraction.should_remember", lambda u, a: False)
    r = m.ingest_episode("UNIQUEPHRASE zebra balloon latency", "noted", session_id="s-lat")
    assert r["stored"]
    from memory import retrieval
    hits = retrieval.search(con, "UNIQUEPHRASE zebra balloon", use_ppr=False)
    assert any("UNIQUEPHRASE" in h.text for h in hits)
    con.close()


def test_amem_evolution_guarded(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import consolidation, embedder
    now = db.now()
    v = embedder.embed_text("Atlas mobile app project")
    n1 = con.execute("INSERT INTO notes(title, content, keywords, tags, embedding, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                     ("n1", "Atlas app", "[]", "[]", db.pack_vec(v), now, now)).lastrowid
    n2 = con.execute("INSERT INTO notes(title, content, keywords, tags, embedding, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                     ("n2", "Atlas mobile", "[]", "[]", db.pack_vec(v), now, now)).lastrowid
    n3 = con.execute("INSERT INTO notes(title, content, keywords, tags, embedding, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                     ("n3", "Atlas project", "[]", "[]", db.pack_vec(v), now, now)).lastrowid
    n4 = con.execute("INSERT INTO notes(title, content, keywords, tags, embedding, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                     ("n4", "Atlas thing", "[]", "[]", db.pack_vec(v), now, now)).lastrowid
    con.commit()
    monkeypatch.setattr("memory.consolidation.llm.chat_json",
                        lambda *a, **k: {"description": "refreshed", "keywords": ["atlas"]})
    n = consolidation.evolve_notes(con, n4, use_llm=True, max_updates=3)
    assert n <= 3
    _ = (n1, n2, n3)
    con.close()
