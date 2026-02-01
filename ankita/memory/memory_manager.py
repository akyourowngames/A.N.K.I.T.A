"""
Ankita Memory Manager - 4-layer memory system.

1. Conversation: Last few turns (short-term)
2. Episodes: What Ankita did (actions with tags)
3. Semantic: Meaning-based recall (embeddings)
4. Preferences: User habits (learnable)
"""

import json
import os
import uuid
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
    mem["conversation"] = mem["conversation"][-15:]  # Keep last 15 turns
    save(mem)

def get_conversation():
    """Get recent conversation history."""
    return load()["conversation"]


# ============== EPISODES (action memory with TAGS) ==============

def _generate_tags(intent: str, entities: dict) -> list:
    """Auto-generate tags from intent and entities."""
    tags = []
    
    # Intent-based tags
    if "youtube" in intent:
        tags.append("youtube")
        tags.append("music")
    if "notepad" in intent:
        tags.append("notes")
        tags.append("writing")
    if "play" in intent:
        tags.append("play")
    if "write" in intent or "note" in intent:
        tags.append("write")
    
    # Entity-based tags
    if "query" in entities:
        query = entities["query"].lower()
        if any(w in query for w in ["lofi", "chill", "beats", "music"]):
            tags.append("music")
        if any(w in query for w in ["study", "learn", "notes"]):
            tags.append("study")
    
    if "content" in entities:
        content = entities["content"].lower()
        if any(w in content for w in ["physics", "math", "chemistry", "biology"]):
            tags.append("study")
        if any(w in content for w in ["todo", "buy", "remember"]):
            tags.append("task")
    
    return list(set(tags))


def add_episode(intent: str, entities: dict, result: dict, tags: list = None):
    """Record an action Ankita performed with auto-tagging."""
    mem = load()
    
    # Auto-generate tags if not provided
    if tags is None:
        tags = _generate_tags(intent, entities)
    
    episode = {
        "id": f"ep_{uuid.uuid4().hex[:8]}",
        "intent": intent,
        "entities": entities,
        "result": result,
        "tags": tags,
        "time": datetime.now().isoformat()
    }
    
    mem["episodes"].append(episode)
    mem["episodes"] = mem["episodes"][-100:]  # Keep last 100 episodes
    save(mem)
    
    return episode


def last_episode():
    """Get the most recent action."""
    eps = load()["episodes"]
    return eps[-1] if eps else None


def get_episodes(limit: int = 10):
    """Get recent episodes."""
    return load()["episodes"][-limit:]


def find_episodes(tag: str = None, intent: str = None, limit: int = 10) -> list:
    """Find episodes by tag or intent."""
    episodes = load()["episodes"]
    results = []
    
    for ep in reversed(episodes):
        match = True
        if tag and tag not in ep.get("tags", []):
            match = False
        if intent and intent not in ep.get("intent", ""):
            match = False
        if match:
            results.append(ep)
            if len(results) >= limit:
                break
    
    return results


# ============== PREFERENCES (learnable habits) ==============

def set_pref(key: str, value):
    """Set a user preference."""
    mem = load()
    mem["preferences"][key] = {
        "value": value,
        "count": mem["preferences"].get(key, {}).get("count", 0) + 1,
        "updated": datetime.now().isoformat()
    }
    save(mem)


def get_pref(key: str, default=None):
    """Get a user preference value."""
    pref = load()["preferences"].get(key)
    if pref is None:
        return default
    return pref.get("value", default) if isinstance(pref, dict) else pref


def learn_pref(key: str, value):
    """Learn a preference from repeated behavior."""
    mem = load()
    pref = mem["preferences"].get(key, {"value": value, "count": 0})
    
    if isinstance(pref, dict):
        if pref.get("value") == value:
            pref["count"] = pref.get("count", 0) + 1
        else:
            # Different value - only change if new is more frequent
            pref = {"value": value, "count": 1}
    else:
        pref = {"value": value, "count": 1}
    
    pref["updated"] = datetime.now().isoformat()
    mem["preferences"][key] = pref
    save(mem)


def get_all_prefs() -> dict:
    """Get all preferences."""
    prefs = load()["preferences"]
    return {k: v.get("value") if isinstance(v, dict) else v for k, v in prefs.items()}


# ============== NOTES (backward compat) ==============

def add_note(filename: str, content: str = ""):
    """Track a note file with content for semantic indexing."""
    mem = load()
    mem["notes"].append({
        "file": filename,
        "content_preview": content[:200] if content else "",
        "time": datetime.now().isoformat()
    })
    save(mem)
    
    # Also index semantically if content provided
    if content:
        from memory.semantic import add_semantic
        add_semantic(
            text=content,
            source="note",
            ref=filename,
            tags=["notes", "writing"]
        )


def last_note():
    """Get the last note."""
    mem = load()
    return mem["notes"][-1] if mem["notes"] else None
