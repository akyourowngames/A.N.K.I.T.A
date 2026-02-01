import json
from memory.memory_manager import last_note

with open("registry/tools_meta.json") as f:
    TOOL_META = json.load(f)

DEFAULT_FILENAME = "note.txt"

def plan(intent_result):
    intent = intent_result["intent"]
    entities = intent_result.get("entities", {})

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

    return {"steps": steps}
