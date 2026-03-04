"""
Real-time Web Search & Content Fetching Engine — God Mode Edition.

Stack:
  1. Search  — 'duckduckgo-search' library for direct API access.
               No HTML parsing. No regex. No 403s. Just clean JSON.
  2. Scrape  — Jina Reader (r.jina.ai) proxy converts ANY URL to clean Markdown.
               Bypasses cookie banners, login walls, school/news site 403s.
               Returns format perfectly sized for GPT-4o context windows.
  3. Prices  — CoinGecko REST API (crypto) + Yahoo Finance scrape (stocks)
               before falling back to search_and_fetch.

Install:
    pip install duckduckgo-search
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import warnings
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlencode

import requests

# Suppress SSL warnings for scraping
warnings.filterwarnings('ignore', message='Unverified HTTPS request')
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared requests.Session — reuse TCP connections across all search calls
# ---------------------------------------------------------------------------
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
})

# ---------------------------------------------------------------------------
# Real browser headers for fallback HTML scraping (used in Try 3 & 4)
# ---------------------------------------------------------------------------
_REAL_BROWSER_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ---------------------------------------------------------------------------
# Simple token-bucket rate limiter — max 50 search calls/min
# ---------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self, max_calls: int = 50, period: float = 60.0) -> None:
        self._lock = threading.Lock()
        self._calls: List[float] = []
        self._max = max_calls
        self._period = period

    def acquire(self) -> None:
        with self._lock:
            now = time.time()
            # Evict calls outside the rolling window
            self._calls = [t for t in self._calls if now - t < self._period]
            if len(self._calls) >= self._max:
                # Sleep until the oldest call falls outside the window
                sleep_for = self._period - (now - self._calls[0])
                if sleep_for > 0:
                    time.sleep(sleep_for)
                self._calls = [t for t in self._calls if time.time() - t < self._period]
            self._calls.append(time.time())

_rate_limiter = _RateLimiter(max_calls=50, period=60.0)

# ---------------------------------------------------------------------------
# Dynamic CoinGecko coin list — fetched once, then cached to disk
# ---------------------------------------------------------------------------
_COINS_CACHE_PATH = os.path.join(os.path.dirname(__file__), ".coingecko_coins.json")
_coins_lock = threading.Lock()
_coins_cache: Optional[Dict[str, str]] = None  # symbol/name → coingecko_id

def _load_coingecko_coins() -> Dict[str, str]:
    """Return a mapping of coin name/symbol → CoinGecko ID.
    Fetches from CoinGecko /coins/list on first call, then caches to disk for 24h.
    Falls back to the hardcoded dict on any failure.
    """
    global _coins_cache
    with _coins_lock:
        if _coins_cache is not None:
            return _coins_cache

        # Try disk cache first (valid for 24h)
        import json
        try:
            cache_data = json.loads(open(_COINS_CACHE_PATH, encoding="utf-8").read())
            if isinstance(cache_data, dict) and cache_data.get("_ts", 0) > time.time() - 86400:
                _coins_cache = {k: v for k, v in cache_data.items() if k != "_ts"}
                log.debug("[CoinGecko] Loaded %d coins from disk cache.", len(_coins_cache))
                return _coins_cache
        except Exception:
            pass

        # Fetch live from CoinGecko
        try:
            resp = _SESSION.get(
                "https://api.coingecko.com/api/v3/coins/list",
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            coins = resp.json()  # list of {id, symbol, name}
            mapping: Dict[str, str] = {}
            for c in coins:
                cid = str(c.get("id", "")).strip()
                sym = str(c.get("symbol", "")).strip().lower()
                name = str(c.get("name", "")).strip().lower()
                if cid and sym:
                    mapping[sym] = cid
                if cid and name:
                    mapping[name] = cid
            # Save to disk
            cache_out = dict(mapping)
            cache_out["_ts"] = time.time()  # type: ignore[assignment]
            try:
                with open(_COINS_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(cache_out, f)
            except Exception:
                pass
            _coins_cache = mapping
            log.debug("[CoinGecko] Fetched %d coin entries from API.", len(mapping))
            return mapping
        except Exception as err:
            log.warning("[CoinGecko] Failed to fetch coin list: %s. Using hardcoded fallback.", err)

    # Hardcoded fallback
    _coins_cache = {
        "bitcoin": "bitcoin",       "btc": "bitcoin",
        "ethereum": "ethereum",     "eth": "ethereum",
        "solana": "solana",         "sol": "solana",
        "dogecoin": "dogecoin",     "doge": "dogecoin",
        "cardano": "cardano",       "ada": "cardano",
        "ripple": "ripple",         "xrp": "ripple",
        "litecoin": "litecoin",     "ltc": "litecoin",
        "polkadot": "polkadot",     "dot": "polkadot",
        "chainlink": "chainlink",   "link": "chainlink",
        "avalanche": "avalanche-2", "avax": "avalanche-2",
        "polygon": "matic-network", "matic": "matic-network",
        "shiba": "shiba-inu",       "shib": "shiba-inu",
        "binancecoin": "binancecoin", "bnb": "binancecoin",
        "tron": "tron",             "trx": "tron",
        "toncoin": "the-open-network", "ton": "the-open-network",
    }
    return _coins_cache


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _jina_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "X-With-Generated-Alt": "true",   # Ask Jina to caption images
        "X-Return-Format": "markdown",    # Explicit markdown format request
    }


# ---------------------------------------------------------------------------
# 1. Search Engine — DuckDuckGo via library (direct API, no HTML scraping)
# ---------------------------------------------------------------------------

def search_web(
    query: str,
    max_results: int = 10,
    include_urls: bool = True,
) -> Dict[str, Any]:
    """
    Real-time web search using the duckduckgo-search library.

    The library handles all authentication, headers, and session management
    internally — no need to maintain HTML parsers or bypass bot detection.

    Args:
        query:       The search query.
        max_results: Maximum number of results to return (capped at 20).
        include_urls: Whether to include URLs in the result dicts.

    Returns:
        Dict with kind, engine, query, results (list), count.
    """
    q = str(query or "").strip()
    if not q:
        raise ValueError("query is required")

    limit = max(1, min(int(max_results), 50))  # increased cap from 20 → 50
    results: List[Dict[str, Any]] = []

    # Apply rate limiting before any external call
    _rate_limiter.acquire()

    # ------------------------------------------------------------------
    # Try 1: ddgs package (new name since 2025)
    # ------------------------------------------------------------------
    try:
        from ddgs import DDGS as NewDDGS  # type: ignore
        with NewDDGS() as ddgs:
            for r in ddgs.text(q, max_results=limit):
                item: Dict[str, Any] = {
                    "title":   r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "domain":  _extract_domain(r.get("href", "")),
                }
                if include_urls:
                    item["url"] = r.get("href", "")
                results.append(item)
        if results:
            return {
                "kind": "web_search",
                "engine": "ddgs-api",
                "query": q,
                "results": results,
                "count": len(results),
            }
    except Exception:
        pass  # Fall through

    # ------------------------------------------------------------------
    # Try 2: old duckduckgo_search package (pre-2025)
    # ------------------------------------------------------------------
    try:
        from duckduckgo_search import DDGS  # type: ignore
        with DDGS() as ddgs:
            for r in ddgs.text(q, max_results=limit):
                item = {
                    "title":   r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "domain":  _extract_domain(r.get("href", "")),
                }
                if include_urls:
                    item["url"] = r.get("href", "")
                results.append(item)
        if results:
            return {
                "kind": "web_search",
                "engine": "duckduckgo-api",
                "query": q,
                "results": results,
                "count": len(results),
            }
    except Exception:
        pass  # Fall through

    # ------------------------------------------------------------------
    # Try 3: DuckDuckGo HTML scrape (most stable — no package dependency)
    # ------------------------------------------------------------------
    ddg_url = f"https://html.duckduckgo.com/html/?{urlencode({'q': q, 'kl': 'us-en'})}"
    try:
        resp = requests.get(ddg_url, timeout=30, headers=_REAL_BROWSER_HEADERS)
        resp.raise_for_status()
        parser = _DuckResultParser()
        parser.feed(resp.text)
        for row in parser.results[:limit]:
            item = _base_result(title=row["title"], url=row["url"], snippet="")
            if include_urls:
                item["url"] = row["url"]
            results.append(item)
        if results:
            return {
                "kind": "web_search",
                "engine": "duckduckgo-html",
                "query": q,
                "include_urls": bool(include_urls),
                "results": results,
            }
    except Exception:
        pass  # Fall through

    # ------------------------------------------------------------------
    # Try 4: Google udm=14 scrape (no API key, Web-only tab)
    # ------------------------------------------------------------------
    try:
        from urllib.parse import unquote
        google_url = f"https://www.google.com/search?{urlencode({'q': q, 'udm': '14', 'num': limit})}"
        resp = requests.get(google_url, timeout=30, headers=_REAL_BROWSER_HEADERS)
        if resp.status_code == 200:
            google_links = re.findall(r'<a href="/url\?q=([^&"]+)[^"]*"[^>]*>([^<]+)', resp.text)
            for raw_url, raw_title in google_links[:limit]:
                clean_url = unquote(raw_url)
                clean_title = re.sub(r'<[^>]+>', '', raw_title).strip()
                if clean_url.startswith("http") and "google.com" not in clean_url and clean_title:
                    item = _base_result(title=clean_title, url=clean_url, snippet="")
                    if include_urls:
                        item["url"] = clean_url
                    results.append(item)
            if results:
                return {
                    "kind": "web_search",
                    "engine": "google-udm14",
                    "query": q,
                    "include_urls": bool(include_urls),
                    "results": results,
                }
    except Exception:
        pass

    # All sources exhausted
    return {
        "kind": "web_search",
        "engine": "none",
        "query": q,
        "results": [],
        "error": "All search sources failed or returned no results.",
    }


# ---------------------------------------------------------------------------
# 2. Content Scraper — Jina Reader (r.jina.ai)
# ---------------------------------------------------------------------------

def fetch_page_content(
    url: str,
    max_chars: int = 15000,
) -> Dict[str, Any]:
    """
    Fetch and clean the content of any URL using Jina Reader.

    Jina Reader proxies through r.jina.ai which:
    - Returns clean Markdown (perfect for LLM context)
    - Strips ads, cookie banners, nav bars, and popups
    - Bypasses most 403 blocks including school/news sites
    - Handles JavaScript-rendered pages

    Args:
        url:       The URL to fetch.
        max_chars: Maximum characters to return (default 6000).

    Returns:
        Dict with ok, url, content, format, truncated.
    """
    if not url:
        return {"ok": False, "error": "No URL provided"}

    url = str(url).strip()
    jina_url = f"https://r.jina.ai/{url}"

    try:
        resp = requests.get(
            jina_url,
            headers=_jina_headers(),
            timeout=30,  # increased from 20s → 30s for slow pages
        )

        if resp.status_code != 200:
            # Fallback to direct fetch if Jina fails
            log.warning(f"[Jina] HTTP {resp.status_code}, falling back to direct fetch")
            try:
                direct_resp = requests.get(url, headers=_REAL_BROWSER_HEADERS, timeout=15, verify=False)
                if direct_resp.status_code == 200:
                    # Strip HTML tags to get readable text
                    raw = direct_resp.text
                    clean = re.sub(r'<style[^>]*>.*?</style>', ' ', raw, flags=re.DOTALL)
                    clean = re.sub(r'<script[^>]*>.*?</script>', ' ', clean, flags=re.DOTALL)
                    clean = re.sub(r'<[^>]+>', ' ', clean)
                    clean = re.sub(r'\s+', ' ', clean).strip()
                    
                    truncated = False
                    if len(clean) > max_chars:
                        clean = clean[:max_chars] + "\n\n... [Content Truncated] ..."
                        truncated = True
                    
                    return {
                        "kind": "page_content",
                        "ok": True,
                        "url": url,
                        "content": clean,
                        "format": "text",
                        "truncated": truncated,
                        "char_count": len(clean),
                    }
            except Exception:
                pass
            
            return {
                "kind": "page_content",
                "ok": False,
                "url": url,
                "error": f"Jina Reader returned HTTP {resp.status_code} and direct fetch failed",
            }

        text = resp.text
        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n... [Content Truncated — use a larger max_chars if needed] ..."
            truncated = True

        return {
            "kind": "page_content",
            "ok": True,
            "url": url,
            "content": text,
            "format": "markdown",
            "truncated": truncated,
            "char_count": len(text),
        }

    except Exception as err:
        # Final fallback to direct fetch
        try:
            direct_resp = requests.get(url, headers=_REAL_BROWSER_HEADERS, timeout=15, verify=False)
            if direct_resp.status_code == 200:
                raw = direct_resp.text
                clean = re.sub(r'<style[^>]*>.*?</style>', ' ', raw, flags=re.DOTALL)
                clean = re.sub(r'<script[^>]*>.*?</script>', ' ', clean, flags=re.DOTALL)
                clean = re.sub(r'<[^>]+>', ' ', clean)
                clean = re.sub(r'\s+', ' ', clean).strip()
                
                truncated = False
                if len(clean) > max_chars:
                    clean = clean[:max_chars] + "\n\n... [Content Truncated] ..."
                    truncated = True
                
                return {
                    "kind": "page_content",
                    "ok": True,
                    "url": url,
                    "content": clean,
                    "format": "text",
                    "truncated": truncated,
                    "char_count": len(clean),
                }
        except Exception:
            pass
        
        return {"kind": "page_content", "ok": False, "url": url, "error": str(err)}


# ---------------------------------------------------------------------------
# 3. Deep Search — search + immediately fetch top results
# ---------------------------------------------------------------------------

def search_and_fetch(
    query: str,
    max_results: int = 10,
    fetch_top: int = 5,
    max_chars_per_page: int = 15000,  # UPGRADE: Read more text per page for better synthesis
) -> Dict[str, Any]:
    """
    Deep Search: search DuckDuckGo, then fetch the full Markdown content
    of the top N results via Jina Reader.

    Use this when you need the ACTUAL CONTENT of pages, not just snippets.
    Perfect for research, fact-checking, and price lookups.

    Args:
        query:             The search query.
        max_results:       How many search results to get.
        fetch_top:         How many of those to actually fetch full content for.
        max_chars_per_page: Max chars per fetched page.

    Returns:
        Dict with kind, query, results (list with title, url, content),
        raw_search_count.
    """
    search_res = search_web(query, max_results=max_results, include_urls=True)
    fetched: List[Dict[str, Any]] = []

    for res in search_res.get("results", [])[:fetch_top]:
        url = res.get("url", "")
        if not url:
            continue
        title = res.get("title", url)
        log.debug("[ANKITA] 🔍 Reading: %s...", title[:60])

        # Try 1: Jina Reader (clean Markdown, bypasses most 403s)
        page = fetch_page_content(url, max_chars=max_chars_per_page)
        if page.get("ok") and page.get("content", "").strip():
            fetched.append({
                "title":   title,
                "url":     url,
                "content": page.get("content", ""),
            })
            continue

        # Try 2: Direct requests with real browser headers (Jina failed or was blocked)
        try:
            resp = requests.get(url, headers=_REAL_BROWSER_HEADERS, timeout=15)
            if resp.status_code == 200:
                raw = resp.text
                # Strip HTML tags to get readable text
                clean = re.sub(r'<style[^>]*>.*?</style>', ' ', raw, flags=re.DOTALL)
                clean = re.sub(r'<script[^>]*>.*?</script>', ' ', clean, flags=re.DOTALL)
                clean = re.sub(r'<[^>]+>', ' ', clean)
                clean = re.sub(r'\s+', ' ', clean).strip()
                if len(clean) > 200:  # Only accept if we got meaningful content
                    content = clean[:max(max_chars_per_page, 12000)]
                    fetched.append({
                        "title":   title,
                        "url":     url,
                        "content": content,
                    })
                    continue
        except Exception:
            pass

        # Try 3: Use snippet from search result as fallback content
        snippet = res.get("snippet", "").strip()
        if snippet:
            fetched.append({
                "title":   title,
                "url":     url,
                "content": f"[Snippet only — page fetch failed] {snippet}",
            })

    return {
        "kind": "search_and_fetch",
        "query": query,
        "results": fetched,
        "fetched_pages": fetched,   # alias for backward compatibility
        "raw_search_count": len(search_res.get("results", [])),
    }


# ---------------------------------------------------------------------------
# 4. News Search — wrapper around search_web with "news" suffix
# ---------------------------------------------------------------------------

def search_news(
    query: str,
    max_results: int = 8,
    include_urls: bool = False,
) -> Dict[str, Any]:
    """
    Search for recent news using DuckDuckGo news backend.

    Args:
        query:       What to search for.
        max_results: Maximum number of news items.
        include_urls: Whether to include URLs in results.

    Returns:
        Dict with kind, query, results.
    """
    q = str(query or "").strip()
    if not q:
        raise ValueError("query is required")

    limit = max(1, min(int(max_results), 30))  # increased cap from 20 → 30
    results: List[Dict[str, Any]] = []

    # Try ddgs first (new package name), then old duckduckgo_search
    for _pkg, _cls in [("ddgs", "DDGS"), ("duckduckgo_search", "DDGS")]:
        try:
            import importlib
            mod = importlib.import_module(_pkg)
            DDGSCls = getattr(mod, _cls)
            with DDGSCls() as ddgs:
                for r in ddgs.news(q, max_results=limit):
                    item: Dict[str, Any] = {
                        "title":   r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "source":  r.get("source", ""),
                        "date":    r.get("date", ""),
                    }
                    if include_urls:
                        item["url"] = r.get("url", "")
                    results.append(item)
            if results:
                break
        except Exception:
            continue

    if not results:
        # Fallback to search_web with "news" appended
        return search_web(f"{q} news", max_results=limit, include_urls=include_urls)

    return {
        "kind": "news_search",
        "engine": "duckduckgo-news-api",
        "query": q,
        "results": results,
        "count": len(results),
    }


# ---------------------------------------------------------------------------
# 5. Price Search — CoinGecko (crypto) + Yahoo Finance (stocks) + fallback
# ---------------------------------------------------------------------------

def search_price(query: str) -> Dict[str, Any]:
    """
    Fast, reliable price fetcher for crypto and stocks.

    Priority order:
    1. CoinGecko REST API — instant for 16+ major cryptos, no key required
    2. Yahoo Finance HTML scrape — for stock tickers (AAPL, TSLA, etc.)
    3. search_and_fetch fallback — extracts $XX,XXX.XX patterns from web content

    Args:
        query: e.g. "bitcoin", "ethereum", "AAPL", "Tesla stock", "gold price"

    Returns:
        Dict with ok, price, currency, source, summary.
    """
    q = str(query or "").strip().lower()
    if not q:
        raise ValueError("query is required")

    # ------------------------------------------------------------------
    # CoinGecko — crypto prices (dynamic coin list, 16000+ coins supported)
    # ------------------------------------------------------------------
    _COINGECKO_IDS = _load_coingecko_coins()
    
    # Priority matching: exact match first, then word boundary match, then substring
    coin_id = None
    
    # Try exact match first (e.g., "bitcoin" → "bitcoin", not "swapbased-coin")
    coin_id = _COINGECKO_IDS.get(q.lower())
    
    # If no exact match, try word-boundary matching (e.g., "bitcoin price" → "bitcoin")
    if not coin_id:
        for key, cg_id in _COINGECKO_IDS.items():
            # Match if the key appears as a complete word in the query
            if re.search(r'\b' + re.escape(key) + r'\b', q.lower()):
                coin_id = cg_id
                break
    if coin_id:
        try:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"},
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            data = resp.json().get(coin_id, {})
            price = data.get("usd")
            change = data.get("usd_24h_change")
            if price is not None:
                change_str = f" ({change:+.2f}% 24h)" if change is not None else ""
                name = coin_id.replace("-", " ").title()
                return {
                    "ok": True,
                    "query": q,
                    "coin_id": coin_id,
                    "price": price,
                    "currency": "USD",
                    "change_24h": change,
                    "source": "coingecko",
                    "summary": f"{name} is currently ${price:,.2f} USD{change_str}. (Source: CoinGecko)",
                }
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Yahoo Finance — stock tickers
    # ------------------------------------------------------------------
    ticker_match = re.search(r'\b([A-Z]{1,5})\b', query.upper())
    ticker = ticker_match.group(1) if ticker_match else None
    if ticker:
        try:
            resp = requests.get(
                f"https://finance.yahoo.com/quote/{ticker}",
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            if resp.status_code == 200:
                price_match = re.search(
                    r'data-field="regularMarketPrice"[^>]*data-value="([0-9.,]+)"',
                    resp.text,
                )
                if price_match:
                    price_val = float(price_match.group(1).replace(",", ""))
                    return {
                        "ok": True,
                        "query": q,
                        "ticker": ticker,
                        "price": price_val,
                        "currency": "USD",
                        "source": "yahoo_finance",
                        "summary": f"{ticker} is currently trading at ${price_val:,.2f} USD. (Source: Yahoo Finance)",
                    }
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Fallback — search_and_fetch with price regex extraction
    # ------------------------------------------------------------------
    try:
        result = search_and_fetch(
            query=f"{query} price today USD",
            max_results=8,
            fetch_top=3,
            max_chars_per_page=8000,
        )
        all_content = " ".join(p.get("content", "") for p in result.get("results", []))
        price_patterns = re.findall(r'\$[\d,]+(?:\.\d{1,2})?', all_content)
        if price_patterns:
            return {
                "ok": True,
                "query": q,
                "source": "web_scrape",
                "price_mentions": price_patterns[:5],
                "summary": f"Price mentions for '{query}': {', '.join(price_patterns[:5])}",
            }
    except Exception as err:
        pass

    return {
        "ok": False,
        "query": q,
        "source": "none",
        "summary": f"Could not find price for '{query}'. Try a more specific query.",
    }


# ---------------------------------------------------------------------------
# 6. File Downloader — stream any file (PDF, CSV, DOCX, ZIP, etc.) to disk
# ---------------------------------------------------------------------------

def download_file(url: str, save_folder: str = None) -> Dict[str, Any]:
    """
    Downloads a file from a URL to the local disk using a streaming request.

    Features:
    - Anti-bot rotating headers to bypass 403s on download/hosting sites.
    - Smart filename detection from Content-Disposition header.
    - Falls back to the URL tail if header is absent.
    - Infers extension from Content-Type if the URL tail has none.
    - Saves to the user's Downloads folder by default.

    Args:
        url:         The direct URL of the file to download.
        save_folder: Optional absolute path to save the file.
                     Defaults to the user's Downloads folder.

    Returns:
        Dict with ok, path, filename, size_bytes on success,
        or ok=False, error on failure.
    """
    if not url:
        return {"ok": False, "error": "No URL provided"}

    url = str(url).strip()

    # --- Resolve save folder ---
    if save_folder:
        dest_dir = save_folder
    else:
        # Prefer the real user home Downloads folder
        dest_dir = os.path.join(os.path.expanduser("~"), "Downloads")

    os.makedirs(dest_dir, exist_ok=True)

    # --- Anti-bot headers (same pool as rest of the module) ---
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": url,
    }

    # --- Content-Type → file extension mapping ---
    _MIME_EXT: Dict[str, str] = {
        "application/pdf":                                                  ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/msword":                                               ".doc",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-excel":                                         ".xls",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/zip":                                                  ".zip",
        "application/x-zip-compressed":                                     ".zip",
        "application/x-tar":                                                ".tar",
        "application/gzip":                                                 ".gz",
        "text/csv":                                                         ".csv",
        "text/plain":                                                       ".txt",
        "application/json":                                                 ".json",
        "image/png":                                                        ".png",
        "image/jpeg":                                                       ".jpg",
        "image/gif":                                                        ".gif",
        "image/webp":                                                       ".webp",
    }

    try:
        resp = _SESSION.get(url, headers=headers, stream=True, timeout=60, allow_redirects=True)
        resp.raise_for_status()

        # --- Step 1: Try to get filename from Content-Disposition header ---
        filename: Optional[str] = None
        cd = resp.headers.get("Content-Disposition", "")
        if cd:
            # Handles both filename= and filename*=UTF-8''...
            fn_match = re.search(r"filename\*?=['\"]?(?:UTF-8'')?([^'\";\r\n]+)['\"]?", cd, re.IGNORECASE)
            if fn_match:
                filename = fn_match.group(1).strip().strip('"').strip("'")

        # --- Step 2: Fall back to URL tail ---
        if not filename:
            url_path = urlparse(url).path
            filename = os.path.basename(url_path) or "downloaded_file"
            # URL-decode percent-encoded characters
            try:
                from urllib.parse import unquote
                filename = unquote(filename)
            except Exception:
                pass

        # --- Step 3: Ensure the filename has an extension ---
        _, ext = os.path.splitext(filename)
        if not ext:
            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            ext = _MIME_EXT.get(content_type, "")
            if ext:
                filename = filename + ext

        # --- Step 4: Sanitise filename (remove illegal path chars) ---
        filename = re.sub(r'[\\/:*?"<>|]', "_", filename)
        if not filename:
            filename = "downloaded_file"

        save_path = os.path.join(dest_dir, filename)

        # --- Step 5: Stream write to disk ---
        total_bytes = 0
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    total_bytes += len(chunk)

        log.info("[ANKITA] ✅ Downloaded %s → %s (%d bytes)", url, save_path, total_bytes)

        return {
            "ok": True,
            "path": os.path.abspath(save_path),
            "filename": filename,
            "size_bytes": total_bytes,
            "url": url,
            "summary": f"Downloaded '{filename}' ({total_bytes:,} bytes) → {os.path.abspath(save_path)}",
        }

    except requests.HTTPError as err:
        return {"ok": False, "url": url, "error": f"HTTP {err.response.status_code}: {err}"}
    except Exception as err:
        return {"ok": False, "url": url, "error": str(err)}


# ---------------------------------------------------------------------------
# 7. Structured Scraper — Extract tables, emails, links, phones, JSON
# ---------------------------------------------------------------------------

def scrape_structured(url: str, extract: str = "tables") -> Dict[str, Any]:
    """
    Extract structured data from a web page.
    
    Args:
        url: The URL to scrape
        extract: Type of data to extract:
                 "tables" - HTML tables → list of rows
                 "links" - All HTTP/HTTPS links
                 "emails" - Email addresses
                 "phones" - Phone numbers
                 "json" - Embedded JSON blobs (schema.org, Next.js data, etc.)
    
    Returns:
        Dict with ok, extract, url, and extracted data
    """
    if not url:
        return {"ok": False, "error": "No URL provided"}
    
    url = str(url).strip()
    
    try:
        resp = requests.get(url, headers=_REAL_BROWSER_HEADERS, timeout=20, verify=False)
        resp.raise_for_status()
        html = resp.text
        
        if extract == "tables":
            # Parse HTML tables into list-of-dicts
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
            tables = []
            for row in rows:
                cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL | re.IGNORECASE)
                clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                if any(clean):  # Only add non-empty rows
                    tables.append(clean)
            return {
                "ok": True,
                "extract": "tables",
                "url": url,
                "rows": tables,
                "count": len(tables),
                "summary": f"Extracted {len(tables)} table rows from {url}"
            }
        
        elif extract == "links":
            links = re.findall(r'href=["\']([^"\']+)["\']', html)
            links = [l for l in links if l.startswith('http')]
            unique_links = list(dict.fromkeys(links))[:50]  # Dedupe and limit
            return {
                "ok": True,
                "extract": "links",
                "url": url,
                "links": unique_links,
                "count": len(unique_links),
                "summary": f"Found {len(unique_links)} unique links on {url}"
            }
        
        elif extract == "emails":
            emails = list(set(re.findall(
                r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
                html
            )))
            return {
                "ok": True,
                "extract": "emails",
                "url": url,
                "emails": emails,
                "count": len(emails),
                "summary": f"Found {len(emails)} email addresses on {url}"
            }
        
        elif extract == "phones":
            phones = list(set(re.findall(
                r'[\+]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{3,5}[-\s\.]?[0-9]{4,6}',
                html
            )))[:30]
            return {
                "ok": True,
                "extract": "phones",
                "url": url,
                "phones": phones,
                "count": len(phones),
                "summary": f"Found {len(phones)} phone numbers on {url}"
            }
        
        elif extract == "json":
            # Find embedded JSON blobs (Next.js __NEXT_DATA__, schema.org, etc.)
            json_blobs = re.findall(
                r'<script[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>(.*?)</script>',
                html,
                re.DOTALL | re.IGNORECASE
            )
            parsed = []
            import json
            for blob in json_blobs[:3]:
                try:
                    parsed.append(json.loads(blob.strip()))
                except:
                    pass
            return {
                "ok": True,
                "extract": "json",
                "url": url,
                "blobs": parsed,
                "count": len(parsed),
                "summary": f"Extracted {len(parsed)} JSON blobs from {url}"
            }
        
        return {"ok": False, "error": f"Unknown extract type: {extract}"}
    
    except Exception as err:
        return {"ok": False, "url": url, "error": str(err)}


# ---------------------------------------------------------------------------
# 8. Compare Search — Side-by-side parallel research
# ---------------------------------------------------------------------------

def compare_search(
    item_a: str,
    item_b: str,
    aspects: List[str] = None
) -> Dict[str, Any]:
    """
    Research two things in parallel and return structured comparison data.
    
    Args:
        item_a: First item to compare
        item_b: Second item to compare
        aspects: Optional list of aspects to compare (e.g., ["price", "specs", "pros", "cons"])
    
    Returns:
        Dict with comparison data for both items
    """
    import concurrent.futures
    
    aspects = aspects or ["overview", "price", "pros", "cons", "verdict"]
    
    def _research_one(item: str) -> Dict:
        result = search_and_fetch(
            query=f"{item} review specs pros cons 2024",
            fetch_top=3,
            max_chars_per_page=8000
        )
        content = " ".join(
            r.get("content", "") for r in result.get("results", [])
        )[:8000]
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
        "instruction": (
            "Compare these two items across all aspects and output a markdown table + verdict. "
            "Format: | Aspect | Item A | Item B | Winner |"
        ),
        "summary": f"Researched {item_a} vs {item_b} in parallel"
    }


# ---------------------------------------------------------------------------
# 9. Web Monitor — Track page changes
# ---------------------------------------------------------------------------

import hashlib
from pathlib import Path

_MONITOR_STORE = Path.home() / ".ankita" / "web_monitors.json"

def web_monitor(
    action: str,
    url: str = None,
    keyword: str = None,
    label: str = None
) -> Dict[str, Any]:
    """
    Track if a web page has changed since last visit.
    
    Args:
        action: "add" | "check" | "list" | "remove"
        url: URL to monitor (required for add/remove)
        keyword: Optional keyword to watch for (triggers alert when found)
        label: Optional label for the monitor
    
    Returns:
        Dict with action results
    """
    import json
    
    store = json.loads(_MONITOR_STORE.read_text()) if _MONITOR_STORE.exists() else {}
    
    if action == "add":
        if not url:
            return {"ok": False, "error": "url required"}
        
        page = fetch_page_content(url, max_chars=30000)
        if not page.get("ok"):
            return {"ok": False, "error": f"Could not fetch {url}"}
        
        content_hash = hashlib.sha256(page["content"].encode()).hexdigest()
        key = label or url[:60]
        store[key] = {
            "url": url,
            "hash": content_hash,
            "keyword": keyword,
            "added": time.time(),
            "last_checked": time.time(),
            "change_count": 0
        }
        _MONITOR_STORE.parent.mkdir(exist_ok=True)
        _MONITOR_STORE.write_text(json.dumps(store, indent=2))
        return {
            "ok": True,
            "monitoring": key,
            "url": url,
            "summary": f"Now monitoring {key} for changes"
        }
    
    elif action == "check":
        results = []
        for key, config in store.items():
            page = fetch_page_content(config["url"], max_chars=30000)
            if not page.get("ok"):
                continue
            
            new_hash = hashlib.sha256(page["content"].encode()).hexdigest()
            changed = new_hash != config["hash"]
            keyword_found = (
                config.get("keyword") and
                config["keyword"].lower() in page["content"].lower()
            )
            
            if changed:
                store[key]["hash"] = new_hash
                store[key]["change_count"] = config.get("change_count", 0) + 1
                store[key]["last_checked"] = time.time()
            
            results.append({
                "label": key,
                "url": config["url"],
                "changed": changed,
                "keyword_found": keyword_found,
                "change_count": store[key]["change_count"]
            })
        
        _MONITOR_STORE.write_text(json.dumps(store, indent=2))
        return {
            "ok": True,
            "results": results,
            "monitored": len(results),
            "summary": f"Checked {len(results)} monitored pages"
        }
    
    elif action == "list":
        return {
            "ok": True,
            "monitors": list(store.keys()),
            "count": len(store),
            "summary": f"Monitoring {len(store)} pages"
        }
    
    elif action == "remove":
        removed = store.pop(label or url or "", None)
        _MONITOR_STORE.write_text(json.dumps(store, indent=2))
        return {
            "ok": True,
            "removed": bool(removed),
            "summary": f"Removed monitor: {label or url}" if removed else "Monitor not found"
        }
    
    return {"ok": False, "error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# 10. Multi Search — Parallel multi-query research
# ---------------------------------------------------------------------------

def multi_search(queries: List[str], fetch_top: int = 2) -> Dict[str, Any]:
    """
    Run multiple independent search queries in parallel.
    Perfect for: list comparisons, batch lookups, research on N topics at once.
    
    Args:
        queries: List of search queries to run in parallel
        fetch_top: Number of pages to fetch per query
    
    Returns:
        Dict with results bundles for each query
    """
    import concurrent.futures
    
    def _one(q: str) -> Dict:
        res = search_and_fetch(query=q, fetch_top=fetch_top, max_chars_per_page=6000)
        return {"query": q, "results": res.get("results", [])}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(queries), 6)) as ex:
        futures = {ex.submit(_one, q): q for q in queries[:6]}  # cap at 6 parallel
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    return {
        "ok": True,
        "kind": "multi_search",
        "count": len(results),
        "bundles": results,
        "summary": f"Completed {len(results)} parallel searches"
    }


# ---------------------------------------------------------------------------
# 11. Fact Check — Cross-source verification
# ---------------------------------------------------------------------------

def fact_check(claim: str, sources: int = 4) -> Dict[str, Any]:
    """
    Verify a claim by fetching N independent sources and detecting conflicts.
    
    Args:
        claim: The claim to verify
        sources: Number of sources to check (default 4)
    
    Returns:
        Dict with verdict, confidence, and source breakdown
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
        
        # Rudimentary signal detection
        supports = any(w in content for w in [
            "confirmed", "true", "verified", "correct", "accurate"
        ])
        contradicts = any(w in content for w in [
            "false", "debunked", "incorrect", "misleading", "wrong", "myth"
        ])
        
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
    
    verdict = ("LIKELY TRUE" if supports_count > contradicts_count
               else "DISPUTED" if contradicts_count > 0
               else "UNVERIFIED")
    
    return {
        "ok": True,
        "claim": claim,
        "verdict": verdict,
        "confidence_pct": confidence,
        "sources_checked": len(source_verdicts),
        "source_breakdown": source_verdicts,
        "summary": f"Fact check: {verdict} ({confidence}% confidence from {len(source_verdicts)} sources)"
    }


# ---------------------------------------------------------------------------
# 12. Reddit & Stack Overflow Search
# ---------------------------------------------------------------------------

def search_reddit(
    query: str,
    subreddit: str = None,
    max_posts: int = 5
) -> Dict[str, Any]:
    """
    Search Reddit via old.reddit.com JSON API (no auth required).
    
    Args:
        query: Search query
        subreddit: Optional subreddit name (e.g., "python", "programming")
        max_posts: Maximum number of posts to return
    
    Returns:
        Dict with posts list
    """
    base = (f"https://www.reddit.com/r/{subreddit}/search.json" if subreddit
            else "https://www.reddit.com/search.json")
    params = {"q": query, "sort": "relevance", "limit": max_posts, "t": "year"}
    
    try:
        resp = requests.get(
            base,
            params=params,
            headers={"User-Agent": "ANKITA-WebAgent/1.0"},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        
        posts = []
        for child in data.get("data", {}).get("children", [])[:max_posts]:
            p = child.get("data", {})
            posts.append({
                "title": p.get("title", ""),
                "subreddit": p.get("subreddit", ""),
                "score": p.get("score", 0),
                "url": "https://reddit.com" + p.get("permalink", ""),
                "body": p.get("selftext", "")[:500],
                "comments": p.get("num_comments", 0),
            })
        
        return {
            "ok": True,
            "query": query,
            "subreddit": subreddit,
            "posts": posts,
            "count": len(posts),
            "summary": f"Found {len(posts)} Reddit posts for '{query}'"
        }
    
    except Exception as e:
        # Fallback: search DuckDuckGo with site:reddit.com
        log.warning("[Reddit] API failed, falling back to web search: %s", e)
        return search_and_fetch(f"{query} site:reddit.com", fetch_top=3)


def search_stackoverflow(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Search Stack Overflow via their public API (no key needed for basic use).
    
    Args:
        query: Search query
        max_results: Maximum number of results
    
    Returns:
        Dict with Stack Overflow results
    """
    try:
        resp = requests.get(
            "https://api.stackexchange.com/2.3/search/advanced",
            params={
                "q": query,
                "site": "stackoverflow",
                "pagesize": max_results,
                "order": "desc",
                "sort": "votes",
                "filter": "withbody"
            },
            timeout=10
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        
        results = []
        for i in items:
            results.append({
                "title": i["title"],
                "score": i["score"],
                "url": i["link"],
                "answered": i["is_answered"],
                "body": re.sub(r'<[^>]+>', '', i.get("body", ""))[:400]
            })
        
        return {
            "ok": True,
            "query": query,
            "results": results,
            "count": len(results),
            "summary": f"Found {len(results)} Stack Overflow answers for '{query}'"
        }
    
    except Exception as err:
        return {"ok": False, "query": query, "error": str(err)}


# ---------------------------------------------------------------------------
# 13. Image Search — Web image search + download
# ---------------------------------------------------------------------------

def image_search(
    query: str,
    max_results: int = 5,
    download: bool = False
) -> Dict[str, Any]:
    """
    Search for images on the web via DuckDuckGo Images API.
    
    Args:
        query: Image search query
        max_results: Maximum number of images to return
        download: If True, downloads the top result to Desktop
    
    Returns:
        Dict with image results
    """
    results = []
    
    # Try ddgs first (new package), then old duckduckgo_search
    for _pkg, _cls in [("ddgs", "DDGS"), ("duckduckgo_search", "DDGS")]:
        try:
            import importlib
            mod = importlib.import_module(_pkg)
            DDGSCls = getattr(mod, _cls)
            with DDGSCls() as ddgs:
                results = list(ddgs.images(query, max_results=max_results))
            if results:
                break
        except Exception:
            continue
    
    images = []
    for r in results[:max_results]:
        images.append({
            "title": r.get("title", ""),
            "url": r.get("image", ""),
            "thumbnail": r.get("thumbnail", ""),
            "source": r.get("url", "")
        })
    
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
    
    return {
        "ok": True,
        "query": query,
        "images": images,
        "count": len(images),
        "summary": f"Found {len(images)} images for '{query}'"
    }


# ---------------------------------------------------------------------------
# 14. Summarise URL — TL;DR any link
# ---------------------------------------------------------------------------

def summarise_url(
    url: str,
    style: str = "bullets",
    max_bullets: int = 7
) -> Dict[str, Any]:
    """
    Fetch a URL and produce a targeted summary.
    
    Args:
        url: URL to summarise
        style: Summary style - "bullets" | "tldr" | "eli5" | "key_stats" | "pros_cons"
        max_bullets: Number of bullet points (for bullets style)
    
    Returns:
        Dict with content and instruction for LLM to synthesize
    """
    page = fetch_page_content(url, max_chars=20000)
    if not page.get("ok"):
        return {"ok": False, "url": url, "error": page.get("error", "Fetch failed")}
    
    content = page["content"][:15000]
    
    style_prompts = {
        "bullets": f"Summarise the following article in exactly {max_bullets} bullet points. Be specific and include key facts, numbers, and names.",
        "tldr": "Write a 2-3 sentence TL;DR of this article. Be direct, no fluff.",
        "eli5": "Explain this article like I'm 5 years old, in simple plain English.",
        "key_stats": "Extract ONLY the key numbers, statistics, and data points from this article. Format as a bulleted list.",
        "pros_cons": "Extract the pros and cons mentioned in this content. Two lists: Pros ✅ and Cons ❌."
    }
    
    title = page.get("content", "")[:100].split('\n')[0]
    
    return {
        "ok": True,
        "url": url,
        "style": style,
        "content_for_llm": content,
        "instruction": style_prompts.get(style, style_prompts["bullets"]),
        "title": title,
        "summary": f"Fetched {url} for {style} summary"
    }


# ---------------------------------------------------------------------------
# 15. Trending Topics — What's hot right now
# ---------------------------------------------------------------------------

def trending_topics(category: str = "general", region: str = "US") -> Dict[str, Any]:
    """
    Fetch what's trending right now across multiple sources.
    
    Args:
        category: "general" | "tech" | "finance" | "sports" | "entertainment" | "science"
        region: Region code (default "US")
    
    Returns:
        Dict with trending topics from multiple sources
    """
    results = {"category": category, "region": region, "sources": {}}
    
    # Hacker News Top Stories (no auth)
    try:
        hn_resp = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=8
        )
        hn_resp.raise_for_status()
        top_ids = hn_resp.json()[:10]
        hn_stories = []
        
        for story_id in top_ids[:5]:
            item = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                timeout=5
            ).json()
            hn_stories.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "score": item.get("score", 0),
                "comments": item.get("descendants", 0)
            })
        
        results["sources"]["hacker_news"] = hn_stories
    except Exception:
        pass
    
    # Reddit r/popular (no auth)
    try:
        reddit_resp = requests.get(
            "https://www.reddit.com/r/popular.json?limit=10",
            headers={"User-Agent": "ANKITA/1.0"},
            timeout=10
        )
        reddit_resp.raise_for_status()
        reddit_data = reddit_resp.json()
        
        posts = []
        for c in reddit_data["data"]["children"][:5]:
            posts.append({
                "title": c["data"]["title"],
                "subreddit": c["data"]["subreddit"],
                "score": c["data"]["score"],
                "url": "https://reddit.com" + c["data"]["permalink"]
            })
        
        results["sources"]["reddit_popular"] = posts
    except Exception:
        pass
    
    # Fallback: search news for trending
    if not results["sources"]:
        news = search_news(f"trending {category} today", max_results=8, include_urls=True)
        results["sources"]["news_search"] = news.get("results", [])
    
    return {
        "ok": True,
        **results,
        "summary": f"Trending topics in {category}"
    }


# ---------------------------------------------------------------------------
# 16. Web to Dataset — Research → Structured CSV/JSON
# ---------------------------------------------------------------------------

def web_to_dataset(
    query: str,
    columns: List[str] = None,
    max_rows: int = 20,
    output_format: str = "json"
) -> Dict[str, Any]:
    """
    Research a topic and extract structured data rows from web results.
    
    Args:
        query: Research query
        columns: List of column names for the dataset
        max_rows: Maximum number of rows to extract
        output_format: "json" or "csv"
    
    Returns:
        Dict with content and extraction instruction for LLM
    """
    columns = columns or ["Name", "Description", "Key Fact", "Source"]
    
    # Fetch 5 pages of content
    result = search_and_fetch(query=query, fetch_top=5, max_chars_per_page=8000)
    all_content = "\n\n".join(
        f"[SOURCE: {r.get('title', '')}]\n{r.get('content', '')[:3000]}"
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
        "summary": f"Researched '{query}' for dataset extraction"
    }


# ---------------------------------------------------------------------------
# Helper classes for HTML parsing
# ---------------------------------------------------------------------------

from html.parser import HTMLParser

class _DuckResultParser(HTMLParser):
    """Minimal HTML parser for DuckDuckGo search results."""
    def __init__(self):
        super().__init__()
        self.results = []
        self._in_result = False
        self._current_title = ""
        self._current_url = ""
    
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "a" and attrs_dict.get("class") == "result__a":
            self._in_result = True
            self._current_url = attrs_dict.get("href", "")
    
    def handle_data(self, data):
        if self._in_result:
            self._current_title += data.strip() + " "
    
    def handle_endtag(self, tag):
        if tag == "a" and self._in_result:
            self._in_result = False
            if self._current_title and self._current_url:
                self.results.append({
                    "title": self._current_title.strip(),
                    "url": self._current_url
                })
            self._current_title = ""
            self._current_url = ""


def _base_result(title: str, url: str, snippet: str) -> Dict[str, Any]:
    """Create a base search result dict."""
    return {
        "title": title,
        "url": url,
        "snippet": snippet,
        "domain": _extract_domain(url)
    }
