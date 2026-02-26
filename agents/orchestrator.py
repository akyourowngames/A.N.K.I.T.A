"""
Orchestrator for A.N.K.I.T.A multi-agent system.

Implements the Fan-Out / Fan-In parallel execution pattern:
  1. Supervisor routes request → list of specialist agents
  2. Fan-Out: dispatch agents concurrently (ThreadPoolExecutor)
  3. Fan-In: collect results, synthesize a single cohesive response

Falls back to the base AgentRuntime if anything goes wrong.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm import LLMRuntime, call_chat_once
from tools.engine import execute_tool_call, TOOL_SPECS, compact_messages

from .supervisor import SupervisorAgent
from .specialists import SPECIALIST_MAP, SpecialistAgent

_MAX_TOOL_STEPS = 8

_SYNTHESIZER_PROMPT = (
    "You are A.N.K.I.T.A's Synthesizer. You receive outputs from specialist agents that executed tasks. "
    "Your ONLY job is to confirm what was done in ONE brief sentence.\n\n"
    "STRICT RULES:\n"
    "1. NEVER echo, repeat, or display the content that was written/generated "
    "(no paragraphs, scripts, songs, emails, or any generated text in your reply).\n"
    "2. NEVER apologize or say 'it seems there was an issue' if the agent outputs show tools succeeded.\n"
    "3. NEVER offer manual alternatives like 'you can copy this yourself' or 'open it manually'.\n"
    "4. If actions succeeded → ONE confirmation sentence. "
    "Example: 'Done — written the paragraph, opened it in Notepad, and started your music.'\n"
    "5. If a genuine error occurred (explicitly marked as failed) → ONE sentence stating what failed.\n"
    "6. You are a STATUS REPORTER, not a content displayer or a chatbot. Be terse."
)


def _run_specialist(
    specialist: SpecialistAgent,
    task: str,
    runtime: LLMRuntime,
    workspace_root: Path,
) -> Dict[str, Any]:
    """Run a single specialist agent to completion and return its result."""
    messages = specialist.make_messages(task)
    max_tokens = runtime.max_tokens

    for _ in range(_MAX_TOOL_STEPS):
        try:
            response = call_chat_once(runtime, messages, tools=specialist.tool_specs, max_tokens=max_tokens)
        except Exception as err:
            return {"agent": specialist.name, "ok": False, "reply": f"[Error] {err}"}

        tool_calls = response.get("tool_calls") or []
        messages.append({
            "role": "assistant",
            "content": response.get("content") or "",
            **({"tool_calls": tool_calls} if tool_calls else {}),
        })

        if not tool_calls:
            return {"agent": specialist.name, "ok": True, "reply": (response.get("content") or "").strip()}

        for tc in tool_calls:
            try:
                result = execute_tool_call(tc, workspace_root=workspace_root)
            except Exception as err:
                result = {"ok": False, "error": str(err)}
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": json.dumps(result, ensure_ascii=False),
            })

    return {"agent": specialist.name, "ok": True, "reply": "Task completed (max steps reached)."}


class Orchestrator:
    """
    Multi-agent orchestrator using Supervisor + parallel Specialists + Synthesizer.

    Usage:
        orch = Orchestrator(runtime, workspace_root)
        reply = orch.run(user_text, messages)
    """

    def __init__(self, runtime: LLMRuntime, workspace_root: Path) -> None:
        self.runtime = runtime
        self.workspace_root = workspace_root
        self.supervisor = SupervisorAgent(runtime)

    def run(self, user_text: str, messages: List[Dict[str, Any]]) -> str:
        """
        Full orchestration pipeline:
          Supervisor → [Fan-Out specialist(s)] → Synthesizer → reply
        """
        # 1. Supervisor routes the request
        routing = self.supervisor.route(user_text)
        agent_names: List[str] = routing["agents"]
        parallel: bool = routing["parallel"]
        reasoning: str = routing.get("reasoning", "")

        # Single GeneralAgent → just use the full agent runtime (cheaper, faster)
        if agent_names == ["GeneralAgent"]:
            return self._run_general(user_text, messages)

        # Override lazy GeneralAgent routing: if the Supervisor chose only GeneralAgent
        # but the user text clearly maps to a specialist, re-route to the right agent.
        _ACTION_OVERRIDES = {
            "play_music": ({"play", "song", "music", "listen", "lofi", "lo-fi"}, ["MusicAgent"]),
            "stop_music": ({"stop music", "pause music"}, ["MusicAgent"]),
            "screenshot": ({"screenshot", "screen capture", "take a screenshot"}, ["SystemAgent"]),
            "launch_app": ({"open notepad", "launch", "open app", "start app"}, ["SystemAgent"]),
            "write_content": ({"write a", "draft a", "generate a", "create a report",
                               "write an essay", "write a poem", "write a script",
                               "write a song", "write a paragraph"}, ["ContentAgent"]),
            "search_web": ({"search for", "google", "look up", "find info"}, ["WebAgent"]),
            "execute_shell": ({"ping ", "ipconfig", "netstat", "tasklist", "whoami",
                               "git status", "git log", "git pull", "git push",
                               "run git", "run script", "terminal command",
                               "shell command", "what is my ip", "my ip address",
                               "show processes", "running processes"}, ["TerminalAgent"]),
        }
        text_lower = user_text.lower()
        if agent_names == ["GeneralAgent"]:
            for _tool, (keywords, reroute_agents) in _ACTION_OVERRIDES.items():
                if any(kw in text_lower for kw in keywords):
                    agent_names = reroute_agents
                    parallel = False
                    break

        specialists = [SPECIALIST_MAP[n] for n in agent_names if n in SPECIALIST_MAP]
        if not specialists:
            return self._run_general(user_text, messages)

        # Force sequential if a producer→consumer dependency is detected
        # e.g. ContentAgent/FileAgent writes a file that SystemAgent/CodeAgent will open
        _PRODUCERS = {"ContentAgent", "FileAgent"}
        _CONSUMERS = {"SystemAgent", "CodeAgent"}
        agent_name_set = set(agent_names)
        if (_PRODUCERS & agent_name_set) and (_CONSUMERS & agent_name_set):
            parallel = False  # override Supervisor — file must exist before it's opened

        # 2. Fan-Out: run specialists (parallel or sequential)
        results: List[Dict[str, Any]] = []
        if parallel and len(specialists) > 1:
            results = self._fan_out_parallel(specialists, user_text)
        else:
            results = self._run_sequential_with_context(specialists, user_text)

        # 3. Fan-In: if only one result, return it directly
        if len(results) == 1:
            reply = results[0].get("reply", "")
            self._append_to_messages(messages, user_text, reply)
            return reply

        # 4. Synthesize multiple results
        reply = self._synthesize(user_text, results)
        self._append_to_messages(messages, user_text, reply)
        return reply

    def _run_sequential_with_context(
        self, specialists: List[SpecialistAgent], task: str
    ) -> List[Dict[str, Any]]:
        """Run specialists one by one, passing each result as context to the next.

        This solves both the Race Condition and the Path Drop bugs:
        - Race Condition: agents run sequentially, so files exist before being opened
        - Path Drop: each agent's full reply (including FILE_PATH: ...) is appended
          to the next agent's task so absolute paths are never lost
        """
        results: List[Dict[str, Any]] = []
        context_so_far = ""  # accumulates previous agents' replies

        for sp in specialists:
            # Build the task for this agent — include prior context so paths propagate
            if context_so_far:
                enriched_task = (
                    f"{task}\n\n"
                    f"--- Context from previous agents ---\n{context_so_far}\n"
                    f"--- End context ---\n\n"
                    f"Use the FILE_PATH above if you need to open/read a file."
                )
            else:
                enriched_task = task

            result = _run_specialist(sp, enriched_task, self.runtime, self.workspace_root)
            results.append(result)

            # Accumulate this agent's reply so the next agent sees it
            reply = result.get("reply", "")
            if reply:
                context_so_far += f"[{sp.name}]: {reply}\n"

        return results

    @staticmethod
    def _extract_file_path(text: str) -> Optional[str]:
        """Extract FILE_PATH: <path> from an agent reply."""
        import re
        match = re.search(r"FILE_PATH:\s*(.+?)(?:\n|$)", text)
        if match:
            return match.group(1).strip()
        return None

    def _fan_out_parallel(
        self, specialists: List[SpecialistAgent], task: str
    ) -> List[Dict[str, Any]]:
        """Dispatch specialists concurrently and collect results."""
        results = [None] * len(specialists)
        with ThreadPoolExecutor(max_workers=min(len(specialists), 4)) as executor:
            future_to_idx = {
                executor.submit(_run_specialist, sp, task, self.runtime, self.workspace_root): i
                for i, sp in enumerate(specialists)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as err:
                    results[idx] = {"agent": specialists[idx].name, "ok": False, "reply": f"[Error] {err}"}
        return results

    def _synthesize(self, user_text: str, results: List[Dict[str, Any]]) -> str:
        """Merge multiple specialist outputs into a single cohesive response."""
        parts = []
        for r in results:
            agent = r.get("agent", "Agent")
            reply = r.get("reply", "")
            if reply:
                parts.append(f"[{agent}]: {reply}")

        combined = "\n\n".join(parts)
        synth_messages = [
            {"role": "system", "content": _SYNTHESIZER_PROMPT},
            {"role": "user", "content": f"Original request: {user_text}\n\nAgent outputs:\n{combined}"},
        ]
        try:
            response = call_chat_once(self.runtime, synth_messages, tools=None, max_tokens=self.runtime.max_tokens)
            return (response.get("content") or combined).strip()
        except Exception:
            return combined

    def _run_general(self, user_text: str, messages: List[Dict[str, Any]]) -> str:
        """Fallback: use full AgentRuntime-style loop with all tools."""
        from agent_runtime import AgentRuntime
        # Reuse the same runtime; create a temp AgentRuntime
        agent = AgentRuntime(runtime=self.runtime, workspace_root=self.workspace_root)
        messages.append({"role": "user", "content": user_text})
        try:
            return agent.run_turn(messages, tools=TOOL_SPECS)
        except Exception as err:
            if messages and messages[-1].get("role") == "user":
                messages.pop()
            return f"[Error] {err}"

    def _append_to_messages(
        self, messages: List[Dict[str, Any]], user_text: str, reply: str
    ) -> None:
        """Append the user/assistant turn to the shared message history."""
        # Only append if user message is not already there
        if not messages or messages[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": reply})
