"""
Few-Shot Learner - Learn from 1-2 examples using embeddings
"""
import numpy as np
import pickle
from datetime import datetime
from brain.learning_db import get_db


class FewShotLearner:
    """
    Few-shot learning using sentence embeddings.
    Enables learning from single examples by semantic similarity.
    """
    
    def __init__(self, similarity_threshold=0.75):
        """
        Args:
            similarity_threshold: Min cosine similarity for match (0-1)
        """
        self.threshold = similarity_threshold
        self.db = get_db()
        self.model = None
        self._init_tables()
    
    def _init_tables(self):
        """Create embedding storage table."""
        cursor = self.db.conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                embedding BLOB,
                action TEXT,
                situation TEXT,
                success_count INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_situation_emb 
            ON embeddings(situation)
        """)
        
        self.db.conn.commit()
    
    def _get_model(self):
        """Lazy load sentence transformer model."""
        if self.model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
                print("[FewShot] Loaded embedding model")
            except Exception as e:
                print(f"[FewShot] Could not load model: {e}")
                return None
        return self.model
    
    def store_example(self, text, action, situation):
        """
        Store single example with embedding.
        
        Args:
            text: User input text
            action: Action taken
            situation: Situation detected
        """
        model = self._get_model()
        if model is None:
            return
        
        # Generate embedding
        embedding = model.encode(text)
        embedding_bytes = pickle.dumps(embedding)
        
        cursor = self.db.conn.cursor()
        
        # Check if similar embedding exists
        cursor.execute("""
            SELECT id, success_count FROM embeddings
            WHERE situation = ? AND action = ?
        """, (situation, action))
        
        existing = cursor.fetchone()
        
        if existing:
            # Update success count
            cursor.execute("""
                UPDATE embeddings
                SET success_count = success_count + 1
                WHERE id = ?
            """, (existing[0],))
            print(f"[FewShot] Updated example: {situation} -> {action} (count: {existing[1] + 1})")
        else:
            # Insert new
            cursor.execute("""
                INSERT INTO embeddings (text, embedding, action, situation, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (text, embedding_bytes, action, situation, datetime.now().isoformat()))
            print(f"[FewShot] Stored new example: {situation} -> {action}")
        
        self.db.conn.commit()
    
    def predict_from_text(self, text, situation=None):
        """
        Predict action from text using embedding similarity.
        
        Args:
            text: User input
            situation: Optional situation filter
        
        Returns:
            dict: Prediction with confidence or None
        """
        model = self._get_model()
        if model is None:
            return None
        
        # Generate query embedding
        query_emb = model.encode(text)
        
        cursor = self.db.conn.cursor()
        
        # Get stored embeddings
        if situation:
            cursor.execute("""
                SELECT id, embedding, action, success_count
                FROM embeddings
                WHERE situation = ?
            """, (situation,))
        else:
            cursor.execute("""
                SELECT id, embedding, action, success_count
                FROM embeddings
            """)
        
        results = cursor.fetchall()
        
        if not results:
            return None
        
        # Calculate similarities
        similarities = []
        for emb_id, emb_bytes, action, success_count in results:
            stored_emb = pickle.loads(emb_bytes)
            
            # Cosine similarity
            similarity = np.dot(query_emb, stored_emb) / (
                np.linalg.norm(query_emb) * np.linalg.norm(stored_emb)
            )
            
            # Boost by success count
            boosted_sim = similarity * (1 + min(success_count / 10.0, 0.2))
            
            similarities.append({
                'action': action,
                'similarity': similarity,
                'boosted_similarity': boosted_sim,
                'success_count': success_count
            })
        
        if not similarities:
            return None
        
        # Get best match
        best = max(similarities, key=lambda x: x['boosted_similarity'])
        
        if best['similarity'] >= self.threshold:
            return {
                'action': best['action'],
                'confidence': best['similarity'],
                'source': 'few_shot',
                'reason': f"Semantic match (similarity: {best['similarity']:.2%})"
            }
        
        return None
    
    def get_stats(self):
        """Get few-shot learning statistics."""
        cursor = self.db.conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) as total_examples,
                   COUNT(DISTINCT situation) as unique_situations,
                   SUM(success_count) as total_uses
            FROM embeddings
        """)
        
        row = cursor.fetchone()
        
        return {
            'total_examples': row[0] or 0,
            'unique_situations': row[1] or 0,
            'total_uses': row[2] or 0
        }


_few_shot_learner = None

def get_few_shot_learner():
    global _few_shot_learner
    if _few_shot_learner is None:
        _few_shot_learner = FewShotLearner()
    return _few_shot_learner
