"""
Notepad Tool - Complete automation for Windows Notepad.
Consolidated into a single powerful tool.
"""
import subprocess
import time
import os
import win32gui
import win32con
import win32api
import pyautogui


def _find_notepad():
    """Find the Notepad window."""
    def callback(hwnd, hwnds):
        if win32gui.IsWindowVisible(hwnd):
            if "Notepad" in win32gui.GetWindowText(hwnd):
                hwnds.append(hwnd)
        return True
    
    hwnds = []
    win32gui.EnumWindows(callback, hwnds)
    return hwnds[0] if hwnds else None


def run(action: str = "open", text: str = "", path: str = "", **kwargs) -> dict:
    """
    Control Notepad.
    
    Actions:
        - open: Launch Notepad
        - focus: Bring Notepad to front
        - write/type: Write text into Notepad
        - save: Save the current file
        - open_file: Open a specific file
        - clear: Clear the content
    """
    action = (action or "open").strip().lower()
    text = text or kwargs.get("content", "")
    path = path or kwargs.get("file_path", "")
    
    try:
        if action == "open":
            subprocess.Popen(["notepad"], shell=False)
            return {"status": "success", "message": "Notepad opened"}
        
        hwnd = _find_notepad()
        
        if not hwnd and action != "open":
            # Auto-open if not found
            subprocess.Popen(["notepad"], shell=False)
            time.sleep(1)
            hwnd = _find_notepad()
            if not hwnd:
                return {"status": "fail", "reason": "Notepad not found and could not be opened"}

        if action == "focus":
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            return {"status": "success", "message": "Notepad focused"}

        if action in ("write", "type"):
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            pyautogui.write(text, interval=0.01)
            return {"status": "success", "message": f"Wrote {len(text)} characters to Notepad"}

        if action == "save":
            win32gui.SetForegroundWindow(hwnd)
            pyautogui.hotkey('ctrl', 's')
            if path:
                time.sleep(0.5)
                pyautogui.write(path)
                pyautogui.press('enter')
                return {"status": "success", "message": f"Saved file to {path}"}
            return {"status": "success", "message": "Triggered save dialog"}

        if action == "open_file":
            if not os.path.exists(path):
                return {"status": "fail", "reason": f"File not found: {path}"}
            subprocess.Popen(["notepad", path], shell=False)
            return {"status": "success", "message": f"Opened {path} in Notepad"}

        if action == "clear":
            win32gui.SetForegroundWindow(hwnd)
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('backspace')
            return {"status": "success", "message": "Cleared Notepad content"}

        return {"status": "fail", "reason": f"Unknown action: {action}"}

    except Exception as e:
        return {"status": "fail", "reason": f"Notepad error: {str(e)}"}
