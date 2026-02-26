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
- GeneralAgent: everything else, complex multi-domain tasks, general conversation

Rules:
1. Pick the MINIMUM set of agents needed.
2. If the task spans multiple independent domains, list them ALL — they can run in parallel.
3. If unsure or the task is conversational, use GeneralAgent alone.
4. Tasks that depend on each other must be handled by a single agent or GeneralAgent.
5. Use ContentAgent whenever the user asks to 'write', 'draft', 'create', or 'generate' a piece of text content.

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
                     "CodeAgent", "CronAgent", "ContentAgent", "GeneralAgent"}
            agents = [a for a in agents if a in valid] or ["GeneralAgent"]

            return {
                "agents": agents,
                "parallel": bool(parsed.get("parallel", len(agents) > 1)),
                "reasoning": str(parsed.get("reasoning", "")),
            }
        except Exception as err:
            return {"agents": ["GeneralAgent"], "parallel": False, "reasoning": f"fallback ({err})"}
