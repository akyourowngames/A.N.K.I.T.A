# J.A.R.V.I.S - Just A Rather Very Intelligent System

An intelligent AI assistant built with FastAPI, LangChain, NVIDIA NIM, Tavily search, and a modern glass-morphism web UI. JARVIS provides three chat modes (Jarvis, General, Realtime), streaming responses, text-to-speech, voice input, and learns from your personal data files. Everything runs on one server with one command.

**Quick start:** `pip install -r requirements.txt` -> create `.env` with `NVIDIA_API_KEY` -> `python run.py` -> open http://localhost:8000

**Terminal chat:** `python cli.py` starts a separate streaming CLI without running the web server, TTS, or STT.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Features](#features)
- [How It Works (Full Workflow)](#how-it-works-full-workflow)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [Configuration](#configuration)
- [Technologies Used](#technologies-used)
- [Frontend Guide](#frontend-guide)
- [Troubleshooting](#troubleshooting)
- [Developer](#developer)

---

## Quick Start

### Prerequisites

- **Python 3.10+** with pip
- **OS**: Windows, macOS, or Linux
- **API Keys** (set in `.env` file):
  - `NVIDIA_API_KEY` (required) - Get from https://build.nvidia.com
  - `TAVILY_API_KEY` (optional, for Realtime mode) - Get from https://tavily.com

### Installation

1. **Clone or download** this repository.

2. **Install dependencies**:

```bash
pip install -r requirements.txt
```

3. **Create a `.env` file** in the project root:

```env
NVIDIA_API_KEY=your_nvidia_api_key_here
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=google/gemma-3n-e2b-it
NVIDIA_FAST_MODEL=meta/llama-3.1-8b-instruct
TAVILY_API_KEY=your_tavily_api_key_here

# Optional
ASSISTANT_NAME=Jarvis
JARVIS_USER_TITLE=Sir
TTS_VOICE=en-GB-RyanNeural
TTS_RATE=+22%
```

4. **Start the server**:

```bash
python run.py
```

5. **Open in browser**: http://localhost:8000

That's it. The server hosts both the API and the frontend on port 8000.

### Terminal CLI

Use the terminal client when you only want text chat and do not need the browser, TTS, or STT:

```bash
python cli.py
```

For a single streamed response:

```bash
python cli.py --once "hello jarvis"
```

Useful options:

- `--session cli` loads a persistent terminal session.
- `--activity` shows route and tool activity while the response streams.
- `--no-open-actions` prints action links instead of opening browser tabs.
- `--rebuild-index` rebuilds the vector index before starting.

---

## Features

### Chat Modes

- **General Mode**: Pure LLM responses using NVIDIA NIM. Uses your learning data and conversation history as context. No internet access.
- **Realtime Mode**: Searches the web via Tavily before answering. Smart query extraction converts messy conversational text into focused search queries. Uses fast search depth with AI-synthesized answers.
- **Jarvis Mode**: Unified route that auto-classifies each query. An NVIDIA-backed brain decides "general" or "realtime", then routes accordingly.

### Text-to-Speech (TTS)

- Server-side TTS using `edge-tts` (Microsoft Edge's free cloud TTS, no API key needed).
- Audio is generated on the server and streamed inline with text chunks via SSE.
- Sentences are detected in real time as text streams in, converted to speech in background threads (ThreadPoolExecutor), and sent to the client as base64 MP3.
- The client plays audio segments sequentially in a queue — speech starts as soon as the first sentence is ready, not after the full response.
- Works on all devices including iOS (uses a persistent `<audio>` element with AudioContext unlock).

### Voice Input

- Browser-native speech recognition (Web Speech API).
- Speak your question; it auto-sends when you stop (400ms delay to avoid mid-sentence sends).
- **Chrome**: Full support with continuous listening and interim results.
- **Safari/iOS**: Optimized with single-utterance mode; a one-time hint appears when first used. Works best in Chrome for full voice features.

### Learning System

- Put `.txt` files in `database/learning_data/` with any personal information, preferences, or context.
- Past conversations are saved as JSON in `database/chats_data/`.
- At startup, all learning data and past chats are chunked, embedded with NVIDIA NIM embeddings, and stored in a FAISS vector index.
- For each question, only the most relevant chunks are retrieved (semantic search) and sent to the LLM. This keeps token usage bounded no matter how much data you add.

### Session Persistence

- Conversations are saved to disk after each message and survive server restarts.
- General and Realtime modes share the same session, so context carries over between modes.

### NVIDIA Runtime

- Configure `NVIDIA_API_KEY`, `NVIDIA_BASE_URL`, `NVIDIA_MODEL`, and `NVIDIA_EMBEDDING_MODEL` in `.env`.
- The existing compatibility wrapper still uses Groq-shaped class names internally, but requests are sent to NVIDIA NIM when `NVIDIA_API_KEY` is present.
- `NVIDIA_FAST_MODEL` powers faster routing and realtime query extraction paths.
- `NVIDIA_EMBEDDING_MODEL` powers FAISS indexing and query retrieval through NVIDIA's OpenAI-compatible embeddings API.

### Frontend

- Dark glass-morphism UI with animated WebGL orb in the background.
- The orb animates when the AI is speaking (TTS playing) and stays subtle when idle.
- **Thinking audio**: Short starter phrases ("One moment please.", etc.) play while waiting for the first token.
- Responsive: works on desktop, tablets, and mobile (including iOS safe area handling).
- No build tools, no frameworks — vanilla HTML/CSS/JS.

---

## How It Works (Full Workflow)

This section explains the complete journey of a user's message from the moment they press Send to the moment they hear the AI speak.

### Step 1: User Sends a Message

The user types a question (or speaks it via voice input) and presses Send. The frontend (`script.js`) does the following:

1. Captures the text from the textarea.
2. Adds the user's message bubble to the chat UI.
3. Shows a typing indicator (three bouncing dots).
4. If TTS is enabled, unlocks the audio context (required on iOS for programmatic playback).
5. Sends a `POST` request to the backend with `{ message, session_id, tts }`.

The endpoint depends on the mode:
- **General**: `POST /chat/stream`
- **Realtime**: `POST /chat/realtime/stream`
- **Jarvis**: `POST /chat/jarvis/stream` (auto-routes to general or realtime)

### Step 2: Backend Receives the Request (app/main.py)

FastAPI validates the request body using the `ChatRequest` Pydantic model (checks message length 1-32,000 chars). The endpoint handler:

1. Gets or creates a session via `ChatService.get_or_create_session()`.
2. Calls `ChatService.process_message_stream()` (general) or `process_realtime_message_stream()` (realtime), which returns a chunk iterator.
3. Wraps the iterator in `_stream_generator()` and returns a `StreamingResponse` with `media_type="text/event-stream"`.

### Step 3: Session Management (app/services/chat_service.py)

`ChatService` manages all conversation state:

1. If no `session_id` is provided, generates a new UUID.
2. If a `session_id` is provided, checks in-memory first, then tries loading from disk (`database/chats_data/chat_{id}.json`).
3. Validates the session ID (no path traversal, max 255 chars).
4. Adds the user's message to the session's message list.
5. Formats conversation history into `(user, assistant)` pairs, capped at `MAX_CHAT_HISTORY_TURNS` (default 20) to keep the prompt within token limits.

### Step 4: Context Retrieval (app/services/vector_store.py)

Before generating a response, the system retrieves relevant context:

1. The user's question is embedded into a vector using the configured NVIDIA embedding model.
2. FAISS performs a nearest-neighbor search against the vector store (which contains chunks from learning data `.txt` files and past conversations).
3. The top 10 most similar chunks are returned.
4. These chunks are escaped (curly braces doubled for LangChain) and added to the system message.

# General chat compatibility wrapper backed by NVIDIA

For general chat:

1. `_build_prompt_and_messages()` assembles the system message:
   - Base personality prompt (from `config.py`)
   - Current date and time
   - Retrieved context chunks from the vector store
   - General mode addendum ("answer from your knowledge, no web search")
2. The prompt is sent to NVIDIA NIM through the compatibility service with streaming enabled.
3. Tokens arrive one by one and are yielded as an iterator.
4. If NVIDIA returns an error, the system reports the failure honestly instead of claiming the model answered.

# Realtime chat: query extraction + Tavily search + NVIDIA

For realtime chat, three additional steps happen before calling NVIDIA:

1. **Query Extraction**: A fast LLM call (with `max_tokens=50`, `temperature=0`) converts the user's raw conversational text into a clean search query. Example: "tell me about that website I mentioned" becomes "Jarvis for Everyone website". It uses the last 3 conversation turns to resolve references like "that", "him", "it".

2. **Tavily Web Search**: The clean query is sent to Tavily's advanced search API:
   - `search_depth="advanced"` for thorough results
   - `include_answer=True` so Tavily's AI synthesizes a direct answer
   - Up to 7 results with relevance scores

3. **Result Formatting**: Search results are structured with clear headers:
   - AI-synthesized answer (marked as primary source)
   - Individual sources with title, content, URL, and relevance score

4. These results are injected into the system message before the Realtime mode addendum (which explicitly instructs the LLM to USE the search data).

### Step 6: Streaming with Inline TTS (app/main.py - _stream_generator)

The `_stream_generator` function is the core of the streaming + TTS pipeline:

1. **Text chunks are yielded immediately** as SSE events (`data: {"chunk": "...", "done": false}`). The frontend displays them in real time — TTS never blocks text display.

2. If TTS is enabled, the generator also:
   a. Accumulates text in a buffer.
   b. Splits the buffer into sentences at punctuation boundaries (`. ! ? , ; :`).
   c. Merges short fragments to avoid choppy speech.
   d. Submits each sentence to a `ThreadPoolExecutor` (4 workers) for background TTS generation via `edge-tts`.
   e. Checks the front of the audio queue for completed TTS jobs and yields them as `data: {"audio": "<base64 MP3>"}` events — in order, without blocking.

3. When the LLM stream ends, any remaining buffered text is flushed and all pending TTS futures are awaited (with a 15-second timeout per sentence).

4. Final event: `data: {"chunk": "", "done": true, "session_id": "..."}`.

### Step 7: Frontend Receives the Stream (frontend/script.js)

The frontend reads the SSE stream with `fetch()` + `ReadableStream`:

1. **Text chunks** (`data.chunk`): Appended to the message bubble in real time. A blinking cursor appears during streaming.
2. **Audio events** (`data.audio`): Passed to `TTSPlayer.enqueue()`, which adds the base64 MP3 to a playback queue.
3. **Done event** (`data.done`): Streaming is complete. The cursor is removed.

### Step 8: TTS Playback (frontend/script.js - TTSPlayer)

The `TTSPlayer` manages audio playback:

1. `enqueue(base64Audio)` adds audio to the queue and starts `_playLoop()` if not already running.
2. `_playLoop()` plays segments sequentially: converts base64 to a data URL, sets it as the `<audio>` element's source, plays it, and waits for `onended` before playing the next segment.
3. When audio starts playing, the orb's `.speaking` class and WebGL animation are activated.
4. When all segments finish (or the user mutes TTS), the orb returns to its idle state.

### Step 9: Session Save (app/services/chat_service.py)

After the stream completes:

1. The full assistant response (accumulated from all chunks) is saved in the session.
2. The session is written to `database/chats_data/chat_{id}.json`.
3. During streaming, the session is also saved every 5 chunks for durability.

### Step 10: Next Startup

When the server restarts:

1. All `.txt` files in `database/learning_data/` are loaded.
2. All `.json` files in `database/chats_data/` (past conversations) are loaded.
3. Everything is chunked, embedded, and indexed in the FAISS vector store.
4. New conversations benefit from all previous context.

---

## Architecture

```
User (Browser)
    |
    |  HTTP POST (JSON) + SSE response stream
    v
+--------------------------------------------------+
|  FastAPI Application  (app/main.py)              |
|  - CORS middleware                               |
|  - Timing middleware (logs all requests)         |
|  - _stream_generator (SSE + inline TTS)          |
+--------------------------------------------------+
    |                           |
    v                           v
+------------------+   +------------------------+
|  ChatService     |   |  TTS Thread Pool       |
|  (chat_service)  |   |  (4 workers, edge-tts) |
|  - Sessions      |   +------------------------+
|  - History       |
|  - Disk I/O      |
+------------------+
    |
    v
+------------------+   +------------------------+
|  GroqService     |   |  RealtimeGroqService   |
|  (groq_service)  |   |  (realtime_service)    |
|  - General chat  |   |  - Query extraction    |
|  - Multi-key     |   |  - Tavily web search   |
|  - LangChain     |   |  - Extends GroqService |
+------------------+   +------------------------+
    |                           |
    v                           v
+--------------------------------------------------+
|  VectorStoreService  (vector_store.py)           |
|  - FAISS index (learning data + past chats)      |
|  - NVIDIA embeddings                             |
|  - Semantic search: returns top-k chunks         |
+--------------------------------------------------+
    |
    v
+--------------------------------------------------+
|  NVIDIA NIM API  (LLM + embeddings)              |
|  - Configured chat and embedding models          |
|  - Primary-first fallback through compatibility  |
+--------------------------------------------------+
```

---

## Project Structure

```
JARVIS/
├── frontend/                    # Web UI (vanilla HTML/CSS/JS, no build tools)
│   ├── index.html               # Single-page app structure
│   ├── style.css                # Dark glass-morphism theme, responsive
│   ├── script.js                # Chat logic, SSE streaming, TTS player, voice input
│   └── orb.js                   # WebGL animated orb renderer (GLSL shaders)
│
├── app/                         # Backend (FastAPI)
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, all endpoints, inline TTS, SSE streaming
│   ├── generate_thinking_audio.py # Generates starter_*.mp3 for "thinking" sound (runs at startup)
│   ├── models.py                # Pydantic models (ChatRequest, ChatResponse, etc.)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── chat_service.py      # Session management, message storage, disk persistence
│   │   ├── groq_service.py      # General chat compatibility wrapper backed by NVIDIA
│   │   ├── realtime_service.py  # Realtime chat: query extraction + Tavily search + NVIDIA
│   │   ├── brain_service.py     # Jarvis: NVIDIA classifier (general vs realtime)
│   │   └── vector_store.py      # FAISS vector index, embeddings, semantic retrieval
│   └── utils/
│       ├── key_rotation.py      # API key rotation (brain ≠ chat per request)
│       ├── __init__.py
│       ├── retry.py             # Retry with exponential backoff (for API calls)
│       └── time_info.py         # Current date/time for the system prompt
│
├── database/                    # Auto-created on first run
│   ├── learning_data/           # Your .txt files (personal info, preferences, etc.)
│   ├── chats_data/              # Saved conversations as JSON
│   └── vector_store/            # FAISS index files
│
├── config.py                    # All settings: API keys, paths, system prompt, TTS config
├── run.py                       # Web server entry point: python run.py
├── cli.py                       # Terminal chat entry point: python cli.py
├── requirements.txt             # Python dependencies
├── .env                         # Your API keys (not committed to git)
└── README.md                    # This file
```

---

## API Endpoints

### POST `/chat`
General chat (non-streaming). Returns full response at once.

### POST `/chat/stream`
General chat with streaming. Returns Server-Sent Events.

### POST `/chat/realtime`
Realtime chat (non-streaming). Searches the web first, then responds.

### POST `/chat/realtime/stream`
Realtime chat with streaming. Web search + SSE streaming.

### POST `/chat/jarvis/stream`
Jarvis mode: brain classifies query → routes to general or realtime. Streaming.

**Request body (all chat endpoints):**
```json
{
  "message": "What is Python?",
  "session_id": "optional-uuid",
  "tts": true
}
```
- `message` (required): 1-32,000 characters.
- `session_id` (optional): omit to create a new session; include to continue an existing one.
- `tts` (optional, default false): set to `true` to receive inline audio events in the stream.

**SSE stream format:**
```
data: {"session_id": "uuid-here", "chunk": "", "done": false}
data: {"chunk": "Hello", "done": false}
data: {"chunk": ", how", "done": false}
data: {"audio": "<base64 MP3>", "sentence": "Hello, how can I help?"}
data: {"chunk": "", "done": true, "session_id": "uuid-here"}
```

**Non-streaming response:**
```json
{
  "response": "Python is a high-level programming language...",
  "session_id": "uuid-here"
}
```

### GET `/chat/history/{session_id}`
Returns all messages for a session.

### GET `/health`
Health check. Returns status of all services.

### POST `/tts`
Standalone TTS endpoint. Send `{"text": "Hello"}`, receive streamed MP3 audio.

### GET `/`
Redirects to `/app/` (the frontend).

### GET `/api`
Returns list of available endpoints.

---

## Configuration

### Environment Variables (.env)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NVIDIA_API_KEY` | Yes | - | NVIDIA NIM API key |
| `NVIDIA_BASE_URL` | Yes | `https://integrate.api.nvidia.com/v1` | NVIDIA OpenAI-compatible API base URL |
| `NVIDIA_MODEL` | Yes | `nvidia/nemotron-3-nano-30b-a3b` | Main NVIDIA chat model |
| `NVIDIA_FAST_MODEL` | No | `nvidia/nemotron-mini-4b-instruct` | Routing and realtime query extraction model |
| `NVIDIA_EMBEDDING_MODEL` | Yes | `nvidia/nv-embedqa-e5-v5` | NVIDIA vector embedding model for FAISS retrieval |
| `NVIDIA_EMBEDDING_BATCH_SIZE` | No | `64` | Number of chunks to embed per NVIDIA request |
| `TAVILY_API_KEY` | No | - | Tavily search API key (for Realtime mode) |
| `ASSISTANT_NAME` | No | `Jarvis` | Assistant's name |
| `JARVIS_USER_TITLE` | No | - | How to address the user (e.g. "Sir") |
| `JARVIS_OWNER_NAME` | No | - | Owner's name (e.g. Shreshth); helps AI know who it serves |
| `TTS_VOICE` | No | `en-GB-RyanNeural` | Edge TTS voice (run `edge-tts --list-voices` to see all) |
| `TTS_RATE` | No | `+22%` | Speech speed adjustment |

### System Prompt

The assistant's personality is defined in `config.py`. Key sections:
- **Role**: conversational face of the system; does not claim to have completed actions unless the result is visible
- **Answering Quality**: instructed to be specific, use context/search results, never give vague answers
- **Tone**: warm, intelligent, concise, witty
- **Formatting**: no asterisks, no emojis, no markdown, plain text only

### Learning Data

Add `.txt` files to `database/learning_data/`:
- Files are loaded and indexed at startup.
- Only relevant chunks are sent to the LLM per question (not the full text).
- Restart the server after adding new files.

### NVIDIA Model Setup

Use NVIDIA NIM models for chat, routing, and vector retrieval:

```env
NVIDIA_API_KEY=your_nvidia_api_key_here
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=meta/llama-3.3-70b-instruct
NVIDIA_FAST_MODEL=meta/llama-3.3-70b-instruct
NVIDIA_EMBEDDING_MODEL=nvidia/nv-embedqa-e5-v5
NVIDIA_EMBEDDING_BATCH_SIZE=64
```

For QA/E5 embedding models, the vector layer sends document chunks as `passage` and user searches as `query`.

---

## Technologies Used

### Backend
| Technology | Purpose |
|-----------|---------|
| FastAPI | Web framework, async endpoints, SSE streaming |
| LangChain | LLM orchestration, prompt templates, message formatting |
| NVIDIA NIM | LLM inference and vector embeddings |
| Tavily | AI-optimized web search with answer synthesis |
| FAISS | Vector similarity search over NVIDIA embeddings |
| edge-tts | Server-side text-to-speech (Microsoft Edge, free, no API key) |
| Pydantic | Request/response validation |
| Uvicorn | ASGI server |

### Frontend
| Technology | Purpose |
|-----------|---------|
| Vanilla JS | Chat logic, SSE streaming, TTS playback queue |
| WebGL/GLSL | Animated orb (simplex noise, procedural lighting) |
| Web Speech API | Browser-native speech-to-text |
| CSS Glass-morphism | Dark translucent panels with backdrop blur |
| Poppins (Google Fonts) | Typography |

---

## Frontend Guide

### Modes

- **Jarvis** (default): Unified mode. The brain classifies each query and routes to General or Realtime automatically.
- **General**: Click "General" in the header. Uses the LLM's knowledge + your learning data. No internet.
- **Realtime**: Click "Realtime" in the header. Searches the web first, then answers with fresh information.

### TTS (Text-to-Speech)

- Click the speaker icon to enable/disable TTS.
- When enabled, the AI speaks its response as it streams in.
- Click again to mute mid-speech (stops immediately, orb returns to idle).

### Voice Input

- Click the microphone icon to start listening.
- Speak your question. It auto-sends when you finish.
- Click again to cancel.
- **Auto-listen mode**: Long-press the mic to enable; after each AI response, listening restarts automatically.

### Orb Animation

- **Idle**: Subtle glow (35% opacity), slowly rotating.
- **Speaking (TTS active)**: Full brightness, pulsing scale animation.
- The orb only animates when TTS audio is playing, not during text streaming.

### Quick Chips

On the welcome screen, click any chip ("What can you do?", "Open YouTube", etc.) to send a preset message.

---

## Troubleshooting

### Server won't start
- Ensure `NVIDIA_API_KEY` is set in `.env`.
- Run `pip install -r requirements.txt` to install all dependencies.
- Check that port 8000 is not in use.

### "Offline" status in the UI
- The server is not running. Start it with `python run.py`.
- Check the terminal for error messages.

### Realtime mode gives generic answers
- Ensure `TAVILY_API_KEY` is set in `.env` and is valid.
- Check the server logs for `[TAVILY]` entries to see if search is working.
- The query extraction LLM call should appear as `[REALTIME] Query extraction:` in logs.

### TTS not working
- Make sure TTS is enabled (speaker icon should be highlighted purple).
- On iOS: TTS requires a user interaction first (tap the speaker button before sending a message).
- Check server logs for `[TTS-INLINE]` errors.

### Vector store errors
- Delete `database/vector_store/` and restart — the index rebuilds automatically.
- Check that `database/` directories exist and are writable.

### Template variable errors
- Likely caused by `{` or `}` in learning data files. The system escapes these automatically, but if you see errors, check your `.txt` files.

---

## Performance

The server logs `[TIMING]` entries for every operation:

| Log Entry | What It Measures |
|-----------|-----------------|
| `session_get_or_create` | Session lookup (memory/disk/new) |
| `vector_db` | Vector store retrieval |
| `tavily_search` | Web search (Realtime only) |
| `nvidia_api` | Full NVIDIA API call |
| `first_chunk` | Time to first streaming token |
| `nvidia_stream_total` | Total stream duration + chunk count |
| `save_session_json` | Session save to disk |

Typical latencies:
- General mode first token: 0.3-1s
- Realtime mode first token: 2-5s (includes query extraction + web search)
- TTS first audio: ~1s after first sentence completes

---

## Error Handling & Stability

- **Rate limits**: NVIDIA rate limit errors are logged and surfaced without pretending the request succeeded.
- **TTS timeouts**: Each sentence has a 15s timeout; failures are logged and skipped without crashing the stream.
- **Vector store**: Malformed chat JSON files are skipped with a warning; startup continues.
- **Health check**: Returns `degraded` if any service fails; frontend shows "Offline" when unreachable.
- **Stream errors**: Exceptions in the SSE stream yield an `error` field so the client can display a message.

## Security Notes

- Session IDs are validated against path traversal (`..`, `/`, `\`).
- API keys are stored in `.env` (never in code).
- CORS allows all origins (`*`) since this is a single-user server.
- No authentication — add it if deploying for multiple users.

---

## Developer

**J.A.R.V.I.S** was developed by **Shreshth Kaushik**, an online educator, businessman, and programmer known for simplifying complex topics with innovative teaching methods.

- **Website:** [theshreshthkaushik.com](https://www.theshreshthkaushik.com/)
- **Instagram:** [@theshreshthkaushik](https://www.instagram.com/theshreshthkaushik/)
- **Telegram:** [t.me/theshreshthkaushik](https://t.me/theshreshthkaushik)
- **YouTube:** [Shreshth Kaushik](https://www.youtube.com/channel/UC7A5u12yVIZaCO_uXnNhc5g)
- **Jarvis for Everyone:** [jarvis4everyone.com](https://jarvis4everyone.com)

> For the latest version of Jarvis and updates, visit **[Jarvis for Everyone](https://jarvis4everyone.com)**.

**Start chatting:** `python run.py` then open http://localhost:8000
