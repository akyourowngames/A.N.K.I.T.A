"""
LLM Client - Ankita's voice (mouth, not hands).

The LLM generates natural language responses ONLY.
It does NOT control tools or make decisions.

Supports:
- Ollama (local, default)
- OpenAI API
- Any OpenAI-compatible API (Groq, Together, etc.)
"""

import os
import requests
from memory.memory_manager import get_conversation, last_episode

# API Configuration - Set via environment variables
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # "ollama", "openai", or "groq"
LLM_API_KEY = os.getenv("GROQ_API_KEY", os.getenv("LLM_API_KEY", ""))
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")  # Fast Groq model

# Template responses (fallback when LLM unavailable)
_TEMPLATES = {
    "youtube.play": "Playing that on YouTube for you 🎵",
    "youtube.open": "Opening YouTube.",
    "notepad.open": "Opening your note.",
    "notepad.write_note": "I've written that down and saved it for you 📝",
    "notepad.continue_note": "Added that to your existing note.",
    "unknown": "I'm not sure what you meant. Try: 'write a note' or 'play something on youtube'."
}

SYSTEM_PROMPT = """You are Ankita, a friendly AI assistant.

IMPORTANT RULES:
1. Be warm and concise (1-2 sentences max)
2. When given "Relevant memories", USE THEM in your response - they are facts about what the user has done
3. Never say "we didn't do much" if memories are provided - summarize them instead
4. When user asks what they've done, list the actions from memories"""


# ============== QUESTION DETECTION ==============

def is_question(text: str) -> bool:
    """Detect if text is a question or conversation."""
    t = text.lower().strip()
    
    # Ends with question mark
    if t.endswith("?"):
        return True
    
    # Starts with question words
    question_starters = (
        "what", "why", "how", "who", "when", "where", "which",
        "explain", "tell me", "can you", "could you", "do you",
        "is ", "are ", "was ", "were ", "will ", "would ",
        "should", "did ", "does ", "have you", "has "
    )
    
    return t.startswith(question_starters)


# ============== CONTEXT BUILDER ==============

def build_context(user_text: str) -> str:
    """Build conversation context for LLM from memory."""
    from memory.recall import get_relevant_memories, format_memories_for_llm
    
    parts = []
    
    # ALWAYS search memory, conditionally inject (gated approach)
    memories = get_relevant_memories(user_text, threshold=0.35)
    if memories:
        memory_ctx = format_memories_for_llm(memories)
        parts.append(memory_ctx)
    
    # Recent conversation
    convo = get_conversation()
    if convo:
        parts.append("\nRecent conversation:")
        for turn in convo[-5:]:
            role = "User" if turn["role"] == "user" else "Ankita"
            parts.append(f"  {role}: {turn['text']}")
    
    # Last action
    last = last_episode()
    if last:
        parts.append(f"\nLast action: {last['intent']} with {last['entities']}")
    
    # Current question
    parts.append(f"\nUser now says: {user_text}")
    
    return "\n".join(parts)


# ============== LLM API CALLS ==============

def _call_ollama(prompt: str) -> str:
    """Call local Ollama API."""
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "gemma2:2b",
            "prompt": prompt,
            "stream": False
        },
        timeout=10
    )
    return response.json().get("response", "").strip()


def _call_openai_api(messages: list) -> str:
    """Call OpenAI-compatible API."""
    response = requests.post(
        LLM_API_URL,
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": LLM_MODEL,
            "messages": messages,
            "max_tokens": 150,
            "temperature": 0.7
        },
        timeout=8
    )
    return response.json()["choices"][0]["message"]["content"].strip()


# ============== MAIN FUNCTIONS ==============

def ask_llm(user_text: str) -> str:
    """
    Ask LLM a question with conversation context.
    Used for unknown intents and questions.
    """
    context = build_context(user_text)
    
    try:
        if LLM_PROVIDER in ("openai", "groq") and LLM_API_KEY:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context}
            ]
            return _call_openai_api(messages)
        else:
            # Default to Ollama
            prompt = f"{SYSTEM_PROMPT}\n\n{context}\n\nAnkita:"
            return _call_ollama(prompt)
    except Exception as e:
        return f"I'm having trouble thinking right now. Try again? ({str(e)[:50]})"


def generate_response(context: dict) -> str:
    """
    Generate a natural language response after action execution.
    Falls back to templates if LLM unavailable.
    """
    intent = context.get("intent", "unknown")
    entities = context.get("entities", {})
    result = context.get("result", {})
    user_text = context.get("user_text", "")
    
    # Build action-specific prompt
    prompt = f"""{SYSTEM_PROMPT}

You have already executed the user's request successfully.

User said: "{user_text}"
Action taken: {intent}
Details: {entities}
Result: {result}

Generate a SHORT, natural, friendly response (1 sentence max).
Use an emoji if appropriate.

Response:"""
    
    try:
        if LLM_PROVIDER in ("openai", "groq") and LLM_API_KEY:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]
            response = _call_openai_api(messages)
        else:
            response = _call_ollama(prompt)
        
        if response and len(response) < 200:
            return response
    except Exception:
        pass
    
    # Fallback to templates
    return _TEMPLATES.get(intent, _TEMPLATES["unknown"])
