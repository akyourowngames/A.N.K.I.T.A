"""God-tier realtime web search for Zumba (zero-API-key).

Backends: DuckDuckGo HTML (web), Google News RSS (realtime news),
Wikipedia (grounding), Hacker News Algolia (tech), Reddit JSON
(best-effort chatter), plus a readable page fetcher with optional
r.jina.ai fallback. No LLM in the loop — deterministic layer, the model
synthesizes (same philosophy as memory recall).

Conventions (match shelltool.py):
- ERROR: text prefix on failures, never raise into chat.
- ZUMBA_NO_WEB=1 kill-switch.
- Head+tail truncation like shell output caps.
"""

from __future__ import annotations

import hashlib
import html as _html
import json
import os
import re
import time
import urllib.parse as _url
from html.parser import HTMLParser

try:
    import requests as _requests
except Exception:  # pragma: no cover
    _requests = None


def enabled() -> bool:
    return os.getenv("ZUMBA_NO_WEB", "") != "1"


def timeout_s() -> float:
    try:
        return max(2.0, float(os.getenv("ZUMBA_WEB_TIMEOUT", "20") or 20))
    except Exception:
        return 20.0


def max_output() -> int:
    try:
        return max(500, int(os.getenv("ZUMBA_WEB_MAX_OUTPUT", "8000") or 8000))
    except Exception:
        return 8000


def cache_ttl() -> float:
    try:
        return max(0.0, float(os.getenv("ZUMBA_WEB_CACHE_TTL", "300") or 300))
    except Exception:
        return 300.0


def retries() -> int:
    try:
        return max(0, min(3, int(os.getenv("ZUMBA_WEB_RETRIES", "1") or 1)))
    except Exception:
        return 1


def region() -> str:
    return (os.getenv("ZUMBA_WEB_REGION", "") or "wt-wt").strip() or "wt-wt"


def jina_fallback() -> bool:
    return (os.getenv("ZUMBA_WEB_JINA_FALLBACK", "1") != "0")


BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HONEST_UA = "zumba/1.0 (+https://kilo.ai)"


# ---- cache (in-process + optional disk mirror) ----

_CACHE: dict[str, tuple[float, str]] = {}


def _cache_dir():
    try:
        from core.store import zumba_home
        d = zumba_home() / "webcache"
    except Exception:
        d = os.path.join(os.path.expanduser("~"), ".zumba", "webcache")
        try:
            import pathlib as _p
            return _p.Path(d)
        except Exception:
            return None
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _cache_key(kind: str, **parts) -> str:
    blob = kind + "|" + "|".join(f"{k}={parts.get(k, '')}" for k in sorted(parts))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def cache_get(key: str):
    entry = _CACHE.get(key)
    if entry and (time.time() - entry[0]) < cache_ttl():
        return entry[1], True
    if cache_ttl() <= 0:
        return None, False
    try:
        d = _cache_dir()
        f = d / f"{key}.json" if d is not None and hasattr(d, "__truediv__") else None
        if f is not None and f.exists():
            payload = json.loads(f.read_text(encoding="utf-8"))
            if (time.time() - float(payload.get("ts", 0))) < cache_ttl():
                _CACHE[key] = (float(payload["ts"]), str(payload["data"]))
                return str(payload["data"]), True
    except Exception:
        pass
    return None, False


def cache_put(key: str, data: str) -> None:
    if cache_ttl() <= 0:
        return
    _CACHE[key] = (time.time(), data)
    try:
        d = _cache_dir()
        if d is not None and hasattr(d, "__truediv__"):
            (d / f"{key}.json").write_text(json.dumps({"ts": time.time(), "data": data})[:200000],
                                           encoding="utf-8")
    except Exception:
        pass


def cache_age(key: str) -> float:
    entry = _CACHE.get(key)
    return (time.time() - entry[0]) if entry else -1.0


# ---- HTTP with retry ----

def _http(method: str, url: str, timeout: float = 0, headers: dict | None = None,
          data: dict | None = None, params: dict | None = None):
    if _requests is None:
        raise RuntimeError("requests is not installed (pip install -r requirements.txt)")
    to = timeout or timeout_s()
    tries = 1 + retries()
    last_exc: Exception | None = None
    for attempt in range(tries):
        try:
            if method == "POST":
                r = _requests.post(url, data=data, params=params, headers=headers or {},
                                   timeout=to, allow_redirects=True)
            else:
                r = _requests.get(url, params=params, headers=headers or {},
                                  timeout=to, allow_redirects=True)
            if r.status_code in (429, 503) and attempt < tries - 1:
                wait = 2.0
                try:
                    ra = r.headers.get("Retry-After", "")
                    if ra and float(ra) <= 20:
                        wait = float(ra)
                except Exception:
                    pass
                time.sleep(wait)
                continue
            return r
        except Exception as exc:
            last_exc = exc
            if attempt < tries - 1:
                time.sleep(1.0)
    raise last_exc or RuntimeError("HTTP request failed")


def _browser_headers() -> dict:
    return {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
            "Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-User": "?1"}


def _honest_headers() -> dict:
    return {"User-Agent": HONEST_UA, "Accept-Language": "en-US,en;q=0.9"}


# ---- URL normalize / truncate ----

def normalize_url(u: str) -> str:
    try:
        p = _url.urlparse((u or "").strip())
        q = [(k, v) for k, v in _url.parse_qsl(p.query)
             if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")]
        path = p.path.rstrip("/") or "/"
        return _url.urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", _url.urlencode(q), ""))
    except Exception:
        return (u or "").strip().rstrip("/")


def truncate_output(text: str, cap: int = 0) -> tuple[str, bool]:
    cap = cap or max_output()
    if len(text) <= cap:
        return text, False
    head = cap * 4 // 5
    tail = cap - head
    note = f"\n[...truncated {len(text) - cap} chars; showing head+tail...]\n"
    return text[:head] + note + text[-tail:], True


# ---- DDG web backend ----

_DDG_CAPTCHA_MARKERS = ("anomaly-modal", "captcha", "challenge-platform", "Please complete the following challenge")

_FRESH_TO_DF = {"1h": "d", "1d": "d", "7d": "w", "30d": "m", "1y": "y"}


def _decode_ddg_href(href: str) -> str:
    try:
        if "uddg=" in href:
            qs = _url.parse_qs(_url.urlparse(href).query)
            if "uddg" in qs:
                return _url.unquote(qs["uddg"][0])
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                return _url.unquote(m.group(1))
        if href.startswith("//"):
            return "https:" + href
        return href
    except Exception:
        return href


def _parse_ddg_html(html_text: str, limit: int) -> tuple[list[dict], bool]:
    if any(m in html_text for m in _DDG_CAPTCHA_MARKERS):
        return [], True
    out: list[dict] = []
    for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.S | re.I):
        raw_href, title_html = m.group(1), m.group(2)
        title = re.sub(r"<[^>]+>", "", title_html)
        title = _html.unescape(title).strip()
        url = _decode_ddg_href(_html.unescape(raw_href.strip()))
        snippet = ""
        seg = html_text[m.end():m.end() + 3000]
        for sm in re.finditer(r'class="result__snippet"[^>]*>(.*?)</\w+>', seg, re.S | re.I):
            cand = _html.unescape(re.sub(r"<[^>]+>", "", sm.group(1))).strip()
            if len(cand) >= 8:
                snippet = cand
                break
        if title and url.startswith("http"):
            out.append({"title": title[:220], "url": url, "snippet": snippet[:400], "source": "web"})
        if len(out) >= limit:
            break
    if not out:
        for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>([^<]{8,160})</a>', html_text):
            href, title = m.group(1), _html.unescape(m.group(2)).strip()
            if "duckduckgo.com" in href or not href.startswith("http"):
                continue
            out.append({"title": title[:220], "url": href, "snippet": "", "source": "web"})
            if len(out) >= limit:
                break
    return out, False


def search_ddg(query: str, freshness: str = "", region_: str = "", limit: int = 8) -> tuple[list[dict], str]:
    note = ""
    form = {"q": query, "kl": region_ or region()}
    if freshness in _FRESH_TO_DF:
        form["df"] = _FRESH_TO_DF[freshness]
    try:
        r = _http("POST", "https://html.duckduckgo.com/html/", headers=_browser_headers(),
                  data=form)
        if r.status_code != 200:
            return [], f"DDG http {r.status_code}"
        results, blocked = _parse_ddg_html(r.text or "", limit)
        if blocked:
            try:
                r2 = _http("GET", "https://lite.duckduckgo.com/lite/", headers=_browser_headers(),
                          params={"q": query})
                results2, blocked2 = _parse_ddg_html(r2.text or "", limit)
                if not blocked2 and results2:
                    return results2, "(DDG html blocked; lite fallback)"
            except Exception:
                pass
            return [], "(DDG blocked; partial results)"
        return results, note
    except Exception as exc:
        return [], f"DDG error: {exc}"


# ---- Google News RSS ----

def _inject_when(query: str, when: str) -> str:
    if not when or re.search(r"\bwhen:\S+|\bafter:\S+|\bbefore:\S+", query):
        return query
    return f"{query} when:{when}"


def news_gnews(query: str, when: str = "1d", limit: int = 8) -> tuple[list[dict], str]:
    import xml.etree.ElementTree as _et
    q = _inject_when(query, when)
    params = {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    try:
        r = _http("GET", "https://news.google.com/rss/search", headers=_honest_headers(), params=params)
        if r.status_code != 200:
            return [], f"GNews http {r.status_code}"
        try:
            root = _et.fromstring(r.text or "")
        except Exception:
            return [], "GNews: bad XML response"
        out: list[dict] = []
        for item in root.iter("item"):
            def _t(tag):
                el = item.find(tag)
                return (el.text or "").strip() if el is not None and el.text else ""
            title = _t("title")
            link = _t("link")
            pub = _t("pubDate")
            src_el = item.find("source")
            src = (src_el.text or "").strip() if src_el is not None and src_el.text else "news"
            desc = re.sub(r"<[^>]+>", "", _t("description") or "")
            if title and link:
                out.append({"title": _html.unescape(title)[:220], "url": link,
                            "snippet": _html.unescape(desc)[:400], "source": src or "news",
                            "date": pub[:32]})
            if len(out) >= limit:
                break
        return out, ""
    except Exception as exc:
        return [], f"GNews error: {exc}"


# ---- Wikipedia ----

def search_wikipedia(query: str, limit: int = 5) -> tuple[list[dict], str]:
    params = {"action": "query", "list": "search", "format": "json",
              "srsearch": query, "srlimit": max(1, min(limit, 20)), "srprop": "snippet"}
    try:
        r = _http("GET", "https://en.wikipedia.org/w/api.php", headers=_honest_headers(), params=params)
        if r.status_code != 200:
            return [], f"Wiki http {r.status_code}"
        try:
            data = r.json()
        except Exception:
            return [], "Wiki: bad JSON"
        out = []
        for item in ((data.get("query") or {}).get("search") or [])[:limit]:
            title = str(item.get("title") or "")
            snip = re.sub(r"<[^>]+>", "", str(item.get("snippet") or ""))
            url = "https://en.wikipedia.org/wiki/" + _url.quote(title.replace(" ", "_"))
            out.append({"title": title[:220], "url": url, "snippet": _html.unescape(snip)[:400],
                        "source": "wikipedia"})
        return out, ""
    except Exception as exc:
        return [], f"Wiki error: {exc}"


# ---- Hacker News ----

_WHEN_TO_SEC = {"1h": 3600, "1d": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "1y": 365 * 86400}


def search_hn(query: str, when: str = "", limit: int = 5) -> tuple[list[dict], str]:
    params = {"query": query, "tags": "story", "hitsPerPage": max(1, min(limit, 20))}
    if when in _WHEN_TO_SEC:
        params["numericFilters"] = f"created_at_i>{int(time.time()) - _WHEN_TO_SEC[when]}"
    try:
        r = _http("GET", "https://hn.algolia.com/api/v1/search", headers=_honest_headers(), params=params)
        if r.status_code != 200:
            return [], f"HN http {r.status_code}"
        try:
            data = r.json()
        except Exception:
            return [], "HN: bad JSON"
        out = []
        for h in (data.get("hits") or [])[:limit]:
            title = str(h.get("title") or "")
            url = str(h.get("url") or "") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            pts = h.get("points", "")
            out.append({"title": title[:220] or url, "url": url,
                        "snippet": f"{pts} points by {h.get('author', '?')}"[:200], "source": "hn"})
        return out, ""
    except Exception as exc:
        return [], f"HN error: {exc}"


# ---- Reddit (best-effort) ----

def search_reddit(query: str, when: str = "", limit: int = 5) -> tuple[list[dict], str]:
    tmap = {"1h": "hour", "1d": "day", "7d": "week", "30d": "month", "1y": "year"}
    params = {"q": query, "limit": max(1, min(limit, 20)), "sort": "new",
              "t": tmap.get(when, "week")}
    try:
        r = _http("GET", "https://www.reddit.com/search.json", headers=_honest_headers(), params=params)
        if r.status_code != 200:
            return [], f"Reddit http {r.status_code} (rate-limited?)"
        try:
            data = r.json()
        except Exception:
            return [], "Reddit: bad JSON"
        out = []
        for child in ((data.get("data") or {}).get("children") or [])[:limit]:
            d = child.get("data") or {}
            title = str(d.get("title") or "")
            url = "https://www.reddit.com" + str(d.get("permalink") or "")
            out.append({"title": title[:220], "url": url,
                        "snippet": f"r/{d.get('subreddit')} · {d.get('score')}↑ · {d.get('num_comments')} comments"[:200],
                        "source": "reddit"})
        return out, ""
    except Exception as exc:
        return [], f"Reddit error: {exc}"


_TECH_HINTS = ("python", "javascript", "typescript", "rust", "golang", " llm", " ai ", "api", "github",
               "startup", "launch", "framework", "database", "linux", "dev", "code", "app ")


def _is_techy(query: str) -> bool:
    low = f" {(query or '').lower()} "
    return any(h.strip() and h in low for h in _TECH_HINTS)


def search(query: str, backend: str = "auto", when: str = "", limit: int = 8,
           use_cache: bool = True) -> tuple[list[dict], str]:
    q = (query or "").strip()
    if not q:
        return [], "ERROR: 'query' is required."
    backend = (backend or "auto").strip().lower()
    limit = max(1, min(int(limit or 8), 20))
    ck = _cache_key("search", q=q, backend=backend, when=when or "", limit=limit)
    if use_cache:
        hit, ok = cache_get(ck)
        if ok:
            try:
                data = json.loads(hit)
                for r in data:
                    r["cached"] = True
                mins = max(1, int(cache_age(ck) // 60)) if cache_age(ck) > 60 else 0
                tag = f"(cached {mins}m ago)" if mins else "(cached just now)"
                return data, tag
            except Exception:
                pass
    if backend == "web":
        results, note = search_ddg(q, freshness=when or "", limit=limit)
        notes = [note] if note else []
    elif backend == "wikipedia":
        results, note = search_wikipedia(q, limit=limit)
        notes = [note] if note else []
    elif backend == "hn":
        results, note = search_hn(q, when=when or "", limit=limit)
        notes = [note] if note else []
    elif backend == "reddit":
        results, note = search_reddit(q, when=when or "", limit=limit)
        notes = [note] if note else []
    else:
        import concurrent.futures as _cf
        jobs = [("ddg", lambda: search_ddg(q, freshness=when or "", limit=limit)),
                ("wiki", lambda: search_wikipedia(q, limit=5))]
        if when or _is_techy(q):
            jobs.append(("hn", lambda: search_hn(q, when=when or "", limit=5)))
        if "news" in q.lower() or "today" in q.lower() or when:
            jobs.insert(1, ("news", lambda: news_gnews(q, when=when or "7d", limit=5)))
        bag: dict[str, tuple[list[dict], str]] = {}
        with _cf.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futs = {ex.submit(fn): name for name, fn in jobs}
            for fut in _cf.as_completed(futs):
                try:
                    bag[futs[fut]] = fut.result()
                except Exception as exc:
                    bag[futs[fut]] = ([], f"{futs[fut]} error: {exc}")
        order = ["ddg", "news", "wiki", "hn"]
        results, notes = [], []
        for name in order:
            rs, nt = bag.get(name, ([], ""))
            results.extend(rs or [])
            if nt:
                notes.append(nt)
    seen, fused = set(), []
    for r in results:
        key = normalize_url(r.get("url", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        fused.append(r)
        if len(fused) >= limit:
            break
    try:
        cache_put(ck, json.dumps(fused))
    except Exception:
        pass
    note = "; ".join(n for n in notes if n)
    return fused, note


def news(query: str, when: str = "1d", limit: int = 8, use_cache: bool = True) -> tuple[list[dict], str]:
    q = (query or "").strip()
    if not q:
        return [], "ERROR: 'query' is required."
    limit = max(1, min(int(limit or 8), 20))
    ck = _cache_key("news", q=q, when=when, limit=limit)
    if use_cache:
        hit, ok = cache_get(ck)
        if ok:
            try:
                return json.loads(hit), "(cached)"
            except Exception:
                pass
    results, note = news_gnews(q, when=when or "1d", limit=limit)
    try:
        cache_put(ck, json.dumps(results))
    except Exception:
        pass
    return results, note


# ---- page fetch ----

class _TextExtract(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript"}

    def __init__(self):
        super().__init__()
        self._skip = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP:
            self._skip += 1
        elif tag.lower() in ("p", "br", "h1", "h2", "h3", "h4", "li", "tr"):
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP and self._skip:
            self._skip -= 1
        elif tag.lower() in ("p", "h1", "h2", "h3", "h4", "li"):
            self._chunks.append("\n")

    def handle_data(self, data):
        if not self._skip and data and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        blob = "".join(self._chunks)
        blob = _html.unescape(blob)
        blob = re.sub(r"[ \t]+", " ", blob)
        blob = re.sub(r"\n\s*\n+", "\n\n", blob)
        return blob.strip()


def _extract_readable(html_text: str) -> str:
    try:
        p = _TextExtract()
        p.feed(html_text[:500000])
        return p.text()
    except Exception:
        txt = re.sub(r"<script.*?</script>", " ", html_text, flags=re.S | re.I)
        txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
        return re.sub(r"\s+", " ", _html.unescape(txt)).strip()


def fetch(url: str, max_chars: int = 0, raw: bool = False, use_cache: bool = True) -> tuple[str, str]:
    u = (url or "").strip()
    if not u or not re.match(r"^https?://", u, re.I):
        return "", "ERROR: 'url' must start with http(s)://."
    cap = int(max_chars or 0) or max_output()
    ck = _cache_key("fetch", url=normalize_url(u), cap=cap, raw=raw)
    if use_cache:
        hit, ok = cache_get(ck)
        if ok:
            return hit, "(cached)"
    try:
        r = _http("GET", u, headers=_browser_headers())
        if r.status_code != 200:
            return "", f"ERROR: fetch http {r.status_code} for {u}."
        ctype = (r.headers.get("Content-Type", "") or "").lower()
        if "json" in ctype:
            try:
                text = json.dumps(r.json(), indent=2, ensure_ascii=False)
            except Exception:
                text = r.text or ""
        elif "html" in ctype or "<html" in (r.text or "")[:2000].lower():
            if raw:
                text = r.text or ""
            else:
                text = _extract_readable(r.text or "")
        else:
            text = r.text or ""
        text = (text or "").strip()
        if len(text) < 600 and not raw and jina_fallback() and u.startswith("http"):
            try:
                jr = _http("GET", "https://r.jina.ai/" + u, headers=_honest_headers())
                if jr.status_code == 200 and len((jr.text or "").strip()) > len(text):
                    text = jr.text.strip()
            except Exception:
                pass
        if not text:
            return "", f"ERROR: no readable text at {u}."
        out, _ = truncate_output(text, cap)
        try:
            cache_put(ck, out)
        except Exception:
            pass
        return out, ""
    except Exception as exc:
        return "", f"ERROR: fetch failed for {u}: {exc}"


# ---- renderers ----

def format_search(results: list[dict], note: str = "") -> str:
    if not results:
        return (f"ERROR: no results.{(' ' + note) if note else ''}").strip()
    lines = []
    for i, r in enumerate(results, 1):
        tag = r.get("source", "web")
        date = f" ({r['date']})" if r.get("date") else ""
        lines.append(f"[{i}] {r.get('title', '(untitled)')} — {tag}{date}\n    {r.get('snippet', '')[:300]}\n    {r.get('url', '')}")
    if note:
        lines.append(f"({note})")
    out = "\n".join(lines)
    capped, _ = truncate_output(out)
    return capped


def format_news(results: list[dict], note: str = "") -> str:
    return format_search(results, note)
