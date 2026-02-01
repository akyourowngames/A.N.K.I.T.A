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
    
    # Fallback: action-level keyword matching (verb + object)
    t = user_text.lower()
    
    # --- YouTube intents ---
    if "youtube" in t or "yt" in t:
        # Action verbs that imply playing
        if any(w in t for w in ["play", "song", "video", "music", "watch", "search"]):
            return "youtube.play"
        else:
            # Just "open youtube" without action
            return "youtube.open"
    
    # --- Notepad intents ---
    if "notepad" in t or "note" in t:
        # Continue/append is most specific
        if any(w in t for w in ["continue", "add to", "append", "keep writing"]):
            return "notepad.continue_note"
        # Write/create action
        elif any(w in t for w in ["write", "make", "create", "jot", "take"]):
            return "notepad.write_note"
        else:
            # Just "open notepad" without action
            return "notepad.open"
    
    # --- Standalone play (no youtube mentioned) ---
    if any(w in t for w in ["play", "song", "video", "music"]):
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
            timeout=3  # Fast timeout - fallback to keywords if Ollama is slow/down
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
