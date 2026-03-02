import json
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import content_ops
from . import cron_ops
from . import deep_research as deep_research_mod
from . import desktop_ops
from . import fs_ops
from . import memory_ops
from . import music_ops
from . import realtime_search
from . import system_ops
from . import terminal_ops
from . import sheets_ops
from . import youtube_ops
from . import figma_ops
from . import whatsapp_ops
from . import contacts_ops


TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_contact",
            "description": "Look up a contact's phone number by name. Use this BEFORE send_whatsapp when the user gives a name instead of a number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Contact name, e.g. 'Rahul' or 'mom'"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_contact",
            "description": "Save a new contact (name + phone number) to the contacts book.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name":  {"type": "string", "description": "Contact name"},
                    "phone": {"type": "string", "description": "Phone in E.164 format, e.g. '+919876543210'"},
                },
                "required": ["name", "phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_contact",
            "description": "Remove a contact from the contacts book by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Contact name to remove"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_contacts",
            "description": "List all saved contacts with their phone numbers.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_whatsapp",
            "description": (
                "Send a WhatsApp message to a phone number using WhatsApp Web + Selenium. "
                "Uses the user's real Chrome profile so WhatsApp Web is already logged in. "
                "phone must be in E.164 format e.g. '+919876543210'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone":   {"type": "string", "description": "Recipient phone in E.164 format, e.g. '+919876543210'"},
                    "message": {"type": "string", "description": "The message text to send"},
                    "wait":    {"type": "integer", "description": "Seconds to wait for WhatsApp Web to load (default 10)"},
                },
                "required": ["phone", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cron",
            "description": "Manage ANKITA cron jobs (status/list/add/update/remove/run/runs/run_due).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "job": {"type": "object"},
                    "job_id": {"type": "string"},
                    "patch": {"type": "object"},
                    "include_disabled": {"type": "boolean"},
                    "mode": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the public web for real-time information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "include_urls": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_music",
            "description": "Search music candidates on the web and rank best match to user request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": "Play music in headless/background mode after validating best match from web search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "headless": {"type": "boolean"},
                    "stop_current": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_music",
            "description": "Stop currently playing headless music process.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_control",
            "description": (
                "Control system settings and perform system actions on Windows. "
                "\n\nVOLUME: volume_up, volume_down, mute_toggle, "
                "volume_set (set exact % via amount param), get_volume (read current %). "
                "\n\nBRIGHTNESS: brightness_up, brightness_down, "
                "brightness_set (exact % via amount), get_brightness (read current %). "
                "\n\nWI-FI / BLUETOOTH: wifi_on, wifi_off, bluetooth_on, bluetooth_off. "
                "\n\nBATTERY & POWER: get_battery_status (%, charging state, time remaining), "
                "set_power_plan (pass plan name via path: balanced/performance/power_saver). "
                "\n\nNETWORK: get_network_status (local IP, public IP, DNS, active adapters). "
                "\n\nCLIPBOARD: get_clipboard (read clipboard text), "
                "set_clipboard (write text to clipboard — pass text via path param). "
                "\n\nPROCESS MANAGER: list_processes (top 15 by CPU with RAM/PID), "
                "kill_process (terminate process by name — pass name via path param). "
                "\n\nSHUTDOWN: shutdown (5s delay), restart (5s delay), "
                "hibernate, sign_out, cancel_shutdown (abort pending shutdown). "
                "\n\nDISPLAY / THEME: night_light_on, night_light_off, "
                "dark_mode_on, dark_mode_off (toggle Windows dark/light theme). "
                "\n\nNOTIFICATIONS: notify (show Windows toast notification — pass message via path param). "
                "\n\nWINDOW / DESKTOP: show_desktop, lock_screen, "
                "window_minimize_all, window_restore_all, sleep_display. "
                "\n\nMEDIA: media_play_pause, media_next, media_prev. "
                "\n\nOTHER: screenshot (save PNG, optional path via path param), "
                "open_url (open URL in browser — pass URL via path param), "
                "empty_recycle_bin, get_system_info (OS, CPU%, RAM%, uptime)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "The action to perform. See tool description for full list. "
                            "Examples: volume_set, get_volume, brightness_set, get_brightness, "
                            "get_battery_status, set_power_plan, get_network_status, "
                            "get_clipboard, set_clipboard, list_processes, kill_process, "
                            "shutdown, restart, hibernate, sign_out, cancel_shutdown, "
                            "night_light_on, night_light_off, dark_mode_on, dark_mode_off, notify."
                        ),
                    },
                    "amount": {
                        "type": "integer",
                        "description": (
                            "Numeric parameter for the action. "
                            "For volume_up/down: steps (1-50). "
                            "For volume_set: exact % (0-100). "
                            "For brightness_up/down: steps (1-50). "
                            "For brightness_set: exact % (1-100)."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "String parameter for actions that need text input: "
                            "open_url → the URL, "
                            "set_clipboard → text to copy, "
                            "kill_process → process name, "
                            "set_power_plan → plan name (balanced/performance/power_saver), "
                            "notify → notification message text, "
                            "screenshot → optional save path."
                        ),
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_music",
            "description": "Get currently playing music details.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "queue_music",
            "description": "Add a song to the music queue to play after current track ends.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Song or artist name to queue"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_queue",
            "description": "Show all songs currently in the music queue.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_queue",
            "description": "Clear all songs from the music queue.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_next_in_queue",
            "description": "Stop current music and play the next song in the queue.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_price",
            "description": (
                "Fast, reliable price fetcher for crypto and stocks. "
                "ALWAYS use this for any price query (bitcoin, ethereum, AAPL, gold, etc.) "
                "BEFORE falling back to search_and_fetch. "
                "Tries CoinGecko API (crypto) → Yahoo Finance scrape (stocks) → web fallback. "
                "Returns the exact price in USD with 24h change for crypto. "
                "No API key required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to look up — e.g. 'bitcoin', 'ethereum', 'AAPL', 'Tesla stock', 'gold price'.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "Search latest news headlines in real time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "include_urls": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page_content",
            "description": (
                "Fetch a URL and extract the full readable text from the page. "
                "Use this when you need actual data from a specific URL — e.g. after search_web returns a link. "
                "Returns the page's visible text content (not HTML)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to fetch"},
                    "max_chars": {"type": "integer", "description": "Max characters to return (default 4000)"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_and_fetch",
            "description": (
                "Search the web AND automatically fetch actual page content from top results. "
                "ALWAYS prefer this over search_web for factual questions like: "
                "'price of bitcoin', 'current weather', 'what is X', 'how much does Y cost', "
                "'latest news about Z', 'specs of iPhone 16', etc. "
                "Returns real scraped text data — not just titles and URLs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "max_results": {"type": "integer", "description": "Number of search results to list (default 5)"},
                    "fetch_top": {"type": "integer", "description": "Number of top pages to scrape for content (default 2)"},
                    "max_chars_per_page": {"type": "integer", "description": "Max chars of content per page (default 3000)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminate_app",
            "description": "Close/terminate a running desktop application by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {"type": "string"},
                    "force": {"type": "boolean"},
                },
                "required": ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "launch_app",
            "description": "Launch a desktop application or command on the local machine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string"},
                },
                "required": ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_shell",
            "description": (
                "Run any PowerShell/CMD/shell command system-wide and return its output. "
                "Use this for: ping, ipconfig, git commands, dir, python scripts, netstat, "
                "tasklist, whoami, curl, or any CLI command. "
                "NOT sandboxed to workspace — can reach any system path. "
                "Has a hard timeout (default 15s). Destructive commands are blocked."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The exact CLI command to run (e.g. 'ping google.com -n 4', 'ipconfig', 'git status')",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Max seconds to wait before killing the command (default 15, max 60)",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a terminal command in workspace and return stdout/stderr/exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string"},
                    "timeout_ms": {"type": "integer"},
                    "use_shell": {"type": "boolean"},
                    "env": {"type": "object"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files/directories in workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "max_entries": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read UTF-8 text file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search text in workspace files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a UTF-8 text file. "
                "SUPPORTS ABSOLUTE PATHS — ALWAYS use the full absolute Desktop path when saving for the user: "
                "e.g. 'C:\\\\Users\\\\anime\\\\Desktop\\\\poem.txt'. "
                "Returns a RECEIPT: {status: 'success', absolute_path: '...', FILE_PATH: '...', bytes: N}. "
                "You MUST see status='success' in the receipt before telling the user the file was saved. "
                "NEVER say 'I saved it' until you see that receipt. Report errors if they appear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "File path. Use FULL ABSOLUTE PATH for Desktop saves "
                            "(e.g. C:\\\\Users\\\\anime\\\\Desktop\\\\report.txt). "
                            "Relative paths resolve against the workspace root."
                        ),
                    },
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace text in UTF-8 file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_path",
            "description": "Rename file/dir in same parent folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "new_name": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["path", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_path",
            "description": "Delete file/dir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "missing_ok": {"type": "boolean"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_path",
            "description": "Move/rename to new destination path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "dst": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["src", "dst"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_path",
            "description": "Copy file/dir to destination path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "dst": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                    "recursive": {"type": "boolean"},
                },
                "required": ["src", "dst"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_dir",
            "description": "Create directory path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "parents": {"type": "boolean"},
                    "exist_ok": {"type": "boolean"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_info",
            "description": "Get metadata for file/dir.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Apply multi-file patch using *** Begin Patch / *** End Patch format.",
            "parameters": {
                "type": "object",
                "properties": {"patch": {"type": "string"}},
                "required": ["patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_interact",
            "description": (
                "Interact directly with the OS using keyboard input. "
                "Use this to type text, press shortcuts, hit enter, or physically drive the UI. "
                "NEVER ask the user to type it themselves — call this instead. "
                "ALWAYS pass the `focus` parameter when you know which app you are targeting "
                "(e.g. 'Notepad', 'Chrome') — this prevents typing into the wrong window. "
                "Actions: "
                "'type_text' — types the given text into the focused window; "
                "'press_shortcut' — presses a key combo like 'ctrl+c', 'enter', 'win+d', 'alt+f4', 'ctrl+shift+esc'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["type_text", "press_shortcut"],
                        "description": "The interaction type.",
                    },
                    "text": {
                        "type": "string",
                        "description": "The text to type, or the shortcut string (e.g. 'ctrl+shift+esc', 'enter', 'win+d').",
                    },
                    "focus": {
                        "type": "string",
                        "description": (
                            "Optional: Window title to focus BEFORE typing or pressing keys. "
                            "e.g. 'Notepad', 'Visual Studio Code', 'Chrome'. "
                            "Always provide this when you know which app you are targeting."
                        ),
                    },
                },
                "required": ["action", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_syntax",
            "description": (
                "Run a fast Python syntax and AST check on a file using the built-in compiler — "
                "no subprocess needed. ALWAYS call this after editing code with edit_file_lines "
                "and BEFORE running it with run_command. Catches SyntaxError and IndentationError instantly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the Python (.py) file to check.",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_lines",
            "description": (
                "Read a specific range of lines from a file without loading the entire file. "
                "Lines are 1-indexed and inclusive on both ends. Each returned line is prefixed "
                "with its line number. Use this BEFORE calling edit_file_lines to confirm the "
                "exact line numbers — never guess. Example: to inspect lines 38-45 of a script."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file (absolute or relative to workspace).",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line to read (1-indexed, inclusive).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to read (1-indexed, inclusive).",
                    },
                },
                "required": ["file_path", "start_line", "end_line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file_lines",
            "description": (
                "Surgically replace a specific range of lines in a file. "
                "Only the targeted lines change — all surrounding code is preserved exactly. "
                "Lines are 1-indexed and inclusive. "
                "CRITICAL: Always call read_file or read_file_lines FIRST to confirm exact line "
                "numbers before calling this — never guess. "
                "Use this for bug fixes, one-line patches, refactors, and any change that "
                "does NOT require rewriting the entire file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file (absolute or relative to workspace).",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line to replace (1-indexed, inclusive).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to replace (1-indexed, inclusive).",
                    },
                    "new_content": {
                        "type": "string",
                        "description": (
                            "Replacement text. May contain multiple lines separated by \\n. "
                            "This replaces ALL lines from start_line to end_line."
                        ),
                    },
                },
                "required": ["file_path", "start_line", "end_line", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_screen",
            "description": (
                "Capture a screenshot of the screen using mss (fast, no screen flash). "
                "Returns the absolute file path and a base64-encoded PNG string ready for "
                "GPT-4o vision analysis. Use this when the user asks what is on their screen, "
                "to read errors, inspect UI, or before clicking a button visually."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "monitor": {
                        "type": "integer",
                        "description": "Monitor index: 0=all monitors combined, 1=primary (default), 2=second monitor.",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "Optional absolute path to save the PNG. Defaults to .ankita/temp/screenshot_<ts>.png.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_screen_context",
            "description": (
                "Load an existing screenshot from disk and return its base64 representation "
                "for vision analysis. Use this when a screenshot was already taken and you "
                "want to re-analyze it without capturing a new one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "Absolute or relative path to a PNG/JPEG screenshot file.",
                    },
                },
                "required": ["image_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "visual_click",
            "description": (
                "Click a UI element on screen by describing it in natural language. "
                "Takes a screenshot, uses GPT-4o vision to find the element's pixel coordinates, "
                "then physically moves the mouse and clicks it with pyautogui. "
                "Example: 'click the Deploy to Vercel button', 'click the red X', 'click Submit'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_description": {
                        "type": "string",
                        "description": "Natural-language description of the UI element to click, e.g. 'the Save button', 'the red X in the top right'.",
                    },
                    "screenshot_path": {
                        "type": "string",
                        "description": "Optional path to an existing screenshot. If omitted, a fresh screenshot is captured.",
                    },
                },
                "required": ["target_description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Save a permanent memory to the long-term vault. "
                "Use when the user says 'remember that X', 'my name is Y', "
                "'I prefer Z', or 'note that W'. "
                "This persists forever — survives restarts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The fact, preference, or note to remember.",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["user_profile", "facts", "projects", "preferences", "people", "locations"],
                        "description": (
                            "Where to store it. "
                            "'user_profile' for personal info (name, preferences), "
                            "'facts' for general facts, "
                            "'projects' for project names and descriptions."
                        ),
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": (
                "Search long-term memory for stored facts or preferences. "
                "Use when you need to look up something the user told Ankita to remember, "
                "or when answering a question that might depend on known user preferences."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword to search for. Omit to retrieve ALL memories.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": (
                "Delete a specific memory from the long-term vault. "
                "Use when the user says 'forget that X' or 'delete the memory about Y'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The exact text of the memory to delete.",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_webcam",
            "description": (
                "Takes a photo using the user's webcam (physical camera). "
                "Use this when asked 'what am I holding', 'look at me', 'take a photo', "
                "'take a selfie', 'scan my room', 'what is this', or 'check my fit'. "
                "Returns a base64 image for vision analysis. "
                "Do NOT use this for screen captures — use capture_screen for that."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "camera_index": {
                        "type": "integer",
                        "description": "Camera ID. 0 = default webcam (usually front camera). 1 = second camera.",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "Optional absolute path to save the image for debugging. Omit for RAM-only mode.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download_file",
            "description": (
                "Download a file (PDF, CSV, DOCX, XLSX, ZIP, etc.) from a direct URL to the local disk. "
                "Use this when the user wants a document, datasheet, report, or any file — "
                "NOT when they just want to read a web page. "
                "Auto-detects the filename from the Content-Disposition header or URL tail. "
                "Infers the file extension from the Content-Type if missing. "
                "Saves to the user's Downloads folder by default. "
                "Returns the absolute local path so you can then open it with launch_app."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The direct URL of the file to download (e.g. https://example.com/report.pdf).",
                    },
                    "save_folder": {
                        "type": "string",
                        "description": (
                            "Optional absolute path to a folder to save the file in. "
                            "Defaults to the user's Downloads folder."
                        ),
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deep_research",
            "description": (
                "Run a comprehensive multi-threaded deep research on any topic. "
                "ALWAYS use this for requests like: 'deep report on X', 'comprehensive analysis of Y', "
                "'research and write about Z', 'detailed writeup on W', 'swarm research X', "
                "'in-depth report', 'full investigation'. "
                "Runs up to 10 parallel web scout threads → synthesises a Master Intelligence Brief. "
                "Returns a RESEARCH_CONTEXT_BLOCK — pass this to ContentAgent for fact-grounded writing. "
                "Do NOT use search_and_fetch for deep research tasks — use this instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The research topic or question to investigate deeply.",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sheets_op",
            "description": (
                "Interact with Google Sheets. Actions: "
                "'append_row' — add a row of data (e.g. log an expense, track a workout); "
                "'read_range' — read cell range from a sheet; "
                "'create_sheet' — create a new spreadsheet; "
                "'list_sheets' — list all spreadsheets; "
                "'update_cell' — update a specific cell."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action":           {"type": "string", "enum": ["append_row", "read_range", "create_sheet", "list_sheets", "update_cell"]},
                    "spreadsheet_name": {"type": "string", "description": "Human-readable spreadsheet name, e.g. 'Expenses 2026'"},
                    "data":             {"type": "array",  "items": {}, "description": "Row data for append_row, e.g. ['2026-02-28', 'Pizza', 500]"},
                    "range_notation":   {"type": "string", "description": "A1 notation range for read_range, e.g. 'A1:D20'"},
                    "sheet_tab":        {"type": "string", "description": "Tab name within the spreadsheet (default: 'Sheet1')"},
                    "title":            {"type": "string", "description": "Title for create_sheet"},
                    "cell":             {"type": "string", "description": "Cell reference for update_cell, e.g. 'B3'"},
                    "value":            {"description": "New value for update_cell"},
                    "max_results":      {"type": "integer"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_op",
            "description": (
                "Manage YouTube library. Actions: "
                "'get_subscriptions' — list subscribed channels; "
                "'search_channel_videos' — search videos from a specific channel; "
                "'create_playlist' — create a new playlist (optionally add videos); "
                "'list_playlists' — list your playlists; "
                "'add_to_playlist' — add a video to an existing playlist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action":       {"type": "string", "enum": ["get_subscriptions", "search_channel_videos", "create_playlist", "list_playlists", "add_to_playlist"]},
                    "channel_name": {"type": "string", "description": "Channel name for search_channel_videos, e.g. 'Fireship'"},
                    "query":        {"type": "string", "description": "Optional search term within the channel"},
                    "name":         {"type": "string", "description": "Playlist name for create_playlist"},
                    "description":  {"type": "string", "description": "Optional playlist description"},
                    "video_ids":    {"type": "array",  "items": {"type": "string"}, "description": "YouTube video IDs to add to new playlist"},
                    "playlist_id":  {"type": "string", "description": "Playlist ID for add_to_playlist"},
                    "video_id":     {"type": "string", "description": "Video ID for add_to_playlist"},
                    "max_results":  {"type": "integer"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "figma_op",
            "description": (
                "Interact with Figma design files. Actions: "
                "'list_projects' — list projects in a team; "
                "'list_files' — list design files in a project; "
                "'read_comments' — read all comments on a file; "
                "'post_comment' — post a comment on a file; "
                "'get_node_properties' — get properties (colours, size, font) of specific nodes; "
                "'get_file_info' — get file metadata (name, pages, last modified)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action":       {"type": "string", "enum": ["list_projects", "list_files", "read_comments", "post_comment", "get_node_properties", "get_file_info"]},
                    "team_id":      {"type": "string", "description": "Figma Team ID for list_projects"},
                    "project_id":   {"type": "string", "description": "Figma Project ID for list_files"},
                    "file_key":     {"type": "string", "description": "Figma file key (from figma.com/file/<KEY>)"},
                    "message":      {"type": "string", "description": "Comment text for post_comment"},
                    "node_id":      {"type": "string", "description": "Optional node ID to anchor comment to a specific element"},
                    "node_ids":     {"type": "string", "description": "Comma-separated node IDs for get_node_properties, e.g. '1:2,1:3'"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_content",
            "description": (
                "Generate any type of text content using the LLM and save it to the Desktop. "
                "Use this when the user asks to 'write', 'draft', 'create', or 'generate' "
                "content such as a report, script, song, pitch deck, summary, paragraph, essay, "
                "or any other written format. Returns the file path and a spoken confirmation.\n\n"
                "TWO-SPEED ENGINE (auto-detected from keywords):\n"
                "  NORMAL mode: concise output matching format norms (poems ~20 lines, emails ~250 words, reports ~800 words).\n"
                "  DEEP mode: 6000-8000+ words (~10 printed pages) — triggered automatically when topic or format_type "
                "contains: 'deep', 'comprehensive', 'detailed', 'in-depth', 'massive', 'extensive', 'thorough', "
                "'10 page', 'full investigation', 'long form', 'deep dive'.\n"
                "For deep reports: pass format_type='deep report' or include 'comprehensive' in topic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "What the content is about (e.g. 'Helper ID app', 'Python coding').",
                    },
                    "format_type": {
                        "type": "string",
                        "description": (
                            "The format of content to produce — e.g. 'report', 'script', 'song', "
                            "'pitch deck', 'summary', 'paragraph', 'essay', 'email', 'poem'."
                        ),
                    },
                    "extra_context": {
                        "type": "string",
                        "description": "Optional rough notes, bullet points, or extra instructions for the LLM.",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Optional absolute path to save the file. Defaults to the user's Desktop.",
                    },
                },
                "required": ["topic", "format_type"],
            },
        },
    },
]


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _match(token: str, choices: List[str], threshold: float = 0.78) -> bool:
    t = token.strip().lower()
    if not t:
        return False
    return any(t == c.lower() or _sim(t, c.lower()) >= threshold for c in choices)


def _tokenize(text: str) -> List[str]:
    cleaned = text
    for ch in ",.;:!?()[]{}<>|/\\\t\r\n":
        cleaned = cleaned.replace(ch, " ")
    return [t for t in cleaned.lower().split(" ") if t]


def _extract_quoted_text(text: str) -> Optional[str]:
    for q in ('"', "'"):
        start = text.find(q)
        if start == -1:
            continue
        end = text.find(q, start + 1)
        if end == -1:
            continue
        val = text[start + 1 : end].strip()
        if val:
            return val
    return None


def _normalize_human_path(raw: str) -> str:
    value = raw.strip().strip("\"'").lower()
    aliases = ["", ".", "this project", "project", "workspace", "this workspace", "here"]
    if any(_sim(value, alias) >= 0.76 for alias in aliases):
        return "."
    return raw.strip().strip("\"'")


def _call(name: str, args: Dict[str, Any], workspace_root: Path) -> Dict[str, Any]:
    if name == "lookup_contact":
        return contacts_ops.lookup_contact(name=str(args.get("name", "")))

    if name == "add_contact":
        return contacts_ops.add_contact(
            name=str(args.get("name", "")),
            phone=str(args.get("phone", "")),
        )

    if name == "remove_contact":
        return contacts_ops.remove_contact(name=str(args.get("name", "")))

    if name == "list_contacts":
        return contacts_ops.list_contacts()

    if name == "send_whatsapp":
        return whatsapp_ops.send_whatsapp(
            phone=str(args.get("phone", "")),
            message=str(args.get("message", "")),
            wait=int(args.get("wait", 10)),
        )
    if name == "cron":
        return cron_ops.cron_action(
            workspace_root=workspace_root,
            action=str(args.get("action", "")),
            job=args.get("job") if isinstance(args.get("job"), dict) else None,
            job_id=str(args.get("job_id", "")) if args.get("job_id") is not None else None,
            patch=args.get("patch") if isinstance(args.get("patch"), dict) else None,
            include_disabled=bool(args.get("include_disabled", False)),
            mode=str(args.get("mode", "due")),
            limit=int(args.get("limit", 20)),
        )
    if name == "search_web":
        return realtime_search.search_web(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 8)),
            include_urls=bool(args.get("include_urls", False)),
        )
    if name == "search_music":
        return music_ops.search_music(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 8)),
        )
    if name == "play_music":
        return music_ops.play_music(
            workspace_root=workspace_root,
            query=str(args.get("query", "")),
            headless=bool(args.get("headless", True)),
            stop_current=bool(args.get("stop_current", True)),
        )
    if name == "stop_music":
        return music_ops.stop_music(workspace_root=workspace_root)
    if name == "current_music":
        return music_ops.current_music(workspace_root=workspace_root)
    if name == "queue_music":
        return music_ops.queue_music(workspace_root=workspace_root, query=str(args.get("query", "")))
    if name == "show_queue":
        return music_ops.show_queue(workspace_root=workspace_root)
    if name == "clear_queue":
        return music_ops.clear_queue(workspace_root=workspace_root)
    if name == "play_next_in_queue":
        return music_ops.play_next_in_queue(workspace_root=workspace_root)
    if name == "system_control":
        return system_ops.system_control(
            action=str(args.get("action", "")),
            amount=int(args.get("amount", 1)),
            path=str(args.get("path")) if args.get("path") is not None else None,
            workspace_root=workspace_root,
        )
    if name == "search_price":
        return realtime_search.search_price(
            query=str(args.get("query", "")),
        )
    if name == "search_news":
        return realtime_search.search_news(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 8)),
            include_urls=bool(args.get("include_urls", False)),
        )
    if name == "fetch_page_content":
        return realtime_search.fetch_page_content(
            url=str(args.get("url", "")),
            max_chars=int(args.get("max_chars", 4000)),
        )
    if name == "deep_research":
        # runtime is injected via execute_tool_call._runtime by the Orchestrator
        _rt = getattr(execute_tool_call, "_runtime", None)
        return deep_research_mod.deep_research(
            topic=str(args.get("topic", "")),
            runtime=_rt,
        )
    if name == "search_and_fetch":
        return realtime_search.search_and_fetch(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 5)),
            fetch_top=int(args.get("fetch_top", 2)),
            max_chars_per_page=int(args.get("max_chars_per_page", 3000)),
        )
    if name == "terminate_app":
        return terminal_ops.terminate_app(
            app=str(args.get("app", "")),
            force=bool(args.get("force", False)),
        )
    if name == "launch_app":
        return terminal_ops.launch_app(
            workspace_root,
            app=str(args.get("app", "")),
            args=[str(v) for v in (args.get("args") or [])] if isinstance(args.get("args"), list) else None,
            cwd=str(args.get("cwd")) if args.get("cwd") is not None else None,
        )
    if name == "execute_shell":
        return terminal_ops.execute_shell_command(
            command=str(args.get("command", "")),
            timeout=int(args.get("timeout", 15)),
        )
    if name == "run_command":
        env = args.get("env")
        env_obj = env if isinstance(env, dict) else None
        return terminal_ops.run_command(
            workspace_root,
            command=str(args.get("command", "")),
            args=[str(v) for v in (args.get("args") or [])] if isinstance(args.get("args"), list) else None,
            cwd=str(args.get("cwd")) if args.get("cwd") is not None else None,
            timeout_ms=int(args.get("timeout_ms", 20000)),
            use_shell=bool(args.get("use_shell", False)),
            env={str(k): str(v) for k, v in env_obj.items()} if env_obj is not None else None,
        )
    if name == "list_files":
        return fs_ops.list_files(workspace_root, path=str(args.get("path", ".")), max_entries=int(args.get("max_entries", 200)))
    if name == "read_file":
        return fs_ops.read_file(workspace_root, path=str(args.get("path", "")))
    if name == "search_text":
        return fs_ops.search_text(
            workspace_root,
            query=str(args.get("query", "")),
            path=str(args.get("path", ".")),
            max_results=int(args.get("max_results", 100)),
        )
    if name == "write_file":
        return fs_ops.write_file(
            workspace_root,
            path=str(args.get("path", "")),
            content=str(args.get("content", "")),
            overwrite=bool(args.get("overwrite", True)),
        )
    if name == "edit_file":
        return fs_ops.edit_file(
            workspace_root,
            path=str(args.get("path", "")),
            old_text=str(args.get("old_text", "")),
            new_text=str(args.get("new_text", "")),
            replace_all=bool(args.get("replace_all", False)),
        )
    if name == "rename_path":
        return fs_ops.rename_path(
            workspace_root,
            path=str(args.get("path", "")),
            new_name=str(args.get("new_name", "")),
            overwrite=bool(args.get("overwrite", False)),
        )
    if name == "delete_path":
        return fs_ops.delete_path(
            workspace_root,
            path=str(args.get("path", "")),
            recursive=bool(args.get("recursive", False)),
            missing_ok=bool(args.get("missing_ok", False)),
        )
    if name == "move_path":
        return fs_ops.move_path(
            workspace_root,
            src=str(args.get("src", "")),
            dst=str(args.get("dst", "")),
            overwrite=bool(args.get("overwrite", False)),
        )
    if name == "copy_path":
        return fs_ops.copy_path(
            workspace_root,
            src=str(args.get("src", "")),
            dst=str(args.get("dst", "")),
            overwrite=bool(args.get("overwrite", False)),
            recursive=bool(args.get("recursive", False)),
        )
    if name == "make_dir":
        return fs_ops.make_dir(
            workspace_root,
            path=str(args.get("path", "")),
            parents=bool(args.get("parents", True)),
            exist_ok=bool(args.get("exist_ok", True)),
        )
    if name == "file_info":
        return fs_ops.file_info(workspace_root, path=str(args.get("path", "")))
    if name == "desktop_interact":
        return desktop_ops.desktop_interact(
            action=str(args.get("action", "")),
            text=str(args.get("text", "")),
            focus=str(args["focus"]) if args.get("focus") else None,
        )
    if name == "check_syntax":
        return fs_ops.check_syntax(
            workspace_root=workspace_root,
            path=str(args.get("file_path", "")),
        )
    if name == "read_file_lines":
        return fs_ops.read_file_lines(
            workspace_root=workspace_root,
            path=str(args.get("file_path", "")),
            start_line=int(args.get("start_line", 1)),
            end_line=int(args.get("end_line", 1)),
        )
    if name == "edit_file_lines":
        return fs_ops.edit_file_lines(
            workspace_root=workspace_root,
            path=str(args.get("file_path", "")),
            start_line=int(args.get("start_line", 1)),
            end_line=int(args.get("end_line", 1)),
            new_content=str(args.get("new_content", "")),
        )
    if name == "apply_patch":
        return fs_ops.apply_patch(workspace_root, patch=str(args.get("patch", "")))
    if name == "remember":
        return memory_ops.remember(
            text=str(args.get("text", "")),
            category=str(args.get("category", "facts")),
        )
    if name == "recall":
        return memory_ops.recall(
            query=str(args.get("query")) if args.get("query") else None,
        )
    if name == "forget":
        return memory_ops.forget(text=str(args.get("text", "")))
    if name == "capture_webcam":
        return desktop_ops.capture_webcam(
            camera_index=int(args.get("camera_index", 0)),
            save_path=str(args.get("save_path")) if args.get("save_path") else None,
        )
    if name == "download_file":
        return realtime_search.download_file(
            url=str(args.get("url", "")),
            save_folder=str(args.get("save_folder")) if args.get("save_folder") else None,
        )
    if name == "write_content":
        return content_ops.write_and_save_content(
            workspace_root=workspace_root,
            topic=str(args.get("topic", "")),
            format_type=str(args.get("format_type", "content")),
            extra_context=str(args.get("extra_context", "")),
            output_dir=str(args.get("output_dir")) if args.get("output_dir") else None,
        )
    if name == "capture_screen":
        return desktop_ops.capture_screen(
            monitor=int(args.get("monitor", 1)),
            save_path=str(args.get("save_path")) if args.get("save_path") else None,
        )
    if name == "read_screen_context":
        return desktop_ops.read_screen_context(
            image_path=str(args.get("image_path", "")),
        )
    if name == "visual_click":
        # visual_click needs the LLMRuntime — retrieve it from the global agent context if available
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return desktop_ops.visual_click(
            target_description=str(args.get("target_description", "")),
            runtime=_runtime,
            screenshot_path=str(args.get("screenshot_path")) if args.get("screenshot_path") else None,
        )
    # ── Google Sheets ──────────────────────────────────────────────────────────
    if name == "sheets_op":
        action = str(args.get("action", ""))
        if action == "append_row":
            return sheets_ops.append_row(
                spreadsheet_name=str(args.get("spreadsheet_name", "")),
                data=args.get("data", []),
                sheet_tab=str(args.get("sheet_tab", "Sheet1")),
            )
        if action == "read_range":
            return sheets_ops.read_range(
                spreadsheet_name=str(args.get("spreadsheet_name", "")),
                range_notation=str(args.get("range_notation", "A1:Z100")),
                sheet_tab=str(args.get("sheet_tab", "Sheet1")),
            )
        if action == "create_sheet":
            return sheets_ops.create_sheet(title=str(args.get("title", "")))
        if action == "list_sheets":
            return sheets_ops.list_sheets(max_results=int(args.get("max_results", 20)))
        if action == "update_cell":
            return sheets_ops.update_cell(
                spreadsheet_name=str(args.get("spreadsheet_name", "")),
                cell=str(args.get("cell", "A1")),
                value=args.get("value", ""),
                sheet_tab=str(args.get("sheet_tab", "Sheet1")),
            )
        return {"status": "error", "message": f"Unknown sheets_op action: {action}"}

    # ── YouTube ────────────────────────────────────────────────────────────────
    if name == "youtube_op":
        action = str(args.get("action", ""))
        if action == "get_subscriptions":
            return youtube_ops.get_subscriptions(max_results=int(args.get("max_results", 20)))
        if action == "search_channel_videos":
            return youtube_ops.search_channel_videos(
                channel_name=str(args.get("channel_name", "")),
                query=str(args.get("query", "")),
                max_results=int(args.get("max_results", 10)),
            )
        if action == "create_playlist":
            return youtube_ops.create_playlist(
                name=str(args.get("name", "")),
                description=str(args.get("description", "")),
                video_ids=args.get("video_ids") if isinstance(args.get("video_ids"), list) else None,
            )
        if action == "list_playlists":
            return youtube_ops.list_playlists(max_results=int(args.get("max_results", 20)))
        if action == "add_to_playlist":
            return youtube_ops.add_to_playlist(
                playlist_id=str(args.get("playlist_id", "")),
                video_id=str(args.get("video_id", "")),
            )
        return {"status": "error", "message": f"Unknown youtube_op action: {action}"}

    # ── Figma ──────────────────────────────────────────────────────────────────
    if name == "figma_op":
        action = str(args.get("action", ""))
        if action == "list_projects":
            return figma_ops.list_projects(team_id=str(args.get("team_id", "")))
        if action == "list_files":
            return figma_ops.list_files(project_id=str(args.get("project_id", "")))
        if action == "read_comments":
            return figma_ops.read_comments(file_key=str(args.get("file_key", "")))
        if action == "post_comment":
            return figma_ops.post_comment(
                file_key=str(args.get("file_key", "")),
                message=str(args.get("message", "")),
                node_id=str(args.get("node_id")) if args.get("node_id") else None,
            )
        if action == "get_node_properties":
            return figma_ops.get_node_properties(
                file_key=str(args.get("file_key", "")),
                node_ids=str(args.get("node_ids", "")),
            )
        if action == "get_file_info":
            return figma_ops.get_file_info(file_key=str(args.get("file_key", "")))
        return {"status": "error", "message": f"Unknown figma_op action: {action}"}

    raise ValueError(f"Unknown tool: {name}")


_HARD_CAP_CHARS = 3000
_HARD_CAP_MSG   = "\n... [OUTPUT TRUNCATED — too much data. Please refine your request or ask for a smaller range.]"


def _hard_cap(result: Any) -> Any:
    """
    Prism Protocol — Token Budget Guard 💎
    Converts any tool result to a string and hard-caps it at _HARD_CAP_CHARS characters.
    This prevents 400 Bad Request / context_length_exceeded crashes from fat API payloads.
    Non-string results (dicts, lists) are JSON-serialised first, then checked.
    Returns the original result unchanged if it's within the limit.

    VISION EXCEPTION: If the result contains a "base64" key (vision tool output),
    we strip the base64 field BEFORE checking size. The vision intercept in
    agent_runtime.py / orchestrator.py handles base64 separately via call_chat_with_image().
    Truncating a base64 field corrupts the image and breaks JSON parsing.
    """
    if isinstance(result, dict):
        # VISION EXCEPTION: preserve base64 fields from truncation
        # The vision intercept extracts base64 BEFORE _hard_cap is applied in execute_tool_call.
        # But if the result is large due to OTHER fields, strip base64 for size check only.
        if "base64" in result:
            # Pass through unchanged — vision intercept handles this result directly
            return result
        # Recursively check inner "result" dict for base64
        _inner = result.get("result", {})
        if isinstance(_inner, dict) and "base64" in _inner:
            return result  # pass through — vision intercept will unwrap it

        serialised = json.dumps(result, ensure_ascii=False)
        if len(serialised) <= _HARD_CAP_CHARS:
            return result
        truncated = serialised[:_HARD_CAP_CHARS] + _HARD_CAP_MSG
        return {"status": "truncated", "data": truncated}
    if isinstance(result, list):
        serialised = json.dumps(result, ensure_ascii=False)
        if len(serialised) <= _HARD_CAP_CHARS:
            return result
        truncated = serialised[:_HARD_CAP_CHARS] + _HARD_CAP_MSG
        return {"status": "truncated", "data": truncated}
    if isinstance(result, str) and len(result) > _HARD_CAP_CHARS:
        return result[:_HARD_CAP_CHARS] + _HARD_CAP_MSG
    return result


def execute_tool_call(tool_call: Dict[str, Any], workspace_root: Path) -> Dict[str, Any]:
    fn = tool_call.get("function", {})
    name = str(fn.get("name", ""))
    raw_args = fn.get("arguments", "{}")

    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
    except json.JSONDecodeError as err:
        raise ValueError(f"Invalid JSON args for {name}: {err}") from err

    if not isinstance(args, dict):
        raise ValueError(f"Tool args must be an object for {name}")

    result = _call(name, args, workspace_root)
    # 💎 Prism Protocol: hard-cap ALL tool outputs before they enter the context window
    result = _hard_cap(result)
    return {"ok": True, "tool": name, "result": result}


def select_tools_for_user_text(user_text: str) -> List[Dict[str, Any]]:
    tokens = _tokenize(user_text)
    chosen: List[str] = []

    has_list = any(_match(t, ["list", "show", "display", "ls"], 0.74) for t in tokens)
    has_files = any(_match(t, ["file", "files", "dir", "directory", "folder"], 0.72) for t in tokens)
    has_cam = any(_match(t, ["webcam", "camera", "photo", "selfie", "holding", "wearing", "room", "scan"], 0.85) for t in tokens)
    if has_cam:
        chosen.append("capture_webcam")
    has_memory = any(_match(t, ["remember", "recall", "forget", "memory", "memorize", "note", "stored"], 0.82) for t in tokens)
    if has_memory:
        chosen.extend(["remember", "recall", "forget"])
    has_read = any(_match(t, ["read", "open", "cat", "summarize"], 0.72) for t in tokens)
    has_search = any(_match(t, ["search", "find", "grep", "contains"], 0.72) for t in tokens)
    has_write = any(_match(t, ["write", "create", "save"], 0.72) for t in tokens)
    has_edit = any(_match(t, ["edit", "replace", "update", "modify"], 0.72) for t in tokens)
    has_rename = any(_match(t, ["rename"], 0.72) for t in tokens)
    has_delete = any(_match(t, ["delete", "remove", "rm"], 0.72) for t in tokens)
    has_move = any(_match(t, ["move", "mv"], 0.72) for t in tokens)
    has_copy = any(_match(t, ["copy", "cp", "duplicate"], 0.72) for t in tokens)
    has_mkdir = any(_match(t, ["mkdir", "folder", "directory"], 0.72) for t in tokens) and any(
        _match(t, ["create", "make", "new"], 0.72) for t in tokens
    )
    has_info = any(_match(t, ["info", "metadata", "stat", "details"], 0.72) for t in tokens)
    has_patch = any(_match(t, ["patch", "diff", "apply", "hunk"], 0.72) for t in tokens)
    has_exec = any(_match(t, ["run", "exec", "execute", "terminal", "cmd", "command", "powershell"], 0.72) for t in tokens)
    has_launch = any(_match(t, ["open", "launch", "start"], 0.72) for t in tokens)
    has_close = any(_match(t, ["close", "kill", "stop", "terminate", "quit"], 0.72) for t in tokens)
    has_web_search = any(_match(t, ["web", "internet", "online", "google"], 0.72) for t in tokens)
    has_news_search = any(_match(t, ["news", "headline", "headlines", "latest"], 0.72) for t in tokens)
    has_search_word = any(_match(t, ["search", "find", "lookup"], 0.72) for t in tokens)
    has_fetch = any(_match(t, ["fetch", "scrape", "content", "page", "open", "read"], 0.72) for t in tokens) and any(
        _match(t, ["url", "link", "website", "site"], 0.72) for t in tokens
    )
    has_factual = any(_match(t, ["price", "cost", "weather", "temperature", "rate", "value", "score", "how much", "what is", "details", "info", "specs"], 0.72) for t in tokens)
    has_cron = any(_match(t, ["cron", "schedule", "reminder", "reminders"], 0.72) for t in tokens)
    has_manage = any(_match(t, ["add", "create", "update", "remove", "run", "list", "status"], 0.72) for t in tokens)
    has_music = any(_match(t, ["music", "song", "songs", "track", "audio"], 0.72) for t in tokens)
    has_play = any(_match(t, ["play", "listen", "start"], 0.72) for t in tokens)
    has_stop = any(_match(t, ["stop", "pause", "end"], 0.72) for t in tokens)
    has_now = any(_match(t, ["current", "now", "what", "which", "name"], 0.72) for t in tokens)
    has_queue = any(_match(t, ["queue", "add", "enqueue", "next", "lineup"], 0.72) for t in tokens)
    has_show_queue = any(_match(t, ["show", "list", "view", "display"], 0.72) for t in tokens) and has_queue
    has_clear_queue = any(_match(t, ["clear", "empty", "remove", "reset"], 0.72) for t in tokens) and has_queue
    has_play_next = any(_match(t, ["next", "skip"], 0.72) for t in tokens) and has_music
    has_system = any(
        _match(
            t,
            [
                "volume",
                "mute",
                "desktop",
                "media",
                "system",
                "sound",
                "brightness",
                "wifi",
                "wireless",
                "bluetooth",
                "screenshot",
                "screen",
                "window",
            ],
            0.72,
        )
        for t in tokens
    )

    if has_cron and has_manage:
        chosen.append("cron")
    if has_music and has_play:
        chosen.append("play_music")
    if has_music and has_stop:
        chosen.append("stop_music")
    if has_music and has_now:
        chosen.append("current_music")
    if has_queue and has_music:
        chosen.append("queue_music")
    if has_show_queue:
        chosen.append("show_queue")
    if has_clear_queue:
        chosen.append("clear_queue")
    if has_play_next:
        chosen.append("play_next_in_queue")
    if has_system:
        chosen.append("system_control")
    if has_news_search:
        chosen.append("search_news")
    if has_fetch:
        chosen.append("fetch_page_content")
    if has_factual or (has_search_word and not has_web_search):
        chosen.append("search_and_fetch")
    if has_web_search and has_search_word:
        chosen.append("search_web")
    if has_close:
        chosen.append("terminate_app")
    if has_launch:
        chosen.append("launch_app")
    if has_exec:
        chosen.append("run_command")
    if has_list and has_files:
        chosen.append("list_files")
    if has_read:
        chosen.append("read_file")
    if has_search:
        chosen.append("search_text")
    if has_write:
        chosen.append("write_file")
    if has_edit:
        chosen.append("edit_file")
    if has_rename:
        chosen.append("rename_path")
    if has_delete:
        chosen.append("delete_path")
    if has_move:
        chosen.append("move_path")
    if has_copy:
        chosen.append("copy_path")
    if has_mkdir:
        chosen.append("make_dir")
    if has_info:
        chosen.append("file_info")
    if has_patch:
        chosen.append("apply_patch")

    if not chosen and any(_match(t, ["workspace", "project", "code", "file"], 0.72) for t in tokens):
        return TOOL_SPECS

    allow = set(chosen)
    return [spec for spec in TOOL_SPECS if spec["function"]["name"] in allow]


def _format_result(result: Dict[str, Any]) -> str:
    if isinstance(result, dict) and result.get("kind") == "music_search":
        rows = result.get("results", [])
        if not isinstance(rows, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"Music search for '{result.get('query', '')}'", "Top matches:"]
        for i, row in enumerate(rows[:8], 1):
            if not isinstance(row, dict):
                continue
            lines.append(f"{i}. {row.get('title', '')} (score={row.get('score', 0)})")
            lines.append(f"   {row.get('domain', '')}")
        best = result.get("best_match")
        if isinstance(best, dict):
            lines.append(f"Best match: {best.get('title', '')} (score={best.get('score', 0)})")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") == "music_play":
        return (
            f"[MUSIC PLAYING]\n"
            f"title: {result.get('title', '')}\n"
            f"pid: {result.get('pid', '')}\n"
            f"score: {result.get('score', 0)}\n"
            f"headless: {bool(result.get('headless', True))}"
        )

    if isinstance(result, dict) and result.get("kind") == "music_stop":
        if bool(result.get("stopped")):
            return f"[MUSIC STOPPED] pid={result.get('pid', '')}"
        return f"[MUSIC STOP] no active player ({result.get('reason', 'unknown')})"

    if isinstance(result, dict) and result.get("kind") == "music_queue_add":
        added = result.get("added", {})
        return (
            f"[QUEUED] #{result.get('position', '?')} — {added.get('title', '')}\n"
            f"Queue length: {result.get('queue_length', 0)}"
        )

    if isinstance(result, dict) and result.get("kind") == "music_queue_show":
        queue = result.get("queue", [])
        if not queue:
            return "Music queue is empty."
        lines = [f"Music Queue ({len(queue)} track(s)):"]
        for i, track in enumerate(queue, 1):
            lines.append(f"{i}. {track.get('title', 'Unknown')} (query: {track.get('query', '')})")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") == "music_queue_clear":
        return "[QUEUE CLEARED] Music queue is now empty."

    if isinstance(result, dict) and result.get("kind") == "music_queue_next":
        if bool(result.get("played")):
            return (
                f"[PLAYING NEXT] {result.get('title', '')}\n"
                f"pid: {result.get('pid', '')}\n"
                f"remaining in queue: {result.get('remaining_in_queue', 0)}"
            )
        return f"[QUEUE NEXT] Could not play next track — {result.get('reason', 'unknown')}"

    if isinstance(result, dict) and result.get("kind") == "music_current":
        if not bool(result.get("playing")):
            return "No music is currently playing."
        return (
            f"[MUSIC CURRENT]\n"
            f"title: {result.get('title', '')}\n"
            f"pid: {result.get('pid', '')}\n"
            f"engine: {result.get('engine', '')}\n"
            f"launcher: {result.get('launcher', '')}"
        )

    if isinstance(result, dict) and result.get("kind") == "system_control":
        lines = [
            f"[SYSTEM] action={result.get('action', '')} ok={bool(result.get('ok'))} amount={result.get('amount', 1)}"
        ]
        if result.get("path"):
            lines.append(f"path: {result.get('path', '')}")
        lines.append(f"stdout: {result.get('stdout', '')}")
        lines.append(f"stderr: {result.get('stderr', '')}")
        return "\n".join(lines).strip()

    if isinstance(result, dict) and result.get("kind") == "cron_status":
        return (
            f"Cron status\n"
            f"- jobs_total: {result.get('jobs_total', 0)}\n"
            f"- jobs_enabled: {result.get('jobs_enabled', 0)}\n"
            f"- jobs_due_now: {result.get('jobs_due_now', 0)}"
        )

    if isinstance(result, dict) and result.get("kind") == "cron_list":
        jobs = result.get("jobs", [])
        if not isinstance(jobs, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"Cron jobs: {len(jobs)}"]
        for row in jobs[:40]:
            if not isinstance(row, dict):
                continue
            jid = row.get("id", "")
            name = row.get("name", "")
            enabled = bool(row.get("enabled", True))
            next_at = row.get("state", {}).get("next_run_at_ms") if isinstance(row.get("state"), dict) else None
            lines.append(f"- {jid} | {name} | enabled={enabled} | next={next_at}")
        if len(jobs) > 40:
            lines.append("... [truncated in display]")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") == "cron_job":
        action = str(result.get("action", ""))
        job = result.get("job", {})
        if not isinstance(job, dict):
            return json.dumps(result, ensure_ascii=False, indent=2)
        return (
            f"Cron {action} complete\n"
            f"- id: {job.get('id', '')}\n"
            f"- name: {job.get('name', '')}\n"
            f"- enabled: {bool(job.get('enabled', True))}\n"
            f"- next_run_at_ms: {job.get('state', {}).get('next_run_at_ms') if isinstance(job.get('state'), dict) else None}"
        )

    if isinstance(result, dict) and result.get("kind") in {"cron_run", "cron_run_due", "cron_runs"}:
        if result.get("kind") == "cron_run":
            return (
                f"Cron run\n"
                f"- job_id: {result.get('job_id', '')}\n"
                f"- status: {result.get('status', '')}\n"
                f"- duration_ms: {result.get('duration_ms', '')}\n"
                f"- error: {result.get('error', '')}"
            )
        if result.get("kind") == "cron_run_due":
            ran = result.get("ran", [])
            if not isinstance(ran, list):
                return json.dumps(result, ensure_ascii=False, indent=2)
            lines = [f"Cron run_due executed: {len(ran)}"]
            for row in ran[:40]:
                if not isinstance(row, dict):
                    continue
                lines.append(f"- {row.get('job_id', '')}: {row.get('status', '')} ({row.get('duration_ms', '')} ms)")
            return "\n".join(lines)
        rows = result.get("runs", [])
        if not isinstance(rows, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"Cron runs for {result.get('job_id', '')}: {len(rows)}"]
        for row in rows[:40]:
            if not isinstance(row, dict):
                continue
            lines.append(f"- {row.get('ts_ms', '')}: {row.get('status', '')} {row.get('error', '')}")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") == "page_content":
        if not bool(result.get("ok")):
            return f"[FETCH FAILED] {result.get('url', '')}\nreason: {result.get('reason', 'unknown')}"
        content = str(result.get("content", ""))
        truncated = bool(result.get("truncated"))
        suffix = "\n... [truncated — ask to fetch more if needed]" if truncated else ""
        return f"[PAGE CONTENT] {result.get('url', '')}\ndomain: {result.get('domain', '')}\n\n{content}{suffix}"

    if isinstance(result, dict) and result.get("kind") == "search_and_fetch":
        query = str(result.get("query", ""))
        engine = str(result.get("engine", ""))
        fetched = result.get("fetched_pages", [])
        search_results = result.get("search_results", [])
        lines = [f"Search & Fetch results for: '{query}' (engine: {engine})"]
        if fetched:
            lines.append(f"\n--- Scraped content from {len(fetched)} page(s) ---")
            for i, page in enumerate(fetched, 1):
                lines.append(f"\n[Source {i}] {page.get('title', '')} ({page.get('domain', '')})")
                lines.append(f"URL: {page.get('url', '')}")
                lines.append(page.get("content", ""))
                if bool(page.get("truncated")):
                    lines.append("... [truncated]")
        else:
            lines.append("\n[No page content could be scraped — showing search results only]")
            for i, row in enumerate(search_results[:5], 1):
                title = str(row.get("title", ""))
                snippet = str(row.get("snippet", ""))
                url = str(row.get("url", ""))
                lines.append(f"{i}. {title}")
                if snippet:
                    lines.append(f"   {snippet}")
                if url:
                    lines.append(f"   {url}")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") in {"web_search", "news_search"}:
        rows = result.get("results", [])
        if not isinstance(rows, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        kind = str(result.get("kind"))
        engine = str(result.get("engine", ""))
        query = str(result.get("query", ""))
        include_urls = bool(result.get("include_urls", False))
        label = "News Brief" if kind == "news_search" else "Web Brief"
        lines = [f"{label} ({engine}) on '{query}'", "Key pointers:"]
        for i, row in enumerate(rows[:12], 1):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "")).strip()
            url = str(row.get("url", "")).strip()
            source = str(row.get("source", "")).strip()
            published = str(row.get("published", "")).strip()
            snippet = str(row.get("snippet", "")).strip()
            meta = " | ".join(x for x in [source or row.get("domain", ""), published] if x)
            lines.append(f"{i}. {title}".strip())
            if meta:
                lines.append(f"   {meta}")
            if snippet:
                lines.append(f"   {snippet}")
            if include_urls and url:
                lines.append(f"   {url}")
        if len(rows) > 12:
            lines.append("... [truncated in display]")
        if not include_urls:
            lines.append("Ask 'with links' if you want source URLs.")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("terminated") is True:
        proc = result.get("process", "")
        requested = result.get("requested", "")
        return f"[CLOSED] requested={requested} process={proc}".strip()

    if isinstance(result, dict) and result.get("launched") is True:
        app = result.get("app", "")
        pid = result.get("pid", "")
        cwd = result.get("cwd", ".")
        args = result.get("args", [])
        args_text = " ".join(str(a) for a in args) if isinstance(args, list) else ""
        return f"[LAUNCHED] {app} {args_text}\npid: {pid}\ncwd: {cwd}".strip()

    if isinstance(result, dict) and "argv" in result and "exit_code" in result:
        ok = bool(result.get("ok"))
        status = "OK" if ok else "FAILED"
        exit_code = result.get("exit_code")
        timed_out = bool(result.get("timed_out"))
        duration = result.get("duration_ms")
        cwd = result.get("cwd", ".")
        argv = result.get("argv", [])
        stdout = str(result.get("stdout", "") or "")
        stderr = str(result.get("stderr", "") or "")
        lines = [
            f"[{status}] exit={exit_code} timeout={timed_out} duration_ms={duration}",
            f"cwd: {cwd}",
            f"cmd: {' '.join(str(x) for x in argv)}",
        ]
        if stdout.strip():
            lines.append("stdout:")
            lines.append(stdout.rstrip())
        if stderr.strip():
            lines.append("stderr:")
            lines.append(stderr.rstrip())
        return "\n".join(lines)

    if isinstance(result, dict) and "path" in result and "content" in result:
        content = str(result.get("content", ""))
        head = content[:3000]
        truncated = len(content) > len(head)
        suffix = "\n... [truncated]" if truncated else ""
        return f"file: {result.get('path')}\n{head}{suffix}"

    if isinstance(result, dict) and "entries" in result:
        entries = result.get("entries", [])
        if not isinstance(entries, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"entries: {len(entries)} (truncated={bool(result.get('truncated'))})"]
        for item in entries[:120]:
            if not isinstance(item, dict):
                continue
            p = item.get("path", "")
            t = item.get("type", "")
            if t == "file":
                lines.append(f"FILE {p}")
            else:
                lines.append(f"DIR  {p}")
        if len(entries) > 120:
            lines.append("... [truncated in display]")
        return "\n".join(lines)

    if isinstance(result, dict) and "matches" in result:
        matches = result.get("matches", [])
        if not isinstance(matches, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [
            f"matches: {len(matches)} (truncated={bool(result.get('truncated'))}, engine={result.get('engine')})"
        ]
        lines.extend(str(m) for m in matches[:120])
        if len(matches) > 120:
            lines.append("... [truncated in display]")
        return "\n".join(lines)

    return json.dumps(result, ensure_ascii=False, indent=2)


def _first_path_after_prep(words: List[str]) -> str:
    preps = ["in", "inside", "from", "at", "on", "within", "under"]
    for i, w in enumerate(words):
        if _match(w.strip("\"'"), preps, 0.7):
            if i + 1 < len(words):
                return _normalize_human_path(" ".join(words[i + 1 :]))
            return "."
    return "."


def _looks_like_python_snippet(text: str) -> bool:
    raw = text.strip()
    lower = raw.lower()
    python_prefixes = (
        "print(",
        "import ",
        "from ",
        "def ",
        "class ",
        "for ",
        "while ",
        "if ",
        "with ",
        "x =",
        "y =",
        "z =",
    )
    if lower.startswith("python ") or lower.startswith("py "):
        return False
    if any(lower.startswith(p) for p in python_prefixes):
        return True
    if raw.endswith(")") and "(" in raw and " " not in raw.split("(", 1)[0]:
        return True
    return False


def _parse_local_intent(user_text: str, workspace_root: Path) -> Optional[Tuple[str, Dict[str, Any]]]:
    text = user_text.strip()
    tokens = _tokenize(text)
    words = text.split()
    lower_words = [w.lower().strip("\"'") for w in words]

    if not tokens:
        return None

    if tokens[0] in {"stop", "pause"} and len(tokens) == 1:
        return ("stop_music", {})

    if tokens[0] in {"stop", "pause"} and any(t in {"music", "song", "audio"} for t in tokens[1:]):
        return ("stop_music", {})

    if tokens[0] in {"play", "listen"}:
        if len(words) == 1:
            return ("__run_help", {"message": "Usage: play <song name>"})
        query = text.split(maxsplit=1)[1].strip().strip("\"'")
        if query:
            return ("play_music", {"query": query, "headless": True, "stop_current": True})

    if tokens[0] == "queue" or (tokens[0] in {"add", "enqueue"} and any(t in {"song", "music", "track"} for t in tokens)):
        if len(words) <= 1:
            return ("show_queue", {})
        query = text.split(maxsplit=1)[1].strip().strip("\"'")
        if query:
            return ("queue_music", {"query": query})

    if tokens[0] in {"next", "skip"} and any(t in {"song", "music", "track", "queue"} for t in tokens):
        return ("play_next_in_queue", {})

    if tokens[0] in {"show", "list", "view"} and any(t in {"queue"} for t in tokens[1:]):
        return ("show_queue", {})

    if tokens[0] in {"clear", "empty", "reset"} and any(t in {"queue"} for t in tokens[1:]):
        return ("clear_queue", {})

    if any(t in {"song", "music", "track"} for t in tokens) and any(
        t in {"what", "which", "name", "current", "now", "playing"} for t in tokens
    ):
        return ("current_music", {})

    has_volume = any(_match(t, ["volume", "sound", "audio", "loudness"], 0.72) for t in tokens)
    has_up = any(_match(t, ["up", "increase", "higher", "raise", "boost", "louder"], 0.72) for t in tokens)
    has_down = any(_match(t, ["down", "decrease", "lower", "reduce", "softer", "quieter"], 0.72) for t in tokens)
    has_desktop = any(_match(t, ["desktop"], 0.75) for t in tokens)
    has_show = any(_match(t, ["show", "minimize", "hide"], 0.74) for t in tokens)
    has_lock = any(_match(t, ["lock"], 0.75) for t in tokens)
    has_screen = any(_match(t, ["screen", "pc", "computer", "system"], 0.72) for t in tokens)
    has_mute = any(_match(t, ["mute", "unmute", "silent"], 0.72) for t in tokens)
    has_next = any(_match(t, ["next", "skip"], 0.72) for t in tokens)
    has_prev = any(_match(t, ["previous", "prev", "back"], 0.72) for t in tokens)
    has_media = any(_match(t, ["song", "track", "music", "audio", "media"], 0.72) for t in tokens)
    has_play_pause = any(_match(t, ["playpause", "pause", "resume", "play"], 0.72) for t in tokens) and has_media
    has_brightness = any(_match(t, ["brightness", "backlight"], 0.74) for t in tokens)
    has_wifi = any(_match(t, ["wifi", "wi-fi", "wlan", "wireless"], 0.72) for t in tokens)
    has_bluetooth = any(_match(t, ["bluetooth", "bt"], 0.72) for t in tokens)
    has_screenshot = any(_match(t, ["screenshot", "snapshot", "capture"], 0.72) for t in tokens) and any(
        _match(t, ["screen", "desktop"], 0.72) for t in tokens
    ) or any(_match(t, ["screenshot"], 0.72) for t in tokens)
    has_window = any(_match(t, ["window", "windows"], 0.72) for t in tokens)
    has_restore = any(_match(t, ["restore", "undo"], 0.72) for t in tokens)
    has_disable = any(_match(t, ["disable", "off", "turnoff", "disconnect"], 0.72) for t in tokens)
    has_enable = any(_match(t, ["enable", "on", "turnon", "connect"], 0.72) for t in tokens)

    if has_show and has_desktop:
        return ("system_control", {"action": "show_desktop", "amount": 1})
    if has_lock and has_screen:
        return ("system_control", {"action": "lock_screen", "amount": 1})
    if has_volume and has_up:
        return ("system_control", {"action": "volume_up", "amount": 6})
    if has_volume and has_down:
        return ("system_control", {"action": "volume_down", "amount": 6})
    if has_mute:
        return ("system_control", {"action": "mute_toggle", "amount": 1})
    if has_next and has_media:
        return ("system_control", {"action": "media_next", "amount": 1})
    if has_prev and has_media:
        return ("system_control", {"action": "media_prev", "amount": 1})
    if has_play_pause:
        return ("system_control", {"action": "media_play_pause", "amount": 1})
    if has_brightness and has_up:
        return ("system_control", {"action": "brightness_up", "amount": 10})
    if has_brightness and has_down:
        return ("system_control", {"action": "brightness_down", "amount": 10})
    if has_brightness:
        nums = [int(t) for t in tokens if t.isdigit()]
        if nums:
            return ("system_control", {"action": "brightness_set", "amount": max(1, min(nums[0], 100))})
    if has_wifi and has_disable:
        return ("system_control", {"action": "wifi_off", "amount": 1})
    if has_wifi and has_enable:
        return ("system_control", {"action": "wifi_on", "amount": 1})
    if has_bluetooth and has_disable:
        return ("system_control", {"action": "bluetooth_off", "amount": 1})
    if has_bluetooth and has_enable:
        return ("system_control", {"action": "bluetooth_on", "amount": 1})
    if has_screenshot:
        return ("system_control", {"action": "screenshot", "amount": 1})
    if has_window and has_show and not has_desktop:
        return ("system_control", {"action": "window_minimize_all", "amount": 1})
    if has_window and has_restore:
        return ("system_control", {"action": "window_restore_all", "amount": 1})

    if tokens[0] == "cron":
        if len(tokens) == 1:
            return ("cron", {"action": "status"})
        action = tokens[1]
        if action in {"status", "list"}:
            return ("cron", {"action": action})
        if action in {"run", "remove", "runs"}:
            if len(words) < 3:
                return ("__run_help", {"message": f"Usage: cron {action} <job_id>"})
            return ("cron", {"action": action, "job_id": words[2].strip()})
        if action == "due":
            return ("cron", {"action": "run_due"})

    if tokens[0] in {"close", "kill", "stop", "terminate", "quit"}:
        if len(words) == 1:
            return (
                "__run_help",
                {"message": "Usage: close <app>. Examples: close notepad | kill chrome"},
            )
        target_text = text.split(maxsplit=1)[1].strip().strip("\"'")
        if target_text:
            return ("terminate_app", {"app": target_text, "force": True})

    # Realtime web/news search (separate from workspace file search)
    news_tokens = {"news", "headline", "headlines", "latest"}
    web_tokens = {"web", "internet", "online", "google"}
    search_tokens = {"search", "find", "lookup"}
    link_tokens = {"link", "links", "url", "urls", "source", "sources"}
    has_news = any(t in news_tokens for t in tokens)
    has_web = any(t in web_tokens for t in tokens)
    has_search = any(t in search_tokens for t in tokens)
    wants_links = any(t in link_tokens for t in tokens)
    if has_news:
        query = _extract_quoted_text(text)
        if not query:
            filtered = [w for w in words if w.lower().strip("\"'") not in news_tokens | search_tokens | {"for", "about"}]
            query = " ".join(filtered).strip()
        query = query or "latest technology news"
        return ("search_news", {"query": query, "max_results": 8, "include_urls": wants_links})
    if has_web and has_search:
        query = _extract_quoted_text(text)
        if not query:
            filtered = [w for w in words if w.lower().strip("\"'") not in web_tokens | search_tokens | {"for", "about"}]
            query = " ".join(filtered).strip()
        if query:
            return ("search_web", {"query": query, "max_results": 8, "include_urls": wants_links})

    # Factual queries — use search_and_fetch to get real data not just links
    factual_triggers = {"price", "cost", "weather", "temperature", "rate", "how much", "what is",
                        "specs", "details", "score", "value", "definition", "meaning", "who is", "when did"}
    if any(trigger in text.lower() for trigger in factual_triggers):
        query = _extract_quoted_text(text) or text.strip()
        if query:
            return ("search_and_fetch", {"query": query, "fetch_top": 2})

    if tokens[0] in {"open", "launch", "start"}:
        if len(words) == 1:
            return (
                "__run_help",
                {"message": "Usage: open <app|file>. Examples: open notepad | open README.md"},
            )
        target_text = text.split(maxsplit=1)[1].strip().strip("\"'")
        if target_text:
            normalized_path = _normalize_human_path(target_text)
            try:
                resolved = fs_ops.resolve_safe_path(workspace_root, normalized_path)
                if resolved.exists() and resolved.is_file():
                    return ("read_file", {"path": normalized_path})
            except Exception:
                pass
            # If user mentions an extension-like token, prefer file read attempt.
            if "." in Path(normalized_path).name and " " not in Path(normalized_path).name:
                return ("read_file", {"path": normalized_path})
            return ("launch_app", {"app": target_text, "args": []})

    if tokens[0] in {"run", "exec", "execute", "cmd"}:
        if len(words) == 1:
            return (
                "__run_help",
                {
                    "message": "Usage: run <command>. Examples: run dir | run python -c \"print('hi')\" | run Get-ChildItem -Force",
                },
            )
        command_text = text.split(maxsplit=1)[1].strip()
        if command_text:
            if _looks_like_python_snippet(command_text):
                return (
                    "run_command",
                    {
                        "command": sys.executable,
                        "args": ["-c", command_text],
                        "use_shell": False,
                        "timeout_ms": 20000,
                    },
                )
            return ("run_command", {"command": command_text, "use_shell": True, "timeout_ms": 20000})

    has_list = any(_match(t, ["list", "show", "display", "ls"], 0.74) for t in tokens)
    has_files = any(_match(t, ["file", "files", "dir", "directory", "folder", "workspace", "project"], 0.72) for t in tokens)
    if has_list and has_files:
        return ("list_files", {"path": _first_path_after_prep(words), "max_entries": 300})

    if tokens[0] in {"read", "open", "cat"} and len(words) > 1:
        return ("read_file", {"path": _normalize_human_path(" ".join(words[1:]))})

    has_search = any(_match(t, ["search", "find", "grep", "contains", "lookup"], 0.72) for t in tokens)
    if has_search:
        query = _extract_quoted_text(text)
        path = _first_path_after_prep(words)
        if not query:
            idx = 0
            for i, w in enumerate(lower_words):
                if _match(w, ["search", "find", "grep", "contains", "lookup"], 0.72):
                    idx = i
                    break
            end = len(words)
            for i, w in enumerate(lower_words):
                if i <= idx:
                    continue
                if _match(w, ["in", "inside", "within", "under"], 0.7):
                    end = i
                    break
            query = " ".join(words[idx + 1 : end]).strip().strip("\"'")
        if query:
            if query.lower().startswith("for "):
                query = query[4:].strip()
            scope_tokens = {
                "workspace",
                "project",
                "repo",
                "repository",
                "codebase",
                "file",
                "files",
                "folder",
                "directory",
                "path",
                "here",
            }
            has_local_scope = any(t in scope_tokens for t in tokens)
            if has_local_scope:
                return ("search_text", {"query": query, "path": path, "max_results": 100})
            wants_links = any(t in {"link", "links", "url", "urls", "source", "sources"} for t in tokens)
            return ("search_web", {"query": query, "max_results": 8, "include_urls": wants_links})

    return None


def try_direct_local_command(user_text: str, workspace_root: Path) -> Optional[str]:
    parsed = _parse_local_intent(user_text, workspace_root)
    if not parsed:
        return None
    name, args = parsed
    if name == "__run_help":
        return str(args.get("message", "Usage: run <command>"))
    return _format_result(_call(name, args, workspace_root))


def _strip_blobs(content: Any) -> Any:
    """
    Strip base64 image blobs and huge JSON payloads from a message content field.
    Handles both string content and list-of-blocks (multimodal) content.
    """
    import re as _re
    if isinstance(content, str):
        # Strip inline base64 data URIs (data:image/...;base64,<blob>)
        stripped = _re.sub(
            r'data:image/[^;]+;base64,[A-Za-z0-9+/=]{200,}',
            '[IMAGE_DATA_REMOVED]',
            content,
        )
        # If the resulting string is still very large (>8000 chars), truncate it
        if len(stripped) > 8000:
            stripped = stripped[:8000] + "\n... [truncated to fit token limit]"
        return stripped
    if isinstance(content, list):
        # Multimodal content blocks — remove image_url blocks entirely
        return [
            block for block in content
            if not (isinstance(block, dict) and block.get("type") == "image_url")
        ] or "[IMAGE_REMOVED]"
    return content


def _estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    """
    Rough token estimator: chars / 4.
    Fast enough to call before every LLM request.
    """
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block.get("text", "")))
        # Also count tool_calls if present
        if m.get("tool_calls"):
            total += len(str(m["tool_calls"]))
    return total // 4  # rough chars-to-tokens ratio


def compact_messages(
    messages: List[Dict[str, Any]],
    keep_tail: int = 8,
    char_limit: int = 120_000,   # ~30k tokens safety margin below 64k limit
) -> List[Dict[str, Any]]:
    """
    Smart message compactor — Token Limit Guardian.

    Strategy (in order):
    1. Strip base64 blobs + large image_url blocks from ALL messages first.
    2. Drop old tool messages (role='tool') beyond the last 4 turns — they're
       the biggest offenders (search results, file contents, vision JSON).
    3. If still over char_limit, drop oldest non-system messages until we fit.
    4. Always keep: system message + last `keep_tail` messages.
    5. Insert a synthetic system note about what was trimmed.
    """
    if not messages:
        return messages

    # Step 1: Strip blobs from every message (in-place copy)
    cleaned: List[Dict[str, Any]] = []
    for m in messages:
        m2 = dict(m)
        if "content" in m2:
            m2["content"] = _strip_blobs(m2["content"])
        cleaned.append(m2)

    # Step 2: If within budget, return as-is
    if _estimate_tokens(cleaned) * 4 <= char_limit:
        return cleaned

    # Step 3: Separate system message
    system_msg = cleaned[0] if cleaned and cleaned[0].get("role") == "system" else None
    rest = cleaned[1:] if system_msg else cleaned

    # Step 4: Drop old tool messages first (biggest savings)
    # Keep only tool messages from the last 4 pairs (8 messages)
    last_n = rest[-8:] if len(rest) > 8 else rest
    older = rest[:-8] if len(rest) > 8 else []
    # Filter older messages — drop tool results, keep user/assistant
    older_filtered = [
        m for m in older
        if m.get("role") in ("user", "assistant") and m.get("content", "").strip()
    ]
    rest = older_filtered + last_n

    # Step 5: If still over budget, trim oldest until fit
    trimmed_count = 0
    while rest and _estimate_tokens(([system_msg] if system_msg else []) + rest) * 4 > char_limit:
        rest.pop(0)
        trimmed_count += 1

    # Always keep at minimum keep_tail messages
    if len(rest) > keep_tail:
        pass  # already fine
    elif len(cleaned) > keep_tail:
        rest = cleaned[-keep_tail:]
        trimmed_count = len(cleaned) - keep_tail - (1 if system_msg else 0)

    # Step 6: Insert trim notice as a system message
    result: List[Dict[str, Any]] = []
    if system_msg:
        result.append(system_msg)
    if trimmed_count > 0:
        result.append({
            "role": "system",
            "content": (
                f"[Token Guardian] Context trimmed: {trimmed_count} older messages removed "
                f"to stay within the model's token limit. Recent conversation follows."
            ),
        })
    result.extend(rest)
    return result
