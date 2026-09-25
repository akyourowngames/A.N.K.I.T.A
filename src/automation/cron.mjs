/**
 * Cron scheduling without dependencies.
 *
 * Supports the standard five fields (minute hour day-of-month month
 * day-of-week) with `*`, `n`, `a-b`, `a,b`, and `/step` in any position,
 * the usual @aliases, and human shorthands like "every 30m" or "daily 08:00".
 */

const FIELD_RANGES = {
  minute: [0, 59],
  hour: [0, 23],
  dom: [1, 31],
  month: [1, 12],
  dow: [0, 7],
};

const ALIASES = {
  "@yearly": "0 0 1 1 *",
  "@annually": "0 0 1 1 *",
  "@monthly": "0 0 1 * *",
  "@weekly": "0 0 * * 0",
  "@daily": "0 0 * * *",
  "@midnight": "0 0 * * *",
  "@hourly": "0 * * * *",
};

const DOW_NAMES = {
  sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6,
};
const MONTH_NAMES = {
  jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
  jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12,
};

function expandField(raw, [min, max], names = null) {
  const values = new Set();
  for (const part of String(raw).split(",")) {
    const piece = part.trim();
    if (!piece) continue;

    const [rangePart, stepPart] = piece.split("/");
    const step = stepPart === undefined ? 1 : Number(stepPart);
    if (!Number.isInteger(step) || step < 1) return null;

    let from;
    let to;
    if (rangePart === "*") {
      from = min;
      to = max;
    } else if (rangePart.includes("-")) {
      const [a, b] = rangePart.split("-");
      from = resolveName(a, names);
      to = resolveName(b, names);
    } else {
      from = resolveName(rangePart, names);
      to = from;
      if (stepPart !== undefined) to = max;
    }

    if (from === null || to === null || from > to) return null;
    if (from < min || to > max) return null;

    for (let v = from; v <= to; v += step) values.add(v);
  }
  if (!values.size) return null;
  if (max === 7 && values.has(7)) {
    values.delete(7);
    values.add(0);
  }
  return values;
}

function resolveName(token, names) {
  const t = String(token).trim().toLowerCase();
  if (names && Object.prototype.hasOwnProperty.call(names, t)) return names[t];
  const n = Number(t);
  return Number.isInteger(n) && t !== "" ? n : null;
}

/** "every 30m" / "daily 08:00" / "@hourly" / "0 8 * * 1-5" -> cron string. */
export function normalizeSchedule(expr) {
  const raw = String(expr ?? "").trim();
  if (!raw) return null;
  const lower = raw.toLowerCase();

  if (ALIASES[lower]) return ALIASES[lower];

  const every = lower.match(/^every\s+(\d+)\s*(m|min|mins|minute|minutes|h|hr|hour|hours|d|day|days)$/);
  if (every) {
    const n = Number(every[1]);
    if (n < 1) return null;
    const unit = every[2][0];
    if (unit === "m") return n <= 59 ? `*/${n} * * * *` : `0 */${Math.max(1, Math.round(n / 60))} * * *`;
    if (unit === "h") return n <= 23 ? `0 */${n} * * *` : `0 0 */${Math.max(1, Math.round(n / 24))} * *`;
    return `0 0 */${n} * *`;
  }

  const atTime = lower.match(/^(?:daily|every\s*day|\@daily)\s+(?:at\s+)?(\d{1,2})[:.](\d{2})\s*(am|pm)?$/);
  if (atTime) {
    let hour = Number(atTime[1]);
    const minute = Number(atTime[2]);
    if (atTime[3] === "pm" && hour < 12) hour += 12;
    if (atTime[3] === "am" && hour === 12) hour = 0;
    if (hour > 23 || minute > 59) return null;
    return `${minute} ${hour} * * *`;
  }

  const weekdays = lower.match(/^weekdays\s+(?:at\s+)?(\d{1,2})[:.](\d{2})\s*(am|pm)?$/);
  if (weekdays) {
    let hour = Number(weekdays[1]);
    const minute = Number(weekdays[2]);
    if (weekdays[3] === "pm" && hour < 12) hour += 12;
    if (weekdays[3] === "am" && hour === 12) hour = 0;
    if (hour > 23 || minute > 59) return null;
    return `${minute} ${hour} * * 1-5`;
  }

  return raw.split(/\s+/).length === 5 ? raw : null;
}

export function parseCron(expr) {
  const cron = normalizeSchedule(expr);
  if (!cron) return null;
  const parts = cron.split(/\s+/);
  if (parts.length !== 5) return null;

  const minute = expandField(parts[0], FIELD_RANGES.minute);
  const hour = expandField(parts[1], FIELD_RANGES.hour);
  const dom = expandField(parts[2], FIELD_RANGES.dom);
  const month = expandField(parts[3], FIELD_RANGES.month);
  const dow = expandField(parts[4], FIELD_RANGES.dow, DOW_NAMES);
  if (!minute || !hour || !dom || !month || !dow) return null;

  return {
    expr: cron,
    minute,
    hour,
    dom,
    month,
    dow,
    // Standard cron: when both day fields are restricted, either may match.
    domRestricted: parts[2].trim() !== "*",
    dowRestricted: parts[4].trim() !== "*",
  };
}

/** True when `date` falls inside the field. Granularity is one minute. */
export function matchCron(expr, date = new Date()) {
  const parsed = typeof expr === "string" ? parseCron(expr) : expr;
  if (!parsed) return false;

  if (!parsed.minute.has(date.getMinutes())) return false;
  if (!parsed.hour.has(date.getHours())) return false;
  if (!parsed.month.has(date.getMonth() + 1)) return false;

  const domHit = parsed.dom.has(date.getDate());
  const dowHit = parsed.dow.has(date.getDay());
  if (parsed.domRestricted && parsed.dowRestricted) return domHit || dowHit;
  if (parsed.domRestricted) return domHit;
  if (parsed.dowRestricted) return dowHit;
  return true;
}

const WEEKDAY_LABEL = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

export function describeCron(expr) {
  const parsed = typeof expr === "string" ? parseCron(expr) : expr;
  if (!parsed) return "invalid schedule";
  const [minute, hour, , , dow] = parsed.expr.split(/\s+/);

  const time =
    /^\d+$/.test(minute) && /^\d+$/.test(hour)
      ? `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`
      : null;

  if (time) {
    if (dow === "*") return `daily at ${time}`;
    if (dow === "1-5") return `weekdays at ${time}`;
    const days = [...parsed.dow].sort((a, b) => a - b).map((d) => WEEKDAY_LABEL[d].slice(0, 3));
    return `${days.join(", ")} at ${time}`;
  }
  if (/^\*\/(\d+)$/.test(minute) && hour === "*") return `every ${minute.slice(2)} minutes`;
  if (/^0$/.test(minute) && /^\*\/(\d+)$/.test(hour)) return `every ${hour.slice(2)} hours`;
  return parsed.expr;
}

/** Parses "30s" / "15m" / "2h" / "3d" into milliseconds. */
export function parseDuration(text, fallbackMs = 0) {
  const m = String(text ?? "").trim().toLowerCase().match(/^(\d+)\s*(s|sec|secs|m|min|mins|h|hr|hrs|d|day|days)$/);
  if (!m) {
    const n = Number(text);
    return Number.isFinite(n) && n > 0 ? n * 1000 : fallbackMs;
  }
  const n = Number(m[1]);
  const unit = m[2][0];
  const mult = unit === "s" ? 1000 : unit === "m" ? 60000 : unit === "h" ? 3600000 : 86400000;
  return n * mult;
}

export function formatDuration(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${(s / 3600).toFixed(s % 3600 === 0 ? 0 : 1)}h`;
  return `${(s / 86400).toFixed(s % 86400 === 0 ? 0 : 1)}d`;
}
