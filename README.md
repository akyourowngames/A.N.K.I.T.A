# ANKITA Chatbot

A simple AI chatbot that supports GitHub Copilot or OpenAI chat models with memory, tools, and persistent conversation context.

## Features

- 🔐 Secure OAuth device flow authentication
- 💬 Interactive chat interface
- 📝 Conversation history management
- 🔄 Token persistence (no need to re-authenticate)

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the chatbot:
```bash
python chatbot.py
```

3. Choose a provider:

   GitHub Copilot (default):
   - No extra env vars required
   - On first run, you'll be prompted to authenticate with GitHub device flow

   Codex CLI with ChatGPT sign-in:
   - Install the official `codex` CLI
   - Run `codex login` and choose `Sign in with ChatGPT`
   - Set `ANKITA_PROVIDER=codex_cli`
   - Optional: set `CODEX_MODEL=gpt-5.4`
   - Optional: set `CODEX_REASONING_EFFORT=xhigh`
   - For GUI-heavy browser automation on Windows, prefer `CODEX_SANDBOX=danger-full-access`
   - For long autonomous tasks, increase `CODEX_EXEC_TIMEOUT_SEC` (for example `600`)
   - For extension-backed browser automation, use the localhost bridge settings in `.env`

   OpenAI Codex / GPT:
   - Set `ANKITA_PROVIDER=openai`
   - Set `OPENAI_API_KEY=...`
   - Optional: set `OPENAI_MODEL=gpt-5.2-codex`
   - Optional: set `OPENAI_BASE_URL=https://api.openai.com/v1`

4. Run the chatbot:
```bash
python chatbot.py
```

## Usage

Simply type your messages and press Enter. The bot will respond using the configured provider.

### Commands

- `/clear` - Clear conversation history
- `/thinking [low|medium|high|xhigh]` - Show or set Codex thinking level
- `/quit` - Exit the chatbot
- `/help` - Show help message

## Requirements

- Python 3.7+
- GitHub account with Copilot access, or an OpenAI API key
- Internet connection

## How It Works

1. **Provider Setup**:
   - Copilot uses GitHub OAuth device flow
   - Codex CLI uses the official local `codex login` session
   - OpenAI uses `OPENAI_API_KEY`
2. **Chat**: Sends messages to the configured chat completions endpoint
3. **Persistence**:
   - Copilot tokens are saved locally in `~/.copilot_chat/token.json`
   - Codex CLI manages its own local auth state

## Notes

- Tokens are stored in `~/.copilot_chat/token.json`
- Default provider is GitHub Copilot with `gpt-4o`
- Codex CLI provider defaults to `gpt-5.4`
- OpenAI provider defaults to `gpt-5.2-codex`
- OpenAI docs currently present `gpt-5.4` and `gpt-5.3-codex` for Codex usage; set `CODEX_MODEL` or `OPENAI_MODEL` explicitly if you want a different model
- Codex CLI auth is separate from standard API-key auth; ANKITA reuses the local `codex` client instead of replaying the ChatGPT token directly against the API
- Phase 1 browser-extension bridge protocol is documented in `docs/browser_extension_protocol.md`
- The MV3 extension executor lives in `browser_extension/` and should be loaded unpacked in Chrome for bridge-backed browser automation
