"""
Timer Tool - God Tier Edition ⏱️
Multiple named timers, presets, intervals, and smart notifications
"""
import time
import threading
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from plyer import notification

# Global timer store
_active_timers = {}
_timer_lock = threading.Lock()

# Presets configuration
PRESETS = {
    "pomodoro": {"duration": 1500, "message": "🍅 Pomodoro complete! Take a 5min break"},
    "short_break": {"duration": 300, "message": "✅ Short break over! Back to work"},
    "long_break": {"duration": 900, "message": "✅ Long break over! Ready to focus"},
    "quick": {"duration": 60, "message": "⏰ 1 minute is up!"},
    "5min": {"duration": 300, "message": "⏰ 5 minutes is up!"},
    "10min": {"duration": 600, "message": "⏰ 10 minutes is up!"},
    "15min": {"duration": 900, "message": "⏰ 15 minutes is up!"},
    "30min": {"duration": 1800, "message": "⏰ 30 minutes is up!"},
    "1hour": {"duration": 3600, "message": "⏰ 1 hour is up!"},
}

# Timer history file
HISTORY_FILE = Path(__file__).parent.parent / 'data' / 'timer_history.json'
HISTORY_FILE.parent.mkdir(exist_ok=True)


def _save_to_history(timer_data):
    """Save completed timer to history"""
    try:
        history = []
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)
        
        history.append(timer_data)
        # Keep only last 100 timers
        history = history[-100:]
        
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except:
        pass


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


def _timer_worker(timer_id, duration, message, name, repeat):
    """Background thread for timer"""
    try:
        time.sleep(duration)
        
        with _timer_lock:
            if timer_id in _active_timers:
                timer_msg = message or f"⏰ Timer '{name}' is up!"
                
                # Timer completed - send notification
                notification.notify(
                    title="⏰ Timer Complete!",
                    message=timer_msg,
                    app_name="Ankita",
                    timeout=10
                )
                
                # Save to history
                _save_to_history({
                    "name": name,
                    "duration": duration,
                    "completed": datetime.now().isoformat(),
                    "message": timer_msg
                })
                
                # Handle repeat
                if repeat and repeat > 0:
                    # Start another timer
                    timer_data = _active_timers[timer_id]
                    timer_data['repeat'] -= 1
                    timer_data['started'] = datetime.now()
                    timer_data['end_time'] = datetime.now() + timedelta(seconds=duration)
                    
                    # Restart worker
                    thread = threading.Thread(
                        target=_timer_worker, 
                        args=(timer_id, duration, message, name, timer_data['repeat']), 
                        daemon=True
                    )
                    thread.start()
                    print(f"[Timer] Timer '{name}' restarted ({timer_data['repeat']} repeats left)")
                else:
                    del _active_timers[timer_id]
                    print(f"[Timer] Timer '{name}' completed{' with repeats' if repeat else ''}")
    except Exception as e:
        print(f"[Timer] Error: {e}")


def run(action: str = "set", duration: str = "", message: str = "", 
        timer_id: str = "", name: str = "", preset: str = "", repeat: int = 0, **kwargs):
    """
    God-Tier Timer Tool
    
    Args:
        action: set, cancel, list, status, presets, history
        duration: Duration string like '5m', '1h', '30s' (for set)
        message: Optional custom notification message
        timer_id: Timer ID to cancel/check
        name: Friendly name for the timer (default: auto-generated)
        preset: Use a preset timer (pomodoro, short_break, etc.)
        repeat: Number of times to repeat (for intervals)
    """
    action = action.lower().strip()
    
    if action == "set":
        # Check preset first
        if preset and preset.lower() in PRESETS:
            preset_data = PRESETS[preset.lower()]
            seconds = preset_data["duration"]
            if not message:
                message = preset_data["message"]
            if not name:
                name = preset.lower()
        elif duration:
            seconds = _parse_duration(duration)
            if not seconds:
                return {"status": "fail", "reason": "invalid_duration",
                        "message": "Use format like '5m', '1h30m', or '45s'"}
        else:
            return {"status": "fail", "reason": "missing_duration",
                    "message": "Specify duration or preset"}
        
        # Generate timer ID and name
        timer_id = f"timer_{int(time.time() * 1000)}"
        if not name:
            name = f"Timer-{len(_active_timers) + 1}"
        
        end_time = datetime.now() + timedelta(seconds=seconds)
        
        with _timer_lock:
            _active_timers[timer_id] = {
                "name": name,
                "duration": seconds,
                "message": message,
                "end_time": end_time,
                "started": datetime.now(),
                "repeat": repeat
            }
        
        # Start background timer
        thread = threading.Thread(
            target=_timer_worker, 
            args=(timer_id, seconds, message, name, repeat), 
            daemon=True
        )
        thread.start()
        
        mins = seconds // 60
        secs = seconds % 60
        time_str = f"{mins}m {secs}s" if secs else f"{mins}m"
        
        repeat_info = f" (repeats {repeat}x)" if repeat > 0 else ""
        
        return {
            "status": "success",
            "timer_id": timer_id,
            "name": name,
            "duration": seconds,
            "end_time": end_time.strftime("%I:%M:%S %p"),
            "repeat": repeat,
            "message": f"✅ Timer '{name}' set for {time_str}{repeat_info}"
        }
    
    elif action == "cancel":
        if not timer_id and not name:
            # Cancel all timers
            with _timer_lock:
                count = len(_active_timers)
                _active_timers.clear()
            return {"status": "success", "message": f"🚫 Cancelled {count} timer(s)"}
        
        # Cancel specific timer by ID or name
        with _timer_lock:
            if timer_id and timer_id in _active_timers:
                timer_name = _active_timers[timer_id]['name']
                del _active_timers[timer_id]
                return {"status": "success", "message": f"🚫 Timer '{timer_name}' cancelled"}
            elif name:
                # Find by name
                for tid, tdata in list(_active_timers.items()):
                    if tdata['name'].lower() == name.lower():
                        del _active_timers[tid]
                        return {"status": "success", "message": f"🚫 Timer '{name}' cancelled"}
            
            return {"status": "fail", "reason": "timer_not_found",
                    "message": f"Timer not found"}
    
    elif action in ["list", "status"]:
        with _timer_lock:
            if not _active_timers:
                return {"status": "success", "timers": [], 
                        "message": "No active timers"}
            
            timers = []
            for tid, tdata in _active_timers.items():
                remaining = (tdata['end_time'] - datetime.now()).total_seconds()
                if remaining > 0:
                    mins = int(remaining // 60)
                    secs = int(remaining % 60)
                    timers.append({
                        "id": tid,
                        "name": tdata['name'],
                        "remaining_seconds": int(remaining),
                        "remaining_formatted": f"{mins}m {secs}s",
                        "end_time": tdata['end_time'].strftime("%I:%M:%S %p"),
                        "message": tdata.get('message', ''),
                        "repeat": tdata.get('repeat', 0)
                    })
            
            return {"status": "success", "timers": timers, "count": len(timers),
                    "message": f"⏱️ {len(timers)} active timer(s)"}
    
    elif action == "presets":
        # List available presets
        preset_list = []
        for preset_name, preset_data in PRESETS.items():
            mins = preset_data["duration"] // 60
            preset_list.append({
                "name": preset_name,
                "duration": f"{mins}m",
                "description": preset_data["message"]
            })
        
        return {"status": "success", "presets": preset_list,
                "message": f"📋 {len(preset_list)} presets available"}
    
    elif action == "history":
        # Show timer history
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)
            
            return {"status": "success", "history": history[-10:],  # Last 10
                    "message": f"📜 Last {min(10, len(history))} timers"}
        else:
            return {"status": "success", "history": [],
                    "message": "No timer history yet"}
    
    return {"status": "fail", "reason": "invalid_action",
            "message": "Valid actions: set, cancel, list, presets, history"}
