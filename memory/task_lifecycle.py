"""Finite task attention with model-derived expiry; original memories remain intact."""
import json
import math
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_lifecycles (
 kind TEXT NOT NULL, item_id INTEGER NOT NULL, expires_at REAL, dormant_at REAL,
 dismissed_at REAL, reason TEXT NOT NULL DEFAULT '', reviewed_at REAL,
 PRIMARY KEY(kind,item_id)
);
CREATE TABLE IF NOT EXISTS task_nudges (
 kind TEXT NOT NULL, item_id INTEGER NOT NULL, event_key TEXT NOT NULL,
 created_at REAL NOT NULL, PRIMARY KEY(kind,item_id,event_key)
);
"""


def ensure_schema(con):
    # Individual statements avoid executescript's implicit commit of callers' writes.
    for statement in _SCHEMA.split(';'):
        if statement.strip():
            con.execute(statement)


def set_policy(con, kind, item_id, expires_at=None, dormant_at=None, reason='', reviewed=True):
    ensure_schema(con)
    if kind not in ('goal', 'follow_up'):
        raise ValueError('Unknown lifecycle record kind')
    for value in (expires_at, dormant_at):
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
            raise ValueError('Lifecycle times must be positive finite epoch timestamps')
    con.execute('INSERT INTO task_lifecycles(kind,item_id,expires_at,dormant_at,reason,reviewed_at) VALUES(?,?,?,?,?,?) '
                'ON CONFLICT(kind,item_id) DO UPDATE SET expires_at=excluded.expires_at,dormant_at=excluded.dormant_at,reason=excluded.reason,reviewed_at=excluded.reviewed_at',
                (kind, item_id, expires_at, dormant_at, reason[:600], time.time() if reviewed else None))


def seed(con, kind, record):
    ensure_schema(con)
    if con.execute('SELECT 1 FROM task_lifecycles WHERE kind=? AND item_id=?', (kind, record['id'])).fetchone():
        return
    # This is a finite attention budget, not a semantic classification or deletion.
    created = float(record.get('created_at') or time.time())
    dormant = created + 2 * 86400
    deadline = record.get('deadline')
    if isinstance(deadline, (int, float)) and deadline > 0:
        dormant = min(dormant, deadline)
    set_policy(con, kind, record['id'], dormant_at=dormant,
               reason='Unreviewed task: stop prompting after its attention window', reviewed=False)


def state(con, kind, item_id, now=None):
    ensure_schema(con)
    now = time.time() if now is None else now
    row = con.execute('SELECT * FROM task_lifecycles WHERE kind=? AND item_id=?', (kind, item_id)).fetchone()
    if not row:
        return 'unreviewed'
    if row['dismissed_at'] is not None:
        return 'dismissed'
    if row['expires_at'] is not None and row['expires_at'] <= now:
        return 'expired'
    if row['dormant_at'] is not None and row['dormant_at'] <= now:
        return 'dormant'
    return 'active'


def eligible(con, kind, record, now=None):
    seed(con, kind, record)
    return state(con, kind, record['id'], now) == 'active'


def claim_nudge(con, kind, item_id, now=None, event_key='follow_up'):
    ensure_schema(con)
    now = time.time() if now is None else now
    if state(con, kind, item_id, now) != 'active':
        return False
    cur = con.execute('INSERT OR IGNORE INTO task_nudges(kind,item_id,event_key,created_at) VALUES(?,?,?,?)',
                      (kind, item_id, event_key, now))
    con.commit()
    return cur.rowcount == 1


def dismiss(con, kind, item_id):
    ensure_schema(con)
    con.execute('UPDATE task_lifecycles SET dismissed_at=? WHERE kind=? AND item_id=?', (time.time(), kind, item_id))
    con.commit()


def reactivate(con, kind, item_id, until, expires_at=None):
    if not isinstance(until, (int, float)) or not math.isfinite(until) or until <= time.time():
        raise ValueError('Renewal needs a future attention deadline')
    if expires_at is not None and expires_at <= time.time():
        raise ValueError('An expired action needs a new future usefulness window')
    set_policy(con, kind, item_id, expires_at=expires_at, dormant_at=until, reason='User explicitly renewed this task')
    con.execute('UPDATE task_lifecycles SET dismissed_at=NULL WHERE kind=? AND item_id=?', (kind, item_id))
    con.execute('DELETE FROM task_nudges WHERE kind=? AND item_id=?', (kind, item_id))
    con.commit()


def review_pending(con, limit=24):
    from . import llm
    ensure_schema(con)
    candidates = []
    for kind, query in (
        ('follow_up', "SELECT id,text,created_at FROM follow_ups WHERE done_at IS NULL AND NOT EXISTS (SELECT 1 FROM task_lifecycles l WHERE l.kind='follow_up' AND l.item_id=follow_ups.id AND l.reviewed_at IS NOT NULL) ORDER BY created_at DESC LIMIT 24"),
        ('goal', "SELECT id,title AS text,description,deadline,created_at FROM goals WHERE status='active' AND NOT EXISTS (SELECT 1 FROM task_lifecycles l WHERE l.kind='goal' AND l.item_id=goals.id AND l.reviewed_at IS NOT NULL) ORDER BY created_at DESC LIMIT 24"),
    ):
        for row in con.execute(query).fetchall():
            record = dict(row)
            seed(con, kind, record)
            policy = con.execute('SELECT reviewed_at FROM task_lifecycles WHERE kind=? AND item_id=?', (kind, record['id'])).fetchone()
            if policy['reviewed_at'] is None:
                candidates.append({'kind': kind, **record})
    candidates = candidates[:limit]
    con.commit()
    if not candidates:
        return 0
    now = time.time()
    prompt = ('Assess the useful lifetime of these unfinished user tasks. Interpret relative dates using each original created_at epoch, NEVER today. '
              'Current epoch: ' + str(now) + '. Preserve durable goals but do not keep prompting about ignored requests. '
              'A time-bound action expires when its event or usefulness window passes. A durable aspiration can remain useful beyond a missed target date. '
              'Return {"items":[{"kind":"goal or follow_up","id":integer,"expires_at":epoch or null,"dormant_at":epoch,'
              '"reason":"explanation","evidence":"exact substring of the original text"}]}. '
              'dormant_at is when to stop unsolicited follow-ups; choose a finite attention window appropriate to the user request. '
              'Do not renew stale intent merely because it was retrieved or reviewed. Data:\n' + json.dumps(candidates, ensure_ascii=False))
    result = llm.chat_json(prompt, max_tokens=1800)
    if not isinstance(result, dict) or not isinstance(result.get('items'), list):
        return 0
    by_id = {(r['kind'], r['id']): r for r in candidates}
    applied = 0
    for item in result['items']:
        if not isinstance(item, dict) or type(item.get('id')) is not int:
            continue
        original = by_id.get((item.get('kind'), item['id']))
        quote = item.get('evidence')
        dormant = item.get('dormant_at')
        if not original or not isinstance(quote, str) or not quote.strip() or quote not in original['text'] or dormant is None:
            continue
        try:
            previous = con.execute('SELECT dormant_at FROM task_lifecycles WHERE kind=? AND item_id=?', (item['kind'], item['id'])).fetchone()
            if previous and previous['dormant_at'] is not None and previous['dormant_at'] <= now:
                dormant = min(dormant, previous['dormant_at'])
            set_policy(con, item['kind'], item['id'], item.get('expires_at'), dormant, str(item.get('reason') or ''))
            applied += 1
        except ValueError:
            continue
    con.commit()
    return applied


def tool_request(tool, args):
    from . import db
    con = db.connect()
    try:
        db.ensure_tier3(con)
        ensure_schema(con)
        if tool == 'task_list':
            rows = []
            for kind, query in (
                ('goal', 'SELECT id,title AS text,created_at,deadline,status FROM goals ORDER BY created_at DESC LIMIT 50'),
                ('follow_up', 'SELECT id,text,created_at,done_at FROM follow_ups ORDER BY created_at DESC LIMIT 50'),
            ):
                for row in con.execute(query).fetchall():
                    item = dict(row)
                    seed(con, kind, item)
                    policy = dict(con.execute('SELECT * FROM task_lifecycles WHERE kind=? AND item_id=?', (kind, item['id'])).fetchone())
                    rows.append({**item, **policy, 'state': state(con, kind, item['id'])})
            con.commit()
            return {'tasks': rows}
        kind, item_id, action = args.get('kind'), args.get('id'), args.get('action')
        if kind not in ('goal', 'follow_up') or type(item_id) is not int or action not in ('dismiss', 'reactivate'):
            raise ValueError('Invalid task kind, id or action')
        query = ('SELECT * FROM goals WHERE id=?' if kind == 'goal' else 'SELECT * FROM follow_ups WHERE id=?')
        row = con.execute(query, (item_id,)).fetchone()
        if not row:
            raise ValueError('Task not found')
        record = dict(row)
        seed(con, kind, record)
        if action == 'dismiss':
            dismiss(con, kind, item_id)
        else:
            if record.get('done_at') or (kind == 'goal' and record.get('status') != 'active'):
                raise ValueError('Completed/archived work cannot be silently reopened; create a new goal')
            expiry = args.get('expires_at')
            if expiry is None:
                expiry = con.execute('SELECT expires_at FROM task_lifecycles WHERE kind=? AND item_id=?', (kind, item_id)).fetchone()['expires_at']
            reactivate(con, kind, item_id, args.get('until'), expiry)
        return {'kind': kind, 'id': item_id, 'state': state(con, kind, item_id), 'history_preserved': True}
    finally:
        con.close()
