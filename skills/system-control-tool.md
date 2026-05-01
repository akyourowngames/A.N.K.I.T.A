# System Control Tool

Use this when sir asks to control the local Windows system:

- set volume
- mute or unmute
- set brightness
- open Bluetooth settings
- open Windows settings pages
- open apps

Behavior:

- Treat direct system control as the first path.
- For opening apps, resolve apps dynamically from Windows instead of relying on a hardcoded app list.
- Try direct launch, command/exe lookup, Start Menu shortcuts, and Windows StartApps/AppID matches.
- If direct control fails, use terminal fallback or return discovered matches where possible.
- For opening apps, verify the app actually appeared in the process/window list before reporting success.
- Say the action is unverified or failed when verification fails; do not say it opened just because the launch command ran.
- Report the final outcome plainly.
- Avoid long explanations unless the action fails.
- Do not ask for confirmation for harmless changes like opening settings.
