# A.N.K.I.T.A - Personal AI Assistant

![GitHub last commit](https://img.shields.io/github/last-commit/akyourowngames/=flat-square)
![GitHub repo size](https://img.shields.io/github/repo-size/akyourowngames/=flat-square)
![GitHub stars](https://img.shields.io/github/stars/akyourowngames/=flat-square)
![Built with Python](https://img.shields.io/badge/built%20with-Python-111827?style=flat-square)

> A Python personal AI assistant with chat, voice, memory, Telegram, desktop tools, and project monitoring.

## Overview

A.N.K.I.T.A is built as a private operating assistant for daily workflows. It combines a terminal chat experience, speech input, persistent memory, tool modules, Telegram access, and a project daemon that can monitor activity and generate reports.

## Highlights

- Streaming terminal chat loop for fast assistant interactions
- Voice input through microphone or browser speech workflows
- Persistent memory, chat history, and profile context
- Telegram bot support for remote assistant access
- Tool modules for search, weather, calendar, Gmail, music playback, image generation, screen vision, and system utilities
- Project daemon for monitoring local work and producing summaries

## Built For

- Personal productivity and daily automation
- AI assistant experimentation
- Learning how tool-using agents can connect to real workflows
- Building a modular assistant foundation that can grow over time

## Tech Stack

- Python
- Google API clients
- Speech-to-text and browser speech workflows
- Telegram bot integration
- Local memory and project monitoring modules

## Quick Start

```powershell
git clone https://github.com/akyourowngames/A.N.K.I.T.A.git
cd A.N.K.I.T.A
python -m venv .venv
./.venv/Scripts/Activate.ps1
pip install -r requirements.txt
```

## Run Locally

```powershell
python main.py
```

## Desktop Frontend

```powershell
python jarvis_frontend.py
```

The PyQt5 frontend opens a JARVIS-style dashboard with chat, files, image generation status, terminal output, voice state, animated orb, and live telemetry. Assistant replies run in a background thread so the interface keeps animating while tools or model calls are working.

## Music Playback

A.N.K.I.T.A can route music requests like `play <song>`, `queue <track>`, `pause music`, `resume music`, `next song`, and `stop music` through the `music` tool. It uses `yt-dlp` for lookup and streams through the first available backend from `MUSIC_PLAYER_ORDER` (`mpv`, `ffplay`, `vlc`, then browser fallback by default).

For best audio-only playback, install `mpv` or `ffmpeg`/`ffplay` and keep `MUSIC_PLAYER=auto`. Use `MUSIC_PLAYER_COMMAND` only when you want a custom player command with `{url}`, `{stream_url}`, or `{title}` placeholders.

## Project Structure

```text
core/ or app/  application logic
tools/        integrations and utilities
requirements.txt  Python dependencies
README.md     project documentation
```

## Roadmap

- Add screenshots and architecture diagram
- Document each tool module with examples
- Add safer onboarding for secrets and local credentials
- Expand tests for assistant workflows and integrations

## Notes

- Keep API keys, OAuth credentials, local memory, and generated data out of public commits.

## Contributing

Contributions, ideas, and polish suggestions are welcome. Open an issue with a clear problem statement or create a focused pull request.

## Author

Built by [Krish](https://github.com/akyourowngames). If this project helped you or sparked an idea, consider starring the repo.
