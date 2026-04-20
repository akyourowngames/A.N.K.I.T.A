from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from jakata_agent.llm import NvidiaChatClient


PLANNER_SYSTEM_PROMPT = """You are the JAKATA task planner.

You will receive:
1. The user's message
2. A JSON list of available tools

Return JSON only. No prose, no markdown fences.

Your job: pick the minimum steps needed to answer the user.

Each step:
  "tool"   : name from the tools list OR "general_chat"
  "args"   : object matching that tool's required args
  "reason" : one short sentence

STRICT RULES:

1. "general_chat" — use ONLY for normal conversation. Questions, follow-ups, opinions, how-to advice.
   Examples: "what can you do", "explain X", "tell me about Y", "how does Z work"

2. "keyboard" — use ONLY when the user wants to literally control a keyboard/send keystrokes/press hotkeys.
   NOT for "what can you do" or any question. Only for actual input control commands.
   Examples: "press ctrl+s", "type hello", "press enter", "run hotkey ctrl+c"

3. "shell" — use for OS commands, running scripts, opening apps, listing processes.
   Examples: "open chrome", "run speed test", "list running processes", "run python script"

4. "window" — use ONLY to focus/list/minimize application windows.

5. "memory" — use for questions about what JAKATA knows/remembers about the user.
   Examples: "what do you know about me", "what's my name", "what is my name", "my name", "where do I live"

6. "datetime" — use for time/date questions.

7. "weather" — use for weather/temperature questions. Set "location" from user message.

8. "search_web" — use for current events, news, live facts, prices, people's roles.
   Rewrite the query to be a clean search-engine query.

9. "read_file", "list_dir", "search_files", "write_file" — use for file operations.

DISAMBIGUATION EXAMPLES:
"what can you do" -> general_chat (it's a question, not a keyboard command)
"open chrome" -> shell with command "start chrome" or "google-chrome &"
"press ctrl+s" -> keyboard with action=hotkey keys=ctrl+s
"list my files" -> list_dir
"run speed test" -> shell with command "speedtest-cli" or "speedtest"
"what time is it" -> datetime
"who is the CEO of nvidia" -> search_web

If user asks for multiple things in one message, emit multiple steps (one per thing).
Never emit two steps for the same tool for the same query.

Output format:
{"steps": [{"tool": "...", "args": {...}, "reason": "..."}]}
"""


@dataclass(slots=True)
class PlanStep:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    fallback_to: str | None = None


class IntentRouter:
    BUILTIN_TOOLS = {"general_chat"}

    def __init__(self, client: NvidiaChatClient) -> None:
        self.client = client

    def plan(self, user_message: str, tool_manifest: list[dict[str, Any]]) -> list[PlanStep]:
        manifest_text = json.dumps(tool_manifest, indent=2)
        user_payload = f"Available tools:\n{manifest_text}\n\nUser message: {user_message}"

        _, raw = self.client.complete_text(PLANNER_SYSTEM_PROMPT, user_payload, temperature=0.0)
        cleaned = raw.strip().replace("```json", "").replace("```", "").strip()

        # Strip any leading/trailing prose around the JSON object
        brace = cleaned.find("{")
        if brace > 0:
            cleaned = cleaned[brace:]
        end_brace = cleaned.rfind("}")
        if end_brace >= 0:
            cleaned = cleaned[: end_brace + 1]

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return self._fallback(user_message, "parse_error")

        raw_steps = payload.get("steps") if isinstance(payload, dict) else None
        if not isinstance(raw_steps, list) or not raw_steps:
            return self._fallback(user_message, "empty_steps")

        known_tools = {entry["name"] for entry in tool_manifest} | self.BUILTIN_TOOLS
        steps: list[PlanStep] = []
        for item in raw_steps:
            if not isinstance(item, dict):
                continue
            tool = item.get("tool", "")
            if tool not in known_tools:
                continue
            args = item.get("args", {})
            if not isinstance(args, dict):
                args = {}
            reason = str(item.get("reason", "")).strip() or "planner"
            steps.append(PlanStep(tool=tool, args=args, reason=reason))

        return steps or self._fallback(user_message, "no_valid_steps")

    @staticmethod
    def _fallback(user_message: str, reason: str) -> list[PlanStep]:
        return [PlanStep(tool="general_chat", args={}, reason=reason)]
