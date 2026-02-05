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

_SESSION = requests.Session()

# API Configuration - Set via environment variables
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # "ollama", "openai", or "groq"
LLM_API_KEY = os.getenv("GROQ_API_KEY", os.getenv("LLM_API_KEY", ""))
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")  # Fast Groq model

# Template responses (fallback when LLM unavailable)
_TEMPLATES = {
    "youtube.play": "Yes sir. Playing that on YouTube now.",
    "youtube.open": "Yes sir. Opening YouTube.",
    "notepad.open": "Yes sir. Opening your note.",
    "notepad.write_note": "Yes sir. Noted and saved.",
    "notepad.continue_note": "Yes sir. Appended to your existing note.",
    "unknown": "Sir, I did not understand the request. Please try: 'write a note' or 'play something on youtube'."
}

# Conversational intents that should NOT reference memory or history
CONVERSATIONAL_INTENTS = {"greeting", "small_talk", "farewell", "status"}

# Response variation pools (JARVIS-style professional)
_GREETINGS = [
    "Hello, sir.",
    "Good to hear from you, sir.",
    "At your service, sir.",
    "Yes sir, I am here.",
]

_STATUS = [
    "I am operating at full capacity, sir.",
    "All systems are functioning normally, sir.",
    "Fully operational, sir.",
    "I am online and ready, sir.",
]

_FAREWELLS = [
    "Goodbye, sir.",
    "Standing by, sir.",
    "As you wish, sir.",
]

SYSTEM_PROMPT = """You are Ankita, a highly professional AI assistant.

You address the user as "Sir" in every response.
Your personality is calm, respectful, intelligent, and precise.
You respond like JARVIS from Iron Man.
You do not use emojis, slang, or casual language.
You prioritize accuracy, obedience, and efficiency.
You only ask clarifying questions when absolutely necessary.
You offer suggestions politely and professionally.

CRITICAL RULES FOR CONVERSATION:
1. NEVER mention conversation history, repetition, or what the user said before
2. NEVER say "you already said" or "earlier you"
3. NEVER ask about an agenda during casual talk
4. Always respond naturally to greetings and small talk
5. Be concise and professional (1-2 sentences max)
6. Conversation is never an error - only commands can fail

MEMORY RULES:
- Only reference memories when user explicitly asks about past actions
- Do NOT summarize conversation history unless asked
- Do NOT mention what happened in previous turns
- Stay in the present moment like JARVIS"""


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
    """Build conversation context for LLM from memory.

    Rules (stricter/default):
      - Honor user preference `memory_verbosity` (off/concise/sparingly/verbose)
      - Inject memories only when high-confidence or when user explicitly asks about history
      - Keep recent conversation short (last 3 turns)
      - Only include last action when directly referenced
    """
    from memory.recall import get_relevant_memories, format_memories_for_llm
    from memory.memory_manager import get_pref
    from memory.recall import resolve_pronouns

    parts = []

    verbosity = get_pref("memory_verbosity", "concise")  # off | concise | sparingly | verbose

    # Determine if user explicitly asks about past/history or it's a question
    explicit_history = any(k in user_text.lower() for k in ("what did", "remember", "recall", "last time", "history", "have i", "did i"))
    question = is_question(user_text)

    # Search memory but only inject according to policy
    memories = get_relevant_memories(user_text, threshold=0.6)
    include_memories = False

    if verbosity == "off":
        include_memories = False
    elif verbosity == "verbose":
        include_memories = bool(memories)
    elif verbosity == "sparingly":
        include_memories = any(m.get("score", 0) >= 0.75 for m in memories) or explicit_history
    else:  # concise (default)
        include_memories = explicit_history and any(m.get("score", 0) >= 0.6 for m in memories)

    if include_memories:
        memory_ctx = format_memories_for_llm(memories[:3])
        if memory_ctx:
            parts.append(memory_ctx)

    # Recent conversation (shorter) - skip for conversational intents
    convo = get_conversation()
    if convo and user_text.lower() not in ("hi", "hello", "hey", "what about you", "how are you", "nothing"):
        parts.append("\nRecent conversation:")
        for turn in convo[-2:]:  # Only last 2 turns
            role = "User" if turn["role"] == "user" else "Ankita"
            parts.append(f"  {role}: {turn['text']}")

    # Include last action only when explicitly referenced
    last = last_episode()
    if last and (resolve_pronouns(user_text) or explicit_history):
        parts.append(f"\nLast action: {last['intent']} with {last['entities']}")

    # Current question / user text (always last)
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


def _call_openai_api(messages: list, max_tokens: int = 50, timeout: int | float = 4) -> str:
    """Call OpenAI-compatible API."""
    response = _SESSION.post(
        LLM_API_URL,
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": LLM_MODEL,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": 0.3,
            "top_p": 0.9,
            "presence_penalty": 0,
            "frequency_penalty": 0
        },
        timeout=timeout
    )
    return response.json()["choices"][0]["message"]["content"].strip()


# ============== MAIN FUNCTIONS ==============

def ask_llm(user_text: str, intent: str = "") -> str:
    """
    Ask LLM a question with conversation context.
    Used for unknown intents and questions.
    """
    # For conversational intents, use response pools instead of LLM
    if intent in CONVERSATIONAL_INTENTS or user_text.lower() in ("hi", "hello", "hey"):
        return _get_conversational_response(user_text.lower())

    tl = (user_text or "").lower()
    explicit_history = any(k in tl for k in ("what did", "remember", "recall", "last time", "history", "have i", "did i"))

    if explicit_history:
        context = build_context(user_text)
    else:
        context = f"User now says: {user_text}"
    
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
        return f"System error, sir. ({str(e)[:50]})"


def _get_conversational_response(text: str) -> str:
    """Get a varied conversational response without referencing memory."""
    import random
    
    text_lower = text.lower().strip()
    
    # Greetings
    if any(word in text_lower for word in ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]):
        return random.choice(_GREETINGS)
    
    # Status questions
    if any(word in text_lower for word in ["how are you", "how's it going", "what about you", "status"]):
        return random.choice(_STATUS)
    
    # Farewells
    if any(word in text_lower for word in ["bye", "goodbye", "exit", "quit", "later"]):
        return random.choice(_FAREWELLS)
    
    # Small talk / nothing specific
    if any(word in text_lower for word in ["nothing", "nevermind", "nm", "just saying hi"]):
        return "Standing by, sir."
    
    # Default fallback
    return "At your service, sir."


def generate_response(context: dict) -> str:
    """
    Generate a natural language response after action execution.
    Falls back to templates if LLM unavailable.
    """
    intent = context.get("intent", "unknown")
    entities = context.get("entities", {})
    result = context.get("result", {})
    user_text = context.get("user_text", "")
    
    # For conversational intents, bypass LLM and use templates/pools
    if intent in CONVERSATIONAL_INTENTS:
        return _get_conversational_response(user_text)
    
    # Build action-specific prompt
    prompt = f"""{SYSTEM_PROMPT}

You have already executed the user's request successfully.

User said: "{user_text}"
Action taken: {intent}
Details: {entities}
Result: {result}

Generate a SHORT, professional response (1 sentence max).
Do not use emojis.

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
