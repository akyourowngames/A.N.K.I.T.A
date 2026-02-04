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
import re


def resolve_pronouns(text: str) -> dict | None:
    """
    Check if text contains pronouns that refer to a past action.
    
    Returns:
        The last episode if pronouns detected, None otherwise.
    """
    t = text.lower()
    
    # Pronoun/reference patterns
    # Use regex to match whole words/phrases to avoid matching substrings
    reference_pattern = r"\b(?:do it|play it|open it|open that|continue it|continue that|the same|same|again|repeat|last|previous)\b"

    # Guard: avoid replaying last action when the user is issuing an explicit new command
    # like "continue note ..." or "write in notepad ...".
    # We only want recall when there's an actual reference target (it/that) or clear replay intent.
    has_explicit_target = re.search(r"\b(?:notepad|note|youtube|yt)\b", t) is not None
    has_true_reference = re.search(r"\b(?:it|that)\b", t) is not None
    has_replay_keyword = re.search(r"\b(?:again|repeat|previous|last)\b", t) is not None

    if has_explicit_target and not (has_true_reference or has_replay_keyword):
        return None

    if re.search(reference_pattern, t):
        last = last_episode()
        if last:
            return {
                "intent": last["intent"],
                "entities": last["entities"]
            }
    
    return None


def get_relevant_memories(text: str, threshold: float = 0.5) -> list:
    """
    Always search memory, return only relevant results.
    
    This replaces keyword-based is_memory_query().
    Memory is searched on EVERY input, but only injected if relevant.
    
    Args:
        text: User input
        threshold: Minimum relevance score (0-1)
    
    Returns:
        List of relevant memories (empty if none match)
    """
    results = []
    t = text.lower()
    
    # Check if user is explicitly asking about history/past
    is_history_query = any(kw in t for kw in [
        "what did", "what have", "so far", "history",
        "remember", "recall", "last time", "yesterday",
        "done before", "did i", "have i"
    ])
    
    # 1. Search semantic memory (meaning-based)
    try:
        from memory.semantic import search_semantic
        semantic_results = search_semantic(text, limit=3)
        for item in semantic_results:
            if item.get("score", 0) >= threshold:
                results.append({
                    "type": "semantic",
                    "text": item.get("text", ""),
                    "source": item.get("source", ""),
                    "ref": item.get("ref", ""),
                    "score": item.get("score", 0)
                })
    except Exception:
        pass
    
    # 2. Only add episodic memory if user is asking about history
    if is_history_query:
        # Smart tag detection from query
        tag = None
        if any(w in t for w in ["note", "wrote", "write", "written"]):
            tag = "notes"
        elif any(w in t for w in ["play", "music", "song", "youtube", "video"]):
            tag = "music"
        elif any(w in t for w in ["study", "learn", "physics", "math", "chemistry"]):
            tag = "study"
        
        episodes = find_episodes(tag=tag, limit=5) if tag else find_episodes(limit=5)
        
        for ep in episodes:
            # Skip unknown intents
            if ep.get("intent") == "unknown":
                continue
            results.append({
                "type": "episodic",
                "text": f"{ep.get('intent')}: {ep.get('entities')}",
                "time": ep.get("time", "")[:10],
                "score": 0.6  # History queries get higher score
            })
    
    # Sort by score, return top results
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:5]


def format_memories_for_llm(memories: list) -> str:
    """Format relevant memories as context for LLM prompt."""
    if not memories:
        return ""
    
    lines = ["Relevant memories:"]
    for m in memories:
        if m["type"] == "semantic":
            lines.append(f"- {m['text'][:100]} (from {m['source']})")
        else:
            lines.append(f"- {m['text']} on {m['time']}")
    
    return "\n".join(lines)


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
