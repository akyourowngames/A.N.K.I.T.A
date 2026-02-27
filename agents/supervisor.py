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

_SUPERVISOR_SYSTEM_PROMPT = """You are A.N.K.I.T.A's Supervisor — the routing brain.

Your job: Analyze the request and pick the BEST specialist.

AGENTS:
- ContentAgent: Writes poems, essays, scripts, emails. (Can now OPEN apps to show work — handles full write+open pipeline itself).
- SystemAgent: Controls Volume, Wi-Fi, Bluetooth, Screen, launches apps. (DOES NOT WRITE CONTENT).
- CodeAgent: Writes/Fixes Python, JS, C++. (Can open VS Code itself after writing).
- FileAgent: file system operations (read, write, edit, search, move, delete files/dirs).
- WebAgent: Search & Research. Can save findings to file.
- MusicAgent: music search, playback control (play, stop, current).
- CronAgent: cron job scheduling (add, list, update, remove, run).
- TerminalAgent: raw terminal/shell access — ping, ipconfig, git, tasklist, netstat, whoami, curl.
- ScreenAgent: Visual tasks ("look at this", "click that", "what's on my screen").
- CommsAgent: WhatsApp messages.
- GeneralAgent: Complex multi-step tasks that genuinely cross domains, or pure conversation.

ASSEMBLY LINE ROUTING RULES (CRITICAL — READ FIRST):
A.N.K.I.T.A uses a Relay Race model. Agents pass the baton. Each does ONE job.

1. "Write a poem" (no app) → ["ContentAgent", "FileAgent"], parallel: false
   - ContentAgent generates the text. FileAgent saves it to Desktop.

2. "Write a poem in Notepad" / "Write a letter and open it" → ["ContentAgent", "FileAgent", "SystemAgent"], parallel: false
   - ContentAgent writes. FileAgent saves. SystemAgent opens. Sequential relay.

3. "Write a report and play music while I read" → ["ContentAgent", "FileAgent", "SystemAgent", "MusicAgent"], parallel: false
   - Assembly line first, then music after. All sequential.

4. "Fix my code and open it in VS Code" → CodeAgent ONLY.
   - CodeAgent is self-sufficient for code tasks (has launch_app).

5. "Turn off wifi" / "open Notepad" (NO content) → SystemAgent ONLY.

6. "Research X and write a report" → ["WebAgent", "FileAgent"], parallel: false
   - WebAgent researches. FileAgent saves. Then add SystemAgent if "open it" requested.

SPECIALIST PRIORITY RULE:
- open/launch/close app, screenshot, volume, brightness (NO writing) → SystemAgent only
- play/stop/queue music → MusicAgent
- write/draft/create/generate text → ContentAgent (ALWAYS followed by FileAgent)
- list/read/edit/delete files (not saving new content) → FileAgent only
- search/google/news/fetch/tell me about/who is/latest news/how does/what is → WebAgent
- download/get/fetch a file/document/datasheet/PDF/report → WebAgent ONLY (WebAgent uses download_file + launch_app internally)
- run command/script/code → CodeAgent
- ping/ipconfig/git/netstat/tasklist/whoami/curl → TerminalAgent
- schedule/cron/remind → CronAgent
- what's on screen, click button visually → ScreenAgent
- GeneralAgent ONLY for pure conversation or genuinely ambiguous with NO real-world actions.

Respond ONLY with valid JSON:
{"agents": ["AgentName"], "parallel": false, "reasoning": "..."}

Examples:
- "write a poem" → {"agents": ["ContentAgent", "FileAgent"], "parallel": false, "reasoning": "ContentAgent writes, FileAgent saves — assembly line"}
- "write a poem in Notepad" → {"agents": ["ContentAgent", "FileAgent", "SystemAgent"], "parallel": false, "reasoning": "assembly line: write → save → open"}
- "write a paragraph about AI and open it in Notepad" → {"agents": ["ContentAgent", "FileAgent", "SystemAgent"], "parallel": false, "reasoning": "assembly line: write → save → open"}
- "write a pitch script for Helper ID" → {"agents": ["ContentAgent", "FileAgent"], "parallel": false, "reasoning": "ContentAgent writes, FileAgent saves"}
- "write a funny song about Python" → {"agents": ["ContentAgent", "FileAgent"], "parallel": false, "reasoning": "ContentAgent writes, FileAgent saves"}
- "write a report and play music while I read" → {"agents": ["ContentAgent", "FileAgent", "SystemAgent", "MusicAgent"], "parallel": false, "reasoning": "assembly line write→save→open, then music"}
- "play some lo-fi music and turn volume up" → {"agents": ["MusicAgent", "SystemAgent"], "parallel": true, "reasoning": "independent tasks"}
- "what time is it" → {"agents": ["GeneralAgent"], "parallel": false, "reasoning": "general knowledge"}
- "list my files" → {"agents": ["FileAgent"], "parallel": false, "reasoning": "file operation only"}
- "hit enter", "press escape", "type my password" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "keyboard interaction via desktop_interact"}
- "run test.py and fix errors" → {"agents": ["CodeAgent"], "parallel": false, "reasoning": "autonomous self-healing dev loop"}
- "open Notepad" → {"agents": ["SystemAgent"], "parallel": false, "reasoning": "just launching an app, no content"}
- "play some songs" → {"agents": ["MusicAgent"], "parallel": false, "reasoning": "music playback"}
- "ping google.com" → {"agents": ["TerminalAgent"], "parallel": false, "reasoning": "raw CLI command"}
- "what's on my screen" → {"agents": ["ScreenAgent"], "parallel": false, "reasoning": "screen vision"}
- "click the Deploy button" → {"agents": ["ScreenAgent"], "parallel": false, "reasoning": "visual click"}
- "get me the LM555 datasheet" → {"agents": ["WebAgent"], "parallel": false, "reasoning": "file hunt: search filetype:pdf → download_file → launch_app"}
- "download the annual report PDF" → {"agents": ["WebAgent"], "parallel": false, "reasoning": "WebAgent searches, downloads and opens the file autonomously"}
- "fetch the numpy cheatsheet" → {"agents": ["WebAgent"], "parallel": false, "reasoning": "file fetch: search → identify PDF URL → download_file → open"}
- "what am I holding?" → {"agents": ["ScreenAgent"], "parallel": false, "reasoning": "webcam task: capture_webcam → vision analysis"}
- "take a selfie" → {"agents": ["ScreenAgent"], "parallel": false, "reasoning": "webcam task: capture_webcam → describe photo"}

WRONG — never do this:
- "write a poem" → WRONG: {"agents": ["ContentAgent"]} ← ContentAgent has NO tools, can't save
- "write a poem in Notepad" → WRONG: {"agents": ["ContentAgent", "SystemAgent"]} ← missing FileAgent
- "play music" → WRONG: {"agents": ["GeneralAgent"]} ← causes text instructions instead of action
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
                     "GeneralAgent", "TerminalAgent", "ScreenAgent"}
            agents = [a for a in agents if a in valid] or ["GeneralAgent"]

            return {
                "agents": agents,
                "parallel": bool(parsed.get("parallel", False)),  # Default sequential for safety
                "reasoning": str(parsed.get("reasoning", "")),
            }
        except Exception as err:
            return {"agents": ["GeneralAgent"], "parallel": False, "reasoning": f"fallback ({err})"}
