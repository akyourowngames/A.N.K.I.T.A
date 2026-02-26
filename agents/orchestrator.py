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
    "You are A.N.K.I.T.A's Synthesizer. You receive the outputs from multiple specialist agents "
    "that worked on sub-tasks in parallel. Merge their results into a single, clear, natural response "
    "for the user. Do not repeat yourself. Be concise and helpful."
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

        specialists = [SPECIALIST_MAP[n] for n in agent_names if n in SPECIALIST_MAP]
        if not specialists:
            return self._run_general(user_text, messages)

        # 2. Fan-Out: run specialists (parallel or sequential)
        results: List[Dict[str, Any]] = []
        if parallel and len(specialists) > 1:
            results = self._fan_out_parallel(specialists, user_text)
        else:
            for sp in specialists:
                results.append(_run_specialist(sp, user_text, self.runtime, self.workspace_root))

        # 3. Fan-In: if only one result, return it directly
        if len(results) == 1:
            reply = results[0].get("reply", "")
            self._append_to_messages(messages, user_text, reply)
            return reply

        # 4. Synthesize multiple results
        reply = self._synthesize(user_text, results)
        self._append_to_messages(messages, user_text, reply)
        return reply

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
