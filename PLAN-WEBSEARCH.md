# PLAN: God-Tier Realtime Web Search Tool for Zumba

> Status: PLANNED (not yet implemented)
> Goal: give Zumba a first-class, **zero-API-key** web search + fetch capability — realtime news, general web results, and full-page reading — exposed as built-in tools, CLI commands, and in-chat commands.

---

## 1. Why (the problem)

Today Zumba only reaches the internet through:
- `shell_run` (curl in PowerShell — clunky, no parsing, no caching)
- MCP servers (`mcp_search` → install a fetcher — needs npx/network/restart)

The model has **no native web tool**. Questions about "what happened today" fail or hallucinate. This plan adds a built-in web layer that follows all existing Zumba conventions (`mcpclient/builtin.py` meta-tools, `ERROR:` prefix, `ZUMBA_NO_*` kill-switch, head+tail truncation, pytest coverage).

## 2. Research summary (keyless realtime sources)

All verified against live docs / reverse-engineering write-ups (SearXNG engine docs, NewsCatcher's Google News RSS reference — re-tested August 2026):

| Source | Endpoint | Auth | Notes |
|---|---|---|---|
| **DuckDuckGo Web (no-JS)** | `POST https://html.duckduckgo.com/html/` (form: `q`, `kl`=region, `df`=freshness `d`/`w`/`m`/`y`; fallback `https://lite.duckduckgo.com/lite`) | none | HTML scrape; results in `a.result__a` (href is `//duckduckgo.com/l/?uddg=<urlencoded>`) + `.result__snippet`. DDG bot-blocker checks User-Agent — must send browser-like UA + `Sec-Fetch` headers; detect CAPTCHA page and fall back to other engines. |
| **Google News RSS (realtime)** | `GET https://news.google.com/rss/search?q=<query+operators>&hl=en-US&gl=US&ceid=US:en` | none | Operators: `when:1h/12h/1d/7d/1y`, `after:YYYY-MM-DD`, `before:YYYY-MM-DD`, `site:host.com`, `intitle:`, `inurl:`, `around:N`, `-term`, exact `"phrases"`. Items: `<title>`, `<link>`, `<pubDate>`, `<source>`, `<description>`. ~100 items max. Still working Aug 2026. |
| **Hacker News (Algolia)** | `GET https://hn.algolia.com/api/v1/search?query=...&tags=story&numericFilters=created_at_i>UNIX` | none | JSON; tech/dev/launches; native date filters. |
| **Wikipedia** | `GET https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srsearch=...&srlimit=N` | none | JSON; encyclopedic grounding. |
| **Reddit public JSON** | `GET https://www.reddit.com/search.json?q=...&limit=N&sort=new&t=week` | none (needs honest UA) | Realtime chatter; strict rate limits → low priority + cached. |
| **Page reader** | direct `GET` + HTML→text extraction (strip script/style/nav/footer, collapse whitespace) | none | Fallback superpath: `https://r.jina.ai/<url>` free reader endpoint when local extraction is thin. |

**Keyless optional upgrades** (phase 3, off by default): public SearXNG instance; Brave/Tavily keys via env — a `backend` registry keeps paid engines to ~30 lines each.

## 3. Architecture

New module **`websearch.py`** (root, sibling of `shelltool.py`), wired into the existing meta-tool layer:

```
websearch.py              # the engine (no MCP imports — pure functions)
├── enabled()             # ZUMBA_NO_WEB kill-switch
├── _http_get/_post       # requests + browser UA + retry (429/503 + Retry-After) + timeout
├── backends
│   ├── search_ddg(query, freshness, region, limit)   → [Result]
│   ├── news_gnews(query, when, limit)                → [Result]   (Google News RSS, stdlib xml)
│   ├── search_wikipedia(query, limit)                → [Result]
│   ├── search_hn(query, when, limit)                 → [Result]
│   └── search_reddit(query, when, limit)             → [Result]   (best-effort)
├── search(query, backend="auto", when=None, limit)   # "auto" = fused: DDG + Wikipedia (+HN if tech-y);
│                                                     # threads, URL dedupe, per-source tags
├── news(query, when="1d", limit)                     # realtime news via Google News RSS
├── fetch(url, max_chars, raw=False)                  # GET → readable text (head+tail truncate)
├── cache                                             # TTL cache (in-process dict + timestamp;
│                                                     #   optional disk mirror under ~/.zumba/webcache/)
└── format_*()                                        # plain-text renderers for model + Rich tables for CLI
```

Registration in `mcpclient/builtin.py` (same pattern as `shell_run`):

| Tool | Args | Behavior |
|---|---|---|
| `zumba__web_search` | `query`*, `backend` (`auto\|web\|wikipedia\|hn\|reddit`), `when` (`1h\|1d\|7d\|30d\|1y`), `limit` | Fused results: `[i] title — source (date) / snippet / URL`. Model uses this for any "latest/current/what's happening" question. |
| `zumba__web_news` | `query`*, `when` (default `1d`), `limit` | Realtime Google News RSS: title/source/date/link. |
| `zumba__web_fetch` | `url`*, `max_chars` (default `ZUMBA_WEB_MAX_OUTPUT`=8000) | Downloads URL, extracts readable text, head+tail truncation. God-mode parity with shell. |

Kill-switch: `visible_tools()` filters all three when `ZUMBA_NO_WEB=1` (mirrors `ZUMBA_NO_SHELL=1`). `handle()` dispatches via `asyncio.to_thread` (HTTP is blocking) and returns `ERROR: ...` strings on failure — never crashes the chat.

## 4. Config & tunables (env-overridable, `defaults.py` style)

| Env var | Default | Meaning |
|---|---|---|
| `ZUMBA_NO_WEB` | `0` | `1` hides web tools entirely (CLI + chat + model) |
| `ZUMBA_WEB_TIMEOUT` | `20` | per-request HTTP timeout (s) |
| `ZUMBA_WEB_MAX_OUTPUT` | `8000` | chars returned to model (head+tail, like shell) |
| `ZUMBA_WEB_CACHE_TTL` | `300` | seconds a search/fetch result is reused |
| `ZUMBA_WEB_RETRIES` | `1` | retries on 429/503 (honors `Retry-After`, capped 20s) |
| `ZUMBA_WEB_REGION` | `wt-wt` | DDG `kl` region / News locale derived from it |
| `ZUMBA_WEB_JINA_FALLBACK` | `1` | use `r.jina.ai/<url>` reader when extraction is thin |
| `ZUMBA_WEB_BRAVE_KEY` etc. | empty | optional paid engines (phase 3) |

## 5. UX surfaces

1. **Model tools** — the 3 built-ins above; extend the system preamble note: *"web_search/web_news/web_fetch are your realtime internet — use them for anything time-sensitive instead of guessing; web_fetch the top result for depth."*
2. **CLI**: `python main.py web search "..." [--backend auto] [--when 7d] [--limit 8]`, `python main.py web news "..." [--when 1d]`, `python main.py web fetch <url> [--raw] [--max-chars N]` — Rich tables/panels via `output.py`.
3. **In-chat**: `/search <q>`, `/news <q>`, `/fetch <url>` — live, bypass the model (like `/shell`).
4. **`/tools` and `zumba mcp tools`** automatically show the new tools (flow through `builtin.visible_tools()`).

## 6. Anti-fragility details

- **DDG CAPTCHA/anomaly detection**: bot-blocker marker in response → try `lite.duckduckgo.com`, then drop to Wikipedia+News fusion with a `"(DDG blocked; partial results)"` note — never an empty answer.
- **Cache-first**: same `query+backend+when` within TTL returns cached (marked `(cached 3m ago)`); fetch cache keyed by URL+max_chars.
- **Dedupe & fuse**: URL-normalize (strip `utm_*`, trailing `/`), RRF-lite order: DDG → News (if `when` or newsy query) → Wikipedia → HN → Reddit; interleave, cap at `limit`.
- **Header hygiene**: browser-like UA + `Accept-Language: en-US` + `Sec-Fetch-*` for DDG; honest `zumba/1.0` UA for Wikipedia/News RSS/Reddit.
- **Output truncation**: head 80% + tail 20% with `[…truncated N chars…]` (same algorithm as `shelltool`).
- **No LLM in the loop** — deterministic web layer; the model synthesizes (matches Zumba's memory-recall philosophy).

## 7. Tests (`tests/test_websearch.py`)

Mocked `requests` via monkeypatch (same style as existing tests):
- DDG HTML parse fixture → titles/URLs (decoded `uddg=`), snippets, CAPTCHA fallback path.
- Google News RSS XML fixture → items with source/date, `when:` operator injection, bad XML → graceful error.
- `search(auto)` fusion: URL dedupe, `limit` respected, source tags, one backend failing doesn't kill the search.
- `fetch`: HTML → readable text; JSON passthrough; timeout/HTTP error → `ERROR:` string; head+tail truncation; Jina fallback when text too short.
- Cache: second call within TTL doesn't re-hit HTTP (call counter).
- `builtin.visible_tools()` filters web tools on `ZUMBA_NO_WEB=1`; `handle()` dispatch works (async).

## 8. Rollout phases

1. **Phase 1 (core)** — `websearch.py` (DDG + Google News + Wikipedia + fetch + cache), builtin tools, CLI + `/search`, tests, README/.env.example docs.
2. **Phase 2 (realtime+)** — HN + Reddit backends, `when` threading everywhere, Jina reader fallback, disk cache mirror, newsy-query auto-escalation.
3. **Phase 3 (optional polish)** — paid-engine registry (Brave/Tavily), DDG image/video (`i.js`/`v.js` need the `vqd` token dance), stock/crypto via free endpoints, `web_read` multi-URL batch tool, memory integration (save interesting findings as notes through the existing memory pipeline).


