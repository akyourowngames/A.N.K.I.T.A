import time
import pytest
from memory import db


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'memory_home', lambda: tmp_path)
    monkeypatch.setattr(db, 'memory_db_path', lambda: tmp_path / 'memory.db')
    connection = db.connect()
    yield connection
    connection.close()


def test_expired_followup_is_not_returned_but_original_is_preserved(con):
    from memory import reflection, task_lifecycle
    now = time.time()
    fid = con.execute('INSERT INTO follow_ups(text,created_at,source_session) VALUES(?,?,?)',
                      ('Book flight for tomorrow', now - 7 * 86400, 'trip')).lastrowid
    task_lifecycle.set_policy(con, 'follow_up', fid, expires_at=now - 6 * 86400,
                              dormant_at=now - 6 * 86400, reason='Travel date passed')
    con.commit()
    assert reflection.open_follow_ups(con) == []
    assert con.execute('SELECT text FROM follow_ups WHERE id=?', (fid,)).fetchone()[0] == 'Book flight for tomorrow'
    assert task_lifecycle.state(con, 'follow_up', fid, now=now) == 'expired'


def test_legacy_ignored_followup_becomes_dormant_without_model(con):
    from memory import reflection
    con.execute('INSERT INTO follow_ups(text,created_at,source_session) VALUES(?,?,?)',
                ('Which departure airport?', time.time() - 7 * 86400, 'trip'))
    con.commit()
    assert reflection.open_follow_ups(con) == []


def test_expired_goal_is_excluded_from_context_and_nudges(con, monkeypatch):
    from memory import goals, proactive, task_lifecycle
    now = time.time()
    goal = goals.create_goal(con, 'Book the flight', deadline=now - 86400, use_llm=False)
    task_lifecycle.set_policy(con, 'goal', goal['id'], expires_at=now - 86400,
                              dormant_at=now - 86400, reason='Trip passed')
    con.commit()
    monkeypatch.setattr(proactive, 'enabled', lambda con=None: True)
    assert 'Book the flight' not in goals.goal_context(con)
    assert not proactive.tick(con, use_llm=False, force=True, now=now)['nudges']
    assert goals.get_goal(con, goal['id'])['title'] == 'Book the flight'


def test_nudge_budget_is_per_item_and_reads_do_not_reactivate(con):
    from memory import task_lifecycle
    now = time.time()
    task_lifecycle.set_policy(con, 'goal', 10, dormant_at=now + 86400, reason='Current project')
    assert task_lifecycle.claim_nudge(con, 'goal', 10, now=now)
    assert not task_lifecycle.claim_nudge(con, 'goal', 10, now=now + 7200)
    assert task_lifecycle.state(con, 'goal', 10, now=now + 90000) == 'dormant'


def test_lifecycle_model_gets_original_time_and_validates_reference(con, monkeypatch):
    from memory import task_lifecycle
    created = time.time() - 7 * 86400
    fid = con.execute('INSERT INTO follow_ups(text,created_at,source_session) VALUES(?,?,?)',
                      ('Book a flight for tomorrow', created, 'trip')).lastrowid
    def classify(prompt, **kwargs):
        assert str(created) in prompt
        return {'items': [{'kind': 'follow_up', 'id': fid, 'expires_at': created + 2 * 86400,
                           'dormant_at': created + 86400, 'reason': 'Travel date passed',
                           'evidence': 'Book a flight for tomorrow'}]}
    monkeypatch.setattr('memory.llm.chat_json', classify)
    assert task_lifecycle.review_pending(con) == 1
    assert task_lifecycle.state(con, 'follow_up', fid) == 'expired'


def test_background_review_cannot_renew_ignored_intent(con, monkeypatch):
    from memory import task_lifecycle, reflection
    now = time.time()
    fid = con.execute('INSERT INTO follow_ups(text,created_at,source_session) VALUES(?,?,?)',
                      ('Finish travel plan', now - 7 * 86400, 'trip')).lastrowid
    assert reflection.open_follow_ups(con) == []
    monkeypatch.setattr('memory.llm.chat_json', lambda *a, **k: {'items': [
        {'kind': 'follow_up', 'id': fid, 'dormant_at': now + 86400, 'evidence': 'Finish travel plan'}]})
    task_lifecycle.review_pending(con)
    assert task_lifecycle.state(con, 'follow_up', fid) == 'dormant'
    task_lifecycle.reactivate(con, 'follow_up', fid, until=now + 86400)
    assert task_lifecycle.state(con, 'follow_up', fid) == 'active'
    task_lifecycle.dismiss(con, 'follow_up', fid)
    assert reflection.open_follow_ups(con) == []


def test_delayed_reflection_keeps_source_clock_and_deduplicates(con, monkeypatch):
    from memory import reflection
    now = time.time()
    exchanges = [{'user': 'Book flight tomorrow', 'assistant': 'Which airport?', 'created_at': now - 7 * 86400}]
    result = {'follow_ups': [{'text': 'Book flight tomorrow', 'index': 0, 'evidence': 'Book flight tomorrow',
                            'expires_at': now - 5 * 86400, 'dormant_at': now - 6 * 86400}]}
    reflection.apply_reflection(con, exchanges, result, 'trip', use_llm=False)
    reflection.apply_reflection(con, exchanges, result, 'trip', use_llm=False)
    assert reflection.open_follow_ups(con) == []
    rows = con.execute('SELECT created_at FROM follow_ups').fetchall()
    assert len(rows) == 1
    assert rows[0]['created_at'] == exchanges[0]['created_at']


def test_task_tool_dismisses_but_retains_original(con, monkeypatch):
    import asyncio
    import json
    from mcpclient import builtin
    from memory import goals, task_lifecycle
    goal = goals.create_goal(con, 'Plan trip', use_llm=False)
    # Handler owns its connection; share the same isolated DB via the fixture.
    result = asyncio.run(builtin.handle(None, 'task_update', {'kind': 'goal', 'id': goal['id'], 'action': 'dismiss'}))
    assert json.loads(result)['state'] == 'dismissed'
    assert task_lifecycle.state(con, 'goal', goal['id']) == 'dismissed'
    assert goals.get_goal(con, goal['id'])['title'] == 'Plan trip'
