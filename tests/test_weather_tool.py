from __future__ import annotations

import json

from jakata_agent.tools.weather import OpenWeatherTool


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_weather_tool_uses_keyless_open_meteo_when_openweather_key_missing(monkeypatch):
    calls: list[str] = []

    def fake_urlopen(url: str, timeout: int):
        del timeout
        calls.append(url)
        if "geocoding-api.open-meteo.com" in url:
            return FakeResponse({"results": [{"name": "Delhi", "country": "India", "latitude": 28.6, "longitude": 77.2}]})
        return FakeResponse(
            {
                "current": {
                    "temperature_2m": 30,
                    "relative_humidity_2m": 41,
                    "apparent_temperature": 32,
                    "wind_speed_10m": 9,
                }
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = OpenWeatherTool(api_key="").run({"location": "Delhi", "units": "metric"})

    assert result.ok
    assert result.data["source"] == "open_meteo"
    assert "Delhi, India" in result.summary
    assert len(calls) == 2
