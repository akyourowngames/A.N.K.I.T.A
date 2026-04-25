"""
Input control tool suite for JAKATA.

Four tools:
  keyboard  - type text, run hotkeys, press keys, key sequences
  clipboard - read and write the system clipboard
  window    - focus windows by title, list open windows, get active window
  mouse     - click, double-click, move, drag, and scroll

Dependencies (install in your project):
  pip install pyautogui pyperclip pygetwindow pynput

Platform notes:
  Windows : full support via pyautogui + pygetwindow + pyperclip
  Linux   : keyboard/clipboard via pyautogui + xclip; windows via xdotool
  macOS   : keyboard via pyautogui; clipboard via pbcopy/pbpaste; windows via AppleScript

All tools use lazy imports and return a clean ToolResult(ok=False) with an
actionable error message if a dependency is missing — the agent can tell the
user exactly what to install.

Register all four via:
    from jakata_agent.tools.keyboard import register_input_tools
    register_input_tools(registry)
"""
from __future__ import annotations

import platform
import subprocess
import sys
import time
import ctypes
from typing import Any

from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Shared platform detection
# ---------------------------------------------------------------------------

PLATFORM = platform.system()   # "Windows" | "Linux" | "Darwin"

# Hotkeys the agent must never execute regardless of instruction
_BLOCKED_HOTKEYS: frozenset[str] = frozenset({
    "ctrl+alt+delete",
    "ctrl+alt+del",
    "win+l",           # lock screen
    "ctrl+alt+backspace",   # kill X server
})

# Maximum characters allowed in a single type operation
_MAX_TYPE_LEN = 4000

# Valid pyautogui key names (subset — covers everything useful)
VALID_KEYS: frozenset[str] = frozenset({
    "enter", "return", "esc", "escape", "tab", "space", "backspace", "delete",
    "up", "down", "left", "right",
    "home", "end", "pageup", "pagedown",
    "f1","f2","f3","f4","f5","f6","f7","f8","f9","f10","f11","f12",
    "ctrl", "alt", "shift", "win", "command", "option", "super",
    "a","b","c","d","e","f","g","h","i","j","k","l","m",
    "n","o","p","q","r","s","t","u","v","w","x","y","z",
    "0","1","2","3","4","5","6","7","8","9",
    "volumeup","volumedown","volumemute",
    "playpause","nexttrack","prevtrack",
    "printscreen","scrolllock","pause","insert","numlock","capslock",
    "semicolon","apostrophe","comma","period","slash","backslash",
    "minus","equals","grave","bracketleft","bracketright",
})


def _norm_hotkey(hotkey: str) -> str:
    """Normalise hotkey string: lowercase, strip spaces around +."""
    return hotkey.lower().replace(" ", "").replace("++", "+plus")


def _is_blocked_hotkey(hotkey: str) -> bool:
    return _norm_hotkey(hotkey) in _BLOCKED_HOTKEYS


def _import_pyautogui():
    try:
        import pyautogui
        pyautogui.FAILSAFE = True   # move mouse to top-left corner to abort
        pyautogui.PAUSE = 0.05      # tiny pause between actions
        return pyautogui, None
    except ImportError:
        return None, "pyautogui not installed. Run: pip install pyautogui"


def _import_pyperclip():
    try:
        import pyperclip
        return pyperclip, None
    except ImportError:
        return None, "pyperclip not installed. Run: pip install pyperclip"


def _import_pygetwindow():
    try:
        import pygetwindow
        return pygetwindow, None
    except ImportError:
        return None, "pygetwindow not installed. Run: pip install pygetwindow"


def _powershell(command: str) -> tuple[bool, str]:
    try:
        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", command],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
        return True, output
    except subprocess.CalledProcessError as exc:
        return False, (exc.output or str(exc)).strip()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _windows_active_title_ctypes() -> str:
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value.strip()
    except Exception:  # noqa: BLE001
        return ""


def _window_rect_payload(win) -> dict[str, int]:
    return {
        "left": int(getattr(win, "left", 0)),
        "top": int(getattr(win, "top", 0)),
        "width": int(getattr(win, "width", 0)),
        "height": int(getattr(win, "height", 0)),
        "right": int(getattr(win, "left", 0)) + int(getattr(win, "width", 0)),
        "bottom": int(getattr(win, "top", 0)) + int(getattr(win, "height", 0)),
    }


def _primary_screen_size() -> tuple[int, int]:
    try:
        if PLATFORM == "Windows":
            return int(ctypes.windll.user32.GetSystemMetrics(0)), int(ctypes.windll.user32.GetSystemMetrics(1))
    except Exception:  # noqa: BLE001
        pass
    pyautogui, err = _import_pyautogui()
    if err or pyautogui is None:
        return 0, 0
    try:
        width, height = pyautogui.size()
        return int(width), int(height)
    except Exception:  # noqa: BLE001
        return 0, 0


# ---------------------------------------------------------------------------
# 1. KeyboardTool
# ---------------------------------------------------------------------------

class KeyboardTool(Tool):
    name = "keyboard"
    public = False
    description = (
        "Control the keyboard: type text, run shortcuts (Ctrl+C, Alt+Tab, etc.), "
        "press individual keys, or hold modifier keys while pressing others. "
        "Works with any focused app — VS Code, browser, terminal, anything."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["type", "hotkey", "press", "key_down", "key_up", "sequence"],
                "description": (
                    "type: types a string of text. "
                    "hotkey: runs a keyboard shortcut like 'ctrl+s' or 'alt+f4'. "
                    "press: presses and releases a single key like 'enter' or 'f5'. "
                    "key_down: holds a key (use with key_up). "
                    "key_up: releases a held key. "
                    "sequence: runs a list of actions in order."
                ),
            },
            "text": {
                "type": "string",
                "description": "Text to type (for action=type).",
            },
            "keys": {
                "type": "string",
                "description": (
                    "For hotkey: shortcut string like 'ctrl+c', 'ctrl+shift+p', 'alt+tab'. "
                    "For press/key_down/key_up: a single key name like 'enter', 'f5', 'esc'."
                ),
            },
            "interval": {
                "type": "number",
                "description": "Seconds between keystrokes when typing. Default 0.03.",
            },
            "steps": {
                "type": "array",
                "description": (
                    "For action=sequence: list of step objects. "
                    "Each step: {action, text?, keys?, delay?}. "
                    "delay: seconds to wait before this step."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("interval", 0.03)
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        pyautogui, err = _import_pyautogui()
        if err:
            return ToolResult(ok=False, summary=err, data={}, error="missing_dep")

        action = str(args.get("action", "")).strip()

        if action == "type":
            return self._do_type(pyautogui, args)
        if action == "hotkey":
            return self._do_hotkey(pyautogui, args)
        if action == "press":
            return self._do_press(pyautogui, args)
        if action == "key_down":
            return self._do_key_hold(pyautogui, args, down=True)
        if action == "key_up":
            return self._do_key_hold(pyautogui, args, down=False)
        if action == "sequence":
            return self._do_sequence(pyautogui, args)

        return ToolResult(ok=False, summary=f"Unknown keyboard action: {action}", data={}, error="unknown_action")

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _do_type(self, pyautogui, args: dict[str, Any]) -> ToolResult:
        text = str(args.get("text", ""))
        if not text:
            return ToolResult(ok=False, summary="No text provided for type action.", data={}, error="missing_text")
        if len(text) > _MAX_TYPE_LEN:
            return ToolResult(ok=False, summary=f"Text too long ({len(text)} chars). Max {_MAX_TYPE_LEN}.", data={}, error="text_too_long")
        interval = float(args.get("interval", 0.03))
        try:
            # Use write() for ASCII, typewrite handles unicode poorly on some platforms
            pyautogui.write(text, interval=interval)
            return ToolResult(
                ok=True,
                summary=f"Typed {len(text)} characters.",
                data={"action": "type", "text_preview": text[:80], "chars": len(text)},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Type failed.", data={}, error=str(exc))

    def _do_hotkey(self, pyautogui, args: dict[str, Any]) -> ToolResult:
        keys_raw = str(args.get("keys", "")).strip()
        if not keys_raw:
            return ToolResult(ok=False, summary="No keys provided for hotkey action.", data={}, error="missing_keys")
        if _is_blocked_hotkey(keys_raw):
            return ToolResult(ok=False, summary=f"Blocked hotkey: {keys_raw}", data={}, error="blocked_hotkey")
        parts = [k.strip() for k in keys_raw.lower().split("+") if k.strip()]
        invalid = [k for k in parts if k not in VALID_KEYS]
        if invalid:
            return ToolResult(ok=False, summary=f"Unknown key name(s): {', '.join(invalid)}", data={}, error="invalid_keys")
        try:
            pyautogui.hotkey(*parts)
            return ToolResult(
                ok=True,
                summary=f"Pressed hotkey: {keys_raw}",
                data={"action": "hotkey", "keys": keys_raw, "parts": parts},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Hotkey failed.", data={}, error=str(exc))

    def _do_press(self, pyautogui, args: dict[str, Any]) -> ToolResult:
        key = str(args.get("keys", "")).strip().lower()
        if not key:
            return ToolResult(ok=False, summary="No key provided for press action.", data={}, error="missing_keys")
        if key not in VALID_KEYS:
            return ToolResult(ok=False, summary=f"Unknown key: {key}", data={}, error="invalid_key")
        try:
            pyautogui.press(key)
            return ToolResult(ok=True, summary=f"Pressed: {key}", data={"action": "press", "key": key})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Press failed.", data={}, error=str(exc))

    def _do_key_hold(self, pyautogui, args: dict[str, Any], down: bool) -> ToolResult:
        key = str(args.get("keys", "")).strip().lower()
        if key not in VALID_KEYS:
            return ToolResult(ok=False, summary=f"Unknown key: {key}", data={}, error="invalid_key")
        try:
            if down:
                pyautogui.keyDown(key)
                action_label = f"Holding down: {key}"
            else:
                pyautogui.keyUp(key)
                action_label = f"Released: {key}"
            return ToolResult(ok=True, summary=action_label, data={"action": "key_down" if down else "key_up", "key": key})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Key hold/release failed.", data={}, error=str(exc))

    def _do_sequence(self, pyautogui, args: dict[str, Any]) -> ToolResult:
        steps = args.get("steps", [])
        if not isinstance(steps, list) or not steps:
            return ToolResult(ok=False, summary="No steps provided for sequence.", data={}, error="missing_steps")

        results: list[dict[str, Any]] = []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                results.append({"step": i, "ok": False, "error": "invalid_step_format"})
                continue
            delay = float(step.get("delay", 0))
            if delay > 0:
                time.sleep(delay)
            step_args = {**args, **step}
            step_args.pop("steps", None)
            step_result = self.run(step_args)
            results.append({"step": i, "action": step.get("action"), "ok": step_result.ok, "summary": step_result.summary})
            if not step_result.ok:
                return ToolResult(
                    ok=False,
                    summary=f"Sequence failed at step {i}: {step_result.summary}",
                    data={"steps": results},
                    error=step_result.error,
                )

        return ToolResult(
            ok=True,
            summary=f"Sequence completed: {len(results)} step(s).",
            data={"action": "sequence", "steps": results},
        )

    def render(self, data: dict[str, Any]) -> str:
        action = data.get("action", "keyboard")
        if action == "type":
            preview = data.get("text_preview", "")
            chars = data.get("chars", "?")
            return f"Typed {chars} chars: {preview!r}{'...' if chars > 80 else ''}"
        if action == "hotkey":
            return f"Shortcut: {data.get('keys', '')}"
        if action == "press":
            return f"Key pressed: {data.get('key', '')}"
        if action == "sequence":
            steps = data.get("steps", [])
            lines = [f"Sequence: {len(steps)} step(s) completed"]
            for s in steps:
                status = "✓" if s.get("ok") else "✗"
                lines.append(f"  {status} step {s.get('step', '?')}: {s.get('summary', '')}")
            return "\n".join(lines)
        return data.get("summary", "Keyboard action done.")


class MouseTool(Tool):
    name = "mouse"
    public = False
    description = (
        "Control the mouse: inspect cursor position, click, double-click, move, drag, and scroll. "
        "Useful for direct desktop interaction when keyboard or browser helpers are insufficient."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["position", "click", "double_click", "move", "move_relative", "drag", "scroll"],
                "description": "Mouse action to perform.",
            },
            "x": {"type": "integer", "description": "Target x coordinate."},
            "y": {"type": "integer", "description": "Target y coordinate."},
            "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Mouse button to use."},
            "dx": {"type": "integer", "description": "Relative horizontal movement for action=move_relative."},
            "dy": {"type": "integer", "description": "Relative vertical movement for action=move_relative."},
            "duration": {"type": "number", "description": "Movement duration in seconds for move or drag actions."},
            "scroll_y": {"type": "integer", "description": "Scroll delta for action=scroll."},
            "path": {
                "type": "array",
                "description": "For action=drag: list of [x, y] pairs or {x, y} points.",
                "items": {"type": "object"},
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("button", "left")
        args.setdefault("duration", 0.08)
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        pyautogui, err = _import_pyautogui()
        if err:
            return ToolResult(ok=False, summary=err, data={}, error="missing_dep")

        action = str(args.get("action", "")).strip()
        try:
            if action == "position":
                x, y = pyautogui.position()
                return ToolResult(ok=True, summary=f"Mouse is at ({x}, {y}).", data={"action": action, "x": x, "y": y})
            if action == "click":
                target = self._require_xy(args)
                if isinstance(target, ToolResult):
                    return target
                x, y = target
                pyautogui.click(x, y, button=str(args.get("button", "left")))
                return ToolResult(ok=True, summary="Mouse click complete.", data={"action": action, "x": x, "y": y})
            if action == "double_click":
                target = self._require_xy(args)
                if isinstance(target, ToolResult):
                    return target
                x, y = target
                pyautogui.doubleClick(x, y, button=str(args.get("button", "left")))
                return ToolResult(ok=True, summary="Mouse double-click complete.", data={"action": action, "x": x, "y": y})
            if action == "move":
                target = self._require_xy(args)
                if isinstance(target, ToolResult):
                    return target
                x, y = target
                duration = max(0.0, float(args.get("duration", 0.08)))
                pyautogui.moveTo(x, y, duration=duration)
                return ToolResult(ok=True, summary="Mouse move complete.", data={"action": action, "x": x, "y": y})
            if action == "move_relative":
                dx = int(args.get("dx", 0))
                dy = int(args.get("dy", 0))
                duration = max(0.0, float(args.get("duration", 0.08)))
                current_x, current_y = pyautogui.position()
                pyautogui.moveRel(dx, dy, duration=duration)
                next_x, next_y = pyautogui.position()
                return ToolResult(
                    ok=True,
                    summary="Mouse relative move complete.",
                    data={"action": action, "from_x": current_x, "from_y": current_y, "x": next_x, "y": next_y, "dx": dx, "dy": dy},
                )
            if action == "scroll":
                target = self._require_xy(args)
                if isinstance(target, ToolResult):
                    return target
                x, y = target
                pyautogui.moveTo(x, y)
                pyautogui.scroll(-int(args.get("scroll_y", 0)))
                return ToolResult(ok=True, summary="Mouse scroll complete.", data={"action": action, "x": x, "y": y, "scroll_y": int(args.get("scroll_y", 0))})
            if action == "drag":
                points = self._normalize_drag_path(args.get("path", []))
                if len(points) < 2:
                    return ToolResult(ok=False, summary="Drag requires at least two points.", data={}, error="invalid_path")
                pyautogui.moveTo(points[0][0], points[0][1])
                pyautogui.mouseDown(button=str(args.get("button", "left")))
                for x, y in points[1:]:
                    pyautogui.moveTo(x, y, duration=max(0.0, float(args.get("duration", 0.08))))
                pyautogui.mouseUp(button=str(args.get("button", "left")))
                return ToolResult(ok=True, summary="Mouse drag complete.", data={"action": action, "points": points})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Mouse action failed: {exc}", data={}, error=str(exc))
        return ToolResult(ok=False, summary=f"Unknown mouse action: {action}", data={}, error="unknown_action")

    @staticmethod
    def _require_xy(args: dict[str, Any]) -> tuple[int, int] | ToolResult:
        if args.get("x", None) in (None, "") or args.get("y", None) in (None, ""):
            return ToolResult(ok=False, summary="Mouse action requires both x and y coordinates.", data={}, error="missing_coordinates")
        return int(args.get("x", 0)), int(args.get("y", 0))

    @staticmethod
    def _normalize_drag_path(path: Any) -> list[tuple[int, int]]:
        points: list[tuple[int, int]] = []
        for point in path if isinstance(path, list) else []:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                points.append((int(point[0]), int(point[1])))
            elif isinstance(point, dict) and "x" in point and "y" in point:
                points.append((int(point["x"]), int(point["y"])))
        return points

    def render(self, data: dict[str, Any]) -> str:
        action = data.get("action", "mouse")
        if action == "position":
            return f"Cursor at ({data.get('x', 0)}, {data.get('y', 0)})"
        if action == "move_relative":
            return f"Moved cursor by ({data.get('dx', 0)}, {data.get('dy', 0)}) to ({data.get('x', 0)}, {data.get('y', 0)})"
        if action == "drag":
            return f"Dragged across {len(data.get('points', []))} point(s)."
        if action == "scroll":
            return f"Scrolled at ({data.get('x', 0)}, {data.get('y', 0)}) by {data.get('scroll_y', 0)}."
        return f"{action} at ({data.get('x', 0)}, {data.get('y', 0)})"


# ---------------------------------------------------------------------------
# 2. ClipboardTool
# ---------------------------------------------------------------------------

class ClipboardTool(Tool):
    name = "clipboard"
    public = False
    description = (
        "Read from or write to the system clipboard. "
        "Use to get copied text, paste content into fields, or stage text for pasting."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "write", "clear"],
                "description": "read: get clipboard text. write: set clipboard text. clear: empty the clipboard.",
            },
            "text": {
                "type": "string",
                "description": "Text to put on the clipboard (for action=write).",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "read")).strip()

        # Platform-native fallbacks when pyperclip isn't available
        if action == "read":
            return self._read()
        if action == "write":
            return self._write(str(args.get("text", "")))
        if action == "clear":
            return self._write("")
        return ToolResult(ok=False, summary=f"Unknown clipboard action: {action}", data={}, error="unknown_action")

    def _read(self) -> ToolResult:
        pyperclip, err = _import_pyperclip()
        if pyperclip:
            try:
                text = pyperclip.paste()
                return ToolResult(ok=True, summary=f"Clipboard: {text[:100]}", data={"text": text, "length": len(text)})
            except Exception as exc:  # noqa: BLE001
                pass

        # Platform fallbacks
        try:
            if PLATFORM == "Darwin":
                text = subprocess.check_output(["pbpaste"], text=True)
            elif PLATFORM == "Linux":
                text = subprocess.check_output(["xclip", "-selection", "clipboard", "-o"], text=True)
            elif PLATFORM == "Windows":
                import tkinter as tk
                root = tk.Tk(); root.withdraw()
                text = root.clipboard_get(); root.destroy()
            else:
                return ToolResult(ok=False, summary="Cannot read clipboard on this platform.", data={}, error="unsupported_platform")
            return ToolResult(ok=True, summary=f"Clipboard: {text[:100]}", data={"text": text, "length": len(text)})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Clipboard read failed.", data={}, error=str(exc))

    def _write(self, text: str) -> ToolResult:
        pyperclip, err = _import_pyperclip()
        if pyperclip:
            try:
                pyperclip.copy(text)
                action_label = "Clipboard cleared." if not text else f"Clipboard set ({len(text)} chars)."
                return ToolResult(ok=True, summary=action_label, data={"text_preview": text[:80], "length": len(text)})
            except Exception as exc:  # noqa: BLE001
                pass

        try:
            if PLATFORM == "Darwin":
                proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                proc.communicate(text.encode("utf-8"))
            elif PLATFORM == "Linux":
                proc = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
                proc.communicate(text.encode("utf-8"))
            elif PLATFORM == "Windows":
                import tkinter as tk
                root = tk.Tk(); root.withdraw()
                root.clipboard_clear(); root.clipboard_append(text); root.update(); root.destroy()
            else:
                return ToolResult(ok=False, summary="Cannot write clipboard on this platform.", data={}, error="unsupported_platform")
            label = "Clipboard cleared." if not text else f"Clipboard set ({len(text)} chars)."
            return ToolResult(ok=True, summary=label, data={"text_preview": text[:80], "length": len(text)})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Clipboard write failed.", data={}, error=str(exc))

    def render(self, data: dict[str, Any]) -> str:
        text = data.get("text", "")
        length = data.get("length", len(text))
        preview = data.get("text_preview", text[:80])
        if not text:
            return "Clipboard is empty."
        return f"Clipboard ({length} chars): {preview!r}{'...' if length > 80 else ''}"


# ---------------------------------------------------------------------------
# 3. WindowTool
# ---------------------------------------------------------------------------

class WindowTool(Tool):
    name = "window"
    public = False
    description = (
        "Manage application windows: focus a window by title, list all open windows, "
        "get the active window, or focus, move, resize, center, close, minimize, maximize, and restore windows."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["focus", "list", "active", "minimize", "maximize", "restore", "close", "move", "resize", "center"],
                "description": (
                    "focus: bring a window to front by title substring. "
                    "list: list all open window titles. "
                    "active: get the currently focused window title. "
                    "minimize/maximize/restore/close: change window state by title. "
                    "move/resize/center: adjust window placement on screen."
                ),
            },
            "title": {
                "type": "string",
                "description": "Window title substring to match (for focus/minimize/maximize/restore/close/move/resize/center).",
            },
            "x": {"type": "integer", "description": "Target left position for action=move."},
            "y": {"type": "integer", "description": "Target top position for action=move."},
            "width": {"type": "integer", "description": "Target width for action=resize or optional width for action=center."},
            "height": {"type": "integer", "description": "Target height for action=resize or optional height for action=center."},
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "")).strip()
        title = str(args.get("title", "")).strip()

        dispatch = {
            "focus":    self._focus,
            "list":     self._list,
            "active":   self._active,
            "minimize": self._state_change,
            "maximize": self._state_change,
            "restore":  self._state_change,
            "close":    self._state_change,
            "move":     self._geometry_change,
            "resize":   self._geometry_change,
            "center":   self._geometry_change,
        }
        fn = dispatch.get(action)
        if not fn:
            return ToolResult(ok=False, summary=f"Unknown window action: {action}", data={}, error="unknown_action")
        return fn(action=action, title=title, args=args)

    # ------------------------------------------------------------------
    # Platform dispatch helpers
    # ------------------------------------------------------------------

    def _focus(self, action: str, title: str, args: dict[str, Any] | None = None) -> ToolResult:
        del action, args
        if not title:
            return ToolResult(ok=False, summary="Window title required for focus.", data={}, error="missing_title")

        if PLATFORM == "Windows":
            return self._windows_op("focus", title)
        if PLATFORM == "Linux":
            return self._linux_xdotool("focus", title)
        if PLATFORM == "Darwin":
            return self._macos_applescript("focus", title)
        return ToolResult(ok=False, summary="Unsupported platform.", data={}, error="unsupported_platform")

    def _list(self, action: str, title: str, args: dict[str, Any] | None = None) -> ToolResult:
        del action, title, args
        if PLATFORM == "Windows":
            return self._windows_op("list", "")
        if PLATFORM == "Linux":
            return self._linux_xdotool("list", "")
        if PLATFORM == "Darwin":
            return self._macos_applescript("list", "")
        return ToolResult(ok=False, summary="Unsupported platform.", data={}, error="unsupported_platform")

    def _active(self, action: str, title: str, args: dict[str, Any] | None = None) -> ToolResult:
        del action, title, args
        if PLATFORM == "Windows":
            return self._windows_op("active", "")
        if PLATFORM == "Linux":
            return self._linux_xdotool("active", "")
        if PLATFORM == "Darwin":
            return self._macos_applescript("active", "")
        return ToolResult(ok=False, summary="Unsupported platform.", data={}, error="unsupported_platform")

    def _state_change(self, action: str, title: str, args: dict[str, Any] | None = None) -> ToolResult:
        del args
        if not title:
            return ToolResult(ok=False, summary=f"Window title required for {action}.", data={}, error="missing_title")
        if action == "close" and PLATFORM != "Windows":
            return ToolResult(ok=False, summary="Window close is only implemented on Windows right now.", data={}, error="unsupported_action")
        if PLATFORM == "Windows":
            return self._windows_op(action, title)
        if PLATFORM == "Linux":
            return self._linux_xdotool(action, title)
        if PLATFORM == "Darwin":
            return self._macos_applescript(action, title)
        return ToolResult(ok=False, summary="Unsupported platform.", data={}, error="unsupported_platform")

    def _geometry_change(self, action: str, title: str, args: dict[str, Any] | None = None) -> ToolResult:
        if not title:
            return ToolResult(ok=False, summary=f"Window title required for {action}.", data={}, error="missing_title")
        args = args or {}
        x = args.get("x")
        y = args.get("y")
        width = args.get("width")
        height = args.get("height")
        if action == "move" and (x in (None, "") or y in (None, "")):
            return ToolResult(ok=False, summary="Window move requires x and y.", data={}, error="missing_coordinates")
        if action == "resize" and (width in (None, "") or height in (None, "")):
            return ToolResult(ok=False, summary="Window resize requires width and height.", data={}, error="missing_size")
        if PLATFORM == "Windows":
            return self._windows_op(
                action,
                title,
                x=int(x) if x not in (None, "") else None,
                y=int(y) if y not in (None, "") else None,
                width=int(width) if width not in (None, "") else None,
                height=int(height) if height not in (None, "") else None,
            )
        return ToolResult(ok=False, summary=f"Window {action} is only implemented on Windows right now.", data={}, error="unsupported_action")

    # ------------------------------------------------------------------
    # Windows
    # ------------------------------------------------------------------

    def _windows_op(
        self,
        action: str,
        title: str,
        *,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> ToolResult:
        pygetwindow, err = _import_pygetwindow()
        if action == "active":
            active_title = _windows_active_title_ctypes()
            if active_title and pygetwindow is not None:
                try:
                    win = pygetwindow.getActiveWindow()
                    if win:
                        return ToolResult(
                            ok=True,
                            summary=f"Active: {active_title}",
                            data={"title": active_title, **_window_rect_payload(win)},
                        )
                except Exception:
                    pass
            if active_title:
                return ToolResult(ok=True, summary=f"Active: {active_title}", data={"title": active_title})
        try:
            if action == "list" and pygetwindow is not None:
                raw_windows = [win for win in pygetwindow.getAllWindows() if str(getattr(win, "title", "")).strip()]
                visible = [str(win.title) for win in raw_windows]
                details = [{"title": str(win.title), **_window_rect_payload(win)} for win in raw_windows[:50]]
                return ToolResult(ok=True, summary=f"{len(visible)} windows.", data={"windows": visible, "window_details": details})

            if action == "active" and pygetwindow is not None:
                win = pygetwindow.getActiveWindow()
                t = win.title if win else "none"
                payload = {"title": t}
                if win is not None:
                    payload.update(_window_rect_payload(win))
                return ToolResult(ok=True, summary=f"Active: {t}", data=payload)

            if pygetwindow is not None:
                windows = pygetwindow.getWindowsWithTitle(title)
                if windows:
                    win = windows[0]
                    if action == "focus":
                        win.activate()
                    elif action == "minimize":
                        win.minimize()
                    elif action == "maximize":
                        win.maximize()
                    elif action == "restore":
                        win.restore()
                    elif action == "close":
                        win.close()
                    elif action == "move":
                        win.moveTo(int(x or 0), int(y or 0))
                    elif action == "resize":
                        win.resizeTo(int(width or 0), int(height or 0))
                    elif action == "center":
                        target_width = int(width or getattr(win, "width", 0))
                        target_height = int(height or getattr(win, "height", 0))
                        if width is not None and height is not None:
                            win.resizeTo(target_width, target_height)
                        screen_width, screen_height = _primary_screen_size()
                        left = max(0, int((screen_width - target_width) / 2)) if screen_width else int(getattr(win, "left", 0))
                        top = max(0, int((screen_height - target_height) / 2)) if screen_height else int(getattr(win, "top", 0))
                        win.moveTo(left, top)
                    label = {
                        "focus": "Focused",
                        "minimize": "Minimized",
                        "maximize": "Maximized",
                        "restore": "Restored",
                        "close": "Closed",
                        "move": "Moved",
                        "resize": "Resized",
                        "center": "Centered",
                    }.get(action, action.title())
                    return ToolResult(
                        ok=True,
                        summary=f"{label} window: {win.title}",
                        data={"title": win.title, "action": action, **_window_rect_payload(win)},
                    )
        except Exception as exc:  # noqa: BLE001
            if action != "focus":
                return ToolResult(ok=False, summary=f"Window operation failed: {exc}", data={}, error=str(exc))

        if action == "focus":
            safe_title = title.replace("'", "''")
            ok, _ = _powershell(
                "$ws = New-Object -ComObject WScript.Shell; "
                f"if ($ws.AppActivate('{safe_title}')) {{ 'focused' }} else {{ exit 1 }}"
            )
            if ok:
                active_title = _windows_active_title_ctypes() or title
                return ToolResult(ok=True, summary=f"Focused window: {active_title}", data={"title": active_title, "action": action})
            return ToolResult(ok=False, summary=f"No window found matching: {title!r}", data={}, error="window_not_found")

        if action == "list":
            ok, output = _powershell(
                "Get-Process | Where-Object { $_.MainWindowTitle } | Select-Object -ExpandProperty MainWindowTitle"
            )
            if ok:
                visible = [line.strip() for line in output.splitlines() if line.strip()]
                return ToolResult(ok=True, summary=f"{len(visible)} windows.", data={"windows": visible, "window_details": []})

        if err:
            return ToolResult(ok=False, summary=err, data={}, error="missing_dep")
        return ToolResult(ok=False, summary=f"No window found matching: {title!r}", data={}, error="window_not_found")

    # ------------------------------------------------------------------
    # Linux (xdotool)
    # ------------------------------------------------------------------

    def _linux_xdotool(self, action: str, title: str) -> ToolResult:
        try:
            if action == "list":
                out = subprocess.check_output(["xdotool", "search", "--name", ".*"], text=True, stderr=subprocess.DEVNULL)
                wids = out.strip().splitlines()
                titles: list[str] = []
                for wid in wids[:200]:
                    try:
                        t = subprocess.check_output(["xdotool", "getwindowname", wid], text=True, stderr=subprocess.DEVNULL).strip()
                        if t:
                            titles.append(t)
                    except Exception:
                        continue
                return ToolResult(ok=True, summary=f"{len(titles)} windows.", data={"windows": titles})

            if action == "active":
                wid = subprocess.check_output(["xdotool", "getactivewindow"], text=True).strip()
                t = subprocess.check_output(["xdotool", "getwindowname", wid], text=True).strip()
                return ToolResult(ok=True, summary=f"Active: {t}", data={"title": t, "wid": wid})

            # Find matching window
            out = subprocess.check_output(["xdotool", "search", "--name", title], text=True, stderr=subprocess.DEVNULL).strip()
            if not out:
                return ToolResult(ok=False, summary=f"No window found matching: {title!r}", data={}, error="window_not_found")
            wid = out.splitlines()[0]
            if action == "focus":
                subprocess.run(["xdotool", "windowactivate", "--sync", wid], check=True)
            elif action == "minimize":
                subprocess.run(["xdotool", "windowminimize", wid], check=True)
            elif action in ("maximize", "restore"):
                subprocess.run(["xdotool", "windowactivate", "--sync", wid], check=True)
            t = subprocess.check_output(["xdotool", "getwindowname", wid], text=True).strip()
            return ToolResult(ok=True, summary=f"{action.title()}d: {t}", data={"title": t, "wid": wid, "action": action})
        except FileNotFoundError:
            return ToolResult(ok=False, summary="xdotool not found. Install: sudo apt install xdotool", data={}, error="missing_dep")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"xdotool failed: {exc}", data={}, error=str(exc))

    # ------------------------------------------------------------------
    # macOS (AppleScript)
    # ------------------------------------------------------------------

    def _macos_applescript(self, action: str, title: str) -> ToolResult:
        try:
            if action == "list":
                script = 'tell application "System Events" to get name of every process whose visible is true'
                out = subprocess.check_output(["osascript", "-e", script], text=True).strip()
                apps = [a.strip() for a in out.split(",") if a.strip()]
                return ToolResult(ok=True, summary=f"{len(apps)} visible apps.", data={"windows": apps})

            if action == "active":
                script = 'tell application "System Events" to get name of first process whose frontmost is true'
                out = subprocess.check_output(["osascript", "-e", script], text=True).strip()
                return ToolResult(ok=True, summary=f"Active: {out}", data={"title": out})

            if action == "focus":
                script = f'tell application "{title}" to activate'
                subprocess.run(["osascript", "-e", script], check=True)
                return ToolResult(ok=True, summary=f"Focused: {title}", data={"title": title, "action": "focus"})

            if action == "minimize":
                script = f'tell application "System Events" to tell process "{title}" to set value of attribute "AXMinimized" of window 1 to true'
                subprocess.run(["osascript", "-e", script], check=True)
                return ToolResult(ok=True, summary=f"Minimized: {title}", data={"title": title, "action": "minimize"})

            return ToolResult(ok=False, summary=f"Action {action!r} not supported on macOS yet.", data={}, error="unsupported_action")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"AppleScript failed: {exc}", data={}, error=str(exc))

    def render(self, data: dict[str, Any]) -> str:
        action = data.get("action", "")
        if "windows" in data:
            windows = data["windows"]
            lines = [f"Open windows ({len(windows)}):"]
            for w in windows[:30]:
                lines.append(f"  - {w}")
            if len(windows) > 30:
                lines.append(f"  ... and {len(windows) - 30} more")
            return "\n".join(lines)
        if "title" in data:
            act = data.get("action", "")
            label = {
                "focus": "Focused",
                "minimize": "Minimized",
                "maximize": "Maximized",
                "restore": "Restored",
                "active": "Active window",
                "close": "Closed",
                "move": "Moved",
                "resize": "Resized",
                "center": "Centered",
            }.get(act, act.title())
            return f"{label}: {data['title']}"
        return data.get("summary", "Window operation done.")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def register_input_tools(registry: ToolRegistry) -> None:
    """
    Register keyboard, clipboard, window, and mouse tools.

    Usage in cli.py:
        from jakata_agent.tools.keyboard import register_input_tools
        register_input_tools(tools)
    """
    registry.register(KeyboardTool())
    registry.register(ClipboardTool())
    registry.register(WindowTool())
    registry.register(MouseTool())
