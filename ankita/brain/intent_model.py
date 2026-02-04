"""
Intent Classifier - Layer 1: Rule-based (fast, deterministic).

This is the PRIMARY classifier:
1. Rules (keywords) - instant, safe ← THIS
2. Gemma (local) - fast, private
3. Cloud LLM (Groq) - smart but slower

Rules handle obvious, explicit commands.
Falls back to "unknown" for anything fuzzy.
"""

import json
import os
import re
from brain.entity_extractor import extract
from brain.text_normalizer import normalize_text

_INTENTS_PATH = os.path.join(os.path.dirname(__file__), "intents.json")
with open(_INTENTS_PATH, "r", encoding="utf-8") as f:
    _INTENTS = json.load(f)

_INTENT_NAMES = list(_INTENTS.keys())


def classify_rules(text: str) -> str:
    """
    Rule-based intent classification using keywords.
    Returns intent string or "unknown".
    """
    t = normalize_text(text)

    # --- System controls (Tier-1) ---
    if "bluetooth" in t:
        if any(w in t for w in ["on", "enable", "start"]):
            return "system.bluetooth.on"
        if any(w in t for w in ["off", "disable", "stop"]):
            return "system.bluetooth.off"
        return "system.bluetooth.status"

    if "gesture" in t or "head" in t or "wave" in t:
        if any(w in t for w in ["window", "switch", "control"]):
            return "system.window_switch.gesture"
        return "system.gesture_mode"

    # --- App control (Tier-1) ---
    if any(w in t for w in ["switch to ", "switch ", "focus ", "go to "]):
        return "system.app.focus"

    if any(w in t for w in ["open ", "launch ", "start "]):
        return "system.app.open"

    if any(w in t for w in ["close this", "close current", "close active"]):
        return "system.app.close_active"

    if any(w in t for w in ["force close", "force quit", "kill ", "end task"]):
        return "system.app.force_close"

    if any(w in t for w in ["close ", "quit "]):
        return "system.app.close"

    if "brightness" in t or "brigthness" in t:
        # If user gave a number (e.g. "brightness 80") treat as set.
        # If user said full/max, treat as set (entity extractor will map to 100).
        if re.search(r"\b\d{1,3}\b", t) or any(w in t for w in ["set", "to", "full", "max", "maximum"]):
            return "system.brightness.set"
        if any(w in t for w in ["up", "increase", "higher", "brighten"]):
            return "system.brightness.up"
        if any(w in t for w in ["down", "decrease", "lower", "dim"]):
            return "system.brightness.down"
        return "system.brightness.status"

    if "volume" in t or "sound" in t:
        if any(w in t for w in ["mute", "silence"]):
            return "system.volume.mute"
        if any(w in t for w in ["unmute"]):
            return "system.volume.unmute"
        if any(w in t for w in ["set", "to"]):
            return "system.volume.set"
        if any(w in t for w in ["up", "increase", "louder", "raise"]):
            return "system.volume.up"
        if any(w in t for w in ["down", "decrease", "lower", "quieter"]):
            return "system.volume.down"
        return "system.volume.status"

    # --- Scheduler: add job ---
    # Detect scheduling language before tool intents so we don't execute immediately.
    has_relative = re.search(r"\b(?:in|after)\s+\d+\s*(?:seconds?|secs?|minutes?|mins?)\b", t) is not None
    has_absolute = re.search(r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", t) is not None
    has_action = any(w in t for w in ["write", "note", "save", "play", "open", "continue", "append"])

    if (has_relative or has_absolute) and has_action:
        return "scheduler.add_job"
    
    # --- Daily summary intents ---
    if any(w in t for w in ["what did i do", "what have i done", "what we have done", "what did we do", "summary", "summarize"]):
        if "yesterday" in t:
            return "summary.yesterday"
        if "today" in t:
            return "summary.today"

    # --- Common conversational phrases (avoid LLM misclassification) ---
    conversational = ["anything else", "what about", "and then", "what else", "anything more"]
    if any(phrase in t for phrase in conversational):
        return "unknown"

    # --- YouTube intents ---
    if "youtube" in t or re.search(r"\byt\b", t):
        if any(w in t for w in ["play", "song", "video", "music", "watch", "search"]):
            return "youtube.play"
        else:
            return "youtube.open"
    
    # --- Notepad intents ---
    if "notepad" in t or "note" in t:
        if any(w in t for w in ["continue", "add to", "append", "keep writing"]):
            return "notepad.continue_note"
        elif any(w in t for w in ["write", "make", "create", "jot", "take"]):
            return "notepad.write_note"
        else:
            return "notepad.open"
    
    # --- Standalone play ---
    if any(w in t for w in ["play", "song", "video", "music"]):
        return "youtube.play"

    return "unknown"


def classify(text: str) -> dict:
    """
    Classify user text using rules.
    Returns dict with 'intent' and 'entities'.
    """
    intent = classify_rules(text)
    entities = extract(intent, text)
    
    return {
        "intent": intent,
        "entities": entities
    }
