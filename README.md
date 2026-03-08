# GitHub Copilot Chatbot

A simple AI chatbot that uses GitHub Copilot's GPT-4 model via OAuth device authentication.

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

3. On first run, you'll be prompted to authenticate:
   - A code will be displayed
   - Browser will open to GitHub
   - Enter the code to authorize
   - Return to terminal and start chatting!

## Usage

Simply type your messages and press Enter. The bot will respond using GitHub Copilot's AI.

### Commands

- `/clear` - Clear conversation history
- `/quit` - Exit the chatbot
- `/help` - Show help message

## Requirements

- Python 3.7+
- GitHub account with Copilot access (paid subscription)
- Internet connection

## How It Works

1. **Authentication**: Uses GitHub's OAuth device flow to get an access token
2. **API Access**: Exchanges the token for Copilot API credentials
3. **Chat**: Sends messages to `api.githubcopilot.com/chat/completions`
4. **Persistence**: Saves tokens locally in `~/.copilot_chat/token.json`

## Notes

- Tokens are stored in `~/.copilot_chat/token.json`
- You need an active GitHub Copilot subscription
- The chatbot uses GPT-4 model by default
