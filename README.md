# ZUMBA — Personal AI Assistant

Zumba is a Python CLI personal assistant with a split brain: [NVIDIA NIM](https://build.nvidia.com) for fast chat with tool calling, and a free Kilo-gateway model for knowledge-graph work that needs reliable structured JSON. It features an interactive chat REPL, persistent SQLite-backed sessions, streaming responses, a terminal-aware renderer, a **long-term memory system** built on a temporal knowledge graph (GraphRAG-style) that is the **sole source of truth** for personal facts (no profile file — the graph answers directly), a Next.js web UI, and a PyQt5 desktop voice assistant.

## Memory (the hippocampus)

Zumba has a built-in long-term memory system — a temporal knowledge graph stored in a single embedded SQLite database (`~/.zumba/memory.db`, zero servers, works offline). Design synthesized from the GraphRAG / LightRAG / Zep-Graphiti / Mem0 / HippoRAG / MemGPT lines of research:

### Write path (after every chat turn)
1. **Capture** — the exchange is stored as an episode (content-hashed, dedup-safe).
2. **Salience gate** — the LLM decides whether the exchange is worth remembering (chit-chat is kept as searchable history but not distilled). Calibrated for first-person facts *and* named people (who to reply to / avoid, friends, contacts).
3. **Extraction** — the LLM extracts entities, typed relations and facts with confidence scores, retried up to 4× (the free extraction model flakes empty ~50% on hard exchanges — one bad roll must not drop the exchange).
4. **Entity resolution** — alias table + vector similarity + LLM merge decisions map mentions onto canonical entities.
5. **Write decision** — Mem0-style ADD / UPDATE / NOOP / INVALIDATE against existing facts; contradictions *invalidate* (bi-temporal `valid_at`/`invalid_at`) instead of deleting, so history is never lost.
6. **Auto-linking** — A-Mem-style notes are embedded and linked to related notes.
7. **Lock discipline** — no write transaction ever spans a network call: planning (reads + LLM) and applying (pure writes) are separate phases with commits between them, so background ingestion never wedges the DB with `database is locked`.

### Read path (before every chat turn)
Hybrid recall with **no LLM in the loop**: vector KNN (local ONNX embeddings, bge-small, 384-dim) + BM25 full-text (stopword-stripped, inflection-expanded so `live` meets `lives`) + graph expansion via **Personalized PageRank** seeded by matched entities, fused with reciprocal-rank fusion **plus direct query↔fact cosine** and hub-damping (high-degree nodes like "Krish" can't drown out specific facts), near-duplicate relations collapsed. Packed into a token budget with provenance and injected as an authoritative system block just before your turn (never saved into session history). Service recall gets a real budget (`ZUMBA_RECALL_BUDGET`, default 2.0s) instead of racing a 0.35s timeout.

### Sleep-time consolidation
Runs opportunistically in the background (or via `zumba memory consolidate`): exponential decay + reinforcement of entity salience, note-link recharging, **Leiden community detection** with LLM-written cluster summaries (GraphRAG global memory), and a **core-block rewrite** (MemGPT/Letta-style L1 profile blocks).

### CLI

```powershell
python main.py web search "..."        # realtime web (DDG + Wiki + HN, zero-key)
python main.py web news "..." --when 1d  # realtime Google News RSS
python main.py web fetch <url>         # readable page text (Jina fallback)
python main.py scrape low <url>        # scrape one simple page (Scrapling static)
python main.py scrape mid <url> -s title=h1  # scrape blocked/JS page or fields (auto stealth)
python main.py scrape high <url> --depth 1   # crawl multi-page (depth<=2, <=20 pages)
python main.py fs read <file> --start 1 --num 200  # read with line numbers
python main.py fs grep <pattern> --path . --glob *.py  # ripgrep-fast search
python main.py fs find <name>                # instant filename locate
python main.py fs edit <file> --old ... --new ...  # targeted edit + backup
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
python main.py me                      # your graph-backed profile (user_facts, no user.md file)
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
| `/scrape <url> [--mid\|--high]` | Scrape a page: low (static) / mid (stealth+fields) / high (crawl) |
| `/fs <op> ...` | Files: read\|grep\|find\|list\|info\|glob\|tree\|edit (no shell needed) |
| `/vault ask\|find\|add\|status\|doc` | Local document vault      |

Set `ZUMBA_NO_MEMORY=1` to disable memory entirely; every memory failure degrades gracefully — chat never breaks because of it.

## Features (chat + sessions)

- **Long-term memory (the hippocampus)** — every exchange is salience-gated and, when memorable, distilled by the LLM into entities, temporal relations and linked notes stored in an embedded knowledge graph. Recall fuses vector search, full-text (BM25) and Personalized PageRank over the graph, and is injected into your prompts automatically.
- **MCP tool servers** — Model Context Protocol layer (`mcpclient/`): stdio/HTTP/SSE servers from `~/.zumba/mcp.json`, OpenAI-style tool loop (25 max turns, final summarize so long runs never end in `(empty response)`), tool transcript persisted across turns in memory (last 10) and in the session DB so `continue`/`--resume` keep tool context (folded into a digest, never replayed bare), live reload + self-install meta-tools
- **Gateway resilience** — client retries after `Retry-After`; agent loop retries transient 408/429/500/502/503 (NIM emits flaky 500s under load) and ends the turn with a progress summary instead of an error when the provider stays down; memory consolidation throttled (no full run on start, 30-min interval) so background LLM calls don't self-inflict rate limits
- **NIM-first** — defaults to `nvidia/nemotron-3-super-120b-a12b`; `zumba models` lists the models on your NVIDIA key
- **Split brain: chat vs knowledge** — chat/normal tasks run on NIM; all memory/knowledge structured calls (extraction, resolution, consolidation, graph ingestion) run on a free Kilo-gateway model (`nex-agi/nex-n2.5-mini:free`, verified live for schema-valid JSON). One switch each: `ZUMBA_*` trio for chat, `ZUMBA_KNOWLEDGE_*` trio for knowledge. Structured calls retry with backoff (`ZUMBA_LLM_ATTEMPTS`, default 3) plus a comma-separated `ZUMBA_KNOWLEDGE_FALLBACK` chain
- **Graph is the source of truth** — `user.md` is deleted by design (`ZUMBA_NO_USER_MD=1`); personal facts live as graph entities/relations/`user_facts` and the model answers from recall evidence with an anti-refusal directive. `zumba me` / `me_show` read the graph, never a file
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
- **Scraping (Scrapling tiers)** — `zumba__scrape_low/scrape_mid/scrape_high` model tools ONLY for explicit scrape requests (`web_fetch` stays general reading): low = fast static page, mid = auto stealth fallback (Cloudflare solver) + CSS/XPath fields, high = multi-page crawl (depth<=2, <=20 pages, same-domain); CLI `zumba scrape low|mid|high`, in-chat `/scrape [--mid|--high]`; `ZUMBA_NO_SCRAPE=1` kill-switch
- **Filesystem (no shell needed)** — 17 model tools: `fs_read/grep/find/list/info/glob/tree` reads + `fs_write/edit/insert/replace_lines/apply_patch(V4A atomic)/batch/undo/mkdir/move/delete(confirm=true)` writes with auto-backup (`.zumba_backups`), unified-diff results, `fs_audit.log`; CLI `zumba fs read|grep|find|list|edit|patch|undo`, in-chat `/fs ...`; `ZUMBA_NO_FS=1` kill-switch
- **The Vault (local document RAG)** — drop files into `~/.zumba/vault/` (`zumba vault add <path>`, `watch`, `status`, `ask`, `find`, `doc`, `forget`, `reindex`); structure-aware chunking, hybrid vector+BM25+RRF, small-to-big parent sections, RAPTOR-lite summaries, local rerank, citations `[Title p.N]`; always-on `[VAULT CONTEXT]` recall hook + `zumba__vault_search/doc/read` tools + `/vault` chat commands; `ZUMBA_NO_VAULT=1` kill-switch
- **Proactive goals (Tier 3)** — `goal add` auto-decomposes via LLM into steps with staggered micro-deadlines; natural-time reminders (`friday 5pm`, `in 3 days`, daily/weekly recur, snooze, desktop toast); background worker fires reminders + deadline/stall nudges + pre-deadline web research + win/fail detection (rate-limited, `config --set-proactive off`); goals lead the daily brief, sit in recall context, and are creatable by the agent (`goal_add`, `remind_add` tools) and chat (`/goal`, `/remind`)
- **Geo / trip brain (PLAN-GO)** — 11 standalone model tools in `tools/geo.py` (`zumba__geo_geocode/reverse/route/traffic/nearby/weather/maps_link/track_start/track_stop/whereami/visit_log`): single questions take one call (how far → route, raining → weather, cafes near X → geocode + nearby); "I'm heading to X" chains geocode → route → live traffic → weather at arrival → nearby → ONE briefing with leave-by time, route, weather, personal context, maps link. TomTom-first when `ZUMBA_TT_KEY` is set (Search, Reverse Geocode, Category/Places Search, Routing + Traffic Incidents/Flow), OSM fallbacks (Nominatim/OSRM/Overpass) otherwise; `ZUMBA_NO_GEO=1` kill-switch. Telegram point/live locations store silently to SQLite (`server/geo_store.py`); the pipeline and Telegram both run the agent tool loop so geo tools fire everywhere, not just CLI
- **325 passing tests** — mocked API, storage, renderer, memory-graph, MCP agent/manager, shell, context-budget, persona, why, tool-memory, plus soul, eval, reflection/mood/prefs/people, retrieval-v2, websearch, scrape, filesystem, vault, goals/reminders, geo, DB-lock concurrency, JSON-retry, and desktop suites. Live recall eval: `python scripts/eval_graph_recall.py --n 12 --ep 6` (isolated DB snapshot, stratified IMP/NONIMP/episode questions, scored)

## Requirements

- Python 3.11+
- An NVIDIA API key for chatting (`ZUMBA_API_KEY`, at https://build.nvidia.com) — listing models also needs the key

## Setup

```powershell
cd zumba
pip install -r requirements.txt
copy .env.example .env   # then put your key in .env
```

| Variable            | Purpose                              | Default                              |
| ------------------- | ------------------------------------ | ------------------------------------ |
| `ZUMBA_API_KEY`      | Auth for chat endpoints (required)  | —                                    |
| `ZUMBA_BASE_URL`    | API base override                    | `https://integrate.api.nvidia.com/v1` |
| `ZUMBA_MODEL`       | Env-level default model (top priority)| `nvidia/nemotron-3-super-120b-a12b` |
| `ZUMBA_KNOWLEDGE_MODEL` | Knowledge-graph model (chat untouched) | `nex-agi/nex-n2.5-mini:free` |
| `ZUMBA_KNOWLEDGE_BASE_URL` | Knowledge endpoint override      | `KILO_BASE_URL` fallback             |
| `ZUMBA_KNOWLEDGE_API_KEY` | Knowledge auth override           | `KILO_API_KEY` fallback              |
| `ZUMBA_KNOWLEDGE_FALLBACK` | Comma-separated fallback models | same knowledge model                 |
| `ZUMBA_LLM_ATTEMPTS` | Structured-call retries (backoff)   | `3`                                    |
| `ZUMBA_MEMORY_MODEL` | Single-call memory override (rarely needed) | knowledge model              |
| `ZUMBA_NO_USER_MD`  | Graph-only profile (`1` = never read/write user.md) | `0`                    |
| `ZUMBA_RECALL_BUDGET` | Service-recall wait per turn (sec) | `2.0`                                  |
| `ZUMBA_NO_EMOJI`    | Force emoji stripping (`1`)          | auto-detect                          |
| `ZUMBA_FORCE_EMOJI` | Force full unicode (`1`)             | auto-detect                          |
| `ZUMBA_NO_MCP`      | Disable MCP layer entirely (`1`)     | enabled                              |
| `ZUMBA_MCP_MAX_ITERATIONS` | Max tool turns per chat turn  | `25`                                 |
| `ZUMBA_NO_SHELL`    | Disable god-mode shell (`1`)         | enabled                              |
| `ZUMBA_SHELL_TIMEOUT` | Default shell timeout (seconds)    | `60`                                 |
| `ZUMBA_SHELL_MAX_OUTPUT` | Shell output cap (chars, head+tail) | `8000`                            |
| `ZUMBA_CONTEXT_LIMIT` | Context budget per model call      | `8192`                               |
| `ZUMBA_NO_MEMORY`   | Disable long-term memory (`1`)       | enabled                              |
| `ZUMBA_TT_KEY`      | TomTom key: live traffic + Places-first geocode/nearby/route | OSM fallbacks |
| `ZUMBA_NO_GEO`      | Disable all geo tools (`1`)          | enabled                              |
| `ZUMBA_OSRM_URL`    | Self-hosted OSRM override            | public demo                          |
| `ZUMBA_OVERPASS_URL` | Overpass mirror override            | `overpass-api.de`                    |
| `ZUMBA_GEO_TRACK_MAX_MIN` | Max live-location track window (min) | `90`                             |
| `ZUMBA_NO_SCRAPE` | Disable scrape tiers (`1`) | enabled |
| `ZUMBA_SCRAPE_TIMEOUT` | Static fetch timeout (seconds) | `30` |
| `ZUMBA_SCRAPE_STEALTH_TIMEOUT` | Stealth browser timeout (seconds) | `30` |
| `ZUMBA_SCRAPE_MAX_OUTPUT` | Scrape output cap (chars, head+tail) | `8000` |
| `ZUMBA_SCRAPE_MAX_PAGES` | Crawl page cap | `20` |
| `ZUMBA_NO_FS` | Disable filesystem tools (`1`) | enabled |
| `ZUMBA_FS_MAX_OUTPUT` | FS output cap (chars, head+tail) | `8000` |
| `ZUMBA_FS_SEARCH_TIMEOUT` | rg search timeout (seconds) | `15` |

Model precedence: `--model` flag → `ZUMBA_MODEL` env → saved default → `nvidia/nemotron-3-super-120b-a12b`.

## Usage

```powershell
python main.py models                 # list models on your key (per-provider cache)
python main.py models --all           # list everything
python main.py models --set-default nvidia/nemotron-3-super-120b-a12b
python main.py ask "Explain black holes briefly"   # one-shot, no memory injected
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

### Web UI (one command)

```powershell
python server/run.py                 # backend :8000 + Next.js frontend :3000
python server/run.py --no-frontend   # backend only (old behavior)
python server/run.py --prod          # backend + production `next start`
```

Open **http://localhost:3000** (the backend is API-only — `GET /` 404 is normal). Ports via `ZUMBA_API_PORT` / `ZUMBA_WEB_PORT`; the frontend points at `NEXT_PUBLIC_API_URL` (default the backend). Includes chat, sessions sidebar with live memory preview, knowledge workspace (`/knowledge`), and voice chat (MediaRecorder → server STT stub → Edge-TTS).

### Desktop voice GUI (Jarvis-style)

```powershell
pip install -r requirements-desktop.txt
python desktop/run.py               # voice GUI: mic toggle, chat, interrupt, exit
python desktop/run.py --text-only   # same GUI, typing only (no mic/speaker)
```

Frameless black window with the arc-reactor gif, Home/Chat screens, and a
status line (`Listening...` → `Thinking...` → `Answering...` → `Available...`).
Voice loop: mic toggle (or typed Submit) → Chrome Web Speech STT (Hindi by
default, `ZUMBA_STT_LANG`) with live partial words on the status line →
auto-translate to English → zumba answer → edge-tts speech. Interrupt
anytime: mic toggle off, say "stop", or talk over it (barge-in keywords).
Say "exit"/"bye" or press X to close.

Mic troubleshooting (`python desktop/mic_test.py` — speak during the 6s test, `--real-mic` drops the fake-device flag to compare):
- Fake device listed → fixed already: the app never substitutes a fake mic (regression-tested).
- Default input is a Bluetooth hands-free mic → set `Settings → Sound →
  Input` to `Microphone Array (Realtek Audio)` (Bluetooth HFP mics are
  usually silent while stereo output is active).
- Browser test page also fails → system-level: unmute + 80+ levels in `mmsys.cpl` → Recording, uncheck exclusive mode, quit mic-hookers (Wispr Flow), reinstall the Realtek driver.

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
    NIM[("NIM\nintegrate.api.nvidia.com")]
    DB[("~/.zumba/zumba.db")]

    MODELS --> API
    ASK --> API
    CHAT --> API
    CHAT --> CONV
    CHAT <--> STORE
    SESS <--> STORE
    CLI --> CONF
    CLI --> OUT
    API --> NIM
    STORE --> DB
```

### Request flow (chat turn)

```mermaid
sequenceDiagram
    participant U as User input
    participant C as Conversation
    participant S as SQLite store
    participant K as NIM /chat/completions
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
- `identity/persona.py` composes soul.md (self-authored identity, 4k cap) + graph profile + editable style prefs (`zumba config --set-style "..."`); `--system` still overrides everything. Ordering: soul → user → identity → style → base (the user slot is empty with `ZUMBA_NO_USER_MD=1`). Recalled memory arrives labeled authoritative — the model must answer from it, never plead ignorance of facts it contains.
- `/why` shows the last turn's exact memory injection: recall query, hit kinds, scores, and source ids. `/why off|on` toggles capture (default on, zero extra cost).

## Soul, user model, eval, daily

- First message with no `~/.zumba/soul.md` triggers onboarding: 3 questions, skippable (`/soul wingit` drafts from early exchanges). Zumba writes soul.md itself (frontmatter + Identity/Voice/Values/Boundaries, 4k cap). Updates go through consent: propose → `soul.proposed.md` → `/soul diff` → `/soul accept|reject`; `/soul edit` opens `$EDITOR`, `/soul show` displays. (The old `user.md` companion file is deleted by design — profile facts live in the graph.)
- `user_facts` table (durable key/value profile, read by `zumba me` / `me_show`); the LLM-maintained `user.md` file is deleted by design — set `ZUMBA_NO_USER_MD=1` (default in `.env.example` is `0`; unset + consolidate rebuilds it). Recall prepends graph evidence bounded, plus recent mood context.
- Session-end reflection (one LLM pass after flush, background thread): decisions → `notes(kind=decision)`, open items → `follow_ups`, poignancy 1-10 → `episodes.importance` (feeds retrieval), mood → `session_moods` (fastembed anchors, no LLM needed).
- Retrieval v2: passages-in-graph PPR (episode/note nodes seed PPR too, reset weighted by importance + recency), A-Mem evolution (new note refreshes top-3 similar, max 3/ingest), temporal read path (`time_range`, `as_of` on `valid_at`), and latency discipline (episode FTS+vector indexed synchronously — ingest → immediate recall is a regression test).
- `zumba memory eval` is the regression net: LLM or heuristic golden Q/A (`single-hop`, `temporal`, `update`) → `eval_pairs`, full read path per question with LLM-judge (containment fallback offline) → `eval_runs` with per-category hit-rate. Every retrieval/extraction change must keep it green.


## Project structure

```text
zumba/
├── main.py          # Typer CLI: models / ask / chat / sessions / config / memory / web / vault / mcp / shell / doctor
├── core/            # App foundation: config (chat + knowledge provider trios), models, store, output, chat, chat_pipeline (agent tool loop), api_client, context_budget
├── desktop/         # PyQt5 voice GUI (Jarvis assets) + Chrome STT + edge-tts + Hindi translate + mic_test; run.py entry
├── requirements-desktop.txt  # PyQt5/pygame/edge-tts/selenium/webdriver-manager/mtranslate
├── identity/        # Who Zumba is + graph profile: persona (incl. GEO_BRIEF trip behavior), soul, userprofile (ZUMBA_NO_USER_MD kill-switch)
├── knowledge/       # Document graph workspace: service (plan/apply locking), extraction, reasoning (retry+fallback chain), storage (busy retry), parsers
├── scripts/         # eval_graph_recall.py (live stratified recall eval), check_knowledge_model.py
├── tools/           # God-mode local tools: shelltool, websearch, scrape (low/mid/high), filesystem (17 fs tools), geo (11 trip-brain tools)
├── server/          # HTTP + Telegram: app, run.py (backend+frontend launcher), telegram_channel (location/live pings), geo_store, channel_store
├── PLAN-GO.md       # Geo/trip-brain build plan (primitives → motion layer)
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
│   ├── websearch.py     # Zero-key web engine: DDG + GNews RSS + Wiki + HN + Reddit + fetch + cache
│   ├── scrape.py        # Scrapling tiers: low (static) / mid (auto stealth + fields) / high (crawl)
│   ├── filesystem.py    # 17 fs tools: read/grep/find/list/info/glob/tree + write/edit/patch/batch/undo
│   └── geo.py           # Trip-brain tools: TomTom-first geocode/reverse/nearby/route/traffic (+incidents/flow), Open-Meteo weather, maps links, track/whereami/visit
├── mcpclient/       # MCP layer (pluggable tool servers)
│   ├── config.py        # ~/.zumba/mcp.json + .mcp.json registry (Claude-Desktop format)
│   ├── manager.py       # Async connection manager: stdio / HTTP / SSE, health, reconnect
│   ├── tools.py         # MCP <-> OpenAI tool schema adapters, server__tool namespacing
│   ├── agent.py         # Agentic tool-use loop (model -> MCP -> model)
│   └── ...
├── memory/          # Long-term memory (temporal knowledge graph)
│   ├── db.py            # Schema: episodes, entities, relations, notes, vec, FTS
│   ├── embedder.py      # Local ONNX embeddings (fastembed bge-small)
│   ├── llm.py           # Structured LLM reasoning (knowledge provider, retry/backoff)
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
├── tests/           # pytest suite incl. conftest (scrubs personal .env flags), test_db_locks (concurrency), test_llm_retry (parser+retry+fallback), test_desktop (offscreen GUI)
├── requirements.txt
└── .env.example     # chat trio + knowledge trio + ZUMBA_NO_USER_MD + desktop vars
```

## Terminal support

| Terminal                        | Emoji | Box style | Streaming       |
| ------------------------------- | ----- | --------- | --------------- |
| Windows Terminal / VS Code      | Full  | Rounded   | Live boxed panel|
| Legacy `cmd` / conhost          | Stripped (auto) | ASCII | Plain + final box |

`zumba doctor` diagnoses the current terminal and prints fixes.

## Testing

```powershell
python -m pytest tests -q                          # full suite (325 green)
python scripts/eval_graph_recall.py --n 12 --ep 6  # live recall eval (isolated snapshot)
```

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| `ZUMBA_API_KEY is not set` | `setx ZUMBA_API_KEY "key"` or add to `.env` |
| `401` | Invalid key — regenerate at build.nvidia.com |
| `402` | Payment required — check billing/limits for your provider |
| Boxes/garbled text in cmd | Expected — safe mode is on; use Windows Terminal or `zumba doctor` |
| Empty assistant reply after tools | Fixed — agent summarizes after 25 tool turns; if it still happens, say `continue` or set `ZUMBA_MCP_MAX_ITERATIONS=40` |
| `database is locked` during ingestion | Fixed — planning (reads+LLM) and applying (writes) are separate phases; status writes retry with backoff. If you still see it: restart the server (old code holds long txns) |
| Knowledge `returned malformed JSON` | Transient free-tier flake — retried automatically (`ZUMBA_LLM_ATTEMPTS`), then the `ZUMBA_KNOWLEDGE_FALLBACK` chain. Persistent = model can't do the shape; switch `ZUMBA_KNOWLEDGE_MODEL` |
| Telegram `409 Conflict ... other getUpdates` | Two bot instances polling — kill the duplicate server process |
| Memory says "no user.md" | By design with `ZUMBA_NO_USER_MD=1` — the profile lives in the graph (`user_facts`); unset to restore the file |
| Assistant denies a stored fact | Check the evidence first (`/why` in chat); usually retrieval ranking or an agent tool-spiral — measure with `scripts/eval_graph_recall.py` |
