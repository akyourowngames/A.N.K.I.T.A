"""
agents/context_agent.py
=======================
ContextAgent — The Memory Synthesizer

Runs BEFORE the Supervisor on every message to extract context from conversation history.
Builds a CONTEXT_BLOCK that helps the Supervisor make better routing decisions.

Purpose:
--------
When user says "finish that" after a long coding session, the Supervisor has no idea what "that" is.
ContextAgent reads the last 10 turns, extracts entities (names, files, URLs, tasks), and injects
a clean CONTEXT_BLOCK into the Supervisor's routing decision.

Example Output:
--------------
CONTEXT: user was debugging main.py, last error was ModuleNotFoundError at line 47, last agent was CodeAgent
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from llm import LLMRuntime, call_chat_once


_CONTEXT_AGENT_SYSTEM_PROMPT = """You are A.N.K.I.T.A's Context Synthesizer.

Your job: Analyze the last 10 conversation turns and extract a compact CONTEXT_BLOCK.

Extract:
  - active_agent: Which agent was last working (CodeAgent, FileAgent, WebAgent, etc.)
  - active_file: Which file was being edited/read (if any)
  - active_task: What task was being performed (debugging, writing, searching, etc.)
  - last_result: What was the outcome (success, error, partial completion)
  - pending_follow_up: What the user likely wants to do next

Output format (JSON):
{
  "active_agent": "CodeAgent",
  "active_file": "main.py",
  "active_task": "debugging ModuleNotFoundError",
  "last_result": "error at line 47",
  "pending_follow_up": "fix the import error",
  "entities": ["main.py", "ModuleNotFoundError", "line 47"]
}

Rules:
- Keep it SHORT — max 200 tokens total
- Extract ONLY facts from the conversation, never hallucinate
- If no clear context, return minimal JSON with nulls
- Focus on the MOST RECENT activity (last 2-3 turns)
- Identify pronouns: "that", "it", "this" → what do they refer to?

Examples:

Conversation:
  User: "fix the bug in main.py"
  Assistant: "Found a NameError on line 47. The variable 'config' is not defined."
  User: "finish that"

Output:
{
  "active_agent": "CodeAgent",
  "active_file": "main.py",
  "active_task": "fixing NameError",
  "last_result": "identified error at line 47",
  "pending_follow_up": "apply the fix to main.py",
  "entities": ["main.py", "line 47", "NameError", "config"]
}

Conversation:
  User: "write a poem about dogs"
  Assistant: "Here's a poem about dogs... [poem text]"
  User: "save it"

Output:
{
  "active_agent": "ContentAgent",
  "active_file": null,
  "active_task": "writing poem about dogs",
  "last_result": "poem generated successfully",
  "pending_follow_up": "save the poem to a file",
  "entities": ["poem", "dogs"]
}

Conversation:
  User: "what's the weather"
  Assistant: "It's 72°F and sunny in your area."
  User: "thanks"

Output:
{
  "active_agent": "GeneralAgent",
  "active_file": null,
  "active_task": "weather query",
  "last_result": "provided weather information",
  "pending_follow_up": null,
  "entities": ["weather", "72°F", "sunny"]
}
"""


class ContextAgent:
    """
    Lightweight context synthesizer that runs before Supervisor routing.
    Extracts entities and task context from recent conversation history.
    """

    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def synthesize(self, history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Analyze conversation history and extract context.

        Args:
            history: Last N conversation turns (user/assistant messages)

        Returns:
            Context dict with active_agent, active_file, active_task, etc.
            Returns None if history is too short or analysis fails.
        """
        if not history or len(history) < 2:
            return None

        # Take last 10 turns (5 user + 5 assistant exchanges)
        recent = history[-10:]

        # Build a compact summary for the LLM
        conversation_text = []
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:500]  # Truncate long messages
            conversation_text.append(f"{role.capitalize()}: {content}")

        prompt = "Analyze this conversation and extract context:\n\n" + "\n".join(conversation_text)

        try:
            response = call_chat_once(
                self.runtime,
                [
                    {"role": "system", "content": _CONTEXT_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                tools=None,
                max_tokens=200,
            )

            content = (response.get("content") or "").strip()

            # Parse JSON from response
            import json
            import re

            # Try to extract JSON from markdown code fence
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                # Try to find raw JSON object
                json_match = re.search(r"\{[\s\S]*\}", content)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    return None

            context = json.loads(json_str)
            return context

        except Exception as err:
            print(f"[ContextAgent] Error synthesizing context: {err}", flush=True)
            return None

    def format_context_block(self, context: Dict[str, Any]) -> str:
        """
        Format context dict into a text block for injection into Supervisor prompt.

        Args:
            context: Context dict from synthesize()

        Returns:
            Formatted text block
        """
        if not context:
            return ""

        lines = ["## CONVERSATION CONTEXT (from ContextAgent):"]

        if context.get("active_agent"):
            lines.append(f"  - Last active agent: {context['active_agent']}")

        if context.get("active_file"):
            lines.append(f"  - Working on file: {context['active_file']}")

        if context.get("active_task"):
            lines.append(f"  - Current task: {context['active_task']}")

        if context.get("last_result"):
            lines.append(f"  - Last result: {context['last_result']}")

        if context.get("pending_follow_up"):
            lines.append(f"  - User likely wants to: {context['pending_follow_up']}")

        if context.get("entities"):
            entities = ", ".join(context["entities"][:5])  # Max 5 entities
            lines.append(f"  - Key entities: {entities}")

        lines.append("")  # Trailing newline
        return "\n".join(lines)
