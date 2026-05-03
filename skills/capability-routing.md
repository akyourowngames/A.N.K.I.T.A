# Capability Routing

Use this as the high-level map of connected assistant capabilities.

Connected tools:

- `tavily_search`: live web search for current, recent, future, official, external, or likely-changing public facts.
- `weather`: current weather, forecast, hourly outlook, and weather advisories.
- `system_control`: Windows volume, mute, screen/display brightness, Bluetooth/settings pages, and opening apps.
- `terminal`: explicit PowerShell, command-line, install, git, unrestricted filesystem, process, or diagnostic commands.
- `local_files`: safe listing, searching, and reading of normal local files in allowed folders.
- `music`: search, play, queue, pause, resume, skip, stop, and status for local music playback.
- `image_generation`: generate and save images through the configured NVIDIA image model.
- `gmail`: search, read, draft, or send Gmail messages when credentials are configured.
- `google_calendar`: list, create, or delete Google Calendar events when credentials are configured.
- `date_time`: current date and time for a timezone.

Routing rules:

- Prefer a connected tool when the user asks for a real action or current/external information.
- Do not say a connected capability is unavailable before trying its tool.
- If a tool fails, report the failure from tool output instead of claiming the capability is not connected.
- Use normal chat only for answers that do not require live data, local state, files, device control, or external actions.
