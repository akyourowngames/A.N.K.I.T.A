from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class DateTimeTool:
    name: str = "date_time"
    description: str = "Returns current time, timezone comparisons, and ISO datetime conversions."

    def run(
        self,
        timezone: str = "Asia/Kolkata",
        mode: str = "now",
        target_timezone: str = "",
        source_time: str = "",
    ) -> str:
        mode = (mode or "now").strip().lower()
        if mode in {"compare", "comparison"}:
            return self._compare(timezone, target_timezone or "UTC")
        if mode in {"convert", "conversion"}:
            return self._convert(timezone, target_timezone or "UTC", source_time)
        return self._now(timezone)

    def _now(self, timezone: str) -> str:
        zone = self._timezone(timezone)
        now = datetime.now(zone)
        return "\n".join(
            [
                f"Current date/time: {now.strftime('%A, %B %d, %Y at %I:%M:%S %p %Z')}",
                f"ISO date/time: {now.isoformat()}",
                f"UTC offset: {self._offset_text(now)}",
                f"Time of day: {self._time_of_day(now.hour)}",
                f"Morning now: {'yes' if now.hour < 12 else 'no'}",
            ]
        )

    def _compare(self, timezone: str, target_timezone: str) -> str:
        source_zone = self._timezone(timezone)
        target_zone = self._timezone(target_timezone)
        source_now = datetime.now(source_zone)
        target_now = source_now.astimezone(target_zone)
        delta = self._offset_delta(source_now, target_now)
        return "\n".join(
            [
                f"{timezone}: {source_now.strftime('%A, %B %d, %Y at %I:%M:%S %p %Z')} ({self._offset_text(source_now)})",
                f"{target_timezone}: {target_now.strftime('%A, %B %d, %Y at %I:%M:%S %p %Z')} ({self._offset_text(target_now)})",
                f"Offset difference: {delta}",
            ]
        )

    def _convert(self, timezone: str, target_timezone: str, source_time: str) -> str:
        if not source_time.strip():
            return "FAILED: source_time is required for date/time conversion."

        source_zone = self._timezone(timezone)
        target_zone = self._timezone(target_timezone)
        try:
            source_dt = self._parse_datetime(source_time, source_zone)
        except ValueError as error:
            return f"FAILED: could not parse source_time: {error}"

        converted = source_dt.astimezone(target_zone)
        return "\n".join(
            [
                f"Source: {source_dt.strftime('%A, %B %d, %Y at %I:%M:%S %p %Z')} ({source_dt.isoformat()})",
                f"Converted: {converted.strftime('%A, %B %d, %Y at %I:%M:%S %p %Z')} ({converted.isoformat()})",
                f"From timezone: {timezone}",
                f"To timezone: {target_timezone}",
            ]
        )

    @staticmethod
    def _timezone(timezone: str):
        normalized = timezone.strip()
        fallbacks = {
            "UTC": datetime_timezone.utc,
            "Etc/UTC": datetime_timezone.utc,
            "Asia/Kolkata": datetime_timezone(timedelta(hours=5, minutes=30), "IST"),
            "Asia/Calcutta": datetime_timezone(timedelta(hours=5, minutes=30), "IST"),
        }
        if normalized in fallbacks:
            return fallbacks[normalized]

        try:
            return ZoneInfo(normalized)
        except ZoneInfoNotFoundError:
            return datetime_timezone.utc

    @staticmethod
    def _parse_datetime(source_time: str, default_timezone) -> datetime:
        text = source_time.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=default_timezone)
        return parsed

    @staticmethod
    def _offset_text(moment: datetime) -> str:
        offset = moment.utcoffset()
        if offset is None:
            return "unknown"
        total_minutes = int(offset.total_seconds() // 60)
        sign = "+" if total_minutes >= 0 else "-"
        total_minutes = abs(total_minutes)
        return f"UTC{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"

    @staticmethod
    def _offset_delta(source: datetime, target: datetime) -> str:
        source_offset = source.utcoffset() or timedelta()
        target_offset = target.utcoffset() or timedelta()
        minutes = int((target_offset - source_offset).total_seconds() // 60)
        sign = "+" if minutes >= 0 else "-"
        minutes = abs(minutes)
        return f"{sign}{minutes // 60}h {minutes % 60}m"

    @staticmethod
    def _time_of_day(hour: int) -> str:
        if hour < 12:
            return "morning"
        if hour < 17:
            return "afternoon"
        if hour < 21:
            return "evening"
        return "night"
