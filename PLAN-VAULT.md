# PLAN: "THE VAULT" — God-Tier Local Document RAG for Zumba

> Status: PLANNED (not yet implemented)
> Idea: drop any file into `~/.zumba/vault/` (or point Zumba at folders) and it becomes **instantly answerable** — "what does my lease say about pets?", "summarize the contract I signed in March", "find the email where the client approved the design".
> Built ON TOP of the existing memory stack (bge-small ONNX embedder, FTS5, sqlite-vec, PageRank, temporal KG) instead of bolting on a second RAG system.

---

## 1. Why this is god tier, not "just RAG"

Most personal RAG tools do: chunk → embed → top-k → stuff context. That's 2023. The Vault is designed as a **document brain**:

| Ordinary RAG | The Vault |
|---|---|
| Dumb fixed-size chunks | **Structure-aware chunking** (headings/paragraphs via `pymupdf4llm` markdown) |
| One embedding per chunk | **Multi-representation indexing** (chunk + section-summary + doc-summary + hypothetical questions per chunk) |
| Vector search only | **4-way hybrid**: vector KNN + BM25 (existing FTS) + graph expansion (existing PPR) + recency/importance |
| Chunks retrieved blind | **Small-to-big retrieval**: search child chunks, inject the *parent section* (Anthropic contextual-retrieval pattern) |
| Flat pile of pages | **RAPTOR-lite hierarchy**: LLM-written section + doc summaries, so "what is this doc about?" hits summaries, not chunk 47 of 300 |
| Static corpus | **Living vault**: filesystem watcher, incremental re-index on change, content-hash dedupe |
| "Here are 5 chunks" | **Citations with receipts**: every claim gets `doc → page → exact quote`, rendered as a Rich panel |
| Separate search from memory | **Unified recall**: Vault chunks live in the SAME knowledge graph as conversations — "what did I read about X" and "what did I tell you about X" answer in one query |

Killer UX: **`zumba vault watch`** — you never "upload" anything. Save a file anywhere in a watched folder; seconds later Zumba knows it.

## 2. Research notes (what SOTA says, 2025-26)

- **pymupdf4llm** (PyMuPDF ≥1.24): PDF → clean **markdown** locally (headings, tables, reading order), no API. Handles EPUB/XPS/CBZ; DOCX/PPTX via python-docx/python-pptx; HTML/std txt. OCR fallback per-page with `get_textpage_ocr()` (Tesseract) only where extraction is empty.
- **Anthropic Contextual Retrieval** (2024, still the best recipe): prepend a 1-2 sentence LLM-written *context* line to each chunk before embedding ("This chunk is from the insurance section of Alice's lease, discussing pet policy") → ~35-49% fewer retrieval failures with hybrid BM25+rerank.
- **Small-to-big / parent-document retrieval**: embed small chunks (~350 tok) for precision, return the parent section (~1-2k tok) for context. One `parent_id` column.
- **Multi-representation indexing**: index hypothetical questions per chunk ("Can I have a dog?") alongside the chunk text — catches vocabulary mismatch, the #1 naive-RAG killer.
- **RAPTOR**: recursive summarize into a tree; conceptual questions answered from summaries beat chunk-only. Lite version: doc-summary + section-summaries (no clustering math at personal scale).
- **Reranking**: local cross-encoder (bge-reranker-base ONNX, ~280MB) reranking top-40 → top-6 is the single biggest quality jump per CPU-ms; fits the existing fastembed/ONNX pattern.

## 3. Architecture

New package **`vault/`** (sibling of `memory/`), reusing `memory/db.py` infra:

```
vault/
├── db.py            # vault.db in ~/.zumba/: docs, sections, chunks, vault_fts
│                    #   docs(hash, path, mtime, kind, title, n_pages, summary, embed, status)
│                    #   sections(id, doc_id, heading, level, summary, embed, parent_id)  ← RAPTOR-lite
│                    #   chunks(id, doc_id, section_id, parent_id, ordinal, text, embed,
│                    #            context_line, hyp_questions, hyp_embeds, fts_rowid)
├── ingest.py        # watch/scan pipeline: stat → hash → parse → chunk → embed → index
│                    #   queue w/ back-pressure, incremental (changed files only), graceful pause
├── parsers.py       # pdf→md (pymupdf4llm), docx/pptx/xlsx/html/md/txt/eml; OCR fallback
├── chunker.py       # markdown-heading-aware splitter (~350 tok, 80 overlap, never splits table/code)
├── context.py       # LLM context lines + hypothetical questions (batched, cheap model, 429-aware)
├── summarize.py     # RAPTOR-lite: doc + section summaries, stored + embedded
├── rerank.py        # local bge-reranker ONNX cross-encoder (optional, auto-download)
├── retrieve.py      # THE ENGINE (see §6)
└── service.py       # orchestrator + CLI + in-chat surface
```

All local: `~/.zumba/vault.db` + `~/.zumba/vault/raw/` (markdown cache per doc so parsing never repeats). Offline after ingest — same philosophy as memory.

## 4. UX surfaces

1. **CLI**
   ```
   zumba vault add <path|glob>      # ingest now (files OR whole folders)
   zumba vault watch [paths...]     # install + run filesystem watcher (saved to config)
   zumba vault status               # docs, chunks, index health, last scan
   zumba vault ask "..."            # standalone retrieval+answer (streams, cites)
   zumba vault find "..."           # retrieval only, no LLM (raw hits, like memory search)
   zumba vault doc <id|title>       # inspect one doc: summary, outline, chunk stats
   zumba vault reindex --all        # full rebuild
   zumba vault forget <id|title>    # remove doc + all embeddings
   ```
2. **In-chat** — Vault is *always on* in recall: the memory-recall step also calls `vault.retrieve()` for document-ish questions; packed as a second system block `[VAULT CONTEXT]` with citations. Commands: `/vault ask|find|add|status|doc`.
3. **Model tools** (builtin layer, same as shell/web tools):
   - `zumba__vault_search` — `query`*, `doc_filter`, `k` → ranked hits with exact quotes/citations
   - `zumba__vault_doc` — `doc`* → full outline + summary (drill-in)
   - `zumba__vault_read` — `doc`, `section` → full section text (the "turn the page" tool)
4. **Answer style**: system-preamble rule — every document claim must cite `[Doc Title p.4 §Insurance]`.

## 5. Config & tunables

| Env var | Default | Meaning |
|---|---|---|
| `ZUMBA_NO_VAULT` | `0` | `1` = feature off entirely |
| `ZUMBA_VAULT_PATHS` | `~/.zumba/vault` | default watch targets (comma list) |
| `ZUMBA_VAULT_CHUNK_TOKENS` | `350` | target chunk size (80 overlap) |
| `ZUMBA_VAULT_TOP_K` | `6` | sections injected into context |
| `ZUMBA_VAULT_BUDGET` | `4000` | token budget for `[VAULT CONTEXT]` |
| `ZUMBA_VAULT_RERANK` | `1` | local cross-encoder reranker on/off |
| `ZUMBA_VAULT_HYDE` | `0` | HyDE-lite query expansion (more accurate, slower) |
| `ZUMBA_VAULT_CONTEXT_LINES` | `1` | LLM contextual-retrieval lines (auto-off without API key) |
| `ZUMBA_VAULT_OCR` | `1` | Tesseract OCR fallback for scanned PDFs |
| `ZUMBA_VAULT_MAX_FILE_MB` | `100` | ignore giant files |

## 6. The retrieval engine, step by step

```
query "can my landlord raise the rent mid-lease?"
 1. rewrite (optional HyDE-lite): embed query + 3 hypothetical answer snippets
 2. candidate pools (parallel):
      - vector KNN over chunks, hypothetical questions, and section summaries
      - BM25 over vault_fts (chunk text + context lines + titles)
      - doc-title/summary match (question about a whole doc → return its outline)
 3. reciprocal-rank fusion (reuse the memory stack's RRF)
 4. cross-encoder rerank top-40 → top-6 (skippable)
 5. expand each hit chunk to its PARENT SECTION (small-to-big)
 6. graph boost: chunk mentions an entity in the memory KG → PPR bump
    (this is the "what I read + what I told Zumba" unification)
 7. pack to token budget (reuse context_budget.fit), each block carries:
      [Vault Lease Agreement 2026 — p.4 §Rent — quote: "..."]
 8. inject as [VAULT CONTEXT] system block; preamble instructs citation
```

Graceful degradation at every step: no reranker → skip; no API key → no context lines/hyp questions; no watcher → `add` still works; corrupt PDF → logged + `status: failed`, never crashes chat.

## 7. Tests (`tests/test_vault_*.py`)

- parsers: PDF fixture → markdown with headings; DOCX; HTML; corrupt file → failed status, no crash.
- chunker: heading boundaries respected; table/code blocks never split; overlap present; token estimates.
- retrieval: synthetic vault → known-question hits right chunk; vocabulary-mismatch case solved by hypothetical-question index; small-to-big returns parent section; dedupe; budget respected.
- RRF fusion + reranker off/on parity (mocked rerank scores).
- incremental ingest: same file re-stat → skipped (hash); changed file → re-chunked, old chunks deleted.
- citations format `[Title p.N §Heading]`; `[VAULT CONTEXT]` block injection into chat turn.
- `ZUMBA_NO_VAULT=1` hides tools + skips recall hook.

## 8. Rollout phases

1. **Phase 1 — core RAG**: parsers (PDF/DOCX/MD/TXT/HTML), chunker, vault.db schema, embed, hybrid retrieve (vector+BM25+RRF), CLI `add/find/ask/status/forget`, `[VAULT CONTEXT]` in chat, tests.
2. **Phase 2 — the smart stuff**: contextual-retrieval lines, hypothetical-question index, RAPTOR-lite summaries, small-to-big, `vault_search/vault_doc/vault_read` builtin tools, `/vault` command.
3. **Phase 3 — living vault**: filesystem watcher daemon, OCR fallback, local cross-encoder reranker, HyDE-lite, memory-KG graph boost, eval harness (recall@k on a golden QA set, same pattern as `memory eval`).

## 9. New dependencies

`pymupdf4llm` (pulls pymupdf), `python-docx`, `python-pptx`, `openpyxl`, optional `watchdog` (watcher), optional `onnxruntime` cross-encoder (reuse fastembed's). All local, no API keys.


