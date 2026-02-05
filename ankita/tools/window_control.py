import pyautogui
import time

def run(action=None, **kwargs):
    """
    Control the current focused window using Windows-native shortcuts.
    
    Args:
        action (str): One of maximize, minimize, restore, desktop, left, right, up, down
        
    Returns:
        dict: Status and message about the action performed
    """
    try:
        if action is None:
            action = kwargs.get("action")

        if action == "maximize":
            pyautogui.hotkey("win", "up")
            return {"status": "success", "message": "Window maximized"}
            
        elif action == "minimize":
            pyautogui.hotkey("win", "down")
            return {"status": "success", "message": "Window minimized"}
            
        elif action == "restore":
            pyautogui.hotkey("win", "down")
            time.sleep(0.1)
            pyautogui.hotkey("win", "down")
            return {"status": "success", "message": "Window restored"}
            
        elif action == "desktop":
            pyautogui.hotkey("win", "d")
            return {"status": "success", "message": "Showed desktop"}
            
        elif action == "left":
            pyautogui.hotkey("win", "left")
            return {"status": "success", "message": "Window snapped left"}
            
        elif action == "right":
            pyautogui.hotkey("win", "right")
            return {"status": "success", "message": "Window snapped right"}
            
        elif action == "up":
            pyautogui.hotkey("win", "up")
            return {"status": "success", "message": "Window moved up"}
            
        elif action == "down":
            pyautogui.hotkey("win", "down")
            return {"status": "success", "message": "Window moved down"}
            
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}
            
    except Exception as e:
        return {"status": "error", "message": f"Window control failed: {str(e)}"}
