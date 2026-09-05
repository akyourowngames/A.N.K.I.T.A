import json
from types import SimpleNamespace

import mcpclient.tools as mt


class FakeTool(SimpleNamespace):
    pass


def _tool(name="echo", desc="Echo text", props=None):
    return FakeTool(
        name=name,
        description=desc,
        inputSchema={
            "type": "object",
            "properties": props or {"text": {"type": "string"}},
            "required": ["text"],
        },
    )


def test_qualify_and_split():
    assert mt.qualify("fs", "read") == "fs__read"
    assert mt.split_qualified("fs__read") == ("fs", "read")
    assert mt.split_qualified("no_sep") is None
    assert mt.split_qualified("__leading") is None


def test_mcp_tool_to_openai():
    out = mt.mcp_tool_to_openai("fs", _tool())
    assert out["type"] == "function"
    fn = out["function"]
    assert fn["name"] == "fs__echo"
    assert fn["description"] == "Echo text"
    assert fn["parameters"]["type"] == "object"
    assert "text" in fn["parameters"]["properties"]


def test_mcp_tools_to_openai_multiple_servers():
    tools = mt.mcp_tools_to_openai("web", [_tool("search"), _tool("fetch")])
    names = [t["function"]["name"] for t in tools]
    assert names == ["web__search", "web__fetch"]


def test_system_preamble_lists_tools():
    text = mt.system_preamble(mt.mcp_tools_to_openai("fs", [_tool()]))
    assert "fs__echo" in text
    assert "text: string" in text


def test_system_preamble_empty():
    assert mt.system_preamble([]) == ""


def test_tool_result_text():
    result = SimpleNamespace(content=[SimpleNamespace(text="hello")], isError=False)
    assert mt.tool_result_text(result) == "hello"


def test_tool_result_text_error():
    result = SimpleNamespace(content=[SimpleNamespace(text="boom")], isError=True)
    assert mt.tool_result_text(result) == "ERROR: boom"


def test_tool_result_text_empty():
    result = SimpleNamespace(content=[], isError=False)
    assert mt.tool_result_text(result) == ""
