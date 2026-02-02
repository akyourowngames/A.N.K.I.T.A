from collections import Counter


EXCLUDED_PREFIXES = (
    "summary.",
    "scheduler.",
)

EXCLUDED_INTENTS = {
    "unknown",
}


def is_real_action(intent: str) -> bool:
    if not intent:
        return False
    if intent in EXCLUDED_INTENTS:
        return False
    if intent.startswith(EXCLUDED_PREFIXES):
        return False
    return True


def summarize_episodes(episodes: list) -> str:
    actions = [
        ep for ep in (episodes or [])
        if is_real_action(ep.get("intent", ""))
    ]

    if not actions:
        return "You didn’t perform any tracked actions in this period."

    counts = Counter(ep.get("intent", "unknown") for ep in actions)

    lines = []
    for intent, count in counts.items():
        lines.append(f"{intent.replace('.', ' ')} × {count}")

    return "Here’s what you did:\n" + "\n".join(lines)


def summarize_sessions(sessions: list) -> str:
    if not sessions:
        return "You didn’t perform any tracked actions in this period."

    # Aggregate sessions by (intent + stable label) so the summary stays short.
    # A session already means "repeated actions close together"; this layer turns
    # a long list of sessions into "in N sessions" lines.
    grouped = {}
    for s in sessions:
        intent = s.get("intent", "")
        entities = s.get("entities", {}) or {}
        count = int(s.get("count", 0) or 0)

        if not is_real_action(intent):
            continue

        label = intent.replace(".", " ")
        if entities.get("query"):
            label += f" ({entities['query']})"
        elif entities.get("filename"):
            label += f" ({entities['filename']})"

        key = (intent, label)
        bucket = grouped.get(key)
        if not bucket:
            grouped[key] = {"label": label, "sessions": 1, "actions": count}
        else:
            bucket["sessions"] += 1
            bucket["actions"] += count

    if not grouped:
        return "You didn’t perform any tracked actions in this period."

    lines = []
    for _, data in grouped.items():
        sessions_n = data["sessions"]
        actions_n = data["actions"]
        label = data["label"]

        if sessions_n == 1:
            if actions_n > 1:
                lines.append(f"{label} — {actions_n} times")
            else:
                lines.append(label)
        else:
            lines.append(f"{label} in {sessions_n} sessions ({actions_n} actions)")

    return "Here’s what you worked on:\n" + "\n".join(lines)
