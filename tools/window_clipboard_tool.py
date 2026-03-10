#!/usr/bin/env python3
"""
Window Management & Clipboard Tool - richer desktop orchestration.
"""

import ctypes
import json
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    import pygetwindow as gw

    PYGETWINDOW_AVAILABLE = True
except ImportError:
    gw = None
    PYGETWINDOW_AVAILABLE = False

try:
    import pyperclip

    PYPERCLIP_AVAILABLE = True
except ImportError:
    pyperclip = None
    PYPERCLIP_AVAILABLE = False


class WindowClipboardTool:
    """Window management and clipboard operations with launch/focus helpers."""

    @staticmethod
    def get_schema():
        """Get tool schema for function calling."""
        return {
            "type": "function",
            "function": {
                "name": "window_clipboard",
                "description": (
                    "Advanced window management, app launch/focus, process inspection, "
                    "layout control, and clipboard operations."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "list_windows",
                                "find_window",
                                "switch_to_window",
                                "focus_or_launch",
                                "launch_app",
                                "get_active_window",
                                "get_window_details",
                                "list_processes",
                                "terminate_process",
                                "minimize_window",
                                "maximize_window",
                                "restore_window",
                                "close_window",
                                "move_window",
                                "resize_window",
                                "arrange_window",
                                "clipboard_read",
                                "clipboard_write",
                                "clipboard_append",
                                "clipboard_clear",
                            ],
                            "description": "Action to perform",
                        },
                        "title": {
                            "type": "string",
                            "description": "Window title or partial title to search for",
                        },
                        "process": {
                            "type": "string",
                            "description": "Process name to search for, such as notepad or chrome",
                        },
                        "pid": {
                            "type": "integer",
                            "description": "Specific process id to target",
                        },
                        "text": {
                            "type": "string",
                            "description": "Clipboard text",
                        },
                        "command": {
                            "type": "string",
                            "description": "Command to launch an application",
                        },
                        "working_directory": {
                            "type": "string",
                            "description": "Working directory for launch_app",
                        },
                        "x": {
                            "type": "integer",
                            "description": "Target x position for window movement",
                        },
                        "y": {
                            "type": "integer",
                            "description": "Target y position for window movement",
                        },
                        "width": {
                            "type": "integer",
                            "description": "Target window width",
                        },
                        "height": {
                            "type": "integer",
                            "description": "Target window height",
                        },
                        "preset": {
                            "type": "string",
                            "enum": [
                                "left",
                                "right",
                                "top",
                                "bottom",
                                "center",
                                "fullscreen",
                                "top_left",
                                "top_right",
                                "bottom_left",
                                "bottom_right",
                            ],
                            "description": "Preset layout for arrange_window",
                        },
                        "timeout_sec": {
                            "type": "number",
                            "description": "How long to wait when focusing or launching",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    @staticmethod
    def execute(arguments: dict) -> str:
        """Execute window/clipboard action."""
        action = arguments.get("action", "")
        if not action:
            return "Error: action is required"

        handlers = {
            "clipboard_read": WindowClipboardTool._clipboard_read,
            "clipboard_write": WindowClipboardTool._clipboard_write,
            "clipboard_append": WindowClipboardTool._clipboard_append,
            "clipboard_clear": WindowClipboardTool._clipboard_clear,
            "list_windows": WindowClipboardTool._list_windows,
            "find_window": WindowClipboardTool._find_window,
            "switch_to_window": WindowClipboardTool._switch_to_window,
            "focus_or_launch": WindowClipboardTool._focus_or_launch,
            "launch_app": WindowClipboardTool._launch_app,
            "get_active_window": WindowClipboardTool._get_active_window,
            "get_window_details": WindowClipboardTool._get_window_details,
            "list_processes": WindowClipboardTool._list_processes,
            "terminate_process": WindowClipboardTool._terminate_process,
            "minimize_window": WindowClipboardTool._minimize_window,
            "maximize_window": WindowClipboardTool._maximize_window,
            "restore_window": WindowClipboardTool._restore_window,
            "close_window": WindowClipboardTool._close_window,
            "move_window": WindowClipboardTool._move_window,
            "resize_window": WindowClipboardTool._resize_window,
            "arrange_window": WindowClipboardTool._arrange_window,
        }

        handler = handlers.get(action)
        if handler is None:
            return f"Error: Unknown action '{action}'"

        try:
            return handler(arguments)
        except Exception as exc:
            return f"Error: {exc}"

    @staticmethod
    def _run_powershell(script: str) -> str:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "").strip() or "PowerShell command failed")
        return (result.stdout or "").strip()

    @staticmethod
    def _get_process_window_records() -> List[Dict]:
        output = WindowClipboardTool._run_powershell(
            (
                "Get-Process | Where-Object { $_.MainWindowTitle -and $_.MainWindowTitle.Trim() -ne '' } | "
                "Select-Object Id,ProcessName,MainWindowTitle,Path | ConvertTo-Json -Compress"
            )
        )
        if not output:
            return []
        data = json.loads(output)
        if isinstance(data, dict):
            return [data]
        return data

    @staticmethod
    def _screen_size() -> tuple[int, int]:
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    @staticmethod
    def _build_window_records(visible_only: bool = True) -> List[Dict]:
        if not PYGETWINDOW_AVAILABLE:
            raise RuntimeError("pygetwindow not installed. Run: pip install pygetwindow")

        process_records = WindowClipboardTool._get_process_window_records()
        records: List[Dict] = []

        for win in gw.getAllWindows():
            title = (win.title or "").strip()
            if not title:
                continue
            if visible_only and not win.visible:
                continue

            process_name = None
            pid = None
            window_path = None
            lowered_title = title.lower()

            for proc in process_records:
                proc_title = str(proc.get("MainWindowTitle") or "").strip()
                if not proc_title:
                    continue
                proc_lower = proc_title.lower()
                if lowered_title == proc_lower or lowered_title in proc_lower or proc_lower in lowered_title:
                    process_name = proc.get("ProcessName")
                    pid = proc.get("Id")
                    window_path = proc.get("Path")
                    break

            records.append(
                {
                    "window": win,
                    "title": title,
                    "process": process_name,
                    "pid": pid,
                    "path": window_path,
                    "visible": bool(win.visible),
                    "minimized": bool(win.isMinimized),
                    "maximized": bool(win.isMaximized),
                    "active": bool(win.isActive),
                    "left": int(win.left),
                    "top": int(win.top),
                    "width": int(win.width),
                    "height": int(win.height),
                }
            )

        return records

    @staticmethod
    def _match_record(arguments: dict, active_fallback: bool = False) -> Optional[Dict]:
        title = str(arguments.get("title", "") or "").lower()
        process = str(arguments.get("process", "") or "").lower()
        pid = arguments.get("pid")

        records = WindowClipboardTool._build_window_records(visible_only=True)
        if not title and not process and pid is None:
            if active_fallback:
                for record in records:
                    if record["active"]:
                        return record
            return None

        for record in records:
            if pid is not None and record.get("pid") == pid:
                return record
            if title and title in record["title"].lower():
                return record
            if process and record.get("process") and process in str(record["process"]).lower():
                return record

        return None

    @staticmethod
    def _format_record(record: Dict) -> str:
        details = [
            f"title={record['title']}",
            f"process={record.get('process') or 'unknown'}",
            f"pid={record.get('pid') or 'unknown'}",
            f"position=({record['left']}, {record['top']})",
            f"size={record['width']}x{record['height']}",
            f"minimized={record['minimized']}",
            f"maximized={record['maximized']}",
            f"active={record['active']}",
        ]
        return ", ".join(details)

    @staticmethod
    def _clipboard_read(arguments: dict) -> str:
        if not PYPERCLIP_AVAILABLE:
            return "Error: pyperclip not installed. Run: pip install pyperclip"
        content = pyperclip.paste()
        if not content:
            return "Clipboard is empty"
        preview = content[:300] + ("..." if len(content) > 300 else "")
        return f"Clipboard content ({len(content)} chars):\n{preview}"

    @staticmethod
    def _clipboard_write(arguments: dict) -> str:
        if not PYPERCLIP_AVAILABLE:
            return "Error: pyperclip not installed. Run: pip install pyperclip"
        text = arguments.get("text", "")
        if not text:
            return "Error: text is required for clipboard_write"
        pyperclip.copy(text)
        return f"OK: Copied {len(text)} chars to clipboard"

    @staticmethod
    def _clipboard_append(arguments: dict) -> str:
        if not PYPERCLIP_AVAILABLE:
            return "Error: pyperclip not installed. Run: pip install pyperclip"
        text = arguments.get("text", "")
        if not text:
            return "Error: text is required for clipboard_append"
        existing = pyperclip.paste() or ""
        combined = existing + text
        pyperclip.copy(combined)
        return f"OK: Appended text to clipboard; new length is {len(combined)} chars"

    @staticmethod
    def _clipboard_clear(arguments: dict) -> str:
        if not PYPERCLIP_AVAILABLE:
            return "Error: pyperclip not installed. Run: pip install pyperclip"
        pyperclip.copy("")
        return "OK: Clipboard cleared"

    @staticmethod
    def _list_windows(arguments: dict) -> str:
        records = WindowClipboardTool._build_window_records(visible_only=True)
        if not records:
            return "No visible windows found"
        lines = [f"Found {len(records)} visible window(s):"]
        for index, record in enumerate(records[:30], 1):
            lines.append(f"{index}. {WindowClipboardTool._format_record(record)}")
        if len(records) > 30:
            lines.append(f"... and {len(records) - 30} more")
        return "\n".join(lines)

    @staticmethod
    def _find_window(arguments: dict) -> str:
        title = arguments.get("title")
        process = arguments.get("process")
        pid = arguments.get("pid")
        if not title and not process and pid is None:
            return "Error: title, process, or pid is required"

        records = WindowClipboardTool._build_window_records(visible_only=True)
        matches = []
        for record in records:
            if pid is not None and record.get("pid") == pid:
                matches.append(record)
                continue
            if title and title.lower() in record["title"].lower():
                matches.append(record)
                continue
            if process and record.get("process") and process.lower() in str(record["process"]).lower():
                matches.append(record)

        if not matches:
            return "No matching windows found"

        lines = [f"Found {len(matches)} matching window(s):"]
        for index, record in enumerate(matches[:15], 1):
            lines.append(f"{index}. {WindowClipboardTool._format_record(record)}")
        return "\n".join(lines)

    @staticmethod
    def _switch_to_window(arguments: dict) -> str:
        record = WindowClipboardTool._match_record(arguments, active_fallback=False)
        if record is None:
            return "Error: No matching window found"
        window = record["window"]
        if window.isMinimized:
            window.restore()
            time.sleep(0.1)
        window.activate()
        time.sleep(0.1)
        return f"OK: Focused window '{record['title']}'"

    @staticmethod
    def _launch_app(arguments: dict) -> str:
        command = arguments.get("command")
        process = arguments.get("process")
        working_directory = arguments.get("working_directory") or None
        if not command:
            if not process:
                return "Error: command or process is required for launch_app"
            command = process

        if working_directory:
            Path(working_directory).mkdir(parents=True, exist_ok=True)

        launched = subprocess.Popen(
            command,
            shell=True,
            cwd=working_directory,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return f"OK: Launched '{command}' with pid {launched.pid}"

    @staticmethod
    def _focus_or_launch(arguments: dict) -> str:
        record = WindowClipboardTool._match_record(arguments, active_fallback=False)
        if record is not None:
            return WindowClipboardTool._switch_to_window(arguments)

        launch_result = WindowClipboardTool._launch_app(arguments)
        timeout_sec = float(arguments.get("timeout_sec", 8))
        deadline = time.time() + timeout_sec

        lookup_arguments = {
            "title": arguments.get("title"),
            "process": arguments.get("process"),
            "pid": arguments.get("pid"),
        }

        while time.time() < deadline:
            record = WindowClipboardTool._match_record(lookup_arguments, active_fallback=False)
            if record is not None:
                WindowClipboardTool._switch_to_window(lookup_arguments)
                return f"{launch_result}\nOK: Focused launched window '{record['title']}'"
            time.sleep(0.4)

        return f"{launch_result}\nWarning: app launched but no matching window appeared within {timeout_sec:.1f}s"

    @staticmethod
    def _get_active_window(arguments: dict) -> str:
        record = WindowClipboardTool._match_record({}, active_fallback=True)
        if record is None:
            return "No active window found"
        return "Active window: " + WindowClipboardTool._format_record(record)

    @staticmethod
    def _get_window_details(arguments: dict) -> str:
        record = WindowClipboardTool._match_record(arguments, active_fallback=True)
        if record is None:
            return "Error: No matching window found"
        return "Window details: " + WindowClipboardTool._format_record(record)

    @staticmethod
    def _list_processes(arguments: dict) -> str:
        records = WindowClipboardTool._get_process_window_records()
        if not records:
            return "No desktop processes with windows found"
        lines = [f"Found {len(records)} desktop process(es):"]
        for index, record in enumerate(records[:30], 1):
            lines.append(
                f"{index}. pid={record.get('Id')} process={record.get('ProcessName')} "
                f"title={record.get('MainWindowTitle')}"
            )
        if len(records) > 30:
            lines.append(f"... and {len(records) - 30} more")
        return "\n".join(lines)

    @staticmethod
    def _terminate_process(arguments: dict) -> str:
        pid = arguments.get("pid")
        process = arguments.get("process")
        if pid is None and not process:
            return "Error: pid or process is required for terminate_process"

        if pid is not None:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        else:
            image_name = str(process)
            if not image_name.lower().endswith(".exe"):
                image_name += ".exe"
            result = subprocess.run(
                ["taskkill", "/IM", image_name, "/T", "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )

        if result.returncode != 0:
            return f"Error: {(result.stderr or result.stdout or '').strip() or 'Failed to terminate process'}"
        return (result.stdout or "OK: Process terminated").strip()

    @staticmethod
    def _minimize_window(arguments: dict) -> str:
        record = WindowClipboardTool._match_record(arguments, active_fallback=True)
        if record is None:
            return "Error: No matching window found"
        record["window"].minimize()
        return f"OK: Minimized window '{record['title']}'"

    @staticmethod
    def _maximize_window(arguments: dict) -> str:
        record = WindowClipboardTool._match_record(arguments, active_fallback=True)
        if record is None:
            return "Error: No matching window found"
        record["window"].maximize()
        return f"OK: Maximized window '{record['title']}'"

    @staticmethod
    def _restore_window(arguments: dict) -> str:
        record = WindowClipboardTool._match_record(arguments, active_fallback=True)
        if record is None:
            return "Error: No matching window found"
        record["window"].restore()
        return f"OK: Restored window '{record['title']}'"

    @staticmethod
    def _close_window(arguments: dict) -> str:
        record = WindowClipboardTool._match_record(arguments, active_fallback=False)
        if record is None:
            return "Error: No matching window found"
        title = record["title"]
        record["window"].close()
        return f"OK: Closed window '{title}'"

    @staticmethod
    def _move_window(arguments: dict) -> str:
        x = arguments.get("x")
        y = arguments.get("y")
        if x is None or y is None:
            return "Error: x and y are required for move_window"
        record = WindowClipboardTool._match_record(arguments, active_fallback=True)
        if record is None:
            return "Error: No matching window found"
        record["window"].moveTo(int(x), int(y))
        return f"OK: Moved window '{record['title']}' to ({x}, {y})"

    @staticmethod
    def _resize_window(arguments: dict) -> str:
        width = arguments.get("width")
        height = arguments.get("height")
        if width is None or height is None:
            return "Error: width and height are required for resize_window"
        record = WindowClipboardTool._match_record(arguments, active_fallback=True)
        if record is None:
            return "Error: No matching window found"
        record["window"].resizeTo(int(width), int(height))
        return f"OK: Resized window '{record['title']}' to {width}x{height}"

    @staticmethod
    def _arrange_window(arguments: dict) -> str:
        preset = arguments.get("preset")
        if not preset:
            return "Error: preset is required for arrange_window"

        record = WindowClipboardTool._match_record(arguments, active_fallback=True)
        if record is None:
            return "Error: No matching window found"

        screen_width, screen_height = WindowClipboardTool._screen_size()
        layouts = {
            "left": (0, 0, screen_width // 2, screen_height),
            "right": (screen_width // 2, 0, screen_width // 2, screen_height),
            "top": (0, 0, screen_width, screen_height // 2),
            "bottom": (0, screen_height // 2, screen_width, screen_height // 2),
            "center": (screen_width // 6, screen_height // 8, int(screen_width * 0.67), int(screen_height * 0.75)),
            "fullscreen": (0, 0, screen_width, screen_height),
            "top_left": (0, 0, screen_width // 2, screen_height // 2),
            "top_right": (screen_width // 2, 0, screen_width // 2, screen_height // 2),
            "bottom_left": (0, screen_height // 2, screen_width // 2, screen_height // 2),
            "bottom_right": (screen_width // 2, screen_height // 2, screen_width // 2, screen_height // 2),
        }

        if preset not in layouts:
            return f"Error: Unknown preset '{preset}'"

        x, y, width, height = layouts[preset]
        record["window"].restore()
        record["window"].moveTo(x, y)
        record["window"].resizeTo(width, height)
        return f"OK: Arranged window '{record['title']}' to preset '{preset}'"
