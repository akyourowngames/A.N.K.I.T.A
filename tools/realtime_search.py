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
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlencode

import requests

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
            return {
                "kind": "page_content",
                "ok": False,
                "url": url,
                "error": f"Jina Reader returned HTTP {resp.status_code}",
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
    coin_id = next((cg_id for key, cg_id in _COINGECKO_IDS.items() if key in q), None)
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
