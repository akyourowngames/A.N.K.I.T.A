# Date-Time Tool

Use this tool when the user asks for fresh clock context.

- current date, time, day, timezone, UTC offset, or time of day
- whether it is morning, afternoon, evening, or night
- comparing two timezones
- converting an ISO datetime from one timezone to another
- scheduling context where exact timezone-aware time matters

Default timezone: `Asia/Kolkata`

Tool arguments:

- `mode`: `now`, `compare`, or `convert`.
- `timezone`: source/current IANA timezone.
- `target_timezone`: target IANA timezone for compare/convert.
- `source_time`: ISO datetime for conversion, for example `2026-05-03T14:30:00`.

Behavior:

- Use `now` for simple current-time questions.
- Use `compare` when sir asks "what time is it there vs here" or asks for two timezones.
- Use `convert` for explicit date/time conversion.
- Treat output as fresh runtime context.
