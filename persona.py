"""Persona layer (identity only): who Zumba is and how it talks.

Composes a system prompt from a constant identity block plus editable style
prefs (``zumba config --set-style``). The ``--system`` flag always overrides
everything — persona only applies to the default.

Deferred on purpose: injecting the user profile / core memory blocks into
the persona is Tier 2's user-model work. See TODO(tier2-profile).
"""

from __future__ import annotations

DEFAULT_SYSTEM = "You are Zumba, a concise helpful personal assistant."

IDENTITY = (
    "You are Zumba, a personal AI assistant. Direct, warm, zero fluff: answer "
    "the question asked and use remembered context without being asked. Never "
    "say 'as an AI'. You have long-term memory across sessions — reference "
    "remembered facts naturally when relevant. You have shell and MCP tools — "
    "be decisive, chain commands instead of narrating, report outcomes briefly."
)

# TODO(tier2-profile): inject user profile / core memory blocks here.


def build_system(base: str = "") -> str:
    """Compose the effective system prompt: identity + saved style + base."""
    try:
        from store import config_get

        style = config_get("style", "").strip()
    except Exception:
        style = ""
    parts = [IDENTITY]
    if style:
        parts.append("Style: " + style)
    if (base or "").strip():
        parts.append(base.strip())
    return "\n\n".join(parts)


def resolve_chat_system(flag_system: str, saved_system: str) -> str:
    """Decide the chat system prompt. Explicit --system wins; a saved
    default_system wins over the flag default; otherwise persona applies."""
    if (flag_system or "").strip() and flag_system.strip() != DEFAULT_SYSTEM:
        return flag_system
    if (saved_system or "").strip():
        return saved_system
    return build_system(DEFAULT_SYSTEM)
