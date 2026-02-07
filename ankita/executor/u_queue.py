"""
U-Queue - User-controllable action queue.

Allows users to control action execution with commands like:
- "stop" - clear queue
- "skip this" - skip current action
- "pause" - pause execution
"""

from collections import deque
import time


class UQueue:
    """
    User-controllable action queue.
    Actions can be paused, skipped, or cancelled by user.
    """
    
    def __init__(self):
        self.queue = deque()
        self.current = None
        self.paused = False
        self.history = []
    
    def add(self, action, priority=False):
        """
        Add single action to queue.
        
        Args:
            action: dict with 'tool' and optional 'args'
            priority: if True, add to front of queue
        """
        if priority:
            self.queue.appendleft(action)
        else:
            self.queue.append(action)
    
    def add_multiple(self, actions):
        """Add multiple actions to queue."""
        for action in actions:
            self.queue.append(action)
    
    def skip_current(self):
        """
        Skip the currently executing action.
        
        Returns:
            bool: True if action was skipped
        """
        if self.current:
            self.current['skipped'] = True
            self.current['skipped_at'] = time.time()
            self.history.append(self.current)
            self.current = None
            return True
        return False
    
    def pause(self):
        """Pause queue execution."""
        self.paused = True
    
    def resume(self):
        """Resume queue execution."""
        self.paused = False
    
    def clear(self):
        """Clear all queued actions."""
        self.queue.clear()
        self.paused = False
    
    def get_next(self):
        """
        Get next action from queue.
        
        Returns:
            dict: next action or None if paused/empty
        """
        if self.paused or not self.queue:
            return None
        
        self.current = self.queue.popleft()
        self.current['started_at'] = time.time()
        return self.current
    
    def mark_complete(self, result):
        """
        Mark current action as complete.
        
        Args:
            result: execution result dict
        """
        if self.current:
            self.current['result'] = result
            self.current['completed_at'] = time.time()
            self.current['duration'] = self.current['completed_at'] - self.current.get('started_at', 0)
            self.history.append(self.current)
            self.current = None
    
    def get_status(self):
        """
        Get queue status.
        
        Returns:
            dict with queue state information
        """
        return {
            'paused': self.paused,
            'current': self.current,
            'queued': len(self.queue),
            'queued_actions': list(self.queue),
            'recent_history': self.history[-5:]
        }
    
    def is_empty(self):
        """Check if queue is empty."""
        return len(self.queue) == 0 and self.current is None


# Global queue instance
_queue = UQueue()


def get_queue():
    """Get the global U-Queue instance."""
    return _queue
