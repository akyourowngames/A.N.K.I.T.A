"""
Screenshot Tool - Pro capture utility with window and region support.
"""
import os
import datetime
import time
import pyautogui
import win32gui
from PIL import ImageGrab


def run(action: str = "full", delay: int = 0, **kwargs) -> dict:
    """
    Take screenshots with advanced options.
    
    Actions:
        - full: Entire screen
        - window: Active window
        - region: Select a region (requires manual mouse drag if implemented, or coordinates)
        - clipboard: Copy to clipboard
        - list: List recent screenshots
    """
    action = (action or "full").strip().lower()
    save_path = kwargs.get("save_path") or kwargs.get("path")
    
    # Optional delay
    if delay > 0:
        time.sleep(delay)
        
    # Default dir
    screenshots_dir = os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    
    if not save_path and action != "clipboard" and action != "list":
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(screenshots_dir, f"screenshot_{timestamp}.png")

    try:
        if action == "full":
            screenshot = pyautogui.screenshot()
            screenshot.save(save_path)
            return {"status": "success", "message": f"Full screenshot saved to {save_path}", "path": save_path}

        if action == "window":
            hwnd = win32gui.GetForegroundWindow()
            rect = win32gui.GetWindowRect(hwnd)
            screenshot = ImageGrab.grab(bbox=rect)
            screenshot.save(save_path)
            return {"status": "success", "message": f"Window screenshot saved to {save_path}", "path": save_path, "window": win32gui.GetWindowText(hwnd)}

        if action == "clipboard":
            screenshot = pyautogui.screenshot()
            import io
            import win32clipboard
            output = io.BytesIO()
            screenshot.convert("RGB").save(output, "BMP")
            data = output.getvalue()[14:]
            output.close()
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            win32clipboard.CloseClipboard()
            return {"status": "success", "message": "Screenshot copied to clipboard"}

        if action == "list":
            files = [os.path.join(screenshots_dir, f) for f in os.listdir(screenshots_dir) if f.endswith('.png')]
            files.sort(key=os.path.getmtime, reverse=True)
            return {"status": "success", "message": f"Found {len(files)} screenshots", "files": files[:10]}

        return {"status": "fail", "reason": f"Unknown action: {action}"}

    except Exception as e:
        return {"status": "fail", "reason": f"Screenshot failed: {str(e)}"}
