"""
LLM Intent Fallback - When rules fail, LLM classifies.

SAFETY:
- LLM outputs structured JSON only
- Intent must be in whitelist
- Entities are validated and filtered
- LLM suggests → Ankita decides
"""

import json
import os
import requests
from brain.intent_registry import ALLOWED_INTENTS, validate_intent_result

# API config (same as llm_client.py)
LLM_API_KEY = os.getenv("GROQ_API_KEY", os.getenv("LLM_API_KEY", ""))
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")

# Build allowed intents string for prompt
INTENTS_LIST = ", ".join(ALLOWED_INTENTS.keys())

SYSTEM_PROMPT = f"""You are an intent classification engine for an AI assistant.
Your job is to understand what the user wants and return ONLY valid JSON.

ALLOWED INTENTS:
{INTENTS_LIST}

ENTITY TYPES:
- youtube.play requires: {{"query": "search term"}}
- notepad.write_note requires: {{"content": "text to write"}}
- notepad.continue_note requires: {{"content": "text to append"}}
- youtube.open and notepad.open require no entities

RULES:
1. Return ONLY valid JSON, no explanation
2. If the intent is unclear, return {{"intent": "unknown", "entities": {{}}}}
3. Extract the relevant content/query from the user's message

FORMAT:
{{"intent": "<intent>", "entities": {{...}}}}"""


def _call_groq(messages: list) -> str:
    """Call Groq API for classification."""
    response = requests.post(
        LLM_API_URL,
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": LLM_MODEL,
            "messages": messages,
            "max_tokens": 100,
            "temperature": 0.1  # Low temperature for consistent classification
        },
        timeout=10
    )
    return response.json()["choices"][0]["message"]["content"].strip()


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response (handles markdown code blocks)."""
    # Remove markdown code blocks if present
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    
    # Try to parse JSON
    return json.loads(text)


def llm_classify(text: str) -> dict:
    """
    Use LLM to classify intent when rules fail.
    Returns validated intent result.
    """
    if not LLM_API_KEY:
        return {"intent": "unknown", "entities": {}}
    
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Classify this: {text}"}
        ]
        
        raw = _call_groq(messages)
        data = _extract_json(raw)
        
        intent = data.get("intent", "unknown")
        entities = data.get("entities", {})
        
        # Validate against whitelist
        result = validate_intent_result(intent, entities)
        
        if result["intent"] != "unknown":
            print(f"[LLM Fallback] Classified as: {result['intent']}")
        
        return result
        
    except Exception as e:
        print(f"[LLM Fallback] Error: {e}")
        return {"intent": "unknown", "entities": {}}
