#!/usr/bin/env python3
"""
Window Management & Clipboard Tool - God-tier window control and clipboard operations
Accurate, reliable, and Windows-optimized
"""

import subprocess
import json
import time
from typing import List, Dict, Optional

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False

try:
    import pygetwindow as gw
    PYGETWINDOW_AVAILABLE = True
except ImportError:
    PYGETWINDOW_AVAILABLE = False


class WindowClipboardTool:
    """God-tier window management and clipboard operations"""
    
    @staticmethod
    def get_schema():
        """Get tool schema for function calling"""
        return {
            "type": "function",
            "function": {
                "name": "window_clipboard",
                "description": "God-tier window management and clipboard operations. List windows, switch to app by name, get active window, minimize/maximize/close windows, read/write clipboard.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "list_windows", "find_window", "switch_to_window",
                                "get_active_window", "minimize_window", "maximize_window",
                                "restore_window", "close_window", "move_window", "resize_window",
                                "clipboard_read", "clipboard_write", "clipboard_clear"
                            ],
                            "description": "Action to perform"
                        },
                        "title": {
                            "type": "string",
                            "description": "Window title or partial title to search for (case-insensitive)"
                        },
                        "process": {
                            "type": "string",
                            "description": "Process name to search for (e.g., 'notepad', 'chrome', 'code')"
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to write to clipboard (for clipboard_write)"
                        },
                        "x": {
                            "type": "integer",
                            "description": "X coordinate for window position (for move_window)"
                        },
                        "y": {
                            "type": "integer",
                            "description": "Y coordinate for window position (for move_window)"
                        },
                        "width": {
                            "type": "integer",
                            "description": "Window width (for resize_window)"
                        },
                        "height": {
                            "type": "integer",
                            "description": "Window height (for resize_window)"
                        }
                    },
                    "required": ["action"]
                }
            }
        }
    
    @staticmethod
    def execute(arguments: dict) -> str:
        """Execute window/clipboard action"""
        action = arguments.get("action", "")
        
        if not action:
            return "Error: action is required"
        
        try:
            # Clipboard actions
            if action == "clipboard_read":
                return WindowClipboardTool._clipboard_read()
            
            elif action == "clipboard_write":
                return WindowClipboardTool._clipboard_write(arguments)
            
            elif action == "clipboard_clear":
                return WindowClipboardTool._clipboard_clear()
            
            # Window actions
            elif action == "list_windows":
                return WindowClipboardTool._list_windows()
            
            elif action == "find_window":
                return WindowClipboardTool._find_window(arguments)
            
            elif action == "switch_to_window":
                return WindowClipboardTool._switch_to_window(arguments)
            
            elif action == "get_active_window":
                return WindowClipboardTool._get_active_window()
            
            elif action == "minimize_window":
                return WindowClipboardTool._minimize_window(arguments)
            
            elif action == "maximize_window":
                return WindowClipboardTool._maximize_window(arguments)
            
            elif action == "restore_window":
                return WindowClipboardTool._restore_window(arguments)
            
            elif action == "close_window":
                return WindowClipboardTool._close_window(arguments)
            
            elif action == "move_window":
                return WindowClipboardTool._move_window(arguments)
            
            elif action == "resize_window":
                return WindowClipboardTool._resize_window(arguments)
            
            else:
                return f"Error: Unknown action '{action}'"
        
        except Exception as e:
            return f"Error: {str(e)}"
    
    # ==================== CLIPBOARD OPERATIONS ====================
    
    @staticmethod
    def _clipboard_read() -> str:
        """Read text from clipboard"""
        if not PYPERCLIP_AVAILABLE:
            return "Error: pyperclip not installed. Run: pip install pyperclip"
        
        try:
            content = pyperclip.paste()
            if content:
                preview = content[:200] + "..." if len(content) > 200 else content
                return f"Clipboard content ({len(content)} chars):\n{preview}"
            else:
                return "Clipboard is empty"
        except Exception as e:
            return f"Error reading clipboard: {str(e)}"
    
    @staticmethod
    def _clipboard_write(args: dict) -> str:
        """Write text to clipboard"""
        if not PYPERCLIP_AVAILABLE:
            return "Error: pyperclip not installed. Run: pip install pyperclip"
        
        text = args.get("text", "")
        if not text:
            return "Error: text is required for clipboard_write"
        
        try:
            pyperclip.copy(text)
            preview = text[:100] + "..." if len(text) > 100 else text
            return f"✓ Copied to clipboard ({len(text)} chars): {preview}"
        except Exception as e:
            return f"Error writing to clipboard: {str(e)}"
    
    @staticmethod
    def _clipboard_clear() -> str:
        """Clear clipboard"""
        if not PYPERCLIP_AVAILABLE:
            return "Error: pyperclip not installed. Run: pip install pyperclip"
        
        try:
            pyperclip.copy("")
            return "✓ Clipboard cleared"
        except Exception as e:
            return f"Error clearing clipboard: {str(e)}"
    
    # ==================== WINDOW OPERATIONS ====================
    
    @staticmethod
    def _list_windows() -> str:
        """List all visible windows"""
        if not PYGETWINDOW_AVAILABLE:
            return "Error: pygetwindow not installed. Run: pip install pygetwindow"
        
        try:
            windows = gw.getAllWindows()
            visible_windows = [w for w in windows if w.title and w.visible]
            
            if not visible_windows:
                return "No visible windows found"
            
            result = [f"Found {len(visible_windows)} visible windows:\n"]
            for i, win in enumerate(visible_windows[:20], 1):  # Limit to 20
                status = []
                if win.isMinimized:
                    status.append("minimized")
                if win.isMaximized:
                    status.append("maximized")
                if win.isActive:
                    status.append("ACTIVE")
                
                status_str = f" [{', '.join(status)}]" if status else ""
                result.append(f"{i}. {win.title}{status_str}")
            
            if len(visible_windows) > 20:
                result.append(f"\n... and {len(visible_windows) - 20} more")
            
            return "\n".join(result)
        
        except Exception as e:
            return f"Error listing windows: {str(e)}"
    
    @staticmethod
    def _find_window(args: dict) -> str:
        """Find window by title or process name"""
        if not PYGETWINDOW_AVAILABLE:
            return "Error: pygetwindow not installed. Run: pip install pygetwindow"
        
        title = args.get("title", "").lower()
        process = args.get("process", "").lower()
        
        if not title and not process:
            return "Error: Either 'title' or 'process' is required"
        
        try:
            windows = gw.getAllWindows()
            matches = []
            
            for win in windows:
                if not win.title or not win.visible:
                    continue
                
                # Match by title
                if title and title in win.title.lower():
                    matches.append(win)
                    continue
                
                # Match by process (check if process name is in title)
                if process and process in win.title.lower():
                    matches.append(win)
            
            if not matches:
                search_term = title or process
                return f"No windows found matching '{search_term}'"
            
            result = [f"Found {len(matches)} matching window(s):\n"]
            for i, win in enumerate(matches[:10], 1):
                status = []
                if win.isMinimized:
                    status.append("minimized")
                if win.isMaximized:
                    status.append("maximized")
                if win.isActive:
                    status.append("ACTIVE")
                
                status_str = f" [{', '.join(status)}]" if status else ""
                result.append(f"{i}. {win.title}{status_str}")
            
            return "\n".join(result)
        
        except Exception as e:
            return f"Error finding window: {str(e)}"
    
    @staticmethod
    def _switch_to_window(args: dict) -> str:
        """Switch to (activate) a window by title or process"""
        if not PYGETWINDOW_AVAILABLE:
            return "Error: pygetwindow not installed. Run: pip install pygetwindow"
        
        title = args.get("title", "").lower()
        process = args.get("process", "").lower()
        
        if not title and not process:
            return "Error: Either 'title' or 'process' is required"
        
        try:
            windows = gw.getAllWindows()
            target_window = None
            
            # Find matching window
            for win in windows:
                if not win.title or not win.visible:
                    continue
                
                if title and title in win.title.lower():
                    target_window = win
                    break
                
                if process and process in win.title.lower():
                    target_window = win
                    break
            
            if not target_window:
                search_term = title or process
                return f"Error: No window found matching '{search_term}'"
            
            # Restore if minimized
            if target_window.isMinimized:
                target_window.restore()
                time.sleep(0.1)
            
            # Activate window
            target_window.activate()
            time.sleep(0.1)
            
            return f"✓ Switched to window: {target_window.title}"
        
        except Exception as e:
            return f"Error switching to window: {str(e)}"
    
    @staticmethod
    def _get_active_window() -> str:
        """Get currently active window"""
        if not PYGETWINDOW_AVAILABLE:
            return "Error: pygetwindow not installed. Run: pip install pygetwindow"
        
        try:
            active = gw.getActiveWindow()
            if active:
                info = {
                    "title": active.title,
                    "position": f"({active.left}, {active.top})",
                    "size": f"{active.width}x{active.height}",
                    "minimized": active.isMinimized,
                    "maximized": active.isMaximized
                }
                return f"Active window: {active.title}\n" + \
                       f"Position: {info['position']}\n" + \
                       f"Size: {info['size']}\n" + \
                       f"Minimized: {info['minimized']}\n" + \
                       f"Maximized: {info['maximized']}"
            else:
                return "No active window found"
        
        except Exception as e:
            return f"Error getting active window: {str(e)}"
    
    @staticmethod
    def _minimize_window(args: dict) -> str:
        """Minimize a window"""
        if not PYGETWINDOW_AVAILABLE:
            return "Error: pygetwindow not installed. Run: pip install pygetwindow"
        
        title = args.get("title", "").lower()
        process = args.get("process", "").lower()
        
        # If no title/process specified, minimize active window
        if not title and not process:
            try:
                active = gw.getActiveWindow()
                if active:
                    active.minimize()
                    return f"✓ Minimized active window: {active.title}"
                else:
                    return "Error: No active window found"
            except Exception as e:
                return f"Error minimizing active window: {str(e)}"
        
        # Find and minimize specific window
        try:
            windows = gw.getAllWindows()
            target_window = None
            
            for win in windows:
                if not win.title or not win.visible:
                    continue
                
                if title and title in win.title.lower():
                    target_window = win
                    break
                
                if process and process in win.title.lower():
                    target_window = win
                    break
            
            if not target_window:
                search_term = title or process
                return f"Error: No window found matching '{search_term}'"
            
            target_window.minimize()
            return f"✓ Minimized window: {target_window.title}"
        
        except Exception as e:
            return f"Error minimizing window: {str(e)}"
    
    @staticmethod
    def _maximize_window(args: dict) -> str:
        """Maximize a window"""
        if not PYGETWINDOW_AVAILABLE:
            return "Error: pygetwindow not installed. Run: pip install pygetwindow"
        
        title = args.get("title", "").lower()
        process = args.get("process", "").lower()
        
        # If no title/process specified, maximize active window
        if not title and not process:
            try:
                active = gw.getActiveWindow()
                if active:
                    active.maximize()
                    return f"✓ Maximized active window: {active.title}"
                else:
                    return "Error: No active window found"
            except Exception as e:
                return f"Error maximizing active window: {str(e)}"
        
        # Find and maximize specific window
        try:
            windows = gw.getAllWindows()
            target_window = None
            
            for win in windows:
                if not win.title or not win.visible:
                    continue
                
                if title and title in win.title.lower():
                    target_window = win
                    break
                
                if process and process in win.title.lower():
                    target_window = win
                    break
            
            if not target_window:
                search_term = title or process
                return f"Error: No window found matching '{search_term}'"
            
            target_window.maximize()
            return f"✓ Maximized window: {target_window.title}"
        
        except Exception as e:
            return f"Error maximizing window: {str(e)}"
    
    @staticmethod
    def _restore_window(args: dict) -> str:
        """Restore a minimized/maximized window to normal size"""
        if not PYGETWINDOW_AVAILABLE:
            return "Error: pygetwindow not installed. Run: pip install pygetwindow"
        
        title = args.get("title", "").lower()
        process = args.get("process", "").lower()
        
        # If no title/process specified, restore active window
        if not title and not process:
            try:
                active = gw.getActiveWindow()
                if active:
                    active.restore()
                    return f"✓ Restored active window: {active.title}"
                else:
                    return "Error: No active window found"
            except Exception as e:
                return f"Error restoring active window: {str(e)}"
        
        # Find and restore specific window
        try:
            windows = gw.getAllWindows()
            target_window = None
            
            for win in windows:
                if not win.title or not win.visible:
                    continue
                
                if title and title in win.title.lower():
                    target_window = win
                    break
                
                if process and process in win.title.lower():
                    target_window = win
                    break
            
            if not target_window:
                search_term = title or process
                return f"Error: No window found matching '{search_term}'"
            
            target_window.restore()
            return f"✓ Restored window: {target_window.title}"
        
        except Exception as e:
            return f"Error restoring window: {str(e)}"
    
    @staticmethod
    def _close_window(args: dict) -> str:
        """Close a window"""
        if not PYGETWINDOW_AVAILABLE:
            return "Error: pygetwindow not installed. Run: pip install pygetwindow"
        
        title = args.get("title", "").lower()
        process = args.get("process", "").lower()
        
        if not title and not process:
            return "Error: Either 'title' or 'process' is required to close a window"
        
        try:
            windows = gw.getAllWindows()
            target_window = None
            
            for win in windows:
                if not win.title or not win.visible:
                    continue
                
                if title and title in win.title.lower():
                    target_window = win
                    break
                
                if process and process in win.title.lower():
                    target_window = win
                    break
            
            if not target_window:
                search_term = title or process
                return f"Error: No window found matching '{search_term}'"
            
            window_title = target_window.title
            target_window.close()
            return f"✓ Closed window: {window_title}"
        
        except Exception as e:
            return f"Error closing window: {str(e)}"
    
    @staticmethod
    def _move_window(args: dict) -> str:
        """Move a window to specific position"""
        if not PYGETWINDOW_AVAILABLE:
            return "Error: pygetwindow not installed. Run: pip install pygetwindow"
        
        x = args.get("x")
        y = args.get("y")
        title = args.get("title", "").lower()
        process = args.get("process", "").lower()
        
        if x is None or y is None:
            return "Error: Both 'x' and 'y' coordinates are required"
        
        # If no title/process specified, move active window
        if not title and not process:
            try:
                active = gw.getActiveWindow()
                if active:
                    active.moveTo(x, y)
                    return f"✓ Moved active window to ({x}, {y})"
                else:
                    return "Error: No active window found"
            except Exception as e:
                return f"Error moving active window: {str(e)}"
        
        # Find and move specific window
        try:
            windows = gw.getAllWindows()
            target_window = None
            
            for win in windows:
                if not win.title or not win.visible:
                    continue
                
                if title and title in win.title.lower():
                    target_window = win
                    break
                
                if process and process in win.title.lower():
                    target_window = win
                    break
            
            if not target_window:
                search_term = title or process
                return f"Error: No window found matching '{search_term}'"
            
            target_window.moveTo(x, y)
            return f"✓ Moved window '{target_window.title}' to ({x}, {y})"
        
        except Exception as e:
            return f"Error moving window: {str(e)}"
    
    @staticmethod
    def _resize_window(args: dict) -> str:
        """Resize a window"""
        if not PYGETWINDOW_AVAILABLE:
            return "Error: pygetwindow not installed. Run: pip install pygetwindow"
        
        width = args.get("width")
        height = args.get("height")
        title = args.get("title", "").lower()
        process = args.get("process", "").lower()
        
        if width is None or height is None:
            return "Error: Both 'width' and 'height' are required"
        
        # If no title/process specified, resize active window
        if not title and not process:
            try:
                active = gw.getActiveWindow()
                if active:
                    active.resizeTo(width, height)
                    return f"✓ Resized active window to {width}x{height}"
                else:
                    return "Error: No active window found"
            except Exception as e:
                return f"Error resizing active window: {str(e)}"
        
        # Find and resize specific window
        try:
            windows = gw.getAllWindows()
            target_window = None
            
            for win in windows:
                if not win.title or not win.visible:
                    continue
                
                if title and title in win.title.lower():
                    target_window = win
                    break
                
                if process and process in win.title.lower():
                    target_window = win
                    break
            
            if not target_window:
                search_term = title or process
                return f"Error: No window found matching '{search_term}'"
            
            target_window.resizeTo(width, height)
            return f"✓ Resized window '{target_window.title}' to {width}x{height}"
        
        except Exception as e:
            return f"Error resizing window: {str(e)}"
