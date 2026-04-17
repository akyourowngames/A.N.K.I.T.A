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

import base64
import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pynput.keyboard  # type: ignore

try:
    import mss
    import mss.tools
except ImportError:
    mss = None

try:
    import pyautogui
    from PIL import Image as _PILImage  # Pillow ships with pyautogui
    pyautogui.FAILSAFE = True  # Moving mouse to corner aborts any action — safety net
except ImportError:
    pyautogui = None
    _PILImage = None

try:
    import cv2  # type: ignore
except ImportError:
    cv2 = None

# Global keyboard controller — instantiated once
keyboard = pynput.keyboard.Controller()


# ---------------------------------------------------------------------------
# DPI Handshake — detect Windows display scaling factor
# ---------------------------------------------------------------------------

def _get_os_scale_factor() -> float:
    """
    Detect the OS-level DPI scaling factor on Windows (e.g. 1.25 for 125% scaling).

    Problem: mss captures PHYSICAL pixels (e.g. 1920px) but pyautogui moves the
    mouse using LOGICAL points (e.g. 1536 points at 125% scaling). Without this
    correction, clicks land 25% off-target on scaled displays.

    Method: Compare pyautogui's reported screen size (logical) with mss physical size.
    This is the most reliable approach because it uses the same APIs as the actual
    tools we're combining.

    Returns 1.0 on non-Windows platforms or if detection fails.
    """
    try:
        # Method 1 (most reliable): pyautogui logical vs mss physical
        if pyautogui is not None and mss is not None:
            with mss.mss() as sct:
                physical_w = sct.monitors[1]["width"]   # mss physical pixels
            logical_w = pyautogui.size().width           # pyautogui logical points
            if logical_w > 0 and physical_w > 0:
                scale = physical_w / logical_w
                return max(1.0, round(scale * 4) / 4)   # snap to 1.0, 1.25, 1.5, 1.75, 2.0
    except Exception:
        pass

    try:
        # Method 2 (fallback): Windows ctypes GetDeviceCaps
        import ctypes
        dc = ctypes.windll.user32.GetDC(0)
        logical_w  = ctypes.windll.gdi32.GetDeviceCaps(dc, 8)    # HORZRES
        physical_w = ctypes.windll.gdi32.GetDeviceCaps(dc, 118)  # DESKTOPHORZRES
        ctypes.windll.user32.ReleaseDC(0, dc)
        if logical_w > 0 and physical_w > 0:
            scale = physical_w / logical_w
            return max(1.0, round(scale * 4) / 4)
    except Exception:
        pass

    return 1.0


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

    # ------------------------------------------------------------------
    # Mouse actions — pyautogui-powered physical mouse control
    # ------------------------------------------------------------------
    elif action == "mouse_click":
        if pyautogui is None:
            return {"ok": False, "error": "pyautogui not installed. Run: pip install pyautogui", "log": result_log}
        try:
            parts = [p.strip() for p in (text or "").split(",")]
            x = int(parts[0]) if len(parts) >= 1 and parts[0] else None
            y = int(parts[1]) if len(parts) >= 2 and parts[1] else None
            if x is not None and y is not None:
                pyautogui.click(x, y)
                result_log.append(f"Clicked at ({x}, {y}).")
            else:
                pyautogui.click()
                result_log.append("Clicked at current mouse position.")
            return {"ok": True, "action": "mouse_click", "result": result_log[-1], "log": result_log}
        except Exception as err:
            return {"ok": False, "error": f"mouse_click failed: {err}", "log": result_log}

    elif action == "mouse_right_click":
        if pyautogui is None:
            return {"ok": False, "error": "pyautogui not installed", "log": result_log}
        try:
            parts = [p.strip() for p in (text or "").split(",")]
            x = int(parts[0]) if len(parts) >= 1 and parts[0] else None
            y = int(parts[1]) if len(parts) >= 2 and parts[1] else None
            if x is not None and y is not None:
                pyautogui.rightClick(x, y)
                result_log.append(f"Right-clicked at ({x}, {y}).")
            else:
                pyautogui.rightClick()
                result_log.append("Right-clicked at current mouse position.")
            return {"ok": True, "action": "mouse_right_click", "result": result_log[-1], "log": result_log}
        except Exception as err:
            return {"ok": False, "error": f"mouse_right_click failed: {err}", "log": result_log}

    elif action == "mouse_double_click":
        if pyautogui is None:
            return {"ok": False, "error": "pyautogui not installed", "log": result_log}
        try:
            parts = [p.strip() for p in (text or "").split(",")]
            x = int(parts[0]) if len(parts) >= 1 and parts[0] else None
            y = int(parts[1]) if len(parts) >= 2 and parts[1] else None
            if x is not None and y is not None:
                pyautogui.doubleClick(x, y)
                result_log.append(f"Double-clicked at ({x}, {y}).")
            else:
                pyautogui.doubleClick()
                result_log.append("Double-clicked at current mouse position.")
            return {"ok": True, "action": "mouse_double_click", "result": result_log[-1], "log": result_log}
        except Exception as err:
            return {"ok": False, "error": f"mouse_double_click failed: {err}", "log": result_log}

    elif action == "mouse_move":
        if pyautogui is None:
            return {"ok": False, "error": "pyautogui not installed", "log": result_log}
        try:
            parts = [p.strip() for p in (text or "").split(",")]
            if len(parts) < 2:
                return {"ok": False, "error": "mouse_move needs 'x, y' in text field", "log": result_log}
            x, y = int(parts[0]), int(parts[1])
            pyautogui.moveTo(x, y, duration=0.3)
            result_log.append(f"Moved mouse to ({x}, {y}).")
            return {"ok": True, "action": "mouse_move", "result": result_log[-1], "log": result_log}
        except Exception as err:
            return {"ok": False, "error": f"mouse_move failed: {err}", "log": result_log}

    elif action == "scroll":
        if pyautogui is None:
            return {"ok": False, "error": "pyautogui not installed", "log": result_log}
        try:
            clicks = int(text or "3")
            pyautogui.scroll(clicks)  # positive=up, negative=down
            direction = "up" if clicks > 0 else "down"
            result_log.append(f"Scrolled {direction} by {abs(clicks)} clicks.")
            return {"ok": True, "action": "scroll", "result": result_log[-1], "log": result_log}
        except Exception as err:
            return {"ok": False, "error": f"scroll failed: {err}", "log": result_log}

    elif action == "drag":
        if pyautogui is None:
            return {"ok": False, "error": "pyautogui not installed", "log": result_log}
        try:
            parts = [p.strip() for p in (text or "").split(",")]
            if len(parts) < 4:
                return {"ok": False, "error": "drag needs 'x1, y1, x2, y2' in text field", "log": result_log}
            x1, y1, x2, y2 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            pyautogui.moveTo(x1, y1, duration=0.2)
            pyautogui.mouseDown()
            pyautogui.moveTo(x2, y2, duration=0.4)
            pyautogui.mouseUp()
            result_log.append(f"Dragged from ({x1},{y1}) to ({x2},{y2}).")
            return {"ok": True, "action": "drag", "result": result_log[-1], "log": result_log}
        except Exception as err:
            return {"ok": False, "error": f"drag failed: {err}", "log": result_log}

    elif action == "mouse_position":
        if pyautogui is None:
            return {"ok": False, "error": "pyautogui not installed", "log": result_log}
        try:
            pos = pyautogui.position()
            return {"ok": True, "action": "mouse_position", "x": pos.x, "y": pos.y, "result": f"Mouse at ({pos.x}, {pos.y})", "log": result_log}
        except Exception as err:
            return {"ok": False, "error": f"mouse_position failed: {err}", "log": result_log}

    else:
        return {
            "ok": False,
            "error": (
                f"Unknown action '{action}'. Use: "
                "type_text, press_shortcut, mouse_click, mouse_right_click, "
                "mouse_double_click, mouse_move, scroll, drag, mouse_position."
            ),
            "log": result_log,
        }


# ---------------------------------------------------------------------------
# VISION — Screenshot capture (mss: fast, no flash, no UAC prompt)
# ---------------------------------------------------------------------------

def _is_near_black_image(img: "_PILImage.Image") -> bool:
    try:
        extrema = img.getextrema()  # [(min,max), (min,max), (min,max)]
        if not extrema:
            return False
        max_r = extrema[0][1]
        max_g = extrema[1][1]
        max_b = extrema[2][1]
        min_r = extrema[0][0]
        min_g = extrema[1][0]
        min_b = extrema[2][0]
        return (
            max_r <= 5 and max_g <= 5 and max_b <= 5
            and (max_r - min_r) < 3
            and (max_g - min_g) < 3
            and (max_b - min_b) < 3
        )
    except Exception:
        return False


def _is_near_black_bytes(data: bytes) -> bool:
    try:
        if not data:
            return False
        sample = data[::1000]
        if not sample:
            return False
        max_v = max(sample)
        min_v = min(sample)
        return max_v <= 5 and (max_v - min_v) < 3
    except Exception:
        return False


def capture_screen(monitor: int = 1, save_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Capture the screen using MSS (fast, no flash).

    Returns the saved file path AND a base64-encoded PNG string so the
    calling LLM can analyse the image without a second round-trip.

    Args:
        monitor:   Monitor index. 1 = primary (default). 0 = all monitors combined.
        save_path: Optional absolute path to save the PNG.
                   Defaults to .ankita/temp/screenshot_<timestamp>.png

    Returns:
        Dict with ok, path, base64, resolution  — or ok=False, error.
    """
    if mss is None:
        return {"ok": False, "error": "mss library not installed. Run: pip install mss"}

    try:
        with mss.mss() as sct:
            # Resolve save path
            if save_path:
                file_path = Path(save_path).resolve()
                file_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                temp_dir = Path.cwd() / ".ankita" / "temp"
                temp_dir.mkdir(parents=True, exist_ok=True)
                file_path = temp_dir / f"screenshot_{int(time.time())}.png"

            # Try requested monitor first, then fallbacks for blank captures
            max_idx = len(sct.monitors) - 1
            preferred = monitor if 0 <= monitor <= max_idx else 1
            candidates = [preferred, 0, 1, 2]
            seen = set()
            for mon in candidates:
                if mon in seen:
                    continue
                seen.add(mon)
                if mon < 0 or mon > max_idx:
                    continue
                sct_img = sct.grab(sct.monitors[mon])
                orig_w, orig_h = sct_img.width, sct_img.height

                if _PILImage is not None:
                    img = _PILImage.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    if _is_near_black_image(img):
                        continue
                    img.save(str(file_path), format="PNG", optimize=True)
                    final_resolution = f"{orig_w}x{orig_h}"
                    scale_x = 1.0
                    scale_y = 1.0

                    _MAX_VIS_W = 960
                    vis_img = img.copy()
                    if orig_w > _MAX_VIS_W:
                        _vis_h = int(orig_h * _MAX_VIS_W / orig_w)
                        vis_img = img.resize((_MAX_VIS_W, _vis_h), _PILImage.LANCZOS)
                    from io import BytesIO as _BytesIO
                    _vis_buf = _BytesIO()
                    vis_img.save(_vis_buf, format="JPEG", quality=60)
                    b64_data = base64.b64encode(_vis_buf.getvalue()).decode("utf-8")
                    vis_resolution = f"{vis_img.width}x{vis_img.height}"
                    print(
                        f"[ScreenCapture] Full PNG saved ({orig_w}x{orig_h}). "
                        f"Vision b64: {vis_resolution} JPEG @ q60 = {len(b64_data)//1024}KB",
                        flush=True,
                    )
                    return {
                        "ok": True,
                        "path": str(file_path),
                        "absolute_path": str(file_path.resolve()),
                        "FILE_PATH": str(file_path.resolve()),
                        "base64": b64_data,           # downscaled JPEG for LLM vision (small)
                        "base64_mime": "image/jpeg",   # hint for call_chat_with_image()
                        "resolution": vis_resolution,  # resolution of the b64 image
                        "original_resolution": f"{orig_w}x{orig_h}",  # full-res (for visual_click)
                        "scale_x": scale_x,
                        "scale_y": scale_y,
                    }

                # --- Fallback: raw MSS PNG (no Pillow available) ---
                if _is_near_black_bytes(sct_img.rgb):
                    continue
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=str(file_path))
                final_resolution = f"{orig_w}x{orig_h}"
                vis_resolution = final_resolution
                scale_x = 1.0
                scale_y = 1.0
                with open(file_path, "rb") as f:
                    b64_data = base64.b64encode(f.read()).decode("utf-8")
                return {
                    "ok": True,
                    "path": str(file_path),
                    "absolute_path": str(file_path.resolve()),
                    "FILE_PATH": str(file_path.resolve()),
                    "base64": b64_data,
                    "base64_mime": "image/jpeg",
                    "resolution": vis_resolution,
                    "original_resolution": f"{orig_w}x{orig_h}",
                    "scale_x": scale_x,
                    "scale_y": scale_y,
                }

            return {
                "ok": False,
                "error": (
                    "Screen capture appears blank (near-black) on all tested monitors. "
                    "This often happens in headless/locked sessions. Unlock the display and try again."
                ),
                "path": str(file_path),
            }

    except Exception as err:
        return {"ok": False, "error": f"Screen capture failed: {err}"}


def read_screen_context(image_path: str) -> Dict[str, Any]:
    """
    Read an existing screenshot file from disk and return it as base64.

    Useful when the screenshot was already taken and you just need to
    re-encode it for a follow-up LLM vision call.

    Args:
        image_path: Absolute or relative path to the PNG/JPEG file.

    Returns:
        Dict with ok, base64  — or ok=False, error.
    """
    p = Path(image_path)
    if not p.exists():
        return {"ok": False, "error": f"File not found: {image_path}"}
    try:
        if _PILImage is not None:
            try:
                img = _PILImage.open(str(p))
                img = img.convert("RGB")
                if _is_near_black_image(img):
                    return {
                        "ok": False,
                        "error": (
                            "Screen context image appears blank (near-black). "
                            "This often happens in headless/locked sessions."
                        ),
                        "path": str(p.resolve()),
                    }
            except Exception:
                pass
        with open(p, "rb") as f:
            raw = f.read()
        if _is_near_black_bytes(raw):
            return {
                "ok": False,
                "error": (
                    "Screen context image appears blank (near-black). "
                    "This often happens in headless/locked sessions."
                ),
                "path": str(p.resolve()),
            }
        b64_data = base64.b64encode(raw).decode("utf-8")
        resolved = str(p.resolve())
        return {"ok": True, "base64": b64_data, "path": resolved, "absolute_path": resolved, "FILE_PATH": resolved}
    except Exception as err:
        return {"ok": False, "error": str(err)}


# ---------------------------------------------------------------------------
# MOUSE — God-Mode visual click (screenshot → GPT-4o → pyautogui)
# ---------------------------------------------------------------------------

def visual_click(
    target_description: str,
    runtime: Any = None,
    screenshot_path: Optional[str] = None,
    verify: bool = False,
) -> Dict[str, Any]:
    """
    God-Mode Click: see the screen, locate a UI element by description, click it.

    Workflow:
      1. Capture the screen (or use an existing screenshot if provided).
      2. Send the image + target description to GPT-4o vision.
      3. Parse the (x, y) coordinates returned by the model.
      4. Move the mouse smoothly and click.

    Args:
        target_description: Natural-language description of the element to click,
                            e.g. "the red Close button", "Submit button", "search bar".
        runtime:            The LLM runtime/client object injected by the agent layer.
                            Required for the GPT-4o vision call.
        screenshot_path:    Optional path to an existing screenshot to avoid recapturing.

    Returns:
        Dict with ok, clicked, coords, screen_path  — or ok=False, error.
    """
    if pyautogui is None:
        return {"ok": False, "error": "pyautogui not installed. Run: pip install pyautogui"}

    if runtime is None:
        return {"ok": False, "error": "LLM runtime not injected — cannot perform vision analysis."}

    # Groq (LLaMA) does NOT support vision — coordinates will be hallucinated
    if hasattr(runtime, "provider") and runtime.provider == "groq":
        return {
            "ok": False,
            "error": (
                "visual_click requires a vision-capable model (e.g. GPT-4o via Copilot). "
                "Groq/LLaMA does not support image input. "
                "Set LLM_PROVIDER=copilot in your .env to enable visual clicking."
            ),
        }

    # Step 1 — Get the image
    if screenshot_path:
        img_res = read_screen_context(screenshot_path)
    else:
        img_res = capture_screen(monitor=1)

    if not img_res.get("ok"):
        return img_res

    b64_img = img_res["base64"]

    # Step 2 — Ask GPT-4o for the element BOUNDING BOX with RESOLUTION ANCHORING
    # Inject exact image dimensions so the model doesn't hallucinate a generic grid
    resized_res = img_res.get("resolution", "1024x576")
    orig_res = img_res.get("original_resolution", resized_res)

    system_prompt = (
        "You are a GUI automation agent with pixel-perfect precision. "
        "Analyse the screenshot provided. Find the UI element described by the user.\n\n"
        f"⚡ RESOLUTION ANCHOR: I am sending you a {resized_res} image "
        f"(downscaled from the original {orig_res} screen). "
        f"ALL coordinates you return MUST be in the {resized_res} image coordinate space — "
        "x from 0 to the image width, y from 0 to the image height. "
        "Do NOT use the original screen resolution.\n\n"
        "Respond ONLY with a JSON object — no markdown, no prose, no explanation.\n\n"
        "PREFERRED format (bounding box — most accurate):\n"
        '  {"left": 100, "top": 200, "right": 300, "bottom": 240, "found": true}\n\n'
        "FALLBACK format (if you cannot determine edges, give center point):\n"
        '  {"x": 200, "y": 220, "found": true}\n\n'
        "If the element is not visible anywhere on screen:\n"
        '  {"found": false}'
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Image resolution: {resized_res}. "
                        f"Find this element and return its bounding box in {resized_res} pixel space: "
                        f"{target_description}"
                    ),
                },
                # IMPORTANT: use "high" detail so the API does NOT internally rescale to 512x512.
                # With "low", coordinates returned by the model are in 512x512 space → wrong clicks.
                # With "high", coordinates are in the actual image resolution space → accurate.
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}", "detail": "high"}},
            ],
        },
    ]

    try:
        # Late import to avoid circular dependency at module load time
        from llm.client import call_chat_with_image  # type: ignore

        # Build a single combined prompt (call_chat_with_image sends one image + one text prompt)
        vision_prompt = (
            f"{system_prompt}\n\n"
            f"Image resolution: {resized_res}. "
            f"Find this element and return its bounding box in {resized_res} pixel space: "
            f"{target_description}"
        )

        # Screenshots are PNG — pass correct MIME type so the API parses them correctly.
        # (The default in call_chat_with_image is image/jpeg for webcam; screenshots are PNG)
        content = call_chat_with_image(runtime, vision_prompt, b64_img, max_tokens=300, mime_type="image/png")

        # --- "Chatty AI" Fix: surgically extract the JSON block from any prose ---
        # Step 1: strip markdown code fences
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].strip()

        # Step 2: use regex to find the FIRST complete {...} block
        json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if json_match:
            content = json_match.group(0)
        else:
            # Last resort: try to find any {...} even with nested braces
            json_match = re.search(r"\{.*?\}", content, re.DOTALL)
            if json_match:
                content = json_match.group(0)

        data = json.loads(content)

        if not data.get("found"):
            return {
                "ok": False,
                "error": f"Element not found on screen: '{target_description}'",
                "screen_path": img_res.get("path"),
            }

        # --- Fix 2: Bounding Box → compute center (averages out AI estimation error) ---
        if "left" in data and "right" in data and "top" in data and "bottom" in data:
            # Bounding box path — most accurate
            ai_x = (float(data["left"]) + float(data["right"])) / 2.0
            ai_y = (float(data["top"]) + float(data["bottom"])) / 2.0
            coord_method = "bbox_center"
        else:
            # Fallback: model returned x/y center point directly
            ai_x = float(data.get("x", 0))
            ai_y = float(data.get("y", 0))
            coord_method = "xy_point"

        # Coordinate conversion:
        # AI returns coords in PHYSICAL screen pixel space (full-res screenshot, no resize).
        # pyautogui uses LOGICAL points (affected by Windows DPI scaling).
        # Formula: logical_point = physical_pixel / os_scale
        img_scale_x = float(img_res.get("scale_x", 1.0))  # always 1.0 now (no resize)
        img_scale_y = float(img_res.get("scale_y", 1.0))  # always 1.0 now (no resize)
        os_scale = _get_os_scale_factor()

        real_x = round(ai_x / os_scale)
        real_y = round(ai_y / os_scale)

        # Step 3 — Visual Debugger: draw red crosshair on screenshot BEFORE clicking
        # This lets you inspect debug_target.png to diagnose misses:
        #   Dot ON button  → DPI/scaling code is wrong
        #   Dot OFF button → AI vision is wrong
        debug_path: Optional[str] = None
        if _PILImage is not None and img_res.get("path"):
            try:
                from PIL import ImageDraw  # type: ignore
                dbg_img = _PILImage.open(img_res["path"])
                draw = ImageDraw.Draw(dbg_img)

                # Convert real screen coords BACK to image space for the debug dot
                # Inverse of: real = round(ai / os_scale)  → ai = real * os_scale
                dbg_x = round(real_x * os_scale)
                dbg_y = round(real_y * os_scale)

                r = 14  # crosshair circle radius in image pixels
                # Red circle
                draw.ellipse([dbg_x - r, dbg_y - r, dbg_x + r, dbg_y + r],
                             outline="red", width=3)
                # Crosshair lines
                draw.line([dbg_x - r, dbg_y, dbg_x + r, dbg_y], fill="red", width=2)
                draw.line([dbg_x, dbg_y - r, dbg_x, dbg_y + r], fill="red", width=2)
                # Small filled center dot
                draw.ellipse([dbg_x - 3, dbg_y - 3, dbg_x + 3, dbg_y + 3], fill="red")

                debug_path = str(Path(img_res["path"]).parent / "debug_target.png")
                dbg_img.save(debug_path)
            except Exception as dbg_err:
                debug_path = f"[debug draw failed: {dbg_err}]"

        # Step 4 — Physical mouse move + click at REAL screen coordinates
        pyautogui.moveTo(real_x, real_y, duration=0.4)  # Smooth — looks human, avoids missed hits
        pyautogui.click()

        result: Dict[str, Any] = {
            "ok": True,
            "clicked": target_description,
            "coord_method": coord_method,              # "bbox_center" or "xy_point"
            "ai_coords": [round(ai_x), round(ai_y)],  # AI coords in resized image space
            "real_coords": [real_x, real_y],           # actual mouse point on screen
            "img_scale": [img_scale_x, img_scale_y],  # image resize multiplier
            "os_scale": os_scale,                      # Windows DPI scaling factor
            "debug_path": debug_path,                  # red-crosshair debug image path
            "before_path": img_res.get("path", screenshot_path or "provided"),
        }

        # --- CLOSED-LOOP VERIFY: re-capture screen after click to confirm UI changed ---
        if verify:
            time.sleep(0.8)  # wait for the UI to settle after the click
            after = capture_screen(monitor=1)
            if after.get("ok"):
                result["after_path"] = after.get("path")
                result["after_base64"] = after.get("base64")
                result["verified"] = True
            else:
                result["verified"] = False
                result["verify_error"] = after.get("error")

        return result

    except json.JSONDecodeError as err:
        return {"ok": False, "error": f"Could not parse GPT-4o response as JSON: {err}. Raw: {content!r}"}
    except Exception as err:
        return {"ok": False, "error": f"visual_click failed: {err}"}


# ---------------------------------------------------------------------------
# WEBCAM — Real-World Vision (Turbo Mode)
# ---------------------------------------------------------------------------

def capture_webcam(camera_index: int = 0, save_path: Optional[str] = None) -> Dict[str, Any]:
    """
    TURBO MODE: Captures a webcam frame with near-zero latency.

    Optimizations vs. naive implementation:
    - No warmup loop (1 dummy read to clear buffer, then instant real read)
    - Direct RAM → Base64 encoding via cv2.imencode (no disk I/O)
    - Resizes to 800px wide max (Goldilocks Zone: great for AI vision, 4× smaller payload)
    - Optional save_path for debugging only

    Args:
        camera_index: OpenCV camera ID. 0 = default webcam, 1 = second camera, etc.
        save_path:    Optional path to also save the image to disk for debugging.

    Returns:
        Dict with ok, path, base64, resolution, latency_mode
        — or ok=False, error on failure.
    """
    if cv2 is None:
        return {"ok": False, "error": "cv2 not installed. Run: pip install opencv-python"}

    cap = None
    try:
        # 1. Open camera — try DirectShow backend first (more reliable on Windows)
        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            # Try again without DirectShow hint
            cap.release()
            cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return {
                "ok": False,
                "error": (
                    f"Camera {camera_index} could not be opened. "
                    "This usually means: (1) another app like Teams/Zoom is using it — "
                    "close those apps and try again, or (2) no webcam is connected. "
                    "Try camera_index=1 if you have a second camera."
                ),
            }

        # 2. INSTANT SNAP — one dummy read to flush the stale buffer frame,
        #    then one real read for the actual photo (no 15-frame warmup needed)
        cap.read()          # flush stale buffer
        ret, frame = cap.read()   # real capture
        cap.release()
        cap = None

        if not ret or frame is None:
            return {"ok": False, "error": "Failed to capture frame from webcam"}

        # 3. TURBO RESIZE — cap at 480px wide.
        # 800px @ q85 JPEG = ~120-200KB base64 → sometimes hits Copilot's vision payload limit.
        # 480px @ q65 JPEG = ~30-60KB base64 → well within limits, still plenty of detail for AI.
        height, width = frame.shape[:2]
        if width > 480:
            scale = 480.0 / width
            frame = cv2.resize(frame, (480, int(height * scale)), interpolation=cv2.INTER_AREA)

        # 4. RAM INJECTION — encode to JPEG in memory, skip disk write entirely
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 65]
        ok_enc, buffer = cv2.imencode(".jpg", frame, encode_params)
        if not ok_enc:
            return {"ok": False, "error": "cv2.imencode failed to compress frame"}

        b64 = base64.b64encode(buffer).decode("utf-8")

        # 5. Optional disk save (for debugging only — not part of normal flow)
        final_path = "memory_only"
        if save_path:
            p = Path(save_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(p), frame)
            final_path = str(p.resolve())

        final_h, final_w = frame.shape[:2]
        return {
            "ok": True,
            "path": final_path,
            "base64": b64,
            "resolution": f"{final_w}x{final_h}",
            "latency_mode": "turbo",
        }

    except Exception as err:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        return {"ok": False, "error": str(err)}
