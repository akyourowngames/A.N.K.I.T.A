"""
Ankita Memory Manager - 3-layer memory system.

1. Conversation: Last few turns (short-term)
2. Episodes: What Ankita did (actions)
3. Preferences: User habits (long-term)
"""

import json
import os
from datetime import datetime

MEMORY_PATH = os.path.join(os.path.dirname(__file__), "memory.json")

def load():
    if not os.path.exists(MEMORY_PATH):
        return {"conversation": [], "episodes": [], "preferences": {}, "notes": []}
    with open(MEMORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save(data):
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ============== CONVERSATION (short-term) ==============

def add_conversation(role: str, text: str):
    """Add a conversation turn (user or ankita)."""
    mem = load()
    mem["conversation"].append({
        "role": role,
        "text": text,
        "time": datetime.now().isoformat()
    })
    mem["conversation"] = mem["conversation"][-10:]  # Keep last 10 turns
    save(mem)

def get_conversation():
    """Get recent conversation history."""
    return load()["conversation"]


# ============== EPISODES (action memory) ==============

def add_episode(intent: str, entities: dict, result: dict):
    """Record an action Ankita performed."""
    mem = load()
    mem["episodes"].append({
        "intent": intent,
        "entities": entities,
        "result": result,
        "time": datetime.now().isoformat()
    })
    mem["episodes"] = mem["episodes"][-50:]  # Keep last 50 episodes
    save(mem)

def last_episode():
    """Get the most recent action."""
    eps = load()["episodes"]
    return eps[-1] if eps else None

def get_episodes(limit: int = 10):
    """Get recent episodes."""
    return load()["episodes"][-limit:]


# ============== PREFERENCES (habits) ==============

def set_pref(key: str, value):
    """Set a user preference."""
    mem = load()
    mem["preferences"][key] = value
    save(mem)

def get_pref(key: str, default=None):
    """Get a user preference."""
    return load()["preferences"].get(key, default)


# ============== NOTES (backward compat) ==============

def add_note(filename: str):
    """Track a note file."""
    mem = load()
    mem["notes"].append({"file": filename})
    save(mem)

def last_note():
    """Get the last note."""
    mem = load()
    return mem["notes"][-1] if mem["notes"] else None
