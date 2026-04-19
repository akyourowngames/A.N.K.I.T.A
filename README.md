# JAKATA

Basic starting point for a personal AI assistant.

This first version does one thing well: it chats normally, keeps context, retries on failure, and falls back to another NVIDIA model instead of giving up immediately.

## Why these models

For a fast chat-first setup, the default stack is:

- `nvidia/llama-3.1-nemotron-nano-8b-v1`
- `nvidia/nemotron-mini-4b-instruct`
- `nvidia/llama-3.1-nemotron-nano-4b-v1_1`

These are all available through NVIDIA's OpenAI-compatible chat API and are better suited to low-latency interactive chat than the larger reasoning models.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Set `NVIDIA_API_KEY` in `.env`, then run:

```powershell
python main.py
```

## Current behavior

- normal multi-turn chat
- retry with exponential backoff
- fallback across multiple NVIDIA chat models
- persistent chat archives across runs
- permanent memory extraction into SQLite
- automatic loading of `.txt` knowledge files
- low-latency retrieval from prior chats, memories, and knowledge files
- model-driven tool use
- Tavily web search
- OpenWeather current weather lookup
- datetime lookup

## Memory layout

JAKATA now keeps memory in `data/`:

- `data/chats/` raw per-session chat logs
- `data/knowledge/` plain `.txt` files loaded on startup
- `data/memory/jakata.db` permanent extracted memory records

If you restart the app with the same session id, it continues from the same conversation and still retrieves relevant older chats plus saved knowledge text.

## Next phase

- self-correction loop
- task execution beyond simple chat
