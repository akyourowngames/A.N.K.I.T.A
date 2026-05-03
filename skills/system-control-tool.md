# System Control Tool

Use this when sir asks to control or inspect the local Windows system without asking for a raw shell command.

- System status: volume, mute state, brightness, battery, OS, and uptime.
- Volume: get volume, set volume, raise/lower volume, mute, unmute, or toggle mute.
- Display brightness: get brightness, set brightness, dim/lower brightness, brighten/raise brightness.
- Windows settings: open Bluetooth or any Windows settings page.
- Apps: dynamically find or open installed apps.
- Links and paths: open URLs, files, folders, or reveal a path in Explorer.
- Lock screen only when sir explicitly asks to lock the screen.

Action mapping:

- `status`: inspect safe local status.
- `get_volume`, `set_volume`, `volume_up`, `volume_down`, `mute`, `unmute`, `toggle_mute`.
- `get_brightness`, `set_brightness`, `brightness_up`, `brightness_down`.
- `open_bluetooth`.
- `open_settings` with `target=<settings page>`; pass the page dynamically, for example `display`, `privacy`, or `windowsupdate`.
- `open_app` with `target=<app name or executable command>`.
- `find_app` with `target=<app name>` when sir asks what app matches are available.
- `open_url` with `target=<absolute URL or URI>`.
- `open_path` with `target=<file/folder path>`.
- `reveal_path` with `target=<file/folder path>`.
- `lock_screen` only for explicit lock requests.

Useful arguments:

- `value`: percent for `set_volume` or `set_brightness`; can also carry URL/path/app/settings target when `target` is not supplied.
- `target`: app name, settings page, URL, file path, or folder path.
- `amount`: adjustment step for `volume_up`, `volume_down`, `brightness_up`, or `brightness_down`; default to 10 when unspecified.

Pro behavior:

- Resolve apps dynamically from Windows. Do not rely on a fixed app list.
- Use `open_app` for application names, program names, and executable commands. Use `open_url` only when the target is already an absolute URL/URI with a scheme.
- For app launch, try Start Menu shortcuts, Windows StartApps/AppID, App Paths registry entries, exact command lookup, and direct paths where appropriate.
- Verify app launch through process/window evidence before claiming success.
- If app launch cannot be verified, return discovered matches and say it failed or is unverified.
- Treat observed PC activity as read-only context. It can describe what is already visible, but it must not be used as proof that this turn completed an action.
- Use the system control tool output as the source of truth for local-control claims. If no tool output is supplied, do not claim completion.
- For vague dim/lower brightness requests, use `brightness_down` with a modest amount. For vague brighten requests, use `brightness_up`.
- For vague raise/lower volume requests, use `volume_up` or `volume_down` with a modest amount.
- Use terminal only when sir asks for command-line execution or when this tool returns a fallback command.
- Do not claim success when tool output says `FAILED`, unavailable, or unverified.
