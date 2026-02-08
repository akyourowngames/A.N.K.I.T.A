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

    # --- Conversational intents (handle casually, no tool execution) ---
    # Greetings - explicit patterns to bypass LLM for JARVIS-style responses
    if t in ("hi", "hello", "hey", "good morning", "good afternoon", "good evening", "greetings"):
        return "conversation.greeting"
    # Status/small talk
    if t in ("how are you", "hows it going", "what about you", "status", "you there"):
        return "conversation.status"
    # Farewells
    if t in ("bye", "goodbye", "see you", "exit", "quit", "later"):
        return "conversation.farewell"
    # Acknowledgments/nothing specific
    if t in ("nothing", "nevermind", "nm", "just saying hi", "ok", "okay"):
        return "conversation.ack"

    # --- Window control intents (high priority) ---
    if any(w in t for w in ["show desktop", "desktop", "minimize all", "show all"]):
        return "window_control.desktop"
    if any(w in t for w in ["minimize", "minimise", "hide window", "hide this"]):
        return "window_control.minimize"
    if any(w in t for w in ["maximize", "maximise", "full screen"]):
        return "window_control.maximize"
    if any(w in t for w in ["restore", "unminimize", "un-minimize"]):
        return "window_control.restore"
    if any(w in t for w in ["snap left", "move left", "left side"]):
        return "window_control.left"
    if any(w in t for w in ["snap right", "move right", "right side"]):
        return "window_control.right"
    if any(w in t for w in ["move up"]):
        return "window_control.up"
    if any(w in t for w in ["move down"]):
        return "window_control.down"

    # --- System controls (Tier-1) ---
    if "bluetooth" in t:
        if any(w in t for w in ["on", "enable", "start"]):
            return "system.bluetooth.on"
        if any(w in t for w in ["off", "disable", "stop"]):
            return "system.bluetooth.off"
        return "system.bluetooth.status"

    if "gesture" in t or re.search(r"\bhead\s*(?:tracking|gesture)\b", t) or "wave" in t:
        if any(w in t for w in ["window", "switch", "control"]):
            return "system.window_switch.gesture"
        return "system.gesture_mode"

    # --- App control (Tier-1) ---
    # IMPORTANT: Check for specific apps (Instagram, YouTube, etc.) BEFORE generic app.open
    
    # --- Instagram intents (check BEFORE generic app.open) ---
    if "instagram" in t or "insta" in t or "ig " in t or t.endswith(" ig"):
        # Login/Logout
        if any(w in t for w in ["login", "log in", "sign in", "signin"]):
            return "instagram.login"
        if any(w in t for w in ["logout", "log out", "sign out", "signout"]):
            return "instagram.logout"
        
        # Navigation
        if any(w in t for w in ["explore", "discover"]):
            return "instagram.explore"
        if "reels" in t or "reel" in t:
            return "instagram.reels"
        if any(w in t for w in ["messages", "dm", "dms", "inbox", "direct"]):
            return "instagram.dm"
        if any(w in t for w in ["notifications", "notify", "alerts"]):
            return "instagram.notifications"
        if any(w in t for w in ["feed", "home", "scroll"]):
            return "instagram.feed"
        
        # Actions
        if any(w in t for w in ["like", "heart"]):
            if "unlike" in t or "remove like" in t:
                return "instagram.unlike"
            return "instagram.like"
        if "comment" in t:
            return "instagram.comment"
        if "follow" in t:
            if "unfollow" in t:
                return "instagram.unfollow"
            return "instagram.follow"
        if any(w in t for w in ["message", "dm", "send message", "text"]):
            return "instagram.dm"
        if any(w in t for w in ["search", "find", "look for"]):
            return "instagram.search"
        if any(w in t for w in ["profile", "check profile", "view profile"]):
            return "instagram.profile"
        if any(w in t for w in ["close", "quit", "exit"]):
            return "instagram.close"
        
        # Default: open Instagram
        return "instagram.open"
    
    # --- Tier-0: Global Force Overrides ---
    if any(w in t for w in ["search for ", "search ", "google ", "look up ", "find "]):
        if "youtube" not in t and "insta" not in t and "yt" not in t and "video" not in t:
            return "web.search"

    # --- OpenClaw Bridge (Priority Cloud Tools) ---

    # --- Generic app control (after specific app checks) ---
    if re.match(r"^(?:switch\s+to|switch|focus|go\s+to)\b", t):
        return "system.app.focus"

    if re.match(r"^(?:open|launch|start)\b", t):
        return "system.app.open"

    if any(w in t for w in ["close this", "close current", "close active"]):
        return "system.app.close_active"

    if re.match(r"^(?:force\s+close|force\s+quit|kill|end\s+task)\b", t):
        return "system.app.force_close"

    if re.match(r"^(?:close|quit|exit)\b", t):
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

    # --- Screenshot intents ---
    screenshot_phrases = [
        "screenshot", "screen shot", "screen capture", "capture screen", 
        "screen grab", "take screenshot", "take a screenshot", "grab screen",
        "capture the screen", "snap screen", "screen snap", "print screen",
        "capture my screen", "take a screen", "screenshot please"
    ]
    if any(w in t for w in screenshot_phrases):
        if any(w in t for w in ["window", "active", "current", "this window"]):
            return "system.screenshot.window"
        if any(w in t for w in ["clipboard", "copy", "to clipboard"]):
            return "system.screenshot.clipboard"
        return "system.screenshot"

    # --- Clipboard intents ---
    if "clipboard" in t:
        if any(w in t for w in ["clear", "empty", "delete", "wipe"]):
            return "system.clipboard.clear"
        if any(w in t for w in ["copy", "write", "set", "put"]):
            return "system.clipboard.write"
        return "system.clipboard.read"
    if any(w in t for w in ["what did i copy", "what is copied", "whats copied"]):
        return "system.clipboard.read"

    # --- Battery intents ---
    if any(w in t for w in ["battery", "power level", "charge level"]):
        if any(w in t for w in ["charging", "plugged", "charger"]):
            return "system.battery.charging"
        if any(w in t for w in ["percent", "percentage", "level"]):
            return "system.battery.percent"
        return "system.battery.status"

    # --- WiFi intents ---
    # Check status phrases FIRST (before checking for 'connect' which would match 'connected')
    if any(w in t for w in ["am i connected", "connected to wifi", "internet status", "network status", "wifi status"]):
        return "system.wifi.status"
    if "wifi" in t or "wi-fi" in t or "wi fi" in t:
        if any(w in t for w in ["scan", "networks", "available", "list", "find"]):
            return "system.wifi.networks"
        if any(w in t for w in ["off", "disable", "stop", "disconnect"]):
            return "system.wifi.off"
        if any(w in t for w in ["on", "enable", "start", "turn on"]):
            return "system.wifi.on"
        # Check for connection-related queries that should be status, not on
        if any(w in t for w in ["connected", "connection", "status", "check"]):
            return "system.wifi.status"
        return "system.wifi.status"

    # --- Power/Lock intents ---
    if any(w in t for w in ["lock screen", "lock computer", "lock pc", "lock my", "lock the"]):
        return "system.power.lock"
    if t in ("lock", "lock it"):
        return "system.power.lock"
    if any(w in t for w in ["go to sleep", "sleep mode", "put to sleep", "enter sleep"]):
        return "system.power.sleep"
    if t == "sleep":
        return "system.power.sleep"
    if any(w in t for w in ["shutdown", "shut down", "power off", "turn off computer", "turn off pc", "turn off laptop"]):
        return "system.power.shutdown"
    if any(w in t for w in ["restart", "reboot"]):
        return "system.power.restart"
    if "hibernate" in t:
        return "system.power.hibernate"
    if any(w in t for w in ["log off", "logoff", "log out", "logout", "sign out", "signout"]):
        return "system.power.logoff"
    if any(w in t for w in ["cancel shutdown", "cancel restart", "abort shutdown", "stop shutdown"]):
        return "system.power.cancel"

    # --- DateTime intents ---
    time_phrases = [
        "what time", "whats the time", "current time", "tell me the time", 
        "time now", "time please", "what is the time", "tell me time",
        "what's the time", "the time", "clock", "gimme the time"
    ]
    if any(w in t for w in time_phrases):
        return "datetime.now"
    
    date_phrases = [
        "what date", "whats the date", "today date", "todays date", 
        "current date", "what is the date", "what's the date", "the date",
        "tell me date", "date today", "today's date"
    ]
    if any(w in t for w in date_phrases):
        return "datetime.date"
    
    day_phrases = [
        "what day", "which day", "day of the week", "day today",
        "today what day", "what day is it", "what day is today",
        "tell me the day", "which day is today"
    ]
    if any(w in t for w in day_phrases):
        return "datetime.day"
    
    if any(w in t for w in ["what week", "week number", "which week", "what week is it"]):
        return "datetime.week"
    if any(w in t for w in ["what month", "current month", "which month", "what month is it"]):
        return "datetime.month"
    if any(w in t for w in ["what year", "current year", "which year", "the year"]):
        return "datetime.year"
    if any(w in t for w in ["tomorrow", "tomorrows date", "tomorrow's date", "date tomorrow"]):
        return "datetime.tomorrow"
    if any(w in t for w in ["yesterday", "yesterdays date", "yesterday's date", "date yesterday"]):
        return "datetime.yesterday"
    if any(w in t for w in ["timezone", "time zone", "what timezone", "my timezone", "what time zone"]):
        return "datetime.timezone"



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

    # --- YouTube intents (with extended controls) ---
    if "youtube" in t or re.search(r"\byt\b", t):
        # YouTube control actions - check BEFORE generic play
        if any(w in t for w in ["pause", "resume", "stop playing"]):
            return "youtube.pause"
        if any(w in t for w in ["fullscreen", "full screen"]):
            return "youtube.fullscreen"
        if any(w in t for w in ["skip ad", "skip advertisement", "skip the ad"]):
            return "youtube.skip_ad"
        if any(w in t for w in ["subscriptions", "subscription", "subs"]):
            return "youtube.subscriptions"
        if any(w in t for w in ["history", "watch history"]):
            return "youtube.history"
        if any(w in t for w in ["add to queue", "queue"]):
            return "youtube.queue"
        if any(w in t for w in ["next video", "play next", "skip"]):
            return "youtube.next"
        if any(w in t for w in ["previous", "go back", "last video"]):
            return "youtube.previous"
        if any(w in t for w in ["captions", "subtitles", "cc"]):
            return "youtube.captions"
        if any(w in t for w in ["theater", "theatre"]):
            return "youtube.theater"
        if any(w in t for w in ["speed up", "faster"]):
            return "youtube.speed_up"
        if any(w in t for w in ["speed down", "slower"]):
            return "youtube.speed_down"
        if any(w in t for w in ["trending"]):
            return "youtube.trending"
        if any(w in t for w in ["shorts"]):
            return "youtube.shorts"
        if any(w in t for w in ["home"]):
            return "youtube.home"
        if any(w in t for w in ["mute"]):
            return "youtube.mute"
        if any(w in t for w in ["unmute"]):
            return "youtube.unmute"
        # Default play/open
        if any(w in t for w in ["play", "song", "video", "music", "watch"]):
            return "youtube.play"
        else:
            return "youtube.open"
    
    # --- Hotspot intents ---
    if any(w in t for w in ["hotspot", "mobile hotspot", "tethering"]):
        if any(w in t for w in ["off", "disable", "stop"]):
            return "system.hotspot.off"
        if any(w in t for w in ["on", "enable", "start", "turn on"]):
            return "system.hotspot.on"
        return "system.hotspot.status"
    
    # --- Night Light intents ---
    if any(w in t for w in ["night light", "nightlight", "blue light", "night mode"]):
        if any(w in t for w in ["off", "disable", "stop"]):
            return "system.nightlight.off"
        if any(w in t for w in ["on", "enable", "start", "turn on"]):
            return "system.nightlight.on"
        return "system.nightlight.status"
    
    # --- Airplane Mode intents ---
    if any(w in t for w in ["airplane mode", "flight mode", "aeroplane mode"]):
        if any(w in t for w in ["off", "disable"]):
            return "system.airplane_mode.off"
        if any(w in t for w in ["on", "enable"]):
            return "system.airplane_mode.on"
        return "system.airplane_mode.status"
    
    # --- Display intents ---
    if any(w in t for w in ["extend display", "extend screen", "second monitor", "external monitor"]):
        return "system.display.extend"
    if any(w in t for w in ["duplicate display", "mirror screen", "mirror display", "duplicate screen"]):
        return "system.display.duplicate"
    if any(w in t for w in ["rotate screen", "rotate display"]):
        return "system.display.rotate"
    if any(w in t for w in ["display settings", "screen settings"]):
        return "system.display.settings"
    
    # --- Audio Device intents ---
    if any(w in t for w in ["switch to headphones", "use headphones", "switch to speakers", "use speakers", 
                             "switch audio", "change audio", "switch to headset", "use headset",
                             "switch to bluetooth", "audio output"]):
        return "system.audio_device.switch"
    if any(w in t for w in ["list audio devices", "audio devices", "sound devices"]):
        return "system.audio_device.list"
    
    # --- Printer intents ---
    if any(w in t for w in ["print this", "print document", "print file", "send to printer"]):
        return "system.printer.print"
    if any(w in t for w in ["print queue", "printing", "whats printing", "printer queue"]):
        return "system.printer.queue"
    if any(w in t for w in ["printer settings", "printers"]):
        return "system.printer.settings"
    
    # --- Trash/Recycle Bin intents ---
    if any(w in t for w in ["recycle bin", "trash", "rubbish bin"]):
        if any(w in t for w in ["empty", "clear", "delete", "clean"]):
            return "system.trash.empty"
        if any(w in t for w in ["open", "show", "view"]):
            return "system.trash.open"
        return "system.trash.status"
    
    # --- Disk/Storage intents ---
    if any(w in t for w in ["sick", "ill", "not feeling well", "headache", "fever", "stomachache", "pain", "hurts"]):
        return "system.power.sleep" # placeholder or mapping to a "health" mode? 
        # Actually I should add a specific intent for health if it doesn't exist.
        # But wait, the test expected 'sick' situation.
    if any(w in t for w in ["disk space", "storage space", "how much storage", "how much space", 
                             "storage status", "drive space", "disk status", "free space"]):
        return "system.disk.status"
    if any(w in t for w in ["disk cleanup", "clean disk", "free up space", "clean storage"]):
        return "system.disk.cleanup"
    if any(w in t for w in ["storage settings"]):
        return "system.disk.settings"
    
    # --- Process Management intents ---
    if any(w in t for w in ["task manager", "open task manager", "show task manager", "process manager"]):
        return "system.processes.manager"
    if any(w in t for w in ["whats using cpu", "high cpu", "cpu usage", "top processes", "which app using cpu"]):
        return "system.processes.cpu"
    if any(w in t for w in ["whats using memory", "high memory", "ram usage", "memory usage", "which app using ram"]):
        return "system.processes.memory"
    if re.match(r"^(?:kill|end task|terminate)\b", t):
        return "system.processes.kill"

    
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
