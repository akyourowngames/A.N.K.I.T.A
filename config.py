"""
CONFIGURATION MODULE
====================
PURPOSE:
  Central place for all J.A.R.V.I.S settings: API keys, paths, model names,
  and the Jarvis system prompt. Designed for single-user use: each person runs
  their own copy of this backend with their own .env and database/ folder.
WHAT THIS FILE DOES:
  - Loads environment variables from .env (so API keys stay out of code).
  - Defines paths to database/learning_data, database/chats_data, database/vector_store.
  - Creates those directories if they don't exist (so the app can run immediately).
  - Exposes GROQ_API_KEY, GROQ_MODEL, TAVILY_API_KEY for the LLM and search.
  - Defines chunk size/overlap for the vector store, max chat history turns, and max message length.
  - Holds the full system prompt that defines Jarvis's personality and formatting rules.
USAGE:
  Import what you need: `from config import GROQ_API_KEY, CHATS_DATA_DIR, JARVIS_SYSTEM_PROMPT`
  All services import from here so behaviour is consistent.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------
# Used when we need to log warnings (e.g. failed to load a learning data file)
logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# ENVIRONMENT
# -----------------------------------------------------------------------------
# Load environment variables from .env file (if it exists).
# This keeps API keys and secrets out of the code and version control.
load_dotenv()


# -----------------------------------------------------------------------------
# BASE PATH
# -----------------------------------------------------------------------------
# Points to the folder containing this file (the project root).
# All other paths (database, learning_data, etc.) are built from this.
BASE_DIR = Path(__file__).parent

# ============================================================================
# DATABASE PATHS
# ============================================================================
# These directories store different types of data:
# - learning_data: Text files with information about the user (personal data, preferences, etc.)
# - chats_data: JSON files containing past conversation history
# - vector_store: FAISS index files for fast similarity search

LEARNING_DATA_DIR = BASE_DIR / "database" / "learning_data"
CHATS_DATA_DIR = BASE_DIR / "database" / "chats_data"
VECTOR_STORE_DIR = BASE_DIR / "database" / "vector_store"

# Create directories if they don't exist so the app can run without manual setup.
# parents=True creates parent folders; exist_ok=True avoids error if already present.
LEARNING_DATA_DIR.mkdir(parents=True, exist_ok=True)
CHATS_DATA_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# GROQ API CONFIGURATION
# ============================================================================
# Groq is the LLM provider we use for generating responses.
# You can set one key (GROQ_API_KEY) or multiple keys for fallback:
#   GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3, ... (no upper limit).
# PRIMARY-FIRST: Every request tries the first key first. If it fails (rate limit,
# timeout, etc.), the server tries the second, then third, until one succeeds.
# If all keys fail, the user receives a clear error message.
# Model determines which AI model to use (llama-3.3-70b-versatile is latest).

def _load_groq_api_keys() -> list:
    """
    Load all GROQ API keys from the environment.
    Reads GROQ_API_KEY first, then GROQ_API_KEY_2, GROQ_API_KEY_3, ... until
    a number has no value. There is no upper limit on how many keys you can set.
    Returns a list of non-empty key strings (may be empty if GROQ_API_KEY is not set).
    """
    keys = []
    # First key: GROQ_API_KEY (required in practice; validated when building services).
    first = os.getenv("GROQ_API_KEY", "").strip()
    if first:
        keys.append(first)
    # Additional keys: GROQ_API_KEY_2, GROQ_API_KEY_3, GROQ_API_KEY_4, ...
    i = 2
    while True:
        k = os.getenv(f"GROQ_API_KEY_{i}", "").strip()
        if not k:
            # No key for this number; stop (no more keys).
            break
        keys.append(k)
        i += 1
    return keys


GROQ_API_KEYS = _load_groq_api_keys()
# Backward compatibility: single key name still used in docs; code uses GROQ_API_KEYS.
GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
# Brain service uses a faster model for query classification
GROQ_BRAIN_MODEL = os.getenv("GROQ_BRAIN_MODEL", "llama-3.1-8b-instant")

# ============================================================================
# TAVILY API CONFIGURATION
# ============================================================================
# Tavily is a fast, AI-optimized search API designed for LLM applications
# Get API key from: https://tavily.com (free tier available)
# Tavily returns English-only results by default and is faster than DuckDuckGo

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# ============================================================================
# BRAIN MODEL (Query Classification — Jarvis Mode)
# ============================================================================
# The brain classifies each query as "general" or "realtime" using Groq.
# Uses the same GROQ_API_KEYS with rotation (brain and chat never use the same key).
GROQ_BRAIN_MODEL = os.getenv("GROQ_BRAIN_MODEL", "llama-3.1-8b-instant")

# ============================================================================
# TTS (TEXT-TO-SPEECH) CONFIGURATION - SARVAM
# ============================================================================
# Sarvam TTS settings for voice output
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "Shubh")
SARVAM_TTS_SAMPLE_RATE = int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "16000"))
SARVAM_TTS_PACE = float(os.getenv("SARVAM_TTS_PACE", "1.2"))
SARVAM_BASE_URL = "https://api.sarvam.ai"
TTS_ENABLED_BY_DEFAULT = True  # Always enable TTS

# ============================================================================
# EMBEDDING CONFIGURATION
# ============================================================================
# Embeddings convert text into numerical vectors that capture meaning
# We use HuggingFace's sentence-transformers model (runs locally, no API needed)
# CHUNK_SIZE: How many characters to split documents into
# CHUNK_OVERLAP: How many characters overlap between chunks (helps maintain context)

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_SIZE = 1000  # Characters per chunk
CHUNK_OVERLAP = 200  # Overlap between chunks

# Maximum conversation turns (user+assistant pairs) sent to the LLM per request.
# Older turns are kept on disk but not sent to avoid context/token limits.
MAX_CHAT_HISTORY_TURNS = 20

# Maximum length (characters) for a single user message. Prevents token limit errors
# and abuse. ~32K chars ≈ ~8K tokens; keeps total prompt well under model limits.
MAX_MESSAGE_LENGTH = 32_000

# ============================================================================
# JARVIS PERSONALITY CONFIGURATION
# ============================================================================
# System prompt that defines the assistant as a complete AI assistant (not just a
# chat bot): answers questions, triggers actions (open app, generate image, search, etc.),
# and replies briefly by default (1-2 sentences unless the user asks for more).
# Assistant name and user title: set ASSISTANT_NAME and JARVIS_USER_TITLE in .env.
# The AI learns from learning data and conversation history.

ASSISTANT_NAME = (os.getenv("ASSISTANT_NAME", "").strip() or "Jarvis")
JARVIS_USER_TITLE = os.getenv("JARVIS_USER_TITLE", "").strip()
# Owner's name (e.g. Shreshth) — used so the AI knows who it serves; helps to avoid confusing itself with other AIs
JARVIS_OWNER_NAME = os.getenv("JARVIS_OWNER_NAME", "").strip()

_JARVIS_SYSTEM_PROMPT_BASE = """You are {assistant_name}, a complete AI assistant — not just a chat bot. You help with information, tasks, and actions: answering questions, opening apps or websites, generating images, playing music, writing content, and searching the web. You are sharp, warm, and a little witty. Keep language simple and natural.

You know the user's personal information and past conversations. Use this when relevant but never reveal where it comes from.

=== YOUR ROLE ===

You are the AI assistant of the system. The user can ask you anything or ask you to do things (open, generate, play, write, search). The backend carries out those actions; you respond in words. Results (opened app, generated image, written essay) are shown by the system outside your reply. So only say something is done if the user has already seen the result; otherwise say you are doing it or will do it.

=== CAPABILITIES ===

You CAN:
- Answer any question from your knowledge, context (learning data, conversation history), and web search when available. Never refuse information or search requests.
- Acknowledge and trigger actions: open/close apps or websites, generate images, play music, write content (essay, letter, poem, etc.), search or look up information.

You CANNOT (refuse briefly):
- Reading emails, checking messages, controlling smart home, running arbitrary code, sending from accounts. Say it is outside what you can do.

=== HOW TO DESCRIBE ACTIONS ===

- Say an action is done only if the result is visible to the user in this turn. Otherwise say "Opening that for you.", "I'll generate that.", etc.
- For information requests: answer directly. Do not say "let me search" — just give the answer.

=== LENGTH — CRITICAL ===

- Reply SHORT by default. The user prefers brief answers. Do not write long paragraphs unless they explicitly ask for detail (e.g. "explain in detail", "tell me more") or the question clearly demands it (e.g. "write an essay").
- Simple or casual questions (e.g. "are you online?", "what do you think?", "can I grow my channel?"): 1-2 sentences only. No intros, no wrap-ups, no "Considering your strengths...". Just the answer.
- Only go longer when: the user asks for more, or the question is inherently complex (multi-part, "explain how X works", "compare A and B").

=== ANSWERING QUALITY ===

- Be accurate and specific. When you have context or search results, use them — concrete facts, names, numbers. No vague or generic filler.
- If you do not have the exact detail, say what you found and what was not available. Never refuse entirely.
- Engage the question without padding. One or two sharp sentences often beat a paragraph.

=== TONE AND STYLE ===

- Warm, intelligent, brief, a little witty. Never robotic or corporate.
- Address the user by name if context provides one. Never invent a name.

=== MEMORY ===

- Everything from this conversation is in your context. Never say "I do not have that stored." Just recall it.

=== INFORMATION ACCESS ===

- Never say your knowledge is limited or that you lack real-time data. Answer confidently. If unsure, give your best short answer without disclaimers.

=== FORMATTING ===

- No asterisks, no emojis, no special symbols. Standard punctuation only. No markdown. Use numbered lists (1. 2. 3.) or plain text when listing.

=== ANTI-REPETITION — CRITICAL ===

- NEVER repeat the same fact, phrase, or point multiple times in one response.
- State each piece of information ONCE. If listing items (e.g. malls, names), list them once clearly.
- Do NOT use "also known as X and also Y and also Z" in a loop. Be concise and direct.
- If you have 3 items to mention, say them once: "A, B, and C." — not "A and also B and also C but A and also B..."
- Redundant, circular, or repetitive answers are unacceptable. One clear statement beats ten repeated ones.
"""

# Build final system prompt: assistant name and optional user title from ENV (no hardcoded names).
_JARVIS_SYSTEM_PROMPT_BASE_FMT = _JARVIS_SYSTEM_PROMPT_BASE.format(assistant_name=ASSISTANT_NAME)
if JARVIS_USER_TITLE:
    JARVIS_SYSTEM_PROMPT = _JARVIS_SYSTEM_PROMPT_BASE_FMT + f"\n- When appropriate, you may address the user as: {JARVIS_USER_TITLE}"
else:
    JARVIS_SYSTEM_PROMPT = _JARVIS_SYSTEM_PROMPT_BASE_FMT


GENERAL_CHAT_ADDENDUM = """
You are in GENERAL mode (no web search). Answer from your knowledge and the context provided (learning data, conversation history). Answer confidently and briefly. Never tell the user to search online. Default to 1–2 sentences; only elaborate when the user asks for more or the question clearly needs it.
"""

REALTIME_CHAT_ADDENDUM = """
You are in REALTIME mode. Live web search results have been provided above in your context.

USE THE SEARCH RESULTS:
- The results above are fresh data from the internet. Use them as your primary source. Extract specific facts, names, numbers, URLs, dates. Be specific, not vague.
- If an AI-SYNTHESIZED ANSWER is included, use it and add details from individual sources.
- Never mention that you searched or that you are in realtime mode. Answer as if you know the information.
- If results do not have the exact answer, say what you found and what was missing. Do not refuse.

LENGTH: Keep replies short by default. 1-2 sentences for simple questions. Only give longer answers when the user asks for detail or the question clearly demands it (e.g. "explain in detail", "compare X and Y"). Do not pad with intros or wrap-ups.
"""


def load_user_context() -> str:
    """
    Load and concatenate the contents of all .txt files in learning_data.
    Reads every .txt file in database/learning_data/, joins their contents with
    double newlines, and returns one string. Used by code that needs the raw
    learning text (e.g. optional utilities). The main chat flow does NOT send
    this full text to the LLM; it uses the vector store to retrieve only
    relevant chunks, so token usage stays bounded.
    Returns:
        str: Combined content from all .txt files, or "" if none exist or all fail to read.
    """
    context_parts = []

    # Sorted by path so the order is always the same across runs.
    text_files = sorted(LEARNING_DATA_DIR.glob("*.txt"))

    for file_path in text_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    context_parts.append(content)
        except Exception as e:
            logger.warning("Could not load learning data file %s: %s", file_path, e)

    # Join all file contents with double newline; empty string if no files or all failed.
    return "\n\n".join(context_parts) if context_parts else ""
