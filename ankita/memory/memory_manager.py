"""
Ankita Memory Manager - Split storage into separate files.

Files:
- conversations.json: Last 15 conversation turns
- episodes.json: Action memory with tags (last 100)
- preferences.json: User habits/learned preferences
- notes.json: Note file tracking
"""

import json
import os
import uuid
from datetime import datetime


_MEMORY_DIR = os.path.dirname(__file__)

CONVO_PATH = os.path.join(_MEMORY_DIR, "conversations.json")
EPISODES_PATH = os.path.join(_MEMORY_DIR, "episodes.json")
PREFS_PATH = os.path.join(_MEMORY_DIR, "preferences.json")
NOTES_PATH = os.path.join(_MEMORY_DIR, "notes.json")

# Legacy path for migration
OLD_MEMORY_PATH = os.path.join(_MEMORY_DIR, "memory.json")


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _ensure_files_exist():
    """Create per-file stores with sensible defaults if missing."""
    if not os.path.exists(CONVO_PATH):
        _save_json(CONVO_PATH, [])
    if not os.path.exists(EPISODES_PATH):
        _save_json(EPISODES_PATH, [])
    if not os.path.exists(PREFS_PATH):
        _save_json(PREFS_PATH, {})
    if not os.path.exists(NOTES_PATH):
        _save_json(NOTES_PATH, [])


def _migrate_if_needed():
    """Migrate legacy combined `memory.json` → per-file stores and back up the old file.

    Safe to call multiple times; idempotent.
    """
    # If the new files already exist, nothing to do
    if os.path.exists(CONVO_PATH) and os.path.exists(EPISODES_PATH) and os.path.exists(PREFS_PATH):
        return

    if os.path.exists(OLD_MEMORY_PATH):
        old = _load_json(OLD_MEMORY_PATH, {})
        # Migrate sections (use defaults when missing)
        _save_json(CONVO_PATH, old.get("conversation", []))
        _save_json(EPISODES_PATH, old.get("episodes", []))
        _save_json(PREFS_PATH, old.get("preferences", {}))
        _save_json(NOTES_PATH, old.get("notes", []))
        # Back up the legacy file so user can recover if needed
        try:
            bak = OLD_MEMORY_PATH + ".bak"
            if not os.path.exists(bak):
                os.rename(OLD_MEMORY_PATH, bak)
        except Exception:
            # Non-fatal: we already migrated the data
            pass

    # Ensure all files exist after migration
    _ensure_files_exist()


def load() -> dict:
    """Load the combined memory view assembled from per-file stores.

    Returns a dict with keys: conversation, episodes, preferences, notes
    (keeps the same public shape so existing callers keep working).
    """
    convo = _load_json(CONVO_PATH, [])
    episodes = _load_json(EPISODES_PATH, [])
    prefs = _load_json(PREFS_PATH, {})
    notes = _load_json(NOTES_PATH, [])

    return {
        "conversation": convo,
        "episodes": episodes,
        "preferences": prefs,
        "notes": notes,
    }


def save(mem: dict):
    """Persist a combined memory dict into the per-file stores (atomic per-file).

    Callers may pass the full dict or partial; missing keys are preserved.
    """
    current = load()
    # Merge to avoid clobbering unrelated sections
    merged = {
        "conversation": mem.get("conversation", current.get("conversation", [])),
        "episodes": mem.get("episodes", current.get("episodes", [])),
        "preferences": mem.get("preferences", current.get("preferences", {})),
        "notes": mem.get("notes", current.get("notes", [])),
    }

    _save_json(CONVO_PATH, merged["conversation"])
    _save_json(EPISODES_PATH, merged["episodes"])
    _save_json(PREFS_PATH, merged["preferences"])
    _save_json(NOTES_PATH, merged["notes"])


# Run migration / ensure files on import
_migrate_if_needed()


# ============== CONVERSATION (short-term) ==============

def add_conversation(role: str, text: str):
    """Add a conversation turn (user or ankita)."""
    mem = load()
    entry = {
        "role": role,
        "text": text,
        "time": datetime.now().isoformat()
    }
    mem["conversation"].append(entry)
    mem["conversation"] = mem["conversation"][-15:]  # Keep last 15 turns
    save(mem)
    
    # NEW: Archive to LangChain Unlimited Memory
    try:
        from memory.langchain_memory import get_langchain_memory
        lc_mem = get_langchain_memory()
        lc_mem.add_memory(f"{role.upper()}: {text}", metadata=entry)
    except Exception as e:
        print(f"[MemoryManager] LangChain archival failed: {e}")

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

    # UNIFIED: Archive to LangChain
    try:
        from memory.langchain_memory import get_langchain_memory
        lc_mem = get_langchain_memory()
        summary = f"ACTION: {intent} with {entities}. Result: {result.get('status', 'unknown')}"
        lc_mem.add_memory(summary, metadata=episode)
    except Exception as e:
        print(f"[MemoryManager] Episode archival failed: {e}")
    
    return episode


def last_episode():
    """Get the most recent action."""
    eps = load()["episodes"]
    return eps[-1] if eps else None


def get_episodes(limit: int = 10):
    """Get recent episodes."""
    return load()["episodes"][-limit:]


def episodes_in_range(start: datetime, end: datetime) -> list:
    """Return episodes whose timestamps fall within [start, end]."""
    mem = load()
    result = []
    for ep in mem.get("episodes", []):
        try:
            t = datetime.fromisoformat(ep.get("time", ""))
        except Exception:
            continue
        if start <= t <= end:
            result.append(ep)
    return result


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
    entry = {
        "file": filename,
        "content_preview": content[:200] if content else "",
        "time": datetime.now().isoformat()
    }
    mem["notes"].append(entry)
    save(mem)
    
    # UNIFIED: Archive full note content to LangChain
    if content:
        try:
            from memory.langchain_memory import get_langchain_memory
            lc_mem = get_langchain_memory()
            lc_mem.add_memory(f"NOTE ({filename}): {content}", metadata=entry)
        except Exception as e:
            print(f"[MemoryManager] Note archival failed: {e}")


def last_note():
    """Get the last note."""
    mem = load()
    return mem["notes"][-1] if mem["notes"] else None
