"""Fit recent conversation messages without inferred summaries."""
from . import context_budget


def fit(messages, session_id=""):
    budget = max(1000, context_budget.get_context_limit() - 1500)
    systems = [m for m in messages if m.role == "system"]
    history = [m for m in messages if m.role != "system"]
    used = sum(context_budget.message_tokens(m) for m in systems)
    current = next((i for i in range(len(history) - 1, -1, -1) if history[i].role == "user"), len(history))
    if used + sum(context_budget.message_tokens(m) for m in history[current:]) > budget:
        raise ValueError("Current message or tool results are too long for the context window. Shorten the input or request a smaller tool result.")
    recent = []
    for message in reversed(history):
        cost = context_budget.message_tokens(message)
        if recent and used + cost > budget:
            break
        recent.append(message)
        used += cost
    recent.reverse()
    # Never replay an orphaned tool result after dropping its call.
    while recent and recent[0].role == "tool":
        recent.pop(0)
    return systems + recent
