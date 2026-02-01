"""
Ankita Recall - Memory-aware pronoun resolution.

Enables:
- "do it again"
- "continue that"
- "play it again"
- "open it"

Without LLM hallucinations - pure deterministic recall.
"""

from memory.memory_manager import last_episode, get_conversation


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
