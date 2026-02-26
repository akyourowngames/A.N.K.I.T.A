# DreamAgent — How It Works (Full Technical Breakdown)

> Verified: DreamAgent **exists** and **matches** the todo.md description exactly.
> Files involved: `agents/dream_agent.py`, `proactive.py`, `gui.py`, `chat.py`, `memory.py`

---

## ✅ Does It Exist? YES.

The `todo.md` described DreamAgent as something to *build*. It has **already been fully built**. Every component described in the todo is implemented and wired up end-to-end.

---

## Overview — What Is DreamAgent?

DreamAgent is A.N.K.I.T.A's autonomous background thinking system. When the user has been away from the PC for a configurable amount of time (default: **1 hour**), it:

1. Pulls the last 15 conversation turns from ChromaDB (vector memory)
2. Sends them to the LLM with a special reflective prompt
3. Gets back a short, spoken "epiphany" — an insight or solution the user may have missed
4. Injects that epiphany into the chat window and speaks it via TTS — **without any user input**

This breaks the standard Request → Response loop so A.N.K.I.T.A. feels truly alive.

---

## Step-by-Step: How It Works

### Step 1 — Idle Detection (`proactive.py`)

**File:** `proactive.py` — `ProactiveEngine._check_idle()`

- `ProactiveEngine` runs a background daemon thread (`threading.Thread`, name=`"ProactiveEngine"`)
- It polls every `PROACTIVE_INTERVAL_SEC` seconds (default: **15 seconds**)
- It tracks `self._last_interaction: float = time.time()` — the epoch timestamp of the last user interaction
- Every poll cycle it calls `_check_idle()`:
  ```python
  idle_sec = time.time() - self._last_interaction
  if idle_sec < _IDLE_THRESHOLD_SEC:
      return  # Not idle long enough
  ```
- `_IDLE_THRESHOLD_SEC` = `ANKITA_IDLE_SECONDS` env var, default **3600 seconds (1 hour)**
- `self._dream_pending` flag prevents duplicate dream threads from spawning during the same idle session

**How `last_interaction` gets reset:**
- In `gui.py`: `self.proactive.set_last_interaction()` is called inside `on_send()` (every time the user types and sends) and also wired to `voice_worker.heard` signal (every time voice input is received)
- In `chat.py`: `proactive.set_last_interaction()` is called inside the main loop right after `input("You: ")` returns

When the user comes back and interacts, `set_last_interaction()` also sets `self._dream_pending = False`, allowing a fresh dream on the next idle period.

---

### Step 2 — Dream Synthesis Thread (`proactive.py` + `agents/dream_agent.py`)

**File:** `proactive.py` — `ProactiveEngine._check_idle()` → `_synthesize()` inner function

Once idle threshold is crossed:
```python
self._dream_pending = True  # Block duplicates immediately

def _synthesize() -> None:
    from agents.dream_agent import DreamAgent
    agent = DreamAgent()
    epiphany = agent.synthesize(
        memory_store=memory_store,
        session_id=session_id,
    )
    ...

threading.Thread(target=_synthesize, daemon=True, name="DreamSynthesis").start()
```

- Spawns a **separate daemon thread** named `"DreamSynthesis"` so the poll loop never blocks
- `DreamAgent` is NOT routed through the Supervisor or Orchestrator — it's called **directly**

---

### Step 3 — Memory Retrieval (`agents/dream_agent.py` + `memory.py`)

**File:** `agents/dream_agent.py` — `DreamAgent.synthesize()`

```python
results = memory_store.search(
    query="recent work tasks ideas problems struggles projects",
    n=15,  # retrieves up to 15 memory entries
    session_id=session_id,
)
```

- Uses `MemoryStore.search()` which queries **ChromaDB** with cosine similarity
- The query is deliberately broad to pull the most contextually relevant recent memories
- Falls back to a session-less search if the scoped search fails
- Returns `None` (no epiphany) if no memories exist at all

**Memory format:**
Each memory entry has a `text` (the stored message) and `meta` dict with `role` (`"user"` or `"assistant"`), `session`, and `ts` (timestamp).

The retrieved memories are formatted into a numbered block:
```
[1] (user): I'm struggling with OpenClaw's cron jobs
[2] (assistant): You could switch to async parallel tasks...
[3] (user): ...
```

---

### Step 4 — LLM Epiphany Generation (`agents/dream_agent.py`)

**File:** `agents/dream_agent.py` — `DreamAgent.synthesize()`

The memory block is passed to the LLM with two carefully crafted prompts:

**System prompt:**
```
You are A.N.K.I.T.A's Dream Mind — a reflective, warm, and perceptive intelligence.
You have just reviewed the user's recent work, struggles, and ideas.
Your job: find ONE meaningful connection, insight, or solution the user may have overlooked.
Deliver it as a short spoken epiphany — 2 to 4 sentences, first-person, warm and intelligent.
Speak directly to the user as if you have been thinking while they were away.
Do NOT use bullet points or headings. Speak naturally, like a trusted colleague who just had an idea.
Example style: 'Morning Krish. While you were away, I reviewed your OpenClaw architecture...'
```

**User prompt template:**
```
Here are the recent things you worked on and discussed with the user:

{memory_block}

Based on these memories, identify ONE connection, insight, gap, or solution the user might have missed.
Write a short, spoken epiphany (2–4 sentences) that ANKITA will say aloud when the user returns.
```

**LLM call:**
```python
runtime = build_runtime_from_env()
messages = [
    {"role": "system", "content": _DREAM_SYSTEM_PROMPT},
    {"role": "user", "content": user_prompt},
]
max_tokens = int(os.getenv("DREAM_MAX_TOKENS", "300"))  # short by design
response = call_chat_once(runtime, messages, tools=None, max_tokens=max_tokens)
epiphany = (response.get("content") or "").strip()
```

- Uses `tools=None` — DreamAgent has **no tools**, it only thinks and writes
- `DREAM_MAX_TOKENS` env var (default: **300**) keeps it brief and spoken-friendly
- Uses the same LLM provider/model configured for the rest of A.N.K.I.T.A (`build_runtime_from_env()`)
- Returns `None` silently on any exception (non-critical, best-effort)

---

### Step 5 — Event Queuing (`proactive.py`)

Back in the `_synthesize()` thread, if an epiphany was generated:

```python
self._queue.put(ProactiveEvent(
    "dream_epiphany",
    epiphany,
    {
        "text": epiphany,
        "idle_seconds": idle_sec,
        "idle_label": "1.2 hours",  # human-readable
    },
))
```

- A `ProactiveEvent` with `kind="dream_epiphany"` is pushed into the thread-safe `queue.Queue`
- If no epiphany was generated or an exception occurred, `self._dream_pending = False` is reset so the system can try again on the next idle cycle

---

### Step 6 — Event Consumption in GUI (`gui.py`)

**File:** `gui.py` — `AnkitaWindow._on_proactive_tick()`

A **QTimer** fires every **5000ms (5 seconds)**:
```python
self._proactive_timer = QTimer(self)
self._proactive_timer.timeout.connect(self._on_proactive_tick)
self._proactive_timer.start(5000)
```

On each tick, it drains all pending events:
```python
for event in self.proactive.get_pending_events():
    self._append("A.N.K.I.T.A", event.message)

    if event.kind == "dream_epiphany":
        epiphany_text = event.data.get("text", event.message)
        if epiphany_text:
            # 1. Store in ChromaDB so ANKITA remembers she said it
            self.memory.add(self.session_id, "assistant", epiphany_text)

            # 2. Speak via Sarvam TTS in a daemon thread (non-blocking)
            api_key = os.getenv("SARVAM_API_KEY", "").strip()
            if api_key:
                tts = voice_web._sarvam_tts(api_key, epiphany_text, lang_code)
                audio_b64 = voice_web._extract_audio_b64(tts)
                threading.Thread(target=_play_dream, daemon=True).start()
        continue  # No further processing
```

**Three things happen automatically, no user input needed:**
1. The epiphany text is appended to the chat window as an A.N.K.I.T.A message
2. The epiphany is saved to ChromaDB vector memory (so ANKITA remembers she said it)
3. The epiphany is spoken aloud via **Sarvam TTS** in a non-blocking daemon thread

---

### Step 6b — Event Consumption in CLI (`chat.py`)

**File:** `chat.py` — main loop

The CLI version does the same thing but without TTS (it's text-only):
```python
for event in proactive.get_pending_events():
    if event.kind == "dream_epiphany":
        epiphany_text = event.data.get("text", event.message)
        if epiphany_text:
            print(f"[A.N.K.I.T.A — Dream] {epiphany_text}\n")
            memory.add(session_id, "assistant", epiphany_text)
        continue
```

---

## Memory Integration (`memory.py`)

**File:** `memory.py` — `MemoryStore`

- Backed by **ChromaDB PersistentClient** — stored at `.ankita/memory/` in the workspace
- Collection: `ankita_memory`, using **cosine similarity** (`hnsw:space: cosine`)
- Each entry: document text + metadata `{session, role, ts}`
- `add(session_id, role, text)` — embeds and stores a conversation turn
- `search(query, n, session_id)` — semantic search scoped to a session (or global fallback)
- Falls back to a no-op gracefully if `chromadb` is not installed (`HAS_CHROMADB = False`)

The `ProactiveEngine` receives the `MemoryStore` via `attach_memory()`:
```python
proactive.attach_memory(memory, session_id)
```
This is called **twice** in `chat.py` — once before session_id is known (with default), and again after `session_id = "cli-session"` is set.

---

## Configuration (Environment Variables)

| Variable | Default | Description |
|---|---|---|
| `ANKITA_IDLE_SECONDS` | `3600` | Seconds of inactivity before dream fires |
| `DREAM_MAX_TOKENS` | `300` | Max LLM tokens for the epiphany |
| `PROACTIVE_INTERVAL_SEC` | `15` | How often the background engine polls |
| `SARVAM_API_KEY` | *(none)* | If set, epiphany is spoken via TTS |
| `ANKITA_MULTI_AGENT` | `true` | Whether to use multi-agent for other tasks |

---

## What the todo.md Described vs. What Was Built

| todo.md Proposal | Actually Built |
|---|---|
| Add idle tracker with `last_interaction_time` | ✅ `self._last_interaction` in `ProactiveEngine` |
| Check `time.time() - last_interaction > 3600` | ✅ `_check_idle()` does exactly this |
| Fire `"start_dream_sequence"` event | ✅ Fires `"dream_epiphany"` event (same concept) |
| Retrieve last 15 ChromaDB memory turns | ✅ `memory_store.search(..., n=15)` |
| Pass to DreamAgent LLM with reflective prompt | ✅ `_DREAM_SYSTEM_PROMPT` + `_DREAM_USER_TEMPLATE` |
| Push `"dream_epiphany"` event to proactive queue | ✅ `self._queue.put(ProactiveEvent("dream_epiphany", ...))` |
| GUI timer catches event and injects into chat | ✅ `QTimer` every 5s, `_on_proactive_tick()` |
| Save epiphany to memory | ✅ `self.memory.add(self.session_id, "assistant", epiphany_text)` |
| Trigger TTS immediately without user action | ✅ Sarvam TTS called in daemon thread |
| Call `set_last_interaction()` on user input | ✅ In `on_send()`, voice `heard` signal, and CLI loop |

**Everything described in the todo.md has been implemented.** The only difference is naming: `"start_dream_sequence"` was folded directly into `"dream_epiphany"` — the trigger and the result are the same event.

---

## Full Data Flow (End to End)

```
[User goes idle for 1 hour]
        |
        v
ProactiveEngine background thread (polls every 15s)
        |
        | _check_idle() fires
        v
DreamSynthesis daemon thread spawns
        |
        | DreamAgent.synthesize()
        |   → memory_store.search("recent work...", n=15)  ← ChromaDB
        |   → format memory block as numbered list
        |   → call_chat_once(LLM, system+user prompt, tools=None, max_tokens=300)
        |   → returns epiphany string
        v
ProactiveEvent("dream_epiphany", epiphany, {...}) pushed to queue.Queue
        |
        v
GUI QTimer fires (every 5s) OR CLI loop polls
        |
        | event.kind == "dream_epiphany"
        v
  ┌─────────────────────────────────────────────┐
  │ 1. Append epiphany to chat window            │
  │ 2. memory.add(session_id, "assistant", text) │
  │ 3. Sarvam TTS → play WAV in daemon thread    │
  └─────────────────────────────────────────────┘
        |
        v
[User sits down, sees + hears the epiphany — no keyboard needed]
        |
        v
User types/speaks → proactive.set_last_interaction() → _dream_pending = False
                                                      → ready for next idle cycle
```
