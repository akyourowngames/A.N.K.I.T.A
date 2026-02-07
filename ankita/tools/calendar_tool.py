"""
Calendar Tool - Basic Windows Calendar integration and date/time queries
"""
import subprocess
from datetime import datetime, timedelta


def run(action: str = "open", **kwargs):
    """
    Calendar tool
    
    Args:
        action: open, today, week, month
    """
    action = action.lower().strip()
    
    try:
        if action == "open":
            # Open Windows Calendar app
            subprocess.Popen("start outlookcal:", shell=True)
            return {
                "status": "success",
                "message": "Opening Calendar app"
            }
        
        elif action == "today":
            today = datetime.now()
            return {
                "status": "success",
                "date": today.strftime("%Y-%m-%d"),
                "day": today.strftime("%A"),
                "message": f"Today is {today.strftime('%A, %B %d, %Y')}"
            }
        
        elif action == "week":
            today = datetime.now()
            week_start = today - timedelta(days=today.weekday())
            week_end = week_start + timedelta(days=6)
            return {
                "status": "success",
                "week_start": week_start.strftime("%Y-%m-%d"),
                "week_end": week_end.strftime("%Y-%m-%d"),
                "message": f"This week: {week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}"
            }
        
        elif action == "month":
            today = datetime.now()
            return {
                "status": "success",
                "month": today.strftime("%B %Y"),
                "message": f"Current month: {today.strftime('%B %Y')}"
            }
        
        else:
            return {"status": "fail", "reason": "invalid_action"}
    
    except Exception as e:
        return {"status": "error", "error": str(e)}
