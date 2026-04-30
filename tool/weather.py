from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WeatherTool:
    name: str = "weather"
    description: str = "Gets current weather for a location using wttr.in JSON."

    def run(self, location: str = "Delhi") -> str:
        location = location.strip() or "Delhi"
        encoded = urllib.parse.quote(location)
        request = urllib.request.Request(
            f"https://wttr.in/{encoded}?format=j1",
            headers={"Accept": "application/json", "User-Agent": "ANKITA-JARVIS/1.0"},
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            return f"FAILED: weather lookup failed: {error}"

        return self._format(data, fallback_location=location)

    @staticmethod
    def _format(data: dict[str, Any], fallback_location: str) -> str:
        current = (data.get("current_condition") or [{}])[0]
        area = (data.get("nearest_area") or [{}])[0]
        weather = (data.get("weather") or [{}])[0]

        place = WeatherTool._value(area.get("areaName")) or fallback_location
        region = WeatherTool._value(area.get("region"))
        country = WeatherTool._value(area.get("country"))
        desc = WeatherTool._value(current.get("weatherDesc")) or "Unknown"

        location_bits = [bit for bit in (place, region, country) if bit]
        display_location = ", ".join(location_bits) or fallback_location
        sunrise = (weather.get("astronomy") or [{}])[0].get("sunrise", "unknown")
        sunset = (weather.get("astronomy") or [{}])[0].get("sunset", "unknown")

        return (
            f"Weather for {display_location}: {desc}, "
            f"{current.get('temp_C', '?')}°C "
            f"(feels like {current.get('FeelsLikeC', '?')}°C), "
            f"humidity {current.get('humidity', '?')}%, "
            f"wind {current.get('windspeedKmph', '?')} km/h, "
            f"UV {current.get('uvIndex', '?')}. "
            f"Sunrise {sunrise}, sunset {sunset}."
        )

    @staticmethod
    def _value(value: Any) -> str:
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return str(value[0].get("value") or "").strip()
        if isinstance(value, str):
            return value.strip()
        return ""
