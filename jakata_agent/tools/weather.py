from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from jakata_agent.tools.base import Tool, ToolResult


class OpenWeatherTool(Tool):
    name = "weather"
    description = "Get the current weather for a city using OpenWeather."
    input_schema = {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City name, optionally with country code."},
            "units": {"type": "string", "enum": ["metric", "imperial", "standard"]},
        },
        "required": ["location"],
        "additionalProperties": False,
    }

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def run(self, args: dict[str, Any]) -> ToolResult:
        if not self.api_key:
            return ToolResult(ok=False, summary="OpenWeather API key is missing.", data={}, error="missing_api_key")

        query = urllib.parse.urlencode(
            {
                "q": str(args["location"]),
                "appid": self.api_key,
                "units": str(args.get("units", "metric")),
            }
        )
        url = f"https://api.openweathermap.org/data/2.5/weather?{query}"
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Weather lookup failed.", data={}, error=str(exc))

        weather = (data.get("weather") or [{}])[0]
        main = data.get("main", {})
        wind = data.get("wind", {})
        summary = (
            f"{data.get('name', args['location'])}: {weather.get('description', 'unknown weather')}, "
            f"{main.get('temp', '?')} degrees, humidity {main.get('humidity', '?')}%."
        )
        return ToolResult(
            ok=True,
            summary=summary,
            data={
                "location": data.get("name", args["location"]),
                "description": weather.get("description", ""),
                "temperature": main.get("temp"),
                "feels_like": main.get("feels_like"),
                "humidity": main.get("humidity"),
                "wind_speed": wind.get("speed"),
            },
        )

