from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from llm_router_testbed.router import MandatoryRouter, RouterResult
from llm_router_testbed.router.router import RouterAttempt

from jakata_agent.config import Settings
from jakata_agent.tools.registry import ToolRegistry


GENERAL_CHAT_TOOL_NAME = "general_chat"
MANDATORY_ROUTER_ENABLED_ENV = "JAKATA_MANDATORY_ROUTER_ENABLED"
MANDATORY_ROUTER_FALLBACK_ENV = "JAKATA_MANDATORY_ROUTER_EMERGENCY_FALLBACK"


def mandatory_router_enabled() -> bool:
    return _env_bool(MANDATORY_ROUTER_ENABLED_ENV, True)


def mandatory_router_emergency_fallback_enabled() -> bool:
    return _env_bool(MANDATORY_ROUTER_FALLBACK_ENV, False)


@dataclass(slots=True)
class LocalIntentClassifierConfig:
    enabled: bool = True
    confidence_threshold: float = 0.86
    margin_threshold: float = 0.08
    min_tool_score: float = 0.62
    max_tools: int = 2


class LocalFirstMandatoryRouter:
    def __init__(
        self,
        *,
        tools_payload: dict[str, Any],
        local_embedder: Any,
        fallback_router: MandatoryRouter,
        config: LocalIntentClassifierConfig,
    ) -> None:
        self.tools_payload = tools_payload
        self.local_embedder = local_embedder
        self.fallback_router = fallback_router
        self.config = config

    def route(self, user_message: str) -> RouterResult:
        local_result = self._route_local(user_message)
        if local_result is not None:
            return local_result
        return self.fallback_router.route(user_message)

    def _route_local(self, user_message: str) -> RouterResult | None:
        if not self.config.enabled or self.local_embedder is None:
            return None
        tools = [item for item in self.tools_payload.get("tools", []) if isinstance(item, dict)]
        if not tools:
            return None
        texts = [self._tool_text(item) for item in tools]
        started = time.perf_counter()
        try:
            scores = [float(item) for item in self.local_embedder.similarity_many(user_message, texts)]
        except Exception:
            return None
        ranked = sorted(zip(scores, tools, strict=False), key=lambda item: item[0], reverse=True)
        if not ranked:
            return None
        best_score = ranked[0][0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = best_score - second_score
        if best_score < self.config.confidence_threshold or margin < self.config.margin_threshold:
            return None
        selected = [
            str(tool.get("label", "")).strip()
            for score, tool in ranked[: max(1, self.config.max_tools)]
            if score >= self.config.min_tool_score and str(tool.get("label", "")).strip()
        ]
        if not selected:
            return None
        output = "[" + ",".join(json_string(label) for label in selected) + "]"
        return RouterResult(
            tools=selected,
            output=output,
            raw_output=output,
            model="local:intent-embedding",
            latency_ms=(time.perf_counter() - started) * 1000,
            attempts=[
                RouterAttempt(
                    kind="local_classify",
                    model="local:intent-embedding",
                    raw_output=output,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            ],
        )

    @staticmethod
    def _tool_text(item: dict[str, Any]) -> str:
        return "\n".join(
            str(value)
            for value in [
                item.get("label", ""),
                item.get("description", ""),
                item.get("safety", ""),
                item.get("categories", ""),
                item.get("aliases", ""),
                item.get("daily_uses", ""),
                item.get("grounding", ""),
            ]
            if value
        )


def json_string(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def build_runtime_mandatory_router(settings: Settings, tools: ToolRegistry, *, local_embedder: Any = None) -> LocalFirstMandatoryRouter | MandatoryRouter | None:
    if not mandatory_router_enabled():
        return None
    model_override = (
        os.getenv("JAKATA_MANDATORY_ROUTER_MODELS", "").strip()
        or os.getenv("JAKATA_MANDATORY_ROUTER_MODEL", "").strip()
        or "qwen/qwen3.5-122b-a10b,nvidia/nemotron-mini-4b-instruct"
    )
    tools_payload = _runtime_tools_payload(tools)
    fallback = MandatoryRouter(
        tools_payload=tools_payload,
        model=model_override,
    )
    return LocalFirstMandatoryRouter(
        tools_payload=tools_payload,
        local_embedder=local_embedder,
        fallback_router=fallback,
        config=LocalIntentClassifierConfig(
            enabled=bool(getattr(settings, "local_router_enabled", True)),
            confidence_threshold=float(getattr(settings, "local_router_confidence_threshold", 0.86) or 0.86),
            margin_threshold=float(getattr(settings, "local_router_margin_threshold", 0.08) or 0.08),
            min_tool_score=float(getattr(settings, "local_router_min_tool_score", 0.62) or 0.62),
            max_tools=int(getattr(settings, "local_router_max_tools", 2) or 2),
        ),
    )


def route_tool_labels(router: MandatoryRouter, user_message: str) -> RouterResult:
    return router.route(user_message)


def _runtime_tools_payload(tools: ToolRegistry) -> dict[str, Any]:
    payload_tools = [
        {
            "label": str(item.get("name", "")).strip(),
            "description": str(item.get("description", "")).strip(),
            "safety": str(item.get("safety", "")).strip(),
            "categories": item.get("categories", []),
            "aliases": item.get("aliases", []),
            "daily_uses": item.get("daily_uses", []),
            "grounding": str(item.get("grounding", "")).strip(),
        }
        for item in tools.manifest(public_only=False)
        if str(item.get("name", "")).strip()
    ]
    if all(item["label"] != GENERAL_CHAT_TOOL_NAME for item in payload_tools):
        payload_tools.append(
            {
                "label": GENERAL_CHAT_TOOL_NAME,
                "description": (
                    "No external tool needed. Use for direct conversational answers, explanation, reasoning, "
                    "advice, rewriting, planning, tutoring, emotional support, and questions that can be answered "
                    "without local files, live web, weather, apps, devices, or generated artifacts."
                ),
                "safety": "read_only",
            }
        )
    return {
        "version": 1,
        "source": "jakata_runtime.tools.manifest",
        "public_only": False,
        "tools": payload_tools,
    }


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "off", "no"}
