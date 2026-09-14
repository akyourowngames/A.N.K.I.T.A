import sqlite3

from scripts.reset_chat_database import reset_database


def test_reset_removes_history_but_preserves_credentials_and_telegram_offset(tmp_path):
    path = tmp_path / "zumba.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE config(key TEXT PRIMARY KEY,value TEXT);
        INSERT INTO config VALUES('default_model','test-model'),('calendar_token','keep'),('last_session','old'),('style','old style');
        CREATE TABLE sessions(id TEXT PRIMARY KEY);
        INSERT INTO sessions VALUES('old');
        CREATE TABLE messages(id INTEGER PRIMARY KEY, content TEXT);
        INSERT INTO messages VALUES(1,'private old message');
        CREATE VIRTUAL TABLE messages_fts USING fts5(content,content='messages',content_rowid='id');
        INSERT INTO messages_fts(rowid,content) VALUES(1,'private old message');
        CREATE TABLE execution_runs(id TEXT,payload TEXT,channel TEXT,update_id INTEGER);
        INSERT INTO execution_runs VALUES('old','private tool payload','telegram',109);
        CREATE TABLE channel_seen(channel TEXT,update_id INTEGER);
        INSERT INTO channel_seen VALUES('telegram',99);
        CREATE TABLE channel_cursors(channel TEXT PRIMARY KEY,next_offset INTEGER,updated_at REAL);
        INSERT INTO channel_cursors VALUES('telegram',50,0);
    """)
    con.close()
    counts = reset_database(path)
    assert counts['messages'] == 1 and counts['execution_runs'] == 1
    con = sqlite3.connect(path)
    assert con.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'private'").fetchone()[0] == 0
    assert con.execute('SELECT next_offset FROM channel_cursors').fetchone()[0] == 110
    config = dict(con.execute('SELECT key,value FROM config'))
    assert config == {'default_model': 'test-model', 'calendar_token': 'keep', 'legacy_migrated': '1'}
    con.close()
    assert b'private old message' not in path.read_bytes()
    assert reset_database(path)['messages'] == 0
