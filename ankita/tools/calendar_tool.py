"""
Calendar Tool - God Tier Edition 📅
Event creation, templates, smart date parsing, and upcoming events
"""
import subprocess
import json
from datetime import datetime, timedelta
from pathlib import Path

# Event templates
EVENT_TEMPLATES = {
    "meeting": {"duration": 60, "description": "Team meeting"},
    "standup": {"duration": 15, "description": "Daily standup"},
    "lunch": {"duration": 60, "description": "Lunch break"},
    "break": {"duration": 15, "description": "Short break"},
    "focus": {"duration": 120, "description": "Focus time - deep work"},
    "workout": {"duration": 45, "description": "Workout session"},
    "review": {"duration": 30, "description": "Code review session"},
}

# Events storage
EVENTS_FILE = Path(__file__).parent.parent / 'data' / 'calendar_events.json'
EVENTS_FILE.parent.mkdir(exist_ok=True)


def _load_events():
    """Load events from file"""
    if EVENTS_FILE.exists():
        try:
            with open(EVENTS_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []


def _save_events(events):
    """Save events to file"""
    try:
        with open(EVENTS_FILE, 'w') as f:
            json.dump(events, f, indent=2)
    except:
        pass


def _parse_date(date_str):
    """Parse natural language dates"""
    if not date_str:
        return datetime.now().strftime('%Y-%m-%d')
    
    date_lower = date_str.lower().strip()
    
    if date_lower == 'today':
        return datetime.now().strftime('%Y-%m-%d')
    elif date_lower == 'tomorrow':
        return (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    elif date_lower == 'next week':
        return (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
    elif date_lower.startswith('in '):
        # "in 3 days"
        try:
            days = int(date_lower.split()[1])
            return (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
        except:
            pass
    
    # Assume it's already formatted
    return date_str


def _check_conflicts(new_event, existing_events):
    """Check if new event conflicts with existing ones"""
    conflicts = []
    
    for event in existing_events:
        if event.get('date') == new_event.get('date'):
            # Same day - check time overlap
            if 'time' in event and 'time' in new_event:
                # Simple time comparison (would need more robust parsing)
                if event['time'] == new_event['time']:
                    conflicts.append(event)
    
    return conflicts


def run(action: str = "open", title: str = "", date: str = "", time: str = "", 
        template: str = "", duration: int = 60, **kwargs):
    """
    God-Tier Calendar Tool
    
    Args:
        action: open, today, week, month, add, list, upcoming, delete, templates
        title: Event title (for add)
        date: Date (today, tomorrow, YYYY-MM-DD, etc.)
        time: Time (HH:MM format)
        template: Event template name
        duration: Duration in minutes (default: 60)
    """
    action = action.lower().strip()
    
    try:
        if action == "open":
            # Open Windows Calendar app
            subprocess.Popen("start outlookcal:", shell=True)
            return {
                "status": "success",
                "message": "📅 Opening Calendar app"
            }
        
        elif action == "today":
            today = datetime.now()
            day_name = today.strftime("%A")
            
            # Get today's events
            events = _load_events()
            today_str = today.strftime('%Y-%m-%d')
            today_events = [e for e in events if e.get('date') == today_str]
            
            return {
                "status": "success",
                "date": today_str,
                "day": day_name,
                "events": today_events,
                "count": len(today_events),
                "message": f"📅 Today is {today.strftime('%A, %B %d, %Y')} ({len(today_events)} events)"
            }
        
        elif action == "week":
            today = datetime.now()
            week_start = today - timedelta(days=today.weekday())
            week_end = week_start + timedelta(days=6)
            
            # Get week's events
            events = _load_events()
            week_events = []
            for i in range(7):
                day = week_start + timedelta(days=i)
                day_str = day.strftime('%Y-%m-%d')
                day_events = [e for e in events if e.get('date') == day_str]
                if day_events:
                    week_events.append({
                        "date": day_str,
                        "day": day.strftime("%A"),
                        "events": day_events
                    })
            
            return {
                "status": "success",
                "week_start": week_start.strftime("%Y-%m-%d"),
                "week_end": week_end.strftime("%Y-%m-%d"),
                "week_events": week_events,
                "message": f"📅 This week: {week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')} ({len(week_events)} days with events)"
            }
        
        elif action == "month":
            today = datetime.now()
            return {
                "status": "success",
                "month": today.strftime("%B %Y"),
                "message": f"📅 Current month: {today.strftime('%B %Y')}"
            }
        
        elif action == "add":
            # Use template if provided
            if template and template.lower() in EVENT_TEMPLATES:
                template_data = EVENT_TEMPLATES[template.lower()]
                if not title:
                    title = template.title()
                if not duration or duration == 60:
                    duration = template_data["duration"]
            
            if not title:
                return {"status": "fail", "reason": "missing_title",
                        "message": "Event title is required"}
            
            # Parse date
            event_date = _parse_date(date)
            
            # Create event
            event = {
                "id": f"evt_{int(datetime.now().timestamp() * 1000)}",
                "title": title,
                "date": event_date,
                "time": time,
                "duration": duration,
                "created": datetime.now().isoformat(),
                "description": kwargs.get('description', '')
            }
            
            # Load and check conflicts
            events = _load_events()
            conflicts = _check_conflicts(event, events)
            
            # Add event
            events.append(event)
            _save_events(events)
            
            when = f"{event_date} at {time}" if time else event_date
            conflict_msg = f" ⚠️ Conflicts with {len(conflicts)} event(s)" if conflicts else ""
            
            return {
                "status": "success",
                "event": event,
                "conflicts": conflicts,
                "message": f"✅ Event '{title}' added for {when} ({duration}min){conflict_msg}"
            }
        
        elif action == "list" or action == "upcoming":
            events = _load_events()
            
            if action == "upcoming":
                # Only future events
                today = datetime.now().strftime('%Y-%m-%d')
                events = [e for e in events if e.get('date', '') >= today]
                events = sorted(events, key=lambda e: (e.get('date', ''), e.get('time', '')))
                events = events[:10]  # Next 10 events
            else:
                # All events
                events = sorted(events, key=lambda e: (e.get('date', ''), e.get('time', '')))
            
            return {
                "status": "success",
                "events": events,
                "count": len(events),
                "message": f"📋 {len(events)} event(s)" + (" upcoming" if action == "upcoming" else "")
            }
        
        elif action == "delete":
            event_id = kwargs.get('event_id', '')
            if not event_id and not title:
                return {"status": "fail", "reason": "missing_identifier",
                        "message": "Provide event_id or title to delete"}
            
            events = _load_events()
            original_count = len(events)
            
            if event_id:
                events = [e for e in events if e.get('id') != event_id]
            elif title:
                events = [e for e in events if e.get('title', '').lower() != title.lower()]
            
            if len(events) < original_count:
                _save_events(events)
                return {"status": "success", 
                        "message": f"🗑️ Event deleted"}
            else:
                return {"status": "fail", "reason": "event_not_found",
                        "message": "Event not found"}
        
        elif action == "templates":
            template_list = []
            for name, data in EVENT_TEMPLATES.items():
                template_list.append({
                    "name": name,
                    "duration": f"{data['duration']}min",
                    "description": data['description']
                })
            
            return {
                "status": "success",
                "templates": template_list,
                "message": f"📋 {len(template_list)} event templates available"
            }
        
        else:
            return {"status": "fail", "reason": "invalid_action",
                    "message": "Valid actions: open, today, week, month, add, list, upcoming, delete, templates"}
    
    except Exception as e:
        return {"status": "error", "error": str(e),
                "message": f"Calendar error: {str(e)}"}
