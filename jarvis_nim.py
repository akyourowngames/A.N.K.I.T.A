from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from latency_trace import (
    current_trace,
    trace_mark,
    trace_mark_once,
    trace_model_call,
)
from local_router import (
    ROUTE_CONFIRMATION_REQUIRED,
    ROUTE_DIRECT_CHAT,
    ROUTE_TOOL_REQUIRED,
    ROUTE_UNCERTAIN,
    ToolDescriptor,
    direct_tool_requests_for_decision,
    route_chat_turn,
)


class NimChatError(Exception):
    pass


_TOOL_SELECTION_CACHE: dict[tuple[str, str], list[str]] = {}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = clean_env_value(value.strip())
        if key and key not in os.environ:
            os.environ[key] = value


def clean_env_value(value: str) -> str:
    if len(value) >= 2:
        first = value[0]
        last = value[-1]
        if (first == '"' and last == '"') or (first == "'" and last == "'"):
            return value[1:-1]
    return value


def env_value(name: str, fallback: str = "") -> str:
    return os.environ.get(name, fallback).strip()


def required_env(name: str) -> str:
    value = env_value(name)
    if not value:
        raise NimChatError(f"Missing {name}. Add it to .env or your shell environment.")
    return value


def env_float(name: str, fallback: float) -> float:
    value = env_value(name)
    if not value:
        return fallback
    try:
        return float(value)
    except ValueError:
        return fallback


def env_int(name: str, fallback: int) -> int:
    value = env_value(name)
    if not value:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def env_bool(name: str, fallback: bool) -> bool:
    value = env_value(name).lower()
    if not value:
        return fallback
    return value in {"1", "true", "yes", "on"}


def chat_url(base_url: str) -> str:
    clean_base = base_url[:-1] if base_url.endswith("/") else base_url
    if clean_base.endswith("/chat/completions"):
        return clean_base
    return f"{clean_base}/chat/completions"


@dataclass(frozen=True)
class JarvisConfig:
    api_key: str
    chat_url: str
    model: str
    temperature: float
    max_tokens: int
    stream: bool
    stream_mode: str
    synthetic_chunk_chars: int
    synthetic_chunk_delay_seconds: float
    timeout_seconds: int
    retry_attempts: int
    retry_delay_seconds: float
    max_tool_rounds: int
    tool_mode: str
    auto_tools: bool
    system_prompt_file: Path
    persona_file: Path
    tool_protocol_file: Path
    user_name: str
    assistant_name: str

    @classmethod
    def from_env(cls) -> "JarvisConfig":
        return cls(
            api_key=required_env("NVIDIA_API_KEY"),
            chat_url=chat_url(required_env("NVIDIA_BASE_URL")),
            model=required_env("NVIDIA_MODEL"),
            temperature=env_float("TEMPERATURE", 0.3),
            max_tokens=env_int("MAX_TOKENS", 600),
            stream=env_bool("NVIDIA_STREAM", True),
            stream_mode=env_value("NIM_STREAM_MODE", "native").lower(),
            synthetic_chunk_chars=env_int("NIM_SYNTHETIC_CHUNK_CHARS", 48),
            synthetic_chunk_delay_seconds=env_float("NIM_SYNTHETIC_CHUNK_DELAY_SECONDS", 0),
            timeout_seconds=env_int("NVIDIA_TIMEOUT_SECONDS", 60),
            retry_attempts=env_int("NIM_RETRY_ATTEMPTS", 2),
            retry_delay_seconds=env_float("NIM_RETRY_DELAY_SECONDS", 1.0),
            max_tool_rounds=env_int("TOOL_MAX_ROUNDS", 3),
            tool_mode=env_value("NIM_TOOL_MODE", "json").lower(),
            auto_tools=env_bool("JARVIS_AUTO_TOOLS", False),
            system_prompt_file=Path(env_value("JARVIS_SYSTEM_PROMPT_FILE", "prompts/chat_system.txt")),
            persona_file=Path(env_value("JARVIS_PERSONA_FILE", "prompts/persona.txt")),
            tool_protocol_file=Path(env_value("JARVIS_TOOL_PROTOCOL_FILE", "prompts/tool_protocol.txt")),
            user_name=env_value("USER_NAME", "User"),
            assistant_name=env_value("AI_NAME", "Jarvis"),
        )

    def system_message(self, capability_text: str = "") -> dict[str, str]:
        content = load_text_file(self.system_prompt_file)
        persona_text = load_optional_text_file(self.persona_file)
        replacements = {
            "{assistant_name}": self.assistant_name,
            "{user_name}": self.user_name,
            "{capability_text}": capability_text,
            "{persona_text}": persona_text,
        }
        for marker, value in replacements.items():
            content = content.replace(marker, value)
        return {
            "role": "system",
            "content": content.strip(),
        }


def chat_once(config: JarvisConfig, messages: list[dict[str, Any]], registry: Any | None = None) -> str:
    trace_mark_once("request_received")
    try:
        if config.auto_tools and registry is not None and registry.visible_tools():
            decision = route_chat_turn(latest_user_text(messages), messages, registry)
            trace = current_trace()
            if trace is not None:
                trace.set_route(decision.mode, decision.selected_tool_names)
            if decision.mode == ROUTE_DIRECT_CHAT and env_bool("JARVIS_DIRECT_CHAT_SKIP_TOOLS", True):
                return final_chat_response(config, messages)
            if decision.mode == ROUTE_CONFIRMATION_REQUIRED:
                return confirmation_required_reply(decision.selected_tool_names)
            if decision.mode == ROUTE_TOOL_REQUIRED:
                direct_requests = direct_tool_requests_for_decision(decision, registry, latest_user_text(messages))
                subset = ToolSubsetRegistry(registry, decision.selected_tool_names, include_always=False)
                if direct_requests:
                    return answer_with_tool_requests(config, [dict(message) for message in messages], subset, direct_requests)
                return chat_with_json_tools(config, messages, subset)
            if decision.mode == ROUTE_UNCERTAIN and not decision.allow_remote_selector:
                return final_chat_response(config, messages)
            return chat_with_configured_tool_mode(config, messages, registry)

        return final_chat_response(config, messages)
    finally:
        trace_mark_once("response_done")


def chat_with_configured_tool_mode(config: JarvisConfig, messages: list[dict[str, Any]], registry: Any) -> str:
    if config.tool_mode == "hybrid":
        return chat_with_hybrid_tools(config, messages, registry)
    if config.tool_mode == "native":
        return chat_with_native_tools(config, messages, registry)
    if config.tool_mode == "native_stream":
        return chat_with_native_streaming_tools(config, messages, registry)
    return chat_with_json_tools(config, messages, registry)


def confirmation_required_reply(tool_names: list[str]) -> str:
    selected = ", ".join(tool_names) if tool_names else "that action"
    return (
        f"{selected} needs explicit approval before I run it because it can affect local or external state. "
        "Tell me to approve the action and I will continue."
    )


def chat_with_json_tools(config: JarvisConfig, messages: list[dict[str, Any]], registry: Any) -> str:
    working_messages = [dict(message) for message in messages]
    requests, model_reply = collect_tool_decision(config, working_messages, registry)
    if not requests:
        if model_reply:
            if config.stream:
                print(model_reply)
            return model_reply
        return final_chat_response(config, working_messages)
    return answer_with_tool_requests(config, working_messages, registry, requests)


def chat_with_hybrid_tools(config: JarvisConfig, messages: list[dict[str, Any]], registry: Any) -> str:
    working_messages = [dict(message) for message in messages]
    requests: list[dict[str, Any]] = []
    for request in collect_native_tool_requests(config, working_messages, registry):
        if request not in requests:
            requests.append(request)
    for request in collect_tool_requests(config, working_messages, registry):
        if request not in requests:
            requests.append(request)
    if not requests:
        return final_chat_response(config, working_messages)
    return answer_with_tool_requests(config, working_messages, registry, requests)


def answer_with_tool_requests(
    config: JarvisConfig,
    working_messages: list[dict[str, Any]],
    registry: Any,
    requests: list[dict[str, Any]],
) -> str:
    trace_mark("tool_execution_started", selected_tools=[request.get("name", "") for request in requests])
    results = execute_tool_requests(registry, requests)
    trace_mark("tool_execution_done")
    direct_answer = grounded_direct_tool_answer(results)
    if direct_answer:
        if config.stream:
            print(direct_answer)
        return direct_answer
    working_messages.append(
        {
            "role": "user",
            "content": tool_results_prompt(
                results,
                latest_user_text(working_messages),
                config.user_name,
            ),
        }
    )
    return final_chat_response(config, working_messages)


def grounded_direct_tool_answer(results: list[dict[str, Any]]) -> str:
    if not env_bool("JARVIS_DETERMINISTIC_WEB_SEARCH_RESULTS", True):
        return ""
    if not results or any(result.get("name") != "web_search" for result in results):
        return ""
    parts: list[str] = []
    for result in results:
        payload = result.get("result")
        if not isinstance(payload, dict) or not payload.get("ok"):
            error = payload.get("error") if isinstance(payload, dict) else ""
            return f"Search did not return usable evidence. {error}".strip()
        search_result = payload.get("result")
        if not isinstance(search_result, dict):
            return "Search did not return usable evidence."
        if not search_result.get("evidence_ok"):
            return "Search did not return enough current evidence to answer safely."
        query = search_result.get("query", "")
        fetched_at = search_result.get("fetched_at_utc", "")
        source_rows = search_result.get("results", [])
        if not isinstance(source_rows, list) or not source_rows:
            return "Search did not return enough current evidence to answer safely."
        heading = "I found current source results"
        if isinstance(query, str) and query.strip():
            heading += f" for {query.strip()}"
        if isinstance(fetched_at, str) and fetched_at.strip():
            heading += f" (fetched {fetched_at.strip()})"
        parts.append(heading + ". I will not infer details beyond these titles without opening the pages:")
        for index, row in enumerate(source_rows[:5], start=1):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "")).strip() or "Untitled result"
            url = str(row.get("url", "")).strip()
            parts.append(f"{index}. {title}" + (f" - {url}" if url else ""))
    if parts:
        parts.append("For a real summary, ask me to open/extract the top sources with the browser controller.")
    return "\n".join(parts).strip()


def execute_tool_requests(registry: Any, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any] | None] = [None for _request in requests]
    batch: list[tuple[int, dict[str, Any]]] = []

    def flush_batch() -> None:
        if not batch:
            return
        max_workers = max(1, min(len(batch), env_int("JARVIS_TOOL_PARALLEL_MAX_WORKERS", 4)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                (index, executor.submit(execute_one_tool_request, registry, request))
                for index, request in batch
            ]
            for index, future in futures:
                results[index] = future.result()
        batch.clear()

    for index, request in enumerate(requests):
        if tool_request_parallel_safe(registry, request):
            batch.append((index, request))
            continue
        flush_batch()
        results[index] = execute_one_tool_request(registry, request)
    flush_batch()
    return [result for result in results if result is not None]


def execute_one_tool_request(registry: Any, request: dict[str, Any]) -> dict[str, Any]:
    result = registry.execute(request["name"], request["parameters"])
    result_payload = json.loads(result)
    return {"name": request["name"], "parameters": request["parameters"], "result": result_payload}


def tool_request_parallel_safe(registry: Any, request: dict[str, Any]) -> bool:
    name = request.get("name")
    if not isinstance(name, str):
        return False
    tool = registry_tool(registry, name)
    if tool is None:
        return False
    return (
        getattr(tool, "risk", "read") == "read"
        and bool(getattr(tool, "parallel_safe", False))
        and not bool(getattr(tool, "requires_confirmation", False))
    )


def registry_tool(registry: Any, name: str) -> Any | None:
    lookup = getattr(registry, "tool", None)
    if callable(lookup):
        return lookup(name)
    base = getattr(registry, "registry", None)
    if base is not None:
        return registry_tool(base, name)
    for tool in registry.visible_tools():
        if getattr(tool, "name", "") == name:
            return tool
    return None


def collect_tool_requests(config: JarvisConfig, messages: list[dict[str, Any]], registry: Any) -> list[dict[str, Any]]:
    requests, _model_reply = collect_tool_decision(config, messages, registry)
    return requests


def collect_tool_decision(
    config: JarvisConfig,
    messages: list[dict[str, Any]],
    registry: Any,
) -> tuple[list[dict[str, Any]], str]:
    requests: list[dict[str, Any]] = []
    model_reply = ""
    passes = max(1, env_int("TOOL_PLANNER_PASSES", 1))
    planner_registry = selected_planner_registry(config, messages, registry)
    direct_response = getattr(planner_registry, "direct_response", "")
    if isinstance(direct_response, str) and direct_response.strip() and can_accept_selector_direct_response(messages):
        return [], direct_response.strip()
    direct_requests = getattr(planner_registry, "direct_requests", [])
    if isinstance(direct_requests, list) and direct_requests:
        return direct_requests, ""
    if not planner_registry.visible_tools() and env_bool("NIM_JSON_SKIP_EMPTY_SELECTION", True):
        fallback_registry = getattr(planner_registry, "registry", planner_registry)
        if fallback_registry is not planner_registry and fallback_registry.visible_tools():
            planner_registry = fallback_registry
        else:
            return [], ""
    for index in range(passes):
        planner_messages = tool_planner_messages(messages, planner_registry)
        trace_mark("planner_started")
        data = post_json(
            config,
            {
                "model": tool_planner_model(config),
                "messages": planner_messages,
                "temperature": 0,
                "max_tokens": env_int("TOOL_PLANNER_MAX_TOKENS", min(config.max_tokens, 256)),
                "stream": False,
            },
        )
        trace_mark("planner_done")
        message = extract_choice_message(data)
        content = message_content(message)
        parsed_requests = parse_tool_requests(content, planner_registry)
        for request in parsed_requests:
            if request not in requests:
                requests.append(request)
        if parsed_requests:
            break
        if env_bool("NIM_JSON_DIRECT_NO_TOOL_RESPONSE", False) and not is_empty_tool_calls_content(content):
            model_reply = content
            break
        if index + 1 >= passes:
            break
    return requests, model_reply


def can_accept_selector_direct_response(messages: list[dict[str, Any]]) -> bool:
    if env_bool("NIM_SELECTOR_DIRECT_RESPONSE_WITH_HISTORY", False):
        return True
    conversational = []
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            conversational.append(role)
    return conversational == ["user"]


def selected_planner_registry(config: JarvisConfig, messages: list[dict[str, Any]], registry: Any) -> Any:
    if not env_bool("TOOL_PLANNER_DYNAMIC_SCHEMAS", True):
        return registry
    tools = registry.visible_tools()
    minimum = env_int("TOOL_PLANNER_DYNAMIC_SCHEMA_MIN_TOOLS", 8)
    if len(tools) < minimum:
        return registry
    names, direct_response, direct_requests = select_planner_tool_decision(config, messages, registry)
    if not names:
        return ToolSubsetRegistry(registry, [], direct_response, direct_requests)
    return ToolSubsetRegistry(registry, names, "", direct_requests, include_always=True)


class ToolSubsetRegistry:
    def __init__(
        self,
        registry: Any,
        names: list[str],
        direct_response: str = "",
        direct_requests: list[dict[str, Any]] | None = None,
        include_always: bool = False,
    ) -> None:
        self.registry = registry
        self.names = set(names)
        self.direct_response = direct_response
        self.direct_requests = direct_requests or []
        self.include_always = include_always

    def visible_tools(self) -> list[Any]:
        return [
            tool
            for tool in self.registry.visible_tools()
            if tool.name in self.names or (self.include_always and getattr(tool, "planner_always_include", False))
        ]

    def tool(self, name: str) -> Any | None:
        if name not in {tool.name for tool in self.visible_tools()}:
            return None
        lookup = getattr(self.registry, "tool", None)
        return lookup(name) if callable(lookup) else registry_tool(self.registry, name)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self.visible_tools()]

    def planner_tools(self) -> list[dict[str, Any]]:
        if hasattr(self.registry, "planner_tools"):
            visible_names = {tool.name for tool in self.visible_tools()}
            return [
                schema
                for schema in self.registry.planner_tools()
                if isinstance(schema, dict) and schema.get("name") in visible_names
            ]
        return self.openai_tools()

    def execute(self, name: str, arguments: Any) -> str:
        return self.registry.execute(name, arguments)

    def capability_text(self) -> str:
        return self.registry.capability_text()

    def tool_skill_context(self) -> str:
        from tools.registry import render_tool_skill_context

        return render_tool_skill_context(self.visible_tools())


def select_planner_tool_names(config: JarvisConfig, messages: list[dict[str, Any]], registry: Any) -> list[str]:
    names, _direct_response, _direct_requests = select_planner_tool_decision(config, messages, registry)
    return names


def select_planner_tool_decision(
    config: JarvisConfig,
    messages: list[dict[str, Any]],
    registry: Any,
) -> tuple[list[str], str, list[dict[str, Any]]]:
    tools = registry.visible_tools()
    available_names = {tool.name for tool in tools}
    cached_names = cached_tool_selection(messages, registry)
    if cached_names is not None:
        return [name for name in cached_names if name in available_names], "", []
    candidates = selector_tool_candidates(registry, tools)
    prompt = tool_selector_prompt(candidates)
    selector_messages = [
        {
            "role": "system",
            "content": prompt,
        },
        {
            "role": "user",
            "content": planner_turn_context(messages),
        },
    ]
    try:
        trace_mark("selector_started")
        data = post_json(
            selector_request_config(config),
            {
                "model": tool_selector_model(config),
                "messages": selector_messages,
                "temperature": 0,
                "max_tokens": env_int("TOOL_PLANNER_SELECTOR_MAX_TOKENS", 160),
                "stream": False,
            },
        )
        trace_mark("selector_done")
    except NimChatError:
        trace_mark("selector_done", fallback=True)
        return fallback_selector_tool_names(registry), "", []

    content = message_content(extract_choice_message(data))
    direct_requests = parse_tool_requests(content, registry)
    names, direct_response = tool_selection_from_selector_content(content, available_names)
    for request in direct_requests:
        name = request.get("name")
        if isinstance(name, str) and name not in names:
            names.append(name)
    limit = env_int("TOOL_PLANNER_SELECTOR_MAX_TOOLS", 12)
    limited_names = names[: max(1, limit)] if names else []
    if limited_names and not direct_requests:
        remember_tool_selection(messages, registry, limited_names)
    return limited_names, (direct_response if not direct_requests else ""), direct_requests


def selector_request_config(config: JarvisConfig) -> JarvisConfig:
    timeout_ms = env_int("JARVIS_SELECTOR_TIMEOUT_MS", 700)
    legacy_seconds = env_value("TOOL_PLANNER_SELECTOR_TIMEOUT_SECONDS")
    if legacy_seconds:
        try:
            timeout_ms = int(float(legacy_seconds) * 1000)
        except ValueError:
            timeout_ms = 700
    clean_timeout = max(0.1, min(timeout_ms / 1000.0, float(config.timeout_seconds)))
    return replace(config, timeout_seconds=clean_timeout, retry_attempts=0)


def cached_tool_selection(messages: list[dict[str, Any]], registry: Any) -> list[str] | None:
    if not env_bool("TOOL_PLANNER_SELECTION_CACHE", True):
        return None
    key = tool_selection_cache_key(messages, registry)
    cached = _TOOL_SELECTION_CACHE.get(key)
    return list(cached) if cached is not None else None


def remember_tool_selection(messages: list[dict[str, Any]], registry: Any, names: list[str]) -> None:
    if not env_bool("TOOL_PLANNER_SELECTION_CACHE", True):
        return
    limit = env_int("TOOL_PLANNER_SELECTION_CACHE_SIZE", 128)
    if len(_TOOL_SELECTION_CACHE) >= max(1, limit):
        first_key = next(iter(_TOOL_SELECTION_CACHE))
        _TOOL_SELECTION_CACHE.pop(first_key, None)
    _TOOL_SELECTION_CACHE[tool_selection_cache_key(messages, registry)] = list(names)


def tool_selection_cache_key(messages: list[dict[str, Any]], registry: Any) -> tuple[str, str]:
    return registry_fingerprint(registry), latest_user_text(messages).strip().casefold()


def registry_fingerprint(registry: Any) -> str:
    parts: list[str] = []
    for tool in registry.visible_tools():
        parts.append(
            "|".join(
                [
                    getattr(tool, "name", ""),
                    getattr(tool, "description", ""),
                    getattr(tool, "category", ""),
                    getattr(tool, "risk", ""),
                ]
            )
        )
    return "\n".join(parts)


def fallback_selector_tool_names(registry: Any) -> list[str]:
    limit = max(1, env_int("TOOL_PLANNER_FALLBACK_MAX_TOOLS", 6))
    safe_tools = [
        tool
        for tool in registry.visible_tools()
        if getattr(tool, "risk", "read") == "read" and not getattr(tool, "requires_confirmation", False)
    ]
    always = [tool.name for tool in safe_tools if getattr(tool, "planner_always_include", False)]
    names = list(always)
    for tool in safe_tools:
        if tool.name not in names:
            names.append(tool.name)
        if len(names) >= limit:
            break
    return names[:limit]


def selector_tool_candidates(registry: Any, tools: list[Any]) -> list[dict[str, Any]]:
    if hasattr(registry, "planner_tools"):
        schemas = registry.planner_tools()
        if isinstance(schemas, list):
            return [schema for schema in schemas if isinstance(schema, dict)]
    return [
        {
            "name": tool.name,
            "description": clip_planner_text(tool.description, env_int("TOOL_PLANNER_SELECTOR_DESCRIPTION_CHARS", 160)),
        }
        for tool in tools
    ]


def tool_names_from_selector_content(content: str, available_names: set[str]) -> list[str]:
    names, _direct_response = tool_selection_from_selector_content(content, available_names)
    return names


def tool_selection_from_selector_content(content: str, available_names: set[str]) -> tuple[list[str], str]:
    text = content.strip()
    values: list[Any] = []
    if text:
        try:
            values.append(json.loads(text))
        except json.JSONDecodeError:
            pass
    values.extend(scan_json_objects(text))

    names: list[str] = []
    direct_response = ""
    for value in values:
        for name in tool_names_from_selector_value(value):
            if name in available_names and name not in names:
                names.append(name)
        if not direct_response and env_bool("NIM_SELECTOR_DIRECT_RESPONSE", True):
            direct_response = direct_response_from_selector_value(value)
    return names, direct_response if not names else ""


def direct_response_from_selector_value(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    tool_names = value.get("tool_names")
    if isinstance(tool_names, list) and tool_names:
        return ""
    response = value.get("direct_response")
    return response.strip() if isinstance(response, str) and response.strip() else ""


def tool_names_from_selector_value(value: Any) -> list[str]:
    if isinstance(value, dict):
        tool_names = value.get("tool_names")
        if isinstance(tool_names, list):
            return [item for item in tool_names if isinstance(item, str)]
        name = value.get("name")
        if isinstance(name, str):
            return [name]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def tool_selector_prompt(candidates: list[dict[str, str]]) -> str:
    template = load_text_file(Path(env_value("JARVIS_TOOL_SELECTOR_PROMPT_FILE", "prompts/tool_selector.txt")))
    return template.replace("{tool_candidates}", json.dumps(candidates, ensure_ascii=True, separators=(",", ":")))


def clip_planner_text(text: str, limit: int) -> str:
    clean_limit = max(20, limit)
    return text if len(text) <= clean_limit else text[:clean_limit].rstrip()


def is_empty_tool_calls_content(content: str) -> bool:
    text = content.strip()
    if not text:
        return True
    for value in scan_json_objects(text):
        if is_empty_tool_call_response(value):
            return True
    try:
        return is_empty_tool_call_response(json.loads(text))
    except json.JSONDecodeError:
        return False


def chat_with_native_tools(config: JarvisConfig, messages: list[dict[str, Any]], registry: Any) -> str:
    working_messages = [dict(message) for message in messages]
    original_user_message = latest_user_text(working_messages)
    all_results: list[dict[str, Any]] = []
    seen_requests: set[str] = set()

    for _round_index in range(max(1, config.max_tool_rounds)):
        requests, model_reply = collect_native_tool_decision(config, working_messages, registry)
        if not requests:
            if model_reply:
                if config.stream:
                    print(model_reply)
                return model_reply
            break
        if not all_results:
            requests = confirm_native_tool_requests(config, working_messages, registry, requests)

        new_requests = []
        for request in requests:
            key = json.dumps(request, sort_keys=True, ensure_ascii=True)
            if key in seen_requests:
                continue
            seen_requests.add(key)
            new_requests.append(request)
        if not new_requests:
            break

        results = execute_tool_requests(registry, new_requests)
        all_results.extend(results)
        working_messages.append(
            {
                "role": "user",
                "content": tool_results_prompt(
                    all_results,
                    original_user_message,
                    config.user_name,
                ),
            }
        )

    return final_chat_response(config, working_messages)


def chat_with_native_streaming_tools(config: JarvisConfig, messages: list[dict[str, Any]], registry: Any) -> str:
    working_messages = [dict(message) for message in messages]
    verify_no_tool = env_bool("NIM_NATIVE_VERIFY_NO_TOOL", False)
    emit_no_tool_reply = config.stream and not verify_no_tool
    requests, streamed_reply = collect_native_stream_tool_decision(
        config,
        working_messages,
        registry,
        emit_output=emit_no_tool_reply,
    )
    if not requests:
        if verify_no_tool:
            planned_requests = collect_tool_requests(config, working_messages, registry)
            if planned_requests:
                return answer_with_tool_requests(config, working_messages, registry, planned_requests)
        if not streamed_reply:
            return chat_with_json_tools(config, working_messages, registry)
        if config.stream and not emit_no_tool_reply:
            print(streamed_reply)
        return streamed_reply

    if env_bool("NIM_NATIVE_PLANNER_CONFIRM", True):
        planned_requests = collect_tool_requests(config, working_messages, registry)
        if planned_requests:
            requests = merge_confirmed_native_requests(requests, planned_requests)

    return answer_with_tool_requests(config, working_messages, registry, requests)


def merge_confirmed_native_requests(
    native_requests: list[dict[str, Any]],
    planned_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    planned_by_name = {request.get("name"): request for request in planned_requests if isinstance(request.get("name"), str)}
    merged = []
    merged_names: set[str] = set()
    for request in native_requests:
        name = request.get("name")
        replacement = planned_by_name.get(name)
        selected = replacement if replacement is not None else request
        merged.append(selected)
        if isinstance(selected.get("name"), str):
            merged_names.add(selected["name"])
    for request in planned_requests:
        name = request.get("name")
        if isinstance(name, str) and name not in merged_names:
            merged.append(request)
            merged_names.add(name)
    return merged


def confirm_native_tool_requests(
    config: JarvisConfig,
    messages: list[dict[str, Any]],
    registry: Any,
    native_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not env_bool("NIM_NATIVE_PLANNER_CONFIRM", True):
        return native_requests
    planned_requests = collect_tool_requests(config, messages, registry)
    return planned_requests if planned_requests else native_requests


def collect_native_tool_requests(config: JarvisConfig, messages: list[dict[str, Any]], registry: Any) -> list[dict[str, Any]]:
    requests, _model_reply = collect_native_tool_decision(config, messages, registry)
    return requests


def collect_native_stream_tool_decision(
    config: JarvisConfig,
    messages: list[dict[str, Any]],
    registry: Any,
    emit_output: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    selected_registry = selected_planner_registry(config, messages, registry)
    direct_response = getattr(selected_registry, "direct_response", "")
    if isinstance(direct_response, str) and direct_response.strip() and can_accept_selector_direct_response(messages):
        return [], direct_response.strip()
    direct_requests = getattr(selected_registry, "direct_requests", [])
    if isinstance(direct_requests, list) and direct_requests:
        return direct_requests, ""
    trace_mark("planner_started")
    payload = {
        "model": config.model,
        "messages": messages_with_tool_skill_context(messages, selected_registry),
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "stream": True,
        "tools": selected_registry.openai_tools(),
        "tool_choice": "auto",
        "parallel_tool_calls": env_bool("NIM_PARALLEL_TOOL_CALLS", True),
    }
    trace_mark_once("first_model_request_started")
    trace_model_call()
    request = urllib.request.Request(
        config.chat_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    with open_url_with_retries(config, request) as response:
        result = read_native_tool_stream(response, selected_registry, emit_output=emit_output)
    trace_mark("planner_done")
    return result


def read_native_tool_stream(response: Any, registry: Any, emit_output: bool = True) -> tuple[list[dict[str, Any]], str]:
    full_text = ""
    pending_text = ""
    streaming_plain_text = False
    tool_calls: dict[int, dict[str, str]] = {}
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue

        data_line = line[len("data:") :].strip()
        if data_line == "[DONE]":
            break

        data = json.loads(data_line)
        choices = data.get("choices", [])
        if not isinstance(choices, list) or not choices:
            continue
        first = choices[0]
        if not isinstance(first, dict):
            continue
        delta = first.get("delta", {})
        if not isinstance(delta, dict):
            continue

        content = delta.get("content")
        if isinstance(content, str) and content:
            full_text += content
            if emit_output:
                if streaming_plain_text:
                    print(content, end="", flush=True)
                else:
                    pending_text += content
                    if should_hold_pending_content(pending_text):
                        continue
                    print(pending_text, end="", flush=True)
                    pending_text = ""
                    streaming_plain_text = True

        merge_tool_call_deltas(tool_calls, delta.get("tool_calls"))

    native_requests = native_tool_requests_from_deltas(tool_calls, registry)
    if native_requests:
        return native_requests, ""
    if full_text:
        requests = parse_tool_requests(full_text, registry)
        if requests:
            return requests, ""
        if is_json_shaped_text(full_text):
            return [], ""
        if emit_output:
            if pending_text:
                print(pending_text, end="", flush=True)
            if streaming_plain_text or pending_text:
                print()
    return [], full_text.strip()


def should_hold_pending_content(text: str) -> bool:
    stripped = text.lstrip()
    return not stripped or stripped[0] in "{["


def is_json_shaped_text(text: str) -> bool:
    stripped = text.lstrip()
    return bool(stripped) and stripped[0] in "{["


def merge_tool_call_deltas(tool_calls: dict[int, dict[str, str]], deltas: Any) -> None:
    if not isinstance(deltas, list):
        return
    for entry in deltas:
        if not isinstance(entry, dict):
            continue
        index_value = entry.get("index", 0)
        index = index_value if isinstance(index_value, int) else 0
        current = tool_calls.setdefault(index, {"name": "", "arguments": ""})
        function = entry.get("function", {})
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        arguments = function.get("arguments")
        if isinstance(name, str) and name:
            current["name"] += name
        if isinstance(arguments, str) and arguments:
            current["arguments"] += arguments


def native_tool_requests_from_deltas(tool_calls: dict[int, dict[str, str]], registry: Any) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for index in sorted(tool_calls):
        entry = tool_calls[index]
        name = entry.get("name", "")
        request = normalize_tool_request({"name": name, "parameters": parse_native_arguments(entry.get("arguments", ""))}, registry)
        if request is not None and request not in requests:
            requests.append(request)
    return requests


def collect_native_tool_decision(
    config: JarvisConfig,
    messages: list[dict[str, Any]],
    registry: Any,
) -> tuple[list[dict[str, Any]], str]:
    selected_registry = selected_planner_registry(config, messages, registry)
    direct_response = getattr(selected_registry, "direct_response", "")
    if isinstance(direct_response, str) and direct_response.strip() and can_accept_selector_direct_response(messages):
        return [], direct_response.strip()
    direct_requests = getattr(selected_registry, "direct_requests", [])
    if isinstance(direct_requests, list) and direct_requests:
        return direct_requests, ""
    tool_schemas = selected_registry.openai_tools()

    trace_mark("planner_started")
    data = post_json(
        config,
        {
            "model": config.model,
            "messages": messages_with_tool_skill_context(messages, selected_registry),
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": False,
            "tools": tool_schemas,
            "tool_choice": "auto",
            "parallel_tool_calls": env_bool("NIM_PARALLEL_TOOL_CALLS", True),
        },
    )
    trace_mark("planner_done")
    message = extract_choice_message(data)
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return [], message_content(message)

    requests: list[dict[str, Any]] = []
    visible_names = {tool.name for tool in selected_registry.visible_tools()}
    for tool_call in tool_calls:
        function = tool_call.get("function", {})
        if not isinstance(function, dict):
            continue
        name = str(function.get("name", ""))
        if name not in visible_names:
            continue
        arguments = function.get("arguments", "{}")
        request = normalize_tool_request({"name": name, "parameters": parse_native_arguments(arguments)}, selected_registry)
        if request is not None and request not in requests:
            requests.append(request)
    return requests, message_content(message)


def parse_native_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str) and arguments.strip():
        try:
            data = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        if isinstance(data, dict):
            return data
    return {}


def json_tool_protocol(registry: Any) -> str:
    tools = registry.planner_tools() if hasattr(registry, "planner_tools") else registry.openai_tools()
    if isinstance(registry, ToolSubsetRegistry) and env_bool("JARVIS_COMPACT_SELECTED_TOOL_PROTOCOL", True):
        return compact_tool_protocol(tools, registry_tool_skill_context(registry))
    template = load_text_file(Path(env_value("JARVIS_TOOL_PROTOCOL_FILE", "prompts/tool_protocol.txt")))
    protocol = template.replace("{tool_schemas}", json.dumps(tools, ensure_ascii=True, separators=(",", ":")))
    skill_context = registry_tool_skill_context(registry)
    if skill_context:
        return protocol.rstrip() + "\n\n" + skill_context
    return protocol


def compact_tool_protocol(tools: list[dict[str, Any]], skill_context: str) -> str:
    parts = [
        "Local tool planner.",
        "Return JSON only; do not answer in prose.",
        'Use {"tool_calls":[]} when none of these selected tools are needed.',
        'Use {"name":"tool_name","parameters":{}} or {"tool_calls":[{"name":"tool_name","parameters":{}}]} when a selected tool is needed.',
        "Use exact user-provided parameter values. Do not invent placeholders.",
        "Selected tool schemas:",
        json.dumps(tools, ensure_ascii=True, separators=(",", ":")),
    ]
    if skill_context:
        parts.append(skill_context)
    return "\n".join(parts)


def messages_with_tool_skill_context(messages: list[dict[str, Any]], registry: Any) -> list[dict[str, Any]]:
    skill_context = registry_tool_skill_context(registry)
    if not skill_context:
        return messages
    return [
        *messages,
        {
            "role": "system",
            "content": skill_context,
        },
    ]


def registry_tool_skill_context(registry: Any) -> str:
    tool_skill_context = getattr(registry, "tool_skill_context", None)
    if callable(tool_skill_context):
        return tool_skill_context()
    return ""


def tool_planner_model(config: JarvisConfig) -> str:
    value = env_value("NVIDIA_TOOL_MODEL")
    return value if value else config.model


def tool_selector_model(config: JarvisConfig) -> str:
    value = env_value("NVIDIA_TOOL_SELECTOR_MODEL")
    return value if value else tool_planner_model(config)


def load_text_file(path: Path) -> str:
    if not path.exists():
        raise NimChatError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8-sig")


def load_optional_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig").strip()


def tool_planner_messages(messages: list[dict[str, Any]], registry: Any) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": json_tool_protocol(registry),
        },
        {
            "role": "user",
            "content": planner_turn_context(messages),
        },
    ]


def planner_turn_context(messages: list[dict[str, Any]]) -> str:
    recent_messages = []
    for message in messages[-8:]:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = message.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        recent_messages.append({"role": role, "content": content[-1200:]})
    return json.dumps(
        {
            "latest_user_message": latest_user_text(messages),
            "recent_messages": recent_messages,
        },
        ensure_ascii=True,
    )


def latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
    return ""


def parse_tool_requests(content: str, registry: Any) -> list[dict[str, Any]]:
    text = content.strip()
    if not text:
        return []

    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        requests = requests_from_json_value(data, registry)
        if requests:
            return requests

    requests = []
    for value in scan_json_objects(text):
        if is_empty_tool_call_response(value):
            return []
        for request in requests_from_json_value(value, registry):
            if request not in requests:
                requests.append(request)
    return requests


def is_empty_tool_call_response(value: Any) -> bool:
    return isinstance(value, dict) and value.get("tool_calls") == []


def requests_from_json_value(data: Any, registry: Any) -> list[dict[str, Any]]:
    requests = []
    if isinstance(data, dict) and isinstance(data.get("tool_calls"), list):
        for entry in data["tool_calls"]:
            request = normalize_tool_request(entry, registry)
            if request is not None:
                requests.append(request)
        return requests

    request = normalize_tool_request(data, registry)
    return [request] if request is not None else []


def scan_json_objects(text: str) -> list[Any]:
    values = []
    starts = []
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            starts.append(index)
            depth += 1
            continue
        if char == "}" and depth > 0:
            depth -= 1
            if starts:
                start = starts.pop()
                candidate = text[start : index + 1]
                try:
                    values.append(json.loads(candidate))
                except json.JSONDecodeError:
                    pass

    return values


def normalize_tool_request(value: Any, registry: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    parameters = value.get("parameters", {})
    if not isinstance(name, str):
        return None
    visible_names = {tool.name for tool in registry.visible_tools()}
    if name not in visible_names:
        return None
    if not isinstance(parameters, dict):
        parameters = {}
    if contains_unresolved_placeholder(parameters):
        return None
    return {"name": name, "parameters": parameters}


def contains_unresolved_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        text = value.strip()
        return len(text) >= 2 and text[0] == "<" and text[-1] == ">"
    if isinstance(value, dict):
        return any(contains_unresolved_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_unresolved_placeholder(item) for item in value)
    return False


def tool_results_prompt(
    results: list[dict[str, Any]],
    latest_user_message: str = "",
    user_name: str = "",
) -> str:
    template = load_text_file(Path(env_value("JARVIS_TOOL_RESULTS_PROMPT_FILE", "prompts/tool_results.txt")))
    replacements = {
        "{latest_user_message}": latest_user_message,
        "{tool_results}": json.dumps(public_tool_results(results), ensure_ascii=False),
        "{user_name}": user_name,
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def public_tool_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public_results: list[dict[str, Any]] = []
    for index, entry in enumerate(results, start=1):
        if not isinstance(entry, dict):
            continue
        public_results.append(
            {
                "result_index": index,
                "parameters": entry.get("parameters", {}),
                "result": public_result_payload(entry.get("result", {})),
            }
        )
    return public_results


def public_result_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        public: dict[str, Any] = {}
        for key, value in payload.items():
            if key == "tool":
                continue
            if key == "operation" and payload.get("dry_run") is True:
                public["requested_action"] = public_result_payload(value)
                continue
            if key == "count" and "total_count" in payload:
                public["shown_count"] = public_result_payload(value)
                continue
            public[key] = public_result_payload(value)
        return public
    if isinstance(payload, list):
        return [public_result_payload(item) for item in payload]
    return payload


def final_chat_response(config: JarvisConfig, messages: list[dict[str, Any]]) -> str:
    trace_mark("final_model_started")
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "stream": config.stream and config.stream_mode == "native",
    }
    if config.stream:
        if config.stream_mode == "native":
            return post_stream(config, payload)
        content = extract_message(post_json(config, payload))
        trace_mark_once("first_model_token")
        trace_mark_once("final_first_token")
        write_synthetic_stream(config, content)
        return content
    content = extract_message(post_json(config, payload))
    trace_mark_once("first_model_token")
    trace_mark_once("final_first_token")
    return content


def post_stream(config: JarvisConfig, payload: dict[str, Any]) -> str:
    trace_mark_once("first_model_request_started")
    trace_model_call()
    request = urllib.request.Request(
        config.chat_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    with open_url_with_retries(config, request) as response:
        return read_streaming_response(response)


def write_synthetic_stream(config: JarvisConfig, content: str) -> None:
    chunk_size = max(1, config.synthetic_chunk_chars)
    index = 0
    while index < len(content):
        print(content[index : index + chunk_size], end="", flush=True)
        index += chunk_size
        if config.synthetic_chunk_delay_seconds > 0:
            time.sleep(config.synthetic_chunk_delay_seconds)
    print()


def post_json(config: JarvisConfig, payload: dict[str, Any]) -> dict[str, Any]:
    trace_mark_once("first_model_request_started")
    trace_model_call()
    request = urllib.request.Request(
        config.chat_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    with open_url_with_retries(config, request) as response:
        body = response.read().decode("utf-8")
        data = json.loads(body)
        if isinstance(data, dict):
            return data
        raise NimChatError("NIM returned a non-object response.")


def open_url_with_retries(config: JarvisConfig, request: urllib.request.Request) -> Any:
    attempts = max(1, config.retry_attempts + 1)
    last_error: Exception | None = None

    for attempt in range(attempts):
        sleep_seconds = config.retry_delay_seconds
        try:
            return urllib.request.urlopen(request, timeout=config.timeout_seconds)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            last_error = NimChatError(f"NIM request failed: {error.code} {error.reason}\n{detail}")
            if not should_retry_http(error.code) or attempt + 1 >= attempts:
                raise last_error from error
            sleep_seconds = retry_delay_seconds(error, config.retry_delay_seconds, attempt)
        except urllib.error.URLError as error:
            last_error = NimChatError(f"NIM request failed: {error.reason}")
            if attempt + 1 >= attempts:
                raise last_error from error
        except TimeoutError as error:
            last_error = NimChatError("NIM request timed out.")
            if attempt + 1 >= attempts:
                raise last_error from error

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    if last_error is not None:
        raise last_error
    raise NimChatError("NIM request failed.")


def should_retry_http(status: int) -> bool:
    return status in {429, 500, 502, 503, 504}


def retry_delay_seconds(error: urllib.error.HTTPError, fallback_seconds: float, attempt: int) -> float:
    retry_after = error.headers.get("Retry-After") if error.headers else ""
    try:
        parsed = float(retry_after)
    except (TypeError, ValueError):
        parsed = 0.0
    if parsed > 0:
        return parsed
    return max(0.0, fallback_seconds * (attempt + 1))


def stream_token(data: dict[str, Any]) -> str:
    choices = data.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta", {})
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content", "")
    return content if isinstance(content, str) else ""


def read_streaming_response(response: Any) -> str:
    full_text = ""
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue

        data_line = line[len("data:") :].strip()
        if data_line == "[DONE]":
            break

        data = json.loads(data_line)
        token = stream_token(data)
        if token:
            trace_mark_once("first_model_token")
            trace_mark_once("final_first_token")
            print(token, end="", flush=True)
            full_text += token

    print()
    return full_text.strip()


def extract_message(data: dict[str, Any]) -> str:
    return message_content(extract_choice_message(data))


def extract_choice_message(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices", [])
    if not choices:
        return {}

    message = choices[0].get("message", {})
    if isinstance(message, dict):
        return message
    return {}


def message_content(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    return ""
