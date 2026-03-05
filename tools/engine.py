import json
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from memory import get_memory_manager

from . import content_ops
from . import cron_ops
from . import deep_research as deep_research_mod
from . import desktop_ops
from . import fs_ops
from . import music_ops
from . import realtime_search
from . import system_ops
from . import terminal_ops
from . import sheets_ops
from . import youtube_ops
from . import figma_ops
from . import whatsapp_ops
from . import contacts_ops
from . import camera_ops
from . import app_manager
from . import voice_ops
from . import health_ops
from . import sync_ops
from . import maps_ops
from . import task_ops
from . import report_ops


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
            "name": "remember",
            "description": "Store a durable memory fact or preference for future turns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "Fact to remember, e.g. 'user prefers markdown reports'."},
                    "key": {"type": "string", "description": "Optional key/category label, e.g. 'music preferences'."},
                    "value": {"type": "string", "description": "Optional value for key-value memory."},
                    "interface": {"type": "string", "description": "Optional source tag, default 'tool'."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Retrieve relevant stored memories by query, or recent memories if query omitted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to recall, e.g. 'music preferences'."},
                    "limit": {"type": "integer", "description": "Maximum items to return (default 8)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Delete memories matching a query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query used to find memories to delete."},
                    "limit": {"type": "integer", "description": "Maximum matches to delete (default 20)."},
                },
                "required": ["query"],
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
                "Smart timeout (auto-detected based on command type, max 600s). Destructive commands are blocked. "
                "Supports persistent session state (cwd, environment variables)."
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
                        "description": "Max seconds to wait before killing the command (auto-detected if not specified, max 600)",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory for the command. Defaults to session CWD (initially user home). Use absolute paths or environment variables like %USERPROFILE%.",
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
            "name": "git_op",
            "description": (
                "Smart git wrapper with proper error handling and structured output. "
                "Actions: status (show changes), log (recent commits), diff (changes summary), "
                "add (stage all), commit (with message), push (to origin), pull (from origin), "
                "branch (list branches), stash (save work), reset (undo last commit). "
                "Auto-detects repo, handles errors, returns structured data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "log", "diff", "add", "commit", "push", "pull", "branch", "stash", "reset"],
                        "description": "Git operation to perform",
                    },
                    "message": {"type": "string", "description": "Commit message (required for commit action)"},
                    "branch": {"type": "string", "description": "Branch name (for branch/push/pull actions)"},
                    "path": {"type": "string", "description": "Repository path (defaults to session CWD)"},
                    "confirm": {"type": "boolean", "description": "Required for destructive actions (reset)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "process_op",
            "description": (
                "Process management for starting, stopping, and checking processes. "
                "Actions: start_background (run detached process), list_background (show running), "
                "kill_background (stop process), is_running (check if alive), port_check (what's using port). "
                "Tracks background processes started this session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start_background", "list_background", "kill_background", "is_running", "port_check"],
                        "description": "Process operation to perform",
                    },
                    "command": {"type": "string", "description": "Command to run (for start_background)"},
                    "name": {"type": "string", "description": "Process name/label (for start_background, kill_background, is_running)"},
                    "port": {"type": "integer", "description": "Port number (for port_check)"},
                    "pid": {"type": "integer", "description": "Process ID (for kill_background, is_running)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fast_file_search",
            "description": "Fast, bounded file search by name/path pattern. Uses ripgrep if available; falls back to PowerShell. Returns structured results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to match against full path strings."},
                    "path": {"type": "string", "description": "Root directory to search (defaults to workspace root if omitted)."},
                    "glob": {"type": "string", "description": "Optional glob filter (e.g., '*.py')."},
                    "max_results": {"type": "integer", "description": "Maximum results to return (default 50, max 200)."},
                    "case_sensitive": {"type": "boolean", "description": "Whether pattern matching is case-sensitive (default false)."},
                },
                "required": ["pattern"],
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
            "name": "read_rich_file",
            "description": "Read and extract text from rich file formats (PDF, DOCX, XLSX, CSV, PPTX, images, ZIP). Auto-detects format and extracts readable content. Use this for non-plain-text files.",
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
            "name": "pc_search",
            "description": "Search for files across the entire PC by name pattern. Searches Desktop, Documents, Downloads, Pictures.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search pattern (supports wildcards like *.txt)"},
                    "file_types": {"type": "array", "items": {"type": "string"}, "description": "Optional list of extensions to filter (e.g. ['.pdf', '.docx'])"},
                    "max_results": {"type": "integer", "description": "Maximum number of results to return (default 50)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trash_path",
            "description": "Move a file or directory to the recycle bin instead of permanent deletion. Safer than delete_path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to move to trash"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disk_analysis",
            "description": "Analyze disk usage by directory. Shows size breakdown of subdirectories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory to analyze (default '.')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diff_files",
            "description": "Compare two text files and show differences in unified diff format.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file1": {"type": "string", "description": "First file path"},
                    "file2": {"type": "string", "description": "Second file path"},
                },
                "required": ["file1", "file2"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bulk_op",
            "description": "Perform batch operations on multiple files (move, copy, delete, trash).",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["move", "copy", "delete", "trash"], "description": "Operation to perform"},
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "List of file paths to operate on"},
                    "destination": {"type": "string", "description": "Destination directory (required for move/copy)"},
                },
                "required": ["operation", "paths"],
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
            "name": "scrape_structured",
            "description": (
                "Extract structured data from any URL: tables → CSV-ready rows, links, emails, phone numbers, or embedded JSON. "
                "Use when user wants 'get all rows from this table', 'find all emails on this page', 'extract the data from X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to scrape"},
                    "extract": {
                        "type": "string",
                        "enum": ["tables", "links", "emails", "phones", "json"],
                        "description": "Type of data to extract: tables, links, emails, phones, or json"
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_search",
            "description": (
                "Research two things in parallel and return structured comparison data. "
                "Use for 'X vs Y', 'compare X and Y', 'which is better X or Y'. "
                "Runs parallel searches and synthesizes a head-to-head comparison."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_a": {"type": "string", "description": "First item to compare"},
                    "item_b": {"type": "string", "description": "Second item to compare"},
                    "aspects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional aspects to compare (e.g., ['price', 'specs', 'pros', 'cons'])"
                    },
                },
                "required": ["item_a", "item_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_monitor",
            "description": (
                "Track if a web page has changed since last visit. "
                "Actions: 'add' (start monitoring), 'check' (check all for changes), 'list' (show monitored pages), 'remove' (stop monitoring). "
                "Use for 'tell me when this page changes', 'monitor this URL', 'notify me if X updates'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "check", "list", "remove"],
                        "description": "Action to perform"
                    },
                    "url": {"type": "string", "description": "URL to monitor (required for add/remove)"},
                    "keyword": {"type": "string", "description": "Optional keyword to watch for"},
                    "label": {"type": "string", "description": "Optional label for the monitor"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "multi_search",
            "description": (
                "Run multiple independent search queries in parallel. "
                "Perfect for: list comparisons, batch lookups, research on N topics at once. "
                "Use when user asks about multiple separate things: 'find best X, Y, and Z', 'research A, B, C'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of search queries to run in parallel"
                    },
                    "fetch_top": {
                        "type": "integer",
                        "description": "Number of pages to fetch per query (default 2)"
                    },
                },
                "required": ["queries"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fact_check",
            "description": (
                "Verify a claim by fetching N independent sources and detecting conflicts. "
                "Returns verified/disputed/unverified verdict with confidence percentage. "
                "Use for 'is it true that...', 'fact check this:', 'verify this claim', 'did X really say'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "The claim to verify"},
                    "sources": {
                        "type": "integer",
                        "description": "Number of sources to check (default 4)"
                    },
                },
                "required": ["claim"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_reddit",
            "description": (
                "Search Reddit for crowd-sourced opinions and discussions. "
                "Use for 'what does reddit think of X', 'reddit best X', 'has anyone had this problem', "
                "'what do people say about Y'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "subreddit": {
                        "type": "string",
                        "description": "Optional subreddit name (e.g., 'python', 'programming')"
                    },
                    "max_posts": {
                        "type": "integer",
                        "description": "Maximum number of posts to return (default 5)"
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_stackoverflow",
            "description": (
                "Search Stack Overflow for programming solutions and technical answers. "
                "Use for 'how to fix X error', 'Stack Overflow Y solution', technical programming questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default 5)"
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "image_search",
            "description": (
                "Search for images on the web via DuckDuckGo Images. "
                "Optionally download the top result to Desktop. "
                "Use for 'find images of X', 'download logo of Y', 'get a photo of Z'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Image search query"},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of images to return (default 5)"
                    },
                    "download": {
                        "type": "boolean",
                        "description": "If true, downloads the top result to Desktop (default false)"
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarise_url",
            "description": (
                "Fetch a URL and produce a targeted summary. "
                "Styles: 'bullets' (N bullet points), 'tldr' (2-3 sentences), 'eli5' (simple explanation), "
                "'key_stats' (numbers only), 'pros_cons' (pros and cons lists). "
                "Use when user pastes a URL and says 'summarise', 'tldr', 'what does this say'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to summarise"},
                    "style": {
                        "type": "string",
                        "enum": ["bullets", "tldr", "eli5", "key_stats", "pros_cons"],
                        "description": "Summary style (default 'bullets')"
                    },
                    "max_bullets": {
                        "type": "integer",
                        "description": "Number of bullet points for bullets style (default 7)"
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trending_topics",
            "description": (
                "Fetch what's trending right now across Hacker News, Reddit, and news sources. "
                "Use for 'what's trending', 'what's hot today', 'what are people talking about', 'top stories right now'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["general", "tech", "finance", "sports", "entertainment", "science"],
                        "description": "Category of trending topics (default 'general')"
                    },
                    "region": {
                        "type": "string",
                        "description": "Region code (default 'US')"
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_to_dataset",
            "description": (
                "Research a topic and extract structured data rows from web results ready for CSV/JSON export. "
                "Use for 'build a table of X', 'give me a list of Y with their Z', 'make a spreadsheet of', "
                "'extract all X and their Y from the web'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Research query"},
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of column names for the dataset"
                    },
                    "max_rows": {
                        "type": "integer",
                        "description": "Maximum number of rows to extract (default 20)"
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["json", "csv"],
                        "description": "Output format (default 'json')"
                    },
                },
                "required": ["query"],
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
    {
        "type": "function",
        "function": {
            "name": "camera_control",
            "description": (
                "Control camera operations: take burst photos, record video clips, scan QR codes. "
                "Uses LLM for intelligent quality assessment and decision-making."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["burst_photos", "record_video", "scan_qr"],
                        "description": "The camera action to perform.",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of photos for burst_photos (default 5).",
                    },
                    "interval": {
                        "type": "number",
                        "description": "Seconds between burst photos (default 2.0).",
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Video duration in seconds for record_video (default 10).",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "QR scan timeout in seconds (default 5).",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_manager",
            "description": (
                "Manage applications: list running apps, close/restart apps with fuzzy name matching, "
                "find top RAM/CPU hogs. Uses LLM for intelligent app name disambiguation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list_running", "close_app", "restart_app", "top_ram_hog"],
                        "description": "The app management action to perform.",
                    },
                    "name": {
                        "type": "string",
                        "description": "App name for close_app or restart_app (fuzzy matching supported).",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Force kill for close_app (default false).",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "voice_control",
            "description": (
                "Text-to-speech operations: speak text aloud, list available voices, "
                "speak with emotional tone. Uses LLM to enhance naturalness and adjust parameters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["speak", "list_voices", "speak_with_emotion"],
                        "description": "The voice action to perform.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to speak for speak or speak_with_emotion actions.",
                    },
                    "rate": {
                        "type": "integer",
                        "description": "Speech rate 50-250 (default 150).",
                    },
                    "volume": {
                        "type": "integer",
                        "description": "Volume 0-100 (default 100).",
                    },
                    "emotion": {
                        "type": "string",
                        "description": "Emotion for speak_with_emotion: happy, sad, excited, calm, urgent, angry.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_health",
            "description": (
                "System diagnostics: full health report (CPU, RAM, disk, temp), "
                "top processes by CPU/RAM, disk health check. Uses LLM for intelligent health analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["full_report", "top_processes", "disk_health"],
                        "description": "The health check action to perform.",
                    },
                    "n": {
                        "type": "integer",
                        "description": "Number of top processes to return (default 5).",
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["cpu", "ram"],
                        "description": "Sort processes by cpu or ram (default cpu).",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_sync",
            "description": (
                "File organization and backup: organize Desktop by file type, "
                "zip folders, quick backup, smart cleanup. Uses LLM for intelligent categorization."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["organize_desktop", "zip_folder", "quick_backup", "smart_cleanup"],
                        "description": "The file sync action to perform.",
                    },
                    "folder_path": {
                        "type": "string",
                        "description": "Folder path for zip_folder action.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Alias for folder_path/directory (prompt compatibility).",
                    },
                    "source": {
                        "type": "string",
                        "description": "Source path for quick_backup action.",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Destination path for quick_backup action.",
                    },
                    "directory": {
                        "type": "string",
                        "description": "Directory path for smart_cleanup action.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Dry run mode for smart_cleanup (default true).",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "window_layout",
            "description": (
                "Window layout controls: snap active window left/right/up/down, enable focus mode "
                "(show desktop), tile windows, or cascade windows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "snap_left",
                            "snap_right",
                            "snap_up",
                            "snap_down",
                            "focus_mode",
                            "tile_windows",
                            "cascade_windows",
                        ],
                        "description": "The window layout action to perform.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "maps_op",
            "description": (
                "Maps and navigation operations: get routes, search places, calculate distances, "
                "check traffic, geocode addresses. Uses free OpenStreetMap services by default; "
                "Google Maps is optional when configured."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["navigate", "search_places", "distance", "traffic", "geocode", "reverse_geocode"],
                        "description": "The maps operation to perform.",
                    },
                    "origin": {
                        "type": "string",
                        "description": "Starting location (address or coordinates).",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Ending location (address or coordinates).",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query for places or geocoding.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["driving", "walking", "bicycling", "transit"],
                        "description": "Travel mode (default: driving).",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_op",
            "description": (
                "Task management: add tasks with priorities and deadlines, list/filter tasks, "
                "mark complete, get overdue tasks, view summary. Auto-schedules cron reminders."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "list", "update", "complete", "delete", "overdue", "summary"],
                        "description": "The task operation to perform.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Task description/title.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                        "description": "Task priority (default: medium).",
                    },
                    "deadline": {
                        "type": "string",
                        "description": "Deadline in natural format (e.g., 'Friday', '2024-12-25', 'in 3 days').",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tags for categorization.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "done", "cancelled"],
                        "description": "Task status (default: pending).",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task ID for update/complete/delete operations.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_pdf",
            "description": (
                "Generate structured reports with sections, tables, and charts. "
                "Exports to PDF or Markdown format. Saves to Desktop by default."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Report title.",
                    },
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "content": {
                                    "type": "string",
                                    "description": "Section content (text, JSON string for tables/lists, or code)"
                                },
                                "type": {
                                    "type": "string",
                                    "enum": ["text", "table", "list", "code"],
                                    "description": "Section content type.",
                                },
                                "language": {"type": "string", "description": "Language for code blocks."},
                            },
                        },
                        "description": "List of report sections.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output file path (defaults to Desktop with timestamp).",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["pdf", "md"],
                        "description": "Output format (default: pdf).",
                    },
                },
                "required": ["title", "sections"],
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


def _call(name: str, args: Dict[str, Any], workspace_root: Path, agent_name: Optional[str] = None) -> Dict[str, Any]:
    # FileAgent gets unrestricted access to the entire PC
    unrestricted = (agent_name == "FileAgent")
    
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
    if name == "remember":
        mem = get_memory_manager(workspace_root)
        key = str(args.get("key", "")).strip()
        value = str(args.get("value", "")).strip()
        fact = str(args.get("fact", "")).strip()
        if not fact and key and value:
            fact = f"{key}: {value}"
        return mem.remember(
            fact=fact,
            interface=str(args.get("interface", "tool")),
        )
    if name == "recall":
        mem = get_memory_manager(workspace_root)
        rows = mem.recall(
            query=str(args.get("query", "")),
            limit=int(args.get("limit", 8)),
        )
        return {
            "kind": "memory_recall",
            "query": str(args.get("query", "")),
            "count": len(rows),
            "items": rows,
        }
    if name == "forget":
        mem = get_memory_manager(workspace_root)
        return mem.forget(
            query=str(args.get("query", "")),
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
            timeout=int(args.get("timeout")) if args.get("timeout") is not None else None,
            cwd=str(args.get("cwd")) if args.get("cwd") is not None else None,
        )
    if name == "fast_file_search":
        return terminal_ops.fast_file_search(
            pattern=str(args.get("pattern", "")),
            path=str(args.get("path")) if args.get("path") is not None else None,
            glob=str(args.get("glob")) if args.get("glob") is not None else None,
            max_results=int(args.get("max_results", 50)),
            case_sensitive=bool(args.get("case_sensitive", False)),
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
    if name == "git_op":
        return terminal_ops.git_op(
            action=str(args.get("action", "")),
            message=str(args.get("message")) if args.get("message") else None,
            branch=str(args.get("branch")) if args.get("branch") else None,
            path=str(args.get("path")) if args.get("path") else None,
            confirm=bool(args.get("confirm", False)),
        )
    if name == "process_op":
        return terminal_ops.process_op(
            action=str(args.get("action", "")),
            command=str(args.get("command")) if args.get("command") else None,
            name=str(args.get("name")) if args.get("name") else None,
            port=int(args.get("port")) if args.get("port") is not None else None,
            pid=int(args.get("pid")) if args.get("pid") is not None else None,
        )
    if name == "list_files":
        return fs_ops.list_files(workspace_root, path=str(args.get("path", ".")), max_entries=int(args.get("max_entries", 200)), unrestricted=unrestricted)
    if name == "read_file":
        return fs_ops.read_file(workspace_root, path=str(args.get("path", "")), unrestricted=unrestricted)
    if name == "read_rich_file":
        return fs_ops.read_rich_file(workspace_root, path=str(args.get("path", "")), unrestricted=unrestricted)
    if name == "search_text":
        return fs_ops.search_text(
            workspace_root,
            query=str(args.get("query", "")),
            path=str(args.get("path", ".")),
            max_results=int(args.get("max_results", 100)),
            unrestricted=unrestricted,
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
            unrestricted=unrestricted,
        )
    if name == "move_path":
        return fs_ops.move_path(
            workspace_root,
            src=str(args.get("src", "")),
            dst=str(args.get("dst", "")),
            overwrite=bool(args.get("overwrite", False)),
            unrestricted=unrestricted,
        )
    if name == "copy_path":
        return fs_ops.copy_path(
            workspace_root,
            src=str(args.get("src", "")),
            dst=str(args.get("dst", "")),
            overwrite=bool(args.get("overwrite", False)),
            recursive=bool(args.get("recursive", False)),
            unrestricted=unrestricted,
        )
    if name == "make_dir":
        return fs_ops.make_dir(
            workspace_root,
            path=str(args.get("path", "")),
            parents=bool(args.get("parents", True)),
            exist_ok=bool(args.get("exist_ok", True)),
            unrestricted=unrestricted,
        )
    if name == "file_info":
        return fs_ops.file_info(workspace_root, path=str(args.get("path", "")), unrestricted=unrestricted)
    if name == "pc_search":
        return fs_ops.pc_search(
            query=str(args.get("query", "")),
            file_types=args.get("file_types"),
            max_results=int(args.get("max_results", 50)),
        )
    if name == "trash_path":
        return fs_ops.trash_path(
            workspace_root,
            path=str(args.get("path", "")),
            unrestricted=unrestricted,
        )
    if name == "disk_analysis":
        return fs_ops.disk_analysis(
            workspace_root,
            path=str(args.get("path", ".")),
            unrestricted=unrestricted,
        )
    if name == "diff_files":
        return fs_ops.diff_files(
            workspace_root,
            file1=str(args.get("file1", "")),
            file2=str(args.get("file2", "")),
            unrestricted=unrestricted,
        )
    if name == "bulk_op":
        return fs_ops.bulk_op(
            workspace_root,
            operation=str(args.get("operation", "")),
            paths=args.get("paths", []),
            destination=str(args.get("destination")) if args.get("destination") else None,
            unrestricted=unrestricted,
        )
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
    if name == "scrape_structured":
        return realtime_search.scrape_structured(
            url=str(args.get("url", "")),
            extract=str(args.get("extract", "tables")),
        )
    if name == "compare_search":
        return realtime_search.compare_search(
            item_a=str(args.get("item_a", "")),
            item_b=str(args.get("item_b", "")),
            aspects=args.get("aspects"),
        )
    if name == "web_monitor":
        return realtime_search.web_monitor(
            action=str(args.get("action", "")),
            url=str(args.get("url")) if args.get("url") else None,
            keyword=str(args.get("keyword")) if args.get("keyword") else None,
            label=str(args.get("label")) if args.get("label") else None,
        )
    if name == "multi_search":
        return realtime_search.multi_search(
            queries=args.get("queries", []),
            fetch_top=int(args.get("fetch_top", 2)),
        )
    if name == "fact_check":
        return realtime_search.fact_check(
            claim=str(args.get("claim", "")),
            sources=int(args.get("sources", 4)),
        )
    if name == "search_reddit":
        return realtime_search.search_reddit(
            query=str(args.get("query", "")),
            subreddit=str(args.get("subreddit")) if args.get("subreddit") else None,
            max_posts=int(args.get("max_posts", 5)),
        )
    if name == "search_stackoverflow":
        return realtime_search.search_stackoverflow(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 5)),
        )
    if name == "image_search":
        return realtime_search.image_search(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 5)),
            download=bool(args.get("download", False)),
        )
    if name == "summarise_url":
        return realtime_search.summarise_url(
            url=str(args.get("url", "")),
            style=str(args.get("style", "bullets")),
            max_bullets=int(args.get("max_bullets", 7)),
        )
    if name == "trending_topics":
        return realtime_search.trending_topics(
            category=str(args.get("category", "general")),
            region=str(args.get("region", "US")),
        )
    if name == "web_to_dataset":
        return realtime_search.web_to_dataset(
            query=str(args.get("query", "")),
            columns=args.get("columns"),
            max_rows=int(args.get("max_rows", 20)),
            output_format=str(args.get("output_format", "json")),
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

    # ── New Tools with LLM Integration ────────────────────────────────────────
    if name == "camera_control":
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return camera_ops.camera_control(
            action=str(args.get("action", "")),
            runtime=_runtime,
            count=int(args.get("count", 5)),
            interval=float(args.get("interval", 2.0)),
            duration=int(args.get("duration", 10)),
            timeout=int(args.get("timeout", 5)),
        )
    
    if name == "app_manager":
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return app_manager.app_manager(
            action=str(args.get("action", "")),
            runtime=_runtime,
            name=str(args.get("name", "")),
            force=bool(args.get("force", False)),
        )
    
    if name == "voice_control":
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return voice_ops.voice_control(
            action=str(args.get("action", "")),
            runtime=_runtime,
            text=str(args.get("text", "")),
            rate=int(args.get("rate", 150)),
            volume=int(args.get("volume", 100)),
            emotion=str(args.get("emotion", "neutral")),
        )
    
    if name == "system_health":
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return health_ops.system_health(
            action=str(args.get("action", "")),
            runtime=_runtime,
            n=int(args.get("n", 5)),
            sort_by=str(args.get("sort_by", "cpu")),
        )
    
    if name == "file_sync":
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return sync_ops.file_sync(
            action=str(args.get("action", "")),
            runtime=_runtime,
            folder_path=str(args.get("folder_path") or args.get("path") or ""),
            source=str(args.get("source", "")),
            destination=str(args.get("destination")) if args.get("destination") else None,
            directory=str(args.get("directory") or args.get("path") or ""),
            dry_run=bool(args.get("dry_run", True)),
        )
    
    if name == "window_layout":
        return system_ops.window_layout(
            action=str(args.get("action", "")),
        )
    
    if name == "maps_op":
        return maps_ops.maps_op(
            action=str(args.get("action", "")),
            origin=str(args.get("origin")) if args.get("origin") else None,
            destination=str(args.get("destination")) if args.get("destination") else None,
            query=str(args.get("query")) if args.get("query") else None,
            mode=str(args.get("mode", "driving")),
        )
    
    if name == "task_op":
        return task_ops.task_op(
            action=str(args.get("action", "")),
            title=str(args.get("title")) if args.get("title") else None,
            priority=str(args.get("priority", "medium")),
            deadline=str(args.get("deadline")) if args.get("deadline") else None,
            tags=args.get("tags") if isinstance(args.get("tags"), list) else None,
            status=str(args.get("status", "pending")),
            task_id=str(args.get("task_id")) if args.get("task_id") else None,
        )
    
    if name == "generate_pdf":
        return report_ops.generate_pdf(
            title=str(args.get("title", "")),
            sections=args.get("sections", []),
            output_path=str(args.get("output_path")) if args.get("output_path") else None,
            format=str(args.get("format", "pdf")),
        )

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


def execute_tool_call(tool_call: Dict[str, Any], workspace_root: Path, agent_name: Optional[str] = None) -> Dict[str, Any]:
    fn = tool_call.get("function", {})
    name = str(fn.get("name", ""))
    raw_args = fn.get("arguments", "{}")

    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
    except json.JSONDecodeError as err:
        raise ValueError(f"Invalid JSON args for {name}: {err}") from err

    if not isinstance(args, dict):
        raise ValueError(f"Tool args must be an object for {name}")

    result = _call(name, args, workspace_root, agent_name=agent_name)
    # 💎 Prism Protocol: hard-cap ALL tool outputs before they enter the context window
    result = _hard_cap(result)
    return {"ok": True, "tool": name, "result": result}


def select_tools_for_user_text(user_text: str) -> List[Dict[str, Any]]:
    """
    LLM-powered tool selector — replaces brittle keyword matching.
    Asks the LLM which tools are needed for the user's request.
    Falls back to all tools on error.
    """
    try:
        from llm import build_runtime_from_env, call_chat_once
        
        # Build a compact tool list for the LLM
        tool_names = [spec["function"]["name"] for spec in TOOL_SPECS]
        tool_descriptions = {
            spec["function"]["name"]: spec["function"]["description"]
            for spec in TOOL_SPECS
        }
        
        system_prompt = f"""You are ANKITA's Tool Selector. Your job is to identify which tools are needed for a user request.

Available tools:
{json.dumps(tool_descriptions, indent=2)}

Analyze the user request and return ONLY the tool names needed (as a JSON array of strings).
If multiple tools might be needed, include all relevant ones.
If unsure, include tools that might be useful.

Respond ONLY with valid JSON array. No explanation. No markdown.
["tool_name1", "tool_name2", ...]"""

        runtime = build_runtime_from_env()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        
        response = call_chat_once(runtime, messages, tools=None, max_tokens=200)
        raw = (response.get("content") or "").strip()
        
        # Parse JSON — strip fences if present
        clean = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        selected_names = json.loads(clean)
        
        if not isinstance(selected_names, list):
            raise ValueError("LLM response is not a list")
        
        # Filter TOOL_SPECS to only include selected tools
        selected_tools = [
            spec for spec in TOOL_SPECS 
            if spec["function"]["name"] in selected_names
        ]
        
        if selected_tools:
            print(f"[ToolSelector] Selected {len(selected_tools)} tools: {[s['function']['name'] for s in selected_tools]}", flush=True)
            return selected_tools
        
        # If no tools selected, return all (safe fallback)
        print(f"[ToolSelector] No tools selected, returning all", flush=True)
        return TOOL_SPECS
        
    except Exception as e:
        print(f"[ToolSelector] ⚠️ LLM selection failed: {e} — returning all tools", flush=True)
        return TOOL_SPECS


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
