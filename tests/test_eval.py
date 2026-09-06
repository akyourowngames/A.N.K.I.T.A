"""T2.8 eval harness: generation, deterministic judge, run storage."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory.db as db


def _con(tmp_path, monkeypatch):
    home = tmp_path / "ehome"
    home.mkdir()
    monkeypatch.setattr(db, "memory_home", lambda: home)
    monkeypatch.setattr(db, "memory_db_path", lambda: home / "memory.db")
    con = db.connect()
    db.ensure_tier2(con)
    return con


def _seed(con):
    now = db.now()
    e1 = con.execute(
        "INSERT INTO entities(name, canonical_name, type, description, created_at, updated_at) VALUES('Atlas','Atlas','project','mobile app',?,?)",
        (now, now)).lastrowid
    e2 = con.execute(
        "INSERT INTO entities(name, canonical_name, type, description, created_at, updated_at) VALUES('Sam','Sam','person','user',?,?)",
        (now, now)).lastrowid
    r = con.execute(
        "INSERT INTO relations(source_id, target_id, type, fact, valid_at, created_at) VALUES(?,?,?,?,?,?)",
        (e2, e1, "builds", "Sam builds Atlas mobile app", now, now)).lastrowid
    ep = con.execute(
        "INSERT INTO episodes(session_id, kind, user_text, assistant_text, hash, created_at, importance) VALUES('s','chat','I build Atlas','Nice','h-eval-1',?,8.0)",
        (now,)).lastrowid
    con.commit()
    return r, ep


def test_generate_pairs_offline(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    _seed(con)
    from memory import eval as _eval
    pairs = _eval.generate_pairs(con, use_llm=False)
    assert pairs
    assert {p["category"] for p in pairs} & {"single-hop", "temporal", "update"}
    assert con.execute("SELECT COUNT(*) FROM eval_pairs").fetchone()[0] >= len(pairs)
    con.close()


def test_judge_containment_fallback():
    from memory.eval import judge_pair
    assert judge_pair("q", "Sam builds Atlas mobile app", "[relation] Sam builds Atlas mobile app", use_llm=False) is True
    assert judge_pair("q", "Sam builds Atlas mobile app", "[relation] nothing about cooking here", use_llm=False) is False


def test_run_eval_stores_run(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    _seed(con)
    from memory import eval as _eval
    from memory import embedder
    now = db.now()
    rel = con.execute("SELECT id FROM relations").fetchone()["id"]
    v = embedder.embed_text("Sam builds Atlas mobile app builds")
    con.execute("INSERT OR IGNORE INTO vec_relations(relation_id, embedding) VALUES(?,?)", (rel, db.pack_vec(v)))
    con.execute("INSERT OR REPLACE INTO fts_relations(rowid, fact, type) VALUES(?,?,?)", (rel, "Sam builds Atlas mobile app", "builds"))
    con.commit()
    report = _eval.run_eval(con=con, use_llm=False)
    assert report["total"] > 0 and report["hit_rate"] >= 0.5
    assert con.execute("SELECT COUNT(*) FROM eval_runs").fetchone()[0] == 1
    assert _eval.last_runs(con)
    con.close()


def test_eval_empty_db_no_crash(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import eval as _eval
    report = _eval.run_eval(con=con, use_llm=False)
    assert report["total"] == 0 and report["hit_rate"] == 0.0
    con.close()
