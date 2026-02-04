from typing import Dict, List

class IntentResult(dict):
    intent: str
    entities: Dict

class Plan(dict):
    steps: List[Dict]
