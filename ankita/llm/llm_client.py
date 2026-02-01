"""
LLM Client - Ankita's voice (mouth, not hands).

The LLM generates natural language responses ONLY.
It does NOT control tools or make decisions.

Uses Ollama/Gemma with fallback to templates.
"""

import requests

# Template responses (fallback when LLM unavailable)
_TEMPLATES = {
    "youtube.play": "Playing that on YouTube for you 🎵",
    "youtube.open": "Opening YouTube.",
    "notepad.open": "Opening your note.",
    "notepad.write_note": "I've written that down and saved it for you 📝",
    "notepad.continue_note": "Added that to your existing note.",
    "unknown": "I'm not sure what you meant. Try: 'write a note' or 'play something on youtube'."
}


def _build_prompt(context: dict) -> str:
    """Build LLM prompt from execution context."""
    intent = context.get("intent", "unknown")
    entities = context.get("entities", {})
    result = context.get("result", {})
    user_text = context.get("user_text", "")
    
    return f"""You are Ankita, a helpful and friendly AI assistant.
You have already executed the user's request successfully.

User said: "{user_text}"
Action taken: {intent}
Details: {entities}
Result: {result}

Generate a SHORT, natural, friendly response (1 sentence max).
Be warm but concise. Use an emoji if appropriate.
Do NOT mention internal tools, code, or technical details.
Do NOT ask follow-up questions.

Response:"""


def generate_response(context: dict) -> str:
    """
    Generate a natural language response using LLM.
    Falls back to templates if LLM unavailable.
    
    Args:
        context: dict with 'intent', 'entities', 'result', 'user_text'
    
    Returns:
        Natural language response string
    """
    intent = context.get("intent", "unknown")
    
    # Try LLM first
    try:
        prompt = _build_prompt(context)
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma2:2b",
                "prompt": prompt,
                "stream": False
            },
            timeout=5
        )
        
        llm_response = response.json().get("response", "").strip()
        
        # Validate response (not empty, not too long)
        if llm_response and len(llm_response) < 200:
            return llm_response
    except Exception:
        pass  # Silent fallback to templates
    
    # Fallback to templates
    return _TEMPLATES.get(intent, _TEMPLATES["unknown"])
