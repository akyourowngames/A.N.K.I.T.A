# Sharing Ankita (Windows)

Ankita packages as a self-contained Electron app. The recipient does **not** need
Node, npm, or this repository — only the `.exe` and, on first run, a way to
authenticate to a model provider.

## What to send

Build the artifacts (`npm run desktop:package`) and share one of:

| File | Use | Notes |
| --- | --- | --- |
| `desktop/release/Ankita-<version>-portable-x64.exe` | **Easiest to share** | Single file (~110 MB), no install. Good for a download link. |
| `desktop/release/Ankita-<version>-setup-x64.exe` | Proper install | Adds Start Menu + desktop shortcut and an uninstaller. |

- Don't email it — most mail services cap attachments below 25 MB. Use a download
  link (GitHub Releases, Google Drive, Dropbox, S3, etc.).
- Share **only** the `.exe`. The `win-unpacked/` folder and `.blockmap`/`latest.yml`
  files are build byproducts.
- The app is currently **unsigned**, so Windows SmartScreen will warn on first
  run. See below.

## What the recipient does

### Portable exe
1. Download `Ankita-<version>-portable-x64.exe` anywhere (e.g. Desktop).
2. If Windows shows **"Windows protected your PC"** → click **More info** →
   **Run anyway**. (This appears because the build is not code-signed.)
3. The Ankita window opens. On first run it asks to connect a model provider
   (see below).

### Installer exe
1. Run `Ankita-<version>-setup-x64.exe`.
2. Same SmartScreen prompt if it appears → **More info** → **Run anyway**.
3. Choose an install folder (per-user by default, no admin needed), finish, and
   launch from the Start Menu or desktop shortcut.

## First run: connecting a model provider

Ankita needs a model. There are two paths.

### A. GitHub Copilot (default, recommended)
On first launch the app shows a **"Connect to GitHub"** dialog with a code.
1. Click **Open GitHub**.
2. Enter the code shown, and approve access.
3. The dialog closes and the app is ready.

The user needs a GitHub account with Copilot access. An internet connection is
required. Credentials are saved locally (see below), so this is one-time.

### B. A custom / keyless provider
Advanced users can skip GitHub by pointing Ankita at any OpenAI-compatible
endpoint (Kilo, Groq, OpenRouter, Ollama, LM Studio, ...). Create the file

```
%USERPROFILE%\.copilot-chat-cli\config.env
```

with, for example:

```env
USERNAME=their-name
AGENT_NAME=Ankita
TOOLS=on

# Pick ONE provider:
# Kilo (keyless free models)
PROVIDER=kilo
MODEL=<model-id>

# or an OpenAI-compatible endpoint
# PROVIDER=compatible
# API_BASE=https://your-endpoint/v1
# API_KEY=sk-...

# or Groq
# PROVIDER=groq
# GROQ_API_KEY=gsk-...
```

Restart the app after saving. See the repository `.env.example` for every option.

## Where Ankita keeps its data

Everything lives under the user's home, nothing is written next to the exe:

```
%USERPROFILE%\.copilot-chat-cli\      # config + auth + teammates + sessions
  config.env                          # provider and settings (you create this)
  auth.json                           # saved GitHub/Copilot token (auto)
  desktop-teammates.json              # teammates
  sessions\                           # per-teammate conversations
  composio.json, mcp.json             # connected apps / MCP servers
```

App cache/preferences (window size, etc.) go under `%APPDATA%\Ankita`.

To reset Ankita on a machine, delete `%USERPROFILE%\.copilot-chat-cli` (removes
all teammates and credentials) and `%APPDATA%\Ankita`.

## Notes for the person sharing

- **Unsigned builds warn.** Windows SmartScreen flags any exe without a
  reputation. Recipients can bypass with More info → Run anyway. To remove the
  warning, add signing credentials — see [`code-signing.md`](./code-signing.md).
- **Auto-update is enabled** for **installed** builds: they check GitHub Releases
  on launch (and via **Help → Check for updates…**) and offer a restart when a
  newer version is ready. Recipients of the **portable** exe re-download instead.
  See [`releasing.md`](./releasing.md) for how to publish a new version.
- **macOS/Linux** targets are declared but unbuilt here; they need to be built on
  (or for) those platforms.
- **Rebuild command:** `npm run desktop:build && npm run desktop:package`.
