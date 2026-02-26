# A.N.K.I.T.A — Content Generator Implementation Log

## Overview

This document records every detail of the **ContentAgent** feature that was
designed and implemented from scratch for A.N.K.I.T.A's multi-agent system.
The feature enables A.N.K.I.T.A to autonomously generate any type of written
content (reports, scripts, songs, pitch decks, emails, essays, poems, etc.)
and save the polished result directly to the user's Desktop — all hands-free.

---

## What Was Built (Full Feature List)

### 1. `tools/content_ops.py` — NEW FILE

The core content generation engine. Two public functions:

#### `write_and_save_content(workspace_root, topic, format_type, extra_context, output_dir)`

The single dynamic tool that handles all content generation.

**How it works:**
- Accepts `topic` (what the content is about), `format_type` (report / script /
  song / pitch deck / email / poem / paragraph / essay / summary / etc.), and
  optional `extra_context` (rough notes or extra instructions).
- Builds a format-aware system prompt:
  > *"You are an expert writer. Adapt your tone perfectly to the requested
  > format. If the format is a song, be creative and rhyme. If a technical
  > report, be precise..."*
- Builds a user prompt:
  > *"Write a {format_type} about: {topic}. Additional context: {extra_context}.
  > Produce only the final {format_type} — no meta-commentary, no preamble."*
- Calls the LLM via the existing `llm.call_chat_once()` with a generous
  `max_tokens=2048` budget (content generation needs more room than tool calls).
- Timestamps the output filename: `{topic}_{format_type}_{YYYYMMDD_HHMMSS}.txt`
- Saves the file to the user's Desktop (or a custom `output_dir` if provided).
- Returns a result dict with:
  - `ok` — True/False
  - `path` — absolute path to saved file
  - `bytes` — file size
  - `filename` — just the filename
  - `topic`, `format_type` — echoed back
  - `spoken_reply` — the exact string A.N.K.I.T.A speaks aloud via TTS:
    > *"Done! I've generated the {format_type} about {topic} and saved it to
    > your Desktop as {filename}."*

#### `detect_format_type(filename_stem, raw_text) -> (format_type, topic)`

Auto-detects the content format and topic from a dropped file's name and
optional contents. Used by the proactive watcher.

**Detection strategy (priority order):**

1. **Explicit directive in file's first line** — if the file starts with
   `format:`, `type:`, or `content type:`, that value is used as the format.
   Example: first line `format: essay` → `format_type = "essay"`.

2. **Filename keyword match** — scans the filename stem (with `_` and `-`
   replaced by spaces) against a list of 35+ known format keywords, ordered
   longest-first so multi-word formats win over single words:
   ```
   "pitch deck", "pitch script", "progress report", "status report",
   "cover letter", "press release", "product description", "executive summary",
   "short story", "blog post", "case study", "action plan", "lesson plan",
   "meeting notes", "research summary", "project proposal",
   "report", "script", "song", "poem", "essay", "email", "summary",
   "paragraph", "story", "pitch", "letter", "proposal", "plan",
   "outline", "review", "analysis", "description", "bio", "biography",
   "tweet", "caption", "tagline", "slogan", "advertisement", "ad"
   ```
   The format keyword is then stripped from the stem to extract the topic.

3. **Fallback** — if no keyword matches, `format_type = "content"` and the
   full filename stem becomes the topic.

**Examples:**
| Filename stem | First line | format_type | topic |
|---|---|---|---|
| `pitch_script_helper_id` | (empty) | `pitch script` | `helper id` |
| `progress_report_openclaw` | (empty) | `progress report` | `openclaw` |
| `funny_song_about_python` | (empty) | `song` | `funny about python` |
| `notes_on_ai_ethics` | `format: essay` | `essay` | `notes on ai ethics` |
| `cover_letter_google` | (empty) | `cover letter` | `google` |
| `random_notes` | (empty) | `content` | `random notes` |

---

### 2. `tools/engine.py` — MODIFIED

Two changes:

**a) Import added at the top:**
```python
from . import content_ops
```

**b) `write_content` tool spec added to `TOOL_SPECS`:**
```python
{
    "type": "function",
    "function": {
        "name": "write_content",
        "description": "Generate any type of text content using the LLM and save it to the Desktop...",
        "parameters": {
            "topic":        "What the content is about",
            "format_type":  "report / script / song / pitch deck / summary / etc.",
            "extra_context": "Optional rough notes or extra instructions",
            "output_dir":   "Optional save path — defaults to Desktop"
        }
    }
}
```

**c) Dispatcher case added to `_call()`:**
```python
if name == "write_content":
    return content_ops.write_and_save_content(
        workspace_root, topic, format_type, extra_context, output_dir
    )
```

---

### 3. `tools/__init__.py` — MODIFIED

Added `content_ops` import so it is accessible as a direct import from the
tools package:
```python
from . import content_ops
```

---

### 4. `agents/specialists.py` — MODIFIED

Four additions:

**a) Tool set:**
```python
_CONTENT_TOOLS = {"write_content", "read_file"}
```
The agent gets `write_content` (to generate and save) and `read_file` (to
optionally read the user's raw notes file before generating).

**b) System prompt:**
```python
_CONTENT_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Content Agent — an expert copywriter, analyst, "
    "and creative writer. Generate polished, complete text in any format: "
    "reports, scripts, songs, pitch decks, summaries, emails, essays, poems. "
    "Adapt your tone to the format. Always call write_content to generate and "
    "save the final piece. Speak the spoken_reply from write_content's result "
    "back to the user word-for-word."
)
```

**c) Instance created:**
```python
ContentAgent = SpecialistAgent("ContentAgent", _CONTENT_TOOLS, _CONTENT_SYSTEM_PROMPT)
```

**d) Registered in `SPECIALIST_MAP`:**
```python
SPECIALIST_MAP = {
    ...
    "ContentAgent": ContentAgent,
    ...
}
```

---

### 5. `agents/supervisor.py` — MODIFIED

Three changes so the Supervisor knows when to route to ContentAgent:

**a) ContentAgent added to the available agents list in the prompt:**
```
- ContentAgent: generate and save any text content — reports, scripts, songs,
  pitch decks, summaries, emails, essays, poems
```

**b) Rule 5 added:**
```
5. Use ContentAgent whenever the user asks to 'write', 'draft', 'create',
   or 'generate' a piece of text content.
```

**c) Three routing examples added:**
```
- "write a pitch script for Helper ID"              → ContentAgent
- "draft a progress report on the OpenClaw arch."  → ContentAgent
- "write a funny song about Python"                → ContentAgent
```

**d) `"ContentAgent"` added to the valid agent name set** in `route()` so it
is never stripped as an unknown agent name.

---

### 6. `proactive.py` — MODIFIED

Two additions:

**a) `raw_ideas` directory initialised in `__init__`:**
```python
self._raw_ideas_dir = workspace_root / ".ankita" / "raw_ideas"
self._raw_ideas_dir.mkdir(parents=True, exist_ok=True)
self._seen_raw_ideas: set = set()
```

**b) `_check_raw_ideas()` method added and wired into `_run()` loop:**

Watches `.ankita/raw_ideas/` for new `.txt`, `.md`, or `.text` files every
poll cycle (default 15 seconds).

When a new file is detected:
- Reads the file content (up to 2000 chars for the preview)
- Calls `detect_format_type(stem, raw_text)` to auto-detect format + topic
- Marks the file as seen (does NOT delete it — ContentAgent may need to re-read it)
- Pushes a `ProactiveEvent("content_request", ...)` with payload:
  ```python
  {
      "file_path":        "/full/path/to/file.txt",
      "file_name":        "file.txt",
      "topic":            "helper id",          # auto-detected
      "format_type":      "pitch script",       # auto-detected
      "raw_text":         "...first 2000 chars...",
      "suggested_prompt": "Write a pitch script about 'helper id'. Use these rough notes: ..."
  }
  ```
- The `message` field is human-readable:
  > *"📝 New idea file detected: 'pitch_script_helper_id.txt'. Generating a
  > pitch script about 'helper id' now."*

---

### 7. `chat.py` — MODIFIED (CLI interface)

The proactive event loop now handles `content_request` automatically:

```python
for event in proactive.get_pending_events():
    print(f"\n[ANKITA] {event.message}\n")

    if event.kind == "content_request":
        suggested_prompt = event.data.get("suggested_prompt", "")
        if suggested_prompt:
            # Run through Orchestrator (or AgentRuntime) on a fresh session
            content_reply = orchestrator.run(
                user_text=suggested_prompt,
                messages=new_session(),   # isolated — no chat history contamination
            )
            print(f"[ANKITA] {content_reply}\n")
            memory.add(session_id, "assistant", content_reply)
```

No user action required. ANKITA processes the file and prints the confirmation
while the user is still typing in the CLI.

---

### 8. `gui.py` — MODIFIED (GUI interface)

Two additions:

**a) `_ContentRequestWorker` QThread class added:**

A dedicated background thread that runs the Orchestrator call off the main
thread so the GUI never freezes during content generation (LLM calls can take
several seconds).

```python
class _ContentRequestWorker(QThread):
    done = pyqtSignal(str, str)  # (reply, error)

    def run(self):
        fresh_messages = new_session()   # isolated session
        reply = orchestrator.run(suggested_prompt, fresh_messages)
        self.done.emit(reply, "")
```

**b) `_on_proactive_tick()` upgraded to handle `content_request`:**

Full flow when a `content_request` event arrives in the GUI:

1. Appends the event message to chat (e.g. *"📝 Generating a pitch script..."*)
2. Checks if a content worker is already running — if so, shows a queue message
   and skips (prevents overlapping LLM calls)
3. Appends *"🖊️ Working on it in the background..."* to chat
4. Turns the status orb **orange** (thinking state)
5. Starts `_ContentRequestWorker` in background
6. On completion (`_on_content_done` callback):
   - Turns orb back to **cyan** (idle state)
   - Appends the full agent reply to chat
   - Saves the reply to vector memory
   - If `SARVAM_API_KEY` is set: calls `voice_web._sarvam_tts()` and plays the
     WAV audio in a **separate daemon thread** (never blocks the UI or the
     worker thread)
7. `self._content_worker` is stored on the window instance and initialised to
   `None` in `__init__`

---

## Full Proactive Flow (End-to-End)

```
User drops:  pitch_script_helper_id.txt  →  .ankita/raw_ideas/
                          │
                          ▼ (within 15 seconds)
          ProactiveEngine._check_raw_ideas()
                          │
                          ├─ detect_format_type("pitch script helper id", "")
                          │     → format="pitch script", topic="helper id"
                          │
                          └─ Pushes ProactiveEvent("content_request", ...)
                                        │
              ┌───────────────────────────────────────────┐
              │ GUI (_on_proactive_tick)                  │
              │                                           │
              │  Chat: "📝 Generating a pitch script..."  │
              │  Chat: "🖊️ Working on it..."              │
              │  Orb → ORANGE (thinking)                  │
              │                                           │
              │  _ContentRequestWorker (background)        │
              │    → Orchestrator → Supervisor             │
              │    → ContentAgent selected                 │
              │    → write_content tool called             │
              │       → LLM generates full pitch script    │
              │       → Saved to Desktop as               │
              │         helper_id_pitch_script_20260226... │
              │    → returns spoken_reply                  │
              │                                           │
              │  Orb → CYAN (idle)                        │
              │  Chat: "Done! I've generated the pitch    │
              │          script and saved it to Desktop." │
              │  Memory: reply stored in ChromaDB         │
              │  TTS: Sarvam speaks reply aloud           │
              └───────────────────────────────────────────┘
```

---

## Manual Trigger (Chat / Voice)

Besides the proactive file-drop flow, ContentAgent can also be triggered
directly by talking to ANKITA:

| What you say | What happens |
|---|---|
| *"Write a pitch script for Helper ID"* | Supervisor → ContentAgent → write_content → Desktop |
| *"Draft a 2-page report on OpenClaw architecture"* | ContentAgent → report saved |
| *"Write a funny song about Python"* | ContentAgent → song saved |
| *"Create a cover letter for a Google internship"* | ContentAgent → letter saved |
| *"Summarise my project in one paragraph"* | ContentAgent → paragraph saved |

The LLM extracts `topic` and `format_type` automatically from natural language.

---

---

## Telegram Bot Upgrade (Full Feature Parity with GUI/CLI)

### What Was Added to `telegram_bot.py`

The Telegram bridge was upgraded from a bare `AgentRuntime` wrapper to full
feature parity with `gui.py` and `chat.py`.

#### Multi-Agent Orchestrator
- Imported `Orchestrator` from `agents`
- Both `agent` (fallback) and `orchestrator` (default) instantiated
- `/agents on|off` command toggles `use_multi_agent` at runtime
- All user messages routed through `orchestrator.run()` when multi-agent is ON

#### Vector Memory (ChromaDB) — Per-Chat Sessions
- `MemoryStore` instantiated and shared across all Telegram chats
- Each chat scoped by `session_id = f"telegram-{chat_id}"`
- `memory.format_memory_context(text, n=4)` injected as system message before each reply
- Both user and assistant turns stored after each exchange
- `/memory` command shows the 5 most relevant recent memories for that chat

#### ProactiveEngine Integration
- `ProactiveEngine` started with `attach_memory(memory, "telegram-session")`
- `_flush_proactive_events()` helper runs every `TELEGRAM_PROACTIVE_CHECK_SEC` (default 15s)
- Events routed to `last_active_chat_id` (most recent chat) or first allowed chat
- **`dream_epiphany`** — epiphany pushed as `💭 <text>`, stored in memory
- **`content_request`** — ContentAgent runs synchronously, result pushed to chat
- **All other events** (system, cron, drop_file) — pushed as `⚙️ <message>`
- `proactive.set_last_interaction()` called on every user message to reset idle timer

#### Commands Added
| Command | Action |
|---|---|
| `/start` or `/help` | Show command list |
| `/reset` | Clear chat session history |
| `/memory` | Show 5 recent relevant ChromaDB memories |
| `/agents on` | Enable multi-agent Orchestrator mode |
| `/agents off` | Disable multi-agent, use bare AgentRuntime |

#### New Env Vars
| Variable | Default | Purpose |
|---|---|---|
| `TELEGRAM_PROACTIVE_CHECK_SEC` | `15` | How often to flush proactive events |
| `ANKITA_MULTI_AGENT` | `true` | Enable/disable multi-agent on startup |

---

## Files Changed / Created

| File | Status | What changed |
|---|---|---|
| `tools/content_ops.py` | ✅ NEW | `write_and_save_content` + `detect_format_type` |
| `tools/engine.py` | ✅ MODIFIED | Import, `write_content` tool spec, dispatcher case |
| `tools/__init__.py` | ✅ MODIFIED | `content_ops` import |
| `agents/specialists.py` | ✅ MODIFIED | `_CONTENT_TOOLS`, prompt, `ContentAgent` instance, `SPECIALIST_MAP` |
| `agents/supervisor.py` | ✅ MODIFIED | ContentAgent in prompt, rule 5, 3 routing examples, valid set |
| `proactive.py` | ✅ MODIFIED | `raw_ideas` dir init, `_check_raw_ideas()` method |
| `chat.py` | ✅ MODIFIED | `content_request` auto-handling in proactive event loop |
| `gui.py` | ✅ MODIFIED | `_ContentRequestWorker` class, full `content_request` + TTS flow |
