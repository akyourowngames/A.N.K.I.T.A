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

_FILE_TOOLS = {"list_files", "read_file", "write_file", "edit_file", "search_text",
               "rename_path", "delete_path", "move_path", "copy_path", "make_dir",
               "file_info", "apply_patch"}

_WEB_TOOLS = {"search_web", "search_news"}

_SYSTEM_TOOLS = {"system_control", "launch_app", "terminate_app"}

_MUSIC_TOOLS = {"play_music", "stop_music", "search_music", "current_music"}

_CODE_TOOLS = {"run_command", "apply_patch"}

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
    "Always use the provided tools. Be safe: never delete without confirmation implied by context."
)

_WEB_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Web Agent — a specialist in real-time information retrieval. "
    "Search the web and news to find accurate, up-to-date information. "
    "Summarise results clearly and concisely."
)

_SYSTEM_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's System Agent — a specialist in controlling the local machine. "
    "You handle volume, brightness, WiFi, Bluetooth, screenshots, app launching and closing. "
    "Use tools immediately to perform the requested system action."
)

_MUSIC_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Music Agent — a specialist in music search and playback. "
    "Search, play, stop, or check what's currently playing. "
    "Always pick the best matching result for playback."
)

_CODE_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Code Agent — a specialist in terminal commands and code execution. "
    "Run shell commands, apply patches, execute scripts. "
    "Prefer PowerShell on Windows. Always return the exit code and output."
)

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
    "Speak the spoken_reply from write_content's result back to the user word-for-word."
)

_GENERAL_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A — a powerful general-purpose AI assistant. "
    "Use any of the available tools to fulfil the user's request completely."
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

FileAgent    = SpecialistAgent("FileAgent",    _FILE_TOOLS,    _FILE_SYSTEM_PROMPT)
WebAgent     = SpecialistAgent("WebAgent",     _WEB_TOOLS,     _WEB_SYSTEM_PROMPT)
SystemAgent  = SpecialistAgent("SystemAgent",  _SYSTEM_TOOLS,  _SYSTEM_SYSTEM_PROMPT)
MusicAgent   = SpecialistAgent("MusicAgent",   _MUSIC_TOOLS,   _MUSIC_SYSTEM_PROMPT)
CodeAgent    = SpecialistAgent("CodeAgent",    _CODE_TOOLS,    _CODE_SYSTEM_PROMPT)
CronAgent    = SpecialistAgent("CronAgent",    _CRON_TOOLS,    _CRON_SYSTEM_PROMPT)
ContentAgent = SpecialistAgent("ContentAgent", _CONTENT_TOOLS, _CONTENT_SYSTEM_PROMPT)
GeneralAgent = SpecialistAgent("GeneralAgent", _ALL_TOOLS,     _GENERAL_SYSTEM_PROMPT)

# Map name → instance for lookup
SPECIALIST_MAP: Dict[str, SpecialistAgent] = {
    "FileAgent":    FileAgent,
    "WebAgent":     WebAgent,
    "SystemAgent":  SystemAgent,
    "MusicAgent":   MusicAgent,
    "CodeAgent":    CodeAgent,
    "CronAgent":    CronAgent,
    "ContentAgent": ContentAgent,
    "GeneralAgent": GeneralAgent,
}
