"""Durable channel intake, execution events and outcomes in the local app database."""
import json
import time
import uuid
from contextlib import contextmanager
from . import store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_runs (
 id TEXT PRIMARY KEY, channel TEXT NOT NULL, chat_id TEXT NOT NULL,
 update_id INTEGER NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
 stage TEXT NOT NULL DEFAULT 'Queued', reply TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
 created_at REAL NOT NULL, updated_at REAL NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
 UNIQUE(channel,update_id)
);
CREATE TABLE IF NOT EXISTS execution_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
 kind TEXT NOT NULL, data TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_events ON execution_events(run_id,id);
CREATE INDEX IF NOT EXISTS idx_runs_queue ON execution_runs(channel,status,created_at);
"""


@contextmanager
def connect():
    con = store.connect()
    try:
        con.execute('PRAGMA synchronous=FULL')
        con.executescript(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _row(row):
    if row is None:
        return None
    result = dict(row)
    result['payload'] = json.loads(result['payload'])
    return result


def create(channel, chat_id, update_id, payload):
    now = time.time()
    with connect() as con:
        con.execute('INSERT OR IGNORE INTO execution_runs(id,channel,chat_id,update_id,payload,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                    (uuid.uuid4().hex[:16], channel, str(chat_id), update_id, json.dumps(payload, ensure_ascii=False), now, now))
        return _row(con.execute('SELECT * FROM execution_runs WHERE channel=? AND update_id=?', (channel, update_id)).fetchone())


def get(run_id):
    with connect() as con:
        return _row(con.execute('SELECT * FROM execution_runs WHERE id=?', (run_id,)).fetchone())


def claim(run_id):
    with connect() as con:
        return con.execute("UPDATE execution_runs SET status='running',stage='Preparing',updated_at=? WHERE id=? AND status='queued'",
                           (time.time(), run_id)).rowcount == 1


def record(run_id, kind, data):
    with connect() as con:
        con.execute('INSERT INTO execution_events(run_id,kind,data,created_at) VALUES(?,?,?,?)',
                    (run_id, kind, json.dumps(data, ensure_ascii=False), time.time()))
        stage = data.get('stage') or (data.get('name') if kind == 'tool_start' else None)
        if stage:
            con.execute("UPDATE execution_runs SET stage=?,updated_at=? WHERE id=? AND status='running'",
                        (str(stage)[:200], time.time(), run_id))


def finish(run_id, status, reply='', error=''):
    if status not in ('completed', 'cancelled', 'failed', 'interrupted', 'timed_out'):
        raise ValueError('Invalid terminal state')
    with connect() as con:
        con.execute("UPDATE execution_runs SET status=?,stage=?,reply=?,error=?,updated_at=? WHERE id=? AND status IN ('queued','running')",
                    (status, status.replace('_', ' ').capitalize(), reply, error[:2000], time.time(), run_id))


def events(run_id):
    with connect() as con:
        return [{**dict(r), 'data': json.loads(r['data'])} for r in con.execute('SELECT * FROM execution_events WHERE run_id=? ORDER BY id', (run_id,))]


def queued(channel):
    with connect() as con:
        return [_row(r) for r in con.execute("SELECT * FROM execution_runs WHERE channel=? AND status='queued' ORDER BY update_id LIMIT 100", (channel,))]


def recent(channel, chat_id, limit=5):
    with connect() as con:
        return [_row(r) for r in con.execute('SELECT * FROM execution_runs WHERE channel=? AND chat_id=? ORDER BY created_at DESC LIMIT ?', (channel, str(chat_id), limit))]


def recover(channel):
    with connect() as con:
        con.execute("UPDATE execution_runs SET status='interrupted',stage='Interrupted',reply='Zumba restarted during this run. Completed steps are saved; no action has been replayed.',updated_at=? WHERE channel=? AND status='running'",
                    (time.time(), channel))


def undelivered(channel):
    with connect() as con:
        return [_row(r) for r in con.execute("SELECT * FROM execution_runs WHERE channel=? AND delivered=0 AND status NOT IN ('queued','running') ORDER BY created_at LIMIT 100", (channel,))]


def delivered(run_id):
    with connect() as con:
        con.execute('UPDATE execution_runs SET delivered=1 WHERE id=?', (run_id,))
