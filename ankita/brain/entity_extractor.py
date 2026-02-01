def extract(intent, text):
    if intent == "notepad.write_note":
        return {
            "content": text
        }

    if intent == "notepad.continue_note":
        return {
            "content": text
        }

    if intent == "youtube.play":
        cleaned = text.lower().replace("play", "").replace("on youtube", "")
        return {
            "query": cleaned.strip()
        }

    return {}
