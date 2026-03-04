"""
Maps and navigation operations for A.N.K.I.T.A.
Supports Google Maps API and OpenStreetMap fallback.
"""
import os
import json
from typing import Any, Dict, Optional
from pathlib import Path

# Try to import requests, fallback gracefully
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def maps_op(
    action: str,
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    query: Optional[str] = None,
    mode: str = "driving",
    **kwargs
) -> Dict[str, Any]:
    """
    Maps and navigation operations.
    
    Actions:
    - navigate: Get route from origin to destination
    - search_places: Find places near a location
    - distance: Calculate distance between two points
    - traffic: Get current traffic info for a route
    - geocode: Convert address to coordinates
    - reverse_geocode: Convert coordinates to address
    
    Args:
        action: The operation to perform
        origin: Starting location (address or coordinates)
        destination: Ending location (address or coordinates)
        query: Search query for places
        mode: Travel mode (driving, walking, bicycling, transit)
    
    Returns:
        Dict with status and result data
    """
    if not HAS_REQUESTS:
        return {
            "status": "error",
            "error": "requests library not installed. Run: pip install requests"
        }
    
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    provider = os.getenv("MAPS_PROVIDER", "auto").lower()
    
    # Auto-select provider
    if provider == "auto":
        provider = "google" if api_key else "osm"
    
    try:
        if action == "navigate":
            return _get_route(origin, destination, mode, api_key, provider)
        elif action == "search_places":
            return _search_places(query, origin, api_key, provider)
        elif action == "distance":
            return _get_distance(origin, destination, mode, api_key, provider)
        elif action == "traffic":
            return _get_traffic(origin, destination, api_key, provider)
        elif action == "geocode":
            return _geocode(query or origin, api_key, provider)
        elif action == "reverse_geocode":
            return _reverse_geocode(origin, api_key, provider)
        else:
            return {"status": "error", "error": f"Unknown action: {action}"}
    
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _get_route(origin: str, destination: str, mode: str, api_key: Optional[str], provider: str) -> Dict[str, Any]:
    """Get navigation route between two points."""
    if not origin or not destination:
        return {"status": "error", "error": "Both origin and destination required"}
    
    if provider == "google" and api_key:
        url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "key": api_key,
            "departure_time": "now"  # For traffic data
        }
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") != "OK":
            return {"status": "error", "error": data.get("error_message", "Route not found")}
        
        route = data["routes"][0]
        leg = route["legs"][0]
        
        return {
            "status": "success",
            "distance": leg["distance"]["text"],
            "duration": leg["duration"]["text"],
            "duration_in_traffic": leg.get("duration_in_traffic", {}).get("text"),
            "start_address": leg["start_address"],
            "end_address": leg["end_address"],
            "steps": [
                {
                    "instruction": step["html_instructions"].replace("<b>", "").replace("</b>", ""),
                    "distance": step["distance"]["text"],
                    "duration": step["duration"]["text"]
                }
                for step in leg["steps"]
            ]
        }
    
    else:  # OSM fallback
        # Use OSRM (Open Source Routing Machine) for routing
        # Geocode addresses first
        origin_coords = _osm_geocode(origin)
        dest_coords = _osm_geocode(destination)
        
        if not origin_coords or not dest_coords:
            return {"status": "error", "error": "Could not geocode addresses"}
        
        url = f"http://router.project-osrm.org/route/v1/{mode}/{origin_coords['lon']},{origin_coords['lat']};{dest_coords['lon']},{dest_coords['lat']}"
        params = {"overview": "false", "steps": "true"}
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("code") != "Ok":
            return {"status": "error", "error": "Route not found"}
        
        route = data["routes"][0]
        leg = route["legs"][0]
        
        return {
            "status": "success",
            "distance": f"{route['distance'] / 1000:.1f} km",
            "duration": f"{route['duration'] / 60:.0f} min",
            "start_address": origin,
            "end_address": destination,
            "steps": [
                {
                    "instruction": step.get("maneuver", {}).get("instruction", "Continue"),
                    "distance": f"{step['distance'] / 1000:.1f} km",
                    "duration": f"{step['duration'] / 60:.0f} min"
                }
                for step in leg["steps"]
            ]
        }


def _search_places(query: str, location: Optional[str], api_key: Optional[str], provider: str) -> Dict[str, Any]:
    """Search for places near a location."""
    if not query:
        return {"status": "error", "error": "Query required"}
    
    default_location = os.getenv("GOOGLE_MAPS_DEFAULT_ORIGIN", "New Delhi")
    location = location or default_location
    
    if provider == "google" and api_key:
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": f"{query} near {location}",
            "key": api_key
        }
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            return {"status": "error", "error": data.get("error_message", "Search failed")}
        
        results = []
        for place in data.get("results", [])[:10]:
            results.append({
                "name": place["name"],
                "address": place.get("formatted_address", ""),
                "rating": place.get("rating"),
                "price_level": place.get("price_level"),
                "open_now": place.get("opening_hours", {}).get("open_now"),
                "types": place.get("types", [])
            })
        
        return {"status": "success", "places": results, "count": len(results)}
    
    else:  # OSM fallback
        coords = _osm_geocode(location)
        if not coords:
            return {"status": "error", "error": "Could not geocode location"}
        
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": query,
            "format": "json",
            "limit": 10,
            "lat": coords["lat"],
            "lon": coords["lon"]
        }
        headers = {"User-Agent": "ANKITA/1.0"}
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()
        
        results = []
        for place in data:
            results.append({
                "name": place.get("display_name", "").split(",")[0],
                "address": place.get("display_name", ""),
                "type": place.get("type", "")
            })
        
        return {"status": "success", "places": results, "count": len(results)}


def _get_distance(origin: str, destination: str, mode: str, api_key: Optional[str], provider: str) -> Dict[str, Any]:
    """Calculate distance between two points."""
    if not origin or not destination:
        return {"status": "error", "error": "Both origin and destination required"}
    
    if provider == "google" and api_key:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": origin,
            "destinations": destination,
            "mode": mode,
            "key": api_key
        }
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") != "OK":
            return {"status": "error", "error": "Distance calculation failed"}
        
        element = data["rows"][0]["elements"][0]
        
        if element.get("status") != "OK":
            return {"status": "error", "error": "Route not found"}
        
        return {
            "status": "success",
            "distance": element["distance"]["text"],
            "duration": element["duration"]["text"],
            "origin": data["origin_addresses"][0],
            "destination": data["destination_addresses"][0]
        }
    
    else:  # OSM fallback
        route = _get_route(origin, destination, mode, api_key, provider)
        if route.get("status") == "success":
            return {
                "status": "success",
                "distance": route["distance"],
                "duration": route["duration"],
                "origin": origin,
                "destination": destination
            }
        return route


def _get_traffic(origin: str, destination: str, api_key: Optional[str], provider: str) -> Dict[str, Any]:
    """Get current traffic information for a route."""
    if provider != "google" or not api_key:
        return {"status": "error", "error": "Traffic data requires Google Maps API"}
    
    route = _get_route(origin, destination, "driving", api_key, provider)
    
    if route.get("status") == "success":
        return {
            "status": "success",
            "normal_duration": route["duration"],
            "current_duration": route.get("duration_in_traffic", route["duration"]),
            "distance": route["distance"]
        }
    
    return route


def _geocode(address: str, api_key: Optional[str], provider: str) -> Dict[str, Any]:
    """Convert address to coordinates."""
    if not address:
        return {"status": "error", "error": "Address required"}
    
    if provider == "google" and api_key:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"address": address, "key": api_key}
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") != "OK":
            return {"status": "error", "error": "Geocoding failed"}
        
        result = data["results"][0]
        location = result["geometry"]["location"]
        
        return {
            "status": "success",
            "address": result["formatted_address"],
            "lat": location["lat"],
            "lon": location["lng"]
        }
    
    else:  # OSM fallback
        coords = _osm_geocode(address)
        if coords:
            return {
                "status": "success",
                "address": address,
                "lat": coords["lat"],
                "lon": coords["lon"]
            }
        return {"status": "error", "error": "Geocoding failed"}


def _reverse_geocode(coords: str, api_key: Optional[str], provider: str) -> Dict[str, Any]:
    """Convert coordinates to address."""
    if not coords:
        return {"status": "error", "error": "Coordinates required"}
    
    try:
        lat, lon = map(float, coords.replace(" ", "").split(","))
    except:
        return {"status": "error", "error": "Invalid coordinates format. Use: lat,lon"}
    
    if provider == "google" and api_key:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"latlng": f"{lat},{lon}", "key": api_key}
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("status") != "OK":
            return {"status": "error", "error": "Reverse geocoding failed"}
        
        result = data["results"][0]
        
        return {
            "status": "success",
            "address": result["formatted_address"],
            "lat": lat,
            "lon": lon
        }
    
    else:  # OSM fallback
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json"}
        headers = {"User-Agent": "ANKITA/1.0"}
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()
        
        return {
            "status": "success",
            "address": data.get("display_name", ""),
            "lat": lat,
            "lon": lon
        }


def _osm_geocode(address: str) -> Optional[Dict[str, float]]:
    """Geocode using OpenStreetMap Nominatim."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": "ANKITA/1.0"}
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()
        
        if data:
            return {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])}
    except:
        pass
    
    return None
