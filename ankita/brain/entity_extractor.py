import re


def _parse_after_seconds(t: str) -> tuple[int | None, str]:
    m = re.search(r"\b(?:in|after)\s+(\d+)\s*(seconds?|secs?|minutes?|mins?)\b", t)
    if not m:
        return None, t

    n = int(m.group(1))
    unit = m.group(2)
    seconds = n * 60 if unit.startswith("min") else n

    cleaned = (t[: m.start()] + " " + t[m.end() :]).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return seconds, cleaned


def _parse_time_hhmm(t: str) -> tuple[str | None, str]:
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", t)
    if not m:
        return None, t

    hour = int(m.group(1))
    minute = int(m.group(2) or "0")
    ampm = (m.group(3) or "").lower()

    if ampm == "am":
        if hour == 12:
            hour = 0
    elif ampm == "pm":
        if hour != 12:
            hour += 12

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None, t

    hhmm = f"{hour:02d}:{minute:02d}"

    cleaned = (t[: m.start()] + " " + t[m.end() :]).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return hhmm, cleaned


def extract(intent, text):
    if intent.startswith("system.app."):
        t = (text or "").strip()
        tl = t.lower()

        if intent == "system.app.close_active":
            return {"action": "close_active"}

        force = any(w in tl for w in ["force", "kill", "end task"]) or intent.endswith("force_close")

        # naive app name extraction: remove leading verb phrases
        cleaned = tl
        for prefix in [
            "switch to ", "switch ", "focus ", "go to ",
            "open ", "launch ", "start ",
            "close ", "quit ",
            "force close ", "force quit ", "kill ", "end task ",
        ]:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break

        # strip filler words
        cleaned = re.sub(r"\b(app|application|program|please|the)\b", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        action = "open" if intent.endswith(".open") else "close"
        if intent.endswith(".focus"):
            action = "focus"
        if intent.endswith("force_close"):
            action = "close"

        entities = {"action": action, "app": cleaned}
        if force:
            entities["force"] = True
        return entities

    if intent.startswith("system.volume."):
        t = (text or "").lower()
        m = re.search(r"\b(\d{1,3})\b", t)
        n = int(m.group(1)) if m else None
        if intent.endswith(".set"):
            return {"action": "set", "value": n}
        if intent.endswith(".up"):
            return {"action": "up", "step": n}
        if intent.endswith(".down"):
            return {"action": "down", "step": n}
        if intent.endswith(".mute"):
            return {"action": "mute"}
        if intent.endswith(".unmute"):
            return {"action": "unmute"}
        return {"action": "status"}

    if intent.startswith("system.brightness."):
        t = (text or "").lower()
        m = re.search(r"\b(\d{1,3})\b", t)
        n = int(m.group(1)) if m else None
        if intent.endswith(".set"):
            if n is None and any(w in t for w in ["full", "max", "maximum", "100%", "all the way"]):
                n = 100
            return {"action": "set", "value": n}
        if intent.endswith(".up"):
            return {"action": "up", "step": n}
        if intent.endswith(".down"):
            return {"action": "down", "step": n}
        return {"action": "status"}

    if intent.startswith("system.bluetooth."):
        if intent.endswith(".on"):
            return {"action": "on"}
        if intent.endswith(".off"):
            return {"action": "off"}
        return {"action": "status"}

    if intent == "scheduler.add_job":
        t = (text or "").strip()

        after_seconds, t2 = _parse_after_seconds(t.lower())
        hhmm, t3 = _parse_time_hhmm(t2)

        job_type = "once" if after_seconds is not None else "daily"

        inner = t3.strip()
        inner = re.sub(r"\s+", " ", inner)

        # If the user schedules "play ... at 7am" without specifying a target,
        # make the scheduled command explicit so it routes to YouTube later.
        lowered = inner.lower()
        if lowered.startswith("play ") and ("youtube" not in lowered and " yt" not in lowered and not lowered.endswith(" yt")):
            inner = inner + " on youtube"

        entities = {"text": inner, "type": job_type}
        if after_seconds is not None:
            entities["after_seconds"] = after_seconds
        if hhmm is not None:
            entities["time"] = hhmm
        return entities

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
