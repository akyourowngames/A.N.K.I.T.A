"""
DateTime Tool - Get current date, time, day of week, and time zone info.
Polished with natural language responses.
"""
import datetime


def run(action: str = "now", timezone: str | None = None, target: str | None = None, **kwargs) -> dict:
    """
    Get date and time information.
    
    Actions:
        - now/current: Get current date and time
        - date/today: Get just the date
        - time/clock: Get just the time
        - day/weekday: Get day of the week
        - week: Get week number
        - month: Get current month
        - year: Get current year
        - tomorrow: Tomorrow's date
        - yesterday: Yesterday's date
        - countdown: Days until a specific date (requires 'target' param)
        - timezone/tz: Get timezone info
    """
    action = (action or "now").strip().lower()
    
    # Normalize action aliases
    action_aliases = {
        "current": "now",
        "datetime": "now",
        "full": "now",
        "today": "date",
        "clock": "time",
        "weekday": "day",
        "dayofweek": "day",
        "tz": "timezone",
    }
    action = action_aliases.get(action, action)
    
    try:
        now = datetime.datetime.now()
        
        if action == "now":
            formatted = now.strftime("%A, %B %d, %Y at %I:%M %p")
            return {
                "status": "success",
                "message": formatted,
                "datetime": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "day": now.strftime("%A"),
                "timezone": datetime.datetime.now().astimezone().tzname()
            }
        
        if action == "date":
            formatted = now.strftime("%A, %B %d, %Y")
            return {
                "status": "success",
                "message": f"Today is {formatted}",
                "date": now.strftime("%Y-%m-%d"),
                "formatted": formatted,
                "day": now.strftime("%A"),
                "month": now.strftime("%B"),
                "year": now.year
            }
        
        if action == "time":
            formatted_12h = now.strftime("%I:%M %p")
            formatted_24h = now.strftime("%H:%M")
            return {
                "status": "success",
                "message": f"It's {formatted_12h}",
                "time": now.strftime("%H:%M:%S"),
                "time_12h": formatted_12h,
                "time_24h": formatted_24h,
                "hour": now.hour,
                "minute": now.minute
            }
        
        if action == "day":
            day_name = now.strftime("%A")
            return {
                "status": "success",
                "message": f"Today is {day_name}",
                "day": day_name,
                "day_number": now.weekday(),
                "iso_weekday": now.isoweekday()
            }
        
        if action == "week":
            week_num = now.isocalendar()[1]
            return {
                "status": "success",
                "message": f"This is week {week_num} of {now.year}",
                "week": week_num,
                "year": now.year
            }
        
        if action == "month":
            month_name = now.strftime("%B")
            return {
                "status": "success",
                "message": f"It's {month_name} {now.year}",
                "month": month_name,
                "month_number": now.month,
                "year": now.year
            }
        
        if action == "year":
            is_leap = now.year % 4 == 0 and (now.year % 100 != 0 or now.year % 400 == 0)
            return {
                "status": "success",
                "message": f"The year is {now.year}",
                "year": now.year,
                "is_leap": is_leap
            }
        
        if action == "tomorrow":
            tomorrow = now + datetime.timedelta(days=1)
            formatted = tomorrow.strftime("%A, %B %d, %Y")
            return {
                "status": "success",
                "message": f"Tomorrow is {formatted}",
                "date": tomorrow.strftime("%Y-%m-%d"),
                "day": tomorrow.strftime("%A")
            }
        
        if action == "yesterday":
            yesterday = now - datetime.timedelta(days=1)
            formatted = yesterday.strftime("%A, %B %d, %Y")
            return {
                "status": "success",
                "message": f"Yesterday was {formatted}",
                "date": yesterday.strftime("%Y-%m-%d"),
                "day": yesterday.strftime("%A")
            }
        
        if action == "countdown":
            if not target:
                target = kwargs.get("target", "")
            if not target:
                return {"status": "fail", "reason": "Missing target date for countdown"}
            
            try:
                # Try parsing common formats
                target_date = None
                for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%B %d, %Y", "%b %d, %Y"]:
                    try:
                        target_date = datetime.datetime.strptime(target, fmt).date()
                        break
                    except ValueError:
                        continue
                
                if not target_date:
                    return {"status": "fail", "reason": f"Could not parse date: {target}"}
                
                delta = (target_date - now.date()).days
                
                if delta > 0:
                    return {
                        "status": "success",
                        "message": f"{delta} day{'s' if delta != 1 else ''} until {target_date.strftime('%B %d, %Y')}",
                        "days": delta,
                        "target": target_date.isoformat()
                    }
                elif delta < 0:
                    return {
                        "status": "success",
                        "message": f"{-delta} day{'s' if -delta != 1 else ''} since {target_date.strftime('%B %d, %Y')}",
                        "days": delta,
                        "target": target_date.isoformat()
                    }
                else:
                    return {
                        "status": "success",
                        "message": f"Today is {target_date.strftime('%B %d, %Y')}!",
                        "days": 0,
                        "target": target_date.isoformat()
                    }
            except Exception as e:
                return {"status": "fail", "reason": f"Date parsing error: {e}"}
        
        if action == "timezone":
            tz_info = datetime.datetime.now().astimezone()
            return {
                "status": "success",
                "message": f"Timezone: {tz_info.tzname()} (UTC{tz_info.strftime('%z')})",
                "timezone": tz_info.tzname(),
                "utc_offset": tz_info.strftime("%z")
            }
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
        
    except Exception as e:
        return {"status": "fail", "reason": "DateTime operation failed", "error": str(e)}
