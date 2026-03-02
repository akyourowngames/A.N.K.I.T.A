"""
Hippocampus — Core Persistent Memory for A.N.K.I.T.A 🧠

A dead-simple, fast, always-on JSON vault that persists forever.
No LangChain. No vector DB overhead. Pure speed.

Structure of .ankita/memory.json:
{
  "user_profile": ["Name is Krish", "Likes Python", "Hates verbose output"],
  "projects":     {"nova_move": "AI Assistant project"},
  "facts":        ["The server IP is 192.168.1.5", "My dog's name is Bruno"]
}

Tools exposed:
  remember(text, category) → saves a fact
  recall(query)            → searches the vault
  forget(text)             → deletes a memory
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────────

MEMORY_FILE = Path(".ankita") / "memory.json"
_LOCK = threading.Lock()   # thread-safe for concurrent agent access

_DEFAULT_STRUCTURE: Dict[str, Any] = {
    "user_profile": [],   # personal info: name, age, location, role
    "facts":        [],   # general facts: server IPs, pet names, dates
    "projects":     {},   # project name → description
    "preferences":  [],   # likes, dislikes, habits, coding style
    "people":       [],   # family, friends, colleagues
    "locations":    [],   # home, office, favourite places
}

# Minimum similarity ratio (0-1) for fuzzy deduplication
_FUZZY_THRESHOLD = 0.82


def _load_memory() -> Dict[str, Any]:
    """Read the vault from disk. Returns a default structure if missing/corrupt."""
    try:
        if MEMORY_FILE.exists():
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Ensure required keys always exist
            for key, default in _DEFAULT_STRUCTURE.items():
                if key not in data:
                    data[key] = type(default)()
            return data
    except Exception as _load_err:
        print(f"[Memory] ⚠️  Failed to load memory.json: {_load_err} — starting fresh", flush=True)
    return {k: ([] if isinstance(v, list) else {}) for k, v in _DEFAULT_STRUCTURE.items()}


def _save_memory(data: Dict[str, Any]) -> None:
    """Write the vault to disk atomically."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file first, then rename — prevents corruption on crash
    tmp = MEMORY_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(MEMORY_FILE)


def _fuzzy_similar(a: str, b: str) -> float:
    """Return similarity ratio between two strings (0.0 – 1.0)."""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _is_duplicate(text: str, existing: List[str]) -> Optional[str]:
    """
    Return the existing item if it's too similar to text, else None.
    Used to prevent near-duplicate memories like 'likes Python' vs 'I like Python'.
    """
    for item in existing:
        if _fuzzy_similar(text, item) >= _FUZZY_THRESHOLD:
            return item
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Public Tools
# ─────────────────────────────────────────────────────────────────────────────

def remember(text: str, category: str = "facts") -> str:
    """
    Save a permanent memory to the vault.

    Use when the user says:
    - "Remember that I use Python 3.10"
    - "My name is Krish"
    - "I prefer dark mode"
    - "Note that the server IP is 192.168.1.5"
    - "I like hiking" → category: preferences
    - "My friend is Advait" → category: people
    - "I live in Mumbai" → category: locations

    Auto-categorises if category not specified:
    - Mentions of name/age/role → user_profile
    - Mentions of like/prefer/hate/love → preferences
    - Mentions of friend/family/colleague → people
    - Mentions of city/place/live/home → locations
    - Project names → projects

    Args:
        text:     The fact or preference to remember.
        category: Where to store it. One of: 'user_profile', 'facts', 'projects',
                  'preferences', 'people', 'locations'. Defaults to 'facts'.

    Returns:
        Confirmation string.
    """
    if not text or not text.strip():
        return "Nothing to remember — text was empty."

    text = text.strip()

    # --- Auto-categorise if caller left it at default 'facts' ---
    if category == "facts":
        tl = text.lower()
        if any(kw in tl for kw in ("my name is", "i am", "i'm", "age is", "i work", "my role")):
            category = "user_profile"
        elif any(kw in tl for kw in ("i like", "i love", "i hate", "i prefer", "i dislike",
                                      "i use", "i always", "i never", "my style", "i enjoy")):
            category = "preferences"
        elif any(kw in tl for kw in ("my friend", "my brother", "my sister", "my mom", "my dad",
                                      "my colleague", "my boss", "my team", "my family")):
            category = "people"
        elif any(kw in tl for kw in ("i live", "my home", "my office", "my city", "my address",
                                      "i'm from", "i am from", "based in")):
            category = "locations"

    # Validate category — only allow known categories to prevent junk key accumulation
    _VALID_CATEGORIES = set(_DEFAULT_STRUCTURE.keys())
    if category not in _VALID_CATEGORIES:
        # Map unknown category to closest known one
        print(f"[Memory] ⚠️  Unknown category '{category}' — mapping to 'facts'", flush=True)
        category = "facts"

    # Cap per-category list size (keep newest 100 items — prune oldest)
    _MAX_ITEMS_PER_CATEGORY = 100

    with _LOCK:
        data = _load_memory()

        # Ensure category exists (known categories only now)
        if category not in data:
            data[category] = type(_DEFAULT_STRUCTURE[category])()

        target = data[category]

        if isinstance(target, list):
            # Exact duplicate check
            if text in target:
                return f"✅ Already knew that: '{text}'"
            # Fuzzy duplicate check — avoid near-duplicate memories
            fuzzy_match = _is_duplicate(text, target)
            if fuzzy_match:
                return f"✅ Already have something similar: '{fuzzy_match}'"
            target.append(text)
            # Prune oldest entries if over cap
            if len(target) > _MAX_ITEMS_PER_CATEGORY:
                pruned = len(target) - _MAX_ITEMS_PER_CATEGORY
                data[category] = target[-_MAX_ITEMS_PER_CATEGORY:]
                print(f"[Memory] 🗑️  Pruned {pruned} oldest entries from [{category}] (cap={_MAX_ITEMS_PER_CATEGORY})", flush=True)
        elif isinstance(target, dict):
            # For dict categories (e.g. 'projects'), use text as a key with empty value
            # Format: "key: value" or just "key"
            if ":" in text:
                k, v = text.split(":", 1)
                target[k.strip()] = v.strip()
            else:
                target[text] = ""
        else:
            return f"Category '{category}' has an unexpected type — cannot store."

        _save_memory(data)
        return f"🧠 Memory stored: '{text}' → [{category}]"


def recall(query: Optional[str] = None) -> str:
    """
    Search the vault for memories.

    Args:
        query: Optional keyword to search for. If omitted, returns ALL memories.

    Returns:
        Formatted string of matching memories, or 'No matching memories found.'
    """
    with _LOCK:
        data = _load_memory()

    if not query:
        # Return a human-readable summary instead of raw JSON
        total_items = sum(
            len(v) if isinstance(v, list) else len(v)
            for v in data.values()
        )
        if total_items == 0:
            return "No memories stored yet. Tell me things about yourself and I'll remember them!"
        lines = ["📚 Here's everything I remember:\n"]
        for cat, items in data.items():
            if not items:
                continue
            label = cat.replace("_", " ").title()
            lines.append(f"**{label}:**")
            if isinstance(items, list):
                for item in items:
                    lines.append(f"  • {item}")
            elif isinstance(items, dict):
                for k, v in items.items():
                    lines.append(f"  • {k}: {v}" if v else f"  • {k}")
        return "\n".join(lines)

    query_lower = query.lower().strip()
    hits: List[str] = []

    for cat, items in data.items():
        if isinstance(items, list):
            for item in items:
                if query_lower in str(item).lower():
                    hits.append(f"[{cat}] {item}")
        elif isinstance(items, dict):
            for k, v in items.items():
                combined = f"{k} {v}".lower()
                if query_lower in combined:
                    hits.append(f"[{cat}] {k}: {v}" if v else f"[{cat}] {k}")

    return "\n".join(hits) if hits else f"No memories matching '{query}'."


def forget(text: str) -> str:
    """
    Delete a specific memory from the vault.
    Uses fuzzy matching — you don't need the exact text, just something close.

    Args:
        text: The memory text to delete (exact or approximate).

    Returns:
        Confirmation string.
    """
    if not text or not text.strip():
        return "Nothing to forget — text was empty."

    text = text.strip()

    with _LOCK:
        data = _load_memory()
        deleted_from: List[str] = []
        deleted_what: List[str] = []

        for cat, items in data.items():
            if isinstance(items, list):
                # Exact match first
                if text in items:
                    items.remove(text)
                    deleted_from.append(cat)
                    deleted_what.append(text)
                else:
                    # Fuzzy match — find the closest item
                    best = max(items, key=lambda x: _fuzzy_similar(text, x), default=None)
                    if best and _fuzzy_similar(text, best) >= _FUZZY_THRESHOLD:
                        items.remove(best)
                        deleted_from.append(cat)
                        deleted_what.append(best)
            elif isinstance(items, dict):
                # Try exact key match
                if text in items:
                    del items[text]
                    deleted_from.append(cat)
                    deleted_what.append(text)
                # Try "key: value" format
                elif ":" in text:
                    k, _ = text.split(":", 1)
                    k = k.strip()
                    if k in items:
                        del items[k]
                        deleted_from.append(cat)
                        deleted_what.append(k)
                else:
                    # Fuzzy key match
                    best_k = max(items.keys(), key=lambda x: _fuzzy_similar(text, x), default=None)
                    if best_k and _fuzzy_similar(text, best_k) >= _FUZZY_THRESHOLD:
                        del items[best_k]
                        deleted_from.append(cat)
                        deleted_what.append(best_k)

        if deleted_from:
            _save_memory(data)
            what = "', '".join(deleted_what)
            return f"🗑️ Forgot: '{what}' (removed from [{', '.join(deleted_from)}])"

    return f"Could not find anything similar to '{text}' in memory. Nothing deleted."


# ─────────────────────────────────────────────────────────────────────────────
# Memory Block Formatter (used by orchestrator for injection)
# ─────────────────────────────────────────────────────────────────────────────

def auto_extract_memories(user_text: str, assistant_reply: str) -> List[str]:
    """
    Automatically extract key facts from a conversation turn and store them.

    Fully LLM-driven — no hardcoded keyword lists or category rules.
    The model decides what is worth remembering and how to categorize it.

    Runs a lightweight LLM pass over (user_text, assistant_reply) to identify
    any personal facts, preferences, names, locations, or projects worth remembering.
    Silently skips if nothing extractable is found.

    Returns:
        List of newly stored memory strings (empty if nothing new found).
    """
    # Skip very short messages that are unlikely to contain facts (< 4 words)
    # This avoids wasting API calls on one-word replies like "ok", "thanks", "yes"
    if len(user_text.split()) < 4:
        return []

    try:
        from llm.client import build_runtime_from_env, call_chat_once  # type: ignore

        runtime = build_runtime_from_env()

        # Get existing memories to avoid re-storing duplicates
        existing = format_memory_block()

        extraction_prompt = (
            "You are a personal memory extractor for an AI assistant.\n"
            "Analyse the conversation turn below and extract any facts worth remembering long-term about the USER.\n\n"
            "What to extract:\n"
            "- Personal details (name, age, location, occupation, nationality)\n"
            "- Preferences and opinions (likes, dislikes, habits, favourite things)\n"
            "- People they mention (friends, family, colleagues)\n"
            "- Places (where they live, work, study, visit)\n"
            "- Projects or goals they are working on\n"
            "- Any specific facts they share about themselves\n\n"
            "What to skip:\n"
            "- Questions the user is asking\n"
            "- General knowledge queries (weather, news, coding help)\n"
            "- Hypotheticals or jokes\n"
            "- Facts already in memory (shown below)\n"
            "- Vague or unclear statements\n\n"
            f"Existing memories (do NOT re-extract these):\n{existing or 'None yet'}\n\n"
            f"User said: {user_text}\n"
            f"Assistant replied: {assistant_reply[:300]}\n\n"
            "Output ONLY a JSON array (or [] if nothing to store):\n"
            '[{"text": "User\'s name is Prakhar", "category": "user_profile"}, ...]\n'
            "Valid categories: user_profile, facts, preferences, people, locations, projects\n"
            "JSON array only:"
        )

        _messages = [
            {
                "role": "system",
                "content": (
                    "You extract personal facts from conversations and output only valid JSON arrays. "
                    "Never output anything other than a JSON array. If nothing to extract, output []."
                ),
            },
            {
                "role": "user",
                "content": extraction_prompt,
            },
        ]
        response_msg = call_chat_once(runtime, _messages, None, 400)
        raw = str(response_msg.get("content") or "")

        # Parse JSON — handle markdown code fences if model wraps in ```json
        import re as _re
        # Strip markdown fences
        raw_clean = _re.sub(r"```(?:json)?", "", raw).strip().strip("`")
        match = _re.search(r"\[.*?\]", raw_clean, _re.DOTALL)
        if not match:
            return []

        facts = json.loads(match.group())
        if not isinstance(facts, list):
            return []

        stored = []
        for item in facts:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            category = str(item.get("category", "facts")).strip()
            if not text or len(text) < 8:
                continue
            result = remember(text, category)
            if "Already" not in result:
                stored.append(text)
                print(f"[AutoMemory] 💡 Stored: [{category}] {text}", flush=True)

        return stored

    except Exception as _e:
        print(f"[AutoMemory] ⚠️  Extraction failed: {_e}", flush=True)
        return []


def auto_extract_memories_async(user_text: str, assistant_reply: str) -> None:
    """
    Fire-and-forget wrapper for auto_extract_memories().
    Runs in a daemon thread so it never blocks the main conversation.
    """
    import threading
    t = threading.Thread(
        target=auto_extract_memories,
        args=(user_text, assistant_reply),
        daemon=True,
        name="AutoMemoryExtractor",
    )
    t.start()


def format_memory_block() -> str:
    """
    Returns a clean, LLM-readable memory block for injection into agent system prompts.

    Example output:
        --- LONG TERM MEMORY ---
        USER PROFILE:
        - Name is Krish
        - Prefers Python 3.10
        FACTS:
        - Server IP is 192.168.1.5
        PROJECTS:
        - nova_move: AI Assistant project
        ------------------------

    Returns empty string if the vault is empty (avoids useless padding).
    """
    with _LOCK:
        data = _load_memory()

    lines: List[str] = []

    profile = data.get("user_profile", [])
    facts = data.get("facts", [])
    projects = data.get("projects", {})

    has_content = bool(profile or facts or projects)
    if not has_content:
        return ""

    lines.append("--- LONG TERM MEMORY ---")

    if profile:
        lines.append("USER PROFILE:")
        for item in profile:
            lines.append(f"- {item}")

    preferences = data.get("preferences", [])
    if preferences:
        lines.append("PREFERENCES:")
        for item in preferences:
            lines.append(f"- {item}")

    people = data.get("people", [])
    if people:
        lines.append("PEOPLE:")
        for item in people:
            lines.append(f"- {item}")

    locations = data.get("locations", [])
    if locations:
        lines.append("LOCATIONS:")
        for item in locations:
            lines.append(f"- {item}")

    if facts:
        lines.append("FACTS:")
        for item in facts:
            lines.append(f"- {item}")

    if projects:
        lines.append("PROJECTS:")
        for k, v in projects.items():
            lines.append(f"- {k}: {v}" if v else f"- {k}")

    lines.append("------------------------")
    return "\n".join(lines)
