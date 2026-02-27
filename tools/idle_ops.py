"""
Idle Detection Tool for A.N.K.I.T.A
=====================================
Uses the Windows API (GetLastInputInfo) to check how long the user has been
away from their keyboard/mouse. Cross-platform fallback returns 0.0 (always active).

Usage:
    from tools.idle_ops import get_idle_seconds
    idle = get_idle_seconds()
    if idle > 300:
        print("User has been AFK for 5 minutes!")
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import platform
from typing import Optional


# ---------------------------------------------------------------------------
# Windows LASTINPUTINFO structure
# ---------------------------------------------------------------------------

class _LASTINPUTINFO(ctypes.Structure):
    """Windows LASTINPUTINFO structure for GetLastInputInfo."""
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_ulong),
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_idle_seconds() -> float:
    """
    Return the number of seconds since the user last touched the mouse or keyboard.

    Uses Windows API (GetLastInputInfo + GetTickCount) for accurate system-wide
    idle detection — this catches inactivity even across different windows/apps.

    Returns:
        float: Idle time in seconds. Returns 0.0 on non-Windows or on API failure
               (safe fallback — treats system as "active" to avoid false triggers).

    Example:
        idle = get_idle_seconds()
        if idle > 300:
            # User has been AFK for 5+ minutes
            trigger_sentinel()
    """
    if platform.system() != "Windows":
        # Non-Windows: no equivalent cross-platform API without extra deps
        return 0.0

    try:
        last_input = _LASTINPUTINFO()
        last_input.cbSize = ctypes.sizeof(_LASTINPUTINFO)

        # GetLastInputInfo populates dwTime with the tick count of last input event
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last_input)):
            return 0.0

        # GetTickCount returns milliseconds since Windows boot
        # Difference = milliseconds of inactivity
        tick_now = ctypes.windll.kernel32.GetTickCount()
        idle_ms = tick_now - last_input.dwTime

        # Handle tick counter wraparound (happens every ~49.7 days of uptime)
        if idle_ms < 0:
            idle_ms += 0xFFFFFFFF  # 32-bit unsigned wraparound correction

        return max(0.0, idle_ms / 1000.0)

    except Exception:
        return 0.0


def is_idle(threshold_seconds: float = 300.0) -> bool:
    """
    Convenience helper — returns True if the user has been idle longer than the threshold.

    Args:
        threshold_seconds: Idle threshold in seconds. Default 300 (5 minutes).

    Returns:
        bool: True if idle >= threshold_seconds, False otherwise.
    """
    return get_idle_seconds() >= threshold_seconds


def idle_status() -> dict:
    """
    Return a structured idle status dict — useful for tool engine integration.

    Returns:
        Dict with ok, idle_seconds, idle_minutes, is_afk (>5min), threshold_met.
    """
    idle_secs = get_idle_seconds()
    return {
        "ok": True,
        "idle_seconds": round(idle_secs, 1),
        "idle_minutes": round(idle_secs / 60.0, 2),
        "is_afk": idle_secs >= 300.0,
        "summary": (
            f"User has been idle for {idle_secs:.0f}s "
            f"({'AFK' if idle_secs >= 300 else 'active'})"
        ),
    }
