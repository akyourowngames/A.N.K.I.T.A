"""
Ankita Recall - Memory-aware intent resolution.

Enables:
- "do it again" → replay last action
- "find my physics notes" → semantic search
- "what did I play yesterday?" → episodic search
- "open that note" → pronoun + memory

Memory is searched BEFORE LLM to prevent hallucination.
"""

from memory.memory_manager import last_episode, get_conversation, find_episodes
from memory.semantic import search_semantic, find_by_meaning


def resolve_pronouns(text: str) -> dict | None:
    """
    Check if text contains pronouns that refer to a past action.
    
    Returns:
        The last episode if pronouns detected, None otherwise.
    """
    t = text.lower()
    
    # Pronoun/reference patterns
    patterns = [
        "it", "that", "again", "continue", 
        "same", "repeat", "last", "previous",
        "do it", "play it", "open it", "the same"
    ]
    
    if any(p in t for p in patterns):
        last = last_episode()
        if last:
            return {
                "intent": last["intent"],
                "entities": last["entities"]
            }
    
    return None


def is_memory_query(text: str) -> bool:
    """Check if the user is asking to recall/find something."""
    t = text.lower()
    
    memory_keywords = [
        "find", "search", "show", "get", "open",
        "what did i", "when did i", "where did i",
        "my notes", "my last", "remember",
        "that note", "that song", "that video"
    ]
    
    return any(kw in t for kw in memory_keywords)


def search_memory(query: str) -> dict | None:
    """
    Search all memory layers for relevant information.
    
    Returns dict with:
        - source: where the result came from
        - results: list of matching items
        - best: the best single match
    """
    results = {
        "source": None,
        "results": [],
        "best": None
    }
    
    # 1. Try semantic search first (meaning-based)
    try:
        semantic_results = search_semantic(query, limit=3)
        if semantic_results and semantic_results[0]["score"] > 0.5:
            results["source"] = "semantic"
            results["results"] = semantic_results
            results["best"] = semantic_results[0]
            return results
    except Exception:
        pass
    
    # 2. Try episodic search (tag/intent based)
    t = query.lower()
    
    # Detect what they're looking for
    if "note" in t or "wrote" in t or "write" in t:
        episodes = find_episodes(tag="notes", limit=5)
    elif "play" in t or "music" in t or "song" in t or "youtube" in t:
        episodes = find_episodes(tag="music", limit=5)
    elif "study" in t or "learn" in t:
        episodes = find_episodes(tag="study", limit=5)
    else:
        episodes = find_episodes(limit=5)
    
    if episodes:
        results["source"] = "episodic"
        results["results"] = episodes
        results["best"] = episodes[0]
        return results
    
    return None


def get_memory_context(query: str) -> str:
    """
    Build memory context string to feed to LLM.
    Searches memory and formats results for the prompt.
    """
    if not is_memory_query(query):
        return ""
    
    search_result = search_memory(query)
    if not search_result:
        return ""
    
    # Format for LLM
    parts = [f"Relevant memories from {search_result['source']}:"]
    
    for item in search_result["results"][:3]:
        if search_result["source"] == "semantic":
            parts.append(f"- {item.get('text', '')[:100]} (from {item.get('source')})")
        else:
            parts.append(f"- {item.get('intent')}: {item.get('entities')} at {item.get('time', '')[:10]}")
    
    return "\n".join(parts)


def get_context_for_llm() -> str:
    """
    Build conversation context string for LLM prompts.
    """
    convo = get_conversation()
    if not convo:
        return ""
    
    lines = []
    for turn in convo[-5:]:  # Last 5 turns
        role = "User" if turn["role"] == "user" else "Ankita"
        lines.append(f"{role}: {turn['text']}")
    
    return "\n".join(lines)
