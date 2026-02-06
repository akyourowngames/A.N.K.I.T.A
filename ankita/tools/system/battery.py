"""
Battery Tool - Get battery status, percentage, and charging state.
Polished with better messages and health indicators.
"""


def run(action: str = "status", **kwargs) -> dict:
    """
    Get battery information.
    
    Actions:
        - status/info: Full battery status (percentage, charging, time remaining)
        - percent/level: Just the percentage
        - charging/plugged: Check if plugged in
        - time/remaining: Time until empty/full
    """
    action = (action or "status").strip().lower()
    
    # Normalize action aliases
    action_aliases = {
        "info": "status",
        "full": "status",
        "level": "percent",
        "percentage": "percent",
        "plugged": "charging",
        "power": "charging",
        "remaining": "time",
    }
    action = action_aliases.get(action, action)
    
    try:
        import psutil
    except ImportError:
        return {
            "status": "fail",
            "reason": "Missing dependency. Install: pip install psutil"
        }
    
    try:
        battery = psutil.sensors_battery()
        
        if battery is None:
            return {
                "status": "success",
                "message": "No battery detected (desktop PC)",
                "has_battery": False
            }
        
        percent = battery.percent
        plugged = battery.power_plugged
        time_left = battery.secsleft
        
        # Convert seconds to readable format
        if time_left == psutil.POWER_TIME_UNLIMITED:
            time_str = "Unlimited (plugged in)"
        elif time_left == psutil.POWER_TIME_UNKNOWN:
            time_str = "Calculating..."
        else:
            hours = time_left // 3600
            minutes = (time_left % 3600) // 60
            if hours > 0:
                time_str = f"{hours}h {minutes}m"
            else:
                time_str = f"{minutes} minutes"
        
        # Determine battery emoji/status
        if percent >= 80:
            level_icon = "🔋"
            level_desc = "High"
        elif percent >= 50:
            level_icon = "🔋"
            level_desc = "Good"
        elif percent >= 20:
            level_icon = "🪫"
            level_desc = "Low"
        else:
            level_icon = "⚠️"
            level_desc = "Critical"
        
        if action == "status":
            if plugged:
                if percent == 100:
                    message = f"Battery fully charged (100%)"
                else:
                    message = f"Battery at {percent}% - Charging"
            else:
                message = f"Battery at {percent}% ({level_desc}) - {time_str} remaining"
            
            return {
                "status": "success",
                "message": message,
                "percent": percent,
                "plugged": plugged,
                "time_remaining": time_str,
                "level": level_desc,
                "has_battery": True
            }
        
        if action == "percent":
            return {
                "status": "success",
                "message": f"Battery is at {percent}%",
                "percent": percent
            }
        
        if action == "charging":
            if plugged:
                if percent == 100:
                    return {
                        "status": "success",
                        "message": "Fully charged and plugged in",
                        "plugged": True,
                        "percent": percent
                    }
                return {
                    "status": "success",
                    "message": f"Charging ({percent}%)",
                    "plugged": True,
                    "percent": percent
                }
            else:
                return {
                    "status": "success",
                    "message": f"Running on battery ({percent}%)",
                    "plugged": False,
                    "percent": percent
                }
        
        if action == "time":
            if plugged:
                return {
                    "status": "success",
                    "message": "Plugged in - no discharge time",
                    "plugged": True,
                    "percent": percent
                }
            return {
                "status": "success",
                "message": f"{time_str} remaining at {percent}%",
                "time_remaining": time_str,
                "percent": percent
            }
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
        
    except Exception as e:
        return {"status": "fail", "reason": "Failed to get battery info", "error": str(e)}
