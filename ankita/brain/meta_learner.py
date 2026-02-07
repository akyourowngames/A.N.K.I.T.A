"""
Meta-Learner - Transfer patterns between similar situations
"""
import json
from datetime import datetime, timedelta
from brain.learning_db import get_db


class MetaLearner:
    """
    Meta-learning system that transfers knowledge between similar situations.
    Enables faster learning by applying patterns from one situation to another.
    """
    
    def __init__(self, similarity_threshold=0.7):
        """
        Args:
            similarity_threshold: Min similarity to transfer (0-1)
        """
        self.threshold = similarity_threshold
        self.db = get_db()
        self._init_tables()
    
    def _init_tables(self):
        """Create meta-learning tables."""
        cursor = self.db.conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pattern_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_situation TEXT,
                target_situation TEXT,
                pattern_type TEXT,
                action TEXT,
                confidence REAL,
                created_at TEXT
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_target_sit 
            ON pattern_transfers(target_situation)
        """)
        
        self.db.conn.commit()
    
    def find_similar_situations(self, target_situation):
        """
        Find situations similar to target.
        
        Uses semantic similarity based on:
        - Common words
        - Action patterns
        - Context patterns
        
        Returns:
            list: [(situation, similarity_score)]
        """
        cursor = self.db.conn.cursor()
        
        # Get all unique situations with actions
        cursor.execute("""
            SELECT DISTINCT situation, COUNT(*) as frequency
            FROM action_history
            WHERE situation != ? AND success = 1
            GROUP BY situation
            HAVING frequency >= 3
        """, (target_situation,))
        
        situations = cursor.fetchall()
        
        # Simple similarity: word overlap
        target_words = set(target_situation.lower().split('_'))
        
        similar = []
        for sit, freq in situations:
            sit_words = set(sit.lower().split('_'))
            overlap = len(target_words & sit_words)
            
            if overlap > 0:
                similarity = overlap / len(target_words | sit_words)
                if similarity >= self.threshold:
                    similar.append((sit, similarity))
        
        return sorted(similar, key=lambda x: x[1], reverse=True)
    
    def transfer_pattern(self, source_situation, target_situation):
        """
        Transfer learned patterns from source to target.
        
        Returns:
            list: Transferred actions with confidence
        """
        cursor = self.db.conn.cursor()
        
        # Get best actions from source
        cursor.execute("""
            SELECT action_taken, COUNT(*) as frequency,
                   AVG(CASE WHEN success = 1 THEN 1.0 ELSE 0.0 END) as success_rate
            FROM action_history
            WHERE situation = ?
            GROUP BY action_taken
            HAVING success_rate > 0.7 AND frequency >= 2
            ORDER BY success_rate DESC, frequency DESC
            LIMIT 3
        """, (source_situation,))
        
        source_actions = cursor.fetchall()
        
        if not source_actions:
            return []
        
        transferred = []
        
        for action, freq, success_rate in source_actions:
            # Calculate transfer confidence
            # Based on source success rate and frequency
            base_conf = success_rate * 0.8  # Conservative transfer
            freq_bonus = min(freq / 10.0, 0.15)  # Max 15% bonus
            transfer_conf = min(base_conf + freq_bonus, 0.9)
            
            transferred.append({
                'action': action,
                'confidence': transfer_conf,
                'source': source_situation,
                'reason': f'Transferred from similar situation: {source_situation}'
            })
            
            # Log transfer
            cursor.execute("""
                INSERT INTO pattern_transfers 
                (source_situation, target_situation, pattern_type, action, confidence, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (source_situation, target_situation, 'action_transfer',
                  action, transfer_conf, datetime.now().isoformat()))
        
        self.db.conn.commit()
        
        print(f"[MetaLearning] Transferred {len(transferred)} patterns: {source_situation} → {target_situation}")
        
        return transferred
    
    def bootstrap_new_situation(self, new_situation):
        """
        Bootstrap learning for new situation using meta-learning.
        
        Returns:
            dict: Best predicted action from transfer
        """
        # Find similar situations
        similar = self.find_similar_situations(new_situation)
        
        if not similar:
            return None
        
        # Transfer from most similar
        best_source = similar[0][0]
        similarity_score = similar[0][1]
        
        transferred = self.transfer_pattern(best_source, new_situation)
        
        if transferred:
            best = transferred[0]
            best['meta_similarity'] = similarity_score
            return best
        
        return None
    
    def get_transfer_stats(self):
        """Get meta-learning statistics."""
        cursor = self.db.conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) as total_transfers,
                   COUNT(DISTINCT target_situation) as unique_targets,
                   AVG(confidence) as avg_confidence
            FROM pattern_transfers
        """)
        
        row = cursor.fetchone()
        
        return {
            'total_transfers': row[0] or 0,
            'unique_targets': row[1] or 0,
            'avg_confidence': row[2] or 0
        }


_meta_learner = None

def get_meta_learner():
    global _meta_learner
    if _meta_learner is None:
        _meta_learner = MetaLearner()
    return _meta_learner
