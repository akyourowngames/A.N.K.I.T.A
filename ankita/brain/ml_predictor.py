"""
ML Predictor - Predicts best actions based on context history using k-NN
"""
import json
from datetime import datetime, timedelta
from collections import Counter
from brain.learning_db import get_db
from brain.context_collector import context_similarity


class MLPredictor:
    """
    Machine learning predictor using k-Nearest Neighbors.
    Learns from historical action success patterns.
    """
    
    def __init__(self, k=10, min_confidence=0.7):
        """
        Initialize predictor.
        
        Args:
            k: Number of nearest neighbors to consider
            min_confidence: Minimum confidence to suggest action
        """
        self.k = k
        self.min_confidence = min_confidence
        self.db = get_db()
    
    def predict_action(self, situation, context):
        """
        Predict best action for situation + context.
        
        Args:
            situation: Situation name (e.g., "hungry")
            context: Current context dict
        
        Returns:
            dict: {
                'action': str,
                'confidence': float,
                'params': dict,
                'reason': str
            } or None if no prediction
        """
        # Get similar past contexts
        similar = self.db.get_similar_contexts(context, situation, limit=self.k * 2)
        
        if len(similar) < 3:
            # Not enough data to predict
            return None
        
        # Score each historical record
        scored = []
        for record in similar:
            try:
                past_context = json.loads(record['context_json'])
                similarity = context_similarity(context, past_context)
                
                # Temporal decay: recent actions weighted higher
                ts = datetime.fromisoformat(record['timestamp'])
                days_ago = (datetime.now() - ts).days
                recency_weight = 1.0 / (1.0 + days_ago / 30.0)  # Decay over 30 days
                
                # Combined score
                score = similarity * recency_weight * record['success']
                
                scored.append({
                    'action': record['action_taken'],
                    'params': json.loads(record['action_params']) if record['action_params'] else {},
                    'score': score,
                    'timestamp': record['timestamp']
                })
            except:
                continue
        
        if not scored:
            return None
        
        # Get top k
        scored.sort(key=lambda x: x['score'], reverse=True)
        top_k = scored[:self.k]
        
        # Vote by action (weighted by score)
        action_votes = {}
        action_params = {}
        
        for item in top_k:
            action = item['action']
            score = item['score']
            
            action_votes[action] = action_votes.get(action, 0) + score
            
            # Collect params for this action
            if action not in action_params:
                action_params[action] = []
            action_params[action].append(item['params'])
        
        # Get winner
        if not action_votes:
            return None
        
        best_action = max(action_votes.items(), key=lambda x: x[1])
        action_name = best_action[0]
        total_score = best_action[1]
        
        # Normalize confidence (0-1)
        max_possible_score = self.k * 1.0
        confidence = min(total_score / max_possible_score, 1.0)
        
        if confidence < self.min_confidence:
            return None
        
        # Average parameters
        params = self._average_params(action_params.get(action_name, []))
        
        # Generate reason
        count = len([v for v in top_k if v['action'] == action_name])
        reason = f"You did this {count}/{self.k} times in similar contexts"
        
        return {
            'action': action_name,
            'confidence': confidence,
            'params': params,
            'reason': reason,
            'sample_size': count
        }
    
    def _average_params(self, param_list):
        """Average parameters from multiple past actions."""
        if not param_list:
            return {}
        
        # For now, take most common params
        # Could be improved with weighted averaging for numeric params
        
        result = {}
        
        # Get all keys
        all_keys = set()
        for p in param_list:
            all_keys.update(p.keys())
        
        for key in all_keys:
            values = [p[key] for p in param_list if key in p]
            
            if not values:
                continue
            
            # Most common value
            counter = Counter(values)
            result[key] = counter.most_common(1)[0][0]
        
        return result
    
    def optimize_parameters(self, action, context, default_params):
        """
        Optimize action parameters based on context.
        
        Args:
            action: Action name
            context: Current context
            default_params: Default parameters
        
        Returns:
            dict: Optimized parameters
        """
        # Get past uses of this action
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT action_params, context_json, success
            FROM action_history
            WHERE action_taken = ?
            AND success = 1
            ORDER BY timestamp DESC
            LIMIT 20
        """, (action,))
        
        records = cursor.fetchall()
        
        if len(records) < 3:
            return default_params
        
        # Find similar contexts and average their params
        similar_params = []
        for record in records:
            try:
                past_ctx = json.loads(record[1])
                similarity = context_similarity(context, past_ctx)
                
                if similarity > 0.6:  # High similarity threshold
                    params = json.loads(record[0]) if record[0] else {}
                    similar_params.append(params)
            except:
                continue
        
        if similar_params:
            return self._average_params(similar_params)
        
        return default_params
    
    def should_suggest_workflow(self, recent_actions, min_pattern_count=5):
        """
        Detect if recent actions match a learned workflow pattern.
        
        Args:
            recent_actions: List of recent action names
            min_pattern_count: Min times pattern must occur to suggest
        
        Returns:
            dict: {
                'pattern': list of actions,
                'next_action': str,
                'confidence': float
            } or None
        """
        if len(recent_actions) < 2:
            return None
        
        # Look for sequences in history
        cursor = self.db.conn.cursor()
        
        # Get action sequences from past hour windows
        cursor.execute("""
            SELECT action_taken, timestamp
            FROM action_history
            WHERE success = 1
            ORDER BY timestamp DESC
            LIMIT 100
        """)
        
        records = cursor.fetchall()
        
        # Build sequences
        sequences = []
        current_seq = []
        last_time = None
        
        for record in records:
            action = record[0]
            ts = datetime.fromisoformat(record[1])
            
            if last_time and (last_time - ts).seconds > 600:  # 10 min gap = new sequence
                if len(current_seq) >= 3:
                    sequences.append(current_seq[::-1])  # Reverse to chronological
                current_seq = []
            
            current_seq.append(action)
            last_time = ts
        
        # Find matching patterns
        recent_pattern = tuple(recent_actions[-2:])  # Last 2 actions
        
        matches = []
        for seq in sequences:
            for i in range(len(seq) - 2):
                if tuple(seq[i:i+2]) == recent_pattern and i + 2 < len(seq):
                    matches.append(seq[i+2])  # Next action in pattern
        
        if len(matches) >= min_pattern_count:
            # Found a pattern!
            counter = Counter(matches)
            next_action, count = counter.most_common(1)[0]
            
            return {
                'pattern': list(recent_pattern),
                'next_action': next_action,
                'confidence': count / len(matches),
                'occurrences': count
            }
        
        return None
    
    def get_learning_stats(self):
        """Get overall learning statistics."""
        cursor = self.db.conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total_actions,
                COUNT(DISTINCT situation) as unique_situations,
                COUNT(DISTINCT action_taken) as unique_actions,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_actions,
                AVG(execution_time_ms) as avg_exec_time
            FROM action_history
        """)
        
        row = dict(cursor.fetchone())
        
        total = row['total_actions'] or 0
        successes = row['successful_actions'] or 0
        
        return {
            'total_actions': total,
            'unique_situations': row['unique_situations'] or 0,
            'unique_actions': row['unique_actions'] or 0,
            'success_rate': successes / total if total > 0 else 0,
            'avg_exec_time_ms': row['avg_exec_time'] or 0
        }


# Global instance
_predictor = None


def get_predictor():
    """Get or create global predictor instance."""
    global _predictor
    if _predictor is None:
        _predictor = MLPredictor()
    return _predictor
