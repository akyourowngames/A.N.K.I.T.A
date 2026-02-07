"""
Active Learner - Ask user when uncertain for immediate learning
"""
from brain.learning_db import get_db
from brain.context_collector import get_current_context


class ActiveLearner:
    """
    Active learning system that queries user when uncertain.
    Enables 1-shot learning from user feedback.
    """
    
    def __init__(self, uncertainty_threshold=0.6):
        """
        Args:
            uncertainty_threshold: Ask user if confidence below this (0-1)
        """
        self.threshold = uncertainty_threshold
        self.db = get_db()
    
    def should_query_user(self, predictions):
        """
        Determine if we should ask user.
        
        Args:
            predictions: List of prediction dicts with 'confidence'
        
        Returns:
            tuple: (should_ask: bool, top_options: list)
        """
        if not predictions:
            return False, []
        
        # Get top prediction
        top = max(predictions, key=lambda p: p.get('confidence', 0))
        top_conf = top.get('confidence', 0)
        
        if top_conf < self.threshold:
            # Uncertain! Show top 2-3 options
            sorted_preds = sorted(predictions, 
                                key=lambda p: p.get('confidence', 0), 
                                reverse=True)
            top_options = sorted_preds[:min(3, len(sorted_preds))]
            return True, top_options
        
        return False, []
    
    def format_query(self, situation, options):
        """
        Format user query message.
        
        Returns:
            str: Formatted question
        """
        if not options:
            return None
        
        msg = f"\n[Ankita] I'm not sure what to do for '{situation}'. Should I:\n"
        
        for i, opt in enumerate(options, 1):
            action = opt.get('action', 'unknown')
            conf = opt.get('confidence', 0)
            msg += f"  {chr(64+i)}) {action} (confidence: {conf:.0%})\n"
        
        msg += f"  {chr(64+len(options)+1)}) Something else\n"
        msg += "Your choice (A/B/C...):"
        
        return msg
    
    def process_user_choice(self, situation, context, options, choice):
        """
        Process user's choice and learn immediately.
        
        Args:
            situation: Situation name
            context: Current context
            options: List of action options shown
            choice: User's choice (A/B/C/etc or action name)
        
        Returns:
            dict: Selected action with boosted confidence
        """
        choice_upper = choice.strip().upper()
        
        # Map letter to index
        if len(choice_upper) == 1 and choice_upper.isalpha():
            idx = ord(choice_upper) - 65  # A=0, B=1, C=2
            
            if 0 <= idx < len(options):
                selected = options[idx]
                action = selected['action']
                
                # Log this as a successful learning event
                self.db.log_action(
                    context=context,
                    action=action,
                    params=selected.get('params', {}),
                    success=1,  # User chose it
                    exec_time_ms=0
                )
                
                print(f"[ActiveLearning] User taught: {situation} → {action}")
                
                # Return with boosted confidence
                return {
                    'action': action,
                    'params': selected.get('params', {}),
                    'confidence': 0.95,  # High confidence from user teaching
                    'source': 'user_taught'
                }
        
        return None
    
    def teach_new_action(self, situation, context, action, params=None):
        """
        User teaches a new action directly.
        
        For when user says "you should do X" or corrects behavior.
        """
        self.db.log_action(
            context=context,
            action=action,
            params=params or {},
            success=1,
            exec_time_ms=0
        )
        
        print(f"[ActiveLearning] New teaching: {situation} → {action}")


_active_learner = None

def get_active_learner():
    global _active_learner
    if _active_learner is None:
        _active_learner = ActiveLearner()
    return _active_learner
