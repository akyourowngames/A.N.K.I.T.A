from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from jakata_agent.tools.base import Tool, ToolResult


class OpenWeatherTool(Tool):
    name = "weather"
    description = "Get the current weather for a city. Uses OpenWeather when configured and keyless Open-Meteo as fallback."
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
            return self._run_open_meteo(args)

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
                "source": "openweather",
                "description": weather.get("description", ""),
                "temperature": main.get("temp"),
                "feels_like": main.get("feels_like"),
                "humidity": main.get("humidity"),
                "wind_speed": wind.get("speed"),
            },
        )

    def _run_open_meteo(self, args: dict[str, Any]) -> ToolResult:
        location = str(args.get("location", "")).strip()
        if not location:
            return ToolResult(ok=False, summary="Weather location is required.", data={}, error="missing_location")
        try:
            encoded_location = urllib.parse.urlencode({"name": location, "count": 1, "language": "en", "format": "json"})
            with urllib.request.urlopen(f"https://geocoding-api.open-meteo.com/v1/search?{encoded_location}", timeout=20) as response:
                geocode = json.loads(response.read().decode("utf-8"))
            results = list(geocode.get("results") or [])
            if not results:
                return ToolResult(ok=False, summary=f"Weather location not found: {location}", data={}, error="location_not_found")
            place = results[0]
            latitude = place["latitude"]
            longitude = place["longitude"]
            units = str(args.get("units", "metric")).strip().lower() or "metric"
            temperature_unit = "fahrenheit" if units == "imperial" else "celsius"
            wind_speed_unit = "mph" if units == "imperial" else "kmh"
            query = urllib.parse.urlencode(
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code",
                    "temperature_unit": temperature_unit,
                    "wind_speed_unit": wind_speed_unit,
                }
            )
            with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Weather lookup failed.", data={}, error=str(exc))

        current = dict(data.get("current") or {})
        place_name = ", ".join(
            part
            for part in [
                str(place.get("name", "")).strip(),
                str(place.get("admin1", "")).strip(),
                str(place.get("country", "")).strip(),
            ]
            if part
        ) or location
        temperature = current.get("temperature_2m")
        humidity = current.get("relative_humidity_2m")
        feels_like = current.get("apparent_temperature")
        wind_speed = current.get("wind_speed_10m")
        unit = "F" if temperature_unit == "fahrenheit" else "C"
        summary = f"{place_name}: {temperature} degrees {unit}, feels like {feels_like} degrees {unit}, humidity {humidity}%, wind {wind_speed} {wind_speed_unit}."
        return ToolResult(
            ok=True,
            summary=summary,
            data={
                "location": place_name,
                "source": "open_meteo",
                "temperature": temperature,
                "feels_like": feels_like,
                "humidity": humidity,
                "wind_speed": wind_speed,
                "units": units,
                "latitude": latitude,
                "longitude": longitude,
            },
        )

