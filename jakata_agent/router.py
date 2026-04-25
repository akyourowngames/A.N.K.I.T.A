from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from jakata_agent.llm import TextCompletionClient


PLANNER_SYSTEM_PROMPT = """You are the JAKATA task planner.

You will receive:
1. The user's message
2. A JSON list of available tools

Return JSON only. No prose, no markdown fences.

Your job: pick the minimum steps needed to answer the user.
All normal chat requests run in the foreground. Background execution is only
requested explicitly through the CLI /bg command and is handled outside this planner.

Each step:
  "tool"   : name from the tools list OR "general_chat"
  "args"   : object matching that tool's required args
  "reason" : one short sentence

STRICT RULES:

1. "general_chat" - use ONLY for normal conversation. Questions, follow-ups, opinions, how-to advice.
   Examples: "what can you do", "explain X", "tell me about Y", "how does Z work"

2. "keyboard" - use ONLY when the user wants to literally control a keyboard/send keystrokes/press hotkeys.
   NOT for "what can you do" or any question. Only for actual input control commands.
   Examples: "press ctrl+s", "type hello", "press enter", "run hotkey ctrl+c"

3. "system" - use for built-in system/device controls and local PC state checks like
   volume, brightness, Bluetooth, recycle bin, power/session actions, launching apps,
   opening paths/URLs/settings, process listing, process lookup, and machine status.
   Examples: "increase volume", "set brightness to 50", "turn bluetooth on",
   "open recycle bin", "show my pc status", "find the chrome process"

4. "shell" - use for arbitrary terminal commands, scripts, package installs, git, and OS tasks
   that are not covered by the dedicated system tool.
   Examples: "run speed test", "run python script", "pip install x", "git status"

5. "window" - use ONLY to focus/list/minimize application windows.

6. "memory" - use for questions about what JAKATA knows/remembers about the user.
   Examples: "what do you know about me", "what's my name", "what is my name", "my name", "where do I live"

7. "datetime" - use for time/date questions.

8. "weather" - use for weather/temperature questions. Set "location" from user message.

9. "search_web" - use for current events, news, live facts, prices, people's roles.
   Rewrite the query to be a clean search-engine query.

10. "read_file", "list_dir", "search_files", "write_file" - use for file operations.

11. "camera" - use for webcam capture or live scene analysis when the user asks what JAKATA can currently see,
    wants the current camera view described, or asks to inspect something visible in front of the PC camera.
    Examples: "what do you see", "describe the live camera feed", "look at what's in front of you"

12. "os_agent" - use for goal-oriented desktop/browser/OS operation, app workflows,
    window/browser control tasks, repeated attempts, and anything that needs
    verify-and-repair loops instead of a single direct tool call.

13. "image_generation" - use when the user asks to generate, create, draw, or render a new image
    from a text prompt. Put the whole requested image description in "prompt".

DISAMBIGUATION EXAMPLES:
"what can you do" -> general_chat + foreground
"open chrome" -> system with action=launch_app target="chrome.exe" + foreground
"increase volume" -> system with action=volume operation="up" + foreground
"show my pc status" -> system with action=status + foreground
"press ctrl+s" -> keyboard with action=hotkey keys=ctrl+s + foreground
"list my files" -> list_dir + foreground
"run speed test" -> shell with command "speedtest-cli" or "speedtest" + foreground
"what time is it" -> datetime + foreground
"who is the CEO of nvidia" -> search_web + foreground
"what do you see right now" -> camera with action=describe + foreground
"refresh chrome and wait for the dashboard to load" -> os_agent + foreground
"open the site, log in, keep trying until the dashboard loads" -> os_agent + foreground
"generate image of a neon sports car" -> image_generation with prompt="a neon sports car" + foreground

If user asks for multiple things in one message, emit multiple steps (one per thing).
Never emit two steps for the same tool for the same query.

Output format:
{
  "steps": [{"tool": "...", "args": {...}, "reason": "..."}]
}
"""


@dataclass(slots=True)
class PlanStep:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    fallback_to: str | None = None


@dataclass(slots=True)
class PlanDecision:
    steps: list[PlanStep]
    execution_mode: str = "foreground"
    background_reason: str = ""


class IntentRouter:
    BUILTIN_TOOLS = {"general_chat"}

    def __init__(self, client: TextCompletionClient) -> None:
        self.client = client

    def plan(self, user_message: str, tool_manifest: list[dict[str, Any]]) -> PlanDecision:
        manifest_text = json.dumps(tool_manifest, indent=2)
        user_payload = f"Available tools:\n{manifest_text}\n\nUser message: {user_message}"

        _, raw = self.client.complete_text(PLANNER_SYSTEM_PROMPT, user_payload, temperature=0.0)
        cleaned = raw.strip().replace("```json", "").replace("```", "").strip()

        brace = cleaned.find("{")
        if brace > 0:
            cleaned = cleaned[brace:]
        end_brace = cleaned.rfind("}")
        if end_brace >= 0:
            cleaned = cleaned[: end_brace + 1]

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return self._fallback("parse_error")

        raw_steps = payload.get("steps") if isinstance(payload, dict) else None
        if not isinstance(raw_steps, list) or not raw_steps:
            return self._fallback("empty_steps")

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

        if not steps:
            return self._fallback("no_valid_steps")
        return PlanDecision(
            steps=steps,
            execution_mode="foreground",
            background_reason="",
        )

    @staticmethod
    def _fallback(reason: str) -> PlanDecision:
        return PlanDecision(
            steps=[PlanStep(tool="general_chat", args={}, reason=reason)],
            execution_mode="foreground",
            background_reason="",
        )
