from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from jakata_agent.llm import TextCompletionClient
from jakata_agent.prompts import load_prompt


PLANNER_SYSTEM_PROMPT = load_prompt("router/planner.md")


@dataclass(slots=True)
class PlanFallback:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass(slots=True)
class PlanStep:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    fallback_to: str | None = None
    fallbacks: list[PlanFallback] = field(default_factory=list)


@dataclass(slots=True)
class PlanDecision:
    steps: list[PlanStep]
    execution_mode: str = "foreground"
    background_reason: str = ""
    direct_answer: str = ""
    memory_context: str = ""


class IntentRouter:
    BUILTIN_TOOLS = {"general_chat"}

    def __init__(self, client: TextCompletionClient) -> None:
        self.client = client

    def plan(
        self,
        user_message: str,
        tool_manifest: list[dict[str, Any]],
        memory_context: str = "",
        conversation_context: str = "",
    ) -> PlanDecision:
        manifest_text = json.dumps(tool_manifest, ensure_ascii=False, separators=(",", ":"))
        context = memory_context.strip()
        context_block = f"\n\nRelevant memory and knowledge context:\n{context}" if context else ""
        conversation = conversation_context.strip()
        conversation_block = f"\n\nRecent conversation context:\n{conversation}" if conversation else ""
        user_payload = f"Available tools:\n{manifest_text}{context_block}{conversation_block}\n\nUser message: {user_message}"

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

        answer = str(payload.get("answer", "")).strip() if isinstance(payload, dict) else ""
        if answer:
            return PlanDecision(
                steps=[PlanStep(tool="general_chat", args={}, reason="direct_answer")],
                execution_mode="foreground",
                background_reason="",
                direct_answer=answer,
                memory_context=context,
            )

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
            fallbacks = self._parse_fallbacks(item, known_tools, args)
            steps.append(PlanStep(tool=tool, args=args, reason=reason, fallbacks=fallbacks))

        if not steps:
            return self._fallback("no_valid_steps")
        return PlanDecision(
            steps=steps,
            execution_mode="foreground",
            background_reason="",
            memory_context=context,
        )

    @staticmethod
    def _fallback(reason: str) -> PlanDecision:
        return PlanDecision(
            steps=[PlanStep(tool="general_chat", args={}, reason=reason)],
            execution_mode="foreground",
            background_reason="",
        )

    @staticmethod
    def _parse_fallbacks(item: dict[str, Any], known_tools: set[str], primary_args: dict[str, Any]) -> list[PlanFallback]:
        parsed: list[PlanFallback] = []
        legacy = item.get("fallback_to")
        if isinstance(legacy, str) and legacy in known_tools:
            parsed.append(PlanFallback(tool=legacy, args=dict(primary_args), reason="legacy fallback"))

        raw_fallbacks = item.get("fallbacks", [])
        if not isinstance(raw_fallbacks, list):
            return parsed
        for fallback in raw_fallbacks[:3]:
            if not isinstance(fallback, dict):
                continue
            tool = str(fallback.get("tool", "")).strip()
            if tool not in known_tools:
                continue
            args = fallback.get("args", {})
            if not isinstance(args, dict):
                args = {}
            reason = str(fallback.get("reason", "")).strip() or "fallback"
            parsed.append(PlanFallback(tool=tool, args=args, reason=reason))
        return parsed
