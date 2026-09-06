# ZUMBA — Personal AI Assistant

Zumba is a Python CLI personal assistant powered by the [Kilo AI Gateway](https://kilo.ai/docs/gateway) — one OpenAI-compatible endpoint for hundreds of models, including free ones. It features an interactive chat REPL, persistent SQLite-backed sessions, streaming responses, a terminal-aware renderer, and a **long-term memory system** built on a temporal knowledge graph (GraphRAG-style).

## Memory (the hippocampus)

Zumba has a built-in long-term memory system — a temporal knowledge graph stored in a single embedded SQLite database (`~/.zumba/memory.db`, zero servers, works offline). Design synthesized from the GraphRAG / LightRAG / Zep-Graphiti / Mem0 / HippoRAG / MemGPT lines of research:

### Write path (after every chat turn)
1. **Capture** — the exchange is stored as an episode (content-hashed, dedup-safe).
2. **Salience gate** — the LLM decides whether the exchange is worth remembering (chit-chat is kept as searchable history but not distilled).
3. **Extraction** — the LLM extracts entities, typed relations and facts with confidence scores.
4. **Entity resolution** — alias table + vector similarity + LLM merge decisions map mentions onto canonical entities.
5. **Write decision** — Mem0-style ADD / UPDATE / NOOP / INVALIDATE against existing facts; contradictions *invalidate* (bi-temporal `valid_at`/`invalid_at`) instead of deleting, so history is never lost.
6. **Auto-linking** — A-Mem-style notes are embedded and linked to related notes.

### Read path (before every chat turn)
Hybrid recall with **no LLM in the loop**: vector KNN (local ONNX embeddings, bge-small, 384-dim) + BM25 full-text + graph expansion via **Personalized PageRank** seeded by matched entities, fused with reciprocal-rank fusion and packed into a token budget with provenance. The block is injected as a system message just before your turn (never saved into session history).

### Sleep-time consolidation
Runs opportunistically in the background (or via `zumba memory consolidate`): exponential decay + reinforcement of entity salience, note-link recharging, **Leiden community detection** with LLM-written cluster summaries (GraphRAG global memory), and a **core-block rewrite** (MemGPT/Letta-style L1 profile blocks).

### CLI

```powershell
python main.py web search "..."        # realtime web (DDG + Wiki + HN, zero-key)
python main.py web news "..." --when 1d  # realtime Google News RSS
python main.py web fetch <url>         # readable page text (Jina fallback)
python main.py vault add ./docs        # ingest files/folders into the Vault
python main.py vault ask "what does my lease say about pets?"  # cited answer
python main.py vault find "client approval"  # raw hits, no LLM
python main.py vault status            # docs/chunks/index health
python main.py goal add "Pass IELTS 7.5" --deadline 2026-12-01 --priority 1  # auto-decomposed + researched
python main.py goal list               # progress bars + next step
python main.py goal step 1.0 done      # check off → progress recomputes
python main.py goal remind "stretch" --at "friday 5pm" --every daily
python main.py goal tick               # one proactive pass (deadline/stall/research/win)
python main.py memory stats            # graph counts + db location
python main.py memory search "..."     # hybrid recall (vector + BM25 + PPR v2)
python main.py memory add "..."        # store a fact through the full pipeline
python main.py memory forget <name>    # invalidate facts about an entity
python main.py memory consolidate      # run sleep-time compute now
python main.py memory eval --generate  # regression net: golden Q/A + hit-rate per category
python main.py memory people           # who matters: recency/frequency ranked
python main.py memory clear --yes      # wipe all memory
python main.py soul show               # self-authored identity (soul.md spec)
python main.py me                      # your profile (user.md, always in context)
python main.py daily                   # morning briefing: follow-ups, dates, resurfaces
python main.py daily --install-reminder --at 08:00  # Windows Task Scheduler job
python main.py mood                    # 30-day valence chart
```

### In-chat commands

| Command         | Action                                   |
| --------------- | ---------------------------------------- |
| `/remember <t>` | Store a fact in long-term memory         |
| `/memory <q>`   | Search long-term memory                  |
| `/forget <n>`   | Invalidate facts about an entity         |
| `/soul show\|diff\|accept\|reject\|edit\|init\|wingit` | Identity file lifecycle |
| `/me`           | Show your user profile                   |
| `/brief`        | Daily briefing from memory               |
| `/search <q>`   | Realtime web search (zero-key)           |
| `/news <q>`     | Realtime news (Google News RSS)          |
| `/fetch <url>`  | Read a web page as text                  |
| `/vault ask\|find\|add\|status\|doc` | Local document vault      |

Set `ZUMBA_NO_MEMORY=1` to disable memory entirely; every memory failure degrades gracefully — chat never breaks because of it.

## Features (chat + sessions)

- **Long-term memory (the hippocampus)** — every exchange is salience-gated and, when memorable, distilled by the LLM into entities, temporal relations and linked notes stored in an embedded knowledge graph. Recall fuses vector search, full-text (BM25) and Personalized PageRank over the graph, and is injected into your prompts automatically.
- **MCP tool servers** — Model Context Protocol layer (`mcpclient/`): stdio/HTTP/SSE servers from `~/.zumba/mcp.json`, OpenAI-style tool loop (25 max turns, final summarize so long runs never end in `(empty response)`), tool transcript persisted across turns in memory (last 10) and in the session DB so `continue`/`--resume` keep tool context (folded into a digest, never replayed bare), live reload + self-install meta-tools
- **429 resilience** — gateway client retries once after `Retry-After` (also one retry on transient 502/503); agent loop retries flaky model calls and ends the turn with a progress summary instead of an error when the provider stays down; memory consolidation throttled (no full run on start, 30-min interval) so background LLM calls don't self-inflict rate limits
- **Free-first** — defaults to `kilo-auto/free`; `zumba models` lists all 18+ free models with no API key needed
- **Interactive chat** — REPL with streaming answers inside bordered panels, slash commands, per-turn autosave
- **Resume that feels continuous** — `--resume` / `--last` / `/load <#>` reprints previous messages before continuing
- **Numbered session picker** — Codex-style `/sessions` list; type a number instead of a 12-char id
- **Persistent preferences** — `/model <id>` saves the global default; system prompt, streaming, and emoji prefs survive restarts
- **Full-text session search** — FTS5 over all messages (`zumba sessions --search <text>`)
- **Legacy-cmd safe rendering** — auto-detects conhost vs Windows Terminal/VS Code; strips emojis, folds smart punctuation, repairs old mojibake
- **Graceful shutdown** — Ctrl+C during save/flush or MCP teardown exits cleanly with session saved
- **God-mode shell** — unrestricted persistent PowerShell for the model (`zumba__shell_run/jobs/kill`) and you (`/shell`, `python main.py shell`); background jobs, audit log, `ZUMBA_NO_SHELL=1` kill-switch
- **Context window manager** — every model call fits `ZUMBA_CONTEXT_LIMIT` (default 8192): system + anchor + recent turns kept, middle overflow becomes one cached rolling summary, stale tool transcripts truncated
- **Persona + provenance** — identity voice with editable `style` prefs (`zumba config --set-style`); `/why` explains the last turn's memory recall with kinds and scores
- **Soul + living memory (Tier 2)** — `~/.zumba/soul.md` is self-authored on first run (3 questions, skippable via `/soul wingit`; `user.md` companion holds your profile and is always injected); session-end reflection writes decisions/follow-ups/importance/mood in one LLM pass; retrieval is HippoRAG-2 passages-in-graph with importance + temporal filters (`as_of`, time ranges) and A-Mem note evolution; `zumba daily` briefs from follow-ups + on-this-day resurfaces; style corrections (`shorter`, `no tables`) fold into soul Voice via propose/accept; `zumba memory eval` keeps the regression net green
- **Web search (zero-key)** — `zumba__web_search/web_news/web_fetch` model tools (DDG + Google News RSS + Wikipedia + HN + Reddit + readable fetch with Jina fallback); CLI `zumba web search|news|fetch`, in-chat `/search|/news|/fetch`; TTL cache, CAPTCHA fallback, `ZUMBA_NO_WEB=1` kill-switch
- **The Vault (local document RAG)** — drop files into `~/.zumba/vault/` (`zumba vault add <path>`, `watch`, `status`, `ask`, `find`, `doc`, `forget`, `reindex`); structure-aware chunking, hybrid vector+BM25+RRF, small-to-big parent sections, RAPTOR-lite summaries, local rerank, citations `[Title p.N]`; always-on `[VAULT CONTEXT]` recall hook + `zumba__vault_search/doc/read` tools + `/vault` chat commands; `ZUMBA_NO_VAULT=1` kill-switch
- **Proactive goals (Tier 3)** — `goal add` auto-decomposes via LLM into steps with staggered micro-deadlines; natural-time reminders (`friday 5pm`, `in 3 days`, daily/weekly recur, snooze, desktop toast); background worker fires reminders + deadline/stall nudges + pre-deadline web research + win/fail detection (rate-limited, `config --set-proactive off`); goals lead the daily brief, sit in recall context, and are creatable by the agent (`goal_add`, `remind_add` tools) and chat (`/goal`, `/remind`)
- **160+ passing tests** — mocked API, storage, renderer, memory-graph, MCP agent/manager, shell, context-budget, persona, why, tool-memory, plus soul, eval, reflection/mood/prefs/people, retrieval-v2, websearch, vault, and goals/reminders suites

## Requirements

- Python 3.11+
- A Kilo API key for chatting (`KILO_API_KEY`) — free models still need a key; listing models does not

## Setup

```powershell
cd zumba
pip install -r requirements.txt
copy .env.example .env   # then put your key in .env
```

| Variable            | Purpose                              | Default                              |
| ------------------- | ------------------------------------ | ------------------------------------ |
| `KILO_API_KEY`      | Auth for chat endpoints (required)   | —                                    |
| `KILO_BASE_URL`     | Gateway override                     | `https://api.kilo.ai/api/gateway`    |
| `ZUMBA_MODEL`       | Env-level default model (top priority)| `kilo-auto/free`                    |
| `ZUMBA_NO_EMOJI`    | Force emoji stripping (`1`)          | auto-detect                          |
| `ZUMBA_FORCE_EMOJI` | Force full unicode (`1`)             | auto-detect                          |
| `ZUMBA_NO_MCP`      | Disable MCP layer entirely (`1`)     | enabled                              |
| `ZUMBA_MCP_MAX_ITERATIONS` | Max tool turns per chat turn  | `25`                                 |
| `ZUMBA_NO_SHELL`    | Disable god-mode shell (`1`)         | enabled                              |
| `ZUMBA_SHELL_TIMEOUT` | Default shell timeout (seconds)    | `60`                                 |
| `ZUMBA_SHELL_MAX_OUTPUT` | Shell output cap (chars, head+tail) | `8000`                            |
| `ZUMBA_CONTEXT_LIMIT` | Context budget per model call      | `8192`                               |
| `ZUMBA_NO_MEMORY`   | Disable long-term memory (`1`)       | enabled                              |

Model precedence: `--model` flag → `ZUMBA_MODEL` env → saved default → `kilo-auto/free`.

## Usage

```powershell
python main.py models                 # list free models (no key needed)
python main.py models --all           # list all ~369 models
python main.py models --set-default cohere/north-mini-code:free
python main.py ask "Explain black holes briefly"
python main.py chat                   # start interactive chat
python main.py chat --last            # continue most recent session
python main.py chat --resume 2        # continue session #2
python main.py sessions               # list saved chats
python main.py sessions --search "invoice"
python main.py sessions --show 1      # print full transcript
python main.py config                 # view preferences
python main.py config --set-model <id> --set-streaming off
python main.py doctor                 # terminal/rendering diagnostics
python main.py version
```

### In-chat commands

| Command        | Action                                        |
| -------------- | --------------------------------------------- |
| `/help`        | Command table                                 |
| `/models`      | Free-model table                              |
| `/model <id>`  | Switch model **and save as default**          |
| `/sessions`    | Numbered picker → type a number to load       |
| `/load <#>`    | Load session by number (bare `/load` picks)   |
| `/new`         | Start a fresh session                         |
| `/system`      | Update system prompt                          |
| `/stream`      | Toggle streaming                              |
| `/emoji`       | Toggle emoji stripping                        |
| `/tokens`      | Token estimate                                |
| `/shell <cmd>` | Run a shell command directly (god-mode, persistent) |
| `/why`         | Explain the last turn's memory recall         |
| `/clear`       | Clear history                                 |
| `/exit`        | Save and exit (Ctrl+C also saves)             |

## Architecture

```mermaid
flowchart TB
    subgraph CLI["main.py — Typer CLI"]
        MODELS["models / providers"]
        ASK["ask (one-shot)"]
        CHAT["chat (REPL)"]
        SESS["sessions / config / doctor"]
    end
    subgraph CORE["Core modules"]
        API["api_client.py\nREST + SSE streaming"]
        CONV["chat.py\nConversation state"]
        STORE["store.py\nSQLite + FTS5"]
        CONF["config.py\nprefs resolution"]
        OUT["output.py\ntheme + sanitizer"]
        TYPES["models.py\ndataclasses"]
    end
    KILO[("Kilo Gateway\napi.kilo.ai")]
    DB[("~/.zumba/zumba.db")]

    MODELS --> API
    ASK --> API
    CHAT --> API
    CHAT --> CONV
    CHAT <--> STORE
    SESS <--> STORE
    CLI --> CONF
    CLI --> OUT
    API --> KILO
    STORE --> DB
```

### Request flow (chat turn)

```mermaid
sequenceDiagram
    participant U as User input
    participant C as Conversation
    participant S as SQLite store
    participant K as Kilo /chat/completions
    participant R as Renderer
    U->>C: append user message
    U->>S: persist message
    C->>K: POST (stream=true)
    K-->>R: SSE token chunks
    alt modern terminal
        R-->>R: Live bordered panel
    else legacy cmd
        R-->>R: plain lines, then one box
    end
    R->>C: append assistant reply
    R->>S: persist reply + tokens
```

### Storage layout (like Hermes/OpenClaw)

```mermaid
erDiagram
    sessions ||--o{ messages : contains
    sessions {
        text id PK
        text title
        text model
        text system
        real created_at
        real updated_at
        int message_count
        int total_tokens
    }
    messages {
        int id PK
        text session_id FK
        text role
        text content
        real created_at
    }
```

- Home store: `~/.zumba/zumba.db` (WAL mode), `~/.zumba/models_cache.json`
- Legacy `sessions/*.json` files auto-import once on first run
- Preferences live in the `config` table: `default_model`, `default_system`, `streaming`, `last_session`

## MCP — plug in any tool server

ZUMBA speaks the [Model Context Protocol](https://modelcontextprotocol.io). Register any MCP server (stdio subprocess, streamable HTTP or SSE) and ZUMBA connects to it, exposes its tools to the model, and runs a full agent loop: the model asks for a tool → ZUMBA executes it over MCP → the result goes back to the model → repeat until the final answer.

```powershell
python main.py mcp list                              # connected servers + live status
python main.py mcp add fs -- npx -y @modelcontextprotocol/server-filesystem C:/Users/anime
python main.py mcp add remote --url https://mcp.example.com/mcp
python main.py mcp remove fs
python main.py mcp tools                             # every tool, namespaced server__tool
python main.py mcp call demo__add -a '{"a": 2, "b": 3}'   # call any tool directly, no LLM
```

Servers live in `~/.zumba/mcp.json` (Claude-Desktop compatible format — copy configs straight over) with project-level overrides in `.mcp.json` (see `mcp.json.example`). In chat: `/mcp` shows server status, `/tools` lists all tools, and when a server is online every turn automatically runs the agent loop. `ZUMBA_NO_MCP=1` disables the layer; a crashing/offline server degrades gracefully exactly like memory. A working example server is bundled: `zumba mcp add demo -- python tests/mcp_echo_server.py`.

### Live reload & self-installation

Changes apply **in the current session — no restart**:
- `python main.py mcp reload` (or `/mcp reload` in chat) hot-reloads the registry: new servers connect, removed ones shut down, changed ones reconnect.
- Editing `~/.zumba/mcp.json` while chatting is picked up automatically on the next message.
- ZUMBA can **manage itself**: the model gets built-in meta-tools (`zumba__mcp_search`, `zumba__mcp_add`, `zumba__mcp_remove`, `zumba__mcp_list`) backed by the official MCP registry. Just ask *"find and install an MCP server for GitHub"* and ZUMBA searches the registry, installs, connects, and uses it — all mid-session.

## Shell — god-mode command tool

Unrestricted, persistent PowerShell for the model and you. One long-lived session: cwd, env vars, and files carry over between calls, so the model chains state instead of re-stating it. No allowlists, no approval prompts — every command, exit code, and timestamp is appended to `~/.zumba/shell_audit.log`.

```powershell
python main.py shell "python --version"   # one-shot (exit code propagates)
```

In chat: `/shell <cmd>` runs directly (bypasses the model); the model gets `zumba__shell_run` (+ `shell_jobs` / `shell_kill` for background jobs with `run_in_background: true`). Windows PowerShell syntax required (`Get-ChildItem`, not `ls -la`); common bash spells are auto-translated (`ls -la` → `Get-ChildItem -Force`, `cat` → `Get-Content`, `grep` → `Select-String`). Timeouts return partial output and restart the session; output caps at `ZUMBA_SHELL_MAX_OUTPUT` (head+tail); `ZUMBA_NO_SHELL=1` removes the tools.

## Context, persona, provenance

- Every model call is fit to `ZUMBA_CONTEXT_LIMIT` (default 8192) by `core/context_budget.py`: system prompts, the first user message (session anchor), and recent turns are always kept; dropped middle turns become one cached rolling summary (rebuilt after ≥6 newly dropped turns); stale tool transcripts truncate to 200 chars.
- `identity/persona.py` composes soul.md (self-authored identity, 4k cap) + user.md profile + editable style prefs (`zumba config --set-style "..."`); `--system` still overrides everything. Ordering: soul → user → identity → style → base.
- `/why` shows the last turn's exact memory injection: recall query, hit kinds, scores, and source ids. `/why off|on` toggles capture (default on, zero extra cost).

## Soul, user model, eval, daily

- First message with no `~/.zumba/soul.md` triggers onboarding: 3 questions, skippable (`/soul wingit` drafts from early exchanges). Zumba writes soul.md itself (frontmatter + Identity/Voice/Values/Boundaries, 4k cap) plus companion `user.md`. Updates go through consent: propose → `soul.proposed.md` → `/soul diff` → `/soul accept|reject`; `/soul edit` opens `$EDITOR`, `/soul show` displays.
- `user_facts` table + LLM-maintained `user.md` (Identity/Projects/People/Preferences/Goals/Current focus); recall always prepends the profile bounded, plus recent mood context.
- Session-end reflection (one LLM pass after flush, background thread): decisions → `notes(kind=decision)`, open items → `follow_ups`, poignancy 1-10 → `episodes.importance` (feeds retrieval), mood → `session_moods` (fastembed anchors, no LLM needed).
- Retrieval v2: passages-in-graph PPR (episode/note nodes seed PPR too, reset weighted by importance + recency), A-Mem evolution (new note refreshes top-3 similar, max 3/ingest), temporal read path (`time_range`, `as_of` on `valid_at`), and latency discipline (episode FTS+vector indexed synchronously — ingest → immediate recall is a regression test).
- `zumba memory eval` is the regression net: LLM or heuristic golden Q/A (`single-hop`, `temporal`, `update`) → `eval_pairs`, full read path per question with LLM-judge (containment fallback offline) → `eval_runs` with per-category hit-rate. Every retrieval/extraction change must keep it green.


## Project structure

```text
zumba/
├── main.py          # Typer CLI: models / ask / chat / sessions / config / memory / web / vault / mcp / shell / doctor
├── core/            # App foundation: config, models, store, output, chat, api_client, context_budget
├── identity/        # Who Zumba is + who you are: persona, soul, userprofile
├── tools/           # God-mode local tools: shelltool, websearch
├── vault/           # Local document RAG (parsers, chunker, ingest, retrieve, rerank, summaries)
├── core/            #   (files)
│   ├── api_client.py    # Gateway client: list_models, chat_completion (+tools), SSE streaming
│   ├── chat.py          # Conversation state, save/load, token estimates
│   ├── store.py         # SQLite sessions + FTS search + config prefs
│   ├── config.py        # Env + saved + default resolution
│   ├── output.py        # Theme, tables/panels, emoji + mojibake sanitizer
│   ├── models.py        # Message (incl. tool_calls) / ModelInfo / ChatResult dataclasses
│   └── context_budget.py # Token estimator + fit-to-budget window + rolling summary
├── identity/        #   (files)
│   ├── persona.py       # Soul + user profile + identity voice + style prefs
│   ├── soul.py          # soul.md / user.md bootstrap, loader, propose/accept, 4k cap
│   └── userprofile.py   # user_facts table + user.md rewrite + always-inject profile block
├── tools/           #   (files)
│   ├── shelltool.py     # God-mode persistent PowerShell session + background jobs + audit
│   └── websearch.py     # Zero-key web engine: DDG + GNews RSS + Wiki + HN + Reddit + fetch + cache
├── mcpclient/       # MCP layer (pluggable tool servers)
│   ├── config.py        # ~/.zumba/mcp.json + .mcp.json registry (Claude-Desktop format)
│   ├── manager.py       # Async connection manager: stdio / HTTP / SSE, health, reconnect
│   ├── tools.py         # MCP <-> OpenAI tool schema adapters, server__tool namespacing
│   ├── agent.py         # Agentic tool-use loop (model -> MCP -> model)
│   └── ...
├── memory/          # Long-term memory (temporal knowledge graph)
│   ├── db.py            # Schema: episodes, entities, relations, notes, vec, FTS
│   ├── embedder.py      # Local ONNX embeddings (fastembed bge-small)
│   ├── llm.py           # Structured LLM reasoning (Kilo gateway)
│   ├── extraction.py    # Salience gate, extraction, write decisions
│   ├── resolve.py       # Entity resolution (alias + vector + LLM merge)
│   ├── graph.py         # PageRank, decay/reinforce, Leiden communities
│   ├── retrieval.py     # Hybrid recall v2 (passages-in-graph PPR + temporal + importance)
│   ├── consolidation.py # Sleep-time compute + A-Mem note evolution
│   ├── reflection.py    # Session-end reflection (decisions/follow-ups/importance/mood)
│   ├── mood.py          # Valence anchors + timeline + chart
│   ├── briefing.py      # Daily briefing composer + scheduler install
│   ├── eval.py          # Eval harness (golden Q/A, judge, runs)
│   ├── preferences.py   # prefers_* detection + soul Voice proposals
│   ├── people.py        # Relationship view
│   └── service.py       # Memory orchestrator
├── sessions/        # Legacy JSON sessions (auto-migrated, git-ignored)
├── tests/           # pytest suite (API mocks, storage, renderer, memory, shell, budget, persona, soul, eval, reflection, retrieval-v2, goals)
├── requirements.txt
└── .env.example
```

## Terminal support

| Terminal                        | Emoji | Box style | Streaming       |
| ------------------------------- | ----- | --------- | --------------- |
| Windows Terminal / VS Code      | Full  | Rounded   | Live boxed panel|
| Legacy `cmd` / conhost          | Stripped (auto) | ASCII | Plain + final box |

`zumba doctor` diagnoses the current terminal and prints fixes.

## Testing

```powershell
python -m pytest tests -q
```

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| `KILO_API_KEY is not set` | `setx KILO_API_KEY "key"` or add to `.env` |
| `401` | Invalid key — regenerate at kilo.ai |
| `402` | Out of credits — free models (`:free`) don't bill |
| Boxes/garbled text in cmd | Expected — safe mode is on; use Windows Terminal or `zumba doctor` |
| Empty assistant reply after tools | Fixed — agent summarizes after 25 tool turns; if it still happens, say `continue` or set `ZUMBA_MCP_MAX_ITERATIONS=40` |
