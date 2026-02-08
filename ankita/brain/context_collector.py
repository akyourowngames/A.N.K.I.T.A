"""
Context Collector - Gathers rich context for learning system
"""
import os
import psutil
import pygetwindow as gw
from datetime import datetime


def get_current_context(situation=None, confidence=None, recent_actions=None):
    """
    Collect current context for ML learning.
    
    Returns:
        dict: Context dictionary with temporal, system, and behavioral data
    """
    now = datetime.now()
    hour = now.hour
    
    # Get active window info
    active_window_title = "Unknown"
    active_window_process = "Unknown"
    try:
        active_window = gw.getActiveWindow()
        if active_window:
            active_window_title = active_window.title

        # Best-effort: resolve the foreground window process (Windows)
        try:
            import win32gui  # type: ignore
            import win32process  # type: ignore
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid:
                    active_window_process = psutil.Process(pid).name()
        except Exception:
            # Keep "Unknown" if pywin32 isn't installed
            pass
    except Exception:
        pass

    # Determine time of day
    if 5 <= hour < 12:
        time_of_day = "morning"
    elif 12 <= hour < 17:
        time_of_day = "afternoon"
    elif 17 <= hour < 21:
        time_of_day = "evening"
    else:
        time_of_day = "night"
    
    # Get battery info
    try:
        battery = psutil.sensors_battery()
        battery_percent = battery.percent if battery else None
        is_charging = battery.power_plugged if battery else None
    except:
        battery_percent = None
        is_charging = None
    
    # Get memory usage
    try:
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
    except:
        memory_percent = None
    
    # Build context
    context = {
        # Temporal
        "timestamp": now.isoformat(),
        "hour": hour,
        "minute": now.minute,
        "day_of_week": now.strftime("%A").lower(),
        "day_name": now.strftime("%A"),
        "is_weekend": now.weekday() >= 5,
        "date": now.strftime("%Y-%m-%d"),
        "month": now.month,
        "time_of_day": time_of_day,
        
        # System
        "battery_percent": battery_percent,
        "is_charging": is_charging,
        "memory_percent": memory_percent,
        "cpu_percent": psutil.cpu_percent(),
        "active_window_title": active_window_title,
        "active_window_process": active_window_process,
        
        # User location (from env)
        "user_location": os.getenv("USER_CITY", ""),
        
        # Behavioral
        "recent_actions": recent_actions or [],
        "situation_detected": situation,
        "detection_confidence": confidence
    }
    
    return context


def get_time_category(hour):
    """
    Categorize hour into meal/activity times.
    Useful for pattern matching.
    """
    if 6 <= hour < 10:
        return "breakfast_time"
    elif 12 <= hour < 14:
        return "lunch_time"
    elif 18 <= hour < 21:
        return "dinner_time"
    elif 21 <= hour < 24 or 0 <= hour < 6:
        return "late_night"
    else:
        return "work_hours"


def context_similarity(ctx1, ctx2):
    """
    Calculate similarity between two contexts (0-1).
    Higher = more similar.
    
    Weights different features:
    - Time of day: 0.3
    - Day of week: 0.2
    - Weekend: 0.1
    - Battery level: 0.1
    - Situation: 0.3
    """
    score = 0.0
    
    # Time of day match (0.3)
    if ctx1.get("time_of_day") == ctx2.get("time_of_day"):
        score += 0.3
    elif abs(ctx1.get("hour", 0) - ctx2.get("hour", 0)) <= 2:
        score += 0.15  # Partial match for close hours
    
    # Day of week match (0.2)
    if ctx1.get("day_of_week") == ctx2.get("day_of_week"):
        score += 0.2
    
    # Weekend match (0.1)
    if ctx1.get("is_weekend") == ctx2.get("is_weekend"):
        score += 0.1
    
    # Battery level similarity (0.1)
    bat1 = ctx1.get("battery_percent")
    bat2 = ctx2.get("battery_percent")
    if bat1 is not None and bat2 is not None:
        bat_diff = abs(bat1 - bat2)
        score += 0.1 * (1 - bat_diff / 100.0)
    
    # Situation match (0.3)
    if ctx1.get("situation_detected") == ctx2.get("situation_detected"):
        score += 0.3
    
    return score


def get_context_features(context):
    """
    Extract numeric features for ML (if needed for advanced models).
    
    Returns:
        list: Feature vector
    """
    return [
        context.get("hour", 0),
        context.get("minute", 0),
        1 if context.get("is_weekend") else 0,
        context.get("battery_percent", 50),
        context.get("memory_percent", 50),
        1 if context.get("is_charging") else 0,
    ]
