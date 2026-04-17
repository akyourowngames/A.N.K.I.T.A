"""
PlannerAgent for A.N.K.I.T.A multi-agent system.

The PlannerAgent is a dedicated thinking layer that decomposes complex multi-step
requests into structured execution plans. It sits between the Supervisor and the
Orchestrator, activating only when a task genuinely needs planning.

UPGRADE: The PlannerAgent is now FULLY TOOL-AWARE. It auto-discovers all agents
and their tool capabilities from the SPECIALIST_MAP, so it never goes stale.
It also generates confidence scores per step and for the overall plan.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Dynamic Capability Discovery
# ---------------------------------------------------------------------------

def _discover_agent_capabilities() -> Dict[str, Dict[str, Any]]:
    """
    Auto-discover ALL registered agents and their tool capabilities.
    
    This is the KEY upgrade: instead of a hard-coded list, the PlannerAgent
    introspects the live SPECIALIST_MAP to know exactly which agents exist
    and what tools each agent has access to.
    
    Returns:
        Dict mapping agent_name -> {
            "tools": [list of tool names],
            "tool_count": int,
            "description": str (generated from tool names),
            "capabilities": [list of high-level capability strings],
        }
    """
    try:
        from agents.specialists import SPECIALIST_MAP
    except ImportError:
        return {}

    capabilities: Dict[str, Dict[str, Any]] = {}

    for agent_name, specialist in SPECIALIST_MAP.items():
        tool_names = [
            spec["function"]["name"]
            for spec in specialist.tool_specs
        ]

        # Classify capabilities from tool names
        cap_tags = _classify_capabilities(tool_names)

        capabilities[agent_name] = {
            "tools": tool_names,
            "tool_count": len(tool_names),
            "capabilities": cap_tags,
        }

    return capabilities


def _classify_capabilities(tool_names: List[str]) -> List[str]:
    """Classify high-level capabilities from a list of tool names."""
    caps = []
    names_set = set(tool_names)

    # File operations
    if names_set & {"read_file", "write_file", "edit_file", "list_files", "delete_path", "move_path", "copy_path"}:
        caps.append("file_operations")
    # Web/search
    if names_set & {"search_web", "search_news", "search_and_fetch", "fetch_page_content", "deep_research"}:
        caps.append("web_research")
    # System control
    if names_set & {"system_control", "launch_app", "open_path", "terminate_app"}:
        caps.append("system_control")
    # Music
    if names_set & {"play_music", "stop_music", "search_music", "queue_music"}:
        caps.append("music_playback")
    # Code
    if names_set & {"run_command", "execute_shell", "check_syntax", "git_op", "code_analysis"}:
        caps.append("code_development")
    # Terminal
    if names_set & {"execute_shell", "chain_commands", "execute_elevated"}:
        caps.append("terminal_access")
    # Vision/Screen
    if names_set & {"capture_screen", "read_screen_context", "visual_click"}:
        caps.append("screen_interaction")
    # Integrations
    if names_set & {"sheets_op", "youtube_op", "figma_op", "github_op", "docker_op"}:
        caps.append("cloud_integrations")
    # Maps
    if "maps_op" in names_set:
        caps.append("navigation_maps")
    # Tasks
    if "task_op" in names_set:
        caps.append("task_management")
    # Reports
    if "generate_pdf" in names_set:
        caps.append("report_generation")
    # Images
    if "generate_image" in names_set:
        caps.append("image_generation")
    # Memory
    if names_set & {"remember", "recall", "forget"}:
        caps.append("memory")
    # Autonomous
    if names_set & {"discover_tools", "auto_install_tool", "auto_install_python_package", "generate_and_run_script"}:
        caps.append("autonomous_ops")
    # Cognitive
    if names_set & {"resolve_error", "smart_retry", "workspace_scan", "plan_and_execute"}:
        caps.append("cognitive_ops")
    # Content
    if not names_set - {"remember", "recall", "forget"}:
        caps.append("pure_content_generation")

    return caps


def _build_agent_manifest() -> str:
    """
    Build a formatted string of all agent capabilities for the system prompt.
    This updates automatically whenever agents/tools are added or removed.
    """
    capabilities = _discover_agent_capabilities()

    if not capabilities:
        return "ERROR: Could not discover agent capabilities. Using fallback."

    lines = []
    total_tools = 0

    for agent_name, info in sorted(capabilities.items()):
        tool_count = info["tool_count"]
        total_tools += tool_count
        cap_tags = ", ".join(info["capabilities"]) if info["capabilities"] else "general"
        tool_list = ", ".join(info["tools"][:15])  # Show first 15 tools
        overflow = f" (+{tool_count - 15} more)" if tool_count > 15 else ""

        lines.append(
            f"- {agent_name}: [{cap_tags}] ({tool_count} tools)\n"
            f"    Tools: {tool_list}{overflow}"
        )

    header = f"TOTAL: {len(capabilities)} agents, {total_tools} tools across the system.\n"
    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# System Prompt Builder (Dynamic)
# ---------------------------------------------------------------------------

def _build_planner_system_prompt() -> str:
    """
    Build the PlannerAgent system prompt with LIVE tool discovery.
    This runs once at import time and caches the result.
    """
    agent_manifest = _build_agent_manifest()

    return f"""You are A.N.K.I.T.A's PlannerAgent — the mission architect.

Your ONLY job: decompose a complex request into a precise, ordered execution plan.

You output a JSON plan with confidence scores. Nothing else.

═══════════════════════════════════════════════════════════════
LIVE AGENT CAPABILITY MANIFEST (auto-discovered, always current):
═══════════════════════════════════════════════════════════════
{agent_manifest}

═══════════════════════════════════════════════════════════════
PLAN FORMAT — OUTPUT ONLY VALID JSON:
═══════════════════════════════════════════════════════════════
{{
  "goal": "one sentence describing what the user ultimately wants",
  "confidence": 0.85,
  "total_steps": 4,
  "estimated_duration_seconds": 30,
  "steps": [
    {{
      "id": 1,
      "agent": "WebAgent",
      "task": "search for best budget laptops under 50000 INR, get top 5 with specs",
      "depends_on": [],
      "condition": null,
      "artifacts_out": ["search_results"],
      "confidence": 0.90,
      "fallback_agent": "GeneralAgent",
      "retry_strategy": "transient",
      "estimated_seconds": 8
    }},
    {{
      "id": 2,
      "agent": "ContentAgent",
      "task": "write a comparison report from the search results",
      "depends_on": [1],
      "condition": null,
      "artifacts_out": ["report_text"],
      "confidence": 0.85,
      "fallback_agent": null,
      "retry_strategy": "none",
      "estimated_seconds": 12
    }},
    {{
      "id": 3,
      "agent": "FileAgent",
      "task": "save the comparison report as laptop_report.md on Desktop",
      "depends_on": [2],
      "condition": null,
      "artifacts_out": ["file_path"],
      "confidence": 0.95,
      "fallback_agent": "TerminalAgent",
      "retry_strategy": "permission",
      "estimated_seconds": 2
    }},
    {{
      "id": 4,
      "agent": "SystemAgent",
      "task": "open the saved report file",
      "depends_on": [3],
      "condition": null,
      "artifacts_out": [],
      "confidence": 0.90,
      "fallback_agent": "TerminalAgent",
      "retry_strategy": "none",
      "estimated_seconds": 2
    }}
  ],
  "risk_assessment": "Low risk. All agents have proven tools for these tasks.",
  "parallel_opportunities": "Steps 1-4 are sequential (each depends on prior). No parallelism possible."
}}

═══════════════════════════════════════════════════════════════
CONFIDENCE SCORING RULES:
═══════════════════════════════════════════════════════════════
- 0.90-1.00: Crystal clear task, agent has the exact right tool
- 0.75-0.89: Clear task, high confidence in agent choice
- 0.60-0.74: Moderate confidence, task might need adaptation
- 0.40-0.59: Low confidence, consider providing fallback_agent
- 0.00-0.39: Very uncertain, MUST provide fallback_agent

Overall plan confidence = geometric mean of step confidences.

═══════════════════════════════════════════════════════════════
RETRY STRATEGY PER STEP:
═══════════════════════════════════════════════════════════════
- "none": No retry needed (idempotent or low-risk)
- "transient": Retry on network/timeout errors with exponential backoff
- "permission": Retry with elevated permissions (escalate to TerminalAgent)
- "alternative": Try fallback_agent if primary fails
- "decompose": Break this step into smaller sub-steps if it fails

═══════════════════════════════════════════════════════════════
PLANNING RULES:
═══════════════════════════════════════════════════════════════
1. Each step's task must be SPECIFIC — include what data to pass from previous steps
2. depends_on = list of step IDs that must complete before this one runs
3. condition = null for unconditional, or a string like "only if step 2 succeeded"
4. artifacts_out = what this step produces that the next step needs
5. Never plan more than 8 steps — decompose further only if the task demands it
6. Never include unnecessary steps — minimum steps to achieve the goal
7. If two steps have NO dependency between them, they can run in parallel (both have same depends_on)
8. Always end the plan — never leave the user's ultimate goal unfinished
9. fallback_agent = backup agent to try if the primary agent fails (null if no fallback)
10. ALWAYS match the agent to its actual tools — never route to an agent for a task it has no tools for
11. ContentAgent has NO tools (only memory). It generates text. FileAgent saves it.
12. When saving content, ALWAYS route through FileAgent (write_file), not ContentAgent
"""


# Cache the prompt at module load time
_PLANNER_SYSTEM_PROMPT = _build_planner_system_prompt()


# ---------------------------------------------------------------------------
# Introspection API (for external callers to understand their own capabilities)
# ---------------------------------------------------------------------------

def get_capability_manifest() -> Dict[str, Any]:
    """
    Public API: Returns a structured manifest of all agent capabilities.
    
    This is the method the user asked about — any part of the system can call
    this to understand what tools are available and which agents handle what.
    
    Usage:
        from agents.planner import get_capability_manifest
        manifest = get_capability_manifest()
        # manifest["agents"]["WebAgent"]["tools"]  -> ["search_web", "search_news", ...]
        # manifest["agents"]["WebAgent"]["capabilities"]  -> ["web_research", ...]
        # manifest["total_agents"]  -> 16
        # manifest["total_tools"]  -> 127
    """
    capabilities = _discover_agent_capabilities()
    total_tools = sum(info["tool_count"] for info in capabilities.values())

    # Build a tool-to-agent reverse lookup
    tool_to_agents: Dict[str, List[str]] = {}
    for agent_name, info in capabilities.items():
        for tool_name in info["tools"]:
            tool_to_agents.setdefault(tool_name, []).append(agent_name)

    return {
        "total_agents": len(capabilities),
        "total_tools": total_tools,
        "agents": capabilities,
        "tool_to_agents": tool_to_agents,
        "agent_names": sorted(capabilities.keys()),
    }


def get_tools_for_task(task_description: str) -> List[str]:
    """
    Suggest which agents are best suited for a given task description.
    Uses simple keyword matching against capability tags.
    
    Usage:
        from agents.planner import get_tools_for_task
        agents = get_tools_for_task("search the web and save results to file")
        # -> ["WebAgent", "FileAgent"]
    """
    capabilities = _discover_agent_capabilities()
    task_lower = task_description.lower()

    # Keyword to capability mapping
    keyword_caps = {
        "search": "web_research",
        "research": "web_research",
        "google": "web_research",
        "web": "web_research",
        "file": "file_operations",
        "save": "file_operations",
        "write": "file_operations",
        "read": "file_operations",
        "music": "music_playback",
        "play": "music_playback",
        "song": "music_playback",
        "code": "code_development",
        "fix": "code_development",
        "debug": "code_development",
        "build": "code_development",
        "terminal": "terminal_access",
        "shell": "terminal_access",
        "command": "terminal_access",
        "screen": "screen_interaction",
        "click": "screen_interaction",
        "screenshot": "system_control",
        "volume": "system_control",
        "brightness": "system_control",
        "open": "system_control",
        "launch": "system_control",
        "sheets": "cloud_integrations",
        "youtube": "cloud_integrations",
        "figma": "cloud_integrations",
        "github": "cloud_integrations",
        "map": "navigation_maps",
        "navigate": "navigation_maps",
        "directions": "navigation_maps",
        "task": "task_management",
        "todo": "task_management",
        "deadline": "task_management",
        "report": "report_generation",
        "pdf": "report_generation",
        "image": "image_generation",
        "draw": "image_generation",
        "paint": "image_generation",
        "generate image": "image_generation",
    }

    matched_caps = set()
    for keyword, cap in keyword_caps.items():
        if keyword in task_lower:
            matched_caps.add(cap)

    # Find agents that have matching capabilities
    matching_agents = []
    for agent_name, info in capabilities.items():
        agent_caps = set(info["capabilities"])
        if agent_caps & matched_caps:
            matching_agents.append(agent_name)

    return matching_agents or ["GeneralAgent"]


# ---------------------------------------------------------------------------
# PlannerAgent Class
# ---------------------------------------------------------------------------

class PlannerAgent:
    """
    A standalone agent that decomposes complex requests into structured execution plans.
    
    The PlannerAgent has no tools — it only reasons and outputs JSON plans.
    
    UPGRADE: Now fully tool-aware via dynamic discovery. The system prompt
    auto-updates whenever agents or tools change.
    
    Introspection API (for making tools aware of themselves):
        >>> from agents.planner import get_capability_manifest
        >>> manifest = get_capability_manifest()
        >>> manifest["total_agents"]  # e.g. 16
        >>> manifest["agents"]["WebAgent"]["tools"]  # list of tool names
        >>> manifest["tool_to_agents"]["search_web"]  # ["WebAgent"]
        
        >>> from agents.planner import get_tools_for_task
        >>> get_tools_for_task("search web and save to file")  # ["WebAgent", "FileAgent"]
    """

    def __init__(self) -> None:
        self.name = "PlannerAgent"
        self.system_prompt = _PLANNER_SYSTEM_PROMPT
        self._capabilities_cache: Optional[Dict[str, Any]] = None

    @property
    def capabilities(self) -> Dict[str, Any]:
        """Lazy-loaded capability manifest."""
        if self._capabilities_cache is None:
            self._capabilities_cache = get_capability_manifest()
        return self._capabilities_cache

    @property
    def total_agents(self) -> int:
        return self.capabilities["total_agents"]

    @property
    def total_tools(self) -> int:
        return self.capabilities["total_tools"]

    @property
    def agent_names(self) -> List[str]:
        return self.capabilities["agent_names"]

    def refresh_capabilities(self) -> None:
        """Force re-discovery of agent capabilities (e.g. after hot-loading new tools)."""
        self._capabilities_cache = None
        # Also rebuild the system prompt
        global _PLANNER_SYSTEM_PROMPT
        _PLANNER_SYSTEM_PROMPT = _build_planner_system_prompt()
        self.system_prompt = _PLANNER_SYSTEM_PROMPT

    def find_agents_for_tool(self, tool_name: str) -> List[str]:
        """Which agents have access to a specific tool?"""
        return self.capabilities.get("tool_to_agents", {}).get(tool_name, [])

    def find_agents_for_task(self, task: str) -> List[str]:
        """Suggest agents for a natural-language task description."""
        return get_tools_for_task(task)

    def __repr__(self) -> str:
        return (
            f"<PlannerAgent name={self.name!r} "
            f"agents={self.total_agents} "
            f"tools={self.total_tools}>"
        )
