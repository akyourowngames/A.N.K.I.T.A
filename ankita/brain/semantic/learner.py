"""
Semantic Learner - Learns from user feedback to personalize behavior.

Adjusts action weights based on:
- User saying "no" or "stop" (negative feedback)
- Successful action execution (positive feedback)
- User manual corrections
"""

import json
import os


class SemanticLearner:
    """Learns and adapts semantic control behavior."""
    
    def __init__(self):
        """Initialize learner with weight storage."""
        self.weights_file = os.path.join(os.path.dirname(__file__), 'learned_weights.json')
        self.weights = self._load_weights()
    
    def _load_weights(self):
        """Load learned action weights from file."""
        if os.path.exists(self.weights_file):
            try:
                with open(self.weights_file, encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[SemanticLearner] Error loading weights: {e}")
                return {}
        return {}
    
    def _save_weights(self):
        """Save learned weights to file."""
        try:
            with open(self.weights_file, 'w', encoding='utf-8') as f:
                json.dump(self.weights, f, indent=2)
        except Exception as e:
            print(f"[SemanticLearner] Error saving weights: {e}")
    
    def adjust_action_weight(self, situation, action_tool, delta):
        """
        Adjust weight of an action for a situation.
        
        Args:
            situation: str, e.g., "bored"
            action_tool: str, e.g., "youtube.open"
            delta: float, positive for increase, negative for decrease
        """
        key = f"{situation}:{action_tool}"
        
        if key not in self.weights:
            self.weights[key] = 1.0
        
        self.weights[key] += delta
        
        # Clamp between 0.0 and 2.0
        self.weights[key] = max(0.0, min(2.0, self.weights[key]))
        
        self._save_weights()
        print(f"[SemanticLearner] Adjusted {key} weight to {self.weights[key]:.2f}")
    
    def get_action_weight(self, situation, action_tool):
        """
        Get learned weight for an action.
        
        Returns:
            float: weight (default 1.0)
        """
        key = f"{situation}:{action_tool}"
        return self.weights.get(key, 1.0)
    
    def handle_negative_feedback(self, situation, action_tool):
        """
        User said 'no' or 'stop' - decrease weight.
        
        Args:
            situation: str
            action_tool: str
        """
        self.adjust_action_weight(situation, action_tool, -0.2)
    
    def handle_positive_feedback(self, situation, action_tool):
        """
        User approved or action was successful - increase weight.
        
        Args:
            situation: str
            action_tool: str
        """
        self.adjust_action_weight(situation, action_tool, 0.1)
    
    def get_filtered_actions(self, situation, actions):
        """
        Filter and sort actions by learned weights.
        
        Args:
            situation: str
            actions: list of action dicts
        
        Returns:
            list of actions, filtered and sorted by weight
        """
        weighted_actions = []
        
        for action in actions:
            tool = action.get('tool', '')
            weight = self.get_action_weight(situation, tool)
            
            # Skip actions with very low weight (user consistently rejected)
            if weight < 0.3:
                print(f"[SemanticLearner] Skipping {tool} for {situation} (low weight: {weight:.2f})")
                continue
            
            weighted_actions.append((weight, action))
        
        # Sort by weight descending
        weighted_actions.sort(key=lambda x: x[0], reverse=True)
        
        return [action for _, action in weighted_actions]


# Singleton instance
_learner = None


def get_learner():
    """Get or create the global learner instance."""
    global _learner
    if _learner is None:
        _learner = SemanticLearner()
    return _learner
