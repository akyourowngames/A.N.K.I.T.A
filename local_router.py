from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any

from latency_trace import trace_mark


ROUTE_DIRECT_CHAT = "direct_chat"
ROUTE_TOOL_REQUIRED = "tool_required"
ROUTE_UNCERTAIN = "uncertain"
ROUTE_CONFIRMATION_REQUIRED = "confirmation_required"


@dataclass(frozen=True)
class RouteDecision:
    mode: str
    selected_tool_names: list[str]
    confidence: float
    reason: str
    allow_remote_selector: bool
    no_tool_confidence: float = 0.0


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    category: str
    risk: str
    requires_confirmation: bool
    tokens: frozenset[str]
    core_tokens: frozenset[str]
    identity_tokens: frozenset[str]
    name_tokens: frozenset[str]
    required_parameters: frozenset[str]


def route_chat_turn(user_text: str, session_context: list[dict[str, Any]] | None, registry: Any) -> RouteDecision:
    trace_mark("local_router_started")
    try:
        decision = route_chat_turn_inner(user_text, registry)
        trace_mark(
            "local_router_done",
            mode=decision.mode,
            confidence=round(decision.confidence, 3),
            selected_tools=decision.selected_tool_names,
        )
        return decision
    except Exception:
        trace_mark("local_router_done", mode=ROUTE_UNCERTAIN, confidence=0.0)
        return RouteDecision(
            mode=ROUTE_UNCERTAIN,
            selected_tool_names=[],
            confidence=0.0,
            reason="local router failed safely",
            allow_remote_selector=True,
            no_tool_confidence=0.0,
        )


def route_chat_turn_inner(user_text: str, registry: Any) -> RouteDecision:
    if not env_bool("JARVIS_FAST_LANE_ENABLED", True) or not env_bool("JARVIS_LOCAL_TOOL_ROUTER", True):
        return RouteDecision(ROUTE_UNCERTAIN, [], 0.0, "fast lane disabled", True, 0.0)

    query_tokens = token_weights(tokenize(user_text))
    descriptors = build_tool_descriptors(registry)
    if not query_tokens or not descriptors:
        return RouteDecision(ROUTE_DIRECT_CHAT, [], 1.0, "no local tool evidence", False, 1.0)

    token_counts: dict[str, int] = {}
    for descriptor in descriptors:
        for token in descriptor.core_tokens:
            token_counts[token] = token_counts.get(token, 0) + 1
    focus_weights = {
        token: weight / math.sqrt(token_counts[token])
        for token, weight in query_tokens.items()
        if token in token_counts
    }
    if not focus_weights:
        return RouteDecision(ROUTE_DIRECT_CHAT, [], 1.0, "no descriptor overlap", False, 1.0)

    scored = sorted(
        ((score_descriptor(focus_weights, descriptor), descriptor) for descriptor in descriptors),
        key=lambda item: (-item[0], item[1].name),
    )
    best_score, best_descriptor = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    high = env_float("JARVIS_LOCAL_ROUTER_HIGH_CONFIDENCE", 0.68)
    low = env_float("JARVIS_LOCAL_ROUTER_LOW_CONFIDENCE", 0.28)
    gap = best_score - runner_up
    no_tool_confidence = round(max(0.0, min(1.0, 1.0 - best_score)), 3)
    display_score = min(1.0, best_score)
    focus_coverage = sum(focus_weights.values()) / max(0.001, sum(query_tokens.values()))

    if best_score < low:
        return RouteDecision(
            ROUTE_DIRECT_CHAT,
            [],
            round(no_tool_confidence, 3),
            "weak local tool evidence",
            False,
            no_tool_confidence,
        )

    selected = selected_candidate_names(scored, best_score)
    risky = [descriptor for score, descriptor in scored if descriptor.name in selected and tool_needs_confirmation(descriptor)]
    best_identity_weight = identity_match_weight(focus_weights, best_descriptor)
    risky_action_evidence = risky and focus_coverage >= 0.45 and best_score >= 0.4
    if best_score < high and best_identity_weight <= 0 and not risky_action_evidence:
        if category_allows_remote_uncertainty(best_descriptor) and env_bool("JARVIS_REMOTE_SELECTOR_ON_UNCERTAIN", True):
            return RouteDecision(
                ROUTE_TOOL_REQUIRED,
                [best_descriptor.name],
                round(display_score, 3),
                "tool category needs grounded evidence",
                False,
                no_tool_confidence,
            )
        return RouteDecision(
            ROUTE_DIRECT_CHAT,
            [],
            round(max(no_tool_confidence, 1.0 - focus_coverage), 3),
            "local evidence does not match tool identity",
            False,
            round(max(no_tool_confidence, 1.0 - focus_coverage), 3),
        )
    if risky and (best_score >= high or risky_action_evidence):
        return RouteDecision(
            ROUTE_CONFIRMATION_REQUIRED,
            [risky[0].name],
            round(display_score, 3),
            "local match requires confirmation",
            False,
            no_tool_confidence,
        )
    if best_score >= high and gap >= env_float("JARVIS_LOCAL_ROUTER_MIN_GAP", 0.03):
        return RouteDecision(
            ROUTE_TOOL_REQUIRED,
            selected,
            round(display_score, 3),
            "high-confidence local tool match",
            False,
            no_tool_confidence,
        )

    return RouteDecision(
        ROUTE_UNCERTAIN,
        selected,
        round(display_score, 3),
        "local tool evidence is ambiguous",
        env_bool("JARVIS_REMOTE_SELECTOR_ON_UNCERTAIN", True),
        no_tool_confidence,
    )


def build_tool_descriptors(registry: Any) -> list[ToolDescriptor]:
    descriptors = []
    for tool in registry.visible_tools():
        identity_parts = [
            getattr(tool, "name", ""),
            getattr(tool, "category", ""),
        ]
        core_parts = [*identity_parts, getattr(tool, "description", "")]
        skill_text = getattr(tool, "skill", "")
        parameters = getattr(tool, "parameters", {})
        required = required_parameters(parameters)
        if isinstance(parameters, dict):
            properties = parameters.get("properties")
            if isinstance(properties, dict):
                for key, value in properties.items():
                    if isinstance(key, str):
                        identity_parts.append(key)
                        core_parts.append(key)
                    if isinstance(value, dict):
                        description = value.get("description")
                        if isinstance(description, str):
                            core_parts.append(description)
        name_tokens = frozenset(tokenize(getattr(tool, "name", "")))
        identity_tokens = frozenset(tokenize(" ".join(part for part in identity_parts if part)))
        core_tokens = frozenset(tokenize(" ".join(part for part in core_parts if part)))
        all_tokens = set(core_tokens)
        if isinstance(skill_text, str) and skill_text.strip():
            all_tokens.update(tokenize(skill_text))
        descriptors.append(
            ToolDescriptor(
                name=getattr(tool, "name", ""),
                category=getattr(tool, "category", ""),
                risk=getattr(tool, "risk", "read"),
                requires_confirmation=bool(getattr(tool, "requires_confirmation", False)),
                tokens=frozenset(all_tokens),
                core_tokens=core_tokens,
                identity_tokens=identity_tokens,
                name_tokens=name_tokens,
                required_parameters=frozenset(required),
            )
        )
    return descriptors


def selected_candidate_names(scored: list[tuple[float, ToolDescriptor]], best_score: float) -> list[str]:
    limit = max(1, env_int("JARVIS_LOCAL_ROUTER_MAX_TOOLS", 6))
    floor = max(env_float("JARVIS_LOCAL_ROUTER_LOW_CONFIDENCE", 0.28), best_score * 0.75)
    names = []
    for score, descriptor in scored:
        if score < floor:
            continue
        names.append(descriptor.name)
        if len(names) >= limit:
            break
    return names


def score_descriptor(query_weights: dict[str, float], descriptor: ToolDescriptor) -> float:
    total = sum(query_weights.values())
    if total <= 0:
        return 0.0
    matched = 0.0
    for token, weight in query_weights.items():
        if token in descriptor.identity_tokens:
            matched += weight
        elif related_to_identity(token, descriptor.identity_tokens):
            matched += weight * 0.8
        elif token in descriptor.core_tokens:
            matched += weight * 0.45
        elif token in descriptor.tokens:
            matched += weight * 0.2
        if token in descriptor.name_tokens:
            matched += weight * 0.35
    return matched / total


def related_to_identity(token: str, identity_tokens: frozenset[str]) -> bool:
    if len(token) < 4:
        return False
    for identity_token in identity_tokens:
        if len(identity_token) < 6:
            continue
        if token in identity_token or identity_token in token:
            return True
    return False


def identity_match_weight(query_weights: dict[str, float], descriptor: ToolDescriptor) -> float:
    matched = 0.0
    for token, weight in query_weights.items():
        if token in descriptor.identity_tokens or related_to_identity(token, descriptor.identity_tokens):
            matched += weight
    return matched


def direct_tool_requests_for_decision(decision: RouteDecision, registry: Any, user_text: str = "") -> list[dict[str, Any]]:
    if decision.mode != ROUTE_TOOL_REQUIRED:
        return []
    requests = []
    for name in decision.selected_tool_names:
        descriptor = next((item for item in build_tool_descriptors(registry) if item.name == name), None)
        if descriptor is None:
            continue
        if descriptor.required_parameters:
            query_threshold = env_float("JARVIS_LOCAL_ROUTER_DIRECT_QUERY_CONFIDENCE", 0.35)
            if (
                descriptor.required_parameters == frozenset({"query"})
                and user_text.strip()
                and decision.confidence >= query_threshold
                and not tool_needs_confirmation(descriptor)
            ):
                requests.append({"name": name, "parameters": {"query": user_text.strip()}})
                continue
            continue
        if decision.confidence < env_float("JARVIS_LOCAL_ROUTER_DIRECT_EXEC_CONFIDENCE", 0.65):
            continue
        if tool_needs_confirmation(descriptor):
            continue
        requests.append({"name": name, "parameters": {}})
    return requests[:1]


def tool_needs_confirmation(descriptor: ToolDescriptor) -> bool:
    return descriptor.risk != "read" or descriptor.requires_confirmation


def category_allows_remote_uncertainty(descriptor: ToolDescriptor) -> bool:
    categories = {
        item.strip()
        for item in os.environ.get("JARVIS_REMOTE_UNCERTAIN_TOOL_CATEGORIES", "web").split(",")
        if item.strip()
    }
    return descriptor.category in categories


def required_parameters(parameters: Any) -> list[str]:
    if not isinstance(parameters, dict):
        return []
    required = parameters.get("required")
    if not isinstance(required, list):
        return []
    return [item for item in required if isinstance(item, str) and item.strip()]


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for character in text.lower():
        if character.isalnum():
            current.append(character)
            continue
        if current:
            tokens.extend(token_variants("".join(current)))
            current = []
    if current:
        tokens.extend(token_variants("".join(current)))
    return tokens


def token_variants(token: str) -> list[str]:
    variants = [token]
    if len(token) > 5 and token.endswith("ing"):
        variants.append(token[:-3])
    if len(token) > 4 and token.endswith("ed"):
        variants.append(token[:-2])
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "is", "us")):
        variants.append(token[:-1])
    return variants


def token_weights(tokens: list[str]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for token in tokens:
        if not token:
            continue
        weight = 0.25 if len(token) <= 2 else 1.0
        weights[token] = weights.get(token, 0.0) + weight
    scale = math.sqrt(max(1.0, sum(weights.values())))
    return {token: weight / scale for token, weight in weights.items()}


def env_bool(name: str, fallback: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return fallback
    return value in {"1", "true", "yes", "on"}


def env_float(name: str, fallback: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return float(value)
    except ValueError:
        return fallback


def env_int(name: str, fallback: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback
