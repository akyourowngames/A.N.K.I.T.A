# PLAN: "ZUMBA EYES" — Screen Awareness + Multi-Tool Chaining

> Status: PLANNED (not yet implemented)
> Idea: Zumba SEES your screen — continuously or on-demand — understands what you're looking at (apps, files, text), and ACTS on it through chained tools: "add these files to the vault", "what was that error I saw 10 minutes ago?", "grab the PDF I was just reading and summarize it".
> The other half of the plan is the **agent-loop latency fix**: tools execute in parallel and report progress live instead of the model going dark for 10s.

---

## 1. The core loop (the "sees my screen and does things" moment)

User (File Explorer open, 3 PDFs selected): *"add these files to the vault and process them"*

1. **Perceive** — EYES snapshots the focused window + foreground app. No LLM yet. ~50ms.
2. **Ground** — structured extraction, cheapest-first: UIA tree (titles, selected items, visible text) → OCR fallback → local VLM only when needed.
3. **Resolve** — "these files" = the 3 selected `.pdf` paths. Zumba shows a 1-line Rich confirmation (`Add 3 files to Vault? [Enter]`) — confirmation, not interrogation.
4. **Chain** — agent loop fires `vault add` → ingest progress streams live → `vault status` → summary offer. First feedback < 2s, tools report back as they run.

## 2. Research summary (how the best systems do it, 2025-26)

Findings from **screenpipe** (21k★ open-source Rewind/Recall clone, YC S26) and **uiautomation** (Windows UIA wrapper):

- **Event-driven capture, not continuous recording** — only store/process frames when the screen *changes* (frame differencing / perceptual hash). Cuts storage to ~5-10 GB/month and CPU to 5-10% on modern hardware. Continuous video is for suckers.
- **Accessibility tree BEFORE OCR** — Windows UI Automation gives structured text (window titles, buttons, selected items, File Explorer listings) faster and far more accurately than OCR. OCR (Windows.Media.Ocr via winrt → Tesseract → RapidOCR) is only the fallback for games/remote desktop/custom UI.
- **Local VLM for understanding, not for reading** — Qwen2.5-VL 3B / MiniCPM-V / Moondream 2 handle "what app is this, what's on screen, is there an error dialog" locally; send frames at ~1280px, ~1-3s on CPU, sub-second on GPU. Use sparingly — VLM per frame is the expensive path.
- **Queryable screen memory** — the whole point of screenpipe/Recall: OCR'd frames + UIA text embedded and indexed so "what was I doing at 3pm" / "that error message from earlier" is a search, not a memory test. Encrypted at rest, kill-switch, per-app deny lists.
- **UIA specifics** — `uiautomation` (pure ctypes/comtypes, no deps) reads foreground window, selected files in Explorer, focused control text; Electron apps need `--force-renderer-accessibility`. Fallback to PowerShell `Get-Process` + Win32 `GetForegroundWindow` for title-only awareness.
- **Agent exposure** — screenpipe ships as an MCP server so agents query screen history as a tool. Zumba does it natively: `eyes_*` builtins in the same layer as `shell_*`/`web_*`.

## 3. Architecture

Two new pieces: a **`eyes/`** package (perception) and an **agent-loop upgrade** (action).

```
eyes/
├── capture.py       # mss screenshot of focused monitor/window; dxcam when GPU present;
│                    #   event-driven: capture on change (perceptual-hash diff, ~1s poll, adaptive)
├── uia.py           # uiautomation wrapper: foreground app, window title, selected items
│                    #   (Explorer), focused control text; graceful fallback to title-only
├── ocr.py           # Windows.Media.Ocr (winrt) primary → Tesseract fallback; cached per frame-hash
├── vlm.py           # local VLM bridge (Ollama: qwen2.5-vl / moondream) — ONLY on demand or
│                    #   for "scene understanding" events; auto-detected availability
├── timeline.py      # screen-event store (vault.db tables: screen_events(hash, ts, app, title,
│                    #   ocr_text, embed, frame_path)) + retention policy (default 7d)
├── watcher.py       # background daemon: capture loop → diff → ground (UIA+OCR) → index (FTS+vec)
│                    #   pause on fullscreen/games/sensitive apps (deny-list), privacy kill-switch
└── service.py       # CLI + tool handlers + confirmation UX
```

**Key design rule — the perception ladder** (cheapest sufficient layer wins):
`foreground title` (0ms) → `UIA structured text` (~50ms) → `OCR` (~200-500ms) → `local VLM` (~1-3s, on demand). The model gets a compact `[SCREEN CONTEXT]` block, not a screenshot — unless it asks for pixels via a tool.

## 4. The agent-loop upgrade (multi-tool chaining + "report back" feel)

This fixes the latency pain you named, and it's required for chaining:

1. **Parallel tool execution** — when the model returns multiple tool calls in one turn, run them concurrently (`asyncio.gather` + `asyncio.to_thread` per tool) instead of sequentially. Result list returned to the model in one shot.
2. **Live tool progress panel** — every tool run renders in a persistent Rich panel that streams status lines (`vault: parsing lease.pdf… chunk 47/120…`) as the tool runs. The model isn't the only narrator anymore; the UI reports back in real time.
3. **Streaming continuation** — the moment tool results land, the next model call streams; first sentence renders + (future: TTS) while the rest generates.
4. **Chaining affordances** — tools can enqueue follow-up tools via a `chain` hint in their result (`{"result": ..., "chain": "vault_status:doc_id=3"}`), so long pipelines don't waste a model round-trip per step. The model still gets the final transcript.
5. **Speculative grounding** — in chat, BEFORE the model answers, Zumba attaches cheap context for free: foreground app/title + recent screen events when the user says "this", "that", "my screen". Deterministic trigger list, zero extra model calls.
6. **Local mini-router (phase 3, optional)** — a tiny local model (Ollama qwen2.5:0.5b) pre-decides obvious tool calls in ~100ms; results are ready when the big model's turn starts. The "instant answers" mode.

## 5. UX surfaces

1. **CLI**
   ```
   zumba eyes status                 # daemon state, capture stats, privacy settings
   zumba eyes start|stop             # run the screen-watcher daemon (default off!)
   zumba eyes now                    # one-shot: ground the current screen (title/UIA/OCR/VLM ladder)
   zumba eyes ask "..."              # search the screen timeline ("that error from earlier")
   zumba eyes deny <app|title>       # privacy deny-list (auto-paused apps)
   zumba eyes retention <days>       # default 7
   ```
2. **In-chat**: `/eyes` (ground now, show panel), `/eyes vlm` (force VLM read), `/eyes off`.
3. **Model tools** (builtin layer, `zumba__eyes_*`):
   - `eyes_screen` — ground the current screen now (ladder; `depth: title|uia|ocr|vlm`)
   - `eyes_history` — `query`, `when` → search screen-event timeline (like memory recall)
   - `eyes_window_list` — all open windows/titles (cheap, for "what am I doing" questions)
4. **The magic phrases**: "this file", "these tabs", "the error on my screen", "what was I doing when X" — all resolve via `[SCREEN CONTEXT]` + `eyes_history` without the user ever naming a path.

## 6. Privacy & safety (non-negotiable, Rewind/Recall lessons)

- **OFF by default.** Continuous capture only runs via explicit `zumba eyes start`.
- Deny-list apps never captured (banking, password managers — seeded with common ones); auto-pause on fullscreen video/games and when the lock screen is active.
- Frames kept only as long as retention says (default 7d); OCR text kept, PNG frames optionally (off by default) — text is what's searchable anyway.
- Kill-switches: `ZUMBA_NO_EYES=1` (whole feature), `ZUMBA_NO_EYES_HISTORY=1` (on-demand only), tray-ish CLI status always visible in `/tools` and `zumba eyes status`.
- All storage under `~/.zumba/` like everything else; nothing leaves the machine except the text the model is explicitly given.

## 7. Config & tunables

| Env var | Default | Meaning |
|---|---|---|
| `ZUMBA_NO_EYES` | `0` | `1` = whole feature off (tools, CLI, daemon) |
| `ZUMBA_NO_EYES_HISTORY` | `0` | `1` = on-demand grounding only, no timeline |
| `ZUMBA_EYES_POLL_S` | `1.0` | screen-poll interval in watcher mode |
| `ZUMBA_EYES_DIFF_THRESHOLD` | `0.02` | perceptual-hash diff to count as "changed" |
| `ZUMBA_EYES_RETENTION_DAYS` | `7` | screen-event TTL |
| `ZUMBA_EYES_STORE_FRAMES` | `0` | keep PNG frames (off = OCR text only) |
| `ZUMBA_EYES_OCR_BACKEND` | `auto` | `winrt` / `tesseract` / `rapidocr` / `auto` |
| `ZUMBA_EYES_VLM` | `auto` | Ollama VLM model for deep reads (`qwen2.5-vl:3b` etc.) |
| `ZUMBA_EYES_DENY_APPS` | (seeded list) | comma list of exe/window-title patterns to never capture |
| `ZUMBA_EYES_MAX_TOOL_PARALLEL` | `4` | cap for parallel tool execution |
| `ZUMBA_AGENT_PARALLEL_TOOLS` | `1` | enable the parallel tool-execution upgrade |

## 8. Tests (`tests/test_eyes_*.py`, `tests/test_agent_parallel.py`)

- capture: fake mss frames; perceptual-hash change detection (same frame → skipped, changed → event).
- uia: mocked window tree → title/app/selected-items extraction; UIA unavailable → title-only fallback, no crash.
- ocr: fixture image via mocked backend; backend failure → graceful `ERROR:` string.
- perception ladder: cheap layer satisfying the request → expensive never invoked.
- timeline: index + `eyes_history` recall (FTS + vector), retention purge, deny-app filtering.
- tools: `eyes_screen`/`eyes_history`/`eyes_window_list` builtin dispatch; `ZUMBA_NO_EYES=1` hides them.
- agent loop: multiple tool calls in one model turn → executed concurrently (order-independent, timing-asserted), results returned in one message; `chain` hints enqueued; progress callbacks fire.
- privacy: deny-listed app produces zero events even in watcher mode.

## 9. Rollout phases

1. **Phase 1 — on-demand eyes + parallel agent loop** (the big wins, no daemon):
   `capture.py` + `uia.py` + ladder (`title → uia → ocr`), `[SCREEN CONTEXT]` injection, `eyes_screen`/`eyes_window_list` tools, `/eyes` command, parallel tool execution + live progress panel. Screen understanding works today, history comes later.
2. **Phase 2 — timeline**: `watcher.py` daemon (event-driven), `timeline.py` store + `eyes_history` tool + `zumba eyes ask`, retention + deny-lists, OCR cache.
3. **Phase 3 — deep vision + chaining polish**: VLM ladder top (`eyes_screen depth=vlm`), `chain` hints, local mini-router speculative tools, TTS-ready streaming (sentence-chunked output events), "see → act" recipes (e.g. screen → detect PDFs → auto-suggest vault add).

## 10. New dependencies

`mss` (screenshots), `uiautomation` (UIA tree), `winrt-Windows.Media.Ocr` (Windows OCR; pure fallback: `rapidocr-onnxruntime` or Tesseract), `pillow` (likely already transitively present), optional `dxcam` (fast GPU capture) and Ollama for local VLM. Watcher uses stdlib (`threading` + `ctypes` Win32) — no heavyweight deps.


Let me break down ZUMBA EYES in plain terms — no jargon dump, just how the thing actually works when you press enter.

## The two halves

**Half 1: EYES (seeing)** — a perception pipeline
**Half 2: Agent loop upgrade (acting)** — parallel tools + live reporting

---

## Half 1: How Zumba "sees" your screen

It does NOT record video. It's a ladder of tricks, cheapest first:

**Rung 0 — Window title (0ms, basically free)**
Windows tells any app what's in focus. Zumba asks: *"Chrome — INVOICE_2026.pdf"*. That alone answers "what am I looking at" 40% of the time.

**Rung 1 — UI Automation tree (~50ms)**
This is the secret weapon. Every normal Windows app (Explorer, Notepad, browsers, Office) exposes its UI as a **structured tree** — the same thing screen readers for blind users use. Zumba doesn't look at pixels; it literally asks Windows:
- "What's the foreground window?" → File Explorer
- "What items are selected in it?" → `lease.pdf`, `invoice.pdf`, `contract.pdf`
- "What text is in the focused control?" → selected paragraph, terminal error text

This is why your example works so cleanly. When you say *"add these files to the vault"*, Zumba doesn't need to "see" anything — Windows already told it the exact file paths you selected. It's like having the answer key, not guessing from a screenshot.

**Rung 2 — OCR (~200-500ms, only if UIA came up empty)**
Some apps (games, PDF viewers rendering as images, remote desktop) expose nothing via UIA. Then Zumba takes a screenshot with `mss` and runs Windows' built-in OCR to read the text off it.

**Rung 3 — Local VLM (~1-3s, only on demand)**
If someone asks something *visual* — "is there a red error dialog on my screen?" — Zumba sends the screenshot to a small local vision model (Qwen2.5-VL via Ollama). Expensive, so it only fires when you explicitly ask or the lower rungs fail.

**The rule: cheapest rung that answers wins.** You asking "add these files" never touches OCR or VLM — the whole perception costs ~50ms.

---

## What happens with your exact example, step by step

```
You:  "add these files to the vault"   (3 PDFs selected in Explorer)

1. PERCEIVE   → foreground title + UIA tree  (~50ms)
              → learns: Explorer, 3 selected paths

2. RESOLVE    → "these files" is ambiguous to a computer.
              → Zumba matches the phrase against what it just saw
              → shows:  Add 3 files to Vault? [Enter]     ← 1-line confirm, not a form

3. CHAIN      → vault add <3 paths>     ── runs ──→ panel streams:
                                          "parsing lease.pdf… chunk 47/120…"
                                          "indexed 214 chunks"
              → vault status            ── confirms

4. ANSWER     → "Done. 3 docs, 214 chunks indexed. Want summaries of each?"
```

---

## Half 2: Why it feels instant (the latency fix)

Your current agent loop is a **relay race**: model thinks → calls tool 1 → waits → gets result → model thinks → calls tool 2 → waits → model writes answer. Every "waits" is dead time, and you stare at a spinner.

Three changes:

**a) Parallel tools** — when the model wants 3 things, they run at the same time (like ordering all dishes at once instead of one at a time). One round trip instead of three.

**b) Live progress panels** — today, when a tool runs for 8 seconds you see *nothing*. New version: a Rich panel streams the tool's progress (`chunk 47/120`) while it works. You're never in the dark — the tool "reports back" as it goes. That's the exact feel you asked for.

**c) Chain hints** — some sequences are predictable. When `vault add` finishes, it can hint "next logical step: vault status" and the loop runs it immediately instead of wasting a full model round-trip to decide the obvious. The model still sees everything at the end.

---

## Half 3 (optional, later): the timeline

With `zumba eyes start`, a quiet daemon runs the capture loop in the background — but **only stores events when the screen changes** (it compares a perceptual hash of each frame; identical screens = skip). Everything OCR'd gets embedded into the same search index as your memory. That's what unlocks *"what was that error I saw an hour ago?"* — it's a text search over your screen history, not a video playback.

Privacy: it's **off by default**, never captures deny-listed apps (banking, password managers), text kept 7 days, frames discarded unless you opt in.

---

**TL;DR:** Zumba doesn't watch pixels like a human — it asks Windows for structured facts (title → UIA → OCR → VLM, cheapest first), resolves your vague words ("these files") against those facts, then executes tools in parallel with live progress streaming. The screen part is *knowing where you are*; the speed part is *never waiting serially and never going silent*.