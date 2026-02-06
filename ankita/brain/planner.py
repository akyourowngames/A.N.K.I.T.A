
import json
import os
from memory.memory_manager import last_note
from datetime import datetime, timedelta
from memory.memory_manager import episodes_in_range
from memory.sessionize import sessionize
from memory.timeline import summarize_sessions

# Always resolve tools_meta.json relative to this file's directory
_dir = os.path.dirname(os.path.abspath(__file__))
meta_path = os.path.join(_dir, "..", "registry", "tools_meta.json")
with open(meta_path, encoding="utf-8") as f:
    TOOL_META = json.load(f)

DEFAULT_FILENAME = "note.txt"

def plan(intent_result):
    intent = intent_result["intent"]
    entities = intent_result.get("entities", {})

    print(f"DEBUG: planner received intent={intent}, entities={entities}")

    if intent.startswith("system."):
        # Extract action from intent for system tools
        # e.g., system.screenshot -> action=full, system.screenshot.window -> action=window
        parts = intent.split(".")
        last_part = parts[-1]
        
        # Map intent suffixes to tool actions
        action_map = {
            # Screenshot - base intent maps to "full"
            "screenshot": "full",
            "window": "window",
            # "clipboard" can be either screenshot.clipboard or system.clipboard
            # Clipboard actions
            "read": "read",
            "write": "write",
            "clear": "clear",
            # Battery
            "battery": "status",
            "status": "status",
            "percent": "percent",
            "charging": "charging",
            # WiFi
            "wifi": "status",
            "on": "on",
            "off": "off",
            "networks": "networks",
            "disconnect": "disconnect",
            # Power
            "power": "lock",  # default power action
            "lock": "lock",
            "sleep": "sleep",
            "shutdown": "shutdown",
            "restart": "restart",
            "hibernate": "hibernate",
            "logoff": "logoff",
            "cancel": "cancel",
            # Clipboard base
            "clipboard": "read",  # default clipboard action is read
        }
        
        # Determine the action based on the last part of the intent
        if last_part in action_map:
            entities["action"] = action_map[last_part]
        elif "action" not in entities:
            entities["action"] = last_part
        
        return {
            "steps": [
                {
                    "tool": intent,
                    "args": entities,
                }
            ]
        }

    # Handle datetime.* intents  
    if intent.startswith("datetime."):
        # Extract action from intent (e.g., datetime.now -> action=now)
        parts = intent.split(".")
        action = parts[-1] if len(parts) > 1 else "now"
        entities["action"] = action
        return {
            "steps": [
                {
                    "tool": intent,
                    "args": entities,
                }
            ]
        }
    
    # Handle youtube.* intents
    if intent.startswith("youtube."):
        # Extract action from intent (e.g., youtube.pause -> action=pause)
        parts = intent.split(".")
        action = parts[-1] if len(parts) > 1 else "open"
        
        # Map intent actions to tool actions
        youtube_action_map = {
            "open": "open",
            "play": "play",
            "pause": "pause",
            "fullscreen": "fullscreen",
            "skip_ad": "skip_ad",
            "subscriptions": "subscriptions",
            "history": "history",
            "queue": "queue",
            "mute": "mute",
            "unmute": "unmute",
            "next": "next",
            "previous": "previous",
            "theater": "theater",
            "captions": "captions",
            "speed_up": "speed_up",
            "speed_down": "speed_down",
            "home": "home",
            "trending": "trending",
            "shorts": "shorts",
        }
        
        entities["action"] = youtube_action_map.get(action, action)
        
        # For play intent, keep the query
        # For control intents, use the control tool
        if action in ("open", "play"):
            return {
                "steps": [
                    {
                        "tool": intent,
                        "args": entities,
                    }
                ]
            }
        else:
            # Use the control tool for all other actions
            return {
                "steps": [
                    {
                        "tool": "youtube.control",
                        "args": entities,
                    }
                ]
            }

    # Handle instagram.* intents
    if intent.startswith("instagram."):
        # Extract action from intent (e.g., instagram.like -> action=like)
        parts = intent.split(".")
        action = parts[-1] if len(parts) > 1 else "open"
        
        # Map intent actions to tool actions
        action_map = {
            "open": "open",
            "login": "login",
            "logout": "logout",
            "feed": "feed",
            "scroll": "feed",
            "home": "navigate",
            "explore": "navigate",
            "reels": "navigate",
            "like": "like",
            "unlike": "unlike",
            "comment": "comment",
            "follow": "follow",
            "unfollow": "unfollow",
            "dm": "dm",
            "message": "dm",
            "search": "search",
            "profile": "profile",
            "notifications": "notifications",
            "close": "close",
        }
        
        entities["action"] = action_map.get(action, action)
        
        # Set destination for navigation actions
        if action in ("explore", "reels", "home"):
            entities["destination"] = action
        
        return {
            "steps": [
                {
                    "tool": intent,
                    "args": entities,
                }
            ]
        }

    if intent.startswith("window_control."):
        action = intent.split(".", 1)[1]
        return {
            "steps": [
                {
                    "tool": intent,
                    "args": {"action": action},
                }
            ]
        }

    if intent == "system.window_switch.gesture" or intent == "system.gesture_mode":
        return {
            "steps": [
                {
                    "tool": "system.window_switch.gesture",
                    "args": {"mode": entities.get("mode", "headless")},
                }
            ]
        }

    if intent == "scheduler.add_job":
        return {
            "steps": [
                {
                    "tool": "scheduler.add_job",
                    "args": entities,
                }
            ]
        }

    if intent == "summary.today":
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        eps = episodes_in_range(start, now)
        return {"message": summarize_sessions(sessionize(eps))}

    if intent == "summary.yesterday":
        end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)
        eps = episodes_in_range(start, end)
        return {"message": summarize_sessions(sessionize(eps))}

    # Handle unknown intent gracefully
    if intent == "unknown":
        return {"steps": [], "message": "I didn't understand that. Try: 'write a note' or 'play something on youtube'"}

    # Special handling for continue_note (context-aware)
    if intent == "notepad.continue_note":
        note = last_note()
        
        if not note:
            # No previous note, create new one
            return {
                "steps": [
                    {
                        "tool": "notepad.write_file",
                        "args": {
                            "content": entities.get("content", ""),
                            "filename": DEFAULT_FILENAME,
                            "mode": "new_version",
                            "open_after": True
                        }
                    }
                ]
            }
        
        # Append to existing note
        return {
            "steps": [
                {
                    "tool": "notepad.write_file",
                    "args": {
                        "content": entities.get("content", ""),
                        "filename": note["file"],
                        "mode": "append",
                        "open_after": True
                    }
                }
            ]
        }

    # Special handling for notepad.write_note
    if intent == "notepad.write_note":
        return {
            "steps": [
                {
                    "tool": "notepad.write_file",
                    "args": {
                        "content": entities.get("content", ""),
                        "filename": DEFAULT_FILENAME,
                        "mode": "new_version",
                        "open_after": True
                    }
                }
            ]
        }

    if intent not in TOOL_META:
        raise Exception(f"Unknown intent: {intent}")

    meta = TOOL_META[intent]
    steps = []

    for step in meta["steps"]:
        s = {"tool": step["tool"]}
        args = {}
        if isinstance(step.get("args"), dict):
            args.update(step.get("args") or {})

        if "args_from" in step:
            src = step["args_from"]
            if isinstance(src, list):
                for key in src:
                    if not isinstance(key, str):
                        continue
                    args[key] = entities.get(key, "")
            elif isinstance(src, str):
                args[src] = entities.get(src, "")

        if args:
            s["args"] = args
        steps.append(s)

    plan_out = {"steps": steps}
    print(f"DEBUG: planner output -> {plan_out}")
    return plan_out
