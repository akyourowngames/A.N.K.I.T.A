import unittest
from unittest.mock import Mock, patch

import tools.maps_ops as maps_ops


def _resp(status_code=200, payload=None):
    m = Mock()
    m.status_code = status_code
    m.json.return_value = payload if payload is not None else {}
    m.raise_for_status.return_value = None
    return m


class MapsOpsTests(unittest.TestCase):
    @patch("tools.maps_ops.requests.post")
    @patch("tools.maps_ops.requests.get")
    def test_search_places_category_uses_overpass(self, mock_get, mock_post):
        mock_get.return_value = _resp(
            payload=[{"lat": "28.63", "lon": "77.22"}]  # geocode location
        )
        mock_post.return_value = _resp(
            payload={
                "elements": [
                    {
                        "lat": 28.631,
                        "lon": 77.221,
                        "tags": {"name": "Cafe One", "amenity": "cafe"},
                    }
                ]
            }
        )
        out = maps_ops.maps_op(action="search_places", query="coffee", origin="Connaught Place")
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["provider"], "osm")
        self.assertEqual(out["action"], "search_places")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["places"][0]["name"], "Cafe One")
        self.assertFalse(out["meta"]["fallback_used"])
        self.assertIn("overpass-api.de", mock_post.call_args.kwargs["url"] if "url" in mock_post.call_args.kwargs else mock_post.call_args.args[0])

    @patch("tools.maps_ops.requests.post")
    @patch("tools.maps_ops.requests.get")
    def test_search_places_falls_back_to_nominatim_when_overpass_empty(self, mock_get, mock_post):
        mock_post.return_value = _resp(payload={"elements": []})
        mock_get.side_effect = [
            _resp(payload=[{"lat": "28.63", "lon": "77.22"}]),  # geocode
            _resp(payload=[{"lat": "28.6305", "lon": "77.2205", "display_name": "Fallback Cafe, New Delhi", "type": "cafe", "class": "amenity"}]),  # fallback search
        ]
        out = maps_ops.maps_op(action="search_places", query="coffee", origin="Connaught Place")
        self.assertEqual(out["status"], "success")
        self.assertTrue(out["meta"]["fallback_used"])
        self.assertEqual(out["count"], 1)

    @patch("tools.maps_ops.requests.post")
    @patch("tools.maps_ops.requests.get")
    def test_search_places_returns_nearest_first_when_coords_available(self, mock_get, mock_post):
        mock_get.return_value = _resp(payload=[{"lat": "28.63", "lon": "77.22"}])
        mock_post.return_value = _resp(
            payload={
                "elements": [
                    {"lat": 28.70, "lon": 77.30, "tags": {"name": "Far Cafe", "amenity": "cafe"}},
                    {"lat": 28.6301, "lon": 77.2201, "tags": {"name": "Near Cafe", "amenity": "cafe"}},
                ]
            }
        )
        out = maps_ops.maps_op(action="search_places", query="cafe", origin="Connaught Place")
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["places"][0]["name"], "Near Cafe")

    @patch("tools.maps_ops.requests.get")
    def test_navigate_osm_returns_steps_distance_duration(self, mock_get):
        mock_get.side_effect = [
            _resp(payload=[{"lat": "28.63", "lon": "77.22"}]),
            _resp(payload=[{"lat": "28.61", "lon": "77.23"}]),
            _resp(
                payload={
                    "code": "Ok",
                    "routes": [
                        {
                            "distance": 4200,
                            "duration": 360,
                            "legs": [{"steps": [{"distance": 300, "duration": 30, "maneuver": {"type": "turn", "modifier": "left"}, "name": "Janpath"}]}],
                        }
                    ],
                }
            ),
        ]
        out = maps_ops.maps_op(action="navigate", origin="A", destination="B")
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["action"], "navigate")
        self.assertIn("distance", out)
        self.assertIn("duration", out)
        self.assertTrue(len(out["steps"]) >= 1)

    @patch("tools.maps_ops.requests.get")
    def test_traffic_osm_sets_live_false_and_note_present(self, mock_get):
        mock_get.side_effect = [
            _resp(payload=[{"lat": "28.63", "lon": "77.22"}]),
            _resp(payload=[{"lat": "28.61", "lon": "77.23"}]),
            _resp(payload={"code": "Ok", "routes": [{"distance": 3000, "duration": 400, "legs": [{"steps": []}]}]}),
        ]
        out = maps_ops.maps_op(action="traffic", origin="A", destination="B")
        self.assertEqual(out["status"], "success")
        self.assertFalse(out["traffic_live_supported"])
        self.assertIn("best-effort", out["note"])

    @patch("tools.maps_ops.requests.get")
    def test_distance_uses_route_normalization(self, mock_get):
        mock_get.side_effect = [
            _resp(payload=[{"lat": "28.63", "lon": "77.22"}]),
            _resp(payload=[{"lat": "28.61", "lon": "77.23"}]),
            _resp(payload={"code": "Ok", "routes": [{"distance": 3000, "duration": 400, "legs": [{"steps": []}]}]}),
        ]
        out = maps_ops.maps_op(action="distance", origin="A", destination="B")
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["action"], "distance")
        self.assertEqual(out["provider"], "osm")
        self.assertIn("route", out)

    @patch("tools.maps_ops.requests.get")
    def test_geocode_reverse_geocode_success_shape(self, mock_get):
        mock_get.side_effect = [
            _resp(payload=[{"lat": "28.61", "lon": "77.20"}]),  # geocode
            _resp(payload={"display_name": "Test Address"}),  # reverse geocode
        ]
        g = maps_ops.maps_op(action="geocode", query="India Gate")
        r = maps_ops.maps_op(action="reverse_geocode", origin="28.61,77.20")
        self.assertEqual(g["status"], "success")
        self.assertEqual(g["action"], "geocode")
        self.assertIn("lat", g)
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["action"], "reverse_geocode")
        self.assertIn("address", r)

    def test_error_schema_contains_error_code(self):
        out = maps_ops.maps_op(action="reverse_geocode", origin="bad_coords")
        self.assertEqual(out["status"], "error")
        self.assertIn("error_code", out)
        self.assertIn("provider", out)
        self.assertEqual(out["action"], "reverse_geocode")

    @patch("tools.maps_ops.requests.get")
    @patch("tools.maps_ops.time.sleep", return_value=None)
    def test_retry_on_transient_timeout_then_success(self, _sleep, mock_get):
        mock_get.side_effect = [
            maps_ops.requests.Timeout("timeout"),
            _resp(payload=[{"lat": "28.61", "lon": "77.20"}]),
        ]
        out = maps_ops.maps_op(action="geocode", query="India Gate")
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["provider"], "osm")

    @patch("tools.maps_ops.HAS_REQUESTS", False)
    def test_no_requests_dependency_error_path(self):
        out = maps_ops.maps_op(action="geocode", query="India Gate")
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error_code"], "MISSING_DEPENDENCY")


if __name__ == "__main__":
    unittest.main()
