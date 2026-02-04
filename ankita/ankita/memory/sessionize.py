from datetime import datetime, timedelta


SESSION_GAP = timedelta(minutes=15)


def _signature(intent: str, entities: dict) -> tuple:
    intent = intent or ""
    entities = (entities or {}).copy()

    # Avoid session fragmentation for notes: content varies by definition.
    # Session identity should be the target note, not the payload.
    if intent.startswith("notepad."):
        entities.pop("content", None)

    items = tuple(sorted(entities.items()))
    return (intent, items)


def sessionize(episodes: list) -> list:
    sessions = []
    episodes = sorted(episodes or [], key=lambda e: e.get("time", ""))

    for ep in episodes:
        intent = ep.get("intent", "")
        entities = ep.get("entities", {}) or {}

        try:
            t = datetime.fromisoformat(ep.get("time", ""))
        except Exception:
            continue

        sig = _signature(intent, entities)

        if not sessions:
            sessions.append({
                "intent": intent,
                "entities": entities,
                "start": t,
                "end": t,
                "count": 1,
            })
            continue

        last = sessions[-1]
        last_sig = _signature(last.get("intent", ""), last.get("entities", {}) or {})

        if sig == last_sig and (t - last["end"]) <= SESSION_GAP:
            last["end"] = t
            last["count"] += 1
        else:
            sessions.append({
                "intent": intent,
                "entities": entities,
                "start": t,
                "end": t,
                "count": 1,
            })

    return sessions
