"""
Reinforcement Learning Agent - Q-Learning for optimal action selection
"""
import json
import random
import hashlib
from datetime import datetime
from brain.learning_db import get_db


class QLearningAgent:
    """Q-Learning agent that learns optimal actions through rewards."""
    
    def __init__(self, learning_rate=0.1, discount_factor=0.9, epsilon=0.2):
        self.lr = learning_rate
        self.gamma = discount_factor
        self.epsilon = epsilon
        
        self.db = get_db()
        self.q_table = self._load_q_table()
        
        self.total_updates = 0
        self.explorations = 0
        self.exploitations = 0
    
    def _load_q_table(self):
        """Load Q-table from database."""
        cursor = self.db.conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS q_values (
                state_hash TEXT,
                action TEXT,
                q_value REAL,
                update_count INTEGER DEFAULT 1,
                last_updated TEXT,
                PRIMARY KEY (state_hash, action)
            )
        """)
        self.db.conn.commit()
        
        cursor.execute("SELECT state_hash, action, q_value FROM q_values")
        q_table = {}
        for row in cursor.fetchall():
            q_table[(row[0], row[1])] = row[2]
        
        print(f"[RL] Loaded {len(q_table)} Q-values")
        return q_table
    
    def _hash_state(self, context, situation):
        """Create state hash from context."""
        state_tuple = (
            situation,
            context.get('time_of_day', 'unknown'),
            context.get('day_of_week', 'unknown'),
            'charging' if context.get('is_charging') else 'battery',
            'high' if context.get('battery_percent', 50) > 70 
            else 'low' if context.get('battery_percent', 50) < 30 
            else 'medium'
        )
        
        state_str = json.dumps(state_tuple, sort_keys=True)
        return hashlib.md5(state_str.encode()).hexdigest()[:16]
    
    def get_q_value(self, state_hash, action):
        """Get Q-value for state-action pair."""
        return self.q_table.get((state_hash, action), 0.0)
    
    def select_action(self, context, situation, available_actions):
        """Select action using epsilon-greedy."""
        if not available_actions:
            return None
        
        state_hash = self._hash_state(context, situation)
        
        # Epsilon-greedy
        if random.random() < self.epsilon:
            action = random.choice(available_actions)
            self.explorations += 1
            method = 'explore'
            print(f"[RL] Exploring: {action}")
        else:
            # Best Q-value
            q_values = [(a, self.get_q_value(state_hash, a)) for a in available_actions]
            action = max(q_values, key=lambda x: x[1])[0]
            self.exploitations += 1
            method = 'exploit'
        
        q_value = self.get_q_value(state_hash, action)
        
        return {
            'action': action,
            'q_value': q_value,
            'method': method,
            'state_hash': state_hash,
            'confidence': min(abs(q_value), 1.0)
        }
    
    def update_q_value(self, state_hash, action, reward, next_state_hash, next_actions):
        """Update Q-value using Q-learning formula."""
        old_q = self.get_q_value(state_hash, action)
        
        # Max Q-value for next state
        if next_actions:
            max_next_q = max([self.get_q_value(next_state_hash, a) for a in next_actions])
        else:
            max_next_q = 0
        
        # Q-learning update
        new_q = old_q + self.lr * (reward + self.gamma * max_next_q - old_q)
        
        # Store
        self.q_table[(state_hash, action)] = new_q
        
        cursor = self.db.conn.cursor()
        cursor.execute("""
            INSERT INTO q_values (state_hash, action, q_value, update_count, last_updated)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(state_hash, action) DO UPDATE SET
                q_value = ?,
                update_count = update_count + 1,
                last_updated = ?
        """, (state_hash, action, new_q, datetime.now().isoformat(),
              new_q, datetime.now().isoformat()))
        
        self.db.conn.commit()
        self.total_updates += 1
        
        print(f"[RL] Q({state_hash[:8]}, {action}): {old_q:.3f} -> {new_q:.3f} (r={reward})")
    
    def learn_from_outcome(self, context, situation, action, success, next_context=None):
        """Learn from action outcome."""
        state_hash = self._hash_state(context, situation)
        
        # Reward
        if success == 1:
            reward = 1.0
        elif success == 0:
            reward = -0.5
        else:
            reward = -1.0
        
        next_state_hash = self._hash_state(next_context or context, situation)
        self.update_q_value(state_hash, action, reward, next_state_hash, [action])


_rl_agent = None

def get_rl_agent():
    global _rl_agent
    if _rl_agent is None:
        _rl_agent = QLearningAgent()
    return _rl_agent
