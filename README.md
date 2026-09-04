# A.N.K.I.T.A - Personal AI Assistant

![GitHub last commit](https://img.shields.io/github/last-commit/akyourowngames/=flat-square)
![GitHub repo size](https://img.shields.io/github/repo-size/akyourowngames/=flat-square)
![GitHub stars](https://img.shields.io/github/stars/akyourowngames/=flat-square)
![Built with Python](https://img.shields.io/badge/built%20with-Python-111827?style=flat-square)

> A Python personal AI assistant with chat, CLI voice input, memory, Telegram, desktop tools, and project monitoring.

## Overview

A.N.K.I.T.A is built as a private operating assistant for daily workflows. It combines a terminal chat experience, speech input, persistent memory, tool modules, Telegram access, and a project daemon that can monitor activity and generate reports.

## Highlights

- Streaming terminal chat loop for fast assistant interactions
- Built-in CLI listening with SpeechRecognition microphone capture and NVIDIA Riva STT
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
- SpeechRecognition microphone capture with NVIDIA Riva speech-to-text
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

For built-in terminal listening:

```powershell
python main.py --listen
python main.py --listen-once
python main.py --list-mics
```

Inside the normal chat loop, use `/listen` for one spoken prompt or `/voice` for hands-free CLI listening.

## Language Behavior

The assistant can be configured for broad multilingual input and English replies:

```env
ASSISTANT_INPUT_LANGUAGES=Any
ASSISTANT_OUTPUT_LANGUAGE=English
STT_PROVIDER=nvidia
STT_NVIDIA_LANGUAGE_CODE=en-US
STT_NVIDIA_LANGUAGE_CODES=en-US
STT_WEB_LANGUAGE_CODES=en-US
STT_WEB_FALLBACK=false
STT_LISTEN_TIMEOUT_SECONDS=3
STT_PHRASE_TIME_LIMIT_SECONDS=6
STT_PAUSE_THRESHOLD=0.35
TTS_NVIDIA_LANGUAGE_CODE=en-US
TTS_VOICE_EFFECT=heavy
```

`STT_NVIDIA_LANGUAGE_CODES` keeps the normal voice path English-only. The web fallback is disabled here to avoid an extra transcription path.

## Telegram Bridge

```powershell
python telegram_bot.py
```

Telegram now supports practical remote desktop actions through normal chat:

- `show desktop files`, `recent files in downloads`, `find invoice in documents`
- `send 1`, `send desktop.ini`, `send the second one`
- `read it`, `show details for that file`, `what can you browse`
- all normal Brain tools still route through Telegram: web search, weather, calendar, Gmail, music, image generation, terminal-backed work, and system controls
- web search uses Tavily when configured and falls back to a free HTML search path when `TAVILY_FREE_FALLBACK=true`
- incoming documents/photos are saved under the Telegram download folder
- folders are zipped automatically before upload
- voice notes, audio files, and video notes are transcribed locally with `faster-whisper`

The free local transcription path uses `faster-whisper` with language auto-detection by default:

```env
TELEGRAM_AUDIO_TRANSCRIPTION=true
TELEGRAM_WHISPER_MODEL=base
TELEGRAM_WHISPER_DEVICE=auto
TELEGRAM_WHISPER_COMPUTE_TYPE=int8
TELEGRAM_WHISPER_LANGUAGE=
TELEGRAM_WHISPER_TASK=transcribe
HF_HUB_DISABLE_SYMLINKS_WARNING=1
HF_HUB_VERBOSITY=error
```

Use a larger multilingual model such as `small` or `medium` for better accuracy, or raise `TELEGRAM_WHISPER_BATCH_SIZE` on a capable GPU for faster batched transcription.

## Desktop Frontend

```powershell
python jarvis_frontend.py
```

The PyQt5 frontend opens a minimal JARVIS-style chat dashboard with the animated orb. Assistant replies run in a background thread so the interface keeps animating while tools or model calls are working.
Use `MIC` for one spoken prompt, or `LOOP` for hands-free listening that rearms after each spoken reply finishes.

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
