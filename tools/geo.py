"""Tiny standalone geo tools (PLAN-GO). Conventions match websearch.py:
ERROR: prefix on failure, never raise into chat, ZUMBA_NO_GEO kill-switch,
in-process cache with TTL, head+tail truncation, timeout <= 10s."""
from __future__ import annotations
import hashlib, json, math, os, time, urllib.parse as _url

try:
    import requests as _requests
except Exception:
    _requests = None

def enabled() -> bool:
    return os.getenv("ZUMBA_NO_GEO", "") != "1"

_TIMEOUT = 10.0
_CACHE: dict[str, tuple[float, str]] = {}
_TOKENS: dict[str, float] = {}  # backend -> last request ts (Nominatim 1 req/s)

def _cache_ttl(kind: str) -> float:
    if kind in ("geocode", "reverse"): return 86400.0
    return 60.0

def _ck(kind: str, **p) -> str:
    blob = kind + "|" + "|".join(f"{k}={p.get(k,'')}" for k in sorted(p))
    return hashlib.sha256(blob.encode()).hexdigest()[:24]

def _cget(k: str, ttl: float):
    e = _CACHE.get(k)
    if e and (time.time() - e[0]) < ttl: return e[1]
    return None

def _cput(k: str, v: str): _CACHE[k] = (time.time(), v)

def _throttle(key: str, min_interval: float):
    now = time.time()
    last = _TOKENS.get(key, 0)
    wait = min_interval - (now - last)
    if wait > 0: time.sleep(wait)
    _TOKENS[key] = time.time()

def _http_get(url: str, params: dict = None, headers: dict = None):
    if _requests is None: raise RuntimeError("requests is not installed")
    return _requests.get(url, params=params or {}, headers=headers or {"User-Agent": "zumba/1.0"},
                         timeout=_TIMEOUT)

def _truncate(t: str, cap: int = 4000) -> str:
    if len(t) <= cap: return t
    h, tl = cap * 4 // 5, cap - cap * 4 // 5
    return t[:h] + f"\n[...truncated {len(t)-cap} chars...]\n" + t[-tl:]

# ---- parsing helpers (pure, unit-testable) ----
def parse_geocode(data: list) -> str:
    if not data: return "ERROR: no candidates found."
    lines = []
    for c in data[:3]:
        try: lines.append(f"- {c.get('display_name','?')[:160]} :: lat={c.get('lat')} lon={c.get('lon')} type={c.get('type','')}/{c.get('class','')}")
        except Exception: continue
    return "Candidates (top 3):\n" + "\n".join(lines)

def parse_route(data: dict) -> str:
    try:
        r = (data.get("routes") or [None])[0]
        if not r: return "ERROR: no route found."
        km = float(r.get("distance", 0)) / 1000.0
        mins = float(r.get("duration", 0)) / 60.0
        legs = r.get("legs") or []
        steps = []
        for leg in legs:
            for s in (leg.get("steps") or [])[:8]:
                nm = ((s.get("name") or "") + " " + str(s.get("maneuver", {}).get("instruction", "") or "")).strip()
                if nm: steps.append(f"- {nm[:120]} ({float(s.get('distance',0))/1000:.1f} km)")
        out = f"Route: {km:.1f} km, ~{mins:.0f} min\n" + ("\n".join(steps) if steps else "(no step detail)")
        return out
    except Exception as e: return f"ERROR: bad route response ({e})."

def parse_overpass(data: dict, lat: float, lon: float, limit: int = 10) -> str:
    try: els = data.get("elements") or []
    except Exception: return "ERROR: bad nearby response."
    if not els: return "ERROR: nothing found nearby."
    rows = []
    for el in els[:limit]:
        tags = el.get("tags") or {}
        name = tags.get("name", "(unnamed)")[:80]
        la, lo = el.get("lat", 0), el.get("lon", 0)
        if not la and el.get("center"): la, lo = el["center"].get("lat", 0), el["center"].get("lon", 0)
        d = _haversine_km(lat, lon, la or lat, lo or lon)
        rows.append(f"- {name} :: {d:.2f} km {_bearing(lat, lon, la or lat, lo or lon)}")
    return "Nearby:\n" + "\n".join(rows)

def _haversine_km(a, b, c, d) -> float:
    R = 6371.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(h))

def _bearing(a, b, c, d) -> str:
    try:
        y = math.sin(math.radians(d-b)) * math.cos(math.radians(c))
        x = math.cos(math.radians(a))*math.sin(math.radians(c)) - math.sin(math.radians(a))*math.cos(math.radians(c))*math.cos(math.radians(d-b))
        deg = (math.degrees(math.atan2(y, x)) + 360) % 360
        return ["N","NE","E","SE","S","SW","W","NW"][int((deg+22.5)//45) % 8]
    except Exception: return ""

def _wmo(code: int) -> str:
    m = {0:"clear",1:"mostly clear",2:"partly cloudy",3:"overcast",45:"fog",48:"fog",51:"drizzle",61:"rain",63:"rain",65:"heavy rain",71:"snow",80:"showers",95:"thunderstorm"}
    if code in m: return m[code]
    if code == 2: return "partly cloudy"
    return "cloudy" if code < 50 else "rain"

# ---- public API (called via builtin.py, plain-text returns) ----
def _tt_key() -> str:
    return (os.getenv("ZUMBA_TT_KEY") or "").strip()

def _tt_geocode_first(q: str):
    """TomTom Search API first (fuzzy, global). Returns list of (lat,lon,label) or []."""
    key = _tt_key()
    if not key: return []
    try:
        r = _http_get(f"https://api.tomtom.com/search/2/search/{_url.quote(q)}.json",
                      {"key": key, "limit": 3, "language": "en-US"})
        if r.status_code != 200: return []
        out = []
        for res in (r.json().get("results") or [])[:3]:
            pos = res.get("position", {})
            addr = res.get("address", {})
            out.append((float(pos.get("lat", 0)), float(pos.get("lon", 0)),
                        str(addr.get("freeformAddress", res.get("poi", {}).get("name", q)))[:160]))
        return [o for o in out if o[0] or o[1]]
    except Exception: return []

def _tt_reverse_first(lat: float, lon: float) -> str:
    key = _tt_key()
    if not key: return ""
    try:
        r = _http_get(f"https://api.tomtom.com/search/2/reverseGeocode/{lat},{lon}.json",
                      {"key": key, "language": "en-US"})
        if r.status_code != 200: return ""
        addrs = (r.json().get("addresses") or [])
        if addrs: return str(addrs[0].get("address", {}).get("freeformAddress", ""))[:400]
    except Exception: pass
    return ""

def geocode(place: str) -> str:
    if not enabled(): return "ERROR: geo tools are disabled (ZUMBA_NO_GEO=1)."
    q = (place or "").strip()
    if not q: return "ERROR: 'place' is required."
    k = _ck("geocode", q=q.lower())
    hit = _cget(k, _cache_ttl("geocode"))
    if hit: return hit + "\n(cached)"
    tt = _tt_geocode_first(q)  # TomTom Search API first when key set
    if tt:
        out = "Candidates (top 3, TomTom):\n" + "\n".join(f"- {lbl[:160]} :: lat={la} lon={lo}" for la, lo, lbl in tt)
        _cput(k, out)
        return _truncate(out)
    try:
        _throttle("nominatim", 1.1)
        r = _http_get("https://nominatim.openstreetmap.org/search", {"q": q, "format": "jsonv2", "limit": 3, "addressdetails": 1})
        if r.status_code != 200: return f"ERROR: geocode http {r.status_code}."
        out = _truncate(parse_geocode(r.json() if isinstance(r.json(), list) else []))
        _cput(k, out)
        return out
    except Exception as e: return f"ERROR: geocode failed ({str(e)[:150]})."

def reverse(lat: float, lon: float) -> str:
    if not enabled(): return "ERROR: geo tools are disabled (ZUMBA_NO_GEO=1)."
    try:
        k = _ck("reverse", lat=round(float(lat),4), lon=round(float(lon),4))
        hit = _cget(k, _cache_ttl("reverse"))
        if hit: return hit + "\n(cached)"
        tt = _tt_reverse_first(float(lat), float(lon))  # TomTom Reverse Geocode first
        if tt:
            _cput(k, tt)
            return tt
        _throttle("nominatim", 1.1)
        r = _http_get("https://nominatim.openstreetmap.org/reverse", {"lat": float(lat), "lon": float(lon), "format": "jsonv2"})
        if r.status_code != 200: return f"ERROR: reverse http {r.status_code}."
        d = r.json()
        out = str(d.get("display_name", "(unknown)"))[:400]
        _cput(k, out)
        return out
    except Exception as e: return f"ERROR: reverse failed ({str(e)[:150]})."

def _coords(s: str):
    """Accept 'lat,lon' or place name (TomTom Search first, Nominatim fallback). Returns (lat,lon,label) or None."""
    s = (s or "").strip()
    if not s: return None
    import re
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", s)
    if m: return float(m.group(1)), float(m.group(2)), s
    tt = _tt_geocode_first(s)
    if tt: return tt[0]
    try:
        _throttle("nominatim", 1.1)
        r = _http_get("https://nominatim.openstreetmap.org/search", {"q": s, "format": "jsonv2", "limit": 1})
        d = r.json()
        if d: return float(d[0]["lat"]), float(d[0]["lon"]), str(d[0].get("display_name",""))[:120]
    except Exception: pass
    return None

def route(origin: str, destination: str, mode: str = "drive") -> str:
    if not enabled(): return "ERROR: geo tools are disabled (ZUMBA_NO_GEO=1)."
    if not (origin or "").strip() or not (destination or "").strip(): return "ERROR: 'origin' and 'destination' are required."
    o, d = _coords(origin), _coords(destination)
    if not o: return f"ERROR: could not geocode origin '{origin[:80]}'."
    if not d: return f"ERROR: could not geocode destination '{destination[:80]}'."
    prof = {"drive": "driving", "walk": "foot", "bike": "bike"}.get((mode or "drive").lower(), "driving")
    base = (os.getenv("ZUMBA_OSRM_URL") or "https://router.project-osrm.org").rstrip("/")
    k = _ck("route", o=f"{o[0]:.4f},{o[1]:.4f}", d=f"{d[0]:.4f},{d[1]:.4f}", m=prof)
    hit = _cget(k, 60.0)
    if hit: return hit + "\n(cached)"
    try:
        r = _http_get(f"{base}/route/v1/{prof}/{o[1]},{o[0]};{d[1]},{d[0]}",
                      {"overview": "false", "steps": "true"})
        if r.status_code != 200: return "ERROR: routing backend down (can't estimate — here's a maps link instead: " + maps_link(destination) + ")."
        out = _truncate(f"From: {o[2]}\nTo: {d[2]}\n" + parse_route(r.json()))
        _cput(k, out)
        return out
    except Exception: return "ERROR: routing backend down (can't estimate)."

def _tt_incidents(lat: float, lon: float) -> str:
    """TomTom Traffic Incidents near a point (bbox ~20km). Returns '' on failure."""
    key = _tt_key()
    if not key: return ""
    try:
        bbox = f"{lon-0.15},{lat-0.15},{lon+0.15},{lat+0.15}"
        r = _http_get("https://api.tomtom.com/traffic/services/4/incidentDetails",
                      {"key": key, "bbox": bbox, "fields": "{incidents{type,geometry{type,coordinates},properties{iconCategory,delay,magnitudeOfDelay,events{description},from,to}}]}",
                       "language": "en-US", "categoryFilter": "0,1,2,3,4,5,6,7,8,9,10,11,14"})
        if r.status_code != 200: return ""
        incs = ((r.json().get("incidents") or []) if isinstance(r.json(), dict) else [])
        if not incs: return "No reported incidents nearby."
        lines = []
        for i in incs[:5]:
            p = i.get("properties", {})
            evs = p.get("events") or [{}]
            desc = str(evs[0].get("description", i.get("type", "incident")))[:120]
            delay = p.get("delay", 0)
            lines.append(f"- {desc} (+{float(delay or 0)/60:.0f} min)" if delay else f"- {desc}")
        return "Incidents nearby:\n" + "\n".join(lines)
    except Exception: return ""

def _tt_flow(lat: float, lon: float) -> str:
    """TomTom Traffic Flow at a point. Returns '' on failure."""
    key = _tt_key()
    if not key: return ""
    try:
        r = _http_get("https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json",
                      {"key": key, "point": f"{lat},{lon}"})
        if r.status_code != 200: return ""
        fsd = (r.json().get("flowSegmentData") or {})
        cur, free = float(fsd.get("currentSpeed", 0)), float(fsd.get("freeFlowSpeed", 0))
        if not cur: return ""
        pct = cur / free if free else 1.0
        state = "flowing freely" if pct > 0.85 else ("slow" if pct > 0.6 else "congested")
        return f"Flow here: {cur:.0f} km/h vs free-flow {free:.0f} km/h ({state})."
    except Exception: return ""

def traffic(origin: str, destination: str) -> str:
    if not enabled(): return "ERROR: geo tools are disabled (ZUMBA_NO_GEO=1)."
    key = _tt_key()
    if not key: return "No live traffic key configured (ZUMBA_TT_KEY) — no live traffic data."
    o, d = _coords(origin), _coords(destination)
    if not o or not d: return "ERROR: could not geocode origin/destination."
    try:
        r = _http_get("https://api.tomtom.com/routing/1/calculateRoute/"
                      f"{o[0]},{o[1]}:{d[0]},{d[1]}/json",
                      {"key": key, "traffic": "true", "travelMode": "car"})
        if r.status_code != 200: return f"ERROR: traffic http {r.status_code}."
        s = (r.json().get("routes") or [{}])[0].get("summary", {})
        tt, ntt = float(s.get("travelTimeInSeconds", 0)), float(s.get("noTrafficTravelTimeInSeconds", 0))
        delta = (tt - ntt) / 60.0
        sev = "light" if delta < 5 else ("moderate" if delta < 15 else "heavy")
        out = f"Traffic (TomTom live): +{delta:.0f} min vs free-flow ({sev}). Total ~{tt/60:.0f} min."
        mid = _tt_incidents((o[0] + d[0]) / 2, (o[1] + d[1]) / 2)
        if mid: out += "\n" + mid
        return _truncate(out)
    except Exception as e: return f"ERROR: traffic failed ({str(e)[:150]})."

def nearby(lat: float, lon: float, category: str, limit: int = 8) -> str:
    """category is free text (e.g. 'cafes'); mapped to OSM tags by the CALLING MODEL
    via `tag` param convention: pass 'cafes' and we try amenity=cafe etc. No hardcoded table —
    we send a regex tag filter covering name/amenity/shop values."""
    if not enabled(): return "ERROR: geo tools are disabled (ZUMBA_NO_GEO=1)."
    cat = (category or "").strip()
    if not cat: return "ERROR: 'category' free text is required."
    try: lat, lon = float(lat), float(lon)
    except Exception: return "ERROR: 'lat'/'lon' must be numbers."
    key = _tt_key()
    if key:  # TomTom Places (Category + fuzzy Search) first — no hardcoded category table
        try:
            esc = cat.replace('"', '').replace("'", "")[:60]
            r = _http_get(f"https://api.tomtom.com/search/2/categorySearch/{_url.quote(esc)}.json",
                          {"key": key, "lat": lat, "lon": lon, "radius": 5000, "limit": int(limit or 8), "language": "en-US"})
            if r.status_code == 200:
                res = (r.json().get("results") or [])
                if res:
                    rows = []
                    for x in res[:int(limit or 8)]:
                        pos, poi = x.get("position", {}), x.get("poi", {})
                        nm = str(poi.get("name", x.get("address", {}).get("freeformAddress", "(unnamed)")))[:80]
                        la, lo = float(pos.get("lat", lat)), float(pos.get("lon", lon))
                        cat0 = ",".join((poi.get("categories") or [""])[:1])[:40].encode("ascii", "ignore").decode()
                        rows.append(f"- {nm} :: {_haversine_km(lat, lon, la, lo):.2f} km {_bearing(lat, lon, la, lo)} [{cat0}]")
                    return "Nearby (TomTom Places):\n" + "\n".join(rows)
            # fall through to Overpass on empty/failure
        except Exception: pass
    base = (os.getenv("ZUMBA_OVERPASS_URL") or "https://overpass-api.de/api/interpreter").strip()
    # Generic regex match against name/amenity/shop/leisure keys — no hardcoded category table.
    esc = cat.replace('"', '').replace("'", "")[:60]
    ql = (f'[out:json][timeout:25];(node["name"~"{esc}",i](around:3000,{lat},{lon});'
          f'node[~"^(amenity|shop|leisure|tourism)$"~"{esc}",i](around:3000,{lat},{lon});'
          f');out center {int(limit or 8)};')
    k = _ck("nearby", lat=round(lat,3), lon=round(lon,3), cat=esc.lower(), lim=limit)
    hit = _cget(k, 60.0)
    if hit: return hit + "\n(cached)"
    try:
        if _requests is None: raise RuntimeError("requests is not installed")
        r = _requests.post(base, data={"data": ql}, timeout=_TIMEOUT,
                           headers={"User-Agent": "zumba/1.0"})
        if r.status_code != 200: return f"ERROR: nearby http {r.status_code}."
        out = _truncate(parse_overpass(r.json(), lat, lon, int(limit or 8)))
        _cput(k, out)
        return out
    except Exception as e: return f"ERROR: nearby failed ({str(e)[:150]})."

def weather(lat: float, lon: float, eta_hours: float = 0.0) -> str:
    if not enabled(): return "ERROR: geo tools are disabled (ZUMBA_NO_GEO=1)."
    try: lat, lon = float(lat), float(lon)
    except Exception: return "ERROR: 'lat'/'lon' must be numbers."
    k = _ck("weather", lat=round(lat,2), lon=round(lon,2))
    hit = _cget(k, 60.0)
    if hit and not eta_hours: return hit + "\n(cached)"
    try:
        r = _http_get("https://api.open-meteo.com/v1/forecast",
                      {"latitude": lat, "longitude": lon, "current": "temperature_2m,precipitation,weather_code",
                       "hourly": "temperature_2m,precipitation_probability,weather_code", "timezone": "auto"})
        if r.status_code != 200: return f"ERROR: weather http {r.status_code}."
        d = r.json()
        cur = d.get("current") or {}
        base_line = f"Now: {cur.get('temperature_2m','?')}°C, precip {cur.get('precipitation','?')}mm, {_wmo(int(cur.get('weather_code',2) or 2))}."
        try:
            h = float(eta_hours or 0)
            if h > 0:
                times = (d.get("hourly") or {}).get("time") or []
                import datetime as _dt
                target = _dt.datetime.now(_dt.timezone.utc).timestamp() + h * 3600
                best, bi = None, 0
                for i, t in enumerate(times[:48]):
                    try: ts = _dt.datetime.fromisoformat(str(t).replace("Z","+00:00")).timestamp()
                    except Exception: continue
                    if best is None or abs(ts-target) < abs(best-target): best, bi = ts, i
                hr = d.get("hourly") or {}
                if best is not None:
                    return base_line + f" At arrival (~+{h:.0f}h): {hr.get('temperature_2m',[None])[bi]}°C, rain prob {hr.get('precipitation_probability',[None])[bi]}%, {_wmo(int(hr.get('weather_code',[2])[bi] or 2))}."
        except Exception: pass
        _cput(k, base_line)
        return base_line
    except Exception as e: return f"ERROR: weather failed ({str(e)[:150]})."

def maps_link(place_or_coords: str) -> str:
    q = (place_or_coords or "").strip()
    if not q: return "ERROR: 'place_or_coords' is required."
    g = "https://www.google.com/maps/search/?api=1&query=" + _url.quote(q)
    o = "https://www.openstreetmap.org/search?query=" + _url.quote(q)
    return f"Maps: {g}\nOSM: {o}"

# ---- motion layer (SQLite-backed) ----
def track_start_fn(chat_id: str, minutes: float = 15.0) -> str:
    from server import geo_store as _gs
    until = _gs.track_start(chat_id or "default", minutes or 15)
    import datetime as _dt
    return f"Tracking for {minutes:.0f} min (until {_dt.datetime.fromtimestamp(until).strftime('%H:%M')}). Share live location in Telegram."

def track_stop_fn(chat_id: str) -> str:
    from server import geo_store as _gs
    _gs.track_stop(chat_id or "default")
    return "Tracking stopped."

def whereami(chat_id: str) -> str:
    from server import geo_store as _gs
    p = _gs.last_ping(chat_id or "default")
    if not p: return "ERROR: no location shared yet — send a Telegram location first."
    import datetime as _dt
    age = (time.time() - float(p["ts"])) / 60.0
    addr = reverse(float(p["lat"]), float(p["lon"]))
    return f"Last known: {p['lat']:.5f},{p['lon']:.5f} ({age:.0f} min ago, {p.get('source','')})\n{addr}"

def visit_log(chat_id: str, action: str = "list", place_name: str = "", lat: float = 0.0,
              lon: float = 0.0, note: str = "", since: str = "", forget: bool = False) -> str:
    from server import geo_store as _gs
    cid = chat_id or "default"
    if forget or (action or "").lower() == "forget":
        n = _gs.purge(cid)
        return f"Forgot {n} geo record(s)."
    if (action or "").lower() == "add":
        if not (place_name or "").strip(): return "ERROR: 'place_name' is required for add."
        _gs.log_visit(cid, place_name.strip(), float(lat or 0), float(lon or 0), note=note or "")
        try:
            from memory import get_memory as _gm
            _gm().capture_async(f"Visited {place_name.strip()}" + (f" ({note})" if note else ""), "", "tool", "geo_visit")
        except Exception: pass
        return f"Logged visit: {place_name.strip()}."
    since_ts = 0.0
    if (since or "").strip():
        try:
            import datetime as _dt
            since_ts = _dt.datetime.fromisoformat(str(since).strip()).timestamp()
        except Exception: since_ts = 0.0
    rows = _gs.query_visits(cid, since_ts)
    if not rows: return "(no visits logged)"
    import datetime as _dt
    return "\n".join(f"- {r['place_name']} @ {_dt.datetime.fromtimestamp(float(r['arrived_at'])).strftime('%m-%d %H:%M')}" + (f" — {r['note']}" if r.get("note") else "") for r in rows[:20])
