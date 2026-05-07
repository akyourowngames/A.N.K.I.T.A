from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable


class ToolRegistryError(Exception):
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
    executor: dict[str, str]
    sort_key: str = ""
    direct_response: str = ""

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

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ToolRegistryError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def visible_tools(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda tool: (tool.sort_key or tool.name, tool.name))

    def openai_tools(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self.visible_tools()]

    def direct_response(self, name: str, payload: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None or not tool.direct_response:
            return ""
        if payload.get("ok") is False:
            return ""
        return render_template(tool.direct_response, flatten_payload(payload))

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
    return json.dumps(payload, ensure_ascii=True)


def discover_tools(manifest_path: Path | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    path = manifest_path or Path(__file__).with_name("tools.json")
    for descriptor in load_manifest(path):
        registry.register(tool_from_descriptor(descriptor))
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
    direct_response = descriptor.get("direct_response", "")

    if not isinstance(parameters, dict):
        raise ToolRegistryError(f"Tool parameters must be an object: {name}")
    if not isinstance(executor, dict):
        raise ToolRegistryError(f"Tool executor must be an object: {name}")
    if not isinstance(sort_key, str):
        raise ToolRegistryError(f"Tool sort_key must be a string: {name}")
    if not isinstance(direct_response, str):
        raise ToolRegistryError(f"Tool direct_response must be a string: {name}")

    module_name = require_manifest_text(executor, "module")
    function_name = require_manifest_text(executor, "function")
    handler = load_handler(module_name, function_name, name)
    return Tool(
        name=name,
        description=description,
        parameters=parameters,
        handler=handler,
        executor={"module": module_name, "function": function_name},
        sort_key=sort_key,
        direct_response=direct_response,
    )


def require_manifest_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolRegistryError(f"Tool manifest field is required: {key}")
    return value.strip()


def load_handler(module_name: str, function_name: str, tool_name: str) -> ToolHandler:
    module = import_module(module_name)
    function = getattr(module, function_name, None)
    if not callable(function):
        raise ToolRegistryError(f"Tool executor is not callable: {tool_name}")
    return function


def flatten_payload(value: Any, prefix: str = "") -> dict[str, str]:
    if isinstance(value, dict):
        result: dict[str, str] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                continue
            child_prefix = f"{prefix}.{key}" if prefix else key
            result.update(flatten_payload(child, child_prefix))
        return result
    if isinstance(value, list):
        return {prefix: json.dumps(value, ensure_ascii=True)}
    if prefix:
        return {prefix: str(value)}
    return {}


def render_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered
