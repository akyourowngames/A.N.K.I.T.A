from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional, Set


def _parse_iso_ms(text: str) -> Optional[int]:
    value = str(text or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _expand_piece(piece: str, minimum: int, maximum: int) -> Set[int]:
    out: Set[int] = set()
    value = piece.strip()
    if not value:
        return out
    base = value
    step = 1
    if "/" in value:
        base, raw_step = value.split("/", 1)
        step = int(raw_step)
    if base == "*":
        start, end = minimum, maximum
    elif "-" in base:
        a, b = base.split("-", 1)
        start, end = int(a), int(b)
    else:
        start = int(base)
        end = int(base)
    if step <= 0:
        raise ValueError("step must be > 0")
    start = max(minimum, start)
    end = min(maximum, end)
    for n in range(start, end + 1, step):
        out.add(n)
    return out


def _parse_field(expr: str, minimum: int, maximum: int) -> Set[int]:
    allowed: Set[int] = set()
    for part in expr.split(","):
        allowed |= _expand_piece(part, minimum, maximum)
    if not allowed:
        raise ValueError("empty cron field")
    return allowed


def _cron_match(dt: datetime, mins: Set[int], hours: Set[int], dom: Set[int], months: Set[int], dow: Set[int]) -> bool:
    cron_dow = (dt.weekday() + 1) % 7
    dom_is_all = len(dom) == 31
    dow_is_all = len(dow) == 7
    day_ok = (dt.day in dom and dow_is_all) or (cron_dow in dow and dom_is_all) or (dt.day in dom or cron_dow in dow)
    return dt.minute in mins and dt.hour in hours and dt.month in months and day_ok


def next_run_ms(schedule: Dict[str, object], now_ms: int) -> Optional[int]:
    kind = str(schedule.get("kind", "")).strip().lower()
    if kind == "at":
        at = _parse_iso_ms(str(schedule.get("at", "")))
        if at is None:
            return None
        return at if at > now_ms else None
    if kind == "every":
        every_ms = int(schedule.get("every_ms", schedule.get("everyMs", 0)) or 0)
        anchor_ms = int(schedule.get("anchor_ms", schedule.get("anchorMs", now_ms)) or now_ms)
        if every_ms <= 0:
            return None
        if now_ms < anchor_ms:
            return anchor_ms
        steps = ((now_ms - anchor_ms) // every_ms) + 1
        return anchor_ms + (steps * every_ms)
    if kind != "cron":
        return None

    expr = str(schedule.get("expr", "")).strip()
    fields = expr.split()
    if len(fields) != 5:
        return None
    mins = _parse_field(fields[0], 0, 59)
    hours = _parse_field(fields[1], 0, 23)
    dom = _parse_field(fields[2], 1, 31)
    months = _parse_field(fields[3], 1, 12)
    dow_raw = _parse_field(fields[4], 0, 7)
    dow = {0 if x == 7 else x for x in dow_raw}

    start = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = start + timedelta(days=366)
    cur = start
    while cur <= limit:
        if _cron_match(cur, mins, hours, dom, months, dow):
            return int(cur.timestamp() * 1000)
        cur += timedelta(minutes=1)
    return None

