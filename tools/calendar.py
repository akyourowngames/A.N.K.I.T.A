"""Google Calendar integration for Zumba (Issue #5).

Conventions match geo.py / websearch.py:
- ERROR: prefix on failure, never raise into chat.
- ZUMBA_NO_CALENDAR=1 kill-switch.
- In-process cache with TTL, head+tail truncation, timeout <= 10s.
- Never hallucinate: when not connected, honest "not connected" + setup hint.
- Secrets never echoed: token previews redacted.

Auth model (zero new deps, stdlib + requests):
- One global token at ~/.zumba/calendar_token.json (0600).
- Env overrides: ZUMBA_CALENDAR_TOKEN / _REFRESH / _CLIENT_ID / _CLIENT_SECRET.
- Interactive flows (CLI / Telegram / Web) call auth_start() -> URL,
  then auth_finish(code) or set_token(pasted_token).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import time
import urllib.parse as _url
from pathlib import Path

try:
    import requests as _requests
except Exception:  # pragma: no cover
    _requests = None

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"
SETUP_URL = "https://console.cloud.google.com/apis/credentials"
DEFAULT_REDIRECT = "http://localhost:8080/"

_TIMEOUT = 10.0
_CACHE: dict[str, tuple[float, str]] = {}


def enabled() -> bool:
    return os.getenv("ZUMBA_NO_CALENDAR", "") != "1"


def calendar_id_default() -> str:
    return (os.getenv("ZUMBA_CALENDAR_ID") or "primary").strip() or "primary"


def redirect_default() -> str:
    return (os.getenv("ZUMBA_CALENDAR_REDIRECT") or DEFAULT_REDIRECT).strip() or DEFAULT_REDIRECT


def token_path() -> Path:
    try:
        from core.store import zumba_home
        return zumba_home() / "calendar_token.json"
    except Exception:
        p = Path.home() / ".zumba" / "calendar_token.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def _redact(tok: str) -> str:
    t = (tok or "").strip()
    if len(t) <= 8:
        return "****" if t else "(none)"
    return f"****{t[-4:]}"


def load_token() -> dict:
    data: dict = {}
    try:
        p = token_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8") or "{}")
            if not isinstance(data, dict):
                data = {}
    except Exception:
        data = {}
    # Env wins for access token / client bits (lets tests inject without files).
    env_map = {
        "access_token": (os.getenv("ZUMBA_CALENDAR_TOKEN") or "").strip(),
        "refresh_token": (os.getenv("ZUMBA_CALENDAR_REFRESH_TOKEN") or "").strip(),
        "client_id": (os.getenv("ZUMBA_CALENDAR_CLIENT_ID") or "").strip(),
        "client_secret": (os.getenv("ZUMBA_CALENDAR_CLIENT_SECRET") or "").strip(),
    }
    for k, v in env_map.items():
        if v:
            data[k] = v
    return data


def save_token(patch: dict) -> Path:
    p = token_path()
    cur: dict = {}
    try:
        if p.exists():
            cur = json.loads(p.read_text(encoding="utf-8") or "{}") or {}
    except Exception:
        cur = {}
    cur.update({k: v for k, v in (patch or {}).items() if v is not None})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return p


def clear_token() -> bool:
    try:
        p = token_path()
        if p.exists():
            p.unlink()
            return True
    except Exception:
        pass
    return False


def is_connected() -> bool:
    if not enabled():
        return False
    tok = load_token()
    return bool((tok.get("access_token") or "").strip())


def not_connected_msg() -> str:
    return (
        "Calendar is not connected — I can't see any events (and won't guess).\n"
        f"Connect: `zumba calendar auth` (CLI) or /cal auth (chat/Telegram) or the web Connect button.\n"
        f"Setup: create OAuth credentials at {SETUP_URL}, then paste the code/token when asked."
    )


def status_text() -> str:
    if not enabled():
        return "ERROR: calendar tools are disabled (ZUMBA_NO_CALENDAR=1)."
    tok = load_token()
    if not (tok.get("access_token") or "").strip():
        return not_connected_msg()
    bits = [f"connected: yes (token {_redact(tok.get('access_token', ''))})"]
    if (tok.get("refresh_token") or "").strip():
        bits.append(f"refresh: yes ({_redact(tok.get('refresh_token', ''))})")
    if (tok.get("client_id") or "").strip():
        bits.append(f"client_id: …{(tok.get('client_id') or '')[-6:]}")
    bits.append(f"calendar: {calendar_id_default()}")
    return "Calendar status — " + ", ".join(bits)


def _truncate(t: str, cap: int = 4000) -> str:
    if len(t) <= cap:
        return t
    h, tl = cap * 4 // 5, cap - cap * 4 // 5
    return t[:h] + f"\n[...truncated {len(t)-cap} chars...]\n" + t[-tl:]


def _ck(kind: str, **p) -> str:
    blob = kind + "|" + "|".join(f"{k}={p.get(k, '')}" for k in sorted(p))
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _cget(k: str, ttl: float):
    e = _CACHE.get(k)
    if e and (time.time() - e[0]) < ttl:
        return e[1]
    return None


def _cput(k: str, v: str):
    _CACHE[k] = (time.time(), v)


# ---- OAuth helpers (pure URL building + token exchange, no google lib) ----

def auth_start(client_id: str = "", redirect_uri: str = "", state: str = "") -> str:
    if not enabled():
        return "ERROR: calendar tools are disabled (ZUMBA_NO_CALENDAR=1)."
    cid = (client_id or load_token().get("client_id") or os.getenv("ZUMBA_CALENDAR_CLIENT_ID") or "").strip()
    if not cid:
        return (
            "ERROR: no Google client_id yet. "
            f"Create one at {SETUP_URL} (OAuth client, Desktop/Installed app), then:\n"
            f"`zumba calendar auth --client-id <id>` or paste it when asked."
        )
    redir = (redirect_uri or redirect_default()).strip()
    st = (state or hashlib.sha256(os.urandom(16)).hexdigest()[:16])
    qs = _url.urlencode({
        "client_id": cid,
        "redirect_uri": redir,
        "response_type": "code",
        "scope": CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": st,
    })
    url = f"{AUTH_URL}?{qs}"
    return (
        "Google Calendar connect (one global token):\n"
        f"1. Open: {url}\n"
        f"2. Approve, copy the code, then finish with:\n"
        f"   `zumba calendar auth --code <code>`  (CLI)\n"
        f"   /cal auth <code>  (chat/Telegram)\n"
        f"   or paste the code in the web Connect dialog.\n"
        f"(redirect: {redir} — must match your OAuth client; state={st})"
    )


def auth_finish(code: str, redirect_uri: str = "", client_id: str = "", client_secret: str = "") -> str:
    if not enabled():
        return "ERROR: calendar tools are disabled (ZUMBA_NO_CALENDAR=1)."
    code = (code or "").strip()
    if not code:
        return "ERROR: 'code' is required (paste the code Google showed after Approve)."
    if _requests is None:
        return "ERROR: requests is not installed."
    tok = load_token()
    cid = (client_id or tok.get("client_id") or os.getenv("ZUMBA_CALENDAR_CLIENT_ID") or "").strip()
    sec = (client_secret or tok.get("client_secret") or os.getenv("ZUMBA_CALENDAR_CLIENT_SECRET") or "").strip()
    if not cid or not sec:
        return "ERROR: need client_id + client_secret to exchange the code (paste them when asked)."
    redir = (redirect_uri or redirect_default()).strip()
    try:
        r = _requests.post(TOKEN_URL, data={
            "code": code, "client_id": cid, "client_secret": sec,
            "redirect_uri": redir, "grant_type": "authorization_code",
        }, timeout=_TIMEOUT)
        if r.status_code != 200:
            return f"ERROR: token exchange http {r.status_code} ({str(r.text)[:200]}). Check code + redirect match."
        d = r.json() if isinstance(r.json(), dict) else {}
        access = str(d.get("access_token") or "").strip()
        if not access:
            return f"ERROR: no access_token in response ({str(d)[:200]})."
        save_token({
            "access_token": access,
            "refresh_token": str(d.get("refresh_token") or tok.get("refresh_token") or ""),
            "client_id": cid, "client_secret": sec,
            "expiry": time.time() + float(d.get("expires_in") or 3600),
        })
        return f"Calendar connected (token {_redact(access)}). Try `zumba calendar today`."
    except Exception as e:
        return f"ERROR: token exchange failed ({str(e)[:150]})."


def set_token(access_token: str, refresh_token: str = "", client_id: str = "", client_secret: str = "") -> str:
    if not enabled():
        return "ERROR: calendar tools are disabled (ZUMBA_NO_CALENDAR=1)."
    access_token = (access_token or "").strip()
    if not access_token:
        return "ERROR: 'access_token' is required (paste your OAuth access token)."
    patch: dict = {"access_token": access_token}
    if (refresh_token or "").strip():
        patch["refresh_token"] = refresh_token.strip()
    if (client_id or "").strip():
        patch["client_id"] = client_id.strip()
    if (client_secret or "").strip():
        patch["client_secret"] = client_secret.strip()
    save_token(patch)
    return f"Calendar token saved ({_redact(access_token)}). Try `zumba calendar today`."


# ---- HTTP layer ----

def _auth_header() -> dict | None:
    tok = load_token().get("access_token", "")
    if not str(tok or "").strip():
        return None
    return {"Authorization": f"Bearer {str(tok).strip()}"}


def _refresh_access_token() -> bool:
    tok = load_token()
    cid = str(tok.get("client_id") or "").strip()
    sec = str(tok.get("client_secret") or "").strip()
    ref = str(tok.get("refresh_token") or "").strip()
    if not (cid and sec and ref) or _requests is None:
        return False
    try:
        r = _requests.post(TOKEN_URL, data={
            "client_id": cid, "client_secret": sec,
            "refresh_token": ref, "grant_type": "refresh_token",
        }, timeout=_TIMEOUT)
        if r.status_code != 200:
            return False
        d = r.json() if isinstance(r.json(), dict) else {}
        access = str(d.get("access_token") or "").strip()
        if not access:
            return False
        save_token({"access_token": access, "expiry": time.time() + float(d.get("expires_in") or 3600)})
        return True
    except Exception:
        return False


def _api_get(path: str, params: dict | None = None):
    if _requests is None:
        raise RuntimeError("requests is not installed")
    h = _auth_header()
    if not h:
        return None, not_connected_msg()
    url = API_BASE + path
    try:
        r = _requests.get(url, headers=h, params=params or {}, timeout=_TIMEOUT)
        if r.status_code == 401 and _refresh_access_token():
            h2 = _auth_header() or {}
            r = _requests.get(url, headers=h2, params=params or {}, timeout=_TIMEOUT)
        if r.status_code == 401:
            return None, "Calendar token expired/revoked — reconnect with `zumba calendar auth`."
        if r.status_code != 200:
            return None, f"ERROR: calendar http {r.status_code} ({str(r.text)[:200]})."
        return r.json(), ""
    except Exception as e:
        return None, f"ERROR: calendar request failed ({str(e)[:150]})."


def _api_post(path: str, body: dict):
    if _requests is None:
        raise RuntimeError("requests is not installed")
    h = dict(_auth_header() or {})
    if not h:
        return None, not_connected_msg()
    h["Content-Type"] = "application/json"
    try:
        r = _requests.post(API_BASE + path, headers=h, json=body or {}, timeout=_TIMEOUT)
        if r.status_code == 401 and _refresh_access_token():
            h2 = dict(_auth_header() or {})
            h2["Content-Type"] = "application/json"
            r = _requests.post(API_BASE + path, headers=h2, json=body or {}, timeout=_TIMEOUT)
        if r.status_code == 401:
            return None, "Calendar token expired/revoked — reconnect with `zumba calendar auth`."
        if r.status_code not in (200, 201):
            return None, f"ERROR: calendar http {r.status_code} ({str(r.text)[:200]})."
        return r.json(), ""
    except Exception as e:
        return None, f"ERROR: calendar create failed ({str(e)[:150]})."


# ---- parsing (pure, unit-testable) ----

def _parse_time(v) -> str:
    if not v:
        return ""
    if isinstance(v, dict):
        return str(v.get("dateTime") or v.get("date") or "")
    return str(v)


def parse_events(data: dict) -> list[dict]:
    try:
        items = (data or {}).get("items") or []
    except Exception:
        return []
    out = []
    for it in items:
        try:
            out.append({
                "id": str(it.get("id") or ""),
                "summary": str(it.get("summary") or "(no title)")[:160],
                "start": _parse_time(it.get("start")),
                "end": _parse_time(it.get("end")),
                "location": str(it.get("location") or "")[:200],
                "description": str(it.get("description") or "")[:500],
                "link": str(it.get("htmlLink") or ""),
                "attendees": [str(a.get("email") or a.get("displayName") or "")[:80]
                              for a in (it.get("attendees") or [])][:5],
            })
        except Exception:
            continue
    return out


def _short_time(iso: str) -> str:
    s = (iso or "").strip()
    if not s:
        return "??:??"
    try:
        # 2026-09-12T09:30:00+05:30 -> 09:30 ; 2026-09-13 (all-day) stays date
        if "T" in s:
            return s.split("T", 1)[1][:5]
        return s[:10]
    except Exception:
        return s[:16]


def format_events(events: list[dict], title: str = "Today") -> str:
    if not events:
        return f"{title}: (no events — enjoy the open day)"
    lines = [f"{title} ({len(events)}):"]
    for e in events:
        span = f"{_short_time(e.get('start',''))}–{_short_time(e.get('end',''))}"
        loc = f" @ {e['location'][:80]}" if e.get("location") else ""
        lines.append(f"- {span} {e.get('summary','(no title)')}{loc}")
        if e.get("link"):
            lines.append(f"  {e['link']}")
    return "\n".join(lines)


def _day_bounds_utc() -> tuple[str, str]:
    now = _dt.datetime.now(_dt.timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + _dt.timedelta(days=1)
    return start.isoformat(), end.isoformat()


# ---- public API (plain-text returns for builtin.py) ----

def today(limit: int = 10, calendar_id: str = "") -> str:
    if not enabled():
        return "ERROR: calendar tools are disabled (ZUMBA_NO_CALENDAR=1)."
    if not is_connected():
        return not_connected_msg()
    try:
        lim = max(1, min(50, int(limit or 10)))
    except Exception:
        return "ERROR: 'limit' must be a number."
    cid = (calendar_id or calendar_id_default()).strip()
    tmin, tmax = _day_bounds_utc()
    ck = _ck("today", cid=cid, lim=lim, day=tmin[:10])
    hit = _cget(ck, 60.0)
    if hit:
        return hit + "\n(cached)"
    data, err = _api_get(f"/calendars/{_url.quote(cid, safe='')}/events", {
        "timeMin": tmin, "timeMax": tmax, "singleEvents": "true",
        "orderBy": "startTime", "maxResults": lim,
    })
    if data is None:
        return err
    out = _truncate(format_events(parse_events(data), "Today"))
    _cput(ck, out)
    return out


def search(query: str, max_results: int = 10, calendar_id: str = "") -> str:
    if not enabled():
        return "ERROR: calendar tools are disabled (ZUMBA_NO_CALENDAR=1)."
    if not is_connected():
        return not_connected_msg()
    q = (query or "").strip()
    if not q:
        return "ERROR: 'query' is required."
    try:
        lim = max(1, min(50, int(max_results or 10)))
    except Exception:
        return "ERROR: 'max_results' must be a number."
    cid = (calendar_id or calendar_id_default()).strip()
    ck = _ck("search", q=q.lower(), lim=lim, cid=cid)
    hit = _cget(ck, 60.0)
    if hit:
        return hit + "\n(cached)"
    data, err = _api_get(f"/calendars/{_url.quote(cid, safe='')}/events", {
        "q": q, "singleEvents": "true", "orderBy": "startTime", "maxResults": lim,
    })
    if data is None:
        return err
    out = _truncate(format_events(parse_events(data), f"Matches for '{q[:60]}'"))
    _cput(ck, out)
    return out


def create(summary: str, start: str, end: str = "", location: str = "",
           description: str = "", calendar_id: str = "") -> str:
    if not enabled():
        return "ERROR: calendar tools are disabled (ZUMBA_NO_CALENDAR=1)."
    if not is_connected():
        return not_connected_msg()
    title = (summary or "").strip()
    s = (start or "").strip()
    if not title or not s:
        return "ERROR: 'summary' and 'start' (ISO, e.g. 2026-09-13T09:30:00) are required."
    e = (end or "").strip()
    if not e:
        try:
            base = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            e = (base + _dt.timedelta(hours=1)).isoformat()
        except Exception:
            return "ERROR: 'start' must be ISO datetime (e.g. 2026-09-13T09:30:00)."
    cid = (calendar_id or calendar_id_default()).strip()
    body: dict = {"summary": title, "start": {"dateTime": s}, "end": {"dateTime": e}}
    if (location or "").strip():
        body["location"] = location.strip()[:200]
    if (description or "").strip():
        body["description"] = description.strip()[:2000]
    data, err = _api_post(f"/calendars/{_url.quote(cid, safe='')}/events", body)
    if data is None:
        return err
    link = str((data or {}).get("htmlLink") or "")
    return f"Created: {title} {_short_time(s)}–{_short_time(e)}" + (f"\n{link}" if link else "")


def _travel_hint(location: str) -> str:
    loc = (location or "").strip()
    if not loc:
        return ""
    try:
        from tools import geo as _geo
        if not _geo.enabled():
            return ""
        return "\n  travel: " + _geo.maps_link(loc).splitlines()[0][:200]
    except Exception:
        return ""


def brief(calendar_id: str = "", limit: int = 10) -> str:
    """Meetings + travel + prep links. Read-only, never hallucinates."""
    if not enabled():
        return "ERROR: calendar tools are disabled (ZUMBA_NO_CALENDAR=1)."
    if not is_connected():
        return not_connected_msg()
    try:
        lim = max(1, min(30, int(limit or 10)))
    except Exception:
        return "ERROR: 'limit' must be a number."
    cid = (calendar_id or calendar_id_default()).strip()
    tmin, tmax = _day_bounds_utc()
    data, err = _api_get(f"/calendars/{_url.quote(cid, safe='')}/events", {
        "timeMin": tmin, "timeMax": tmax, "singleEvents": "true",
        "orderBy": "startTime", "maxResults": lim,
    })
    if data is None:
        return err
    events = parse_events(data)
    if not events:
        return "Calendar brief: (no meetings today — open day for deep work)"
    lines = [f"Calendar brief ({len(events)} today):"]
    for i, e in enumerate(events, 1):
        span = f"{_short_time(e.get('start',''))}–{_short_time(e.get('end',''))}"
        lines.append(f"{i}. {span} {e.get('summary','(no title)')}")
        if e.get("location"):
            lines.append(f"   where: {e['location'][:120]}")
            th = _travel_hint(e["location"])
            if th:
                lines.append(f"  {th.strip()}")
            else:
                lines.append("   travel: leave ~30m buffer (share live location for live ETA)")
        if e.get("attendees"):
            lines.append(f"   with: {', '.join(e['attendees'][:4])}")
        if e.get("link"):
            lines.append(f"   prep: {e['link']}")
        if i < len(events):
            try:
                a = _dt.datetime.fromisoformat(str(e.get('end')).replace("Z", "+00:00"))
                b = _dt.datetime.fromisoformat(str(events[i].get('start')).replace("Z", "+00:00"))
                gap = (b - a).total_seconds() / 60.0
                if 0 < gap < 120:
                    lines.append(f"   gap: {gap:.0f}m to next — prep/buffer time")
            except Exception:
                pass
    return _truncate("\n".join(lines))
