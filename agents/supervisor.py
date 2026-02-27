"""
Supervisor Agent for A.N.K.I.T.A.

The Supervisor's only job is to read the user's request and decide:
  - Which specialist agent(s) should handle it
  - Whether they can run in parallel

It uses a lightweight LLM call with a structured JSON response.
Falls back to GeneralAgent if routing fails.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from llm import LLMRuntime, call_chat_once

_SUPERVISOR_SYSTEM_PROMPT = """You are A.N.K.I.T.A's Supervisor — a routing intelligence.

Your job: Analyse the user's request and decide which specialist agents to invoke.

Available specialist agents:
- FileAgent: file system operations (read, write, edit, search, move, delete files/dirs)
- WebAgent: real-time web search, news lookup
- SystemAgent: system control (volume, brightness, WiFi, Bluetooth, launch/close apps, screenshot)
- MusicAgent: music search, playback control (play, stop, current)
- CodeAgent: terminal commands, script execution, code patches
- CronAgent: cron job scheduling (add, list, update, remove, run)
- ContentAgent: generate and save any text content — reports, scripts, songs, pitch decks, summaries, emails, essays, poems
- TerminalAgent: raw terminal/shell access — ping servers, ipconfig, git commands, dir/ls, run Python scripts, check network/system info, tasklist, netstat, whoami, curl
- GeneralAgent: everything else, complex multi-domain tasks, general conversation

Rules:
1. Pick the MINIMUM set of agents needed.
2. If the task spans multiple independent domains, list them ALL — they can run in parallel.
3. If unsure or the task is conversational, use GeneralAgent alone.
4. Tasks that depend on each other must be handled by a single agent or GeneralAgent.
5. Use ContentAgent whenever the user asks to 'write', 'draft', 'create', or 'generate' a piece of text content.
6. DEPENDENCY RULE (CRITICAL): If Agent A must CREATE or WRITE a file/content that Agent B will then OPEN, READ, or USE — you MUST set "parallel": false. The producer agent runs first and its full absolute file path is passed to the consumer agent. Example chains that MUST be sequential (parallel: false):
   - ContentAgent writes → SystemAgent opens in Notepad/app
   - FileAgent writes → SystemAgent opens
   - ContentAgent writes → CodeAgent reads/runs
   If tasks are truly independent (e.g. play music + take screenshot), parallel: true is fine.
7. SPECIALIST PRIORITY RULE (CRITICAL): NEVER route to GeneralAgent if the task clearly maps to a specialist. Use the right agent:
   - User says open/launch/close an app, take screenshot, volume, brightness → SystemAgent
   - User says play/stop/queue music → MusicAgent
   - User says write/draft/create/generate text → ContentAgent
   - User says list/read/save/delete files → FileAgent
   - User says search/google/news/fetch → WebAgent
   - User says run command/script/code in workspace → CodeAgent
   - User says ping/ipconfig/git/netstat/tasklist/whoami/curl or any raw CLI command → TerminalAgent
   - User says schedule/cron/remind → CronAgent
   GeneralAgent is ONLY for pure conversation, greetings, or genuinely ambiguous requests with NO real-world actions.
8. AUTONOMOUS EXECUTION RULE: You are routing for an AUTONOMOUS EXECUTION SYSTEM, not a text chatbot. Every action the user requests MUST be executed by a specialist agent. Never route a task to GeneralAgent just because it seems complex — complexity is handled inside each specialist.

Respond ONLY with valid JSON in this exact format (no extra text):
{
  "agents": ["AgentName1", "AgentName2"],
  "parallel": true,
  "reasoning": "brief explanation"
}

Examples:
- "play some lo-fi music and turn volume up" → {"agents": ["MusicAgent", "SystemAgent"], "parallel": true, "reasoning": "independent tasks"}
- "search web for Python tips and save to a file" → {"agents": ["GeneralAgent"], "parallel": false, "reasoning": "sequential: search then write"}
- "what time is it" → {"agents": ["GeneralAgent"], "parallel": false, "reasoning": "general knowledge"}
- "list my files" → {"agents": ["FileAgent"], "parallel": false, "reasoning": "file operation only"}
- "write a pitch script for Helper ID" → {"agents": ["ContentAgent"], "parallel": false, "reasoning": "content generation task"}
- "draft a progress report on the OpenClaw architecture" → {"agents": ["ContentAgent"], "parallel": false, "reasoning": "content generation task"}
- "write a funny song about Python" → {"agents": ["ContentAgent"], "parallel": false, "reasoning": "creative writing task"}
- "hit enter", "press escape", "type my password" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "keyboard interaction via desktop_interact"}
- "press ctrl+shift+esc" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "keyboard shortcut via desktop_interact"}
- "deep dive into X", "research and investigate" → {"agents": ["WebAgent"], "parallel": false, "reasoning": "deep research mode"}
- "run test.py and fix errors" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "autonomous self-healing dev loop"}
- "write a paragraph about AI and open it in Notepad" → {"agents": ["ContentAgent", "SystemAgent"], "parallel": false, "reasoning": "ContentAgent must write file first before SystemAgent can open it — dependency chain"}
- "write a paragraph about AI, open it in Notepad, and play music while I read it" → {"agents": ["ContentAgent", "SystemAgent", "MusicAgent"], "parallel": false, "reasoning": "ContentAgent writes first, SystemAgent opens after, MusicAgent plays — sequential to avoid race condition"}
- "open Notepad" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "app launch is SystemAgent"}
- "play some songs" → {"agents": ["MusicAgent"], "parallel": false, "reasoning": "music playback is MusicAgent"}
- "take a screenshot" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "screenshot is SystemAgent"}
- "ping google.com" → {"agents": ["TerminalAgent"], "parallel": false, "reasoning": "raw CLI command is TerminalAgent"}
- "what is my IP address" → {"agents": ["TerminalAgent"], "parallel": false, "reasoning": "ipconfig is TerminalAgent"}
- "run git status" → {"agents": ["TerminalAgent"], "parallel": false, "reasoning": "git command is TerminalAgent"}
- "show running processes" → {"agents": ["TerminalAgent"], "parallel": false, "reasoning": "tasklist is TerminalAgent"}

WRONG examples (never do this):
- "write a paragraph about AI and open it in Notepad" → WRONG: {"agents": ["GeneralAgent"]} ← this causes lazy text response instead of action
- "play music" → WRONG: {"agents": ["GeneralAgent"]} ← this causes text instructions instead of playing music
"""


class SupervisorAgent:
    """
    Routes user requests to the appropriate specialist agent(s).
    """

    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def route(self, user_text: str) -> Dict[str, Any]:
        """
        Returns:
            {
                "agents": ["FileAgent", ...],
                "parallel": bool,
                "reasoning": str
            }
        Falls back to GeneralAgent on any error.
        """
        messages = [
            {"role": "system", "content": _SUPERVISOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        try:
            response = call_chat_once(self.runtime, messages, tools=None, max_tokens=256)
            content = (response.get("content") or "").strip()

            # Extract JSON — handle markdown code fences
            json_str = content
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if fence_match:
                json_str = fence_match.group(1).strip()
            else:
                # Try to find the first {...} block
                brace_match = re.search(r"\{[\s\S]*\}", content)
                if brace_match:
                    json_str = brace_match.group(0)

            parsed = json.loads(json_str)
            agents = parsed.get("agents", ["GeneralAgent"])
            if not isinstance(agents, list) or not agents:
                agents = ["GeneralAgent"]

            # Validate agent names
            valid = {"FileAgent", "WebAgent", "SystemAgent", "MusicAgent",
                     "CodeAgent", "CronAgent", "ContentAgent", "CommsAgent",
                     "GeneralAgent", "TerminalAgent"}
            agents = [a for a in agents if a in valid] or ["GeneralAgent"]

            return {
                "agents": agents,
                "parallel": bool(parsed.get("parallel", len(agents) > 1)),
                "reasoning": str(parsed.get("reasoning", "")),
            }
        except Exception as err:
            return {"agents": ["GeneralAgent"], "parallel": False, "reasoning": f"fallback ({err})"}
