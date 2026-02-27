import os
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse
import xml.etree.ElementTree as ET

import requests

# ---------------------------------------------------------------------------
# Full modern browser headers — bypasses bot detection on DDG, school sites,
# and most news/local websites that reject bare User-Agent strings.
# ---------------------------------------------------------------------------
_REAL_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


class _DuckResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._current_href = ""
        self._current_text_parts: List[str] = []
        self.results: List[Dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {k: (v or "") for k, v in attrs}
        cls = attr_map.get("class", "")
        href = attr_map.get("href", "")
        # Match DuckDuckGo's HTML formats (tightest matching — no noisy nav links):
        # 1. Old stable format: class contains "result__a"
        # 2. New HTML5 format: href contains "/l/?uddg=" (genuine DDG redirect)
        # DO NOT use "any external http link" fallback — that grabs nav/footer garbage
        is_ddg_result = (
            "result__a" in cls
            or ("uddg=" in href and "/l/?" in href)
        )
        if is_ddg_result and href:
            self._capture = True
            self._current_href = href
            self._current_text_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._current_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._capture:
            return
        title = " ".join("".join(self._current_text_parts).split()).strip()
        link = _normalize_duck_link(self._current_href)
        if title and link:
            self.results.append({"title": title, "url": link})
        self._capture = False
        self._current_href = ""
        self._current_text_parts = []


def _normalize_duck_link(url: str) -> str:
    parsed = urlparse(url)
    if parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        unwrapped = qs.get("uddg", [])
        if unwrapped and unwrapped[0]:
            return unwrapped[0]
    if parsed.scheme and parsed.netloc:
        return url
    return ""


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def _base_result(title: str, url: str, snippet: str = "") -> Dict[str, str]:
    row: Dict[str, str] = {"title": title, "domain": _domain(url), "snippet": snippet}
    return row


def search_web(query: str, max_results: int = 8, include_urls: bool = False) -> Dict[str, Any]:
    q = str(query or "").strip()
    if not q:
        raise ValueError("query is required")
    limit = max(1, min(int(max_results), 20))

    google_key = os.getenv("GOOGLE_SEARCH_API_KEY", "").strip()
    google_cx = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip()
    if google_key and google_cx:
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "q": q,
                    "key": google_key,
                    "cx": google_cx,
                    "num": min(limit, 10),
                    "safe": "off",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", []) if isinstance(data, dict) else []
            out: List[Dict[str, str]] = []
            for item in items[:limit]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip()
                url = str(item.get("link", "")).strip()
                desc = str(item.get("snippet", "")).strip()
                if not title or not url:
                    continue
                row = _base_result(title=title, url=url, snippet=desc)
                if include_urls:
                    row["url"] = url
                out.append(row)
            if out:
                return {
                    "kind": "web_search",
                    "engine": "google-custom-search",
                    "query": q,
                    "include_urls": bool(include_urls),
                    "results": out,
                }
        except Exception:
            # Fallback below
            pass

    # Fallback 1: DuckDuckGo HTML results (no key)
    # Use html.duckduckgo.com (more stable endpoint) + kl=us-en for region
    ddg_url = f"https://html.duckduckgo.com/html/?{urlencode({'q': q, 'kl': 'us-en'})}"
    try:
        resp = requests.get(ddg_url, timeout=30, headers=_REAL_BROWSER_HEADERS)
        resp.raise_for_status()
        parser = _DuckResultParser()
        parser.feed(resp.text)
        out = []
        for row in parser.results[:limit]:
            item = _base_result(title=row["title"], url=row["url"], snippet="")
            if include_urls:
                item["url"] = row["url"]
            out.append(item)
        if out:
            return {
                "kind": "web_search",
                "engine": "duckduckgo-html",
                "query": q,
                "include_urls": bool(include_urls),
                "results": out,
            }
    except Exception:
        pass

    # Fallback 2: Google with udm=14 (Web-only tab, bypasses AI overviews)
    # Free — no API key needed. Scrapes the Google search results page.
    try:
        google_url = f"https://www.google.com/search?{urlencode({'q': q, 'udm': '14', 'num': limit})}"
        resp = requests.get(google_url, timeout=30, headers=_REAL_BROWSER_HEADERS)
        if resp.status_code == 200:
            # Extract links from Google results — look for <a href="/url?q=...">
            google_links = re.findall(r'<a href="/url\?q=([^&"]+)[^"]*"[^>]*>([^<]+)', resp.text)
            out = []
            for raw_url, raw_title in google_links[:limit]:
                from urllib.parse import unquote
                clean_url = unquote(raw_url)
                clean_title = re.sub(r'<[^>]+>', '', raw_title).strip()
                if clean_url.startswith("http") and "google.com" not in clean_url and clean_title:
                    item = _base_result(title=clean_title, url=clean_url, snippet="")
                    if include_urls:
                        item["url"] = clean_url
                    out.append(item)
            if out:
                return {
                    "kind": "web_search",
                    "engine": "google-udm14-scrape",
                    "query": q,
                    "include_urls": bool(include_urls),
                    "results": out,
                }
    except Exception:
        pass

    # Last resort: return empty
    return {
        "kind": "web_search",
        "engine": "none",
        "query": q,
        "include_urls": bool(include_urls),
        "results": [],
    }


class _TextExtractor(HTMLParser):
    """Strips HTML tags and extracts visible text."""

    SKIP_TAGS = {"script", "style", "noscript", "head", "meta", "link", "iframe", "nav", "footer", "header"}

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        if tag.lower() in self.SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.SKIP_TAGS and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self) -> str:
        raw = " ".join(self._parts)
        # Collapse multiple whitespace/newlines
        raw = re.sub(r"\s{2,}", " ", raw)
        return raw.strip()


def fetch_page_content(url: str, max_chars: int = 4000, timeout: int = 15) -> Dict[str, Any]:
    """Fetch a URL and return extracted readable text content from the page."""
    url = str(url or "").strip()
    if not url:
        raise ValueError("url is required")

    _BLOCKED_DOMAINS = {
        "twitter.com", "x.com", "facebook.com", "instagram.com",
        "linkedin.com", "reddit.com",  # often block scrapers
    }
    domain = _domain(url)
    if any(domain == bd or domain.endswith("." + bd) for bd in _BLOCKED_DOMAINS):
        return {
            "kind": "page_content",
            "url": url,
            "domain": domain,
            "ok": False,
            "reason": "domain_blocked_for_scraping",
            "content": "",
        }

    headers = _REAL_BROWSER_HEADERS

    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return {"kind": "page_content", "url": url, "domain": domain, "ok": False, "reason": "timeout", "content": ""}
    except requests.exceptions.HTTPError as e:
        return {"kind": "page_content", "url": url, "domain": domain, "ok": False, "reason": f"http_error_{e.response.status_code}", "content": ""}
    except Exception as e:
        return {"kind": "page_content", "url": url, "domain": domain, "ok": False, "reason": str(e), "content": ""}

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type and "text/plain" not in content_type:
        return {
            "kind": "page_content",
            "url": url,
            "domain": domain,
            "ok": False,
            "reason": f"unsupported_content_type:{content_type}",
            "content": "",
        }

    extractor = _TextExtractor()
    try:
        extractor.feed(resp.text)
    except Exception:
        pass

    text = extractor.get_text()
    truncated = len(text) > max_chars
    return {
        "kind": "page_content",
        "url": url,
        "domain": domain,
        "ok": True,
        "char_count": len(text),
        "truncated": truncated,
        "content": text[:max_chars],
    }


def search_and_fetch(query: str, max_results: int = 5, fetch_top: int = 3, max_chars_per_page: int = 5000) -> Dict[str, Any]:
    """Search the web AND fetch actual content from the top results.
    
    Perfect for factual queries like 'price of bitcoin', 'weather today', 
    'latest iPhone specs', etc. Returns real scraped data, not just URLs.
    """
    q = str(query or "").strip()
    if not q:
        raise ValueError("query is required")

    # First get search results with URLs
    search_result = search_web(q, max_results=max(max_results, fetch_top + 2), include_urls=True)
    results = search_result.get("results", [])

    fetched_pages: List[Dict[str, Any]] = []
    attempted = 0
    for row in results:
        if attempted >= fetch_top or len(fetched_pages) >= fetch_top:
            break
        url = str(row.get("url", "")).strip()
        if not url:
            continue
        attempted += 1
        page = fetch_page_content(url, max_chars=max_chars_per_page)
        if page.get("ok") and page.get("content", "").strip():
            fetched_pages.append({
                "title": str(row.get("title", "")),
                "url": url,
                "domain": str(row.get("domain", "")),
                "content": page["content"],
                "truncated": bool(page.get("truncated")),
            })

    return {
        "kind": "search_and_fetch",
        "query": q,
        "engine": search_result.get("engine", ""),
        "search_results": results[:max_results],
        "fetched_pages": fetched_pages,
        "pages_fetched": len(fetched_pages),
    }


def search_price(query: str) -> Dict[str, Any]:
    """
    Fast, reliable price fetcher for crypto and stocks.

    Tries 3 sources in priority order:
    1. CoinGecko REST API (crypto — no API key needed)
    2. Yahoo Finance page scrape (stocks)
    3. search_and_fetch fallback (general price queries)

    Args:
        query: What to look up — e.g. "bitcoin", "ethereum", "AAPL", "gold price"

    Returns:
        Dict with ok, price, currency, source, and a human-readable summary.
    """
    q = str(query or "").strip().lower()
    if not q:
        raise ValueError("query is required")

    # ------------------------------------------------------------------
    # 1. CoinGecko — best for crypto (bitcoin, ethereum, solana, etc.)
    # ------------------------------------------------------------------
    _COINGECKO_IDS = {
        "bitcoin": "bitcoin", "btc": "bitcoin",
        "ethereum": "ethereum", "eth": "ethereum",
        "solana": "solana", "sol": "solana",
        "dogecoin": "dogecoin", "doge": "dogecoin",
        "cardano": "cardano", "ada": "cardano",
        "ripple": "ripple", "xrp": "ripple",
        "litecoin": "litecoin", "ltc": "litecoin",
        "polkadot": "polkadot", "dot": "polkadot",
        "chainlink": "chainlink", "link": "chainlink",
        "avalanche": "avalanche-2", "avax": "avalanche-2",
        "polygon": "matic-network", "matic": "matic-network",
        "shiba": "shiba-inu", "shib": "shiba-inu",
        "binancecoin": "binancecoin", "bnb": "binancecoin",
        "tron": "tron", "trx": "tron",
        "toncoin": "the-open-network", "ton": "the-open-network",
    }

    # Match query against coin names/symbols
    coin_id = None
    for key, cg_id in _COINGECKO_IDS.items():
        if key in q:
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
            data = resp.json()
            coin_data = data.get(coin_id, {})
            price = coin_data.get("usd")
            change = coin_data.get("usd_24h_change")
            if price is not None:
                change_str = f" ({change:+.2f}% 24h)" if change is not None else ""
                summary = f"{coin_id.replace('-', ' ').title()} is currently ${price:,.2f} USD{change_str}. (Source: CoinGecko)"
                return {
                    "ok": True,
                    "query": q,
                    "coin_id": coin_id,
                    "price": price,
                    "currency": "USD",
                    "change_24h": change,
                    "source": "coingecko",
                    "summary": summary,
                }
        except Exception:
            pass  # Fall through to next source

    # ------------------------------------------------------------------
    # 2. Yahoo Finance scrape — for stocks (AAPL, TSLA, GOOGL, etc.)
    # ------------------------------------------------------------------
    # Extract potential ticker from query (uppercased 1-5 char word)
    ticker_match = re.search(r'\b([A-Z]{1,5})\b', query.upper())
    ticker = ticker_match.group(1) if ticker_match else None

    if ticker:
        try:
            yf_url = f"https://finance.yahoo.com/quote/{ticker}"
            resp = requests.get(
                yf_url,
                timeout=10,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html",
                },
            )
            if resp.status_code == 200:
                # Extract price from HTML — Yahoo puts it in fin-streamer[data-field="regularMarketPrice"]
                price_match = re.search(
                    r'data-field="regularMarketPrice"[^>]*data-value="([0-9.,]+)"',
                    resp.text,
                )
                if price_match:
                    price_str = price_match.group(1).replace(",", "")
                    price_val = float(price_str)
                    summary = f"{ticker} is currently trading at ${price_val:,.2f} USD. (Source: Yahoo Finance)"
                    return {
                        "ok": True,
                        "query": q,
                        "ticker": ticker,
                        "price": price_val,
                        "currency": "USD",
                        "source": "yahoo_finance",
                        "summary": summary,
                    }
        except Exception:
            pass  # Fall through to web scrape

    # ------------------------------------------------------------------
    # 3. Fallback — search_and_fetch with bigger limits
    # ------------------------------------------------------------------
    try:
        result = search_and_fetch(
            query=f"{query} price today USD",
            max_results=5,
            fetch_top=3,
            max_chars_per_page=4000,
        )
        # Extract price-like patterns from fetched content
        all_content = " ".join(
            p.get("content", "") for p in result.get("fetched_pages", [])
        )
        # Look for $XX,XXX.XX or $XX.XX patterns
        price_patterns = re.findall(r'\$[\d,]+(?:\.\d{1,2})?', all_content)
        if price_patterns:
            return {
                "ok": True,
                "query": q,
                "source": "web_scrape",
                "price_mentions": price_patterns[:5],
                "summary": f"Found price mentions for '{query}': {', '.join(price_patterns[:5])}. Raw content available in fetched_pages.",
                "fetched_pages": result.get("fetched_pages", []),
            }
        return {
            "ok": False,
            "query": q,
            "source": "web_scrape",
            "summary": f"Could not find a clear price for '{query}'. Try a more specific query.",
            "fetched_pages": result.get("fetched_pages", []),
        }
    except Exception as err:
        return {
            "ok": False,
            "query": q,
            "source": "none",
            "summary": f"All price sources failed: {err}",
        }


def search_news(query: str, max_results: int = 8, include_urls: bool = False) -> Dict[str, Any]:
    q = str(query or "").strip()
    if not q:
        raise ValueError("query is required")
    limit = max(1, min(int(max_results), 20))

    params = {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    url = f"https://news.google.com/rss/search?{urlencode(params)}"
    resp = requests.get(url, timeout=30, headers=_REAL_BROWSER_HEADERS)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []
    out: List[Dict[str, str]] = []
    for item in items[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        source = ""
        src_node = item.find("source")
        if src_node is not None and src_node.text:
            source = src_node.text.strip()
        if title and link:
            row: Dict[str, str] = {
                "title": title,
                "domain": _domain(link),
                "published": pub_date,
                "source": source,
            }
            if include_urls:
                row["url"] = link
            out.append(row)
    return {
        "kind": "news_search",
        "engine": "google-news-rss",
        "query": q,
        "include_urls": bool(include_urls),
        "results": out,
    }
