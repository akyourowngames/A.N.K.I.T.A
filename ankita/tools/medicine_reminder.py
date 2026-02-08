"""
Medicine Reminder Tool
Sets reminders for taking medicine
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from tools.base_tool import BaseTool


class MedicineReminder(BaseTool):
    """Tool to set and manage medicine reminders."""
    
    def __init__(self):
        super().__init__()
        self.name = "medicine.reminder"
        self.category = "health"
        
        # Data file for reminders
        self.data_dir = Path(__file__).parent.parent / 'data'
        self.data_dir.mkdir(exist_ok=True)
        self.reminders_file = self.data_dir / 'medicine_reminders.json'
    
    def execute(self, action='add', medicine=None, time=None, frequency='daily', **params):
        """
        Manage medicine reminders.
        
        Args:
            action: 'add', 'list', 'delete'
            medicine: Name of medicine
            time: Time to take (HH:MM format)
            frequency: 'daily', 'weekly', 'as_needed'
        
        Returns:
            dict: Success/error response
        """
        try:
            if action == 'add':
                return self._add_reminder(medicine, time, frequency)
            elif action == 'list':
                return self._list_reminders()
            elif action == 'delete':
                return self._delete_reminder(medicine)
            else:
                return self._error(f"Unknown action: {action}")
        
        except Exception as e:
            return self._error(f"Medicine reminder error: {str(e)}", e)
    
    def _add_reminder(self, medicine, time, frequency):
        """Add a medicine reminder."""
        if not medicine:
            return self._error("Medicine name is required")
        if not time:
            return self._error("Time is required (format: HH:MM)")
        
        # Validate time format
        try:
            hours, minutes = map(int, time.split(':'))
            if not (0 <= hours < 24 and 0 <= minutes < 60):
                return self._error("Invalid time. Use format HH:MM (00:00 to 23:59)")
        except:
            return self._error("Invalid time format. Use HH:MM (e.g., 09:30)")
        
        # Load existing reminders
        reminders = self._load_reminders()
        
        # Check for duplicates
        for r in reminders:
            if (r.get('active') and 
                r['medicine'].lower() == medicine.lower() and 
                r['time'] == time):
                return self._error(
                    f"Reminder already exists for {medicine} at {time}"
                )
        
        # Create new reminder
        reminder = {
            'medicine': medicine,
            'time': time,
            'frequency': frequency or 'daily',
            'created': datetime.now().isoformat(),
            'active': True
        }
        
        # Add to list
        reminders.append(reminder)
        
        # Save
        self._save_reminders(reminders)
        
        # Create Windows notification (simple approach)
        self._create_notification(reminder)
        
        return self._success(
            f"✓ Reminder set: {medicine} at {time} ({frequency or 'daily'})",
            reminder
        )
    
    def _list_reminders(self):
        """List all active reminders."""
        reminders = self._load_reminders()
        active = [r for r in reminders if r.get('active', True)]
        
        return self._success(
            f"Found {len(active)} active reminders",
            {'reminders': active}
        )
    
    def _delete_reminder(self, medicine):
        """Delete a reminder."""
        if not medicine:
            return self._error("Medicine name required")
        
        reminders = self._load_reminders()
        
        # Mark as inactive
        found = False
        for r in reminders:
            if r['medicine'].lower() == medicine.lower():
                r['active'] = False
                found = True
        
        if found:
            self._save_reminders(reminders)
            return self._success(f"Deleted reminder for {medicine}")
        else:
            return self._error(f"Reminder for {medicine} not found")
    
    def _load_reminders(self):
        """Load reminders from file."""
        if self.reminders_file.exists():
            with open(self.reminders_file, 'r') as f:
                return json.load(f)
        return []
    
    def _save_reminders(self, reminders):
        """Save reminders to file."""
        with open(self.reminders_file, 'w') as f:
            json.dump(reminders, f, indent=2)
    
    def _create_notification(self, reminder):
        """Create system notification/task."""
        # For Windows: Could use Task Scheduler
        # For now, just log it
        # In full implementation, integrate with Windows Task Scheduler
        # or use libraries like win10toast for notifications
        pass


# Tool registration
def get_tool():
    """Factory function for tool registry."""
    return MedicineReminder()


# CLI test
if __name__ == '__main__':
    tool = MedicineReminder()
    
    # Add reminder
    result = tool.execute(action='add', medicine='Aspirin', time='09:00', frequency='daily')
    print(result)
    
    # List reminders
    result = tool.execute(action='list')
    print(result)
