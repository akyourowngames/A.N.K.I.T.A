# Weather Tool

Use this when sir asks for:

- current weather, temperature, feels-like temperature, humidity, wind, visibility, UV, sunrise, or sunset
- daily forecast, tomorrow's weather, weekend outlook, hourly timing, or whether rain/storms/snow are likely
- whether it is a good time to go out, commute, ride, walk, shoot video, travel, or keep windows/laundry outside
- heat, cold, poor visibility, high wind, high UV, rain, storm, or snow risk

Tool arguments:

- `location`: city, area, or place name. Prefer known user facts for default location when available.
- `mode`: `current`, `forecast`, `hourly`, or `full`/`pro`. Use `full` for planning-style answers.
- `days`: forecast days from 1 to 3.
- `units`: `metric` or `imperial`.
- `include_hourly`: include hourly rows when the user cares about timing.
- `hourly_slots`: number of hourly rows per day, from 1 to 8.

Pro behavior:

- Lead with the current condition and temperature.
- Add advisories when structured data shows heat stress, cold, high UV, strong wind, low visibility, active precipitation, rain, storm, or snow risk.
- Use forecast mode for "today/tomorrow/next few days" and hourly mode when timing matters.
- Keep short answers compact, but use `full`/`pro` mode for outdoor planning or travel decisions.
- Do not expose provider names, raw payloads, or implementation details.
