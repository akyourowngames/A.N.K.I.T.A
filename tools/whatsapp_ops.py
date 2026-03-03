"""
WhatsApp send tool for A.N.K.I.T.A — PyAutoGUI-based outbound sender.

Strategy:
  1. Open WhatsApp Web send URL in your default browser (already logged in).
  2. Wait 15 seconds for the page to load.
  3. Click message box, paste via clipboard, hit Enter.

  No profile issues. Messages stay in history. Works with your real Chrome.

Requirements:
    pip install pyautogui pyperclip pillow
"""
from __future__ import annotations

import os
import time
import webbrowser
import urllib.parse
import subprocess
import platform
from typing import Dict, Any


def _focus_browser() -> None:
    """Bring Chrome window to foreground."""
    try:
        if platform.system() == "Windows":
            script = (
                "Add-Type -AssemblyName Microsoft.VisualBasic; "
                "[Microsoft.VisualBasic.Interaction]::AppActivate('Google Chrome')"
            )
            subprocess.run(["powershell", "-Command", script],
                           capture_output=True, timeout=5)
        elif platform.system() == "Darwin":
            subprocess.run(["osascript", "-e",
                            'tell application "Google Chrome" to activate'],
                           capture_output=True, timeout=5)
        time.sleep(0.5)
    except Exception:
        pass


def send_whatsapp(phone: str, message: str, wait: int = 15) -> Dict[str, Any]:
    """
    Send a WhatsApp message via WhatsApp Web using PyAutoGUI.

    Opens the send URL in your default browser, waits 15 seconds for it
    to load, then uses keyboard automation to send the message.

    Args:
        phone:   E.164 format number, e.g. "+919876543210".
        message: The message text to send.
        wait:    Seconds to wait for WhatsApp Web to load (default 15).

    Returns:
        {"ok": True,  "phone": phone, "message": message} on success.
        {"ok": False, "error": "..."}                     on failure.
    """
    try:
        import pyautogui
        import pyperclip
    except ImportError:
        return {"ok": False, "error": "Run: pip install pyautogui pyperclip pillow"}

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.1

    # ------------------------------------------------------------------
    # 1. Open WhatsApp Web send URL in default browser
    # ------------------------------------------------------------------
    encoded_msg = urllib.parse.quote(message)
    url = (
        f"https://web.whatsapp.com/send"
        f"?phone={phone}&text={encoded_msg}"
        f"&type=phone_number&app_absent=0"
    )

    try:
        webbrowser.open(url)
    except Exception as e:
        return {"ok": False, "error": f"Failed to open browser: {e}"}

    # ------------------------------------------------------------------
    # 2. Wait for page to load
    # ------------------------------------------------------------------
    time.sleep(wait)

    # ------------------------------------------------------------------
    # 3. Focus the browser window
    # ------------------------------------------------------------------
    _focus_browser()
    time.sleep(0.5)

    # ------------------------------------------------------------------
    # 4. Click the message input area (bottom of WhatsApp Web)
    # ------------------------------------------------------------------
    screen_w, screen_h = pyautogui.size()
    msg_box_x = int(screen_w * 0.60)
    msg_box_y = int(screen_h * 0.93)

    try:
        pyautogui.click(msg_box_x, msg_box_y)
        time.sleep(0.5)
    except Exception as e:
        return {"ok": False, "error": f"Failed to click message box: {e}"}

    # ------------------------------------------------------------------
    # 5. Paste message via clipboard and send
    # ------------------------------------------------------------------
    try:
        pyperclip.copy(message)
        time.sleep(0.2)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.4)
        pyautogui.press('enter')
        time.sleep(1.5)
    except Exception as e:
        return {"ok": False, "error": f"Failed to type/send: {e}"}

    return {"ok": True, "phone": phone, "message": message}
