"""
Desktop interaction tools for A.N.K.I.T.A — God Mode keyboard control.

Uses pynput (already in requirements.txt) to physically drive the OS keyboard.

Key fix: desktop_interact() now accepts an optional `focus` parameter.
When provided, it uses WScript.Shell.AppActivate() via PowerShell to
force-bring the target window to the foreground BEFORE typing anything.

This prevents the "focus stealing" bug where ANKITA typed into Telegram
instead of Notepad because Windows hadn't brought Notepad to the front yet.

Supported actions via desktop_interact():
  type_text     — types a string character by character into the focused window
  press_shortcut — presses a key combination like "ctrl+c", "win+d", "enter"
"""
from __future__ import annotations

import subprocess
import time
from typing import Any, Dict, List, Optional

import pynput.keyboard  # type: ignore

# Global keyboard controller — instantiated once
keyboard = pynput.keyboard.Controller()


# ---------------------------------------------------------------------------
# Key name → pynput.keyboard.Key mapping
# ---------------------------------------------------------------------------
_KEY_MAP: Dict[str, Any] = {
    # Modifiers
    "ctrl":       pynput.keyboard.Key.ctrl,
    "control":    pynput.keyboard.Key.ctrl,
    "shift":      pynput.keyboard.Key.shift,
    "alt":        pynput.keyboard.Key.alt,
    "win":        pynput.keyboard.Key.cmd,
    "super":      pynput.keyboard.Key.cmd,
    "cmd":        pynput.keyboard.Key.cmd,
    # Navigation
    "enter":      pynput.keyboard.Key.enter,
    "return":     pynput.keyboard.Key.enter,
    "escape":     pynput.keyboard.Key.esc,
    "esc":        pynput.keyboard.Key.esc,
    "tab":        pynput.keyboard.Key.tab,
    "space":      pynput.keyboard.Key.space,
    "backspace":  pynput.keyboard.Key.backspace,
    "delete":     pynput.keyboard.Key.delete,
    "del":        pynput.keyboard.Key.delete,
    "home":       pynput.keyboard.Key.home,
    "end":        pynput.keyboard.Key.end,
    "pageup":     pynput.keyboard.Key.page_up,
    "page_up":    pynput.keyboard.Key.page_up,
    "pagedown":   pynput.keyboard.Key.page_down,
    "page_down":  pynput.keyboard.Key.page_down,
    "insert":     pynput.keyboard.Key.insert,
    "ins":        pynput.keyboard.Key.insert,
    # Arrow keys
    "up":         pynput.keyboard.Key.up,
    "down":       pynput.keyboard.Key.down,
    "left":       pynput.keyboard.Key.left,
    "right":      pynput.keyboard.Key.right,
    # Function keys
    "f1":  pynput.keyboard.Key.f1,  "f2":  pynput.keyboard.Key.f2,
    "f3":  pynput.keyboard.Key.f3,  "f4":  pynput.keyboard.Key.f4,
    "f5":  pynput.keyboard.Key.f5,  "f6":  pynput.keyboard.Key.f6,
    "f7":  pynput.keyboard.Key.f7,  "f8":  pynput.keyboard.Key.f8,
    "f9":  pynput.keyboard.Key.f9,  "f10": pynput.keyboard.Key.f10,
    "f11": pynput.keyboard.Key.f11, "f12": pynput.keyboard.Key.f12,
    # Misc
    "menu":       pynput.keyboard.Key.menu,
    "caps_lock":  pynput.keyboard.Key.caps_lock,
    "num_lock":   pynput.keyboard.Key.num_lock,
    "print_screen": pynput.keyboard.Key.print_screen,
    "prtscn":     pynput.keyboard.Key.print_screen,
}


def _get_key_object(key_str: str) -> Any:
    """
    Map a key name string to a pynput Key object or single character.

    Args:
        key_str: Lowercase key name e.g. "ctrl", "enter", "a", "1".

    Returns:
        pynput.keyboard.Key for special keys, or the character string itself.

    Raises:
        ValueError if the key name is unrecognised and not a single char.
    """
    key_str = key_str.strip().lower()
    if key_str in _KEY_MAP:
        return _KEY_MAP[key_str]
    if len(key_str) == 1:
        return key_str  # Regular character — pynput handles it directly
    raise ValueError(
        f"Unknown key name: '{key_str}'. "
        f"Valid special keys: {', '.join(sorted(_KEY_MAP.keys()))}"
    )


# ---------------------------------------------------------------------------
# Focus helper — the core fix for the Telegram hijack bug
# ---------------------------------------------------------------------------

def _focus_window_native(window_title: str) -> bool:
    """
    Force-activate a window by its title using PowerShell + WScript.Shell.AppActivate().

    This is the fix for the "focus stealing" bug. Without this, desktop_interact
    would type into whatever window happened to be active (e.g. Telegram) instead
    of the intended target (e.g. Notepad).

    Args:
        window_title: The window title or partial title to match (e.g. "Notepad").

    Returns:
        True if the PowerShell command ran without exception, False otherwise.
    """
    # Sanitise to prevent command injection (single-quote escaping for PS)
    safe_title = window_title.replace("'", "''")
    ps_script = (
        f"$wshell = New-Object -ComObject wscript.shell; "
        f"$wshell.AppActivate('{safe_title}')"
    )
    try:
        subprocess.run(
            ["powershell", "-Command", ps_script],
            check=False,
            capture_output=True,
            timeout=3,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def desktop_interact(
    action: str,
    text: str,
    focus: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Interact directly with the OS using keyboard input.

    ALWAYS pass `focus` when you know which app you're targeting. This prevents
    the input from going to whatever window is coincidentally active.

    Args:
        action: "type_text" — types text into the focused window.
                "press_shortcut" — presses a key combo like "ctrl+c", "enter", "win+d".
        text:   For type_text: the string to type.
                For press_shortcut: the shortcut string e.g. "ctrl+shift+esc".
        focus:  Optional window title to focus BEFORE acting (e.g. "Notepad", "Chrome").
                If provided, AppActivate is called + 0.5s settle delay before any keys.

    Returns:
        Dict with ok, action, result/error, and a log list.
    """
    result_log: List[str] = []
    action = (action or "").strip().lower()

    # ------------------------------------------------------------------
    # Step 1 — Focus the target window BEFORE touching the keyboard
    # ------------------------------------------------------------------
    if focus:
        success = _focus_window_native(focus)
        if success:
            result_log.append(f"Focus attempt on '{focus}' initiated via WScript.Shell.AppActivate.")
            time.sleep(0.5)  # Give Windows time to actually switch the UI
        else:
            result_log.append(f"⚠️  Warning: Could not focus window '{focus}'. Proceeding anyway.")
            time.sleep(0.3)
    else:
        time.sleep(0.15)  # Small settle delay even without explicit focus

    # ------------------------------------------------------------------
    # Step 2 — Execute the action
    # ------------------------------------------------------------------
    if action == "type_text":
        if not text:
            return {"ok": False, "error": "text is required for type_text", "log": result_log}
        try:
            keyboard.type(text)
            result_log.append(f"Typed {len(text)} characters.")
            return {
                "ok": True,
                "action": "type_text",
                "text": text,
                "result": f"Typed {len(text)} characters into {repr(focus) if focus else 'active window'}.",
                "log": result_log,
            }
        except Exception as err:
            return {"ok": False, "error": f"type_text failed: {err}", "log": result_log}

    elif action == "press_shortcut":
        if not text:
            return {"ok": False, "error": "text is required for press_shortcut", "log": result_log}

        parts = [p.strip().lower() for p in text.split("+")]
        pressed_keys: List[Any] = []

        try:
            # Press all keys (modifiers held first, then main key)
            for part in parts:
                key_obj = _get_key_object(part)
                keyboard.press(key_obj)
                pressed_keys.append(key_obj)
                time.sleep(0.05)

            time.sleep(0.05)

            # Release in reverse order
            for key_obj in reversed(pressed_keys):
                keyboard.release(key_obj)
                time.sleep(0.05)

            result_log.append(f"Pressed shortcut: {text}")
            return {
                "ok": True,
                "action": "press_shortcut",
                "text": text,
                "result": f"Pressed shortcut: {text}",
                "log": result_log,
            }

        except Exception as err:
            # Safety: always release any stuck keys even on crash
            for key_obj in reversed(pressed_keys):
                try:
                    keyboard.release(key_obj)
                except Exception:
                    pass
            return {"ok": False, "error": f"press_shortcut failed: {err}", "log": result_log}

    else:
        return {
            "ok": False,
            "error": f"Unknown action '{action}'. Use 'type_text' or 'press_shortcut'.",
            "log": result_log,
        }
