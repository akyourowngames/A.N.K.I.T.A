from __future__ import annotations

from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.capabilities import CapabilitiesTool
from jakata_agent.tools.registry import ToolRegistry
from jakata_agent.tools.search_web import TavilySearchTool
from jakata_agent.tools.screen import OCRTool, ScreenTool
from jakata_agent.tools.weather import OpenWeatherTool


class DemoTool(Tool):
    name = "demo"
    description = "Demo tool."
    input_schema = {"type": "object", "properties": {}, "required": []}
    categories = ("daily_life",)
    use_with = ("memory", "document")
    daily_uses = ("Show metadata in manifests.",)
    grounding = "Test grounding."
    output_capabilities = ("demo_output",)

    def run(self, args: dict) -> ToolResult:
        return ToolResult(ok=True, summary="ok", data=args)


def test_registry_manifest_exposes_synergy_metadata():
    registry = ToolRegistry()
    registry.register(DemoTool())
    item = registry.manifest()[0]
    assert item["categories"] == ["daily_life"]
    assert item["use_with"] == ["memory", "document"]
    assert item["daily_uses"] == ["Show metadata in manifests."]
    assert item["grounding"] == "Test grounding."
    assert item["output_capabilities"] == ["demo_output"]


def test_capabilities_lists_tool_chains():
    registry = ToolRegistry()
    registry.register(DemoTool())
    tool = CapabilitiesTool(registry)
    result = tool.run({})
    assert result.ok
    assert "Good tool chains" in result.summary
    assert "demo + memory, document" in result.summary


def test_daily_grounded_tools_are_public_and_chain_aware():
    assert ScreenTool.public is True
    assert OCRTool.public is True
    assert "ocr" in ScreenTool.use_with
    assert "screen" in OCRTool.use_with
    assert "forecast_days" in OpenWeatherTool.input_schema["properties"]


def test_search_web_scopes_domain_without_double_site():
    assert TavilySearchTool._scoped_query("python docs", "docs.python.org") == "python docs site:docs.python.org"
    assert TavilySearchTool._scoped_query("python docs site:docs.python.org", "python.org") == "python docs site:docs.python.org"
