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

    "web.search": ["query", "max_results"],

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

    # Window control (safe: only OS window hotkeys)
    "window_control.maximize": ["action"],
    "window_control.minimize": ["action"],
    "window_control.restore": ["action"],
    "window_control.desktop": ["action"],
    "window_control.left": ["action"],
    "window_control.right": ["action"],
    "window_control.up": ["action"],
    "window_control.down": ["action"],

    # Notepad tool-level intents
    "notepad.open_file": ["path"],
    "notepad.focus": [],
    "notepad.write": ["content"],
    "notepad.write_file": ["content", "filename", "mode", "open_after"],
    "notepad.save": [],

    # YouTube control intents
    "youtube.pause": ["action"],
    "youtube.fullscreen": ["action"],
    "youtube.skip_ad": ["action"],
    "youtube.subscriptions": ["action"],
    "youtube.history": ["action"],
    "youtube.queue": ["action"],
    "youtube.mute": ["action"],
    "youtube.unmute": ["action"],
    "youtube.next": ["action"],
    "youtube.previous": ["action"],
    "youtube.theater": ["action"],
    "youtube.captions": ["action"],
    "youtube.speed_up": ["action"],
    "youtube.speed_down": ["action"],
    "youtube.home": ["action"],
    "youtube.trending": ["action"],
    "youtube.shorts": ["action"],

    # Hotspot
    "system.hotspot.on": ["action"],
    "system.hotspot.off": ["action"],
    "system.hotspot.status": ["action"],

    # Night Light
    "system.nightlight.on": ["action"],
    "system.nightlight.off": ["action"],
    "system.nightlight.status": ["action"],

    # Airplane Mode
    "system.airplane_mode.on": ["action"],
    "system.airplane_mode.off": ["action"],
    "system.airplane_mode.status": ["action"],

    # Display
    "system.display.rotate": ["action", "direction"],
    "system.display.extend": ["action"],
    "system.display.duplicate": ["action"],
    "system.display.settings": ["action"],

    # Audio Device
    "system.audio_device.switch": ["action", "device"],
    "system.audio_device.list": ["action"],
    "system.audio_device.status": ["action"],

    # Printer
    "system.printer.print": ["action", "file_path"],
    "system.printer.queue": ["action"],
    "system.printer.settings": ["action"],

    # Trash/Recycle Bin
    "system.trash.status": ["action"],
    "system.trash.empty": ["action"],
    "system.trash.open": ["action"],

    # Disk/Storage
    "system.disk.status": ["action", "drive"],
    "system.disk.cleanup": ["action", "drive"],
    "system.disk.settings": ["action"],

    # Processes
    "system.processes.status": ["action"],
    "system.processes.cpu": ["action"],
    "system.processes.memory": ["action"],
    "system.processes.kill": ["action", "name"],
    "system.processes.find": ["action", "name"],
    "system.processes.manager": ["action"],
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
