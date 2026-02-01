import pyautogui
import time
import pyperclip

def run(content="", text="", **kwargs):
    # Accept both 'content' and 'text' for compatibility
    data = content or text
    
    time.sleep(0.3)
    
    # Use clipboard + paste (bypasses input queue issues)
    pyperclip.copy(data)
    time.sleep(0.2)
    
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.3)
    
    return {"status": "success"}
