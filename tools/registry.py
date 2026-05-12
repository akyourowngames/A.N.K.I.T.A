from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable

from extension_system import ExtensionCatalog, load_extension_catalog


class ToolRegistryError(Exception):
    pass


class ToolExecutorError(ToolRegistryError):
    pass


class ToolInputError(Exception):
    pass


ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    executor: dict[str, Any]
    sort_key: str = ""
    planner_always_include: bool = False

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._disabled_tools: list[dict[str, str]] = []

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ToolRegistryError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def visible_tools(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda tool: (tool.sort_key or tool.name, tool.name))

    def disable_tool(self, name: str, reason: str) -> None:
        self._disabled_tools.append({"name": name, "reason": reason})

    def disabled_tools(self) -> list[dict[str, str]]:
        return list(self._disabled_tools)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self.visible_tools()]

    def planner_tools(self) -> list[dict[str, Any]]:
        return [planner_tool_schema(tool) for tool in self.visible_tools()]

    def execute(self, name: str, arguments: Any) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return tool_payload({"ok": False, "error": f"Tool is not registered: {name}"})

        try:
            params = parse_arguments(arguments)
            result = tool.handler(params)
            return tool_payload({"ok": True, "tool": name, "result": result})
        except ToolInputError as error:
            return tool_payload({"ok": False, "tool": name, "error": str(error)})
        except Exception as error:
            return tool_payload({"ok": False, "tool": name, "error": f"{type(error).__name__}: {error}"})

    def capability_text(self) -> str:
        tools = self.visible_tools()
        if not tools:
            return "Registered local tools: none."

        lines = ["Registered local tools:"]
        for tool in tools:
            lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)


_ACTIVE_REGISTRY: ToolRegistry | None = None


def set_active_registry(registry: ToolRegistry | None) -> None:
    global _ACTIVE_REGISTRY
    _ACTIVE_REGISTRY = registry


def active_registry() -> ToolRegistry | None:
    return _ACTIVE_REGISTRY


def active_or_discovered_registry() -> ToolRegistry:
    registry = active_registry()
    return registry if registry is not None else discover_tools()


def parse_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    return {}


def require_text(params: dict[str, Any], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"{name} is required")
    return value.strip()


def optional_text(params: dict[str, Any], name: str, fallback: str = "") -> str:
    value = params.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def tool_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def discover_tools(
    manifest_path: Path | None = None,
    extension_catalog: ExtensionCatalog | None = None,
) -> ToolRegistry:
    catalog = extension_catalog or load_extension_catalog()
    registry = ToolRegistry()
    path = manifest_path or Path(__file__).with_name("tools.json")
    for descriptor in load_manifest(path):
        registry.register(tool_from_descriptor(descriptor))
    for descriptor in catalog.tool_descriptors():
        try:
            registry.register(tool_from_descriptor(descriptor))
        except ToolExecutorError as error:
            registry.disable_tool(descriptor_name(descriptor), str(error))
    return registry


def load_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ToolRegistryError(f"Tool manifest not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ToolRegistryError(f"Tool manifest is not valid JSON: {path}") from error

    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, list):
        raise ToolRegistryError("Tool manifest must contain a tools list")

    descriptors = []
    for entry in tools:
        if not isinstance(entry, dict):
            raise ToolRegistryError("Tool manifest entries must be objects")
        descriptors.append(entry)
    return descriptors


def tool_from_descriptor(descriptor: dict[str, Any]) -> Tool:
    name = require_manifest_text(descriptor, "name")
    description = require_manifest_text(descriptor, "description")
    parameters = descriptor.get("parameters")
    executor = descriptor.get("executor")
    sort_key = descriptor.get("sort_key", "")
    planner_always_include = bool(descriptor.get("planner_always_include", False))

    if not isinstance(parameters, dict):
        raise ToolRegistryError(f"Tool parameters must be an object: {name}")
    if not isinstance(executor, dict):
        raise ToolRegistryError(f"Tool executor must be an object: {name}")
    if not isinstance(sort_key, str):
        raise ToolRegistryError(f"Tool sort_key must be a string: {name}")

    manifest_root = descriptor_manifest_root(descriptor)
    executor_type = optional_manifest_text(executor, "type", "python").casefold()
    if executor_type == "command":
        handler = command_handler_from_executor(executor, manifest_root, name)
        executor_ref = command_executor_reference(executor)
    else:
        module_name = require_manifest_text(executor, "module")
        function_name = require_manifest_text(executor, "function")
        handler = load_handler(module_name, function_name, name)
        executor_ref = {"type": "python", "module": module_name, "function": function_name}
    return Tool(
        name=name,
        description=description,
        parameters=parameters,
        handler=handler,
        executor=executor_ref,
        sort_key=sort_key,
        planner_always_include=planner_always_include,
    )


def descriptor_manifest_root(descriptor: dict[str, Any]) -> Path:
    raw = descriptor.get("_extension_root")
    if isinstance(raw, str) and raw.strip():
        return Path(raw).resolve()
    return Path.cwd().resolve()


def command_handler_from_executor(executor: dict[str, Any], manifest_root: Path, tool_name: str) -> ToolHandler:
    command = command_argv_from_executor(executor, manifest_root, tool_name)
    cwd = executor_cwd(executor, manifest_root)
    timeout_seconds = executor_int(executor, "timeout_seconds", env_int("JARVIS_COMMAND_TOOL_TIMEOUT_SECONDS", 30), 1, 3600)
    max_output_chars = executor_int(executor, "max_output_chars", env_int("JARVIS_COMMAND_TOOL_MAX_OUTPUT_CHARS", 20000), 100, 200000)
    stdin_mode = optional_manifest_text(executor, "stdin", "json").casefold()
    output_mode = optional_manifest_text(executor, "output", "auto").casefold()
    extra_env = executor_env(executor, manifest_root)

    def run_command_tool(params: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        env = os.environ.copy()
        env.update(extra_env)
        env["JARVIS_TOOL_NAME"] = tool_name
        env["JARVIS_EXTENSION_ROOT"] = str(manifest_root)
        env["JARVIS_WORKSPACE"] = str(Path.cwd().resolve())
        stdin = json.dumps(params, ensure_ascii=False) if stdin_mode == "json" else None
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as error:
            elapsed = round(time.perf_counter() - started, 3)
            raise ToolInputError(
                command_error_message(
                    tool_name,
                    None,
                    text_value(error.stdout),
                    text_value(error.stderr),
                    max_output_chars,
                    elapsed,
                    timed_out=True,
                )
            ) from error

        elapsed = round(time.perf_counter() - started, 3)
        stdout = text_value(completed.stdout)
        stderr = text_value(completed.stderr)
        if completed.returncode != 0:
            raise ToolInputError(
                command_error_message(
                    tool_name,
                    completed.returncode,
                    stdout,
                    stderr,
                    max_output_chars,
                    elapsed,
                    timed_out=False,
                )
            )
        return command_result_payload(tool_name, command, cwd, stdout, stderr, output_mode, max_output_chars, elapsed)

    return run_command_tool


def command_argv_from_executor(executor: dict[str, Any], manifest_root: Path, tool_name: str) -> list[str]:
    command = executor.get("command")
    if isinstance(command, list):
        values = [expand_executor_value(item, manifest_root) for item in command if isinstance(item, str) and item.strip()]
        if values:
            return values
    program = optional_manifest_text(executor, "program", "")
    args = executor.get("args", [])
    if program:
        values = [expand_executor_value(program, manifest_root)]
        if isinstance(args, list):
            values.extend(expand_executor_value(item, manifest_root) for item in args if isinstance(item, str))
        return values
    raise ToolExecutorError(f"Command tool executor needs command or program: {tool_name}")


def executor_cwd(executor: dict[str, Any], manifest_root: Path) -> Path:
    raw = optional_manifest_text(executor, "cwd", "{workspace_root}")
    expanded = expand_executor_value(raw, manifest_root)
    return Path(expanded).resolve()


def executor_env(executor: dict[str, Any], manifest_root: Path) -> dict[str, str]:
    raw = executor.get("env", {})
    env: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, str):
                env[key] = expand_executor_value(value, manifest_root)
    return env


def expand_executor_value(value: str, manifest_root: Path) -> str:
    workspace = str(Path.cwd().resolve())
    extension = str(manifest_root)
    return value.replace("{workspace_root}", workspace).replace("{extension_root}", extension)


def command_result_payload(
    tool_name: str,
    command: list[str],
    cwd: Path,
    stdout: str,
    stderr: str,
    output_mode: str,
    max_output_chars: int,
    elapsed: float,
) -> dict[str, Any]:
    clipped_stdout = clip_text(stdout, max_output_chars)
    clipped_stderr = clip_text(stderr, max_output_chars)
    payload: dict[str, Any] = {
        "tool": tool_name,
        "command": command,
        "cwd": str(cwd),
        "exit_code": 0,
        "elapsed_seconds": elapsed,
        "stdout": clipped_stdout,
        "stderr": clipped_stderr,
        "stdout_truncated": len(stdout) > max_output_chars,
        "stderr_truncated": len(stderr) > max_output_chars,
    }
    if output_mode in {"json", "auto"} and stdout.strip():
        try:
            payload["json"] = json.loads(stdout)
        except json.JSONDecodeError as error:
            if output_mode == "json":
                raise ToolInputError(f"{tool_name} produced invalid JSON output: {error}") from error
    if not payload.get("json"):
        payload["user_output"] = clipped_stdout.strip() or clipped_stderr.strip() or "Done."
    return payload


def command_error_message(
    tool_name: str,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    max_output_chars: int,
    elapsed: float,
    timed_out: bool,
) -> str:
    status = "timed out" if timed_out else f"exited with code {exit_code}"
    parts = [f"{tool_name} command {status} after {elapsed}s."]
    clipped_stdout = clip_text(stdout, max_output_chars).strip()
    clipped_stderr = clip_text(stderr, max_output_chars).strip()
    if clipped_stdout:
        parts.append(f"stdout: {clipped_stdout}")
    if clipped_stderr:
        parts.append(f"stderr: {clipped_stderr}")
    return " ".join(parts)


def command_executor_reference(executor: dict[str, Any]) -> dict[str, Any]:
    reference: dict[str, Any] = {"type": "command"}
    for key in ["command", "program", "args", "cwd", "stdin", "output", "timeout_seconds", "max_output_chars"]:
        if key in executor:
            reference[key] = executor[key]
    return reference


def planner_tool_schema(tool: Tool) -> dict[str, Any]:
    properties = tool.parameters.get("properties")
    required = tool.parameters.get("required")
    compact: dict[str, Any] = {
        "name": tool.name,
        "description": clip_text(tool.description, env_int("TOOL_PLANNER_DESCRIPTION_CHARS", 120)),
        "parameters": {},
    }
    if isinstance(required, list):
        compact["required"] = [item for item in required if isinstance(item, str)]
    if isinstance(properties, dict):
        compact_properties: dict[str, Any] = {}
        for key, value in properties.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            field: dict[str, Any] = {}
            value_type = value.get("type")
            description = value.get("description")
            enum_values = value.get("enum")
            if isinstance(value_type, str):
                field["type"] = value_type
            if env_bool("TOOL_PLANNER_FIELD_DESCRIPTIONS", False) and isinstance(description, str):
                field["description"] = clip_text(description, env_int("TOOL_PLANNER_FIELD_DESCRIPTION_CHARS", 80))
            if isinstance(enum_values, list):
                field["enum"] = enum_values
            compact_properties[key] = field
        compact["parameters"] = compact_properties
    return compact


def env_int(name: str, fallback: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def env_bool(name: str, fallback: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return fallback
    return value in {"1", "true", "yes", "on"}


def clip_text(text: str, limit: int) -> str:
    clean_limit = max(20, limit)
    return text if len(text) <= clean_limit else text[:clean_limit].rstrip()


def require_manifest_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolRegistryError(f"Tool manifest field is required: {key}")
    return value.strip()


def optional_manifest_text(data: dict[str, Any], key: str, fallback: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def executor_int(data: dict[str, Any], key: str, fallback: int, minimum: int, maximum: int) -> int:
    value = data.get(key)
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip():
        try:
            number = int(value.strip())
        except ValueError:
            number = fallback
    else:
        number = fallback
    return max(minimum, min(maximum, number))


def text_value(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def descriptor_name(descriptor: dict[str, Any]) -> str:
    value = descriptor.get("name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unnamed"


def load_handler(module_name: str, function_name: str, tool_name: str) -> ToolHandler:
    module = import_module(module_name)
    function = getattr(module, function_name, None)
    if not callable(function):
        raise ToolExecutorError(f"Tool executor is not callable: {tool_name}")
    return function
