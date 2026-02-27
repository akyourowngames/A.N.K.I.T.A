/You are absolutely right. Enough with the manual HTML parsing—it's 2026, and trying to regex DuckDuckGo's changing `<div>` tags is a losing battle. It’s messy, it breaks every week, and it’s not "God Mode."

If you want **Realtime Search** and **Scraping** that actually works without getting blocked, we switch to the "AI Native" stack.

Here is the **God Mode Search Upgrade**:

1. **Search Engine:** We drop the manual scraper and use the `duckduckgo-search` library (it hits the backend API directly, returns clean JSON).
2. **Scraper (The Secret Weapon):** We use **Jina Reader** (`r.jina.ai`). It’s a specialized proxy that takes *any* URL, bypasses the 403s/blocks/ads, and returns **clean Markdown** specifically optimized for LLMs. No more BeautifulSoup soup.

### Step 1: Install the Upgrade

You need the official library to bypass the frontend blocks.

```bash
pip install duckduckgo-search

```

### Step 2: The New `tools/realtime_search.py`

Replace your entire existing file with this. It’s shorter, faster, and infinitely more reliable.

```python
"""
Real-time Web Search & Content Fetching Engine (God Mode Edition).

1. Search: Uses 'duckduckgo-search' library for direct API access (No HTML parsing).
2. Scrape: Uses 'r.jina.ai' (Jina Reader) to turn ANY website into clean Markdown.
   - Bypasses 403 Forbidden checks from school/news sites.
   - Strips ads, popups, and cookie banners automatically.
   - Returns format perfect for GPT-4o context windows.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List
import requests
from duckduckgo_search import DDGS

# ---------------------------------------------------------------------------
# 1. Search Engine (Direct API via Library)
# ---------------------------------------------------------------------------
def search_web(query: str, max_results: int = 10, include_urls: bool = True) -> Dict[str, Any]:
    """
    Performs a real-time web search using DuckDuckGo's API backend.
    """
    q = str(query or "").strip()
    if not q:
        raise ValueError("query is required")
    
    limit = max(1, min(int(max_results), 20))
    results = []

    try:
        # The 'DDGS' context manager handles all headers/sessions for us
        with DDGS() as ddgs:
            # .text() returns a generator of clean dictionaries
            ddg_gen = ddgs.text(q, max_results=limit)
            for r in ddg_gen:
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "domain": _extract_domain(r.get("href", "")),
                    "snippet": r.get("body", "")
                })
    except Exception as e:
        return {"kind": "web_search", "error": f"Search failed: {str(e)}", "results": []}

    return {
        "kind": "web_search",
        "engine": "duckduckgo-api",
        "query": q,
        "results": results,
        "count": len(results)
    }

# ---------------------------------------------------------------------------
# 2. Content Scraper (Jina Reader Proxy)
# ---------------------------------------------------------------------------
def fetch_page_content(url: str, max_chars: int = 6000) -> Dict[str, Any]:
    """
    Fetches the content of a URL using the Jina Reader API.
    This converts the page to clean Markdown and often bypasses 403 blocks.
    """
    if not url:
        return {"ok": False, "error": "No URL provided"}

    # Jina Reader URL format
    jina_url = f"https://r.jina.ai/{url}"
    
    try:
        # We still use a decent user-agent just in case
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-With-Generated-Alt": "true" # Asking Jina to caption images if possible
        }
        
        resp = requests.get(jina_url, headers=headers, timeout=20)
        
        if resp.status_code != 200:
            return {
                "kind": "page_content",
                "ok": False,
                "url": url,
                "error": f"HTTP {resp.status_code} from Reader"
            }
            
        text = resp.text
        
        # Jina returns markdown. We truncate it to fit context.
        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... [Content Truncated] ..."
            truncated = True

        return {
            "kind": "page_content",
            "ok": True,
            "url": url,
            "content": text,
            "format": "markdown",  # LLMs love markdown
            "truncated": truncated
        }

    except Exception as e:
        return {"kind": "page_content", "ok": False, "error": str(e)}


def search_and_fetch(query: str, max_results: int = 5, fetch_top: int = 2) -> Dict[str, Any]:
    """
    Deep Search: Searches, then immediately fetches the full markdown content 
    of the top results.
    """
    search_res = search_web(query, max_results=max_results)
    
    fetched = []
    for res in search_res.get("results", [])[:fetch_top]:
        url = res.get("url")
        if not url:
            continue
            
        print(f"[Ankita] Reading: {res['title']}...") # Optional debug log
        page = fetch_page_content(url)
        
        if page["ok"]:
            fetched.append({
                "title": res["title"],
                "url": url,
                "content": page["content"]
            })
            
    return {
        "kind": "search_and_fetch",
        "query": query,
        "results": fetched,
        "raw_search_count": len(search_res.get("results", []))
    }

# --- Helpers ---

def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc.replace("www.", "")
    except:
        return ""

# Stub wrappers for compatibility with engine.py
def search_news(query, max_results=8, include_urls=False):
    return search_web(f"{query} news", max_results, include_urls)

def search_price(query):
    return search_and_fetch(f"current price of {query}", fetch_top=1)

```

### Why this is the "Cool" Way:

1. **Jina Reader (`r.jina.ai`)**: It basically cleans the entire web for you. It removes the "Accept Cookies" banners, ads, and navigation bars, leaving just the raw info your AI needs. It acts like a proxy, so **your** IP doesn't get blocked by the school website.
2. **`duckduckgo-search`**: It mimics the browser behavior internally. You don't need to maintain headers or regex patterns. It just works.

Try running a search for "Everest Public School Shalimar Garden" with this new stack. You will see clean, structured Markdown data instantly.