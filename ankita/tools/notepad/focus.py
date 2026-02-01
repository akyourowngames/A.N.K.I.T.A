import time
import pyautogui
import pygetwindow as gw
from tools.common.win_focus import force_focus_and_input

def run(**kwargs):
    time.sleep(0.3)  # Extra wait for window stability
    
    ok = force_focus_and_input("Notepad")
    if not ok:
        return {"status": "fail", "reason": "Notepad not found"}

    time.sleep(0.3)

    win = gw.getWindowsWithTitle("Notepad")[0]
    x = win.left + win.width // 2
    y = win.top + win.height // 2

    pyautogui.click(x, y)
    time.sleep(0.3)

    return {"status": "success"}
