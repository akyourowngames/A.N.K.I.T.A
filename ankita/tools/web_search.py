import requests
import os
import urllib.parse
import xml.etree.ElementTree as ET


def _coingecko_price(coin_id: str) -> dict:
    r = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": coin_id, "vs_currencies": "usd"},
        timeout=8,
    )
    data = r.json() if r.ok else {}
    price = None
    try:
        price = data.get(coin_id, {}).get("usd")
    except Exception:
        price = None
    if price is None:
        return {"status": "fail", "reason": "no_price"}
    return {
        "status": "success",
        "results": [
            {
                "title": f"{coin_id} price (USD)",
                "snippet": f"{coin_id} price is ${price} USD.",
                "url": "https://www.coingecko.com/",
                "source": "CoinGecko",
            }
        ],
    }


def _wttr_weather(location: str) -> dict:
    loc = (location or "").strip()
    if not loc:
        return {"status": "fail", "reason": "missing_location"}
    r = requests.get(f"https://wttr.in/{urllib.parse.quote(loc)}", params={"format": "j1"}, timeout=8)
    data = r.json() if r.ok else {}

    try:
        current = (data.get("current_condition") or [{}])[0]
        temp_c = current.get("temp_C")
        feels_c = current.get("FeelsLikeC")
        desc = ((current.get("weatherDesc") or [{}])[0].get("value") or "").strip()
        if temp_c is None:
            return {"status": "fail", "reason": "no_weather"}
        snippet = f"Current weather in {loc}: {temp_c}°C"
        if feels_c is not None:
            snippet += f" (feels like {feels_c}°C)"
        if desc:
            snippet += f", {desc}."
        else:
            snippet += "."
        return {
            "status": "success",
            "results": [
                {
                    "title": f"Weather in {loc}",
                    "snippet": snippet,
                    "url": f"https://wttr.in/{urllib.parse.quote(loc)}",
                    "source": "wttr.in",
                }
            ],
        }
    except Exception:
        return {"status": "fail", "reason": "parse_error"}


def _google_news_rss(query: str, max_results: int) -> dict:
    q = (query or "").strip()
    if not q:
        return {"status": "fail", "reason": "missing_query"}
    url = "https://news.google.com/rss/search"
    params = {"q": q, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    r = requests.get(url, params=params, timeout=8)
    if not r.ok:
        return {"status": "fail", "reason": "http_error"}

    try:
        root = ET.fromstring(r.text)
    except Exception:
        return {"status": "fail", "reason": "parse_error"}

    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if not title:
            continue
        snippet = title
        if pub:
            snippet = f"{title} ({pub})"
        items.append({"title": title, "snippet": snippet, "url": link, "source": "Google News"})
        if len(items) >= int(max_results):
            break

    return {"status": "success", "results": items}


def _tavily_search(query: str, max_results: int) -> dict:
    key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if not key:
        return {"status": "fail", "reason": "missing_api_key"}

    r = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": key,
            "query": query,
            "max_results": int(max_results),
            "include_answer": False,
            "include_raw_content": False,
        },
        timeout=10,
    )
    if not r.ok:
        return {"status": "fail", "reason": f"http_{r.status_code}"}

    data = r.json() if r.content else {}
    raw = data.get("results") or []
    if not isinstance(raw, list):
        raw = []

    out = []
    for it in raw[: int(max_results)]:
        if not isinstance(it, dict):
            continue
        out.append(
            {
                "title": (it.get("title") or "").strip() or "Result",
                "snippet": (it.get("content") or "").strip(),
                "url": (it.get("url") or "").strip(),
                "source": "Tavily",
            }
        )

    return {"status": "success", "results": out}


def _serpapi_search(query: str, max_results: int) -> dict:
    key = (os.getenv("SERPAPI_API_KEY") or "").strip()
    if not key:
        return {"status": "fail", "reason": "missing_api_key"}

    r = requests.get(
        "https://serpapi.com/search.json",
        params={
            "engine": "google",
            "q": query,
            "api_key": key,
            "num": int(max_results),
        },
        timeout=12,
    )
    if not r.ok:
        return {"status": "fail", "reason": f"http_{r.status_code}"}

    data = r.json() if r.content else {}
    raw = data.get("organic_results") or []
    if not isinstance(raw, list):
        raw = []

    out = []
    for it in raw[: int(max_results)]:
        if not isinstance(it, dict):
            continue
        out.append(
            {
                "title": (it.get("title") or "").strip() or "Result",
                "snippet": (it.get("snippet") or "").strip(),
                "url": (it.get("link") or "").strip(),
                "source": "SerpAPI",
            }
        )

    return {"status": "success", "results": out}


def run(query: str = "", max_results: int = 5, **kwargs):
    q = (query or "").strip()
    if not q:
        return {"status": "fail", "reason": "missing_query"}

    # --- OpenClaw Priority Search ---
    # Try to use OpenClaw's Brave search first if it's available
    try:
        # Check if bridge is online
        bridge_resp = requests.get("http://127.0.0.1:5050/health", timeout=1)
        if bridge_resp.ok:
            print(f"[WebSearch] OpenClaw detected. Routing query: {q}")
            # The bridge currently handles web_search async or returns a placeholder.
            # Let's try to call the proxy endpoint we created.
            proxy_resp = requests.post(
                "http://127.0.0.1:5050/openclaw/web_search",
                json={"query": q, "count": max_results},
                timeout=5
            )
            if proxy_resp.ok:
                proxy_data = proxy_resp.json()
                # If the bridge returned actual results, return them
                if proxy_data.get("results"):
                    return {"status": "success", "query": q, "results": proxy_data["results"]}
                # Otherwise, if it just acknowledged, we might want to continue to local fallbacks
                # but for now let's trust the bridge if it's there.
    except Exception:
        pass

    # Handle empty string max_results from semantic control
    if max_results == '' or max_results is None:
        max_results = 5
    try:
        max_results = int(max_results)
    except (ValueError, TypeError):
        max_results = 5

    # Add location to "near me" queries for better results
    user_location = (os.getenv("USER_CITY") or os.getenv("USER_LOCATION") or "").strip()
    if user_location and ("near me" in q.lower() or "nearby" in q.lower()):
        # Replace "near me" with actual location
        q_original = q
        q = q.lower().replace("near me", f"in {user_location}")
        q = q.replace("nearby", f"in {user_location}")
        print(f"[WebSearch] Location-aware: '{q_original}' -> '{q}'")

    tl = q.lower()

    provider = (os.getenv("WEB_SEARCH_PROVIDER") or "").strip().lower()
    
    # Try Tavily first (if available)
    tavily_key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if tavily_key and provider in ("tavily", ""):
        print(f"[WebSearch] Trying Tavily for: {q}")
        try:
            out = _tavily_search(q, max_results=max_results)
            print(f"[WebSearch] Tavily result status: {out.get('status')}, results: {len(out.get('results', []))}")
            if out.get("status") == "success" and out.get("results"):
                return {"status": "success", "query": q, "results": out.get("results", [])}
            else:
                print(f"[WebSearch] Tavily failed: {out.get('reason', 'no results')}")
        except Exception as e:
            print(f"[WebSearch] Tavily exception: {e}")

    # Try SerpAPI next
    if provider == "serpapi" and (os.getenv("SERPAPI_API_KEY") or "").strip():
        print(f"[WebSearch] Trying SerpAPI for: {q}")
        try:
            out = _serpapi_search(q, max_results=max_results)
            if out.get("status") == "success" and out.get("results"):
                return {"status": "success", "query": q, "results": out.get("results", [])}
        except Exception as e:
            print(f"[WebSearch] SerpAPI exception: {e}")

    try:
        if any(k in tl for k in ("bitcoin", "btc")) and any(k in tl for k in ("price", "rate", "value", "cost")):
            out = _coingecko_price("bitcoin")
            if out.get("status") == "success":
                return {"status": "success", "query": q, "results": out.get("results", [])}
        if "weather" in tl:
            loc = tl
            for k in ("weather in", "current weather in", "weather at"):
                if k in loc:
                    loc = loc.split(k, 1)[1].strip(" ?")
                    break
            loc = (loc or "").strip(" ?")
            out = _wttr_weather(loc)
            if out.get("status") == "success":
                return {"status": "success", "query": q, "results": out.get("results", [])}
        if "news" in tl or "headline" in tl or "headlines" in tl:
            out = _google_news_rss(q, max_results=max_results)
            if out.get("status") == "success":
                return {"status": "success", "query": q, "results": out.get("results", [])}
    except Exception:
        pass

    try:
        # Better fallback: DuckDuckGo 'HTML' search (naive but effective)
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(
            f"https://duckduckgo.com/html/?q={urllib.parse.quote(q)}",
            headers=headers,
            timeout=8
        )
        if r.ok:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.find_all("div", class_="result")[:int(max_results)]:
                title_tag = item.find("a", class_="result__a")
                snippet_tag = item.find("a", class_="result__snippet")
                if title_tag:
                    results.append({
                        "title": title_tag.get_text().strip(),
                        "snippet": snippet_tag.get_text().strip() if snippet_tag else "",
                        "url": title_tag.get("href", ""),
                        "source": "DuckDuckGo"
                    })
            if results:
                return {"status": "success", "query": q, "results": results}
    except Exception as e:
        print(f"[WebSearch] Scraper fallback failed: {e}")

    # Fallback to the original API method if scraper fails
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={
                "q": q,
                "format": "json",
                "no_redirect": 1,
                "no_html": 1,
            },
            timeout=8,
        )
        data = r.json() if r.ok else {}

        results = []

        abstract = (data.get("AbstractText") or "").strip()
        if abstract:
            results.append(
                {
                    "title": (data.get("Heading") or "").strip() or q,
                    "snippet": abstract,
                    "url": (data.get("AbstractURL") or "").strip(),
                    "source": "DuckDuckGo",
                }
            )

        related = data.get("RelatedTopics") or []
        if isinstance(related, list):
            for item in related:
                if len(results) >= int(max_results):
                    break

                if isinstance(item, dict) and "Text" in item:
                    results.append(
                        {
                            "title": (item.get("Text") or "").strip(),
                            "snippet": (item.get("Text") or "").strip(),
                            "url": (item.get("FirstURL") or "").strip(),
                            "source": "DuckDuckGo",
                        }
                    )
                    continue

                if isinstance(item, dict) and "Topics" in item and isinstance(item.get("Topics"), list):
                    for sub in item.get("Topics"):
                        if len(results) >= int(max_results):
                            break
                        if isinstance(sub, dict) and "Text" in sub:
                            results.append(
                                {
                                    "title": (sub.get("Text") or "").strip(),
                                    "snippet": (sub.get("Text") or "").strip(),
                                    "url": (sub.get("FirstURL") or "").strip(),
                                    "source": "DuckDuckGo",
                                }
                            )

        return {"status": "success", "query": q, "results": results[: int(max_results)]}
    except Exception as e:
        return {"status": "error", "error": str(e)}
