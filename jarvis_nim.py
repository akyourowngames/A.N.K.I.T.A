from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class NimChatError(Exception):
    pass


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
    if config.auto_tools and registry is not None and registry.visible_tools():
        if config.tool_mode == "hybrid":
            return chat_with_hybrid_tools(config, messages, registry)
        if config.tool_mode == "native":
            return chat_with_native_tools(config, messages, registry)
        if config.tool_mode == "native_stream":
            return chat_with_native_streaming_tools(config, messages, registry)
        return chat_with_json_tools(config, messages, registry)

    return final_chat_response(config, messages)


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
    results, direct_responses = execute_tool_requests(registry, requests)

    if len(results) == 1 and len(direct_responses) == 1:
        reply = "\n".join(direct_responses)
        if config.stream:
            print(reply)
        return reply

    working_messages.append(
        {
            "role": "user",
            "content": tool_results_prompt(
                results,
                latest_user_text(working_messages),
                "\n".join(direct_responses),
            ),
        }
    )
    return final_chat_response(config, working_messages)


def execute_tool_requests(registry: Any, requests: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    results = []
    direct_responses = []
    for request in requests:
        result = registry.execute(request["name"], request["parameters"])
        result_payload = json.loads(result)
        results.append({"name": request["name"], "parameters": request["parameters"], "result": result_payload})
        direct_response = registry.direct_response(request["name"], result_payload)
        if direct_response:
            direct_responses.append(direct_response)
    return results, direct_responses


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
    for index in range(passes):
        planner_messages = tool_planner_messages(messages, registry)
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
        message = extract_choice_message(data)
        content = message_content(message)
        parsed_requests = parse_tool_requests(content, registry)
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
    all_direct_responses: list[str] = []
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

        results, direct_responses = execute_tool_requests(registry, new_requests)
        if (
            not all_results
            and env_bool("NIM_DIRECT_SINGLE_TOOL_RESULT", True)
            and len(results) == 1
            and len(direct_responses) == 1
        ):
            reply = "\n".join(direct_responses)
            if config.stream:
                print(reply)
            return reply
        all_results.extend(results)
        all_direct_responses.extend(direct_responses)
        working_messages.append(
            {
                "role": "user",
                "content": tool_results_prompt(
                    all_results,
                    original_user_message,
                    "\n".join(all_direct_responses),
                ),
            }
        )

    return final_chat_response(config, working_messages)


def chat_with_native_streaming_tools(config: JarvisConfig, messages: list[dict[str, Any]], registry: Any) -> str:
    working_messages = [dict(message) for message in messages]
    requests, streamed_reply = collect_native_stream_tool_decision(config, working_messages, registry)
    if not requests:
        return streamed_reply

    if env_bool("NIM_NATIVE_PLANNER_CONFIRM", True):
        planned_requests = collect_tool_requests(config, working_messages, registry)
        if planned_requests:
            requests = planned_requests

    return answer_with_tool_requests(config, working_messages, registry, requests)


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
) -> tuple[list[dict[str, Any]], str]:
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "stream": True,
        "tools": registry.openai_tools(),
        "tool_choice": "auto",
        "parallel_tool_calls": env_bool("NIM_PARALLEL_TOOL_CALLS", True),
    }
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
        return read_native_tool_stream(response, registry)


def read_native_tool_stream(response: Any, registry: Any) -> tuple[list[dict[str, Any]], str]:
    full_text = ""
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
            print(content, end="", flush=True)
            full_text += content

        merge_tool_call_deltas(tool_calls, delta.get("tool_calls"))

    if full_text:
        print()
    return native_tool_requests_from_deltas(tool_calls, registry), full_text.strip()


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
    visible_names = {tool.name for tool in registry.visible_tools()}
    requests: list[dict[str, Any]] = []
    for index in sorted(tool_calls):
        entry = tool_calls[index]
        name = entry.get("name", "")
        if name not in visible_names:
            continue
        request = {"name": name, "parameters": parse_native_arguments(entry.get("arguments", ""))}
        if request not in requests:
            requests.append(request)
    return requests


def collect_native_tool_decision(
    config: JarvisConfig,
    messages: list[dict[str, Any]],
    registry: Any,
) -> tuple[list[dict[str, Any]], str]:
    tool_schemas = registry.openai_tools()

    data = post_json(
        config,
        {
            "model": config.model,
            "messages": messages,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": False,
            "tools": tool_schemas,
            "tool_choice": "auto",
            "parallel_tool_calls": env_bool("NIM_PARALLEL_TOOL_CALLS", True),
        },
    )
    message = extract_choice_message(data)
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return [], message_content(message)

    requests: list[dict[str, Any]] = []
    visible_names = {tool.name for tool in registry.visible_tools()}
    for tool_call in tool_calls:
        function = tool_call.get("function", {})
        if not isinstance(function, dict):
            continue
        name = str(function.get("name", ""))
        if name not in visible_names:
            continue
        arguments = function.get("arguments", "{}")
        request = {"name": name, "parameters": parse_native_arguments(arguments)}
        if request not in requests:
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
    template = load_text_file(Path(env_value("JARVIS_TOOL_PROTOCOL_FILE", "prompts/tool_protocol.txt")))
    tools = registry.planner_tools() if hasattr(registry, "planner_tools") else registry.openai_tools()
    return template.replace("{tool_schemas}", json.dumps(tools, ensure_ascii=True))


def tool_planner_model(config: JarvisConfig) -> str:
    value = env_value("NVIDIA_TOOL_MODEL")
    return value if value else config.model


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
    return {"name": name, "parameters": parameters}


def tool_results_prompt(
    results: list[dict[str, Any]],
    latest_user_message: str = "",
    display_results: str = "",
) -> str:
    template = load_text_file(Path(env_value("JARVIS_TOOL_RESULTS_PROMPT_FILE", "prompts/tool_results.txt")))
    replacements = {
        "{latest_user_message}": latest_user_message,
        "{tool_results}": json.dumps(results, ensure_ascii=True),
        "{tool_display_results}": display_results,
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def final_chat_response(config: JarvisConfig, messages: list[dict[str, Any]]) -> str:
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
        write_synthetic_stream(config, content)
        return content
    return extract_message(post_json(config, payload))


def post_stream(config: JarvisConfig, payload: dict[str, Any]) -> str:
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
        try:
            return urllib.request.urlopen(request, timeout=config.timeout_seconds)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            last_error = NimChatError(f"NIM request failed: {error.code} {error.reason}\n{detail}")
            if not should_retry_http(error.code) or attempt + 1 >= attempts:
                raise last_error from error
        except urllib.error.URLError as error:
            last_error = NimChatError(f"NIM request failed: {error.reason}")
            if attempt + 1 >= attempts:
                raise last_error from error
        except TimeoutError as error:
            last_error = NimChatError("NIM request timed out.")
            if attempt + 1 >= attempts:
                raise last_error from error

        if config.retry_delay_seconds > 0:
            time.sleep(config.retry_delay_seconds)

    if last_error is not None:
        raise last_error
    raise NimChatError("NIM request failed.")


def should_retry_http(status: int) -> bool:
    return status in {429, 500, 502, 503, 504}


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
