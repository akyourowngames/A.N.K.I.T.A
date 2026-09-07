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

# PLAN-GO §3 — the "heading to" trip-brain behavior. The planner is NOT a
# classifier; it is this composition pattern over small geo tools.
GEO_BRIEF = (
    "Geo/trip behavior: you have zumba__geo_geocode / geo_reverse / geo_route "
    "(mode drive|walk|bike) / geo_traffic (live TomTom) / geo_nearby (free-text "
    "category) / geo_weather (eta_hours for arrival) / geo_maps_link / "
    "geo_track_start / geo_track_stop / geo_whereami / geo_visit_log. "
    "Single questions need ONE call (how far → geo_route; raining → geo_weather; "
    "cafes near X → geocode + nearby). When the user says they are heading "
    "somewhere, chain: geocode destination → route from last known location "
    "(geo_whereami; ask if unknown) → traffic delta → weather at arrival → 2-3 "
    "nearby places → memory/vault context. Compose ONE message: leave-by time, "
    "route summary, weather line, personal context, maps link. During an active "
    "live share, only interrupt on material changes (+10 min or arrival). "
    "Partial answers beat silence; on backend failure give a maps link + honest "
    "'can't estimate'."
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
    try:
        if GEO_BRIEF:
            parts.append(GEO_BRIEF)
    except Exception:
        pass
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
