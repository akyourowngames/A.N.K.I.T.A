from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from jakata_agent.llm import NvidiaChatClient


PLANNER_SYSTEM_PROMPT = """You are the JAKATA task planner.

Return JSON only.

Break the user's message into one or more steps. Each step must have:
- kind: one of general_chat, memory, datetime, weather, search_web
- args: an object
- reason: short explanation

Rules:
- Use multiple steps when the user asks for multiple things in one message.
- greetings or casual chat only -> one general_chat step
- personal facts/preferences/name/location/remembered details -> memory
- time/date/day/month/year questions -> datetime
- weather/temperature/forecast questions -> weather
- requests to search online, latest news, current events, CEO, prices, live facts -> search_web
- For weather, set args.location when the location is available.
- For search_web, set args.query to the actual search query, not the whole sentence when obvious.
- For datetime, args can be {"include_utc": true}
- general_chat should usually be alone unless the user also asked for factual/tool tasks

Output format:
{
  "steps": [
    {"kind":"memory","args":{},"reason":"..."},
    {"kind":"weather","args":{"location":"Delhi","units":"metric"},"reason":"..."}
  ]
}
"""


@dataclass(slots=True)
class PlanStep:
    kind: str
    args: dict[str, Any]
    reason: str


class IntentRouter:
    VALID_KINDS = {"general_chat", "memory", "datetime", "weather", "search_web"}

    def __init__(self, client: NvidiaChatClient) -> None:
        self.client = client

    def plan(self, user_message: str) -> list[PlanStep]:
        _, raw = self.client.complete_text(PLANNER_SYSTEM_PROMPT, user_message)
        cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return self._fallback_plan(user_message, "planner_json_error")

        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            return self._fallback_plan(user_message, "planner_missing_steps")

        steps: list[PlanStep] = []
        for item in raw_steps:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            if kind not in self.VALID_KINDS:
                continue
            args = item.get("args", {})
            if not isinstance(args, dict):
                args = {}
            reason = str(item.get("reason", "")).strip() or "llm_planner"
            steps.append(PlanStep(kind=kind, args=args, reason=reason))

        if not steps:
            return self._fallback_plan(user_message, "planner_invalid_steps")
        return self._normalize_steps(user_message, steps)

    def _normalize_steps(self, user_message: str, steps: list[PlanStep]) -> list[PlanStep]:
        normalized: list[PlanStep] = []
        seen: set[tuple[str, str]] = set()
        for step in steps:
            kind = step.kind
            args = dict(step.args)

            if kind == "datetime":
                args["include_utc"] = True
            elif kind == "weather":
                args.setdefault("location", self._infer_location(user_message) or "London")
                args.setdefault("units", "metric")
            elif kind == "search_web":
                args.setdefault("query", self._clean_search_query(user_message))
                args.setdefault("topic", self._infer_search_topic(user_message))
                args.setdefault("max_results", 5)

            dedupe_key = (kind, json.dumps(args, sort_keys=True))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized.append(PlanStep(kind=kind, args=args, reason=step.reason))

        return normalized or self._fallback_plan(user_message, "planner_normalized_empty")

    def _fallback_plan(self, user_message: str, reason: str) -> list[PlanStep]:
        lowered = user_message.lower().strip()
        steps: list[PlanStep] = []
        if self._is_memory_question(lowered):
            steps.append(PlanStep("memory", {}, reason))
        if self._is_datetime_question(lowered):
            steps.append(PlanStep("datetime", {"include_utc": True}, reason))
        if self._is_weather_question(lowered):
            steps.append(
                PlanStep(
                    "weather",
                    {"location": self._infer_location(user_message) or "London", "units": "metric"},
                    reason,
                )
            )
        if self._is_search_question(lowered):
            steps.append(
                PlanStep(
                    "search_web",
                    {
                        "query": self._clean_search_query(user_message),
                        "topic": self._infer_search_topic(user_message),
                        "max_results": 5,
                    },
                    reason,
                )
            )
        if not steps:
            steps.append(PlanStep("general_chat", {}, reason))
        return steps

    @staticmethod
    def _is_memory_question(lowered: str) -> bool:
        triggers = [
            "what do you know about me",
            "what do yu know about me",
            "what do you remember about me",
            "where do i live",
            "what's my name",
            "whats my name",
            "who am i",
            "tell me my name",
        ]
        return any(trigger in lowered for trigger in triggers)

    @staticmethod
    def _is_datetime_question(lowered: str) -> bool:
        phrases = [
            "what time",
            "current time",
            "local time",
            "time is it",
            "what's the time",
            "whats the time",
            "what is the date",
            "today's date",
            "todays date",
            "current date",
        ]
        return any(phrase in lowered for phrase in phrases)

    @staticmethod
    def _is_weather_question(lowered: str) -> bool:
        return any(token in lowered for token in ["weather", "temperature", "forecast"])

    @staticmethod
    def _is_search_question(lowered: str) -> bool:
        return any(
            token in lowered
            for token in ["search", "online", "latest", "news", "current ceo", "ceo of", "price of", "stock price", "release news"]
        )

    @staticmethod
    def _infer_location(user_message: str) -> str | None:
        lowered = user_message.lower()
        for marker in [" in ", " for ", " at "]:
            if marker in lowered:
                idx = lowered.rfind(marker)
                return user_message[idx + len(marker) :].strip(" ?.,")
        return None

    @staticmethod
    def _clean_search_query(user_message: str) -> str:
        cleaned = user_message.strip()
        prefixes = ["search online for", "search online:", "search online", "search:", "look online for", "find online"]
        lowered = cleaned.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return cleaned[len(prefix) :].strip(" :")
        if "latest fastapi release news" in lowered:
            return "latest FastAPI release news"
        if "latest nvidia news" in lowered:
            return "latest NVIDIA news"
        if "nvidia ceo" in lowered:
            return "latest NVIDIA CEO news"
        return cleaned.replace("-", " ")

    @staticmethod
    def _infer_search_topic(user_message: str) -> str:
        lowered = user_message.lower()
        if any(token in lowered for token in ["stock", "market", "share price", "finance"]):
            return "finance"
        if any(token in lowered for token in ["news", "breaking", "today", "latest"]):
            return "news"
        return "general"
