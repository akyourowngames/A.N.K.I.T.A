"""
Gemma Intent Classifier - LOCAL, fast, offline-friendly.

This is Layer 2 in the classification pipeline:
1. Rules (keywords) - instant
2. Gemma (local) - fast, private ← THIS
3. Cloud LLM (Groq) - smart but slower

Gemma handles:
- Intent classification
- Entity extraction hints
- Fuzzy command understanding

Gemma does NOT:
- Generate long answers
- Chat
- Plan steps
- Call tools
"""

import json
import os
import requests
from brain.intent_registry import ALLOWED_INTENTS, validate_intent_result
from brain.entity_extractor import extract

# Ollama endpoint (local Gemma)
OLLAMA_URL = "http://localhost:11434/api/generate"
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "gemma2:2b")
GEMMA_TIMEOUT = 3  # Fast timeout

# Build intents list for prompt
INTENTS_LIST = ", ".join(ALLOWED_INTENTS.keys())

CLASSIFICATION_PROMPT = f"""You are an intent classifier for an AI assistant.
Classify the user's message into ONE of these intents: {INTENTS_LIST}

Rules:
- Return ONLY the intent name, nothing else
- If unsure, return "unknown"

User: {{text}}
Intent:"""


def _is_ollama_available() -> bool:
    """Check if Ollama is running."""
    try:
        requests.get("http://localhost:11434/api/tags", timeout=1)
        return True
    except:
        return False


def gemma_classify(text: str) -> dict:
    """
    Use local Gemma to classify intent.
    Returns validated intent result.
    """
    try:
        prompt = CLASSIFICATION_PROMPT.format(text=text)
        
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": GEMMA_MODEL,
                "prompt": prompt,
                "stream": False
            },
            timeout=GEMMA_TIMEOUT
        )
        
        result = response.json().get("response", "").strip().lower()
        
        # Find matching intent
        intent = "unknown"
        for allowed_intent in ALLOWED_INTENTS.keys():
            if allowed_intent in result:
                intent = allowed_intent
                break
        
        if intent == "unknown":
            return {"intent": "unknown", "entities": {}}
        
        # Extract entities
        entities = extract(intent, text)
        
        # Validate against whitelist
        validated = validate_intent_result(intent, entities)
        
        if validated["intent"] != "unknown":
            print(f"[Gemma] Classified as: {validated['intent']}")
        
        return validated
        
    except Exception as e:
        # Silent fail - next layer will handle it
        return {"intent": "unknown", "entities": {}}


def is_gemma_available() -> bool:
    """Check if Gemma/Ollama is available for classification."""
    return _is_ollama_available()
