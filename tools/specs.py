"""Tool specification schemas for A.N.K.I.T.A.

Auto-collected by tools/engine.py.
DO NOT import this directly — use tools.engine.TOOL_SPECS.
"""
from typing import Any, Dict, List


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
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate an AI image from a text prompt using Pollinations.ai. "
                "Free, no API key needed. Saves the result as a PNG to Desktop. "
                "After a successful generation, always emit 'TELEGRAM_IMAGE: <path>' "
                "so ANKITA auto-delivers the photo inline in Telegram. "
                "Models: flux (default, best quality), turbo (fast), "
                "flux-realism (photorealistic), dreamshaper (artistic/fantasy), "
                "flux-anime (anime/manga), flux-3d (CGI renders)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Detailed text description of the image to generate.",
                    },
                    "width": {
                        "type": "integer",
                        "description": "Image width in pixels. Recommended: 512, 768, 1024 (default).",
                    },
                    "height": {
                        "type": "integer",
                        "description": "Image height in pixels. Recommended: 512, 768, 1024 (default).",
                    },
                    "model": {
                        "type": "string",
                        "enum": ["flux", "turbo", "flux-realism", "dreamshaper", "flux-anime", "flux-3d"],
                        "description": "Image model. Default: flux.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional absolute path to save the image. Defaults to Desktop.",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
]

