from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WeatherTool:
    name: str = "weather"
    description: str = "Gets current weather, forecast, hourly outlook, and risk advisories for a location."
    endpoint: str = "https://wttr.in"
    default_location: str = "Delhi"

    def run(
        self,
        location: str = "",
        mode: str = "current",
        days: Any = 1,
        units: str = "metric",
        include_hourly: bool | None = None,
        hourly_slots: Any = 4,
    ) -> str:
        location = location.strip() or self.default_location
        encoded = urllib.parse.quote(location, safe="")
        request = urllib.request.Request(
            f"{self.endpoint.rstrip('/')}/{encoded}?format=j1",
            headers={"Accept": "application/json", "User-Agent": "ANKITA-JARVIS/1.0"},
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            return f"FAILED: weather lookup failed: {error}"

        return self._format(
            data,
            fallback_location=location,
            mode=mode,
            days=days,
            units=units,
            include_hourly=include_hourly,
            hourly_slots=hourly_slots,
        )

    @staticmethod
    def _format(
        data: dict[str, Any],
        fallback_location: str,
        mode: str = "current",
        days: Any = 1,
        units: str = "metric",
        include_hourly: bool | None = None,
        hourly_slots: Any = 4,
    ) -> str:
        mode = WeatherTool._mode(mode)
        units = WeatherTool._units(units)
        days = WeatherTool._clamp_int(days, default=1, minimum=1, maximum=3)
        hourly_slots = WeatherTool._clamp_int(hourly_slots, default=4, minimum=1, maximum=8)
        if include_hourly is None:
            include_hourly = mode in {"hourly", "full"}

        current = WeatherTool._first_dict(data.get("current_condition"))
        area = WeatherTool._first_dict(data.get("nearest_area"))
        weather_days = WeatherTool._weather_days(data)

        lines = [WeatherTool._current_line(current, area, fallback_location, units)]
        advisories = WeatherTool._advisories(current, weather_days[:days])
        if advisories:
            lines.append("Advisories: " + "; ".join(advisories) + ".")

        if mode in {"forecast", "full"}:
            lines.append(WeatherTool._forecast_section(weather_days[:days], units))

        if include_hourly:
            lines.append(WeatherTool._hourly_section(weather_days[:days], units, hourly_slots))

        return "\n".join(lines)

    @staticmethod
    def _current_line(current: dict[str, Any], area: dict[str, Any], fallback_location: str, units: str) -> str:
        display_location = WeatherTool._display_location(area, fallback_location)
        desc = WeatherTool._description(current)
        temp = WeatherTool._current_temperature(current, units)
        feels_like = WeatherTool._current_feels_like(current, units)
        wind = WeatherTool._wind(current, units)
        humidity = WeatherTool._percent(current.get("humidity"))
        uv = WeatherTool._text(current.get("uvIndex"), "unknown")
        visibility = WeatherTool._visibility(current, units)
        precip = WeatherTool._precip(current, units)
        pressure = WeatherTool._text(current.get("pressure"), "")

        parts = [
            desc,
            f"{temp} (feels like {feels_like})",
            f"humidity {humidity}",
            f"wind {wind}",
            f"UV {uv}",
        ]
        if precip:
            parts.append(f"precip {precip}")
        if visibility:
            parts.append(f"visibility {visibility}")
        if pressure:
            parts.append(f"pressure {pressure} mb")

        return f"Weather for {display_location}: " + ", ".join(parts) + "."

    @staticmethod
    def _forecast_section(weather_days: list[dict[str, Any]], units: str) -> str:
        if not weather_days:
            return "Forecast: no daily forecast data returned."

        lines = ["Forecast:"]
        for day in weather_days:
            date = WeatherTool._text(day.get("date"), "today")
            condition = WeatherTool._daily_condition(day)
            high = WeatherTool._temperature(day.get(WeatherTool._daily_high_key(units)), units)
            low = WeatherTool._temperature(day.get(WeatherTool._daily_low_key(units)), units)
            rain = WeatherTool._max_chance(day, "chanceofrain")
            storm = WeatherTool._max_chance(day, "chanceofthunder")
            snow = WeatherTool._max_chance(day, "chanceofsnow")
            uv = WeatherTool._text(day.get("uvIndex"), "unknown")
            astronomy = WeatherTool._astronomy(day)
            sunrise = WeatherTool._text(astronomy.get("sunrise"), "unknown")
            sunset = WeatherTool._text(astronomy.get("sunset"), "unknown")
            chances = WeatherTool._chance_text({"rain": rain, "storm": storm, "snow": snow})

            lines.append(
                f"- {date}: {condition}; high {high}, low {low}; "
                f"{chances}; UV {uv}; sunrise {sunrise}, sunset {sunset}."
            )

        return "\n".join(lines)

    @staticmethod
    def _hourly_section(weather_days: list[dict[str, Any]], units: str, hourly_slots: int) -> str:
        rows: list[str] = []
        for day in weather_days:
            date = WeatherTool._text(day.get("date"), "today")
            for entry in WeatherTool._hourly_entries(day)[:hourly_slots]:
                time_label = WeatherTool._hour_label(entry.get("time"))
                condition = WeatherTool._description(entry)
                temp = WeatherTool._temperature(entry.get(WeatherTool._hourly_temp_key(units)), units)
                feels_like = WeatherTool._temperature(entry.get(WeatherTool._hourly_feels_key(units)), units)
                rain = WeatherTool._percent(entry.get("chanceofrain"))
                storm = WeatherTool._percent(entry.get("chanceofthunder"))
                wind = WeatherTool._wind(entry, units)
                rows.append(
                    f"- {date} {time_label}: {condition}; {temp} (feels like {feels_like}); "
                    f"rain {rain}; storm {storm}; wind {wind}."
                )

        if not rows:
            return "Hourly: no hourly forecast data returned."
        return "Hourly:\n" + "\n".join(rows)

    @staticmethod
    def _advisories(current: dict[str, Any], weather_days: list[dict[str, Any]]) -> list[str]:
        advisories: list[str] = []
        feels_c = WeatherTool._number(current.get("FeelsLikeC"))
        wind_kmph = WeatherTool._number(current.get("windspeedKmph"))
        visibility_km = WeatherTool._number(current.get("visibility"))
        uv = WeatherTool._number(current.get("uvIndex"))
        precip_mm = WeatherTool._number(current.get("precipMM"))
        rain_chance = WeatherTool._max_chance_many(weather_days, "chanceofrain")
        storm_chance = WeatherTool._max_chance_many(weather_days, "chanceofthunder")
        snow_chance = WeatherTool._max_chance_many(weather_days, "chanceofsnow")

        if feels_c is not None and feels_c >= 38:
            advisories.append(f"heat stress likely, feels like {WeatherTool._format_number(feels_c)} deg C")
        if feels_c is not None and feels_c <= 5:
            advisories.append(f"cold conditions, feels like {WeatherTool._format_number(feels_c)} deg C")
        if wind_kmph is not None and wind_kmph >= 35:
            advisories.append(f"strong wind around {WeatherTool._format_number(wind_kmph)} km/h")
        if visibility_km is not None and visibility_km <= 4:
            advisories.append(f"low visibility around {WeatherTool._format_number(visibility_km)} km")
        if uv is not None and uv >= 6:
            advisories.append(f"high UV index {WeatherTool._format_number(uv)}")
        if precip_mm is not None and precip_mm > 0:
            advisories.append(f"active precipitation {WeatherTool._format_number(precip_mm)} mm")
        if rain_chance is not None and rain_chance >= 60:
            advisories.append(f"rain chance peaks near {rain_chance}%")
        if storm_chance is not None and storm_chance >= 40:
            advisories.append(f"storm chance peaks near {storm_chance}%")
        if snow_chance is not None and snow_chance >= 50:
            advisories.append(f"snow chance peaks near {snow_chance}%")

        return advisories

    @staticmethod
    def _display_location(area: dict[str, Any], fallback_location: str) -> str:
        place = WeatherTool._value(area.get("areaName")) or fallback_location
        region = WeatherTool._value(area.get("region"))
        country = WeatherTool._value(area.get("country"))
        location_bits = [bit for bit in (place, region, country) if bit]
        return ", ".join(location_bits) or fallback_location

    @staticmethod
    def _weather_days(data: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for item in data.get("weather") or [] if isinstance(item, dict)]

    @staticmethod
    def _hourly_entries(day: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for item in day.get("hourly") or [] if isinstance(item, dict)]

    @staticmethod
    def _astronomy(day: dict[str, Any]) -> dict[str, Any]:
        return WeatherTool._first_dict(day.get("astronomy"))

    @staticmethod
    def _daily_condition(day: dict[str, Any]) -> str:
        direct = WeatherTool._description(day, default="")
        if direct:
            return direct

        hourly = WeatherTool._hourly_entries(day)
        if not hourly:
            return "Unknown"

        noon_minutes = 12 * 60
        closest = min(hourly, key=lambda entry: abs(WeatherTool._time_minutes(entry.get("time")) - noon_minutes))
        return WeatherTool._description(closest)

    @staticmethod
    def _description(record: dict[str, Any], default: str = "Unknown") -> str:
        return WeatherTool._value(record.get("weatherDesc")) or default

    @staticmethod
    def _current_temperature(current: dict[str, Any], units: str) -> str:
        key = "temp_F" if units == "imperial" else "temp_C"
        return WeatherTool._temperature(current.get(key), units)

    @staticmethod
    def _current_feels_like(current: dict[str, Any], units: str) -> str:
        key = "FeelsLikeF" if units == "imperial" else "FeelsLikeC"
        return WeatherTool._temperature(current.get(key), units)

    @staticmethod
    def _temperature(value: Any, units: str) -> str:
        suffix = "deg F" if units == "imperial" else "deg C"
        return WeatherTool._measure(value, suffix, unknown=f"unknown {suffix}")

    @staticmethod
    def _wind(record: dict[str, Any], units: str) -> str:
        if units == "imperial":
            return WeatherTool._measure(record.get("windspeedMiles"), "mph")
        return WeatherTool._measure(record.get("windspeedKmph"), "km/h")

    @staticmethod
    def _visibility(record: dict[str, Any], units: str) -> str:
        key = "visibilityMiles" if units == "imperial" else "visibility"
        suffix = "mi" if units == "imperial" else "km"
        value = WeatherTool._text(record.get(key), "")
        return WeatherTool._measure(value, suffix) if value else ""

    @staticmethod
    def _precip(record: dict[str, Any], units: str) -> str:
        key = "precipInches" if units == "imperial" else "precipMM"
        suffix = "in" if units == "imperial" else "mm"
        value = WeatherTool._number(record.get(key))
        if value is None:
            return ""
        return f"{WeatherTool._format_number(value)} {suffix}"

    @staticmethod
    def _daily_high_key(units: str) -> str:
        return "maxtempF" if units == "imperial" else "maxtempC"

    @staticmethod
    def _daily_low_key(units: str) -> str:
        return "mintempF" if units == "imperial" else "mintempC"

    @staticmethod
    def _hourly_temp_key(units: str) -> str:
        return "tempF" if units == "imperial" else "tempC"

    @staticmethod
    def _hourly_feels_key(units: str) -> str:
        return "FeelsLikeF" if units == "imperial" else "FeelsLikeC"

    @staticmethod
    def _chance_text(chances: dict[str, int | None]) -> str:
        parts = [f"{name} {value}%" for name, value in chances.items() if value is not None]
        return ", ".join(parts) if parts else "precipitation risk unknown"

    @staticmethod
    def _max_chance(day: dict[str, Any], key: str) -> int | None:
        values = [WeatherTool._int(entry.get(key)) for entry in WeatherTool._hourly_entries(day)]
        values = [value for value in values if value is not None]
        return max(values) if values else None

    @staticmethod
    def _max_chance_many(weather_days: list[dict[str, Any]], key: str) -> int | None:
        values = [WeatherTool._max_chance(day, key) for day in weather_days]
        values = [value for value in values if value is not None]
        return max(values) if values else None

    @staticmethod
    def _hour_label(value: Any) -> str:
        minutes = WeatherTool._time_minutes(value)
        if minutes < 0:
            return WeatherTool._text(value, "time unknown")
        hour = minutes // 60
        minute = minutes % 60
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _time_minutes(value: Any) -> int:
        raw = WeatherTool._text(value, "")
        if not raw:
            return -1
        try:
            number = int(float(raw))
        except ValueError:
            return -1
        hour = number // 100
        minute = number % 100
        if hour > 23 or minute > 59:
            return -1
        return hour * 60 + minute

    @staticmethod
    def _percent(value: Any) -> str:
        text = WeatherTool._text(value, "")
        return f"{text}%" if text else "unknown"

    @staticmethod
    def _measure(value: Any, suffix: str, unknown: str | None = None) -> str:
        text = WeatherTool._text(value, "")
        if not text:
            return unknown or f"unknown {suffix}"
        number = WeatherTool._number(text)
        if number is None:
            return f"{text} {suffix}"
        return f"{WeatherTool._format_number(number)} {suffix}"

    @staticmethod
    def _mode(mode: str) -> str:
        normalized = (mode or "current").strip().lower()
        aliases = {
            "now": "current",
            "today": "current",
            "daily": "forecast",
            "forecast": "forecast",
            "hourly": "hourly",
            "full": "full",
            "pro": "full",
            "detailed": "full",
        }
        return aliases.get(normalized, "current")

    @staticmethod
    def _units(units: str) -> str:
        normalized = (units or "metric").strip().lower()
        if normalized in {"imperial", "us", "fahrenheit", "f"}:
            return "imperial"
        return "metric"

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        parsed = WeatherTool._int(value)
        if parsed is None:
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _int(value: Any) -> int | None:
        number = WeatherTool._number(value)
        return int(number) if number is not None else None

    @staticmethod
    def _number(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(int(value))
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _format_number(value: float) -> str:
        if value.is_integer():
            return str(int(value))
        return f"{value:.1f}".rstrip("0").rstrip(".")

    @staticmethod
    def _text(value: Any, default: str) -> str:
        if value is None:
            return default
        text = str(value).strip()
        return text if text else default

    @staticmethod
    def _value(value: Any) -> str:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    text = str(item.get("value") or "").strip()
                    if text:
                        return text
                elif isinstance(item, str) and item.strip():
                    return item.strip()
            return ""
        if isinstance(value, dict):
            return str(value.get("value") or "").strip()
        if isinstance(value, str):
            return value.strip()
        return ""

    @staticmethod
    def _first_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    return item
        if isinstance(value, dict):
            return value
        return {}
