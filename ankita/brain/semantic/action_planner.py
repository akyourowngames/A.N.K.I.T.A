"""
Semantic Action Planner - Generates action chains for situations.

Applies DWIM (Do What I Mean) rules based on context.
"""

import json
import os


class SemanticActionPlanner:
    """Plans actions for detected situations with context awareness."""
    
    def __init__(self):
        """Initialize the action planner."""
        self.situations = self._load_situations()
    
    def _load_situations(self):
        """Load situation definitions."""
        situations_path = os.path.join(os.path.dirname(__file__), 'situations.json')
        with open(situations_path, encoding='utf-8') as f:
            return json.load(f)
    
    def plan_actions(self, situation, context=None):
        """
        Generate action chain for a situation.
        
        Args:
            situation: str, situation name
            context: dict, optional context for DWIM rules
                - battery_percent: int (0-100)
                - hotspot_available: bool
                - wifi_connected: bool
                - time_of_day: str ('morning', 'afternoon', 'evening', 'night')
        
        Returns:
            list of action dicts
        """
        if situation not in self.situations:
            return []
        
        actions = self.situations[situation]['actions'].copy()
        
        # Apply DWIM rules if context provided
        if context:
            actions = self._apply_dwim_rules(situation, actions, context)
        
        return actions
    
    def _apply_dwim_rules(self, situation, actions, context):
        """
        Context-aware action modification (Do What I Mean).
        
        Rules:
        - If battery < 20%, avoid heavy actions
        - If on hotspot, prefer it over wifi
        - If night time, prefer lower brightness
        - If user recently rejected, skip similar actions
        """
        filtered_actions = []
        battery = context.get('battery_percent', 100)
        time_of_day = context.get('time_of_day', 'day')
        
        for action in actions:
            tool = action.get('tool', '')
            
            # Battery-aware filtering
            if battery < 20:
                # Skip heavy actions when battery low
                if tool in ['youtube.play', 'youtube.open']:
                    print(f"[DWIM] Skipping {tool} - battery low ({battery}%)")
                    continue
            
            # Network preference for network_slow situation
            if situation == 'network_slow':
                if context.get('hotspot_available'):
                    # If hotspot available, suggest it
                    if action.get('action') == 'on' and tool == 'system.wifi':
                        # Replace wifi reconnect with hotspot
                        action = {'tool': 'system.hotspot', 'action': 'on'}
                        print("[DWIM] Preferring hotspot over wifi")
            
            # Time-based brightness adjustment
            if tool == 'system.brightness':
                if time_of_day == 'night' and action.get('value', 50) > 30:
                    action = action.copy()
                    action['value'] = min(action.get('value', 50), 30)
                    print(f"[DWIM] Lowering brightness for night time")
            
            filtered_actions.append(action)
        
        return filtered_actions
    
    def get_situation_description(self, situation):
        """Get human-readable description of what will be done."""
        if situation in self.situations:
            return self.situations[situation].get('description', f"Handling {situation}.")
        return f"Handling {situation}."
    
    def get_all_situations(self):
        """Get list of all available situations."""
        return list(self.situations.keys())


# Singleton instance
_planner = None


def get_planner():
    """Get or create the global planner instance."""
    global _planner
    if _planner is None:
        _planner = SemanticActionPlanner()
    return _planner
