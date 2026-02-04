import pyautogui
import time

def run(filename="note.txt", **kwargs):
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "s")
    time.sleep(0.3)
    pyautogui.write(filename)
    pyautogui.press("enter")
    return {"status": "success"}
