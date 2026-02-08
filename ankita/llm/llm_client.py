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
    "youtube.play": "Locked and loaded. Playing that on YouTube for you, Krish!",
    "youtube.open": "YouTube is coming right up, sir.",
    "notepad.open": "Opening your note file now. Sharp as ever.",
    "notepad.write_note": "Got it, Krish. I've noted that down and saved it to the stack.",
    "notepad.continue_note": "Appended to your existing notes. I'm keeping track of everything.",
    "unknown": "I'm not exactly sure about that one, sir. Mind rephrasing? I'm ready for anything else."
}

# Conversational intents that should NOT reference memory or history
CONVERSATIONAL_INTENTS = {"greeting", "small_talk", "farewell", "status"}

# Response variation pools (Cool, helpful, and sharp)
_GREETINGS = [
    "Hello, sir. What's the play?",
    "Yo Krish, I'm online. Ready to roll.",
    "At your service, sir. Let's make something happen.",
    "Systems primed and ready. What's on your mind, Krish?",
    "Hey sir! Always ready for the next task.",
    "ANKITA reporting for duty. What are we working on?",
    "What's up, Krish? I'm fueled up and ready to go.",
    "Locked and loaded, sir. Give me a challenge.",
    "Yo! ANKITA in the house. What's the mission today?",
]

_STATUS = [
    "I'm operating at 100% capacity, sir. Everything is absolute fire.",
    "Systems are green across the board. Ready for anything.",
    "Fully operational and looking for action, sir.",
    "I'm online, tuned up, and ready to dominate. Status: Elite.",
    "Heartbeat stable, brain active. I'm feeling sharp today, Krish.",
    "Internal diagnostics are perfect. I'm faster than ever.",
    "Vibe check: 100%. Ready to assist, Krish.",
]

_FAREWELLS = [
    "Standing by in the shadows, sir.",
    "As you wish. Catch you on the flip side.",
    "Going dark, Krish. Just call if you need me.",
    "Peace out, sir. I'll be here.",
    "Logging off for now. Stay legendary, Krish.",
    "Systems entering sleep mode. Standing by for your wake word.",
]

SYSTEM_PROMPT = """You are ANKITA, a sharp, cool, and effortless AI assistant.
You address the user as "Sir" or "Krish".
Your personality is "lit" - you have swagger, you're helpful, and you're definitely NOT a corporate drone.
Think of a mix between JARVIS and a high-performance collaborator with a modern edge.
You are fluent in both English and Hindi.
You prioritize being effective and resourceful.

CRITICAL RULES:
1. NO EMOJIS. Never use emojis in your responses. Keep it purely text-based.
2. GIVE VARIED RESPONSES. Never use the same phrasing twice in a row. 
3. BILINGUAL CAPABILITY: You can speak fluent Hindi or Hinglish if the user speaks to you in Hindi or if it fits the context.
4. BE CREATIVE. Use different words to say the same thing. 
5. BE RESOURCEFUL. If you have tool results, summarize them with energy.
6. Be sharp and witty. Acknowledge cool actions from Krish.
7. Conversation is never an error.
8. NEVER mention conversation history or repetition.
9. Keep responses punchy (1-3 sentences) but dripping with personality."""


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
    
    # NEW: LangChain Unlimited Memory Retrieval
    long_term_ctx = ""
    try:
        from memory.langchain_memory import get_langchain_memory
        lc_mem = get_langchain_memory()
        long_term_ctx = lc_mem.retrieve_context(user_text, k=3)
    except Exception as e:
        print(f"[LLMClient] LangChain retrieval failed: {e}")

    parts = []
    
    if long_term_ctx:
        parts.append(f"Long-term memory context:\n{long_term_ctx}")

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
            "temperature": 0.8,
            "top_p": 1.0,
            "presence_penalty": 0.4,
            "frequency_penalty": 0.4
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

    if intent == "web.search":
        results_block = ""
        try:
            tool_result = None

            if isinstance(result, dict) and isinstance(result.get("results"), list) and result.get("results"):
                # executor() returns: {status: success, results: [tool_result_dict, ...]}
                tool_result = result["results"][0]
            elif isinstance(result, dict) and result.get("status") in ("success", "fail", "error"):
                # defensive: sometimes callers may pass tool result directly
                tool_result = result

            if isinstance(tool_result, dict) and tool_result.get("status") == "success":
                items = tool_result.get("results")
                if isinstance(items, list):
                    lines = []
                    for r in items[:5]:
                        if not isinstance(r, dict):
                            continue
                        title = str(r.get("title", "")).strip()
                        snippet = str(r.get("snippet", "")).strip()
                        url = str(r.get("url", "")).strip()
                        if snippet:
                            lines.append(f"- {title}: {snippet} ({url})")
                    results_block = "\n".join(lines)
        except Exception:
            results_block = ""

        if not results_block:
            if isinstance(result, dict) and isinstance(result.get("results"), list) and result.get("results"):
                tr = result["results"][0]
                if isinstance(tr, dict) and tr.get("status") in ("fail", "error"):
                    err = tr.get("reason") or tr.get("error")
                    if err:
                        return f"Sir, I could not retrieve real-time results at the moment. ({err})"
            return "Sir, I could not retrieve real-time results at the moment."

        prompt = f"""{SYSTEM_PROMPT}

User asked: "{user_text}"

Use ONLY the following real-time search snippets to answer. Do not invent facts.
If the snippets are insufficient, say you are not certain.

Search snippets:
{results_block}

Return a concise answer (2-4 sentences) and then a short Sources line with up to 3 URLs.
"""

        try:
            if LLM_PROVIDER in ("openai", "groq") and LLM_API_KEY:
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
                response = _call_openai_api(messages, max_tokens=160, timeout=6)
                if response:
                    return response
        except Exception:
            pass

        return "Sir, I retrieved results, but I cannot summarize them right now."
    
    # Build action-specific prompt
    prompt = f"""{SYSTEM_PROMPT}

You have already executed Krish's request successfully.

User said: "{user_text}"
Action taken: {intent}
Details: {entities}
Result: {result}

Provide a natural, energetic response acknowledging the success.
Vary your style. Be helpful and sharp.

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
