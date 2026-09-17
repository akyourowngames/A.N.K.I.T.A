#!/usr/bin/env python3
"""Scrapling bridge for ankita (Node side: tools/scrape-*.mjs).

Stdlib-only plus a lazy `scrapling` import. Protocol: argv[1] is JSON
{cmd, ...}, stdout is one JSON object. Never prints anything else.

Commands:
  check    -> {ok, scrapling} (probe: is Scrapling importable?)
  static   -> {results: [{url, final_url, status, title, markdown, text,
              links[], fields{}, error}]} for urls[] (Chrome impersonation)
  stealth  -> single result via headless Chromium + Cloudflare solver
"""

from __future__ import annotations

import html as _html
import ipaddress
import json
import logging as _logging
import re
import socket
import sys
import urllib.parse as _url


def _force_utf8() -> None:
    """Windows consoles default stdout to the ANSI codepage, which cannot
    encode characters like U+200B that Wikipedia pages contain — printing the
    JSON then dies with UnicodeEncodeError. Force UTF-8 on both streams."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
        except Exception:
            pass


def _dump(payload: dict) -> None:
    """ensure_ascii keeps the payload pure ASCII so it survives any pipe
    encoding, and flush avoids a truncated read on process exit."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    sys.stdout.write("\n")
    try:
        sys.stdout.flush()
    except Exception:
        pass


def _silence_scrapling() -> None:
    # Scrapling re-applies INFO to its logger on every fetch; a Filter on the
    # logger object survives that, setLevel alone does not.
    class _Drop(_logging.Filter):
        def filter(self, record) -> bool:
            try:
                msg = record.getMessage()
            except Exception:
                return True
            return "Fetched (" not in msg and "No Cloudflare challenge found" not in msg

    try:
        lg = _logging.getLogger("scrapling")
        if not any(isinstance(f, _Drop) for f in lg.filters):
            lg.addFilter(_Drop())
        lg.setLevel(_logging.WARNING)
    except Exception:
        pass


def _host_blocked(url: str) -> str:
    try:
        host = (_url.urlparse((url or "").strip()).hostname or "").strip().lower().rstrip(".")
    except Exception:
        return "unparseable URL"
    if not host:
        return "missing host"
    if host == "localhost":
        return "loopback host"
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return f"DNS does not resolve: {host}"
    ips = [r[4][0] for r in infos]
    if not ips:
        return f"DNS does not resolve: {host}"
    for ip in ips:
        try:
            if not ipaddress.ip_address(ip.split("%")[0]).is_global:
                return f"non-public address ({ip})"
        except Exception:
            return f"unparseable address ({ip})"
    return ""


def _is_url(u: str) -> bool:
    return bool(re.match(r"^https?://", (u or "").strip(), re.I))


def _select(resp, selector: str) -> list:
    sel = (selector or "").strip()
    if not sel or resp is None:
        return []
    try:
        nodes = resp.xpath(sel[6:].strip()) if sel.lower().startswith("xpath:") else resp.css(sel)
    except Exception:
        return []
    vals: list = []
    try:
        for n in nodes or []:
            try:
                v = n.get() if hasattr(n, "get") else str(n)
            except Exception:
                continue
            if v is None:
                continue
            v = str(v).strip()
            if sel.lower().endswith("::text"):
                v = _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", v))).strip()
            if v:
                vals.append(v[:500])
            if len(vals) >= 20:
                break
    except Exception:
        pass
    return vals


def _title(resp) -> str:
    try:
        t = _select(resp, "title::text")
        return _html.unescape((t[0] if t else "")[:220])
    except Exception:
        return ""


def _text(resp, want_markdown: bool) -> str:
    if resp is None:
        return ""
    try:
        if want_markdown:
            try:
                md = resp.markdown()
                if md and str(md).strip():
                    return str(md).strip()
            except Exception:
                pass
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


def _links(resp) -> list:
    if resp is None:
        return []
    out, seen = [], set()
    for h in _select(resp, "a::attr(href)"):
        h = (h or "").strip()
        if not h or h.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        try:
            h = resp.urljoin(h) if hasattr(resp, "urljoin") else _url.urljoin("", h)
        except Exception:
            pass
        if _is_url(h) and h not in seen:
            seen.add(h)
            out.append(h)
        if len(out) >= 200:
            break
    return out


def _history_urls(resp) -> list:
    urls: list = []
    try:
        for h in getattr(resp, "history", None) or []:
            u = str(getattr(h, "url", "") or "")
            if u and u not in urls:
                urls.append(u)
    except Exception:
        pass
    try:
        final = str(getattr(resp, "url", "") or "")
        if final and final not in urls:
            urls.append(final)
    except Exception:
        pass
    return urls


def _result(url: str, resp, selectors: dict, want_markdown: bool) -> dict:
    try:
        status = int(getattr(resp, "status", 200) or 200)
    except Exception:
        status = 200
    fields = {}
    for field, sel in (selectors or {}).items():
        try:
            fields[str(field)] = _select(resp, str(sel))
        except Exception:
            fields[str(field)] = []
    return {
        "url": url,
        "final_url": str(getattr(resp, "url", "") or url),
        "history": _history_urls(resp),
        "status": status,
        "title": _title(resp),
        "markdown": _text(resp, True) if want_markdown else "",
        "text": _text(resp, False),
        "links": _links(resp),
        "fields": fields,
        "error": "",
    }


def _parse_selectors(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k).strip(): str(v).strip() for k, v in raw.items() if str(k).strip() and str(v).strip()}
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            maybe = json.loads(raw)
            if isinstance(maybe, dict):
                return _parse_selectors(maybe)
        except Exception:
            pass
        out = {}
        for part in re.split(r"[;,\n]+", raw):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() and v.strip():
                    out[k.strip()] = v.strip()
            elif part.strip():
                out[part.strip()] = part.strip()
        return out
    return {}


def cmd_check(_args: dict) -> dict:
    try:
        import scrapling  # noqa: F401
        ver = getattr(scrapling, "__version__", "unknown")
        return {"ok": True, "scrapling": str(ver)}
    except Exception as exc:
        return {"ok": False, "error": f"scrapling not importable: {exc}"}


def cmd_static(args: dict) -> dict:
    _silence_scrapling()
    try:
        from scrapling.fetchers import Fetcher
    except Exception as exc:
        return {"ok": False, "error": f"scrapling import failed: {exc}"}
    urls = args.get("urls") or ([args.get("url")] if args.get("url") else [])
    timeout = max(2.0, float(args.get("timeout_s") or 30))
    retries = max(0, min(3, int(args.get("retries") or 0)))
    selectors = _parse_selectors(args.get("selectors"))
    want_markdown = bool(args.get("markdown", True))
    results = []
    for url in urls:
        u = str(url or "").strip().split()[0] if str(url or "").strip() else ""
        if not _is_url(u):
            results.append({"url": u, "error": "not an http(s) URL"})
            continue
        blocked = _host_blocked(u)
        if blocked:
            results.append({"url": u, "error": f"refusing ({blocked})"})
            continue
        try:
            resp = Fetcher.get(u, impersonate="chrome", stealthy_headers=True,
                               follow_redirects="safe", timeout=timeout, retries=retries)
        except Exception as exc:
            results.append({"url": u, "error": f"fetch failed: {exc}"})
            continue
        results.append(_result(u, resp, selectors, want_markdown))
    return {"ok": True, "results": results}


def cmd_stealth(args: dict) -> dict:
    _silence_scrapling()
    try:
        from scrapling.fetchers import StealthyFetcher
    except Exception as exc:
        return {"ok": False, "error": f"scrapling import failed: {exc}"}
    u = str(args.get("url") or "").strip().split()[0] if str(args.get("url") or "").strip() else ""
    if not _is_url(u):
        return {"ok": False, "error": "not an http(s) URL"}
    blocked = _host_blocked(u)
    if blocked:
        return {"ok": False, "error": f"refusing ({blocked})"}
    kw: dict = dict(headless=True, solve_cloudflare=True, network_idle=True,
                    timeout=max(5000, int(args.get("timeout_ms") or 30000)), block_webrtc=True)
    if str(args.get("wait_selector") or "").strip():
        kw["wait_selector"] = str(args.get("wait_selector")).strip()
    selectors = _parse_selectors(args.get("selectors"))
    want_markdown = bool(args.get("markdown", True))
    try:
        resp = StealthyFetcher.fetch(u, **kw)
    except Exception as exc:
        return {"ok": False, "error": f"stealth fetch failed: {exc}"}
    out = _result(u, resp, selectors, want_markdown)
    out["mode"] = "stealth"
    return {"ok": True, "result": out}


def main() -> int:
    _force_utf8()
    try:
        args = json.loads(sys.argv[1] if len(sys.argv) > 1 else "{}")
    except Exception as exc:
        _dump({"ok": False, "error": f"bad argv JSON: {exc}"})
        return 2
    cmd = str(args.get("cmd") or "check")
    try:
        if cmd == "static":
            _dump(cmd_static(args))
        elif cmd == "stealth":
            _dump(cmd_stealth(args))
        else:
            _dump(cmd_check(args))
    except Exception as exc:
        _dump({"ok": False, "error": f"bridge crashed: {exc}"})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
