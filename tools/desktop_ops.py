"""
Desktop interaction tools for A.N.K.I.T.A — God Mode keyboard, mouse & screen control.

Uses pynput (already in requirements.txt) to physically drive the OS keyboard.
Uses mss for fast screen capture and pyautogui for mouse click-by-sight.

Supported actions via desktop_interact():
  type_text      — types a string character by character into the focused window
  press_shortcut — presses a key combination like "ctrl+c", "win+d", "enter"

Screen vision functions:
  capture_screen(monitor, save_path) — fast screenshot via mss, returns path + base64
  read_screen_context(image_path)    — load existing screenshot as base64 for vision
  visual_click(target_description)   — screenshot → GPT-4o coords → pyautogui.click
"""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Key name aliases so natural language maps to pynput Key enum
_KEY_ALIASES: Dict[str, str] = {
    "enter":      "enter",
    "return":     "enter",
    "escape":     "esc",
    "esc":        "esc",
    "tab":        "tab",
    "space":      "space",
    "backspace":  "backspace",
    "delete":     "delete",
    "del":        "delete",
    "home":       "home",
    "end":        "end",
    "pageup":     "page_up",
    "page_up":    "page_up",
    "pagedown":   "page_down",
    "page_down":  "page_down",
    "up":         "up",
    "down":       "down",
    "left":       "left",
    "right":      "right",
    "f1":  "f1",  "f2":  "f2",  "f3":  "f3",  "f4":  "f4",
    "f5":  "f5",  "f6":  "f6",  "f7":  "f7",  "f8":  "f8",
    "f9":  "f9",  "f10": "f10", "f11": "f11", "f12": "f12",
    "ctrl":   "ctrl",
    "control": "ctrl",
    "shift":  "shift",
    "alt":    "alt",
    "win":    "cmd",
    "super":  "cmd",
    "cmd":    "cmd",
    "menu":   "menu",
    "insert": "insert",
    "ins":    "insert",
    "print_screen": "print_screen",
    "prtscn": "print_screen",
    "caps_lock": "caps_lock",
    "num_lock":  "num_lock",
}

# Modifier key names that should be held while pressing the main key
_MODIFIER_KEYS = {"ctrl", "shift", "alt", "cmd"}


def _parse_keys(shortcut: str):
    """
    Parse a shortcut string like "ctrl+shift+esc" into a list of pynput Key objects
    or single characters.

    Returns:
        list of (pynput.keyboard.Key | str) — Key objects for special keys,
        single-char strings for regular characters.
    """
    from pynput.keyboard import Key  # type: ignore

    parts = [p.strip().lower() for p in shortcut.split("+")]
    resolved = []
    for part in parts:
        alias = _KEY_ALIASES.get(part, part)
        if hasattr(Key, alias):
            resolved.append(getattr(Key, alias))
        elif len(part) == 1:
            resolved.append(part)  # Regular character key
        else:
            # Unknown key name — try as-is, pynput may handle it
            if hasattr(Key, part):
                resolved.append(getattr(Key, part))
            else:
                raise ValueError(
                    f"Unknown key name: '{part}'. "
                    f"Valid special keys: {', '.join(_KEY_ALIASES.keys())}"
                )
    return resolved


def desktop_interact(action: str, text: str) -> Dict[str, Any]:
    """
    Interact directly with the OS keyboard — type text or press shortcuts.

    Args:
        action: One of "type_text" or "press_shortcut".
        text:   For type_text — the string to type.
                For press_shortcut — the shortcut string e.g. "ctrl+shift+esc",
                "enter", "win+d", "alt+f4".

    Returns:
        Dict with ok, action, text, and a result message.
    """
    try:
        from pynput.keyboard import Controller, Key  # type: ignore
    except ImportError:
        return {
            "ok": False,
            "error": "pynput is not installed. Run: pip install pynput",
        }

    controller = Controller()
    action = action.strip().lower()

    # Small pre-action delay so focus is established
    time.sleep(0.15)

    if action == "type_text":
        if not text:
            return {"ok": False, "error": "text is required for type_text action"}
        try:
            controller.type(text)
            return {
                "ok": True,
                "action": "type_text",
                "text": text,
                "result": f"Typed {len(text)} characters.",
            }
        except Exception as err:
            return {"ok": False, "error": f"type_text failed: {err}"}

    elif action == "press_shortcut":
        if not text:
            return {"ok": False, "error": "text is required for press_shortcut action"}
        try:
            keys = _parse_keys(text)
            # Press all keys in sequence (hold modifiers, then main key)
            for key in keys:
                controller.press(key)
                time.sleep(0.05)
            # Release in reverse order
            for key in reversed(keys):
                controller.release(key)
                time.sleep(0.05)
            return {
                "ok": True,
                "action": "press_shortcut",
                "text": text,
                "result": f"Pressed shortcut: {text}",
            }
        except Exception as err:
            return {"ok": False, "error": f"press_shortcut failed: {err}"}

    else:
        return {
            "ok": False,
            "error": f"Unknown action '{action}'. Use 'type_text' or 'press_shortcut'.",
        }


# ---------------------------------------------------------------------------
# Phase 1 — The Retina: fast screen capture via mss
# ---------------------------------------------------------------------------

def capture_screen(
    monitor: int = 0,
    save_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Capture the screen using mss (fast, no screen flash).

    Args:
        monitor:   Monitor index. 0 = all monitors combined, 1 = primary, 2 = second, etc.
        save_path: Optional absolute path to save the PNG. If omitted, saves to
                   .ankita/temp/screenshot_<timestamp>.png in the workspace.

    Returns:
        Dict with:
            ok        — bool
            path      — absolute path to saved PNG
            b64       — base64-encoded PNG string (ready for GPT-4o image_url payload)
            width     — image width in pixels
            height    — image height in pixels
    """
    try:
        import mss  # type: ignore
        import mss.tools  # type: ignore
    except ImportError:
        return {"ok": False, "error": "mss is not installed. Run: pip install mss"}

    try:
        with mss.mss() as sct:
            monitors = sct.monitors  # index 0 = all, 1 = primary, etc.
            mon_index = max(0, min(monitor, len(monitors) - 1))
            mon = monitors[mon_index]
            screenshot = sct.grab(mon)

            # Determine save path
            if save_path:
                out_path = Path(save_path)
            else:
                temp_dir = Path(".ankita") / "temp"
                temp_dir.mkdir(parents=True, exist_ok=True)
                ts = int(time.time() * 1000)
                out_path = temp_dir / f"screenshot_{ts}.png"

            out_path.parent.mkdir(parents=True, exist_ok=True)
            mss.tools.to_png(screenshot.rgb, screenshot.size, output=str(out_path))

            # Encode to base64 for vision API
            raw_bytes = out_path.read_bytes()
            b64 = base64.b64encode(raw_bytes).decode("ascii")

            return {
                "ok": True,
                "path": str(out_path.resolve()),
                "b64": b64,
                "width": screenshot.width,
                "height": screenshot.height,
            }

    except Exception as err:
        return {"ok": False, "error": f"capture_screen failed: {err}"}


# ---------------------------------------------------------------------------
# Phase 2 — The Optic Nerve: load existing screenshot as base64
# ---------------------------------------------------------------------------

def read_screen_context(image_path: str) -> Dict[str, Any]:
    """Load an existing screenshot from disk and return its base64 representation.

    Use this when you already have a screenshot on disk and want to re-analyze it
    without taking a new capture.

    Args:
        image_path: Absolute or relative path to a PNG/JPEG image file.

    Returns:
        Dict with:
            ok    — bool
            path  — resolved absolute path
            b64   — base64-encoded image string
            size  — file size in bytes
    """
    try:
        p = Path(image_path)
        if not p.exists():
            return {"ok": False, "error": f"File not found: {image_path}"}
        raw_bytes = p.read_bytes()
        b64 = base64.b64encode(raw_bytes).decode("ascii")
        return {
            "ok": True,
            "path": str(p.resolve()),
            "b64": b64,
            "size": len(raw_bytes),
        }
    except Exception as err:
        return {"ok": False, "error": f"read_screen_context failed: {err}"}


# ---------------------------------------------------------------------------
# Phase 4 — God-Tier Telekinesis: click a UI element by visual description
# ---------------------------------------------------------------------------

def visual_click(
    target_description: str,
    runtime: Any = None,
    screenshot_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Capture the screen, ask GPT-4o to locate a UI element, then click it.

    Workflow:
        1. Take a fresh screenshot (or use screenshot_path if provided).
        2. Send the image + description to GPT-4o vision.
        3. Parse the (x, y) pixel coordinates from the model response.
        4. Use pyautogui.click(x, y) to physically click that position.

    Args:
        target_description: Natural-language description of what to click,
                            e.g. "the Deploy to Vercel button", "the red X button".
        runtime:            LLMRuntime instance for GPT-4o vision call.
                            If None, click is skipped and only coords are returned.
        screenshot_path:    Optional path to an existing screenshot. If omitted,
                            a fresh screenshot is captured automatically.

    Returns:
        Dict with:
            ok          — bool
            x, y        — pixel coordinates GPT-4o identified
            clicked     — True if pyautogui.click() was called successfully
            path        — path to the screenshot used
            reasoning   — the model's raw response (for debugging)
    """
    try:
        import pyautogui  # type: ignore
        pyautogui.FAILSAFE = True  # move mouse to top-left corner to abort
    except ImportError:
        return {"ok": False, "error": "pyautogui is not installed. Run: pip install pyautogui"}

    # Step 1 — capture or load screenshot
    if screenshot_path:
        cap = read_screen_context(screenshot_path)
    else:
        cap = capture_screen(monitor=1)  # primary monitor

    if not cap.get("ok"):
        return {"ok": False, "error": f"Screen capture failed: {cap.get('error', 'unknown')}"}

    b64 = cap["b64"]
    used_path = cap["path"]
    width = cap.get("width", 1920)
    height = cap.get("height", 1080)

    # Step 2 — ask GPT-4o to locate the element
    vision_prompt = (
        f"You are a computer vision assistant. Look at this screenshot carefully.\n"
        f"Find the UI element described as: \"{target_description}\"\n\n"
        f"The image is {width}x{height} pixels.\n"
        f"Reply with ONLY a JSON object in this exact format (no markdown, no explanation):\n"
        f'{{ "x": <pixel_x>, "y": <pixel_y>, "found": true, "label": "<what you found>" }}\n'
        f"If the element is NOT visible, reply:\n"
        f'{{ "x": null, "y": null, "found": false, "label": "not found" }}'
    )

    if runtime is None:
        # No runtime provided — return capture info only (useful for testing)
        return {
            "ok": True,
            "x": None,
            "y": None,
            "clicked": False,
            "path": used_path,
            "reasoning": "No runtime provided — skipping vision lookup and click.",
        }

    try:
        from llm.client import call_chat_with_image  # type: ignore
        raw_response = call_chat_with_image(
            runtime=runtime,
            prompt=vision_prompt,
            image_b64=b64,
            max_tokens=256,
        )
    except Exception as err:
        return {"ok": False, "error": f"GPT-4o vision call failed: {err}", "path": used_path}

    # Step 3 — parse coordinates from model response
    import json as _json
    import re as _re

    coords: Dict[str, Any] = {}
    try:
        # Strip any markdown fences just in case
        clean = _re.sub(r"```[a-z]*\n?", "", raw_response).strip()
        coords = _json.loads(clean)
    except Exception:
        # Try to extract x/y with regex as fallback
        xm = _re.search(r'"x"\s*:\s*(\d+)', raw_response)
        ym = _re.search(r'"y"\s*:\s*(\d+)', raw_response)
        if xm and ym:
            coords = {"x": int(xm.group(1)), "y": int(ym.group(1)), "found": True}
        else:
            return {
                "ok": False,
                "error": "Could not parse coordinates from model response.",
                "reasoning": raw_response,
                "path": used_path,
            }

    if not coords.get("found") or coords.get("x") is None:
        return {
            "ok": False,
            "error": f"Element not found on screen: {target_description}",
            "reasoning": raw_response,
            "path": used_path,
        }

    x = int(coords["x"])
    y = int(coords["y"])

    # Step 4 — click the element
    try:
        time.sleep(0.1)  # tiny settle delay
        pyautogui.click(x, y)
        return {
            "ok": True,
            "x": x,
            "y": y,
            "clicked": True,
            "label": coords.get("label", target_description),
            "path": used_path,
            "reasoning": raw_response,
        }
    except Exception as err:
        return {
            "ok": False,
            "error": f"pyautogui.click failed: {err}",
            "x": x,
            "y": y,
            "clicked": False,
            "path": used_path,
            "reasoning": raw_response,
        }
