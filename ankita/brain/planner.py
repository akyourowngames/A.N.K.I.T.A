
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
        return {
            "steps": [
                {
                    "tool": intent,
                    "args": entities,
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
        if "args_from" in step:
            key = step["args_from"]
            s["args"] = {key: entities.get(key, "")}
        steps.append(s)

    plan_out = {"steps": steps}
    print(f"DEBUG: planner output -> {plan_out}")
    return plan_out
