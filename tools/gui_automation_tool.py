#!/usr/bin/env python3
"""
GUI Automation Tool - Full control over keyboard, mouse, and windows
Like Jarvis - can type, click, move mouse, execute shortcuts, control windows
"""

try:
    import pyautogui
    import time
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


class GUIAutomationTool:
    """Complete GUI automation for Jarvis-like control"""
    
    @staticmethod
    def get_schema():
        """Get tool schema for function calling"""
        return {
            "type": "function",
            "function": {
                "name": "gui_control",
                "description": "Control keyboard, mouse, and windows like Jarvis. Type text, execute shortcuts, click, move mouse, control windows (minimize, maximize, focus). Full GUI automation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "type", "press", "hotkey", "click", "move_mouse", 
                                "screenshot", "get_position", "scroll", "drag",
                                "alert", "confirm", "prompt"
                            ],
                            "description": "Action to perform"
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to type (for 'type' action)"
                        },
                        "key": {
                            "type": "string",
                            "description": "Key to press (for 'press' action). Examples: enter, tab, esc, space, backspace, delete, up, down, left, right, f1-f12"
                        },
                        "keys": {
                            "type": "string",
                            "description": "Comma-separated keys for hotkey (for 'hotkey' action). Examples: 'ctrl,c' or 'alt,tab' or 'win,d'"
                        },
                        "x": {
                            "type": "integer",
                            "description": "X coordinate (for click, move_mouse, drag)"
                        },
                        "y": {
                            "type": "integer",
                            "description": "Y coordinate (for click, move_mouse, drag)"
                        },
                        "button": {
                            "type": "string",
                            "enum": ["left", "right", "middle"],
                            "description": "Mouse button (for click action, default: left)"
                        },
                        "clicks": {
                            "type": "integer",
                            "description": "Number of clicks (default: 1, use 2 for double-click)"
                        },
                        "amount": {
                            "type": "integer",
                            "description": "Scroll amount (for scroll action, positive=up, negative=down)"
                        },
                        "duration": {
                            "type": "number",
                            "description": "Duration in seconds for smooth movements (default: 0.5)"
                        },
                        "interval": {
                            "type": "number",
                            "description": "Interval between keystrokes in seconds (for type action, default: 0.05)"
                        }
                    },
                    "required": ["action"]
                }
            }
        }
    
    @staticmethod
    def execute(arguments: dict) -> str:
        """Execute GUI automation action"""
        if not PYAUTOGUI_AVAILABLE:
            return "Error: pyautogui not installed. Run: pip install pyautogui"
        
        action = arguments.get("action", "")
        
        if not action:
            return "Error: action is required"
        
        try:
            # Safety: Enable fail-safe (move mouse to corner to abort)
            pyautogui.FAILSAFE = True
            
            if action == "type":
                return GUIAutomationTool._type_text(arguments)
            
            elif action == "press":
                return GUIAutomationTool._press_key(arguments)
            
            elif action == "hotkey":
                return GUIAutomationTool._execute_hotkey(arguments)
            
            elif action == "click":
                return GUIAutomationTool._click_mouse(arguments)
            
            elif action == "move_mouse":
                return GUIAutomationTool._move_mouse(arguments)
            
            elif action == "screenshot":
                return GUIAutomationTool._take_screenshot(arguments)
            
            elif action == "get_position":
                return GUIAutomationTool._get_mouse_position()
            
            elif action == "scroll":
                return GUIAutomationTool._scroll(arguments)
            
            elif action == "drag":
                return GUIAutomationTool._drag_mouse(arguments)
            
            elif action == "alert":
                return GUIAutomationTool._show_alert(arguments)
            
            elif action == "confirm":
                return GUIAutomationTool._show_confirm(arguments)
            
            elif action == "prompt":
                return GUIAutomationTool._show_prompt(arguments)
            
            else:
                return f"Error: Unknown action '{action}'"
        
        except Exception as e:
            return f"Error: {str(e)}"
    
    @staticmethod
    def _type_text(args: dict) -> str:
        """Type text"""
        text = args.get("text", "")
        interval = args.get("interval", 0.05)
        
        if not text:
            return "Error: text is required for type action"
        
        pyautogui.write(text, interval=interval)
        return f"✓ Typed: {text[:50]}{'...' if len(text) > 50 else ''}"
    
    @staticmethod
    def _press_key(args: dict) -> str:
        """Press a key"""
        key = args.get("key", "")
        
        if not key:
            return "Error: key is required for press action"
        
        pyautogui.press(key)
        return f"✓ Pressed key: {key}"
    
    @staticmethod
    def _execute_hotkey(args: dict) -> str:
        """Execute keyboard shortcut"""
        keys_str = args.get("keys", "")
        
        if not keys_str:
            return "Error: keys is required for hotkey action (comma-separated, e.g., 'ctrl,c')"
        
        keys = [k.strip() for k in keys_str.split(',')]
        pyautogui.hotkey(*keys)
        return f"✓ Executed hotkey: {' + '.join(keys)}"
    
    @staticmethod
    def _click_mouse(args: dict) -> str:
        """Click mouse"""
        x = args.get("x")
        y = args.get("y")
        button = args.get("button", "left")
        clicks = args.get("clicks", 1)
        
        if x is not None and y is not None:
            pyautogui.click(x, y, clicks=clicks, button=button)
            return f"✓ Clicked {button} button {clicks}x at ({x}, {y})"
        else:
            pyautogui.click(clicks=clicks, button=button)
            return f"✓ Clicked {button} button {clicks}x at current position"
    
    @staticmethod
    def _move_mouse(args: dict) -> str:
        """Move mouse"""
        x = args.get("x")
        y = args.get("y")
        duration = args.get("duration", 0.5)
        
        if x is None or y is None:
            return "Error: x and y coordinates are required for move_mouse action"
        
        pyautogui.moveTo(x, y, duration=duration)
        return f"✓ Moved mouse to ({x}, {y})"
    
    @staticmethod
    def _take_screenshot(args: dict) -> str:
        """Take screenshot"""
        filename = args.get("text", "screenshot.png")
        
        screenshot = pyautogui.screenshot()
        screenshot.save(filename)
        return f"✓ Screenshot saved: {filename}"
    
    @staticmethod
    def _get_mouse_position() -> str:
        """Get current mouse position"""
        x, y = pyautogui.position()
        return f"Mouse position: ({x}, {y})"
    
    @staticmethod
    def _scroll(args: dict) -> str:
        """Scroll"""
        amount = args.get("amount", 0)
        
        if amount == 0:
            return "Error: amount is required for scroll action (positive=up, negative=down)"
        
        pyautogui.scroll(amount)
        direction = "up" if amount > 0 else "down"
        return f"✓ Scrolled {direction} by {abs(amount)}"
    
    @staticmethod
    def _drag_mouse(args: dict) -> str:
        """Drag mouse"""
        x = args.get("x")
        y = args.get("y")
        duration = args.get("duration", 0.5)
        button = args.get("button", "left")
        
        if x is None or y is None:
            return "Error: x and y coordinates are required for drag action"
        
        pyautogui.drag(x, y, duration=duration, button=button)
        return f"✓ Dragged mouse to ({x}, {y})"
    
    @staticmethod
    def _show_alert(args: dict) -> str:
        """Show alert dialog"""
        text = args.get("text", "Alert")
        
        pyautogui.alert(text)
        return f"✓ Showed alert: {text}"
    
    @staticmethod
    def _show_confirm(args: dict) -> str:
        """Show confirmation dialog"""
        text = args.get("text", "Confirm?")
        
        result = pyautogui.confirm(text)
        return f"User clicked: {result}"
    
    @staticmethod
    def _show_prompt(args: dict) -> str:
        """Show input prompt"""
        text = args.get("text", "Enter value:")
        
        result = pyautogui.prompt(text)
        if result:
            return f"User entered: {result}"
        else:
            return "User cancelled"
