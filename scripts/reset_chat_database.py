"""Erase conversation traces in Zumba's app DB while retaining integrations.

Invoked by reset_memory.ps1 with Zumba stopped. No model or application imports.
"""
import argparse
import json
from pathlib import Path
import sqlite3

HISTORY_TABLES = (
    "execution_events", "execution_runs", "channel_map", "channel_seen",
    "geo_pings", "geo_visits", "geo_tracks", "messages", "sessions",
)


def reset_database(path: Path):
    if not path.is_file():
        return {}
    con = sqlite3.connect(path, timeout=5)
    try:
        con.execute("PRAGMA secure_delete=ON")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {}
        with con:
            # Retain Telegram offsets so clearing seen rows cannot replay old updates.
            if "channel_cursors" in tables:
                for source in ("channel_seen", "execution_runs"):
                    if source not in tables:
                        continue
                    for channel, highest in con.execute(f"SELECT channel,MAX(update_id) FROM {source} GROUP BY channel").fetchall():
                        con.execute("INSERT INTO channel_cursors(channel,next_offset,updated_at) VALUES(?,?,0) "
                                    "ON CONFLICT(channel) DO UPDATE SET next_offset=max(next_offset,excluded.next_offset)",
                                    (channel, highest + 1))
            for table in HISTORY_TABLES:
                if table in tables:
                    counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    con.execute(f"DELETE FROM {table}")
            if "messages_fts" in tables:
                con.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
            if "config" in tables:
                con.execute("DELETE FROM config WHERE key IN ('last_session','style','default_system')")
                con.execute("INSERT OR REPLACE INTO config(key,value) VALUES('legacy_migrated','1')")
            if "sqlite_sequence" in tables:
                for table in HISTORY_TABLES:
                    con.execute("DELETE FROM sqlite_sequence WHERE name=?", (table,))
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("VACUUM")
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert all(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0 for t in counts)
        return counts
    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    print(json.dumps({"cleared_rows": reset_database(args.database)}))
