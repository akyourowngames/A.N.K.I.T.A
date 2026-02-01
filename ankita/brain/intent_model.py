"""
Intent Classifier - Layer 1: Rule-based (fast, deterministic).

This is the PRIMARY classifier:
1. Rules (keywords) - instant, safe ← THIS
2. Gemma (local) - fast, private
3. Cloud LLM (Groq) - smart but slower

Rules handle obvious, explicit commands.
Falls back to "unknown" for anything fuzzy.
"""

import json
import os
from brain.entity_extractor import extract

_INTENTS_PATH = os.path.join(os.path.dirname(__file__), "intents.json")
with open(_INTENTS_PATH, "r", encoding="utf-8") as f:
    _INTENTS = json.load(f)

_INTENT_NAMES = list(_INTENTS.keys())


def classify_rules(text: str) -> str:
    """
    Rule-based intent classification using keywords.
    Returns intent string or "unknown".
    """
    t = text.lower()
    
    # --- YouTube intents ---
    if "youtube" in t or "yt" in t:
        if any(w in t for w in ["play", "song", "video", "music", "watch", "search"]):
            return "youtube.play"
        else:
            return "youtube.open"
    
    # --- Notepad intents ---
    if "notepad" in t or "note" in t:
        if any(w in t for w in ["continue", "add to", "append", "keep writing"]):
            return "notepad.continue_note"
        elif any(w in t for w in ["write", "make", "create", "jot", "take"]):
            return "notepad.write_note"
        else:
            return "notepad.open"
    
    # --- Standalone play ---
    if any(w in t for w in ["play", "song", "video", "music"]):
        return "youtube.play"
    
    return "unknown"


def classify(text: str) -> dict:
    """
    Classify user text using rules.
    Returns dict with 'intent' and 'entities'.
    """
    intent = classify_rules(text)
    entities = extract(intent, text)
    
    return {
        "intent": intent,
        "entities": entities
    }
