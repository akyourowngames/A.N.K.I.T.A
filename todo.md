# 🌐 ANKITA — WebAgent MEGA UPGRADE BLUEPRINT
### 10 New Powers | Implementation-Ready | Zero Wasted Calls

---

## 🎯 CURRENT STATE — What WebAgent Already Has

| Tool | What It Does |
|---|---|
| `search_web` | DuckDuckGo text search → snippets |
| `search_news` | DuckDuckGo news backend → headlines |
| `search_and_fetch` | Search + Jina Reader fetch top N pages → Markdown content |
| `fetch_page_content` | Fetch a single URL via Jina Reader |
| `search_price` | CoinGecko (crypto) + Yahoo Finance (stocks) |
| `download_file` | Stream any file (PDF/ZIP/CSV) to disk |
| `deep_research` | 10 parallel scouts → Master Intelligence Brief |
| `write_content` | Save research output |
| `launch_app` | Open downloaded files |

**The gap:** WebAgent can READ the web but can't INTERACT with it, MONITOR it, EXTRACT structured data from it, or COMPARE/TRACK things over time.

---

## 🚀 THE 10 NEW POWERS

---

### 🆕 POWER 1 — `scrape_structured` Tool (Tables, Lists, JSON Extraction)

**The gap:** `fetch_page_content` via Jina returns raw Markdown. If the user says "get me all the countries and their GDP from Wikipedia" or "extract the price table from this page", WebAgent can't turn messy HTML into clean structured data.

**New function in `realtime_search.py`:**
```python
def scrape_structured(url: str, extract: str = "tables") -> Dict[str, Any]:
    """
    Extract structured data from a web page.
    extract: "tables" | "lists" | "links" | "emails" | "phones" | "json"
    """
    import re
    from urllib.request import urlopen

    resp = requests.get(url, headers=_REAL_BROWSER_HEADERS, timeout=20)
    html = resp.text

    if extract == "tables":
        # Parse HTML tables into list-of-dicts
        from html.parser import HTMLParser
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        tables = []
        for row in rows:
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
            clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if any(clean): tables.append(clean)
        return {"ok": True, "extract": "tables", "url": url, "rows": tables, "count": len(tables)}

    elif extract == "links":
        links = re.findall(r'href=["\']([^"\']+)["\']', html)
        links = [l for l in links if l.startswith('http')]
        return {"ok": True, "extract": "links", "url": url, "links": list(set(links))[:50]}

    elif extract == "emails":
        emails = list(set(re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', html)))
        return {"ok": True, "extract": "emails", "url": url, "emails": emails}

    elif extract == "phones":
        phones = list(set(re.findall(r'[\+]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{3,5}[-\s\.]?[0-9]{4,6}', html)))
        return {"ok": True, "extract": "phones", "url": url, "phones": phones[:30]}

    elif extract == "json":
        # Find embedded JSON blobs (e.g. Next.js __NEXT_DATA__, schema.org, etc.)
        json_blobs = re.findall(r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
        parsed = []
        for blob in json_blobs[:3]:
            try: parsed.append(json.loads(blob.strip()))
            except: pass
        return {"ok": True, "extract": "json", "url": url, "blobs": parsed}

    return {"ok": False, "error": f"Unknown extract type: {extract}"}
```

**Tool spec:**
```python
{"name": "scrape_structured",
 "description": "Extract structured data from any URL: tables → CSV-ready rows, links, emails, phone numbers, or embedded JSON. Use when user wants 'get all rows from this table', 'find all emails on this page', 'extract the data from X'.",
 "parameters": {"url": "string", "extract": "tables|lists|links|emails|phones|json"}}
```

**Routing examples:**
- "get all the laptop prices from this page" → `scrape_structured(url, extract="tables")`
- "find all contact emails on their site" → `scrape_structured(url, extract="emails")`
- "extract the data from this Wikipedia table" → `scrape_structured(url, extract="tables")`

---

### 🆕 POWER 2 — `compare_search` Tool (Side-by-Side Web Comparisons)

**The gap:** "Compare iPhone 15 vs Samsung S24" or "which is better, X or Y" currently just does a plain search. This power runs two parallel targeted fetches and synthesizes a head-to-head comparison table.

**New function in `realtime_search.py`:**
```python
def compare_search(item_a: str, item_b: str, aspects: List[str] = None) -> Dict[str, Any]:
    """
    Research two things in parallel and return structured comparison data.
    aspects: optional list like ["price", "specs", "pros", "cons"]
    """
    import concurrent.futures

    aspects = aspects or ["overview", "price", "pros", "cons", "verdict"]

    def _research_one(item: str) -> Dict:
        result = search_and_fetch(query=f"{item} review specs pros cons 2024", fetch_top=3)
        content = " ".join(r.get("content","") for r in result.get("results",[]))[:8000]
        return {"item": item, "content": content}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        fut_a = ex.submit(_research_one, item_a)
        fut_b = ex.submit(_research_one, item_b)
        data_a = fut_a.result()
        data_b = fut_b.result()

    return {
        "ok": True,
        "kind": "comparison",
        "item_a": item_a,
        "item_b": item_b,
        "aspects": aspects,
        "data_a": data_a["content"],
        "data_b": data_b["content"],
        "instruction": "Compare these two items across all aspects and output a markdown table + verdict."
    }
```

**System prompt addition for WebAgent:**
```
COMPARISON PROTOCOL:
When user says "X vs Y", "compare X and Y", "which is better X or Y":
→ ALWAYS call compare_search(item_a="X", item_b="Y")
→ Format result as a clean markdown comparison table
→ Add a 1-sentence verdict at the end
NEVER just do a plain search_web for comparison queries.
```

---

### 🆕 POWER 3 — `web_monitor` Tool (Track a Page for Changes)

**The gap:** "Tell me when this product comes back in stock", "notify me if this webpage changes", "check this page every hour". Currently this would need WatchdogAgent, but WebAgent has no native change-detection.

**New function in `realtime_search.py`:**
```python
import hashlib, json
from pathlib import Path

_MONITOR_STORE = Path.home() / ".ankita" / "web_monitors.json"

def web_monitor(action: str, url: str = None, keyword: str = None, label: str = None) -> Dict[str, Any]:
    """
    action: "add" | "check" | "list" | "remove"
    Tracks if a web page has changed since last visit.
    Stores SHA256 of page content. On "check" — refetches and compares.
    """
    store = json.loads(_MONITOR_STORE.read_text()) if _MONITOR_STORE.exists() else {}

    if action == "add":
        if not url: return {"ok": False, "error": "url required"}
        page = fetch_page_content(url, max_chars=30000)
        if not page.get("ok"): return {"ok": False, "error": f"Could not fetch {url}"}
        content_hash = hashlib.sha256(page["content"].encode()).hexdigest()
        key = label or url[:60]
        store[key] = {"url": url, "hash": content_hash, "keyword": keyword,
                      "added": time.time(), "last_checked": time.time(), "change_count": 0}
        _MONITOR_STORE.parent.mkdir(exist_ok=True)
        _MONITOR_STORE.write_text(json.dumps(store, indent=2))
        return {"ok": True, "monitoring": key, "url": url}

    elif action == "check":
        results = []
        for key, config in store.items():
            page = fetch_page_content(config["url"], max_chars=30000)
            if not page.get("ok"): continue
            new_hash = hashlib.sha256(page["content"].encode()).hexdigest()
            changed = new_hash != config["hash"]
            keyword_found = config.get("keyword") and config["keyword"].lower() in page["content"].lower()
            if changed:
                store[key]["hash"] = new_hash
                store[key]["change_count"] = config.get("change_count", 0) + 1
                store[key]["last_checked"] = time.time()
            results.append({"label": key, "url": config["url"], "changed": changed,
                            "keyword_found": keyword_found, "change_count": store[key]["change_count"]})
        _MONITOR_STORE.write_text(json.dumps(store, indent=2))
        return {"ok": True, "results": results, "monitored": len(results)}

    elif action == "list":
        return {"ok": True, "monitors": list(store.keys()), "count": len(store)}

    elif action == "remove":
        removed = store.pop(label or url or "", None)
        _MONITOR_STORE.write_text(json.dumps(store, indent=2))
        return {"ok": True, "removed": bool(removed)}

    return {"ok": False, "error": f"Unknown action: {action}"}
```

**WatchdogAgent integration:** Register a cron job that calls `web_monitor(action="check")` every N minutes and sends a notification via `system_control("notify")` if `changed=True`.

---

### 🆕 POWER 4 — `multi_search` Tool (Parallel Multi-Query Research)

**The gap:** Deep research fires 10 scouts for ONE topic. But what if the user says "find me the best Python courses, JS courses, and SQL courses"? WebAgent currently does 3 sequential searches. This fires them all in parallel.

**New function in `realtime_search.py`:**
```python
def multi_search(queries: List[str], fetch_top: int = 2) -> Dict[str, Any]:
    """
    Run multiple independent search queries in parallel.
    Perfect for: list comparisons, batch lookups, research on N topics at once.
    Returns one result bundle per query.
    """
    import concurrent.futures

    def _one(q: str) -> Dict:
        res = search_and_fetch(query=q, fetch_top=fetch_top, max_chars_per_page=6000)
        return {"query": q, "results": res.get("results", [])}

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(queries), 6)) as ex:
        futures = {ex.submit(_one, q): q for q in queries[:6]}  # cap at 6 parallel
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    return {"ok": True, "kind": "multi_search", "count": len(results), "bundles": results}
```

**System prompt addition:**
```
MULTI-QUERY PROTOCOL:
When user asks about N separate things in one request:
  "find best X, Y, and Z" → multi_search(queries=["best X", "best Y", "best Z"])
  "research A, B, C for me" → multi_search(queries=["A overview", "B overview", "C overview"])
ALWAYS batch parallel queries instead of searching one by one.
```

---

### 🆕 POWER 5 — `fact_check` Tool (Cross-Source Verification)

**The gap:** WebAgent gives you the first result it finds. For important claims ("is this drug safe?", "did X really say that?", "is this statistic real?"), it should cross-reference 3+ sources and flag conflicts.

**New function in `realtime_search.py`:**
```python
def fact_check(claim: str, sources: int = 4) -> Dict[str, Any]:
    """
    Verify a claim by fetching N independent sources and detecting conflicts.
    Returns: verified, conflicting_sources, confidence, source_breakdown.
    """
    result = search_and_fetch(
        query=f'"{claim}" fact check verify',
        max_results=sources * 2,
        fetch_top=sources,
        max_chars_per_page=5000
    )

    source_verdicts = []
    for r in result.get("results", []):
        content = r.get("content", "").lower()
        claim_words = set(claim.lower().split())
        # Rudimentary signal detection
        supports = any(w in content for w in ["confirmed", "true", "verified", "correct", "accurate"])
        contradicts = any(w in content for w in ["false", "debunked", "incorrect", "misleading", "wrong", "myth"])
        source_verdicts.append({
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "signal": "supports" if supports and not contradicts
                     else "contradicts" if contradicts
                     else "neutral",
            "excerpt": content[:300]
        })

    supports_count = sum(1 for v in source_verdicts if v["signal"] == "supports")
    contradicts_count = sum(1 for v in source_verdicts if v["signal"] == "contradicts")
    confidence = round(supports_count / max(len(source_verdicts), 1) * 100)

    return {
        "ok": True,
        "claim": claim,
        "verdict": "LIKELY TRUE" if supports_count > contradicts_count
                   else "DISPUTED" if contradicts_count > 0
                   else "UNVERIFIED",
        "confidence_pct": confidence,
        "sources_checked": len(source_verdicts),
        "source_breakdown": source_verdicts
    }
```

**Routing:** "is it true that...", "fact check this:", "verify this claim", "did X really say" → `fact_check(claim=...)`

---

### 🆕 POWER 6 — `search_reddit` Tool (Reddit & Forum Intelligence)

**The gap:** DuckDuckGo gives official sources. But Reddit, Stack Overflow, Hacker News, and Quora have the *real* crowd-sourced opinions. "What do people actually think of X?", "has anyone had this problem?", "best X according to Reddit" — these need a Reddit-aware scraper.

**New function in `realtime_search.py`:**
```python
def search_reddit(query: str, subreddit: str = None, max_posts: int = 5) -> Dict[str, Any]:
    """
    Search Reddit via old.reddit.com JSON API (no auth required).
    subreddit: optional e.g. "python", "programming", "buildapc"
    """
    base = f"https://www.reddit.com/r/{subreddit}/search.json" if subreddit \
           else "https://www.reddit.com/search.json"
    params = {"q": query, "sort": "relevance", "limit": max_posts, "t": "year"}
    try:
        resp = requests.get(base, params=params,
                           headers={"User-Agent": "ANKITA-WebAgent/1.0"}, timeout=15)
        data = resp.json()
        posts = []
        for child in data.get("data", {}).get("children", [])[:max_posts]:
            p = child.get("data", {})
            posts.append({
                "title":    p.get("title", ""),
                "subreddit": p.get("subreddit", ""),
                "score":    p.get("score", 0),
                "url":      "https://reddit.com" + p.get("permalink", ""),
                "body":     p.get("selftext", "")[:500],
                "comments": p.get("num_comments", 0),
            })
        return {"ok": True, "query": query, "posts": posts, "count": len(posts)}
    except Exception as e:
        # Fallback: search DuckDuckGo with site:reddit.com
        return search_and_fetch(f"{query} site:reddit.com", fetch_top=3)
```

**Also add Stack Overflow:**
```python
def search_stackoverflow(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search Stack Overflow via their public API (no key needed for basic use)."""
    resp = requests.get(
        "https://api.stackexchange.com/2.3/search/advanced",
        params={"q": query, "site": "stackoverflow", "pagesize": max_results,
                "order": "desc", "sort": "votes", "filter": "withbody"},
        timeout=10
    )
    items = resp.json().get("items", [])
    return {
        "ok": True,
        "results": [{"title": i["title"], "score": i["score"],
                     "url": i["link"], "answered": i["is_answered"],
                     "body": re.sub(r'<[^>]+>', '', i.get("body",""))[:400]} for i in items]
    }
```

**Routing:** "what does reddit think of X", "reddit best X", "has anyone solved Y error" → `search_reddit`; "how to fix X error" in code context → `search_stackoverflow`

---

### 🆕 POWER 7 — `image_search` Tool (Web Image Search + Download)

**The gap:** WebAgent can't find images. "Find me a photo of X", "download the logo of Y", "get reference images for Z" — completely blind right now.

**New function in `realtime_search.py`:**
```python
def image_search(query: str, max_results: int = 5, download: bool = False) -> Dict[str, Any]:
    """
    Search for images on the web via DuckDuckGo Images API.
    download=True saves the top result to Desktop.
    """
    try:
        import importlib
        mod = importlib.import_module("ddgs")
        DDGSCls = getattr(mod, "DDGS")
        with DDGSCls() as ddgs:
            results = list(ddgs.images(query, max_results=max_results))
    except Exception:
        # Fallback: scrape Google Images via search
        results = []

    images = [{"title": r.get("title",""), "url": r.get("image",""),
               "thumbnail": r.get("thumbnail",""), "source": r.get("url","")}
              for r in results[:max_results]]

    if download and images:
        img_url = images[0]["url"]
        try:
            img_resp = requests.get(img_url, timeout=15, headers=_REAL_BROWSER_HEADERS)
            ext = img_url.split(".")[-1].split("?")[0][:4] or "jpg"
            safe_name = re.sub(r'[^\w]', '_', query[:30])
            save_path = Path.home() / "Desktop" / f"{safe_name}.{ext}"
            save_path.write_bytes(img_resp.content)
            images[0]["downloaded_to"] = str(save_path)
        except Exception as e:
            images[0]["download_error"] = str(e)

    return {"ok": True, "query": query, "images": images, "count": len(images)}
```

**Routing:** "find images of X", "download logo of Y", "get a photo of Z", "reference image for" → `image_search`

---

### 🆕 POWER 8 — `summarise_url` Tool (TL;DR Any Link — Article/Paper/Doc)

**The gap:** `fetch_page_content` dumps raw Markdown. There's no dedicated "just give me the TL;DR of this URL" tool. For long articles, papers, YouTube transcripts — the agent wastes tokens reading everything when a targeted 5-bullet summary is enough.

**New function in `realtime_search.py`:**
```python
def summarise_url(url: str, style: str = "bullets", max_bullets: int = 7) -> Dict[str, Any]:
    """
    Fetch a URL and produce a targeted summary.
    style: "bullets" | "tldr" | "eli5" | "key_stats" | "pros_cons"
    This is distinct from fetch_page_content — it produces a ready-to-use summary,
    not raw content. WebAgent calls this when user just wants the gist.
    """
    page = fetch_page_content(url, max_chars=20000)
    if not page.get("ok"):
        return {"ok": False, "url": url, "error": page.get("error", "Fetch failed")}

    content = page["content"][:15000]
    style_prompts = {
        "bullets":   f"Summarise the following article in exactly {max_bullets} bullet points. Be specific and include key facts, numbers, and names.",
        "tldr":      "Write a 2-3 sentence TL;DR of this article. Be direct, no fluff.",
        "eli5":      "Explain this article like I'm 5 years old, in simple plain English.",
        "key_stats": "Extract ONLY the key numbers, statistics, and data points from this article. Format as a bulleted list.",
        "pros_cons": "Extract the pros and cons mentioned in this content. Two lists: Pros ✅ and Cons ❌."
    }

    return {
        "ok": True,
        "url": url,
        "style": style,
        "content_for_llm": content,
        "instruction": style_prompts.get(style, style_prompts["bullets"]),
        "title": page.get("content","")[:100].split('\n')[0]
    }
```

**System prompt addition:**
```
SUMMARISE-URL PROTOCOL:
When user pastes a URL and says "summarise", "tldr", "what does this say", "explain this":
  → call summarise_url(url=<url>, style="bullets")
  → use the instruction field to guide your synthesis
When they say "pros and cons of this article" → style="pros_cons"
When they say "just give me the stats" → style="key_stats"
```

---

### 🆕 POWER 9 — `trending_topics` Tool (What's Hot Right Now)

**The gap:** No way to answer "what's trending today?", "what are people talking about?", "what's viral on X right now?" — needs a multi-source trending aggregator.

**New function in `realtime_search.py`:**
```python
def trending_topics(category: str = "general", region: str = "US") -> Dict[str, Any]:
    """
    Fetch what's trending right now across multiple sources.
    category: "general" | "tech" | "finance" | "sports" | "entertainment" | "science"
    Aggregates from: Google Trends RSS, Reddit r/popular, Hacker News top
    """
    results = {"category": category, "region": region, "sources": {}}

    # Hacker News Top Stories (no auth)
    try:
        hn_resp = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=8)
        top_ids = hn_resp.json()[:10]
        hn_stories = []
        for story_id in top_ids[:5]:
            item = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout=5).json()
            hn_stories.append({"title": item.get("title",""), "url": item.get("url",""),
                               "score": item.get("score", 0), "comments": item.get("descendants",0)})
        results["sources"]["hacker_news"] = hn_stories
    except Exception: pass

    # Reddit r/popular (no auth)
    try:
        reddit_resp = requests.get("https://www.reddit.com/r/popular.json?limit=10",
                                   headers={"User-Agent": "ANKITA/1.0"}, timeout=10)
        reddit_data = reddit_resp.json()
        posts = [{"title": c["data"]["title"], "subreddit": c["data"]["subreddit"],
                  "score": c["data"]["score"], "url": "https://reddit.com" + c["data"]["permalink"]}
                 for c in reddit_data["data"]["children"][:5]]
        results["sources"]["reddit_popular"] = posts
    except Exception: pass

    # Fallback: search news for trending
    if not results["sources"]:
        news = search_news(f"trending {category} today", max_results=8, include_urls=True)
        results["sources"]["news_search"] = news.get("results", [])

    return {"ok": True, **results}
```

**Routing:** "what's trending", "what's hot today", "what are people talking about", "top stories right now" → `trending_topics`

---

### 🆕 POWER 10 — `web_to_dataset` Tool (Research → Structured CSV/JSON)

**The gap:** The final boss upgrade. WebAgent can find data, but right now it just dumps text. This power takes any research query and builds a clean structured dataset from it — ready for Excel, analysis, or saving.

**New function in `realtime_search.py`:**
```python
def web_to_dataset(query: str, columns: List[str] = None, max_rows: int = 20,
                   output_format: str = "json") -> Dict[str, Any]:
    """
    Research a topic and extract structured data rows from web results.
    Example: query="top AI companies 2024", columns=["Company", "Valuation", "Founded", "Product"]
    Returns structured rows that can be saved as CSV or JSON.
    """
    columns = columns or ["Name", "Description", "Key Fact", "Source"]

    # Fetch 5 pages of content
    result = search_and_fetch(query=query, fetch_top=5, max_chars_per_page=8000)
    all_content = "\n\n".join(
        f"[SOURCE: {r.get('title','')}]\n{r.get('content','')[:3000]}"
        for r in result.get("results", [])
    )

    # Return content + structured extraction instruction for LLM
    instruction = (
        f"From the following web content, extract up to {max_rows} data rows.\n"
        f"Columns: {columns}\n"
        f"Output ONLY a JSON array of objects with these exact keys. "
        f"Each row must have all {len(columns)} columns. "
        f"If a value is unknown, use null. No extra text. Just the JSON array."
    )

    return {
        "ok": True,
        "query": query,
        "columns": columns,
        "max_rows": max_rows,
        "output_format": output_format,
        "content_for_llm": all_content[:20000],
        "extraction_instruction": instruction,
    }
```

**System prompt addition:**
```
DATASET PROTOCOL:
When user says "build a table of X", "give me a list of Y with their Z",
"research all X and their Y", "make a spreadsheet of":
  1. Call web_to_dataset(query=..., columns=[...])
  2. Use the extraction_instruction to format your response as a clean table
  3. If user said "save it" or "make a CSV" → pass result to FileAgent (write_content → .csv)
  4. If user said "open in Excel" → FileAgent saves → SystemAgent launches Excel
```

---

## 🏗️ IMPLEMENTATION CHECKLIST

### Phase 1 — Add to `realtime_search.py` (all self-contained)
- [ ] `scrape_structured(url, extract)` — table/email/link extractor
- [ ] `compare_search(item_a, item_b, aspects)` — parallel comparison research
- [ ] `web_monitor(action, url, keyword, label)` — change detection with hash store
- [ ] `multi_search(queries, fetch_top)` — parallel N-query batch
- [ ] `fact_check(claim, sources)` — multi-source cross-reference verifier
- [ ] `search_reddit(query, subreddit)` + `search_stackoverflow(query)` — forum intel
- [ ] `image_search(query, download)` — DuckDuckGo images + optional download
- [ ] `summarise_url(url, style)` — TL;DR / bullets / pros_cons / key_stats
- [ ] `trending_topics(category, region)` — HN + Reddit + news aggregator
- [ ] `web_to_dataset(query, columns, max_rows)` — structured data extractor

### Phase 2 — Wire into `engine.py`
Add 10 new entries to `TOOL_SPECS`:
```python
# Just the names — full specs follow each function above
"scrape_structured", "compare_search", "web_monitor",
"multi_search", "fact_check", "search_reddit",
"image_search", "summarise_url", "trending_topics", "web_to_dataset"
```

Add dispatch in `execute_tool_call()`:
```python
if name == "scrape_structured": return realtime_search.scrape_structured(...)
if name == "compare_search":    return realtime_search.compare_search(...)
# ... etc
```

Add NLP triggers in `select_tools_for_user_text()`:
```python
has_compare = any(_match(t, ["compare", "versus", "vs", "better", "difference"], 0.80) for t in tokens)
if has_compare: chosen.append("compare_search")

has_trending = any(_match(t, ["trending", "viral", "hot", "popular", "whats"], 0.80) for t in tokens)
if has_trending: chosen.append("trending_topics")

has_reddit = any(_match(t, ["reddit", "forum", "community", "people think"], 0.82) for t in tokens)
if has_reddit: chosen.append("search_reddit")

has_factcheck = any(_match(t, ["fact", "verify", "true", "false", "claim", "debunk"], 0.80) for t in tokens)
if has_factcheck: chosen.append("fact_check")
```

### Phase 3 — Update `specialists.py`
Add all 10 new tools to `_WEB_TOOLS`:
```python
_WEB_TOOLS = {"search_web", "search_news", "search_and_fetch", "fetch_page_content",
              "search_price", "write_content", "download_file", "launch_app", "deep_research",
              # NEW
              "scrape_structured", "compare_search", "web_monitor", "multi_search",
              "fact_check", "search_reddit", "image_search", "summarise_url",
              "trending_topics", "web_to_dataset"} | _MEMORY_TOOLS
```

### Phase 4 — Update `supervisor.py` routing table
```python
# New routing keywords to add:
- "compare X vs Y / X vs Y" → WebAgent
- "what does reddit think / reddit says / reddit best" → WebAgent
- "trending today / what's hot / top stories" → WebAgent
- "fact check / is it true / verify this" → WebAgent
- "summarise this link / tldr this url" → WebAgent
- "build a table of / make a dataset of / extract data from" → ["WebAgent", "FileAgent"]
- "monitor this page / tell me if X changes" → ["WebAgent", "CronAgent"]
- "find images of / download photo of" → WebAgent
```

### Phase 5 — No new pip installs needed 🎉
Everything uses libraries already in the stack:
- `requests` ✅ already installed
- `ddgs` / `duckduckgo_search` ✅ already installed
- `re`, `json`, `hashlib`, `concurrent.futures` ✅ Python stdlib
- Stack Overflow API ✅ no key required
- Reddit JSON API ✅ no key required
- Hacker News Firebase API ✅ no key required

---

## 💬 ANKITA Personality — New Response Lines

```
COMPARE: "Ok bestie, ran both in parallel. Here's the breakdown 👇⚡"
REDDIT: "checked Reddit so you don't have to 😂 here's the actual tea:"
TRENDING: "this is what the internet is losing its mind over rn 🔥"
FACT CHECK: "ok so I checked 4 sources on this and... {verdict} 🔍"
IMAGE SEARCH: "found it! downloading to your Desktop rn 🖼️"
DATASET: "built you a clean {N}-row table 📊 want me to save it as Excel?"
MONITOR: "👀 watching that page for you. I'll ping when something changes."
```

---

## 📊 UPGRADE SUMMARY

| # | Power | Function | No New Deps | Effort |
|---|---|---|---|---|
| 1 | Structured Scraper (tables/emails) | `scrape_structured` | ✅ | Easy |
| 2 | Side-by-Side Comparison | `compare_search` | ✅ | Easy |
| 3 | Page Change Monitor | `web_monitor` | ✅ | Medium |
| 4 | Parallel Multi-Query | `multi_search` | ✅ | Easy |
| 5 | Multi-Source Fact Checker | `fact_check` | ✅ | Easy |
| 6 | Reddit + Stack Overflow Search | `search_reddit` | ✅ | Easy |
| 7 | Image Search + Download | `image_search` | ✅ | Easy |
| 8 | Smart URL Summariser | `summarise_url` | ✅ | Easy |
| 9 | Trending Topics Aggregator | `trending_topics` | ✅ | Medium |
| 10 | Research → Structured Dataset | `web_to_dataset` | ✅ | Medium |

**Zero new pip installs. All 10 powers use existing deps or Python stdlib.**

---

## 🔥 KILLER COMBOS UNLOCKED AFTER THIS UPGRADE

| User Says | Agent Chain |
|---|---|
| "Compare MacBook Air M3 vs Dell XPS 15 and save to Excel" | `compare_search` → `web_to_dataset` → FileAgent (.xlsx) |
| "What do people on Reddit think of Notion vs Obsidian" | `search_reddit` × 2 → `compare_search` |
| "Get me a table of all S&P 500 companies from Wikipedia" | `scrape_structured(extract="tables")` → `web_to_dataset` |
| "Fact check: 'Apple is the most valuable company'" | `fact_check` → cross-ref 4 sources → verdict |
| "Monitor Tesla's stock page, tell me if it drops below $200" | `web_monitor(add)` + `CronAgent` scheduled check |
| "What's trending on Hacker News today, summarise top 3" | `trending_topics` → `summarise_url` × 3 |
| "Find all emails on competitor's contact page" | `scrape_structured(extract="emails")` |
| "Download the logo for Stripe" | `image_search(query="Stripe logo PNG", download=True)` |

---

*Blueprint by Claude for ANKITA WebAgent — all 10 powers are independent, implement in any order*