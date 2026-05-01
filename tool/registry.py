from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

from tool.date_time import DateTimeTool
from tool.gmail import GmailTool
from tool.google_calendar import GoogleCalendarTool
from tool.local_files import LocalFilesTool
from tool.nvidia_image import NvidiaImageTool
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
        self.local_files = LocalFilesTool()
        self.image_generation = NvidiaImageTool()
        self.gmail = GmailTool()
        self.google_calendar = GoogleCalendarTool()
        self._planner_text_cache: str | None = None

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
            ToolSpec(
                name="local_files",
                description="List, search, or read files inside allowed local folders from LOCAL_FILE_ALLOWED_PATHS.",
                args={
                    "action": "roots, list, search, read.",
                    "path": "Optional allowed folder or file path.",
                    "query": "Filename search query for search.",
                    "max_results": "Optional integer, default 20.",
                },
            ),
            ToolSpec(
                name="image_generation",
                description="Generate an image using NVIDIA image models and save it to an allowed output folder.",
                args={
                    "prompt": "Image description.",
                    "output_path": "Optional output file or folder path.",
                    "size": "Optional image size if supported by the configured NVIDIA model.",
                    "n": "Optional image count, default 1, max 4.",
                    "seed": "Optional integer seed if supported by the configured NVIDIA model.",
                    "open_after_save": "Optional boolean; open generated image files after saving.",
                },
            ),
            ToolSpec(
                name="gmail",
                description="Search, read, draft, or send Gmail email messages.",
                args={
                    "action": "search, read, draft, send.",
                    "query": "Gmail search query for search/list.",
                    "message_id": "Message id for read.",
                    "to": "Recipient email for draft/send.",
                    "subject": "Email subject for draft/send.",
                    "body": "Email body for draft/send.",
                    "max_results": "Optional integer, default 5.",
                },
            ),
            ToolSpec(
                name="google_calendar",
                description="List, create, or delete Google Calendar events.",
                args={
                    "action": "list, create, delete.",
                    "calendar_id": "Optional calendar id, default primary.",
                    "query": "Optional search text for list/search.",
                    "summary": "Event title for create.",
                    "start": "ISO datetime for create.",
                    "end": "Optional ISO datetime for create.",
                    "event_id": "Event id for delete.",
                    "max_results": "Optional integer, default 10.",
                },
            ),
        ]

    def planner_text(self) -> str:
        if self._planner_text_cache is not None:
            return self._planner_text_cache
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
        self._planner_text_cache = "\n".join(lines)
        return self._planner_text_cache

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
            if name == "local_files":
                return self.local_files.run(
                    action=str(args.get("action") or "roots"),
                    path=str(args.get("path") or ""),
                    query=str(args.get("query") or ""),
                    max_results=int(args.get("max_results") or 20),
                )
            if name == "image_generation":
                seed_value = args.get("seed")
                seed = int(seed_value) if seed_value not in (None, "") else None
                return self.image_generation.run(
                    prompt=str(args.get("prompt") or ""),
                    output_path=str(args.get("output_path") or ""),
                    size=str(args.get("size") or ""),
                    n=int(args.get("n") or 1),
                    seed=seed,
                    open_after_save=self._optional_bool(args.get("open_after_save")),
                )
            if name == "gmail":
                return self.gmail.run(
                    action=str(args.get("action") or "search"),
                    query=str(args.get("query") or ""),
                    to=str(args.get("to") or ""),
                    subject=str(args.get("subject") or ""),
                    body=str(args.get("body") or ""),
                    message_id=str(args.get("message_id") or ""),
                    max_results=int(args.get("max_results") or 5),
                )
            if name == "google_calendar":
                return self.google_calendar.run(
                    action=str(args.get("action") or "list"),
                    calendar_id=str(args.get("calendar_id") or "primary"),
                    query=str(args.get("query") or ""),
                    summary=str(args.get("summary") or ""),
                    start=str(args.get("start") or ""),
                    end=str(args.get("end") or ""),
                    timezone_name=str(args.get("timezone_name") or "Asia/Kolkata"),
                    location=str(args.get("location") or ""),
                    description=str(args.get("description") or ""),
                    event_id=str(args.get("event_id") or ""),
                    max_results=int(args.get("max_results") or 10),
                )
        except Exception as error:
            return f"Tool error: {error}"

        return f"Unknown tool: {name}"

    def run_stream(self, name: str, args: dict[str, Any] | None = None) -> Iterator[str]:
        args = args or {}
        if name == "image_generation":
            seed_value = args.get("seed")
            seed = int(seed_value) if seed_value not in (None, "") else None
            result = yield from self.image_generation.run_stream(
                prompt=str(args.get("prompt") or ""),
                output_path=str(args.get("output_path") or ""),
                size=str(args.get("size") or ""),
                n=int(args.get("n") or 1),
                seed=seed,
                open_after_save=self._optional_bool(args.get("open_after_save")),
            )
            return result

        yield self.run(name, args)

    @staticmethod
    def _optional_bool(value: Any) -> bool | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
