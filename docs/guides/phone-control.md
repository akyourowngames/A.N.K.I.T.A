# Phone control

Ankita can drive an Android phone, emulator or (on a Mac) an iOS simulator
through one `phone` tool. It is built on
[mobile-next/mobile-mcp](https://github.com/mobile-next/mobile-mcp), pinned to a
known version so the set of actions cannot change under you.

This is different from [phone pairing](phone-pairing.md): pairing connects the
Ankita phone app to the desktop assistant. This page is about the assistant
using adb to operate a phone.

Phone control is exposed by the desktop app and desktop host. The plain
terminal client does not offer the `phone` tool.

## What you need

- **Android:** the Android SDK Platform Tools (`adb`) and a running emulator or
  a USB-connected phone with **USB debugging** turned on and authorized.
- **iOS:** a Mac with Xcode and a booted simulator. iOS does not work on
  Windows.
- Node 20 or newer. The first call downloads the bridge and its platform
  helper, so it takes longer than later ones.

Ankita finds `adb` on your `PATH`, or under the standard Android SDK location
(`%LOCALAPPDATA%\Android\Sdk\platform-tools` on Windows).

## Using it

Ask in plain words, for example:

- "Connect to my phone over Wi-Fi."
- "What's on my phone screen right now?"
- "Open Chrome on the emulator and search for weather."
- "Take a screenshot of the phone."
- "Which app is in the foreground?"
- "Show me the last 40 log lines for tag=AndroidRuntime."

The assistant starts with `action="devices"`, picks the phone (it selects
automatically when exactly one is attached), then reads the screen with
`action="see"` and taps the fresh `@ref` it returns.

A `phone-control` guide loads automatically as soon as the phone tool is
discovered. It keeps the assistant on that connect → read → act path, tells it
to rediscover a changed Wi-Fi port instead of reusing an old one, and avoids
extra screenshots, unfiltered logs and repeated device lookups.

## Adding a phone over Wi-Fi

Ankita does the setup; you only read a number off the phone.

1. On the phone: Settings → Developer options → **Wireless debugging** → on.
2. Tap **Pair device with pairing code** and leave that dialog open.
3. Tell Ankita *"connect to my phone over Wi-Fi"* and give it the **six-digit
   code** it asks for.

Ankita finds the phone on your network itself (`adb mdns`), pairs with it, and
connects — you never type an adb command or copy a port number. The code is
sent to adb over stdin, so it never appears in the process list, and it is
hidden from the approval preview.

If a wireless phone drops off after the phone sleeps or the router changes,
the next action reconnects it automatically using the address it remembered.
To connect a phone that was already paired, ask *"reconnect my phone over
Wi-Fi"* — it uses the remembered address, or re-discovers it with
`action="wireless"`.


## Actions

| Action | What it does |
| --- | --- |
| `wireless`, `wireless_pair`, `wireless_connect` | Find, pair and reconnect a phone over Wi-Fi |
| `devices`, `use` | List phones and choose the active one |
| `see` | Read the screen: refs, labels and coordinates |
| `tap`, `double_tap`, `long_press` | Act on a `@ref` or on x/y from the latest screenshot |
| `swipe`, `type`, `button` | Swipe, type text (optionally submit), press a hardware button |
| `screenshot` | Capture the screen; the image is attached for you |
| `open`, `launch`, `foreground`, `apps` | Open a URL, launch an app, see the current app, list apps |
| `install`, `uninstall`, `terminate`, `clear_data` | Manage installed apps |
| `orientation`, `set_orientation`, `size`, `fold` | Screen size, rotation, foldable posture |
| `logs`, `crashes`, `crash` | Device logs and crash reports |
| `location`, `clipboard`, `start_recording`, `stop_recording` | Location override, clipboard, screen recording |
| `batch` | Run several steps in one call |
| `raw` | Call an allow-listed mobile-mcp tool directly |

## Approval

- **First use** asks once, showing the exact command that will run. This is the
  only time third-party code starts.
- **After that**, reading the screen, tapping, typing and launching apps run
  without a prompt.
- **Destructive actions** — `uninstall`, `clear_data` and `stop_recording` (and
  their `raw` equivalents) — always ask, because they end or erase state.

The bridge is hidden from the MCP server list and never starts on its own; only
a phone action starts it. Telephone and cloud-device tools from mobile-mcp are
not offered, so a call can never reserve or bill a remote device.

## Safety

- Phone screen content is treated as untrusted data. It cannot authorize an
  action by itself.
- Type only text you intend the phone to receive; the approval preview hides it
  from your transcript.
- Logins, passwords and payment screens should be handled by you directly on
  the phone.
- Captures are saved into `downloaded-images/` in the current workspace.

## Troubleshooting

- **"No local phone…"** — start an emulator, plug in a phone with USB debugging
  on, or say "connect to my phone over Wi-Fi". On Windows, the Android emulator
  also needs hardware virtualization enabled.
- **"No phone is advertising wireless debugging"** — wireless debugging is off
  on the phone, or the phone is on a different network. The pairing dialog must
  be open for pairing; the main screen is enough for reconnecting.
- **Wireless drops after sleep** — the next action reconnects automatically; if
  it does not, ask it to reconnect.
- **Slow first call** — the bridge is downloading. Later calls are faster.
- **`adb` not found** — install Android SDK Platform Tools, or set
  `ANDROID_HOME` to your SDK folder.
