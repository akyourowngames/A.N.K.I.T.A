import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import music_ops


class MusicOpsTests(unittest.TestCase):
    def test_search_music_ranks_matches(self) -> None:
        fake = {
            "engine": "duckduckgo-html",
            "results": [
                {"title": "Shape of You - Ed Sheeran (Official Audio)", "url": "https://example.com/1", "domain": "example.com", "snippet": "official audio"},
                {"title": "Random podcast episode", "url": "https://example.com/2", "domain": "example.com", "snippet": "talk show"},
            ],
        }
        with patch("tools.music_ops._has_yt_dlp", return_value=False):
            with patch("tools.music_ops.realtime_search.search_web", return_value=fake):
                out = music_ops.search_music("shape of you", max_results=5)
        self.assertEqual(out["kind"], "music_search")
        self.assertTrue(len(out["results"]) >= 1)
        self.assertEqual(out["results"][0]["title"], "Shape of You - Ed Sheeran (Official Audio)")

    def test_stop_music_without_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = music_ops.stop_music(root)
            self.assertEqual(out["kind"], "music_stop")
            self.assertFalse(out["stopped"])

    def test_play_music_uses_windows_fallback(self) -> None:
        fake_search = {
            "kind": "music_search",
            "is_confident_match": True,
            "results": [
                {"title": "Track", "url": "https://example.com/track", "score": 0.9},
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("tools.music_ops.search_music", return_value=fake_search):
                with patch("tools.music_ops._build_player_command", return_value=None):
                    with patch("tools.music_ops._fallback_windows_builtin", return_value={"pid": 123, "local_file": "x", "launcher": "wmp-com"}):
                        out = music_ops.play_music(root, "track")
            self.assertEqual(out["kind"], "music_play")
            self.assertEqual(out["pid"], 123)


if __name__ == "__main__":
    unittest.main(verbosity=2)
