import json
import os

MEMORY_PATH = os.path.join(os.path.dirname(__file__), "memory.json")

def load():
    if not os.path.exists(MEMORY_PATH):
        return {"notes": []}
    with open(MEMORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save(data):
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def add_note(filename):
    mem = load()
    mem["notes"].append({"file": filename})
    save(mem)

def last_note():
    mem = load()
    if mem["notes"]:
        return mem["notes"][-1]
    return None
