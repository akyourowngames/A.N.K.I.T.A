"""
General Reminder Tool
Sets various types of reminders
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from tools.base_tool import BaseTool


class ReminderTool(BaseTool):
    """Tool to set and manage general reminders."""
    
    def __init__(self):
        super().__init__()
        self.name = "reminder.set"
        self.category = "productivity"
        
        # Data file
        self.data_dir = Path(__file__).parent.parent / 'data'
        self.data_dir.mkdir(exist_ok=True)
        self.reminders_file = self.data_dir / 'reminders.json'
    
    def execute(self, action='add', title=None, time=None, date=None, **params):
        """
        Manage reminders.
        
        Args:
            action: 'add', 'list', 'delete', 'complete'
            title: What to be reminded about
            time: Time (HH:MM format)
            date: Date (YYYY-MM-DD) or 'today', 'tomorrow'
        
        Returns:
            dict: Success/error response
        """
        try:
            if action == 'add':
                return self._add_reminder(title, time, date, params)
            elif action == 'list':
                return self._list_reminders()
            elif action == 'delete':
                return self._delete_reminder(title)
            elif action == 'complete':
                return self._complete_reminder(title)
            else:
                return self._error(f"Unknown action: {action}")
        
        except Exception as e:
            return self._error(f"Reminder error: {str(e)}", e)
    
    def _add_reminder(self, title, time, date, params):
        """Add a reminder."""
        if not title:
            return self._error("Title is required")
        if not title.strip():
            return self._error("Title cannot be empty")
        
        # Parse date
        reminder_date = self._parse_date(date)
        
        # Validate time if provided
        if time:
            try:
                hours, minutes = map(int, time.split(':'))
                if not (0 <= hours < 24 and 0 <= minutes < 60):
                    return self._error("Invalid time. Use HH:MM format")
            except:
                return self._error("Invalid time format. Use HH:MM (e.g., 14:30)")
        
        # Load existing
        reminders = self._load_reminders()
        
        # Check for duplicates
        for r in reminders:
            if (not r.get('completed') and 
                r['title'].lower() == title.lower() and
                r.get('date') == reminder_date):
                return self._error(
                    f"Similar reminder already exists for '{title}' on {reminder_date}"
                )
        
        # Create reminder
        reminder = {
            'id': len(reminders) + 1,
            'title': title.strip(),
            'time': time,
            'date': reminder_date,
            'created': datetime.now().isoformat(),
            'completed': False,
            'notes': params.get('notes', '')
        }
        
        reminders.append(reminder)
        self._save_reminders(reminders)
        
        # Format message
        when = f"{reminder_date} at {time}" if time else reminder_date
        
        return self._success(
            f"✓ Reminder set: '{title}' for {when}",
            reminder
        )
    
    def _list_reminders(self):
        """List active reminders."""
        reminders = self._load_reminders()
        active = [r for r in reminders if not r.get('completed', False)]
        
        # Sort by date
        active.sort(key=lambda r: (r.get('date', ''), r.get('time', '')))
        
        return self._success(
            f"Found {len(active)} active reminders",
            {'reminders': active}
        )
    
    def _delete_reminder(self, title):
        """Delete a reminder."""
        if not title:
            return self._error("Title required")
        
        reminders = self._load_reminders()
        
        # Remove matching
        original_count = len(reminders)
        reminders = [r for r in reminders if r['title'].lower() != title.lower()]
        
        if len(reminders) < original_count:
            self._save_reminders(reminders)
            return self._success(f"Deleted reminder: {title}")
        else:
            return self._error(f"Reminder '{title}' not found")
    
    def _complete_reminder(self, title):
        """Mark reminder as complete."""
        if not title:
            return self._error("Title required")
        
        reminders = self._load_reminders()
        
        found = False
        for r in reminders:
            if r['title'].lower() == title.lower():
                r['completed'] = True
                r['completed_at'] = datetime.now().isoformat()
                found = True
        
        if found:
            self._save_reminders(reminders)
            return self._success(f"Completed: {title}")
        else:
            return self._error(f"Reminder '{title}' not found")
    
    def _parse_date(self, date_str):
        """Parse date string."""
        if not date_str:
            return datetime.now().strftime('%Y-%m-%d')
        
        date_lower = date_str.lower()
        
        if date_lower == 'today':
            return datetime.now().strftime('%Y-%m-%d')
        elif date_lower == 'tomorrow':
            return (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            return date_str  # Assume it's already in correct format
    
    def _load_reminders(self):
        """Load from file."""
        if self.reminders_file.exists():
            with open(self.reminders_file, 'r') as f:
                return json.load(f)
        return []
    
    def _save_reminders(self, reminders):
        """Save to file."""
        with open(self.reminders_file, 'w') as f:
            json.dump(reminders, f, indent=2)


# Tool registration
def get_tool():
    """Factory function for tool registry."""
    return ReminderTool()


# CLI test
if __name__ == '__main__':
    tool = ReminderTool()
    
    # Add
    result = tool.execute(action='add', title='Meeting with team', time='14:00', date='tomorrow')
    print(result)
    
    # List
    result = tool.execute(action='list')
    print(result)
