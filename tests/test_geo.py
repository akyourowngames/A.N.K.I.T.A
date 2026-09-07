import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tempfile
from tools import geo

def test_maps_link():
    out = geo.maps_link("Connaught Place")
    assert "google.com/maps" in out and "openstreetmap" in out
    assert geo.maps_link("").startswith("ERROR:")

def test_parse_geocode():
    out = geo.parse_geocode([{"display_name": "Delhi, India", "lat": "28.6", "lon": "77.2", "type": "city", "class": "place"}])
    assert "28.6" in out and "Delhi" in out
    assert geo.parse_geocode([]).startswith("ERROR:")

def test_parse_route():
    d = {"routes": [{"distance": 10000, "duration": 1200, "legs": [{"steps": [{"name": "Main St", "distance": 500, "maneuver": {"instruction": "Turn left"}}]}]}]}
    out = geo.parse_route(d)
    assert "10.0 km" in out and "Main St" in out
    assert geo.parse_route({}).startswith("ERROR:")

def test_parse_overpass_and_bearing():
    d = {"elements": [{"lat": 28.632, "lon": 77.219, "tags": {"name": "Cafe X", "amenity": "cafe"}}]}
    out = geo.parse_overpass(d, 28.631, 77.217, 5)
    assert "Cafe X" in out and "km" in out
    assert geo.parse_overpass({"elements": []}, 0, 0).startswith("ERROR:")

def test_haversine():
    assert geo._haversine_km(0, 0, 0, 0) == 0.0
    assert 100 < geo._haversine_km(28.6, 77.2, 19.0, 72.8) < 1500

def test_kill_switch():
    os.environ["ZUMBA_NO_GEO"] = "1"
    try:
        assert geo.geocode("Delhi").startswith("ERROR:")
        assert geo.weather(0, 0).startswith("ERROR:")
    finally:
        os.environ.pop("ZUMBA_NO_GEO", None)

def test_builtin_geo_registered():
    from mcpclient import builtin
    names = [t["function"]["name"] for t in builtin.BUILTIN_TOOLS]
    for n in ("geo_geocode", "geo_route", "geo_weather", "geo_nearby", "geo_maps_link",
              "geo_track_start", "geo_whereami", "geo_visit_log"):
        assert any(x.endswith("__" + n) for x in names), n
    os.environ["ZUMBA_NO_GEO"] = "1"
    try:
        vis = [t["function"]["name"] for t in builtin.visible_tools()]
        assert not any("__geo_" in v for v in vis)
    finally:
        os.environ.pop("ZUMBA_NO_GEO", None)
