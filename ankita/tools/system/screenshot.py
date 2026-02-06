"""
Screenshot Tool - Capture screen, window, or region.
Polished with better error handling and more actions.
"""
import os
import datetime


def run(action: str = "full", save_path: str | None = None, **kwargs) -> dict:
    """
    Take screenshots.
    
    Actions:
        - full/screen/desktop: Capture entire screen
        - window/active/current: Capture active window
        - clipboard/copy: Capture to clipboard
    """
    action = (action or "full").strip().lower()
    
    # Normalize action aliases
    action_aliases = {
        "screen": "full",
        "desktop": "full",
        "active": "window",
        "current": "window",
        "copy": "clipboard",
        "status": "full",  # Default fallback
    }
    action = action_aliases.get(action, action)
    
    try:
        import pyautogui
        from PIL import ImageGrab
    except ImportError:
        return {
            "status": "fail",
            "reason": "Missing dependencies. Install: pip install pyautogui pillow"
        }
    
    # Generate default save path if not provided
    if not save_path and action != "clipboard":
        screenshots_dir = os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(screenshots_dir, f"screenshot_{timestamp}.png")
    
    try:
        if action in ("full",):
            # Full screen capture
            screenshot = pyautogui.screenshot()
            screenshot.save(save_path)
            return {
                "status": "success",
                "message": f"Screenshot saved to Pictures/Screenshots",
                "path": save_path
            }
        
        if action in ("window",):
            # Active window capture
            try:
                import win32gui
                from PIL import ImageGrab
                
                hwnd = win32gui.GetForegroundWindow()
                window_title = win32gui.GetWindowText(hwnd)
                
                # Get window dimensions
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                
                # Capture the window region
                screenshot = ImageGrab.grab(bbox=(left, top, right, bottom))
                screenshot.save(save_path)
                
                return {
                    "status": "success",
                    "message": f"Window screenshot saved ({window_title[:30]}...)" if len(window_title) > 30 else f"Window screenshot saved ({window_title})",
                    "path": save_path,
                    "window": window_title
                }
            except ImportError:
                # Fallback to full screenshot if win32 not available
                screenshot = pyautogui.screenshot()
                screenshot.save(save_path)
                return {
                    "status": "success",
                    "message": "Full screenshot saved (window capture unavailable)",
                    "path": save_path
                }
        
        if action in ("clipboard",):
            # Capture to clipboard
            screenshot = pyautogui.screenshot()
            try:
                import io
                import win32clipboard
                
                output = io.BytesIO()
                screenshot.convert("RGB").save(output, "BMP")
                data = output.getvalue()[14:]  # Remove BMP header
                output.close()
                
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
                win32clipboard.CloseClipboard()
                
                return {
                    "status": "success",
                    "message": "Screenshot copied to clipboard"
                }
            except ImportError:
                # Save to file as fallback
                if not save_path:
                    screenshots_dir = os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots")
                    os.makedirs(screenshots_dir, exist_ok=True)
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    save_path = os.path.join(screenshots_dir, f"screenshot_{timestamp}.png")
                screenshot.save(save_path)
                return {
                    "status": "success",
                    "message": "Screenshot saved (clipboard unavailable)",
                    "path": save_path
                }
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
        
    except Exception as e:
        return {"status": "fail", "reason": "Screenshot failed", "error": str(e)}
