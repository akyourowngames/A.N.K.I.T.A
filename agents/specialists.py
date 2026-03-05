"""
Specialist sub-agents for A.N.K.I.T.A multi-agent architecture.

Each specialist has access only to its domain-specific tools,
making it focused and accurate — avoiding tool confusion.
"""
from __future__ import annotations

# DreamAgent is standalone (not Supervisor-routed) — exposed here for convenience
from agents.dream_agent import DreamAgent  # noqa: F401

from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.engine import TOOL_SPECS

# ---------------------------------------------------------------------------
# Tool subsets by domain
# ---------------------------------------------------------------------------

_MEMORY_TOOLS = {"remember", "recall", "forget"}  # available to ALL agents

_FILE_TOOLS = {"list_files", "read_file", "read_file_lines", "read_rich_file", "write_file", "edit_file",
               "edit_file_lines", "search_text", "rename_path", "delete_path", "move_path",
               "copy_path", "make_dir", "file_info", "apply_patch", "write_content",
               "launch_app", "file_sync", "pc_search", "trash_path", "disk_analysis",
               "diff_files", "bulk_op",
               # Camera — FileAgent can save photos anywhere on the PC
               "capture_webcam"} | _MEMORY_TOOLS

_WEB_TOOLS = {"search_web", "search_news", "search_and_fetch", "fetch_page_content",
              "search_price", "write_content", "download_file", "launch_app",
              "deep_research",
              # Advanced research tools (previously orphaned — now wired in)
              "compare_search", "multi_search", "fact_check", "image_search",
              "scrape_structured", "search_reddit", "search_stackoverflow",
              "summarise_url", "trending_topics", "web_monitor",
              "web_to_dataset"} | _MEMORY_TOOLS

_SYSTEM_TOOLS = {"system_control", "launch_app", "terminate_app", "desktop_interact",
                 "read_file", "search_text", "execute_shell", "run_command",
                 "camera_control", "app_manager", "voice_control", "system_health",
                 "file_sync", "window_layout", "process_op", "capture_webcam",
                 "system_audit", "discover_tools", "auto_install_tool",
                 "execute_elevated", "service_op", "get_system_context",
                 "resolve_error", "smart_retry", "process_watch",
                 "translate_command"} | _MEMORY_TOOLS

_MUSIC_TOOLS = {"play_music", "stop_music", "search_music", "current_music", 
                "queue_music", "show_queue", "clear_queue", "play_next_in_queue", 
                "system_control"} | _MEMORY_TOOLS

# UPGRADE: CodeAgent can now launch VS Code or terminals to show its work
# UPGRADE 9: Added git_op for native git awareness
# UPGRADE 14: Added deep_research, download_file, process_op, diff_files, bulk_op for advanced dev workflows
# UPGRADE 15: Added autonomous ops for self-sufficient development
_CODE_TOOLS = {"run_command", "apply_patch", "execute_shell", "check_syntax",
               "read_file", "read_file_lines", "edit_file", "edit_file_lines", "write_file",
               "launch_app", "search_text", "list_files", "make_dir", "copy_path",
               "rename_path", "delete_path", "move_path", "file_info",
               "search_web", "fetch_page_content", "git_op",
               "deep_research", "download_file", "process_op", "diff_files", "bulk_op",
               "auto_install_tool", "auto_install_python_package", "generate_and_run_script",
               "execute_pipeline", "environment_setup", "github_op",
               "resolve_error", "smart_retry", "workspace_scan", "plan_and_execute",
               "code_analysis", "project_scaffold", "self_extend", "execute_extension"} | _MEMORY_TOOLS
_TERMINAL_TOOLS = {"execute_shell", "list_files", "read_file", "run_command", "git_op",
                   "process_op", "fast_file_search",
                   # Autonomous ops — full system control like OpenClaw
                   "discover_tools", "auto_install_tool", "auto_install_python_package",
                   "generate_and_run_script", "execute_pipeline", "environment_setup",
                   "system_audit", "execute_elevated", "chain_commands", "get_system_context",
                   # Integration hub — GitHub, Docker, SSH, API, DB, Services
                   "github_op", "docker_op", "ssh_op", "api_test", "db_query",
                   "service_op",
                   # Cognitive ops — self-healing, intelligence, self-extension
                   "resolve_error", "smart_retry", "workspace_scan", "plan_and_execute",
                   "code_analysis", "project_scaffold", "self_extend", "execute_extension",
                   "process_watch", "translate_command", "list_extensions"} | _MEMORY_TOOLS

_CRON_TOOLS = {"cron"} | _MEMORY_TOOLS

# ASSEMBLY LINE: ContentAgent is now a pure text generator — NO tools.
# FileAgent saves the output. SystemAgent opens the file.
_CONTENT_TOOLS = _MEMORY_TOOLS  # recall + remember for style memory

_COMMS_TOOLS = {"send_whatsapp", "lookup_contact", "add_contact", "remove_contact", "list_contacts"} | _MEMORY_TOOLS

# UPGRADE: ScreenAgent gets full vision + interaction
_SCREEN_TOOLS = {"capture_screen", "read_screen_context", "visual_click", "system_control", "desktop_interact", "capture_webcam", "read_file"}

# Cloud / Integration tools — Google Sheets, YouTube, Figma + DevOps integrations
_INTEGRATION_TOOLS = {"sheets_op", "youtube_op", "figma_op",
                      "github_op", "docker_op", "ssh_op", "api_test",
                      "db_query", "service_op",
                      "process_watch", "workspace_scan"} | _MEMORY_TOOLS

# WatchdogAgent has no direct tools — it calls WatchdogManager via Python import
_WATCHDOG_TOOLS: set = set()

# NavigatorAgent — Maps and location intelligence
_NAVIGATOR_TOOLS = {"maps_op"} | _MEMORY_TOOLS

# TaskAgent — Smart to-do and reminders
_TASK_TOOLS = {"task_op", "cron"} | _MEMORY_TOOLS

# ReportAgent — Automated report builder
_REPORT_TOOLS = {"generate_pdf", "disk_analysis", "git_op", "read_file", "list_files", 
                 "write_file", "system_health", "search_web", "fetch_page_content"} | _MEMORY_TOOLS

# ImageAgent — AI image generation via Pollinations.ai (no API key needed)
_IMAGE_TOOLS = {"generate_image", "image_search", "search_web"} | _MEMORY_TOOLS

_ALL_TOOLS = {s["function"]["name"] for s in TOOL_SPECS}


def _filter_specs(names: set) -> List[Dict[str, Any]]:
    return [s for s in TOOL_SPECS if s["function"]["name"] in names]


# ---------------------------------------------------------------------------
# Specialist system prompts
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# System prompts live in agents/prompts.py — edit them there.
# ---------------------------------------------------------------------------
from agents.prompts import (
    _CODE_SYSTEM_PROMPT,
    _COMMS_SYSTEM_PROMPT,
    _CONTENT_SYSTEM_PROMPT,
    _CRON_SYSTEM_PROMPT,
    _DESKTOP,
    _FILE_SYSTEM_PROMPT,
    _GENERAL_SYSTEM_PROMPT,
    _IMAGE_SYSTEM_PROMPT,
    _INTEGRATION_SYSTEM_PROMPT,
    _MUSIC_SYSTEM_PROMPT,
    _NAVIGATOR_SYSTEM_PROMPT,
    _REPORT_SYSTEM_PROMPT,
    _SCREEN_SYSTEM_PROMPT,
    _SYSTEM_SYSTEM_PROMPT,
    _TASK_SYSTEM_PROMPT,
    _TELEGRAM_DELIVERY_GUIDE,
    _TERMINAL_SYSTEM_PROMPT,
    _WATCHDOG_SYSTEM_PROMPT,
    _WEB_SYSTEM_PROMPT
)


class SpecialistAgent:
    """
    A focused sub-agent with a limited tool set and a domain-specific system prompt.
    Used by the Orchestrator to handle delegated sub-tasks.
    """

    def __init__(self, name: str, tool_names: set, system_prompt: str) -> None:
        self.name = name
        self.tool_specs = _filter_specs(tool_names)
        self.system_prompt = system_prompt

    def make_messages(self, task: str, history: Optional[List[Dict[str, Any]]] = None, mood_context: str = "") -> List[Dict[str, Any]]:
        """Build messages for this specialist.

        Args:
            task: The current user task/message
            history: Optional conversation history (last N clean user/assistant turns)
            mood_context: Optional mood directive from PersonalityEngine to adapt tone

        Returns:
            List of messages: [system, mood?, history..., current_task]
        """
        messages = [{"role": "system", "content": self.system_prompt + _TELEGRAM_DELIVERY_GUIDE}]

        # Inject mood directive as a second system message when non-empty
        if mood_context:
            messages.append({"role": "system", "content": mood_context})

        # Inject conversation history if provided
        if history:
            messages.extend(history)

        # Add current task
        messages.append({"role": "user", "content": task})

        return messages


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
CommsAgent        = SpecialistAgent("CommsAgent",        _COMMS_TOOLS,        _COMMS_SYSTEM_PROMPT)
GeneralAgent      = SpecialistAgent("GeneralAgent",      _ALL_TOOLS,          _GENERAL_SYSTEM_PROMPT)
TerminalAgent     = SpecialistAgent("TerminalAgent",     _TERMINAL_TOOLS,     _TERMINAL_SYSTEM_PROMPT)
ScreenAgent       = SpecialistAgent("ScreenAgent",       _SCREEN_TOOLS,       _SCREEN_SYSTEM_PROMPT)
IntegrationAgent  = SpecialistAgent("IntegrationAgent",  _INTEGRATION_TOOLS,  _INTEGRATION_SYSTEM_PROMPT)
WatchdogAgent     = SpecialistAgent("WatchdogAgent",     _WATCHDOG_TOOLS,     _WATCHDOG_SYSTEM_PROMPT)
NavigatorAgent    = SpecialistAgent("NavigatorAgent",    _NAVIGATOR_TOOLS,    _NAVIGATOR_SYSTEM_PROMPT)
TaskAgent         = SpecialistAgent("TaskAgent",         _TASK_TOOLS,         _TASK_SYSTEM_PROMPT)
ReportAgent       = SpecialistAgent("ReportAgent",       _REPORT_TOOLS,       _REPORT_SYSTEM_PROMPT)
ImageAgent        = SpecialistAgent("ImageAgent",        _IMAGE_TOOLS,        _IMAGE_SYSTEM_PROMPT)

# Import PlannerAgent
from agents.planner import PlannerAgent as _PlannerAgentClass

# Create PlannerAgent instance (no tools — pure reasoning agent)
PlannerAgent = SpecialistAgent("PlannerAgent", set(), _PlannerAgentClass().system_prompt)

# Map name → instance for lookup
SPECIALIST_MAP: Dict[str, SpecialistAgent] = {
    "FileAgent":        FileAgent,
    "WebAgent":         WebAgent,
    "SystemAgent":      SystemAgent,
    "MusicAgent":       MusicAgent,
    "CodeAgent":        CodeAgent,
    "CronAgent":        CronAgent,
    "ContentAgent":     ContentAgent,
    "CommsAgent":       CommsAgent,
    "GeneralAgent":     GeneralAgent,
    "TerminalAgent":    TerminalAgent,
    "ScreenAgent":      ScreenAgent,
    "IntegrationAgent": IntegrationAgent,
    "WatchdogAgent":    WatchdogAgent,
    "NavigatorAgent":   NavigatorAgent,
    "TaskAgent":        TaskAgent,
    "ReportAgent":      ReportAgent,
    "ImageAgent":       ImageAgent,
    "PlannerAgent":     PlannerAgent,
}
