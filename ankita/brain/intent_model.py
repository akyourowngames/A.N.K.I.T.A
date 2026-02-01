import json
import os
import requests
from brain.entity_extractor import extract

_INTENTS_PATH = os.path.join(os.path.dirname(__file__), "intents.json")
with open(_INTENTS_PATH, "r", encoding="utf-8") as f:
    _INTENTS = json.load(f)

_INTENT_NAMES = list(_INTENTS.keys())

def _build_prompt(text):
    intents_list = ", ".join(_INTENT_NAMES)
    return (
        f"You are an intent classifier. "
        f"Choose exactly one intent from this list: {intents_list}. "
        f"Return ONLY the intent string, nothing else.\n\n"
        f"User: {text}\nIntent:"
    )

def _extract_intent(response_text, user_text):
    # Check for exact intent match in LLM response
    for intent in _INTENT_NAMES:
        if intent in response_text:
            return intent
    
    # Fallback: keyword matching from user text
    user_lower = user_text.lower()
    
    # Check for continue/append intent first (more specific)
    if any(word in user_lower for word in ["continue", "add to", "keep writing", "append"]):
        return "notepad.continue_note"
    
    if any(word in user_lower for word in ["note", "notepad", "write", "jot"]):
        return "notepad.write_note"
    if any(word in user_lower for word in ["youtube", "video", "play", "watch"]):
        return "youtube.play"
    
    return "unknown"

def classify(text):
    prompt = _build_prompt(text)
    result = ""
    
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma2:2b",
                "prompt": prompt,
                "stream": False
            },
            timeout=10
        )
        result = response.json().get("response", "")
    except Exception:
        # Silent fallback - keyword matching will handle it
        pass
    
    intent = _extract_intent(result, text)
    entities = extract(intent, text)
    
    return {
        "intent": intent,
        "entities": entities
    }
