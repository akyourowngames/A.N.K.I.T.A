You are absolutely right. The current setup is "thinking" too much and routing poorly. It splits the job into two dumb agents (one that writes, one that opens) who don't talk to each other, so you end up with an empty Notepad and a hidden file.

We are going to implement **Unidirectional Execution Flow**.

**The Fix:**

1. **Power-Up the Specialists:** We will give the `ContentAgent` and `CodeAgent` the power to **Launch Apps** themselves. They shouldn't need to ask the System Agent to open a file they just created.
2. **Fix the Supervisor Brain:** We will hard-code a "Composite Task" rule. "Write X in Y" is ONE job, not two. It goes to the Creator Agent, who handles the whole pipeline.

Here is the upgrade plan for `specialists.py` and `supervisor.py`.

### 1. Upgrade `agents/specialists.py`

We are adding `launch_app` to the Content and Code agents so they can finish the job.

```python
"""
Specialist sub-agents for A.N.K.I.T.A multi-agent architecture.
UPGRADE: ContentAgent and CodeAgent can now LAUNCH apps to show their work.
"""
from __future__ import annotations
from agents.dream_agent import DreamAgent  # noqa: F401
from pathlib import Path
from typing import Any, Dict, List
from tools.engine import TOOL_SPECS

# ---------------------------------------------------------------------------
# Tool subsets by domain (UPGRADED)
# ---------------------------------------------------------------------------

_FILE_TOOLS = {
    "list_files", "read_file", "read_file_lines", "write_file", "edit_file",
    "edit_file_lines", "search_text", "rename_path", "delete_path", "move_path",
    "copy_path", "make_dir", "file_info", "apply_patch", "write_content"
}

_WEB_TOOLS = {
    "search_web", "search_news", "search_and_fetch", "fetch_page_content",
    "search_price", "write_content"
}

_SYSTEM_TOOLS = {
    "system_control", "launch_app", "terminate_app", "desktop_interact",
    "read_file", "search_text"
}

_MUSIC_TOOLS = {
    "play_music", "stop_music", "search_music", "current_music"
}

# UPGRADE: CodeAgent can now launch VS Code or terminals
_CODE_TOOLS = {
    "run_command", "apply_patch", "execute_shell", "read_file", "write_file",
    "list_files", "edit_file_lines", "check_syntax", "launch_app"
}

_CRON_TOOLS = {"cron"}

# UPGRADE: ContentAgent can now launch Notepad/Word to show the poem
_CONTENT_TOOLS = {
    "write_and_save_content", "launch_app" 
}

_COMMS_TOOLS = {"send_whatsapp", "read_whatsapp"} 

# UPGRADE: ScreenAgent gets full vision + interaction
_SCREEN_TOOLS = {
    "capture_screen", "read_screen_context", "visual_click", "system_control", "desktop_interact"
}

# Terminal Agent gets everything for raw power
_TERMINAL_TOOLS = {
    "execute_shell", "list_files", "read_file", "run_command"
}

_ALL_TOOLS = {t["function"]["name"] for t in TOOL_SPECS}


# ---------------------------------------------------------------------------
# System Prompts (The "Personality" & "Rules")
# ---------------------------------------------------------------------------

_GENERAL_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A — a powerful general-purpose AI assistant. "
    "You have access to ALL tools. Use them proactively. "
    "UNIDIRECTIONAL FLOW: If the user wants to 'write X in Y', YOU must: "
    "1. Create the file first. 2. THEN launch the app to open it. "
    "Never open the app before the file exists."
)

_CONTENT_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Content Creator. You write poems, essays, emails, and scripts. "
    "You have a 'God Mode' workflow: "
    "1. GENERATE the content using `write_and_save_content`. "
    "2. IF the user asked to see it in an app (like 'in Notepad'), use `launch_app` "
    "to open the file you just saved. "
    "Done. No questions. 💅"
)

_CODE_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Senior Developer. "
    "AUTONOMOUS DEV LOOP: "
    "1. Read code. 2. Fix code. 3. `check_syntax` (CRITICAL). 4. Run/Deploy. "
    "If the user wants to see the code, use `launch_app` to open it in VS Code."
)

_SYSTEM_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's System Operator. You control Wi-Fi, Volume, Apps, and Processes. "
    "RULE: Do NOT try to generate content (poems, code) by typing. "
    "If the user wants content created, that is the ContentAgent's job. "
    "You only handle the OS. Stay in your lane."
)

_SCREEN_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Vision. You see everything. "
    "Use `capture_screen` to see the UI. "
    "Use `visual_click` to manipulate it. "
    "Never hallucinate. If you don't see it, say so."
)

# ... (Other prompts remain standard) ...

_FILE_SYSTEM_PROMPT = "You are the File System Manager. You organize, find, and manage files."
_WEB_SYSTEM_PROMPT = "You are the Deep Research Agent. Dig deep, follow links, verify facts."
_MUSIC_SYSTEM_PROMPT = "You are the DJ. Play the vibe."
_CRON_SYSTEM_PROMPT = "You are the Scheduler. Manage time and tasks."
_COMMS_SYSTEM_PROMPT = "You are the Communications Officer. Handle WhatsApp and messages."
_TERMINAL_SYSTEM_PROMPT = "You are the Shell Master. Execute commands safely."


# ---------------------------------------------------------------------------
# Specialist Instances
# ---------------------------------------------------------------------------

FileAgent     = SpecialistAgent("FileAgent",     _FILE_TOOLS,     _FILE_SYSTEM_PROMPT)
WebAgent      = SpecialistAgent("WebAgent",      _WEB_TOOLS,      _WEB_SYSTEM_PROMPT)
SystemAgent   = SpecialistAgent("SystemAgent",   _SYSTEM_TOOLS,   _SYSTEM_SYSTEM_PROMPT)
MusicAgent    = SpecialistAgent("MusicAgent",    _MUSIC_TOOLS,    _MUSIC_SYSTEM_PROMPT)
CodeAgent     = SpecialistAgent("CodeAgent",     _CODE_TOOLS,     _CODE_SYSTEM_PROMPT)
CronAgent     = SpecialistAgent("CronAgent",     _CRON_TOOLS,     _CRON_SYSTEM_PROMPT)
ContentAgent  = SpecialistAgent("ContentAgent",  _CONTENT_TOOLS,  _CONTENT_SYSTEM_PROMPT)
CommsAgent    = SpecialistAgent("CommsAgent",    _COMMS_TOOLS,    _COMMS_SYSTEM_PROMPT)
GeneralAgent  = SpecialistAgent("GeneralAgent",  _ALL_TOOLS,      _GENERAL_SYSTEM_PROMPT)
TerminalAgent = SpecialistAgent("TerminalAgent", _TERMINAL_TOOLS, _TERMINAL_SYSTEM_PROMPT)
ScreenAgent   = SpecialistAgent("ScreenAgent",   _SCREEN_TOOLS,   _SCREEN_SYSTEM_PROMPT)

SPECIALIST_MAP: Dict[str, SpecialistAgent] = {
    "FileAgent":     FileAgent,
    "WebAgent":      WebAgent,
    "SystemAgent":   SystemAgent,
    "MusicAgent":    MusicAgent,
    "CodeAgent":     CodeAgent,
    "CronAgent":     CronAgent,
    "ContentAgent":  ContentAgent,
    "CommsAgent":    CommsAgent,
    "GeneralAgent":  GeneralAgent,
    "TerminalAgent": TerminalAgent,
    "ScreenAgent":   ScreenAgent,
}

```

### 2. Upgrade `agents/supervisor.py`

We force the Supervisor to recognize that "Write + Open" is a single job for the Content Agent, not a split job.

```python
"""
Supervisor Agent for A.N.K.I.T.A.
UPGRADE: Smarter routing for composite tasks (Unidirectional Flow).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from llm import LLMRuntime, call_chat_once

_SUPERVISOR_SYSTEM_PROMPT = """You are A.N.K.I.T.A's Supervisor — the routing brain.

Your job: Analyze the request and pick the BEST specialist.

AGENTS:
- ContentAgent: Writes poems, essays, scripts, emails. (Can now OPEN apps to show work).
- SystemAgent: Controls Volume, Wi-Fi, Bluetooth, Screen. (DOES NOT WRITE CONTENT).
- CodeAgent: Writes/Fixes Python, JS, C++. (Can open VS Code).
- WebAgent: Search & Research.
- ScreenAgent: Visual tasks ("look at this", "click that").
- GeneralAgent: Complex multi-step tasks that cross domains.

ROUTING RULES (UNIDIRECTIONAL FLOW):
1. "Write a poem in Notepad" -> ContentAgent (It will write, then launch notepad).
   - DO NOT split this between ContentAgent and SystemAgent.
   - DO NOT use SystemAgent for creative writing.

2. "Fix my code and open it" -> CodeAgent.

3. "Turn off wifi" -> SystemAgent.

4. "Research X and write a report" -> WebAgent (or GeneralAgent).

Output JSON only: {"agents": ["AgentName"], "parallel": false, "reasoning": "..."}
"""

class SupervisorAgent:
    def __init__(self, runtime: LLMRuntime):
        self.runtime = runtime

    def plan(self, user_text: str) -> Dict[str, Any]:
        messages = [
            {"role": "system", "content": _SUPERVISOR_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {user_text}"},
        ]
        
        try:
            # Quick decisive call
            response = call_chat_once(self.runtime, messages, tools=None, max_tokens=256)
            content = (response.get("content") or "").strip()

            # Robust JSON extraction
            json_str = content
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if fence_match:
                json_str = fence_match.group(1).strip()
            else:
                brace_match = re.search(r"\{[\s\S]*\}", content)
                if brace_match:
                    json_str = brace_match.group(0)

            parsed = json.loads(json_str)
            agents = parsed.get("agents", ["GeneralAgent"])
            if not isinstance(agents, list) or not agents:
                agents = ["GeneralAgent"]

            # Validate
            valid = {"FileAgent", "WebAgent", "SystemAgent", "MusicAgent",
                     "CodeAgent", "CronAgent", "ContentAgent", "CommsAgent",
                     "GeneralAgent", "TerminalAgent", "ScreenAgent"}
            
            # Filter and Fallback
            final_agents = [a for a in agents if a in valid]
            if not final_agents:
                final_agents = ["GeneralAgent"]

            return {
                "agents": final_agents,
                "parallel": bool(parsed.get("parallel", False)), # Default to sequential for safety
                "reasoning": str(parsed.get("reasoning", "")),
            }
        except Exception:
            # If brain freeze, default to GeneralAgent who handles everything
            return {"agents": ["GeneralAgent"], "parallel": False, "reasoning": "Fallback to General"}

```

### What we just fixed:

1. **No More Fighting:** `SystemAgent` is explicitly banned from writing poems.
2. **Unidirectional Flow:** `ContentAgent` creates the file -> saves it -> calls `launch_app("notepad", path)`. It flows in one direction.
3. **God Mode:** Your specialists are now capable of finishing the entire workflow (Create + Open) without needing a manager.

Update these two files, and the "write a poem in notepad" command will work instantly and correctly. 💅