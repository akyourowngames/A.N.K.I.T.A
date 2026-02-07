"""
Hybrid Intelligence - Combines all learning systems for optimal predictions
"""
from brain.rl_agent import get_rl_agent
from brain.active_learner import get_active_learner
from brain.meta_learner import get_meta_learner
from brain.few_shot_learner import get_few_shot_learner
from brain.ml_predictor import get_predictor


class HybridIntelligence:
    """
    Combines multiple learning systems with priority fallback:
    1. Q-Learning (RL) - If high confidence
    2. Few-Shot - If semantic match found
    3. Meta-Learning - If similar situation exists
    4. k-NN - If patterns exist
    5. Active Learning - Ask user when uncertain
    """
    
    def __init__(self):
        self.rl_agent = get_rl_agent()
        self.active_learner = get_active_learner()
        self.meta_learner = get_meta_learner()
        self.few_shot = get_few_shot_learner()
        self.knn_predictor = get_predictor()
    
    def predict_best_action(self, user_text, situation, context, available_actions):
        """
        Predict best action using all learning systems.
        
        Returns:
            dict: {
                'action': str,
                'params': dict,
                'confidence': float,
                'source': str (rl/few_shot/meta/knn/active),
                'reason': str,
                'ask_user': bool (if should query user)
            }
        """
        predictions = []
        
        # Layer 1: Q-Learning (Reinforcement Learning)
        try:
            rl_pred = self.rl_agent.select_action(context, situation, available_actions)
            if rl_pred and rl_pred['confidence'] > 0.8:
                # High confidence from RL
                print(f"[HybridAI] Using RL: {rl_pred['action']} ({rl_pred['confidence']:.2%})")
                return {
                    **rl_pred,
                    'params': {},
                    'source': 'reinforcement_learning',
                    'reason': f"RL Q-value: {rl_pred['q_value']:.3f}",
                    'ask_user': False
                }
            elif rl_pred:
                predictions.append(rl_pred)
        except Exception as e:
            print(f"[HybridAI] RL error: {e}")
        
        # Layer 2: Few-Shot Learning (Semantic match)
        try:
            few_shot_pred = self.few_shot.predict_from_text(user_text, situation)
            if few_shot_pred and few_shot_pred['confidence'] > 0.75:
                print(f"[HybridAI] Using Few-Shot: {few_shot_pred['action']} ({few_shot_pred['confidence']:.2%})")
                return {
                    **few_shot_pred,
                    'params': {},
                    'ask_user': False
                }
            elif few_shot_pred:
                predictions.append(few_shot_pred)
        except Exception as e:
            print(f"[HybridAI] Few-Shot error: {e}")
        
        # Layer 3: Meta-Learning (Transfer from similar situations)
        try:
            meta_pred = self.meta_learner.bootstrap_new_situation(situation)
            if meta_pred and meta_pred['confidence'] > 0.7:
                print(f"[HybridAI] Using Meta-Learning: {meta_pred['action']} ({meta_pred['confidence']:.2%})")
                return {
                    **meta_pred,
                    'params': {},
                    'ask_user': False
                }
            elif meta_pred:
                predictions.append(meta_pred)
        except Exception as e:
            print(f"[HybridAI] Meta-Learning error: {e}")
        
        # Layer 4: k-NN (Historical pattern matching)
        try:
            knn_pred = self.knn_predictor.predict_action(situation, context)
            if knn_pred and knn_pred['confidence'] > 0.7:
                print(f"[HybridAI] Using k-NN: {knn_pred['action']} ({knn_pred['confidence']:.2%})")
                return {
                    **knn_pred,
                    'source': 'knn',
                    'ask_user': False
                }
            elif knn_pred:
                predictions.append(knn_pred)
        except Exception as e:
            print(f"[HybridAI] k-NN error: {e}")
        
        # Layer 5: Active Learning (Ask user when uncertain)
        if predictions:
            should_ask, top_options = self.active_learner.should_query_user(predictions)
            
            if should_ask:
                # Return best option but flag to ask user
                best = max(predictions, key=lambda p: p.get('confidence', 0))
                print(f"[HybridAI] Uncertain - will ask user (top conf: {best.get('confidence', 0):.2%})")
                return {
                    **best,
                    'ask_user': True,
                    'options': top_options
                }
            else:
                # Use best prediction
                best = max(predictions, key=lambda p: p.get('confidence', 0))
                print(f"[HybridAI] Using best prediction: {best['action']} ({best.get('confidence', 0):.2%})")
                return {
                    **best,
                    'ask_user': False
                }
        
        # No predictions available
        return None
    
    def learn_from_outcome(self, user_text, situation, context, action, params, success):
        """
        Update all learning systems based on outcome.
        
        Args:
            user_text: Original user input
            situation: Detected situation
            context: Context when action was taken
            action: Action that was executed
            params: Parameters used
            success: 1 if success, 0 if fail, -1 if canceled
        """
        # Update RL agent
        try:
            self.rl_agent.learn_from_outcome(context, situation, action, success)
        except Exception as e:
            print(f"[HybridAI] RL learning error: {e}")
        
        # Store few-shot example if successful
        if success == 1:
            try:
                self.few_shot.store_example(user_text, action, situation)
            except Exception as e:
                print(f"[HybridAI] Few-Shot storage error: {e}")
    
    def get_combined_stats(self):
        """Get statistics from all learning systems."""
        stats = {}
        
        try:
            stats['rl'] = self.rl_agent.get_stats() if hasattr(self.rl_agent, 'get_stats') else {}
        except:
            stats['rl'] = {}
        
        try:
            stats['knn'] = self.knn_predictor.get_learning_stats()
        except:
            stats['knn'] = {}
        
        try:
            stats['meta'] = self.meta_learner.get_transfer_stats()
        except:
            stats['meta'] = {}
        
        try:
            stats['few_shot'] = self.few_shot.get_stats()
        except:
            stats['few_shot'] = {}
        
        return stats


# Global instance
_hybrid_ai = None

def get_hybrid_ai():
    global _hybrid_ai
    if _hybrid_ai is None:
        _hybrid_ai = HybridIntelligence()
    return _hybrid_ai
