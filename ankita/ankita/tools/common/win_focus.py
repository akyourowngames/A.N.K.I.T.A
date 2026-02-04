import ctypes
import time
import pygetwindow as gw

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

def force_focus_and_input(window_title):
    windows = gw.getWindowsWithTitle(window_title)
    if not windows:
        return False

    win = windows[0]
    hwnd = win._hWnd

    # Restore window
    user32.ShowWindow(hwnd, 9)

    # Get thread IDs
    foreground_hwnd = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)

    # Attach input threads
    user32.AttachThreadInput(fg_thread, target_thread, True)

    # Force foreground
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(hwnd)
    time.sleep(0.1)

    # Detach threads
    user32.AttachThreadInput(fg_thread, target_thread, False)

    return True
