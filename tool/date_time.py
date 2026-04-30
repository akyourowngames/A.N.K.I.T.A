from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class DateTimeTool:
    name: str = "date_time"
    description: str = "Returns the current date and time for a timezone."

    def run(self, timezone: str = "Asia/Kolkata") -> str:
        now = datetime.now(self._timezone(timezone))
        return now.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")

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
