"""Persona layer: who Zumba is and how it talks (Tier 2: soul.md + user.md).

Composes a system prompt from soul.md (self-authored identity, capped),
user.md profile (always in context), the constant identity fallback, plus
editable style prefs (``zumba config --set-style``). The ``--system`` flag
always overrides everything — persona only applies to the default.
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

def soul_block() -> str:
    try:
        from identity import soul as _soul
        return _soul.inject_block()
    except Exception:
        return ""


def user_block() -> str:
    try:
        from identity import userprofile as _up
        return _up.profile_block()
    except Exception:
        return ""


def build_system(base: str = "") -> str:
    """Compose the effective system prompt.

    Ordering (test-pinned): soul identity first, then user profile, then the
    constant IDENTITY fallback, style prefs, and base. Soul + profile are
    capped upstream so the window manager stays safe.
    """
    try:
        from core.store import config_get

        style = config_get("style", "").strip()
    except Exception:
        style = ""
    parts = []
    try:
        sb = soul_block()
        if sb:
            parts.append(sb)
    except Exception:
        pass
    try:
        ub = user_block()
        if ub:
            parts.append(ub)
    except Exception:
        pass
    parts.append(IDENTITY)
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
