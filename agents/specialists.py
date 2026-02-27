"""
Specialist sub-agents for A.N.K.I.T.A multi-agent architecture.

Each specialist has access only to its domain-specific tools,
making it focused and accurate — avoiding tool confusion.
"""
from __future__ import annotations

# DreamAgent is standalone (not Supervisor-routed) — exposed here for convenience
from agents.dream_agent import DreamAgent  # noqa: F401

from pathlib import Path
from typing import Any, Dict, List

from tools.engine import TOOL_SPECS

# ---------------------------------------------------------------------------
# Tool subsets by domain
# ---------------------------------------------------------------------------

_FILE_TOOLS = {"list_files", "read_file", "read_file_lines", "write_file", "edit_file",
               "edit_file_lines", "search_text", "rename_path", "delete_path", "move_path",
               "copy_path", "make_dir", "file_info", "apply_patch"}

_WEB_TOOLS = {"search_web", "search_news", "search_and_fetch", "fetch_page_content", "write_content"}

_SYSTEM_TOOLS = {"system_control", "launch_app", "terminate_app"}

_MUSIC_TOOLS = {"play_music", "stop_music", "search_music", "current_music"}

_CODE_TOOLS = {"run_command", "apply_patch", "execute_shell", "read_file",
               "read_file_lines", "edit_file_lines", "write_file"}
_TERMINAL_TOOLS = {"execute_shell", "read_file"}

_CRON_TOOLS = {"cron"}

_CONTENT_TOOLS = {"write_content", "read_file"}

_ALL_TOOLS = {s["function"]["name"] for s in TOOL_SPECS}


def _filter_specs(names: set) -> List[Dict[str, Any]]:
    return [s for s in TOOL_SPECS if s["function"]["name"] in names]


# ---------------------------------------------------------------------------
# Specialist system prompts
# ---------------------------------------------------------------------------

_FILE_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's File Agent — a specialist in file system operations. "
    "Your job is to read, write, search, organise, and manage files and directories. "
    "Always use the provided tools. Be safe: never delete without confirmation implied by context.\n\n"
    "SURGICAL EDITING RULES (God Mode):\n"
    "1. NEVER guess line numbers. If the user asks you to edit a specific part of a file, "
    "you MUST call read_file or read_file_lines first to see the exact code and confirm the "
    "correct line numbers.\n"
    "2. For targeted fixes (bug patches, one-line changes, small refactors), prefer "
    "edit_file_lines over write_file — it is safer and preserves the rest of the file.\n"
    "3. Only use write_file when you need to create a new file or completely replace its content.\n"
    "4. When using edit_file_lines, double-check start_line and end_line from what read_file_lines "
    "showed you before calling it."
)

_WEB_SYSTEM_PROMPT = """You are A.N.K.I.T.A's Web Research Agent — a specialist in finding real, accurate, live information from the web.

CRITICAL RULES:
1. NEVER output a raw list of URLs or raw search tool output. You are a researcher, not a search bar.
2. For ANY factual question (price, weather, specs, news, scores, definitions, etc.) — ALWAYS use search_and_fetch. It scrapes actual page content so you get real data, not just links.
3. Read the scraped content, extract the exact answer, and reply in natural language. Example: "Bitcoin is currently trading at $68,420 according to CoinGecko."
4. If the user asks to "save it", "open it in Notepad", or "write it to a file" — call write_content to save your research summary, then include FILE_PATH: <absolute_path> in your reply so SystemAgent can open it.
5. Only use search_web or search_news when the user explicitly wants a list of links or headlines.
6. If search_and_fetch returns no content, fall back to fetch_page_content on the top URL from search_web.
"""

_SYSTEM_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's System Agent — a specialist in controlling the local machine. "
    "You handle volume, brightness, WiFi, Bluetooth, screenshots, app launching and closing. "
    "Use tools immediately to perform the requested system action. "
    "CRITICAL: When opening a file in an app (e.g. Notepad), always look for a FILE_PATH: <path> "
    "line in your task context and use that FULL ABSOLUTE PATH. Never guess or use relative paths. "
    "If no absolute path is found in context, ask the user to clarify before opening."
)

_MUSIC_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Music Agent — a specialist in music search and playback. "
    "Search, play, stop, or check what's currently playing. "
    "Always pick the best matching result for playback."
)

_CODE_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Code Agent — a specialist in terminal commands, code execution, "
    "and autonomous bug fixing. Run shell commands, apply patches, execute scripts. "
    "Prefer PowerShell on Windows. Always return the exit code and output.\n\n"
    "AUTONOMOUS DEV LOOP (God Mode):\n"
    "When asked to run a script and fix errors, follow this loop:\n"
    "1. Run the script with run_command and read the error message carefully.\n"
    "2. Identify the file and line number from the traceback.\n"
    "3. Call read_file_lines on that file around the error line to see the exact broken code.\n"
    "4. Call edit_file_lines to surgically fix only the broken lines — never rewrite the whole file.\n"
    "5. Run the script again with run_command to verify the fix worked.\n"
    "6. Repeat until the script passes or you exhaust reasonable attempts (max 3 fix cycles).\n"
    "CRITICAL: Never guess line numbers — always read first, then edit."
)

_TERMINAL_SYSTEM_PROMPT = """\
You are A.N.K.I.T.A's Terminal Agent — you have direct shell access to the user's Windows machine via PowerShell.
Your job is to run CLI commands, check system status, use Git, ping servers, inspect network, or run scripts.

CRITICAL SAFETY RULES:
1. NEVER run destructive commands: del /s, format, rmdir /s, rd /s, Remove-Item -Recurse -Force, or any command that wipes data.
2. Keep commands concise and targeted. Use execute_shell to run them.
3. Read the terminal output carefully and summarize the result for the user simply and professionally.
4. Do NOT echo the entire raw terminal output unless explicitly asked — extract the key facts.
5. If the user asks to read a file from the output path, use read_file.
6. You are an EXECUTION agent — run the command immediately, don't explain how to do it manually.\
"""

_CRON_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Scheduler Agent — a specialist in cron job management. "
    "Add, update, list, remove, and trigger scheduled tasks. "
    "Support 'at', 'every', and 'cron' schedule types."
)

_CONTENT_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Content Agent — an expert copywriter, analyst, and creative writer. "
    "Your job is to generate polished, complete text content in any format the user requests: "
    "reports, scripts, songs, pitch decks, summaries, emails, essays, poems, and more. "
    "Adapt your tone perfectly to the format. If given raw notes via read_file, incorporate them. "
    "Always call write_content to generate and save the final piece. "
    "CRITICAL: After saving, your reply MUST include the FULL ABSOLUTE file path of the saved file "
    "(e.g. C:\\Users\\Krish\\Desktop\\AI_paragraph.txt) so downstream agents can open it. "
    "Format it clearly as: FILE_PATH: <absolute_path>. "
    "Speak the spoken_reply from write_content's result back to the user word-for-word."
)

_GENERAL_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A — a powerful general-purpose AI assistant. "
    "You have access to ALL tools — file, system, music, search, code, cron. "
    "Use them proactively when the user's request involves any real-world action. "
    "CRITICAL: NEVER give the user manual instructions like 'copy this into Notepad', "
    "'open the file yourself', 'paste this into your editor', or 'you can do X by...'. "
    "If the task requires opening a file → call launch_app with the file path. "
    "If it requires writing content → call write_content to save it first. "
    "If it requires playing music → call play_music. "
    "You are an AUTONOMOUS EXECUTION SYSTEM. Do the action — never describe it."
)


# ---------------------------------------------------------------------------
# Specialist class
# ---------------------------------------------------------------------------

class SpecialistAgent:
    """
    A focused sub-agent with a limited tool set and a domain-specific system prompt.
    Used by the Orchestrator to handle delegated sub-tasks.
    """

    def __init__(self, name: str, tool_names: set, system_prompt: str) -> None:
        self.name = name
        self.tool_specs = _filter_specs(tool_names)
        self.system_prompt = system_prompt

    def make_messages(self, task: str) -> List[Dict[str, Any]]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task},
        ]

    def __repr__(self) -> str:
        return f"<SpecialistAgent name={self.name!r} tools={[s['function']['name'] for s in self.tool_specs]}>"


# ---------------------------------------------------------------------------
# Pre-built specialist instances
# ---------------------------------------------------------------------------

FileAgent     = SpecialistAgent("FileAgent",     _FILE_TOOLS,     _FILE_SYSTEM_PROMPT)
WebAgent      = SpecialistAgent("WebAgent",      _WEB_TOOLS,      _WEB_SYSTEM_PROMPT)
SystemAgent   = SpecialistAgent("SystemAgent",   _SYSTEM_TOOLS,   _SYSTEM_SYSTEM_PROMPT)
MusicAgent    = SpecialistAgent("MusicAgent",    _MUSIC_TOOLS,    _MUSIC_SYSTEM_PROMPT)
CodeAgent     = SpecialistAgent("CodeAgent",     _CODE_TOOLS,     _CODE_SYSTEM_PROMPT)
CronAgent     = SpecialistAgent("CronAgent",     _CRON_TOOLS,     _CRON_SYSTEM_PROMPT)
ContentAgent  = SpecialistAgent("ContentAgent",  _CONTENT_TOOLS,  _CONTENT_SYSTEM_PROMPT)
GeneralAgent  = SpecialistAgent("GeneralAgent",  _ALL_TOOLS,      _GENERAL_SYSTEM_PROMPT)
TerminalAgent = SpecialistAgent("TerminalAgent", _TERMINAL_TOOLS, _TERMINAL_SYSTEM_PROMPT)

# Map name → instance for lookup
SPECIALIST_MAP: Dict[str, SpecialistAgent] = {
    "FileAgent":     FileAgent,
    "WebAgent":      WebAgent,
    "SystemAgent":   SystemAgent,
    "MusicAgent":    MusicAgent,
    "CodeAgent":     CodeAgent,
    "CronAgent":     CronAgent,
    "ContentAgent":  ContentAgent,
    "GeneralAgent":  GeneralAgent,
    "TerminalAgent": TerminalAgent,
}
