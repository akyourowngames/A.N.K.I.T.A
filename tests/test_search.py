import unittest
from unittest.mock import patch
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import realtime_search


class _FakeResponse:
    def __init__(self, text: str = "", json_data=None, status_code: int = 200):
        self.text = text
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._json


class RealtimeSearchTests(unittest.TestCase):
    def test_search_web_google_custom_search(self) -> None:
        payload = {
            "items": [
                {"title": "A", "link": "https://example.com/a", "snippet": "desc a"},
                {"title": "B", "link": "https://example.com/b", "snippet": "desc b"},
            ]
        }
        with patch.dict("os.environ", {"GOOGLE_SEARCH_API_KEY": "k", "GOOGLE_SEARCH_ENGINE_ID": "cx"}, clear=False):
            with patch("tools.realtime_search.requests.get", return_value=_FakeResponse(json_data=payload)):
                out = realtime_search.search_web("ankita", max_results=5)
        self.assertEqual(out["kind"], "web_search")
        self.assertEqual(out["engine"], "google-custom-search")
        self.assertEqual(len(out["results"]), 2)
        self.assertNotIn("url", out["results"][0])
        self.assertFalse(out["include_urls"])

    def test_search_web_duck_html(self) -> None:
        html = """
        <html><body>
        <a class="result__a" href="https://example.com/a">Result A</a>
        <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fb">Result B</a>
        </body></html>
        """
        with patch.dict("os.environ", {"GOOGLE_SEARCH_API_KEY": "", "GOOGLE_SEARCH_ENGINE_ID": ""}, clear=False):
            with patch("tools.realtime_search.requests.get", return_value=_FakeResponse(text=html)):
                out = realtime_search.search_web("ankita", max_results=5)
        self.assertEqual(out["kind"], "web_search")
        self.assertTrue(len(out["results"]) >= 2)
        self.assertNotIn("url", out["results"][0])
        self.assertFalse(out["include_urls"])

    def test_search_news_rss(self) -> None:
        xml = """<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>Headline</title>
            <link>https://news.example/item1</link>
            <pubDate>Wed, 18 Feb 2026 10:00:00 GMT</pubDate>
            <source url="https://news.example">NewsSource</source>
          </item>
        </channel></rss>
        """
        with patch("tools.realtime_search.requests.get", return_value=_FakeResponse(text=xml)):
            out = realtime_search.search_news("ai", max_results=5)
        self.assertEqual(out["kind"], "news_search")
        self.assertEqual(len(out["results"]), 1)
        self.assertEqual(out["results"][0]["title"], "Headline")
        self.assertNotIn("url", out["results"][0])
        self.assertFalse(out["include_urls"])

    def test_search_news_with_urls_opt_in(self) -> None:
        xml = """<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>Headline</title>
            <link>https://news.example/item1</link>
            <pubDate>Wed, 18 Feb 2026 10:00:00 GMT</pubDate>
            <source url="https://news.example">NewsSource</source>
          </item>
        </channel></rss>
        """
        with patch("tools.realtime_search.requests.get", return_value=_FakeResponse(text=xml)):
            out = realtime_search.search_news("ai", max_results=5, include_urls=True)
        self.assertTrue(out["include_urls"])
        self.assertEqual(out["results"][0]["url"], "https://news.example/item1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
