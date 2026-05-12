from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .registry import ToolInputError, optional_text


def get_current_datetime(params: dict[str, Any]) -> dict[str, Any]:
    timezone = optional_text(params, "timezone")
    if timezone:
        try:
            now = datetime.now(ZoneInfo(timezone))
        except ZoneInfoNotFoundError as error:
            return get_network_datetime(timezone, error)
    else:
        now = datetime.now().astimezone()

    date_text = now.date().isoformat()
    time_text = now.strftime("%H:%M:%S")
    timezone_text = str(now.tzinfo)
    return {
        "summary": f"Current date and time: {date_text} {time_text} {timezone_text}",
        "timezone": str(now.tzinfo),
        "iso": now.isoformat(),
        "date": date_text,
        "time": time_text,
        "utc_offset": now.strftime("%z"),
    }


def get_network_datetime(timezone: str, original_error: Exception) -> dict[str, Any]:
    base_url = os.environ.get("TIME_API_BASE_URL", "https://timeapi.io/api/timezone/zone")
    zone_param = os.environ.get("TIME_API_ZONE_PARAM", "timeZone")
    timeout = time_timeout()
    url = f"{base_url}?{urllib.parse.urlencode({zone_param: timezone})}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, dict):
                raise ToolInputError("time service returned a non-object response")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ToolInputError(f"unknown timezone: {timezone}; time service failed: {error.code} {error.reason} {detail}") from error
    except urllib.error.URLError as error:
        raise ToolInputError(f"unknown timezone: {timezone}; time service failed: {error.reason}") from original_error
    except TimeoutError as error:
        raise ToolInputError(f"unknown timezone: {timezone}; time service timed out") from error

    raw_datetime = data.get("datetime") or data.get("dateTime") or data.get("currentLocalTime")
    if not isinstance(raw_datetime, str) or not raw_datetime:
        raise ToolInputError(f"time service did not return datetime for timezone: {timezone}")

    parsed = parse_service_datetime(raw_datetime)
    date_text = parsed.date().isoformat() if parsed else ""
    time_text = parsed.strftime("%H:%M:%S") if parsed else ""
    timezone_text = str(data.get("timezone") or data.get("timeZone") or timezone)
    summary_parts = [item for item in [date_text, time_text, timezone_text] if item]
    return {
        "summary": f"Current date and time: {' '.join(summary_parts)}".strip(),
        "timezone": data.get("timezone") or data.get("timeZone") or timezone,
        "iso": raw_datetime,
        "date": date_text,
        "time": time_text,
        "utc_offset": data.get("utc_offset") or data.get("utcOffset") or offset_from_service_data(data),
    }


def parse_service_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def offset_from_service_data(data: dict[str, Any]) -> str:
    offset = data.get("currentUtcOffset")
    if not isinstance(offset, dict):
        return ""

    seconds = offset.get("seconds")
    if not isinstance(seconds, int | float):
        return ""

    sign = "+" if seconds >= 0 else "-"
    total_minutes = abs(int(seconds)) // 60
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def time_timeout() -> int:
    raw = os.environ.get("TIME_API_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 20
    try:
        return int(raw)
    except ValueError:
        return 20
