"""Scrapling-powered scraping for Zumba (tiers low / mid / high).

Distinct from ``tools/websearch.py::fetch`` on purpose:
- ``web_fetch`` = general single-page reading (requests + Jina fallback).
- ``scrape_*`` = ONLY when the user asks to *scrape*: structured fields,
  anti-bot pages, or multi-page crawls.

Tiers (the model picks by user need, no hardcoded keyword routing):
- low:  fast static fetch (Scrapling ``Fetcher`` w/ Chrome impersonation),
  one page, readable text/markdown, no browser.
- mid:  static first, auto-escalate to ``StealthyFetcher`` (Cloudflare
  solver, headless Chromium) on structural block signals (HTTP
  403/429/503 or thin body). Optional CSS/XPath selectors for fields.
- high: multi-page BFS crawl (depth<=2, pages<=20, same-domain default),
  reusing one stealth session for pages that failed statically.

Conventions (match websearch.py / geo.py):
- ERROR: text prefix on failures, never raise into chat.
- ZUMBA_NO_SCRAPE=1 kill-switch.
- Cache via websearch cache infra (distinct key prefix), head+tail truncate.
"""

from __future__ import annotations

import json
import logging as _logging
import os
import re
import time
import urllib.parse as _url

# Scrapling re-applies INFO to its logger on EVERY fetch (setup_logger is
# lru_cached and re-called per request), so setLevel alone never sticks.
# A logger-level Filter survives that: it lives on the logger object and is
# consulted for every record regardless of level resets/handler re-adds.
class _ScraplingNoiseFilter(_logging.Filter):
    _DROP = ("Fetched (", "No Cloudflare challenge found")

    def filter(self, record) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return not any(s in msg for s in self._DROP)


def _silence_scrapling() -> None:
    try:
        lg = _logging.getLogger("scrapling")
        if not any(isinstance(f, _ScraplingNoiseFilter) for f in lg.filters):
            lg.addFilter(_ScraplingNoiseFilter())
        lg.setLevel(_logging.WARNING)
        for name in list(_logging.root.manager.loggerDict):
            if name.startswith("scrapling."):
                try:
                    _logging.getLogger(name).setLevel(_logging.WARNING)
                except Exception:
                    pass
    except Exception:
        pass


_silence_scrapling()


def enabled() -> bool:
    return os.getenv("ZUMBA_NO_SCRAPE", "") != "1"


def timeout_s() -> float:
    try:
        return max(2.0, float(os.getenv("ZUMBA_SCRAPE_TIMEOUT", "30") or 30))
    except Exception:
        return 30.0


def stealth_timeout_ms() -> int:
    try:
        return max(5000, int(float(os.getenv("ZUMBA_SCRAPE_STEALTH_TIMEOUT", "30") or 30) * 1000))
    except Exception:
        return 30000


def max_output() -> int:
    try:
        return max(500, int(os.getenv("ZUMBA_SCRAPE_MAX_OUTPUT", "8000") or 8000))
    except Exception:
        return 8000


def max_pages() -> int:
    try:
        return max(1, min(50, int(os.getenv("ZUMBA_SCRAPE_MAX_PAGES", "20") or 20)))
    except Exception:
        return 20


def retries() -> int:
    try:
        return max(0, min(3, int(os.getenv("ZUMBA_SCRAPE_RETRIES", "1") or 1)))
    except Exception:
        return 1


_THIN_BODY_CHARS = 600
_BLOCK_STATUS = (403, 429, 503)


# ---- small helpers (pure, unit-testable) ----

def is_url(u: str) -> bool:
    return bool(re.match(r"^https?://", (u or "").strip(), re.I))


def normalize_url(u: str) -> str:
    try:
        from tools.websearch import normalize_url as _norm
        return _norm(u)
    except Exception:
        return (u or "").strip().rstrip("/")


def truncate_output(text: str, cap: int = 0) -> tuple[str, bool]:
    try:
        from tools.websearch import truncate_output as _trunc
        return _trunc(text, cap or max_output())
    except Exception:
        cap = cap or max_output()
        if len(text) <= cap:
            return text, False
        head = cap * 4 // 5
        return text[:head] + f"\n[...truncated {len(text) - cap} chars...]\n" + text[-head:], True


def _host_blocked_reason(url: str) -> str:
    """SSRF guard: refuse non-public hosts (loopback/private/link-local/etc).

    Structural check only (DNS + ipaddress globals), never content cues.
    Unresolvable hosts fail closed.
    """
    import ipaddress
    import socket
    try:
        host = (_url.urlparse((url or "").strip()).hostname or "").strip().lower().rstrip(".")
    except Exception:
        return "unparseable URL"
    if not host:
        return "missing host"
    if host in ("localhost",):
        return "loopback host"
    try:
        ips = [r[4][0] for r in socket.getaddrinfo(host, None)]
    except Exception:
        return f"DNS does not resolve: {host}"
    if not ips:
        return f"DNS does not resolve: {host}"
    for ip in ips:
        try:
            if not ipaddress.ip_address(ip.split("%")[0]).is_global:
                return f"non-public address ({ip})"
        except Exception:
            return f"unparseable address ({ip})"
    return ""


def check_url_public(url: str) -> str:
    """'' when fetchable, else 'ERROR: ...' SSRF refusal. Never raises."""
    reason = _host_blocked_reason(url)
    if reason:
        return f"ERROR: refusing to fetch {url} ({reason})."
    return ""


def json_out(items: list, cap: int = 0) -> str:
    """Serialize to JSON that always parses: shrink text/fields to fit cap.

    Never slices serialized JSON (which would corrupt it). Marks shrunk
    items with "truncated": true.
    """
    cap = cap or max_output()
    blob = json.dumps(items, ensure_ascii=False)
    if len(blob) <= cap:
        return blob
    shrunk = False
    budget = max(200, cap // max(1, len(items)))
    for it in items:
        if not isinstance(it, dict):
            continue
        if isinstance(it.get("text"), str) and len(it["text"]) > budget:
            it["text"] = it["text"][:budget]
            it["truncated"] = True
            shrunk = True
        fields = it.get("fields")
        if isinstance(fields, dict):
            for k, vals in fields.items():
                if isinstance(vals, list):
                    cut = [str(v)[:min(500, budget)] for v in vals[:10]]
                    if cut != vals:
                        fields[k] = cut
                        shrunk = True
            if shrunk:
                it["truncated"] = True
    blob = json.dumps(items, ensure_ascii=False)
    if len(blob) > cap:
        # last resort: hard per-item text budget, still valid JSON
        tiny = max(200, cap // max(1, len(items)) // 2)
        for it in items:
            if isinstance(it, dict):
                if isinstance(it.get("text"), str):
                    it["text"] = it["text"][:tiny]
                    it["truncated"] = True
                if isinstance(it.get("fields"), dict):
                    for k in it["fields"]:
                        it["fields"][k] = [str(v)[:tiny] for v in it["fields"][k][:5]]
                    it["truncated"] = True
        blob = json.dumps(items, ensure_ascii=False)
    return blob


def parse_selectors(raw) -> dict:
    """Accept dict, 'k=css, k2=css' string, or list of 'k=css'. Never raises."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k).strip(): str(v).strip() for k, v in raw.items()
                if str(k).strip() and str(v).strip()}
    if isinstance(raw, (list, tuple)):
        out: dict = {}
        for item in raw:
            s = str(item or "")
            if "=" in s:
                k, v = s.split("=", 1)
                if k.strip() and v.strip():
                    out[k.strip()] = v.strip()
        return out
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            maybe = json.loads(s)
            if isinstance(maybe, dict):
                return parse_selectors(maybe)
        except Exception:
            pass
        out = {}
        for part in re.split(r"[;,\n]+", s):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() and v.strip():
                    out[k.strip()] = v.strip()
            elif part.strip():
                out[part.strip()] = part.strip()
        return out
    return {}


def _select(resp, selector: str) -> list[str]:
    """Run one CSS (default) or XPath ('xpath:...' prefix) selector. Never raises."""
    sel = (selector or "").strip()
    if not sel or resp is None:
        return []
    try:
        if sel.lower().startswith("xpath:"):
            nodes = resp.xpath(sel[6:].strip())
        else:
            nodes = resp.css(sel)
    except Exception:
        return []
    vals: list[str] = []
    try:
        for n in (nodes or []):
            try:
                if hasattr(n, "get"):
                    v = n.get()
                else:
                    v = str(n)
            except Exception:
                continue
            if v is None:
                continue
            v = str(v).strip()
            if sel.lower().endswith("::text"):
                # Scrapling 0.4 get() may serialize the element; ::text wants inner text.
                v = re.sub(r"<[^>]+>", " ", v)
                import html as _html2
                v = _html2.unescape(re.sub(r"\s+", " ", v)).strip()
            if v:
                vals.append(v[:500])
            if len(vals) >= 20:
                break
    except Exception:
        return vals
    return vals


def extract_fields(resp, selectors: dict) -> dict:
    """Map field -> list of extracted strings. Pure w.r.t. parsing (no I/O)."""
    out: dict = {}
    for field, sel in (selectors or {}).items():
        try:
            out[str(field)] = _select(resp, str(sel))
        except Exception:
            out[str(field)] = []
    return out


def response_text(resp, format: str = "markdown") -> str:
    """Readable text from a Scrapling Response. Never raises."""
    fmt = (format or "markdown").strip().lower()
    if resp is None:
        return ""
    try:
        if fmt == "markdown":
            try:
                md = resp.markdown()
                if md and str(md).strip():
                    return str(md).strip()
            except Exception:
                pass
        try:
            t = resp.get_all_text(ignore_tags=("script", "style", "nav", "footer", "header", "aside", "form", "noscript"))
            if t and str(t).strip():
                return str(t).strip()
        except Exception:
            pass
        try:
            body = resp.body or b""
            if isinstance(body, (bytes, bytearray)):
                return bytes(body).decode(resp.encoding or "utf-8", errors="replace").strip()
            return str(body).strip()
        except Exception:
            return ""
    except Exception:
        return ""


def extract_links(resp, base_url: str = "") -> list[str]:
    """Absolute http(s) links from a page. Never raises."""
    if resp is None:
        return []
    hrefs: list[str] = []
    try:
        for v in _select(resp, "a::attr(href)"):
            hrefs.append(v)
    except Exception:
        return []
    out: list[str] = []
    for h in hrefs:
        h = (h or "").strip()
        if not h or h.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        try:
            absu = resp.urljoin(h) if hasattr(resp, "urljoin") else _url.urljoin(base_url, h)
        except Exception:
            absu = h
        if is_url(absu):
            out.append(absu)
    # de-dupe, preserve order
    seen, uniq = set(), []
    for u in out:
        k = normalize_url(u)
        if k not in seen:
            seen.add(k)
            uniq.append(u)
    return uniq


# ---- fetchers (I/O; import scrapling lazily so tests can stub) ----

def static_get(url: str):
    _silence_scrapling()
    from scrapling.fetchers import Fetcher
    return Fetcher.get(
        url,
        impersonate="chrome",
        stealthy_headers=True,
        follow_redirects="safe",
        timeout=timeout_s(),
        retries=retries(),
    )


def stealth_fetch(url: str, wait_selector: str = ""):
    _silence_scrapling()
    from scrapling.fetchers import StealthyFetcher
    kw: dict = dict(
        headless=True,
        solve_cloudflare=True,
        network_idle=True,
        timeout=stealth_timeout_ms(),
        block_webrtc=True,
    )
    if (wait_selector or "").strip():
        kw["wait_selector"] = wait_selector.strip()
    return StealthyFetcher.fetch(url, **kw)


def _body_len(resp) -> int:
    try:
        return len(response_text(resp, "text"))
    except Exception:
        return 0


def needs_stealth(resp) -> bool:
    """Structural block signal only (status / body length) — never content cues."""
    if resp is None:
        return True
    try:
        if int(getattr(resp, "status", 200) or 200) in _BLOCK_STATUS:
            return True
    except Exception:
        pass
    return _body_len(resp) < _THIN_BODY_CHARS


def _cache_key(kind: str, **parts) -> str:
    try:
        from tools.websearch import _cache_key as _ck
        return "scrape:" + _ck(kind, **parts)
    except Exception:
        import hashlib
        blob = kind + "|" + "|".join(f"{k}={parts.get(k, '')}" for k in sorted(parts))
        return "scrape:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _cache_get(key: str):
    try:
        from tools.websearch import cache_get
        return cache_get(key)
    except Exception:
        return None, False


def _cache_put(key: str, data: str) -> None:
    try:
        from tools.websearch import cache_put
        cache_put(key, data)
    except Exception:
        pass


# ---- tiers ----

def scrape_low(url: str, format: str = "markdown", max_chars: int = 0,
               use_cache: bool = True) -> tuple[str, str]:
    """LOW: fast static fetch, one page, readable text. No browser, no selectors."""
    u = (url or "").strip().split()[0] if (url or "").strip() else ""
    if not is_url(u):
        return "", "ERROR: 'url' must start with http(s)://."
    denied = check_url_public(u)
    if denied:
        return "", denied
    fmt = (format or "markdown").strip().lower() or "markdown"
    if fmt not in ("markdown", "text", "json"):
        return "", "ERROR: 'format' must be markdown, text, or json."
    cap = int(max_chars or 0) or max_output()
    ck = _cache_key("low", url=normalize_url(u), format=fmt, cap=cap)
    if use_cache:
        hit, ok = _cache_get(ck)
        if ok and hit:
            return hit, "(cached; low/static)"
    try:
        resp = static_get(u)
    except Exception as exc:
        return "", f"ERROR: scrape-low fetch failed for {u}: {exc}"
    landed = check_url_public(str(getattr(resp, "url", "") or u))
    if landed:
        return "", landed + " (redirect landed on a non-public host)."
    try:
        status = int(getattr(resp, "status", 200) or 200)
    except Exception:
        status = 200
    if status in _BLOCK_STATUS:
        return "", (f"ERROR: {u} blocked static fetch (http {status}). "
                    "Use scrape-mid (auto stealth) for this page.")
    if status < 200 or status >= 400:
        return "", f"ERROR: scrape-low http {status} for {u}."
    text = response_text(resp, fmt if fmt != "json" else "markdown")
    if fmt == "json":
        import html as _html
        title = ""
        try:
            t = _select(resp, "title::text")
            title = (t[0] if t else "")[:220]
            title = _html.unescape(title)
        except Exception:
            title = ""
        text = json_out([{"url": u, "title": title, "text": text}], cap)
        text = (text or "").strip()
        if not text:
            return "", (f"ERROR: no readable text at {u} (static). "
                        "Use scrape-mid for JS/blocked pages.")
        try:
            _cache_put(ck, text)
        except Exception:
            pass
        return text, "(low/static)"
    text = (text or "").strip()
    if not text:
        return "", (f"ERROR: no readable text at {u} (static). "
                    "Use scrape-mid for JS/blocked pages.")
    out, _ = truncate_output(text, cap)
    try:
        _cache_put(ck, out)
    except Exception:
        pass
    return out, "(low/static)"


def scrape_mid(url: str, selectors=None, format: str = "markdown", mode: str = "auto",
               wait_selector: str = "", max_chars: int = 0,
               use_cache: bool = True) -> tuple[str, str]:
    """MID: static first, auto-escalate to stealth browser on block signals.

    mode: auto (default) | static | stealth.
    selectors: dict field->css (or 'xpath:...'), string 'k=css, ...', or list.
    """
    u = (url or "").strip().split()[0] if (url or "").strip() else ""
    if not is_url(u):
        return "", "ERROR: 'url' must start with http(s)://."
    denied = check_url_public(u)
    if denied:
        return "", denied
    md = (mode or "auto").strip().lower() or "auto"
    if md not in ("auto", "static", "stealth"):
        return "", "ERROR: 'mode' must be auto, static, or stealth."
    fmt = (format or "markdown").strip().lower() or "markdown"
    if fmt not in ("markdown", "text", "json"):
        return "", "ERROR: 'format' must be markdown, text, or json."
    sels = parse_selectors(selectors)
    cap = int(max_chars or 0) or max_output()
    ck = _cache_key("mid", url=normalize_url(u), sels=json.dumps(sels, sort_keys=True),
                    format=fmt, mode=md, cap=cap)
    if use_cache:
        hit, ok = _cache_get(ck)
        if ok and hit:
            return hit, "(cached; mid)"
    resp = None
    used = "static"
    if md in ("auto", "static"):
        try:
            resp = static_get(u)
        except Exception as exc:
            if md == "static":
                return "", f"ERROR: scrape-mid static fetch failed for {u}: {exc}"
            resp = None
    if md == "stealth" or (md == "auto" and needs_stealth(resp)):
        try:
            resp = stealth_fetch(u, wait_selector)
            used = "stealth"
        except Exception as exc:
            if resp is None:
                return "", f"ERROR: scrape-mid stealth fetch failed for {u}: {exc}"
            used = "static+stealth-failed"
    if resp is None:
        return "", f"ERROR: scrape-mid fetch failed for {u}."
    landed = check_url_public(str(getattr(resp, "url", "") or u))
    if landed:
        return "", landed + " (redirect landed on a non-public host)."
    try:
        status = int(getattr(resp, "status", 200) or 200)
    except Exception:
        status = 200
    if status < 200 or status >= 400:
        return "", f"ERROR: scrape-mid http {status} for {u} ({used})."
    if sels:
        fields = extract_fields(resp, sels)
        out = json_out([{"url": u, "mode": used, "fields": fields}], cap)
        try:
            _cache_put(ck, out)
        except Exception:
            pass
        return out, f"(mid/{used}; {len(sels)} selector(s))"
    text = response_text(resp, fmt if fmt != "json" else "markdown")
    if fmt == "json":
        import html as _html
        title = ""
        try:
            t = _select(resp, "title::text")
            title = _html.unescape((t[0] if t else "")[:220])
        except Exception:
            title = ""
        out = json_out([{"url": u, "mode": used, "title": title,
                         "text": text or ""}], cap)
        if not out.strip():
            return "", f"ERROR: no readable text at {u} ({used})."
        try:
            _cache_put(ck, out)
        except Exception:
            pass
        return out, f"(mid/{used})"
    text = (text or "").strip()
    if not text:
        return "", f"ERROR: no readable text at {u} ({used})."
    out, _ = truncate_output(text, cap)
    try:
        _cache_put(ck, out)
    except Exception:
        pass
    return out, f"(mid/{used})"


def scrape_high(urls, depth: int = 1, limit: int = 8, same_domain: bool = True,
                selectors=None, mode: str = "auto", max_chars: int = 0,
                use_cache: bool = True) -> tuple[str, str]:
    """HIGH: multi-page BFS crawl. depth<=2, pages<=limit (<=max_pages)."""
    if isinstance(urls, str):
        seeds = [s for s in re.split(r"[\s,;]+", urls) if s]
    else:
        seeds = [str(s or "").strip() for s in (urls or []) if str(s or "").strip()]
    seeds = [s for s in seeds if is_url(s)]
    if not seeds:
        return "", "ERROR: 'urls' must be one or more http(s) URLs."
    for s in seeds:
        denied = check_url_public(s)
        if denied:
            return "", denied
    seed_hosts = set()
    for s in seeds:
        try:
            seed_hosts.add(_url.urlparse(s).netloc.lower())
        except Exception:
            pass
    clamp_notes: list[str] = []
    try:
        want_depth = int(depth if depth is not None else 1)
        depth = max(0, min(2, want_depth))
        if want_depth != depth:
            clamp_notes.append(f"depth clamped {want_depth}->{depth} (max 2)")
    except Exception:
        return "", "ERROR: 'depth' must be a number 0-2."
    try:
        want_limit = int(limit or 8)
        limit = max(1, min(max_pages(), want_limit))
        if want_limit != limit:
            clamp_notes.append(f"limit clamped {want_limit}->{limit} (max {max_pages()})")
    except Exception:
        return "", "ERROR: 'limit' must be a number."
    md = (mode or "auto").strip().lower() or "auto"
    if md not in ("auto", "static", "stealth"):
        return "", "ERROR: 'mode' must be auto, static, or stealth."
    sels = parse_selectors(selectors)
    cap = int(max_chars or 0) or max_output()
    ck = _cache_key("high", urls=",".join(sorted(normalize_url(s) for s in seeds)),
                    depth=depth, limit=limit, same=same_domain,
                    sels=json.dumps(sels, sort_keys=True), mode=md, cap=cap)
    if use_cache:
        hit, ok = _cache_get(ck)
        if ok and hit:
            return hit, "(cached; high)"
    t0 = time.time()
    budget_s = min(240.0, max(20.0, timeout_s() * 4))
    visited: set = set()
    queue: list[tuple[str, int]] = [(s, 0) for s in seeds[:limit]]
    pages: list[dict] = []
    stealth_uses = 0
    while queue and len(pages) < limit and (time.time() - t0) < budget_s:
        cur, d = queue.pop(0)
        key = normalize_url(cur)
        if key in visited:
            continue
        if check_url_public(cur):
            continue
        visited.add(key)
        resp = None
        used = "static"
        if md in ("auto", "static"):
            try:
                resp = static_get(cur)
            except Exception:
                resp = None
        if md == "stealth" or (md == "auto" and needs_stealth(resp)):
            try:
                resp = stealth_fetch(cur, "")
                used = "stealth"
                stealth_uses += 1
            except Exception:
                if resp is None:
                    pages.append({"url": cur, "mode": "failed", "title": "", "text": ""})
                    continue
                used = "static+stealth-failed"
        if resp is None:
            pages.append({"url": cur, "mode": "failed", "title": "", "text": ""})
            continue
        if check_url_public(str(getattr(resp, "url", "") or cur)):
            pages.append({"url": cur, "mode": "blocked-private-redirect", "title": "", "text": ""})
            continue
        try:
            st = int(getattr(resp, "status", 200) or 200)
        except Exception:
            st = 200
        if st < 200 or st >= 400:
            pages.append({"url": cur, "mode": f"http-{st}", "title": "", "text": ""})
            continue
        title = ""
        try:
            t = _select(resp, "title::text")
            import html as _html
            title = _html.unescape((t[0] if t else "")[:220])
        except Exception:
            title = ""
        entry: dict = {"url": cur, "mode": used, "title": title}
        if sels:
            try:
                entry["fields"] = extract_fields(resp, sels)
            except Exception:
                entry["fields"] = {}
        else:
            try:
                entry["text"] = response_text(resp, "markdown")[:2000]
            except Exception:
                entry["text"] = ""
        pages.append(entry)
        if d < depth and len(pages) + len(queue) < limit * 2:
            try:
                for link in extract_links(resp, cur):
                    try:
                        if same_domain and _url.urlparse(link).netloc.lower() not in seed_hosts:
                            continue
                    except Exception:
                        continue
                    if normalize_url(link) not in visited:
                        queue.append((link, d + 1))
            except Exception:
                pass
            time.sleep(0.2)
    if not pages:
        return "", "ERROR: crawl fetched nothing."
    tail = f"(high/{md}; {len(pages)} page(s), {stealth_uses} stealth)"
    if clamp_notes:
        tail += " [" + "; ".join(clamp_notes) + "]"
    out = format_records(pages, tail)
    out, _ = truncate_output(out, cap)
    try:
        _cache_put(ck, out)
    except Exception:
        pass
    return out, tail


# ---- renderers ----

def format_records(pages: list[dict], note: str = "") -> str:
    if not pages:
        return "ERROR: nothing scraped."
    lines = []
    for i, p in enumerate(pages, 1):
        title = (p.get("title") or "(untitled)")[:160]
        lines.append(f"[{i}] {title} — {p.get('mode', '')}\n    {p.get('url', '')}")
        if p.get("fields"):
            for k, vals in (p["fields"] or {}).items():
                shown = "; ".join((vals or [])[:5])[:400] or "(no match)"
                lines.append(f"    {k}: {shown}")
        elif p.get("text"):
            lines.append(f"    {(p['text'] or '')[:500]}")
    if note:
        lines.append(f"({note})")
    out = "\n".join(lines)
    capped, _ = truncate_output(out)
    return capped
