from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .registry import ToolInputError, optional_text, require_text


def get_weather(params: dict[str, Any]) -> dict[str, Any]:
    location = require_text(params, "location")
    units = optional_text(params, "units", os.environ.get("WEATHER_UNITS", "metric")).lower()
    timeout = weather_timeout()

    geocoding = fetch_json(
        os.environ.get("WEATHER_GEOCODING_BASE_URL", "https://geocoding-api.open-meteo.com/v1/search"),
        {
            "name": location,
            "count": 1,
            "language": "en",
            "format": "json",
        },
        timeout,
    )
    results = geocoding.get("results", [])
    if not isinstance(results, list) or not results:
        raise ToolInputError(f"weather location not found: {location}")

    selected = results[0]
    latitude = selected.get("latitude")
    longitude = selected.get("longitude")
    if not isinstance(latitude, int | float) or not isinstance(longitude, int | float):
        raise ToolInputError(f"weather location has no coordinates: {location}")

    forecast_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "auto",
    }
    if units == "imperial":
        forecast_params["temperature_unit"] = "fahrenheit"
        forecast_params["wind_speed_unit"] = "mph"
        forecast_params["precipitation_unit"] = "inch"

    forecast = fetch_json(
        os.environ.get("WEATHER_FORECAST_BASE_URL", "https://api.open-meteo.com/v1/forecast"),
        forecast_params,
        timeout,
    )

    return {
        "requested_location": location,
        "resolved_location": {
            "name": selected.get("name"),
            "admin1": selected.get("admin1"),
            "country": selected.get("country"),
            "latitude": latitude,
            "longitude": longitude,
            "timezone": selected.get("timezone"),
        },
        "current": forecast.get("current", {}),
        "current_units": forecast.get("current_units", {}),
        "daily": forecast.get("daily", {}),
        "daily_units": forecast.get("daily_units", {}),
    }


def weather_timeout() -> int:
    raw = os.environ.get("WEATHER_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 20
    try:
        return int(raw)
    except ValueError:
        return 20


def fetch_json(base_url: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    url = f"{base_url}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, dict):
                return data
            raise ToolInputError("weather service returned a non-object response")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ToolInputError(f"weather service failed: {error.code} {error.reason} {detail}") from error
    except urllib.error.URLError as error:
        raise ToolInputError(f"weather service failed: {error.reason}") from error
    except TimeoutError as error:
        raise ToolInputError("weather service timed out") from error
