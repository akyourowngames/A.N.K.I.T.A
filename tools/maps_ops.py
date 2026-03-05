"""
Maps and navigation operations for A.N.K.I.T.A.
Defaults to free OpenStreetMap services (Nominatim + OSRM).
Google Maps remains optional when explicitly configured.
"""
from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
    from requests import Response
    HAS_REQUESTS = True
except ImportError:  # pragma: no cover
    HAS_REQUESTS = False


def maps_op(
    action: str,
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    query: Optional[str] = None,
    mode: str = "driving",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Maps and navigation operations with OSM-first behavior."""
    provider = _normalize_provider(os.getenv("MAPS_PROVIDER", "osm"))
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")

    if not HAS_REQUESTS:
        return _error(
            provider=provider,
            action=action,
            error_code="MISSING_DEPENDENCY",
            error="requests library not installed. Run: pip install requests",
        )

    try:
        if action == "navigate":
            return _get_route(origin, destination, mode, api_key, provider)
        if action == "search_places":
            return _search_places(query, origin, api_key, provider)
        if action == "distance":
            return _get_distance(origin, destination, mode, api_key, provider)
        if action == "traffic":
            return _get_traffic(origin, destination, api_key, provider)
        if action == "geocode":
            return _geocode(query or origin, api_key, provider)
        if action == "reverse_geocode":
            return _reverse_geocode(origin, api_key, provider)
        return _error(provider=provider, action=action, error_code="UNKNOWN_ACTION", error=f"Unknown action: {action}")
    except requests.Timeout:
        return _error(provider=provider, action=action, error_code="UPSTREAM_TIMEOUT", error="Maps provider timed out")
    except Exception as exc:
        return _error(provider=provider, action=action, error_code="UPSTREAM_ERROR", error=str(exc))


def _normalize_provider(value: str) -> str:
    provider = (value or "osm").strip().lower()
    if provider == "auto":
        return "osm"
    if provider in {"osm", "google"}:
        return provider
    return "osm"


def _user_agent() -> str:
    ua = (os.getenv("MAPS_USER_AGENT", "ANKITA/1.0") or "ANKITA/1.0").strip()
    email = (os.getenv("MAPS_CONTACT_EMAIL", "") or "").strip()
    if email:
        return f"{ua} ({email})"
    return ua


def _timeout(service: str) -> float:
    if service == "overpass":
        return float(os.getenv("MAPS_OVERPASS_TIMEOUT_SEC", "20"))
    if service == "osrm":
        return float(os.getenv("MAPS_OSRM_TIMEOUT_SEC", "10"))
    return float(os.getenv("MAPS_NOMINATIM_TIMEOUT_SEC", "10"))


def _results_limit() -> int:
    try:
        return max(1, min(25, int(os.getenv("MAPS_RESULTS_LIMIT", "10"))))
    except ValueError:
        return 10


def _search_radius() -> int:
    try:
        return max(300, min(25000, int(os.getenv("MAPS_SEARCH_RADIUS_M", "5000"))))
    except ValueError:
        return 5000


def _http_get_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 10,
    retries: int = 2,
    backoff: float = 0.6,
) -> Any:
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            response: Response = requests.get(url, params=params, headers=headers, timeout=timeout)
            status = int(response.status_code)
            if status in {429, 500, 502, 503, 504}:
                if attempt < retries:
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise RuntimeError(f"HTTP {status}")
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError) as err:
            last_error = err
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            raise
        except requests.HTTPError as err:
            last_error = err
            raise
    if last_error:
        raise last_error
    raise RuntimeError("HTTP request failed")


def _http_post_json(
    url: str,
    *,
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 20,
    retries: int = 2,
    backoff: float = 0.6,
) -> Any:
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            response: Response = requests.post(url, data=data, headers=headers, timeout=timeout)
            status = int(response.status_code)
            if status in {429, 500, 502, 503, 504}:
                if attempt < retries:
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise RuntimeError(f"HTTP {status}")
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError) as err:
            last_error = err
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            raise
        except requests.HTTPError as err:
            last_error = err
            raise
    if last_error:
        raise last_error
    raise RuntimeError("HTTP request failed")


def _success(provider: str, action: str, payload: Dict[str, Any], meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "status": "success",
        "provider": provider,
        "action": action,
        "meta": meta or {},
    }
    out.update(payload)
    return out


def _error(provider: str, action: str, error_code: str, error: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "status": "error",
        "provider": provider,
        "action": action,
        "error_code": error_code,
        "error": error,
        "meta": meta or {},
    }


def _get_route(origin: Optional[str], destination: Optional[str], mode: str, api_key: Optional[str], provider: str) -> Dict[str, Any]:
    if not origin or not destination:
        return _error(provider, "navigate", "MISSING_INPUT", "Both origin and destination required")
    if provider == "google" and api_key:
        return _route_google(origin, destination, mode, api_key)
    return _route_osrm(origin, destination, mode)


def _route_google(origin: str, destination: str, mode: str, api_key: str) -> Dict[str, Any]:
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "key": api_key,
        "departure_time": "now",
    }
    data = _http_get_json(url, params=params, timeout=_timeout("nominatim"))
    if data.get("status") != "OK":
        return _error("google", "navigate", "ROUTE_NOT_FOUND", data.get("error_message", "Route not found"))

    route = data["routes"][0]
    leg = route["legs"][0]
    payload = {
        "route": {
            "distance": leg["distance"]["text"],
            "duration": leg["duration"]["text"],
            "duration_in_traffic": leg.get("duration_in_traffic", {}).get("text"),
            "start_address": leg["start_address"],
            "end_address": leg["end_address"],
            "steps": [
                {
                    "instruction": step["html_instructions"].replace("<b>", "").replace("</b>", ""),
                    "distance": step["distance"]["text"],
                    "duration": step["duration"]["text"],
                }
                for step in leg.get("steps", [])
            ],
        },
    }
    payload.update(payload["route"])
    return _success("google", "navigate", payload, meta={"mode_used": mode, "fallback_used": False})


def _route_osrm(origin: str, destination: str, mode: str) -> Dict[str, Any]:
    origin_coords = _geocode_nominatim(origin)
    dest_coords = _geocode_nominatim(destination)
    if not origin_coords or not dest_coords:
        return _error("osm", "navigate", "GEOCODE_FAILED", "Could not geocode origin or destination")

    osrm_profile, mode_fallback = _to_osrm_profile(mode)
    url = (
        "https://router.project-osrm.org/route/v1/"
        f"{osrm_profile}/{origin_coords['lon']},{origin_coords['lat']};{dest_coords['lon']},{dest_coords['lat']}"
    )
    data = _http_get_json(url, params={"overview": "false", "steps": "true"}, headers={"User-Agent": _user_agent()}, timeout=_timeout("osrm"))

    if data.get("code") != "Ok" or not data.get("routes"):
        return _error("osm", "navigate", "ROUTE_NOT_FOUND", "Route not found")

    route = data["routes"][0]
    leg = route["legs"][0]
    steps = [
        {
            "instruction": _render_osrm_step_instruction(step),
            "distance": f"{step['distance'] / 1000:.1f} km",
            "duration": f"{step['duration'] / 60:.0f} min",
        }
        for step in leg.get("steps", [])
    ]
    payload = {
        "route": {
            "distance": f"{route['distance'] / 1000:.1f} km",
            "duration": f"{route['duration'] / 60:.0f} min",
            "start_address": origin,
            "end_address": destination,
            "steps": steps,
        },
    }
    payload.update(payload["route"])
    return _success(
        "osm",
        "navigate",
        payload,
        meta={"mode_used": osrm_profile, "mode_fallback": mode_fallback, "fallback_used": False},
    )


def _search_places(query: Optional[str], location: Optional[str], api_key: Optional[str], provider: str) -> Dict[str, Any]:
    if not query:
        return _error(provider, "search_places", "MISSING_INPUT", "Query required")

    default_location = os.getenv("MAPS_DEFAULT_ORIGIN", os.getenv("GOOGLE_MAPS_DEFAULT_ORIGIN", "New Delhi"))
    location = location or default_location

    if provider == "google" and api_key:
        return _search_places_google(query, location, api_key)

    origin_coords = _geocode_nominatim(location)
    if not origin_coords:
        return _error("osm", "search_places", "GEOCODE_FAILED", "Could not geocode location")

    overpass_results = _search_places_overpass(query, origin_coords)
    if overpass_results:
        return _search_success("osm", query, location, overpass_results, fallback_used=False)

    nominatim_results = _search_places_nominatim_fallback(query, location, origin_coords)
    if nominatim_results:
        return _search_success("osm", query, location, nominatim_results, fallback_used=True)

    return _error("osm", "search_places", "NO_RESULTS", "No places found", meta={"fallback_used": True})


def _search_success(provider: str, query: str, location: str, places: List[Dict[str, Any]], fallback_used: bool) -> Dict[str, Any]:
    payload = {
        "query": query,
        "origin": location,
        "places": places,
        "count": len(places),
    }
    return _success(provider, "search_places", payload, meta={"fallback_used": fallback_used})


def _search_places_google(query: str, location: str, api_key: str) -> Dict[str, Any]:
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"query": f"{query} near {location}", "key": api_key}
    data = _http_get_json(url, params=params, timeout=_timeout("nominatim"))
    if data.get("status") not in {"OK", "ZERO_RESULTS"}:
        return _error("google", "search_places", "UPSTREAM_ERROR", data.get("error_message", "Search failed"))

    places: List[Dict[str, Any]] = []
    for p in data.get("results", [])[:_results_limit()]:
        places.append(
            {
                "name": p.get("name", "Unknown"),
                "address": p.get("formatted_address", ""),
                "rating": p.get("rating"),
                "price_level": p.get("price_level"),
                "open_now": p.get("opening_hours", {}).get("open_now"),
                "types": p.get("types", []),
                "lat": (p.get("geometry", {}).get("location", {}) or {}).get("lat"),
                "lon": (p.get("geometry", {}).get("location", {}) or {}).get("lng"),
            }
        )

    payload = {"query": query, "origin": location, "places": places, "count": len(places)}
    return _success("google", "search_places", payload, meta={"fallback_used": False})


def _search_places_overpass(query: str, origin_coords: Dict[str, float]) -> List[Dict[str, Any]]:
    key, value = _map_query_to_overpass_tag(query)
    if not key or not value:
        return []

    radius = _search_radius()
    limit = _results_limit()
    lat = origin_coords["lat"]
    lon = origin_coords["lon"]

    overpass_query = (
        "[out:json][timeout:20];"
        "(" 
        f"node[{key}={value}](around:{radius},{lat},{lon});"
        f"way[{key}={value}](around:{radius},{lat},{lon});"
        f"relation[{key}={value}](around:{radius},{lat},{lon});"
        ");"
        f"out center {limit};"
    )

    data = _http_post_json(
        "https://overpass-api.de/api/interpreter",
        data={"data": overpass_query},
        headers={"User-Agent": _user_agent()},
        timeout=_timeout("overpass"),
    )

    elements = data.get("elements", [])
    results: List[Dict[str, Any]] = []
    for el in elements:
        tags = el.get("tags", {}) or {}
        lat2 = el.get("lat", (el.get("center") or {}).get("lat"))
        lon2 = el.get("lon", (el.get("center") or {}).get("lon"))
        if lat2 is None or lon2 is None:
            continue

        dist_km = _haversine_km(origin_coords["lat"], origin_coords["lon"], float(lat2), float(lon2))
        name = tags.get("name") or tags.get("brand") or value.replace("_", " ").title()
        address = _format_overpass_address(tags)
        results.append(
            {
                "name": name,
                "address": address,
                "type": tags.get("amenity") or tags.get("tourism") or tags.get("shop") or key,
                "category": f"{key}:{value}",
                "lat": float(lat2),
                "lon": float(lon2),
                "distance_km": round(dist_km, 3),
            }
        )

    results.sort(key=lambda x: x.get("distance_km", 1e9))
    return results[:limit]


def _search_places_nominatim_fallback(query: str, location: str, origin_coords: Dict[str, float]) -> List[Dict[str, Any]]:
    params = {
        "q": f"{query} near {location}",
        "format": "json",
        "limit": _results_limit(),
        "addressdetails": 1,
    }
    data = _http_get_json(
        "https://nominatim.openstreetmap.org/search",
        params=params,
        headers={"User-Agent": _user_agent()},
        timeout=_timeout("nominatim"),
    )

    results: List[Dict[str, Any]] = []
    for place in data:
        try:
            lat = float(place["lat"])
            lon = float(place["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        dist_km = _haversine_km(origin_coords["lat"], origin_coords["lon"], lat, lon)
        results.append(
            {
                "name": place.get("display_name", "").split(",")[0] or "Unknown",
                "address": place.get("display_name", ""),
                "type": place.get("type", ""),
                "category": place.get("class", ""),
                "lat": lat,
                "lon": lon,
                "distance_km": round(dist_km, 3),
            }
        )

    results.sort(key=lambda x: x.get("distance_km", 1e9))
    return results[: _results_limit()]


def _get_distance(origin: Optional[str], destination: Optional[str], mode: str, api_key: Optional[str], provider: str) -> Dict[str, Any]:
    if not origin or not destination:
        return _error(provider, "distance", "MISSING_INPUT", "Both origin and destination required")

    if provider == "google" and api_key:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {"origins": origin, "destinations": destination, "mode": mode, "key": api_key}
        data = _http_get_json(url, params=params, timeout=_timeout("nominatim"))

        if data.get("status") != "OK":
            return _error("google", "distance", "UPSTREAM_ERROR", "Distance calculation failed")

        element = data.get("rows", [{}])[0].get("elements", [{}])[0]
        if element.get("status") != "OK":
            return _error("google", "distance", "ROUTE_NOT_FOUND", "Route not found")

        payload = {
            "distance": element["distance"]["text"],
            "duration": element["duration"]["text"],
            "origin": data.get("origin_addresses", [origin])[0],
            "destination": data.get("destination_addresses", [destination])[0],
        }
        return _success("google", "distance", payload, meta={"fallback_used": False})

    route = _route_osrm(origin, destination, mode)
    if route.get("status") != "success":
        return _error("osm", "distance", route.get("error_code", "ROUTE_NOT_FOUND"), route.get("error", "Route not found"), meta=route.get("meta", {}))

    payload = {
        "distance": route.get("distance"),
        "duration": route.get("duration"),
        "origin": origin,
        "destination": destination,
        "route": route.get("route"),
    }
    return _success("osm", "distance", payload, meta=route.get("meta", {}))


def _get_traffic(origin: Optional[str], destination: Optional[str], api_key: Optional[str], provider: str) -> Dict[str, Any]:
    if not origin or not destination:
        return _error(provider, "traffic", "MISSING_INPUT", "Both origin and destination required")

    if provider != "google" or not api_key:
        route = _route_osrm(origin, destination, "driving")
        if route.get("status") != "success":
            return _error("osm", "traffic", route.get("error_code", "ROUTE_NOT_FOUND"), route.get("error", "Route not found"), meta=route.get("meta", {}))

        payload = {
            "distance": route.get("distance"),
            "estimated_duration": route.get("duration"),
            "traffic_live_supported": False,
            "note": "Live traffic is unavailable on free OSM endpoints; returning best-effort route ETA.",
        }
        return _success("osm", "traffic", payload, meta={"traffic_live_supported": False, "fallback_used": False})

    route = _route_google(origin, destination, "driving", api_key)
    if route.get("status") != "success":
        return _error("google", "traffic", route.get("error_code", "ROUTE_NOT_FOUND"), route.get("error", "Route not found"), meta=route.get("meta", {}))

    payload = {
        "normal_duration": route.get("duration"),
        "current_duration": route.get("duration_in_traffic", route.get("duration")),
        "distance": route.get("distance"),
        "traffic_live_supported": True,
    }
    return _success("google", "traffic", payload, meta={"traffic_live_supported": True, "fallback_used": False})


def _geocode(address: Optional[str], api_key: Optional[str], provider: str) -> Dict[str, Any]:
    if not address:
        return _error(provider, "geocode", "MISSING_INPUT", "Address required")

    if provider == "google" and api_key:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        data = _http_get_json(url, params={"address": address, "key": api_key}, timeout=_timeout("nominatim"))
        if data.get("status") != "OK":
            return _error("google", "geocode", "GEOCODE_FAILED", "Geocoding failed")
        result = data["results"][0]
        location = result["geometry"]["location"]
        payload = {"address": result["formatted_address"], "lat": location["lat"], "lon": location["lng"]}
        return _success("google", "geocode", payload, meta={"fallback_used": False})

    coords = _geocode_nominatim(address)
    if not coords:
        return _error("osm", "geocode", "GEOCODE_FAILED", "Geocoding failed")
    payload = {"address": address, "lat": coords["lat"], "lon": coords["lon"]}
    return _success("osm", "geocode", payload, meta={"fallback_used": False})


def _reverse_geocode(coords: Optional[str], api_key: Optional[str], provider: str) -> Dict[str, Any]:
    if not coords:
        return _error(provider, "reverse_geocode", "MISSING_INPUT", "Coordinates required")

    try:
        lat, lon = map(float, coords.replace(" ", "").split(","))
    except Exception:
        return _error(provider, "reverse_geocode", "INVALID_COORDS", "Invalid coordinates format. Use: lat,lon")

    if provider == "google" and api_key:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        data = _http_get_json(url, params={"latlng": f"{lat},{lon}", "key": api_key}, timeout=_timeout("nominatim"))
        if data.get("status") != "OK":
            return _error("google", "reverse_geocode", "REVERSE_GEOCODE_FAILED", "Reverse geocoding failed")
        payload = {"address": data["results"][0]["formatted_address"], "lat": lat, "lon": lon}
        return _success("google", "reverse_geocode", payload, meta={"fallback_used": False})

    result = _reverse_geocode_nominatim(lat, lon)
    if not result:
        return _error("osm", "reverse_geocode", "REVERSE_GEOCODE_FAILED", "Reverse geocoding failed")
    payload = {"address": result.get("display_name", ""), "lat": lat, "lon": lon}
    return _success("osm", "reverse_geocode", payload, meta={"fallback_used": False})


def _geocode_nominatim(address: str) -> Optional[Dict[str, float]]:
    data = _http_get_json(
        "https://nominatim.openstreetmap.org/search",
        params={"q": address, "format": "json", "limit": 1},
        headers={"User-Agent": _user_agent()},
        timeout=_timeout("nominatim"),
    )
    if not data:
        return None
    try:
        return {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])}
    except (KeyError, TypeError, ValueError):
        return None


def _reverse_geocode_nominatim(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    data = _http_get_json(
        "https://nominatim.openstreetmap.org/reverse",
        params={"lat": lat, "lon": lon, "format": "json"},
        headers={"User-Agent": _user_agent()},
        timeout=_timeout("nominatim"),
    )
    if not isinstance(data, dict):
        return None
    return data


def _to_osrm_profile(mode: str) -> Tuple[str, bool]:
    mode = (mode or "driving").strip().lower()
    if mode == "bicycling":
        return "cycling", False
    if mode == "walking":
        return "walking", False
    if mode == "transit":
        return "driving", True
    return "driving", False


def _render_osrm_step_instruction(step: Dict[str, Any]) -> str:
    maneuver = step.get("maneuver", {}) or {}
    m_type = str(maneuver.get("type", "continue")).replace("_", " ")
    modifier = str(maneuver.get("modifier", "")).replace("_", " ").strip()
    name = (step.get("name") or "").strip()
    if name and modifier:
        return f"{m_type.title()} {modifier} onto {name}"
    if name:
        return f"{m_type.title()} onto {name}"
    if modifier:
        return f"{m_type.title()} {modifier}"
    return m_type.title()


def _map_query_to_overpass_tag(query: str) -> Tuple[Optional[str], Optional[str]]:
    q = (query or "").strip().lower()
    mappings = [
        (("coffee", "cafe"), ("amenity", "cafe")),
        (("restaurant", "food", "eatery", "diner"), ("amenity", "restaurant")),
        (("hospital", "clinic"), ("amenity", "hospital")),
        (("atm", "cash"), ("amenity", "atm")),
        (("fuel", "petrol", "gas station"), ("amenity", "fuel")),
        (("pharmacy", "chemist", "medical store"), ("amenity", "pharmacy")),
        (("hotel", "stay", "lodging"), ("tourism", "hotel")),
    ]
    for keys, tag in mappings:
        if any(k in q for k in keys):
            return tag
    return (None, None)


def _format_overpass_address(tags: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("addr:housenumber", "addr:street", "addr:suburb", "addr:city", "addr:state"):
        value = str(tags.get(key, "")).strip()
        if value:
            parts.append(value)
    return ", ".join(parts)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c
