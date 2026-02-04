"""
Intent Registry - Whitelist of allowed intents and their entities.

LLM can ONLY return intents from this list.
This prevents hallucination and unauthorized actions.
"""

# Allowed intents and their valid entity keys
ALLOWED_INTENTS = {
    # YouTube
    "youtube.open": [],
    "youtube.play": ["query"],
    
    # Notepad
    "notepad.open": [],
    "notepad.write_note": ["content"],
    "notepad.continue_note": ["content"],

    # Summaries (memory-only)
    "summary.today": [],
    "summary.yesterday": [],

    # Scheduler (safe: writes into jobs.json, does not directly run tools)
    "scheduler.add_job": ["text", "type", "after_seconds", "time"],

    # System controls (Tier-1)
    "system.volume.up": ["action", "step"],
    "system.volume.down": ["action", "step"],
    "system.volume.mute": ["action"],
    "system.volume.unmute": ["action"],
    "system.volume.set": ["action", "value"],
    "system.volume.status": ["action"],

    "system.brightness.up": ["action", "step"],
    "system.brightness.down": ["action", "step"],
    "system.brightness.set": ["action", "value"],
    "system.brightness.status": ["action"],

    "system.bluetooth.on": ["action"],
    "system.bluetooth.off": ["action"],
    "system.bluetooth.status": ["action"],
    "system.window_switch": ["query"],
    "system.window_switch.gesture": ["mode"],
    "system.gesture_mode": ["mode"],

    "system.app.open": ["action", "app"],
    "system.app.close": ["action", "app"],
    "system.app.force_close": ["action", "app", "force"],
    "system.app.close_active": ["action"],
    "system.app.focus": ["action", "app"],
}


def is_valid_intent(intent: str) -> bool:
    """Check if intent is in the whitelist."""
    return intent in ALLOWED_INTENTS


def get_allowed_entities(intent: str) -> list:
    """Get allowed entity keys for an intent."""
    return ALLOWED_INTENTS.get(intent, [])


def validate_intent_result(intent: str, entities: dict) -> dict:
    """
    Validate and clean an intent result.
    Returns cleaned result or unknown if invalid.
    """
    if intent not in ALLOWED_INTENTS:
        return {"intent": "unknown", "entities": {}}
    
    # Filter to only allowed entities
    allowed = ALLOWED_INTENTS[intent]
    clean_entities = {
        k: v for k, v in entities.items()
        if k in allowed
    }
    
    return {
        "intent": intent,
        "entities": clean_entities
    }
