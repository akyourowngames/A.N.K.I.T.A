"""Tests for the zero-API-key websearch engine (requests mocked)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import websearch


class _Resp:
    def __init__(self, status=200, text="", json_data=None, headers=None):
        self.status_code = status
        self.text = text
        self._json = json_data
        self.headers = headers or {"Content-Type": "text/html"}

    def json(self):
        if self._json is not None:
            return self._json
        raise ValueError("no json")


DDG_HTML = """
<html><body>
<div class="result">
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Falpha">Alpha Page</a>
<a class="result__snippet" href="#">ignore</a>
<div class="result__snippet">Alpha snippet about testing.</div>
</div>
<div class="result">
<a class="result__a" href="https://example.com/beta">Beta Page</a>
<div class="result__snippet">Beta snippet here.</div>
</div>
</body></html>
"""

RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Big Event Happens</title><link>https://news.example.com/e1</link>
<pubDate>Sat, 06 Sep 2026 05:00:00 GMT</pubDate><source>ExampleNews</source>
<description><![CDATA[<p>Details of the event.</p>]]></description></item>
</channel></rss>"""


def _mock_http(monkeypatch, tmp_path, handler):
    monkeypatch.setattr(websearch, "_http", handler)
    websearch._CACHE.clear()
    monkeypatch.setattr(websearch, "_cache_dir", lambda: tmp_path / "webcache")


def test_ddg_parse_titles_urls_snippets(monkeypatch, tmp_path):
    def fake(method, url, **kw):
        assert method == "POST"
        assert "duckduckgo" in url
        assert kw["data"]["q"] == "alpha test"
        return _Resp(200, DDG_HTML)
    _mock_http(monkeypatch, tmp_path, fake)
    results, note = websearch.search_ddg("alpha test", limit=5)
    assert len(results) == 2
    assert results[0]["url"] == "https://example.com/alpha"
    assert results[0]["title"] == "Alpha Page"
    assert "testing" in results[0]["snippet"]
    assert note == ""


def test_ddg_captcha_falls_back(monkeypatch, tmp_path):
    calls = []

    def fake(method, url, **kw):
        calls.append(url)
        if "lite" in url:
            return _Resp(200, DDG_HTML)
        return _Resp(200, "<html>anomaly-modal captcha challenge</html>")
    _mock_http(monkeypatch, tmp_path, fake)
    results, note = websearch.search_ddg("x", limit=5)
    assert results and "lite" in note.lower() or "blocked" in note.lower()
    assert any("lite" in c for c in calls)


def test_gnews_parse_and_when_injection(monkeypatch, tmp_path):
    seen = {}

    def fake(method, url, **kw):
        seen.update(kw.get("params", {}))
        assert "news.google.com" in url
        return _Resp(200, RSS_XML, headers={"Content-Type": "application/rss+xml"})
    _mock_http(monkeypatch, tmp_path, fake)
    results, note = websearch.news_gnews("mars mission", when="1d", limit=5)
    assert "when:1d" in seen["q"]
    assert results[0]["title"] == "Big Event Happens"
    assert results[0]["source"] == "ExampleNews"
    assert "2026" in results[0]["date"]
    assert note == ""


def test_gnews_bad_xml_graceful(monkeypatch, tmp_path):
    _mock_http(monkeypatch, tmp_path, lambda *a, **k: _Resp(200, "<<<not xml", headers={}))
    results, note = websearch.news_gnews("x")
    assert results == [] and "bad XML" in note


def test_fusion_dedupe_limit_and_partial_failure(monkeypatch, tmp_path):
    def fake(method, url, **kw):
        if "duckduckgo" in url:
            return _Resp(200, DDG_HTML)
        if "wikipedia" in url:
            raise RuntimeError("wiki down")
        raise AssertionError(url)
    _mock_http(monkeypatch, tmp_path, fake)
    monkeypatch.setattr(websearch, "_is_techy", lambda q: False)
    results, note = websearch.search("alpha test fusion qb1", backend="auto", limit=1)
    assert len(results) == 1
    assert "wiki" in note.lower() or "error" in note.lower()


def test_fetch_html_to_text_and_truncation(monkeypatch, tmp_path):
    html_page = ("<html><head><style>.x{}</style><script>var a=1;</script></head>"
                 "<body><nav>menu</nav><h1>Hello World</h1><p>" + ("word " * 5000) + "</p></body></html>")

    def fake(method, url, **kw):
        return _Resp(200, html_page, headers={"Content-Type": "text/html"})
    _mock_http(monkeypatch, tmp_path, fake)
    monkeypatch.setattr(websearch, "jina_fallback", lambda: False)
    text, err = websearch.fetch("https://example.com/p-trunc", max_chars=1000)
    assert err == "" and "Hello World" in text
    assert "menu" not in text and "truncated" in text


def test_fetch_bad_url_and_http_error(monkeypatch, tmp_path):
    text, err = websearch.fetch("notaurl")
    assert text == "" and err.startswith("ERROR")
    _mock_http(monkeypatch, tmp_path, lambda *a, **k: _Resp(404, "nope", headers={}))
    monkeypatch.setattr(websearch, "jina_fallback", lambda: False)
    text, err = websearch.fetch("https://example.com/missing-404", use_cache=False)
    assert text == "" and "404" in err


def test_cache_second_call_no_rehit(monkeypatch, tmp_path):
    calls = []

    def fake(method, url, **kw):
        calls.append(1)
        return _Resp(200, DDG_HTML)
    _mock_http(monkeypatch, tmp_path, fake)
    websearch.search("cache me unique qz9", backend="web", limit=2)
    websearch.search("cache me unique qz9", backend="web", limit=2)
    assert len(calls) == 1


def test_kill_switch_filters_tools(monkeypatch):
    import mcpclient.builtin as _b
    monkeypatch.delenv("ZUMBA_NO_WEB", raising=False)
    names = [t["function"]["name"] for t in _b.visible_tools()]
    assert any(n.endswith("__web_search") for n in names)
    monkeypatch.setenv("ZUMBA_NO_WEB", "1")
    names2 = [t["function"]["name"] for t in _b.visible_tools()]
    assert not any("__web_" in n for n in names2)


def test_builtin_handle_dispatch(monkeypatch):
    import asyncio
    import mcpclient.builtin as _b

    class _Mgr:
        meta_state = {}

    async def go():
        out = await _b.handle(_Mgr(), "web_search", {"query": "", "limit": 3})
        assert out.startswith("ERROR")
        monkeypatch.setattr(websearch, "search", lambda *a, **k: ([{"title": "T", "url": "https://t.co", "snippet": "s", "source": "web"}], ""))
        out2 = await _b.handle(_Mgr(), "web_search", {"query": "hi", "limit": 3})
        assert "[1]" in out2 and "https://t.co" in out2
    asyncio.run(go())
