import os, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server.geo_store as gs

def _isolate(tmp_path=None):
    import pathlib
    d = tempfile.mkdtemp()
    os.environ["ZUMBA_GEO_DB"] = os.path.join(d, "geo.db")
    return d

def test_ping_lifecycle():
    _isolate()
    gs.record_ping("c1", 28.6, 77.2, source="point")
    p = gs.last_ping("c1")
    assert p and abs(p["lat"] - 28.6) < 1e-6
    assert gs.last_ping("nobody") is None
    assert gs.last_ping("c1", max_age_s=0.0) is not None

def test_track_window():
    _isolate()
    gs.track_start("c1", 30)
    assert gs.track_active("c1")
    gs.track_stop("c1")
    assert not gs.track_active("c1")

def test_visit_lifecycle_and_purge():
    _isolate()
    gs.log_visit("c1", "Cafe X", 28.6, 77.2, note="good")
    rows = gs.query_visits("c1")
    assert rows and rows[0]["place_name"] == "Cafe X"
    n = gs.purge("c1")
    assert n >= 1 and gs.query_visits("c1") == []
