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
- If direct control fails, use terminal fallback where possible.
- Report the final outcome plainly.
- Avoid long explanations unless the action fails.
- Do not ask for confirmation for harmless changes like opening settings.
