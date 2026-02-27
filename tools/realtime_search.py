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

import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests


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
    max_chars_per_page: int = 12000,
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
        print(f"[ANKITA] 🔍 Reading: {title[:60]}...")

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
    # CoinGecko — crypto prices
    # ------------------------------------------------------------------
    _COINGECKO_IDS = {
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
