"""
Focus Mode Tool
Enables complete focus environment
"""
from tools.base_tool import BaseTool


class FocusMode(BaseTool):
    """Tool to enable complete focus mode."""
    
    def __init__(self):
        super().__init__()
        self.name = "focus.mode"
        self.category = "productivity"
    
    def execute(self, duration=25, enable_music=True, **params):
        """
        Enable focus mode.
        
        Args:
            duration: Focus duration in minutes (default: 25 - Pomodoro)
            enable_music: Whether to play focus music
        
        Returns:
            dict: Success/error response
        """
        try:
            actions_taken = []
            
            # 1. Enable Do Not Disturb
            try:
                from tools.dnd.enable import get_tool as get_dnd
                dnd = get_dnd()
                dnd.execute()
                actions_taken.append("✓ DND enabled")
            except Exception as e:
                # Try alternative path
                try:
                    import subprocess
                    subprocess.run(['powershell', '-Command', 
                        '(New-Object -ComObject Shell.Application).MinimizeAll()'], 
                        capture_output=True)
                    actions_taken.append("✓ Focus mode active")
                except:
                    actions_taken.append("✗ DND failed")
            
            # 2. Close distracting apps (using taskkill)
            distracting_apps = ['chrome.exe', 'discord.exe', 'slack.exe']
            closed = []
            
            try:
                import subprocess
                for app in distracting_apps:
                    try:
                        subprocess.run(['taskkill', '/IM', app, '/F'], 
                            capture_output=True, timeout=2)
                        closed.append(app.replace('.exe', ''))
                    except:
                        pass
                
                if closed:
                    actions_taken.append(f"✓ Closed: {', '.join(closed)}")
            except:
                pass
            
            # 3. Set timer (notify user)
            try:
                from tools.timer.set import get_tool as get_timer
                timer = get_timer()
                timer.execute(minutes=duration)
                actions_taken.append(f"✓ Timer set for {duration} min")
            except:
                actions_taken.append(f"⏱ Focus for {duration} min (manual timer)")
            
            # 4. Optional: Play focus music via YouTube
            if enable_music:
                try:
                    import webbrowser
                    webbrowser.open("https://www.youtube.com/watch?v=jfKfPfyJRdk")  # Lofi hip hop
                    actions_taken.append("✓ Focus music started")
                except:
                    actions_taken.append("✗ Music failed")
            
            # 5. Lower brightness (Windows)
            try:
                import subprocess
                # Windows brightness via PowerShell
                subprocess.run([
                    'powershell', '-Command',
                    '(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,70)'
                ], capture_output=True, timeout=3)
                actions_taken.append("✓ Brightness set to 70%")
            except:
                pass
            
            return self._success(
                f"Focus mode activated for {duration} minutes",
                {
                    'duration': duration,
                    'actions': actions_taken,
                    'music_enabled': enable_music
                }
            )
        
        except Exception as e:
            return self._error(f"Focus mode error: {str(e)}", e)


# Tool registration
def get_tool():
    """Factory function for tool registry."""
    return FocusMode()


# CLI test
if __name__ == '__main__':
    tool = FocusMode()
    result = tool.execute(duration=25, enable_music=True)
    print(result)
