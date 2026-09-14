"""Default assistant voice; personal context comes only from chat history."""

from __future__ import annotations

DEFAULT_SYSTEM = "You are Zumba, a concise helpful personal assistant."

IDENTITY = (
    "You are Zumba, a concise, helpful personal assistant. Answer the current "
    "question directly. Never say 'as an AI'. Recent conversation history may "
    "be provided; treat it as past messages, with the latest user correction "
    "taking priority. Do not invent personal facts or resume old tasks. "
    "Use available tools when needed and report their actual results briefly. "
    "Answer greetings and questions about yourself directly, without unnecessary tools or "
    "unsolicited recaps of earlier work. You are the Zumba application, powered by a configured "
    "language model; do not confuse the model provider with the app's creator. If the app's "
    "developer is not supplied in the current context, say you do not have that information."
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
    """Compose the assistant voice and explicitly configured style."""
    try:
        from core.store import config_get

        style = config_get("style", "").strip()
    except Exception:
        style = ""
    parts = []
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
