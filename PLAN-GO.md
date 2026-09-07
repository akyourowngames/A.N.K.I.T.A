# PLAN-GO — "Heading to X" Trip Brain (built from small, individually-usable geo tools)

## Core principle (read this first)

**The trip planner is NOT a tool — it's a behavior.** Every capability lives in
`tools/geo.py` as a tiny standalone function, each exposed to the model as its
own builtin tool (same pattern as `web_search` / `web_news` / `web_fetch`).
The model can compose them freely:

- "how far is X from Y" → `geo_route` alone
- "is it raining in Delhi" → `geo_weather` alone
- "good cafes near Connaught Place" → `geo_geocode` + `geo_nearby` alone
- "I'm heading to X" → model chains geocode → route → weather → nearby → memory itself

No hardcoded "trip intent" classifier (AGENTS.md no-hardcoding rule). The
"heading to" moment is just the LLM choosing to call several small tools in
sequence — which it already knows how to do.

## 1. The tools (all in `tools/geo.py`, ~600 lines total)

Each returns a compact text/JSON blob for the model. Conventions match
`websearch.py`: `ERROR:` prefix on failure, never raise into chat,
`ZUMBA_NO_GEO=1` kill-switch, in-process cache with TTL, head+tail truncation.

| Tool | Function | Backend | Keyless? |
|---|---|---|---|
| `geo_geocode` | fuzzy place → `{lat, lon, display_name, type}` (top 3 candidates so the model can disambiguate) | Nominatim (1 req/s, cached aggressively) | ✅ |
| `geo_reverse` | lat/lon → human-readable address | Nominatim reverse | ✅ |
| `geo_route` | origin→destination → distance, duration, steps summary; `mode=drive\|walk\|bike` | OSRM public demo; self-host via `ZUMBA_OSRM_URL` | ✅ |
| `geo_traffic` | origin+destination → live traffic delta (+X min, severity) | TomTom free tier (2,500/day) if `ZUMBA_TT_KEY`; else honest "no live traffic" | optional key |
| `geo_nearby` | lat/lon + **free-text category** → POI list (name, distance, bearing) | Overpass API; category text → OSM tags via LLM, no hardcoded category table | ✅ |
| `geo_weather` | lat/lon (+ optional eta_hours) → temp, rain, condition at arrival time | Open-Meteo | ✅ |
| `geo_maps_link` | place or lat/lon → one-tap Google/OSM deep link | pure string ops | ✅ |
| `geo_track_start/stop` | watch the user's live location for N minutes → current position on demand | SQLite `geo_pings` | ✅ |
| `geo_whereami` | last known location or error if never shared | SQLite | ✅ |
| `geo_visit_log` | record/query place visits → "where was I Saturday 6pm" | SQLite + memory graph | ✅ |

**Storage** — one SQLite store (new `server/geo_store.py`, channel_store style):

```sql
CREATE TABLE IF NOT EXISTS geo_pings (
    chat_id TEXT, lat REAL, lon REAL, accuracy REAL,
    source TEXT,          -- 'live' | 'point' | 'checkin'
    ts REAL NOT NULL,
    PRIMARY KEY (chat_id, ts)
);
CREATE TABLE IF NOT EXISTS geo_visits (
    chat_id TEXT, place_name TEXT, lat REAL, lon REAL,
    arrived_at REAL, departed_at REAL, note TEXT,
    PRIMARY KEY (chat_id, arrived_at)
);
```

Place visits are also pushed into the memory graph (distilled as entity +
temporal relation), so "what did I do last Saturday" just works via existing recall.

## 2. Telegram plumbing (small, in `server/telegram_channel.py`)

- `handle_update`: if `msg.location` exists → `geo_store.record_ping`, one-line
  ack only for point-shares ("📍 Got it"). No LLM call.
- Accept `edited_message` (Telegram live location re-sends via edits): add to
  `allowed_updates`, store ping, update active `geo_track` window.
- **No new commands, no intent classifier.** The model gets the tools and the
  normal chat pipeline handles "heading to X". The only channel-level logic is
  store-the-ping, because pings arrive with no text to reason about.

## 3. The "heading to" moment (prompt-side, ~15 lines)

Add one paragraph to the system/persona prompt describing the tools and the
composition pattern: when the user says they're heading somewhere, chain
geocode → route from last known location (ask if unknown) → traffic delta →
weather at arrival → 2–3 nearby places → memory/vault context about the
destination. Compose ONE message: leave-by time, route summary, weather line,
personal context, maps link. During an active live share, only interrupt with
material changes (+10 min or arrival). That's the entire "planner" — the
composition intelligence lives in the model, where it belongs and keeps improving.

## 4. Anti-fragility

- Nominatim 1 req/s: per-backend token bucket (reuse `_Bucket` pattern), cache
  geocodes forever (places don't move), routes/weather 60s.
- OSRM demo is best-effort: on failure return `ERROR: routing backend down` and
  the model falls back to a maps link + honest "can't estimate".
- Every backend timeout ≤ 10s; worst-case trip chain ~15s; partial answers beat
  silence (route without weather > nothing).
- Kill-switch: `ZUMBA_NO_GEO=1` removes all geo tools (same filter pattern in
  `mcpclient/builtin.py.available_builtin_tools`).
- Privacy: pings stay in local SQLite; `forget` arg purges history; nothing geo
  leaves the machine except backend coordinate queries.

## 5. Tests (`tests/test_geo.py`, `tests/test_geo_store.py`)

- Unit: maps-link formatting, ping window math, bucket/cache, mock-HTTP parsing
  for geocode/route/nearby (Nominatim/OSRM/Overpass fixture JSON).
- Store: record/query ping + visit lifecycle, purge.
- Offline integration: FakeAPI telegram test — point location → ping stored, no
  reply spam; edited_message live location → window updated.

## 6. Build order (2 PR-sized chunks)

1. **PR-1 — the primitives**: `tools/geo.py` (geocode, reverse, route,
   maps_link, weather, nearby) + geo_store + registration in
   `mcpclient/builtin.py` + tests. **This alone gives Zumba ~6 new standalone
   capabilities.**
2. **PR-2 — the motion layer**: Telegram location/edited_message handling,
   geo_track/whereami/visit_log tools, prompt paragraph for trip composition.
   **This turns it into the heading-to brain.**

## 7. Config (add to `.env.example`)

```
ZUMBA_NO_GEO=0            # 1 disables all geo tools
ZUMBA_OSRM_URL=           # optional self-hosted OSRM
ZUMBA_TT_KEY=             # optional TomTom key (live traffic)
ZUMBA_OVERPASS_URL=       # optional Overpass mirror
ZUMBA_GEO_TRACK_MAX_MIN=90
```

## 8. Definition of done

- "how far is X" / "weather there" / "cafes near Y" each work with ONE tool call.
- Point-share stores silently; live location updates tracked.
- "I'm heading to X" produces the single composed briefing with leave-by time,
  weather, one personal-context line, and a maps link.
- All 10 tools individually listed, individually callable, individually tested.

