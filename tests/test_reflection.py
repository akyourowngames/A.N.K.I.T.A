"""T2.2 reflection + T2.4 mood + T2.1 user facts + T2.6 prefs + T2.7 people."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory.db as db


def _con(tmp_path, monkeypatch):
    home = tmp_path / "rhome"
    home.mkdir()
    monkeypatch.setattr(db, "memory_home", lambda: home)
    monkeypatch.setattr(db, "memory_db_path", lambda: home / "memory.db")
    con = db.connect()
    db.ensure_tier2(con)
    return con


def test_reflection_heuristic_writes_followups_decisions_importance(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    now = db.now()
    e1 = con.execute("INSERT INTO episodes(session_id, kind, user_text, assistant_text, hash, created_at) VALUES('s1','chat','We decided to ship Atlas','Ok','h-r1',?)",
                     (now,)).lastrowid
    e2 = con.execute("INSERT INTO episodes(session_id, kind, user_text, assistant_text, hash, created_at) VALUES('s1','chat','I must finish the demo tomorrow','Ok','h-r2',?)",
                     (now,)).lastrowid
    con.commit()
    from memory import reflection as _ref
    exchanges = [{"user": "We decided to ship Atlas", "assistant": "Ok", "episode_id": e1},
                 {"user": "I must finish the demo tomorrow", "assistant": "Ok", "episode_id": e2}]
    monkeypatch.setattr("memory.llm.chat_json", lambda *a, **k: {"decisions": [{"text": "Ship Atlas", "reason": "team decision"}], "follow_ups": ["Finish the demo tomorrow"], "importance": [{"index": 0, "score": 8}, {"index": 1, "score": 7}], "mood": {"valence": 0.2, "energy": 0.6, "note": "focused"}})
    out = _ref.reflect_session(con, exchanges, session_id="s1", use_llm=True)
    assert out["applied"]["follow_ups"] >= 1
    assert out["applied"]["importance_set"] == 2
    assert con.execute("SELECT COUNT(*) FROM follow_ups WHERE done_at IS NULL").fetchone()[0] >= 1
    assert con.execute("SELECT importance FROM episodes WHERE id=?", (e1,)).fetchone()[0] != 5.0
    assert con.execute("SELECT COUNT(*) FROM session_moods").fetchone()[0] >= 1
    assert _ref.open_follow_ups(con)
    con.close()


def test_mood_scoring_and_chart(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import mood as _mood
    v, e = _mood.score_mood("I am so happy and grateful today, fantastic!")
    assert v > 0
    v2, _ = _mood.score_mood("I feel sad stressed and awful")
    assert v2 < 0
    _mood.record_mood(con, "s1", 0.8, 0.7, "great day")
    _mood.record_mood(con, "s2", -0.6, 0.3, "rough day")
    chart = _mood.render_chart(con)
    assert "MOOD" in chart and "avg" in chart
    assert "great day" in chart
    assert _mood.mood_context(con) != ""
    con.close()


def test_user_facts_and_profile_prepend(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from identity import userprofile as _up
    _up.upsert_fact(con, "likes", "Sam likes Rust", 0.8)
    con.commit()
    assert any(f["key"] == "likes" for f in _up.get_facts(con))
    n = _up.extract_user_facts_from_relations(con, [{"type": "prefers_brevity", "fact": "Give shorter answers", "confidence": 0.9, "source": "user"}])
    assert n >= 1
    home = tmp_path / "zup"
    home.mkdir()
    monkeypatch.setenv("ZUMBA_HOME", str(home))
    from identity import soul
    monkeypatch.setattr(soul, "_home", lambda: home)
    monkeypatch.setattr("memory.llm.chat_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    soul.bootstrap_flow({"sound": "terse", "keep": "Sam likes Rust"})
    assert "Sam likes Rust" in _up.profile_block()
    from memory.service import Memory
    m = Memory(con=con)
    monkeypatch.setattr("memory.service.retrieval.search", lambda con, q, top_k=8, max_bytes=6000, **kw: [])
    text, hits = m.recall_with_hits("anything")
    assert "Sam likes Rust" in text or "user.md" in text
    con.close()


def test_preferences_detect_and_propose(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import preferences as _prefs
    monkeypatch.setattr("memory.llm.chat_json", lambda *a, **k: {"prefs": [{"type": "prefers_brevity", "fact": "Give shorter, terser answers."}, {"type": "prefers_no_tables", "fact": "Avoid tables; use prose or bullets."}]})
    found = _prefs.detect_corrections("please be shorter, no tables ever")
    assert {f["type"] for f in found} >= {"prefers_brevity", "prefers_no_tables"}
    home = tmp_path / "zpref"
    home.mkdir()
    monkeypatch.setenv("ZUMBA_HOME", str(home))
    from identity import soul
    monkeypatch.setattr(soul, "_home", lambda: home)
    monkeypatch.setattr("memory.llm.chat_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    soul.bootstrap_flow({"sound": "terse"})
    now = db.now()
    e1 = con.execute("INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('user','user','person',?,?)", (now, now)).lastrowid
    e2 = con.execute("INSERT INTO entities(name, canonical_name, type, created_at, updated_at) VALUES('assistant_style','assistant_style','style',?,?)", (now, now)).lastrowid
    con.execute("INSERT INTO relations(source_id, target_id, type, fact, created_at) VALUES(?,?,?,?,?)",
                (e1, e2, "prefers_brevity", "Give shorter, terser answers.", now))
    con.commit()
    assert _prefs.active_preferences(con)
    path = _prefs.propose_voice_update(con)
    assert path and soul.has_proposal()
    con.close()


def test_people_ranking(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    now = db.now()
    a = con.execute("INSERT INTO entities(name, canonical_name, type, description, created_at, updated_at) VALUES('Mira','Mira','person','teammate',?,?)", (now, now)).lastrowid
    b = con.execute("INSERT INTO entities(name, canonical_name, type, description, created_at, updated_at) VALUES('Jon','Jon','person','friend',?,?)", (now, now)).lastrowid
    ep = con.execute("INSERT INTO episodes(session_id, kind, user_text, assistant_text, hash, created_at) VALUES('s','chat','met Mira','ok','h-p1',?)", (now,)).lastrowid
    con.execute("INSERT INTO episode_entities(episode_id, entity_id, salience) VALUES(?,?,?)", (ep, a, 0.9))
    con.execute("INSERT INTO episode_entities(episode_id, entity_id, salience) VALUES(?,?,?)", (ep, b, 0.4))
    con.execute("INSERT INTO relations(source_id, target_id, type, fact, created_at) VALUES(?,?, 'knows', 'user knows Mira', ?)", (a, b, now))
    con.commit()
    from memory import people as _ppl
    rows = _ppl.people_overview(con)
    assert rows and rows[0]["name"] == "Mira"
    assert "Mira" in _ppl.render_people(rows)
    con.close()


def test_briefing_compose_offline(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    from memory import briefing as _br
    con.execute("INSERT INTO follow_ups(text, created_at, source_session) VALUES(?,?,?)", ("Finish demo", db.now(), "s1"))
    con.execute("INSERT INTO communities(label, level, summary, created_at, updated_at) VALUES(?,?,?, ?,?)",
                ("c", 0, "Atlas project cluster", db.now(), db.now()))
    con.commit()
    text = _br.compose_daily(con, use_llm=False)
    assert "FOLLOW-UPS" in text and "Finish demo" in text
    con.close()
