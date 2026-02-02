import re

def normalize(intent, entities, raw_text):
    text = (raw_text or "").lower().strip()

    def _cleanup(s: str) -> str:
        s = re.sub(r"\s+", " ", s)
        return s.strip(" \t\n\r\f\v-:,.!?")

    # ---- NOTEPAD ----
    if intent == "notepad.write_note":
        cleaned = text
        cleaned = re.sub(r"\b(write|note|save)\b", " ", cleaned)
        cleaned = re.sub(r"\b(in|to)\s+notepad\b", " ", cleaned)
        cleaned = re.sub(r"\bnotepad\b", " ", cleaned)
        return {
            "content": _cleanup(cleaned)
        }

    if intent == "notepad.continue_note":
        cleaned = text
        cleaned = re.sub(r"\b(continue|add|append)\b", " ", cleaned)
        cleaned = re.sub(r"\bnote\b", " ", cleaned)
        return {
            "content": _cleanup(cleaned)
        }

    # ---- YOUTUBE ----
    if intent == "youtube.play":
        cleaned = text
        cleaned = re.sub(r"\bplay\b", " ", cleaned)
        cleaned = re.sub(r"\bon\s+(youtube|yt)\b", " ", cleaned)
        cleaned = re.sub(r"\b(youtube|yt)\b", " ", cleaned)
        return {
            "query": _cleanup(cleaned)
        }

    return entities
