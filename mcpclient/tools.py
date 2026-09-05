"""Adapters between MCP tools and the OpenAI/Kilo `tools` chat format."""
import json
from typing import Any, Optional

from mcpclient import defaults

SEP = defaults.SEP


def qualify(server: str, tool: str) -> str:
    """Namespaced tool name the model sees: server__tool (MCP spec separator)."""
    return f"{server}{SEP}{tool}"


def split_qualified(name: str) -> Optional[tuple]:
    if SEP not in name:
        return None
    server, tool = name.split(SEP, 1)
    return (server, tool) if server and tool else None


def _openai_type(json_schema_type: Any) -> str:
    mapping = {"str": "string", "int": "integer", "float": "number", "bool": "boolean",
               "string": "string", "integer": "integer", "number": "number", "boolean": "boolean"}
    return mapping.get(str(json_schema_type), "string")


def mcp_tool_to_openai(server: str, tool: Any) -> dict:
    """Convert an MCP Tool (has .name, .description, .inputSchema) to OpenAI format."""
    name = getattr(tool, "name", None) or (tool.get("name") if isinstance(tool, dict) else "")
    desc = getattr(tool, "description", None) or (tool.get("description") if isinstance(tool, dict) else "") or ""
    schema = getattr(tool, "inputSchema", None)
    if schema is None and isinstance(tool, dict):
        schema = tool.get("inputSchema")
    schema = dict(schema) if isinstance(schema, dict) else {"type": "object", "properties": {}}
    schema.setdefault("type", "object")
    return {
        "type": "function",
        "function": {
            "name": qualify(server, name),
            "description": str(desc).strip() or f"Tool {name} from MCP server {server}",
            "parameters": schema,
        },
    }


def mcp_tools_to_openai(server: str, tools: list) -> list:
    return [mcp_tool_to_openai(server, t) for t in tools]


def system_preamble(tools: list) -> str:
    """Fallback description of available tools for models without function calling."""
    if not tools:
        return ""
    lines = ["You can use these connected MCP tools by name when helpful. Call them using the standard function/tool-call mechanism. "
             "GROUNDING RULE: only ever claim a server/tool is connected if it appears in the latest zumba__mcp_list result. "
             "Registry search results are candidates, NOT connected servers. If unsure, call zumba__mcp_list first and quote it verbatim:"]
    for t in tools:
        fn = t.get("function", {})
        args = ", ".join(
            f"{k}: {_openai_type(v.get('type', 'string')) if isinstance(v, dict) else 'string'}"
            for k, v in (fn.get("parameters", {}).get("properties", {}) or {}).items()
        )
        sig = f"{fn.get('name')}({args})"
        d = " ".join(str(fn.get("description", "")).split())[:200]
        lines.append(f"- {sig} — {d}")
    return "\n".join(lines)


def tool_result_text(result: Any) -> str:
    """Flatten an MCP CallToolResult into plain text for the model."""
    parts = []
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content")
    for item in content or []:
        text = getattr(item, "text", None)
        if text is None and isinstance(item, dict):
            text = item.get("text")
        if text is None and isinstance(item, dict):
            text = json.dumps(item, ensure_ascii=False)
        if text:
            parts.append(str(text))
    if getattr(result, "isError", False):
        joined = "\n".join(parts) or "Tool reported an error."
        return f"ERROR: {joined}"
    return "\n".join(parts) or ""
