"""
Timer Tool - Set timers with notifications (Windows Toast notifications)
"""
import time
import threading
import os
from datetime import datetime, timedelta
from plyer import notification

# Global timer store
_active_timers = {}
_timer_lock = threading.Lock()


def _parse_duration(duration_str):
    """
    Parse duration string like '5m', '1h', '30s', '1h30m'
    Returns seconds
    """
    duration_str = duration_str.lower().strip()
    
    total_seconds = 0
    current_number = ""
    
    for char in duration_str:
        if char.isdigit():
            current_number += char
        elif char in ['s', 'm', 'h']:
            if current_number:
                num = int(current_number)
                if char == 's':
                    total_seconds += num
                elif char == 'm':
                    total_seconds += num * 60
                elif char == 'h':
                    total_seconds += num * 3600
                current_number = ""
    
    # If just a number, assume minutes
    if current_number:
        total_seconds += int(current_number) * 60
    
    return total_seconds if total_seconds > 0 else None


def _timer_worker(timer_id, duration, message):
    """Background thread for timer"""
    try:
        time.sleep(duration)
        
        with _timer_lock:
            if timer_id in _active_timers:
                # Timer completed
                notification.notify(
                    title="⏰ Timer Complete!",
                    message=message or f"Timer for {duration//60}m is up!",
                    app_name="Ankita",
                    timeout=10
                )
                del _active_timers[timer_id]
                print(f"[Timer] Timer '{timer_id}' completed")
    except Exception as e:
        print(f"[Timer] Error: {e}")


def run(action: str = "set", duration: str = "", message: str = "", timer_id: str = "", **kwargs):
    """
    Timer tool
    
    Args:
        action: set, cancel, list, status
        duration: Duration string like '5m', '1h', '30s', '1h30m' (for set)
        message: Optional message for notification (for set)
        timer_id: Timer ID to cancel (for cancel/status)
    """
    action = action.lower().strip()
    
    if action == "set":
        if not duration:
            return {"status": "fail", "reason": "missing_duration"}
        
        seconds = _parse_duration(duration)
        if not seconds:
            return {"status": "fail", "reason": "invalid_duration"}
        
        # Generate timer ID
        timer_id = f"timer_{int(time.time())}"
        end_time = datetime.now() + timedelta(seconds=seconds)
        
        with _timer_lock:
            _active_timers[timer_id] = {
                "duration": seconds,
                "message": message,
                "end_time": end_time,
                "started": datetime.now()
            }
        
        # Start background timer
        thread = threading.Thread(target=_timer_worker, args=(timer_id, seconds, message), daemon=True)
        thread.start()
        
        mins = seconds // 60
        secs = seconds % 60
        time_str = f"{mins}m {secs}s" if secs else f"{mins}m"
        
        return {
            "status": "success",
            "timer_id": timer_id,
            "duration": seconds,
            "end_time": end_time.strftime("%I:%M:%S %p"),
            "message": f"Timer set for {time_str}"
        }
    
    elif action == "cancel":
        if not timer_id:
            # Cancel all timers
            with _timer_lock:
                count = len(_active_timers)
                _active_timers.clear()
            return {"status": "success", "message": f"Cancelled {count} timer(s)"}
        
        with _timer_lock:
            if timer_id in _active_timers:
                del _active_timers[timer_id]
                return {"status": "success", "message": f"Timer '{timer_id}' cancelled"}
            else:
                return {"status": "fail", "reason": "timer_not_found"}
    
    elif action == "list" or action == "status":
        with _timer_lock:
            if not _active_timers:
                return {"status": "success", "timers": [], "message": "No active timers"}
            
            timers = []
            for tid, tdata in _active_timers.items():
                remaining = (tdata['end_time'] - datetime.now()).total_seconds()
                if remaining > 0:
                    timers.append({
                        "id": tid,
                        "remaining": int(remaining),
                        "end_time": tdata['end_time'].strftime("%I:%M:%S %p"),
                        "message": tdata.get('message', '')
                    })
            
            return {"status": "success", "timers": timers, "count": len(timers)}
    
    return {"status": "fail", "reason": "invalid_action"}
