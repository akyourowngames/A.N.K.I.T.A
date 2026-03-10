#!/usr/bin/env python3
"""
GUI Automation Tool - broader keyboard, mouse, screenshot, and image-based control.
"""

import time
from pathlib import Path
from typing import Optional, Tuple

try:
    import pyautogui

    PYAUTOGUI_AVAILABLE = True
except ImportError:
    pyautogui = None
    PYAUTOGUI_AVAILABLE = False

try:
    import pyperclip

    PYPERCLIP_AVAILABLE = True
except ImportError:
    pyperclip = None
    PYPERCLIP_AVAILABLE = False


class GUIAutomationTool:
    """Expanded GUI automation for autonomous desktop interaction."""

    @staticmethod
    def get_schema():
        """Get tool schema for function calling."""
        return {
            "type": "function",
            "function": {
                "name": "gui_control",
                "description": (
                    "Advanced desktop automation for keyboard, mouse, screenshots, waits, "
                    "and image-based actions. Use this when ANKITA needs to interact with "
                    "the visible desktop."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "type",
                                "paste",
                                "press",
                                "hotkey",
                                "key_down",
                                "key_up",
                                "click",
                                "double_click",
                                "mouse_down",
                                "mouse_up",
                                "move_mouse",
                                "move_relative",
                                "screenshot",
                                "get_position",
                                "get_screen_size",
                                "scroll",
                                "drag",
                                "drag_relative",
                                "locate_on_screen",
                                "wait_for_image",
                                "click_image",
                                "alert",
                                "confirm",
                                "prompt",
                                "sleep",
                            ],
                            "description": "Action to perform",
                        },
                        "text": {
                            "type": "string",
                            "description": "Text used for typing, paste, alert, confirm, or prompt",
                        },
                        "path": {
                            "type": "string",
                            "description": "Path to an image or screenshot file",
                        },
                        "key": {
                            "type": "string",
                            "description": "Single key to press or hold",
                        },
                        "keys": {
                            "type": "string",
                            "description": "Comma-separated keys for hotkey actions",
                        },
                        "x": {
                            "type": "integer",
                            "description": "X coordinate for position-based actions",
                        },
                        "y": {
                            "type": "integer",
                            "description": "Y coordinate for position-based actions",
                        },
                        "width": {
                            "type": "integer",
                            "description": "Width for screenshot regions",
                        },
                        "height": {
                            "type": "integer",
                            "description": "Height for screenshot regions",
                        },
                        "button": {
                            "type": "string",
                            "enum": ["left", "right", "middle"],
                            "description": "Mouse button to use",
                        },
                        "clicks": {
                            "type": "integer",
                            "description": "Number of clicks for click actions",
                        },
                        "amount": {
                            "type": "integer",
                            "description": "Scroll amount. Positive is up, negative is down.",
                        },
                        "duration": {
                            "type": "number",
                            "description": "Duration in seconds for movement, drag, or sleep actions",
                        },
                        "interval": {
                            "type": "number",
                            "description": "Interval between keystrokes",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Image match confidence for locate actions when supported",
                        },
                        "grayscale": {
                            "type": "boolean",
                            "description": "Use grayscale matching for image actions",
                        },
                        "timeout_sec": {
                            "type": "number",
                            "description": "How long to wait for wait_for_image",
                        },
                        "use_clipboard": {
                            "type": "boolean",
                            "description": "Use clipboard paste instead of typing text character by character",
                        },
                        "clear_first": {
                            "type": "boolean",
                            "description": "Select all and delete before typing or pasting",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    @staticmethod
    def execute(arguments: dict) -> str:
        """Execute GUI automation action."""
        if not PYAUTOGUI_AVAILABLE:
            return "Error: pyautogui not installed. Run: pip install pyautogui"

        action = arguments.get("action", "")
        if not action:
            return "Error: action is required"

        pyautogui.FAILSAFE = True

        handlers = {
            "type": GUIAutomationTool._type_text,
            "paste": GUIAutomationTool._paste_text,
            "press": GUIAutomationTool._press_key,
            "hotkey": GUIAutomationTool._execute_hotkey,
            "key_down": GUIAutomationTool._key_down,
            "key_up": GUIAutomationTool._key_up,
            "click": GUIAutomationTool._click_mouse,
            "double_click": GUIAutomationTool._double_click,
            "mouse_down": GUIAutomationTool._mouse_down,
            "mouse_up": GUIAutomationTool._mouse_up,
            "move_mouse": GUIAutomationTool._move_mouse,
            "move_relative": GUIAutomationTool._move_relative,
            "screenshot": GUIAutomationTool._take_screenshot,
            "get_position": GUIAutomationTool._get_mouse_position,
            "get_screen_size": GUIAutomationTool._get_screen_size,
            "scroll": GUIAutomationTool._scroll,
            "drag": GUIAutomationTool._drag_mouse,
            "drag_relative": GUIAutomationTool._drag_relative,
            "locate_on_screen": GUIAutomationTool._locate_on_screen,
            "wait_for_image": GUIAutomationTool._wait_for_image,
            "click_image": GUIAutomationTool._click_image,
            "alert": GUIAutomationTool._show_alert,
            "confirm": GUIAutomationTool._show_confirm,
            "prompt": GUIAutomationTool._show_prompt,
            "sleep": GUIAutomationTool._sleep,
        }

        handler = handlers.get(action)
        if handler is None:
            return f"Error: Unknown action '{action}'"

        try:
            return handler(arguments)
        except Exception as exc:
            return f"Error: {exc}"

    @staticmethod
    def _region_from_args(args: dict) -> Optional[Tuple[int, int, int, int]]:
        x = args.get("x")
        y = args.get("y")
        width = args.get("width")
        height = args.get("height")
        if None in (x, y, width, height):
            return None
        return int(x), int(y), int(width), int(height)

    @staticmethod
    def _prepare_path(args: dict, default_name: str) -> Path:
        raw_path = (args.get("path") or args.get("text") or default_name).strip()
        output_path = Path(raw_path)
        if output_path.parent and str(output_path.parent) not in {"", "."}:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

    @staticmethod
    def _clear_current_field() -> None:
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")

    @staticmethod
    def _type_text(args: dict) -> str:
        text = args.get("text", "")
        interval = float(args.get("interval", 0.03))
        use_clipboard = bool(args.get("use_clipboard", False))
        clear_first = bool(args.get("clear_first", False))

        if not text:
            return "Error: text is required for type action"

        if clear_first:
            GUIAutomationTool._clear_current_field()

        if use_clipboard:
            if not PYPERCLIP_AVAILABLE:
                return "Error: pyperclip not installed. Run: pip install pyperclip"
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        else:
            pyautogui.write(text, interval=interval)

        return f"OK: Entered text ({len(text)} chars)"

    @staticmethod
    def _paste_text(args: dict) -> str:
        text = args.get("text", "")
        clear_first = bool(args.get("clear_first", False))

        if text and not PYPERCLIP_AVAILABLE:
            return "Error: pyperclip not installed. Run: pip install pyperclip"

        if clear_first:
            GUIAutomationTool._clear_current_field()

        if text:
            pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        return "OK: Pasted clipboard content"

    @staticmethod
    def _press_key(args: dict) -> str:
        key = args.get("key", "")
        presses = int(args.get("clicks", 1))
        if not key:
            return "Error: key is required for press action"
        pyautogui.press(key, presses=presses, interval=float(args.get("interval", 0.0)))
        return f"OK: Pressed key '{key}' {presses} time(s)"

    @staticmethod
    def _execute_hotkey(args: dict) -> str:
        keys_str = args.get("keys", "")
        if not keys_str:
            return "Error: keys is required for hotkey action"
        keys = [key.strip() for key in keys_str.split(",") if key.strip()]
        if not keys:
            return "Error: No valid keys provided"
        pyautogui.hotkey(*keys)
        return f"OK: Executed hotkey {' + '.join(keys)}"

    @staticmethod
    def _key_down(args: dict) -> str:
        key = args.get("key", "")
        if not key:
            return "Error: key is required for key_down action"
        pyautogui.keyDown(key)
        return f"OK: Held key '{key}' down"

    @staticmethod
    def _key_up(args: dict) -> str:
        key = args.get("key", "")
        if not key:
            return "Error: key is required for key_up action"
        pyautogui.keyUp(key)
        return f"OK: Released key '{key}'"

    @staticmethod
    def _click_mouse(args: dict) -> str:
        x = args.get("x")
        y = args.get("y")
        button = args.get("button", "left")
        clicks = int(args.get("clicks", 1))
        duration = float(args.get("duration", 0.0))

        if x is not None and y is not None:
            pyautogui.click(int(x), int(y), clicks=clicks, button=button, duration=duration)
            return f"OK: Clicked {button} at ({x}, {y}) {clicks} time(s)"

        pyautogui.click(clicks=clicks, button=button, duration=duration)
        return f"OK: Clicked {button} at current position {clicks} time(s)"

    @staticmethod
    def _double_click(args: dict) -> str:
        updated_args = dict(args)
        updated_args["clicks"] = 2
        return GUIAutomationTool._click_mouse(updated_args)

    @staticmethod
    def _mouse_down(args: dict) -> str:
        button = args.get("button", "left")
        x = args.get("x")
        y = args.get("y")
        if x is not None and y is not None:
            pyautogui.mouseDown(int(x), int(y), button=button)
            return f"OK: Mouse down {button} at ({x}, {y})"
        pyautogui.mouseDown(button=button)
        return f"OK: Mouse down {button} at current position"

    @staticmethod
    def _mouse_up(args: dict) -> str:
        button = args.get("button", "left")
        x = args.get("x")
        y = args.get("y")
        if x is not None and y is not None:
            pyautogui.mouseUp(int(x), int(y), button=button)
            return f"OK: Mouse up {button} at ({x}, {y})"
        pyautogui.mouseUp(button=button)
        return f"OK: Mouse up {button} at current position"

    @staticmethod
    def _move_mouse(args: dict) -> str:
        x = args.get("x")
        y = args.get("y")
        if x is None or y is None:
            return "Error: x and y are required for move_mouse"
        duration = float(args.get("duration", 0.3))
        pyautogui.moveTo(int(x), int(y), duration=duration)
        return f"OK: Moved mouse to ({x}, {y})"

    @staticmethod
    def _move_relative(args: dict) -> str:
        x = args.get("x", 0)
        y = args.get("y", 0)
        duration = float(args.get("duration", 0.3))
        pyautogui.moveRel(int(x), int(y), duration=duration)
        pos_x, pos_y = pyautogui.position()
        return f"OK: Moved mouse relatively by ({x}, {y}); current position is ({pos_x}, {pos_y})"

    @staticmethod
    def _take_screenshot(args: dict) -> str:
        output_path = GUIAutomationTool._prepare_path(args, "screenshot.png")
        region = GUIAutomationTool._region_from_args(args)
        screenshot = pyautogui.screenshot(region=region)
        screenshot.save(output_path)
        if region:
            return f"OK: Saved region screenshot to {output_path}"
        return f"OK: Saved screenshot to {output_path}"

    @staticmethod
    def _get_mouse_position(args: dict) -> str:
        x, y = pyautogui.position()
        return f"Mouse position: ({x}, {y})"

    @staticmethod
    def _get_screen_size(args: dict) -> str:
        width, height = pyautogui.size()
        return f"Screen size: {width}x{height}"

    @staticmethod
    def _scroll(args: dict) -> str:
        amount = args.get("amount")
        if amount is None:
            return "Error: amount is required for scroll"
        x = args.get("x")
        y = args.get("y")
        if x is not None and y is not None:
            pyautogui.scroll(int(amount), x=int(x), y=int(y))
        else:
            pyautogui.scroll(int(amount))
        direction = "up" if int(amount) > 0 else "down"
        return f"OK: Scrolled {direction} by {abs(int(amount))}"

    @staticmethod
    def _drag_mouse(args: dict) -> str:
        x = args.get("x")
        y = args.get("y")
        if x is None or y is None:
            return "Error: x and y are required for drag"
        duration = float(args.get("duration", 0.5))
        button = args.get("button", "left")
        pyautogui.dragTo(int(x), int(y), duration=duration, button=button)
        return f"OK: Dragged mouse to ({x}, {y})"

    @staticmethod
    def _drag_relative(args: dict) -> str:
        x = args.get("x", 0)
        y = args.get("y", 0)
        duration = float(args.get("duration", 0.5))
        button = args.get("button", "left")
        pyautogui.dragRel(int(x), int(y), duration=duration, button=button)
        pos_x, pos_y = pyautogui.position()
        return f"OK: Dragged relatively by ({x}, {y}); current position is ({pos_x}, {pos_y})"

    @staticmethod
    def _image_search_kwargs(args: dict) -> dict:
        kwargs = {
            "grayscale": bool(args.get("grayscale", False)),
        }
        region = GUIAutomationTool._region_from_args(args)
        if region:
            kwargs["region"] = region
        confidence = args.get("confidence")
        if confidence is not None:
            kwargs["confidence"] = float(confidence)
        return kwargs

    @staticmethod
    def _locate_image(args: dict):
        image_path = args.get("path")
        if not image_path:
            return None, "Error: path is required for image actions"
        resolved = Path(image_path)
        if not resolved.exists():
            return None, f"Error: image not found: {resolved}"
        location = pyautogui.locateOnScreen(str(resolved), **GUIAutomationTool._image_search_kwargs(args))
        return location, None

    @staticmethod
    def _locate_on_screen(args: dict) -> str:
        location, error = GUIAutomationTool._locate_image(args)
        if error:
            return error
        if location is None:
            return "No matching image found on screen"
        center = pyautogui.center(location)
        return (
            f"Found image at left={location.left}, top={location.top}, "
            f"width={location.width}, height={location.height}, center=({center.x}, {center.y})"
        )

    @staticmethod
    def _wait_for_image(args: dict) -> str:
        timeout_sec = float(args.get("timeout_sec", 10))
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            location, error = GUIAutomationTool._locate_image(args)
            if error:
                return error
            if location is not None:
                center = pyautogui.center(location)
                return f"Found image at center ({center.x}, {center.y})"
            time.sleep(0.3)
        return f"Timeout: image not found within {timeout_sec:.1f}s"

    @staticmethod
    def _click_image(args: dict) -> str:
        timeout_sec = float(args.get("timeout_sec", 5))
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            location, error = GUIAutomationTool._locate_image(args)
            if error:
                return error
            if location is not None:
                center = pyautogui.center(location)
                button = args.get("button", "left")
                clicks = int(args.get("clicks", 1))
                pyautogui.click(center.x, center.y, clicks=clicks, button=button)
                return f"OK: Clicked image center at ({center.x}, {center.y})"
            time.sleep(0.3)
        return f"Timeout: image not found within {timeout_sec:.1f}s"

    @staticmethod
    def _show_alert(args: dict) -> str:
        text = args.get("text", "Alert")
        pyautogui.alert(text)
        return f"OK: Displayed alert: {text}"

    @staticmethod
    def _show_confirm(args: dict) -> str:
        text = args.get("text", "Confirm?")
        result = pyautogui.confirm(text)
        return f"User clicked: {result}"

    @staticmethod
    def _show_prompt(args: dict) -> str:
        text = args.get("text", "Enter value:")
        result = pyautogui.prompt(text)
        if result:
            return f"User entered: {result}"
        return "User cancelled"

    @staticmethod
    def _sleep(args: dict) -> str:
        seconds = float(args.get("duration", args.get("timeout_sec", 1)))
        time.sleep(seconds)
        return f"OK: Slept for {seconds:.2f}s"
