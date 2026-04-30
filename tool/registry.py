from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tool.date_time import DateTimeTool
from tool.system_control import SystemControlTool
from tool.tavily_search import TavilySearchTool
from tool.terminal import TerminalTool
from tool.weather import WeatherTool


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: dict[str, str]


class ToolRegistry:
    def __init__(self) -> None:
        self.date_time = DateTimeTool()
        self.tavily_search = TavilySearchTool()
        self.weather = WeatherTool()
        self.system_control = SystemControlTool()
        self.terminal = TerminalTool()

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="date_time",
                description="Get the current date/time for a timezone.",
                args={"timezone": "Optional IANA timezone. Default: Asia/Kolkata."},
            ),
            ToolSpec(
                name="tavily_search",
                description="Search the live web for current or external information.",
                args={"query": "Search query.", "max_results": "Optional integer, default 5."},
            ),
            ToolSpec(
                name="weather",
                description="Get current weather for a city or location.",
                args={"location": "City or location. Default: Delhi."},
            ),
            ToolSpec(
                name="system_control",
                description="Control Windows settings or apps. If it fails, terminal fallback is used.",
                args={
                    "action": "set_volume, set_brightness, mute, open_bluetooth, open_settings, open_app.",
                    "value": "Optional value, such as 0-100 for volume/brightness.",
                    "target": "Optional settings page or app name.",
                },
            ),
            ToolSpec(
                name="terminal",
                description="Run an unrestricted PowerShell terminal command.",
                args={"command": "PowerShell command.", "cwd": "Optional working directory.", "timeout": "Optional seconds."},
            ),
        ]

    def planner_text(self) -> str:
        lines = []
        for spec in self.specs():
            lines.append(
                json.dumps(
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "args": spec.args,
                    },
                    ensure_ascii=False,
                )
            )
        return "\n".join(lines)

    def run(self, name: str, args: dict[str, Any] | None = None) -> str:
        args = args or {}
        try:
            if name == "date_time":
                timezone = str(args.get("timezone") or "Asia/Kolkata")
                return self.date_time.run(timezone=timezone)
            if name == "tavily_search":
                query = str(args.get("query") or "").strip()
                max_results = int(args.get("max_results") or 5)
                return self.tavily_search.run(query=query, max_results=max_results)
            if name == "weather":
                location = str(args.get("location") or "Delhi")
                return self.weather.run(location=location)
            if name == "system_control":
                action = str(args.get("action") or "")
                value = args.get("value")
                target = str(args.get("target") or "") or None
                result = self.system_control.run(action=action, value=value, target=target)
                if result.startswith("FAILED:") and "FALLBACK_COMMAND:" in result:
                    fallback_command = result.split("FALLBACK_COMMAND:", 1)[1].strip()
                    fallback_result = self.terminal.run(fallback_command)
                    return f"{result}\n\nTerminal fallback result:\n{fallback_result}"
                return result
            if name == "terminal":
                command = str(args.get("command") or "")
                cwd = str(args.get("cwd") or "") or None
                timeout = int(args.get("timeout") or 120)
                return self.terminal.run(command=command, cwd=cwd, timeout=timeout)
        except Exception as error:
            return f"Tool error: {error}"

        return f"Unknown tool: {name}"
