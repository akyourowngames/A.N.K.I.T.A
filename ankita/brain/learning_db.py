"""
Learning Database - SQLite storage for action history and pattern learning
"""
import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path


class LearningDB:
    """SQLite wrapper for storing and querying action history."""
    
    def __init__(self, db_path=None):
        """Initialize database connection."""
        if db_path is None:
            # Store in brain directory
            brain_dir = Path(__file__).parent
            db_path = brain_dir / "ankita.db"
        
        self.db_path = str(db_path)
        self.conn = None
        self._init_db()
    
    def _init_db(self):
        """Create database and tables if they don't exist."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Return rows as dicts
        
        cursor = self.conn.cursor()
        
        # Action history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS action_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                hour INTEGER,
                day_of_week TEXT,
                is_weekend INTEGER,
                time_of_day TEXT,
                battery_percent INTEGER,
                situation TEXT,
                action_taken TEXT NOT NULL,
                action_params TEXT,
                success INTEGER DEFAULT 1,
                execution_time_ms INTEGER,
                context_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for fast queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_situation ON action_history(situation)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hour ON action_history(hour)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dow ON action_history(day_of_week)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON action_history(timestamp)")
        
        self.conn.commit()
    
    def log_action(self, context, action, params=None, success=1, exec_time_ms=0):
        """
        Log an action with its context.
        
        Args:
            context: dict from context_collector
            action: str, action taken (e.g., "web.search")
            params: dict, action parameters
            success: int, 1=success, 0=failure, -1=canceled
            exec_time_ms: int, execution time in milliseconds
        
        Returns:
            int: ID of inserted row
        """
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT INTO action_history (
                timestamp, hour, day_of_week, is_weekend, time_of_day,
                battery_percent, situation, action_taken, action_params,
                success, execution_time_ms, context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            context.get("timestamp"),
            context.get("hour"),
            context.get("day_of_week"),
            1 if context.get("is_weekend") else 0,
            context.get("time_of_day"),
            context.get("battery_percent"),
            context.get("situation_detected"),
            action,
            json.dumps(params) if params else None,
            success,
            exec_time_ms,
            json.dumps(context)
        ))
        
        self.conn.commit()
        return cursor.lastrowid
    
    def get_similar_contexts(self, context, situation, limit=20):
        """
        Find similar past contexts for prediction.
        
        Args:
            context: Current context dict
            situation: Situation name
            limit: Max results to return
        
        Returns:
            list of dicts: Past action records
        """
        cursor = self.conn.cursor()
        
        # Get actions from same/similar context
        # Priority: same situation > same time_of_day > same hour range
        cursor.execute("""
            SELECT * FROM action_history
            WHERE situation = ?
            AND success = 1
            ORDER BY 
                CASE 
                    WHEN time_of_day = ? THEN 3
                    WHEN ABS(hour - ?) <= 2 THEN 2
                    WHEN is_weekend = ? THEN 1
                    ELSE 0
                END DESC,
                timestamp DESC
            LIMIT ?
        """, (
            situation,
            context.get("time_of_day"),
            context.get("hour"),
            1 if context.get("is_weekend") else 0,
            limit
        ))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    def get_action_stats(self, situation, action):
        """
        Get statistics for a specific situation-action pair.
        
        Returns:
            dict: {total, successes, success_rate, avg_exec_time}
        """
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                AVG(CASE WHEN success = 1 THEN execution_time_ms ELSE NULL END) as avg_exec_time
            FROM action_history
            WHERE situation = ? AND action_taken = ?
        """, (situation, action))
        
        row = dict(cursor.fetchone())
        total = row['total'] or 0
        successes = row['successes'] or 0
        
        return {
            'total': total,
            'successes': successes,
            'success_rate': successes / total if total > 0 else 0,
            'avg_exec_time': row['avg_exec_time'] or 0
        }
    
    def get_recent_actions(self, limit=10):
        """Get recent action history."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT action_taken, timestamp, situation
            FROM action_history
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_pattern_frequency(self, situation, action, time_window_days=30):
        """
        Check how often a situation-action pair occurs.
        
        Returns:
            int: Number of occurrences in time window
        """
        cursor = self.conn.cursor()
        
        since_date = (datetime.now() - timedelta(days=time_window_days)).isoformat()
        
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM action_history
            WHERE situation = ? 
            AND action_taken = ?
            AND timestamp >= ?
            AND success = 1
        """, (situation, action, since_date))
        
        return cursor.fetchone()[0]
    
    def cleanup_old_data(self, days_to_keep=90):
        """Remove old action history to keep DB small."""
        cursor = self.conn.cursor()
        
        cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).isoformat()
        
        cursor.execute("""
            DELETE FROM action_history
            WHERE timestamp < ?
        """, (cutoff_date,))
        
        deleted = cursor.rowcount
        self.conn.commit()
        
        # Vacuum to reclaim space
        cursor.execute("VACUUM")
        
        return deleted
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()


# Global instance
_db = None


def get_db():
    """Get or create global database instance."""
    global _db
    if _db is None:
        _db = LearningDB()
    return _db
