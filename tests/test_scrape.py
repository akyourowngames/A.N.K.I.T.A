"""Tests for the Scrapling scrape tiers (fetchers stubbed, no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import scrape

_REAL_CHECK_URL_PUBLIC = scrape.check_url_public

import pytest


@pytest.fixture(autouse=True)
def _allow_net(monkeypatch):
    # SSRF guard does real DNS; stub to allow-all except in SSRF tests,
    # which rebind the real implementation explicitly.
    monkeypatch.setattr(scrape, "check_url_public", lambda url: "")


class _Node:
    def __init__(self, val):
        self._val = val

    def get(self):
        return self._val


class _Resp:
    def __init__(self, status=200, text="Hello World body " * 60, title="Demo Page",
                 links=None, url="https://example.com/a"):
        self.status = status
        self._text = text
        self._title = title
        self._links = links or []
        self.url = url
        self.encoding = "utf-8"
        self.body = text.encode("utf-8")

    def get_all_text(self, ignore_tags=None):
        return self._text

    def markdown(self):
        return "# Demo\n\n" + self._text[:200]

    def css(self, sel):
        if sel == "title::text":
            return [_Node(self._title)]
        if sel == "h1::text":
            return [_Node("Hello World")]
        if sel == "a::attr(href)":
            return [_Node(h) for h in self._links]
        return []

    def xpath(self, sel):
        return []

    def urljoin(self, href):
        import urllib.parse as _u
        return _u.urljoin(self.url, href)


def _nocache(monkeypatch, tmp_path):
    import tools.websearch as _web
    monkeypatch.setattr(_web, "_CACHE", {}, raising=False)
    monkeypatch.setattr(_web, "cache_get", lambda k: (None, False))
    monkeypatch.setattr(_web, "cache_put", lambda k, v: None)


def test_parse_selectors_dict_str_list():
    assert scrape.parse_selectors({"a": "h1"}) == {"a": "h1"}
    assert scrape.parse_selectors("title=h1, price=.price") == {"title": "h1", "price": ".price"}
    assert scrape.parse_selectors(["title=h1"]) == {"title": "h1"}
    assert scrape.parse_selectors('{"t": "h1"}') == {"t": "h1"}
    assert scrape.parse_selectors("") == {}
    assert scrape.parse_selectors(None) == {}


def test_is_url_and_bad_url():
    assert scrape.is_url("https://example.com/x")
    assert not scrape.is_url("notaurl")
    text, err = scrape.scrape_low("notaurl", use_cache=False)
    assert text == "" and err.startswith("ERROR")
    text, err = scrape.scrape_mid("notaurl", use_cache=False)
    assert text == "" and err.startswith("ERROR")
    text, err = scrape.scrape_high("notaurl", use_cache=False)
    assert text == "" and err.startswith("ERROR")


def test_low_static_ok(monkeypatch, tmp_path):
    _nocache(monkeypatch, tmp_path)
    monkeypatch.setattr(scrape, "static_get", lambda url: _Resp())
    text, note = scrape.scrape_low("https://example.com/a", use_cache=False)
    assert "Demo" in text and "low" in note


def test_low_blocked_points_to_mid(monkeypatch, tmp_path):
    _nocache(monkeypatch, tmp_path)
    monkeypatch.setattr(scrape, "static_get", lambda url: _Resp(status=403, text="x"))
    text, err = scrape.scrape_low("https://example.com/b", use_cache=False)
    assert text == "" and "scrape-mid" in err


def test_mid_auto_escalates_to_stealth(monkeypatch, tmp_path):
    _nocache(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(scrape, "static_get", lambda url: _Resp(status=403, text="x"))
    monkeypatch.setattr(scrape, "stealth_fetch",
                        lambda url, ws="": calls.append(url) or _Resp())
    text, note = scrape.scrape_mid("https://example.com/c", use_cache=False)
    assert calls and "stealth" in note and "Demo" in text


def test_mid_static_mode_no_stealth(monkeypatch, tmp_path):
    _nocache(monkeypatch, tmp_path)
    monkeypatch.setattr(scrape, "static_get", lambda url: _Resp())
    called = []
    monkeypatch.setattr(scrape, "stealth_fetch",
                        lambda url, ws="": called.append(1) or _Resp())
    text, note = scrape.scrape_mid("https://example.com/d", mode="static", use_cache=False)
    assert not called and "static" in note


def test_mid_selectors_json(monkeypatch, tmp_path):
    import json
    _nocache(monkeypatch, tmp_path)
    monkeypatch.setattr(scrape, "static_get", lambda url: _Resp())
    text, note = scrape.scrape_mid("https://example.com/e", selectors={"title": "h1::text"},
                                   format="json", use_cache=False)
    payload = json.loads(text)
    assert payload[0]["fields"]["title"] == ["Hello World"]
    assert "mid" in note


def test_mid_bad_mode():
    text, err = scrape.scrape_mid("https://example.com/e", mode="nope", use_cache=False)
    assert text == "" and err.startswith("ERROR")


def test_high_crawls_two_pages(monkeypatch, tmp_path):
    _nocache(monkeypatch, tmp_path)
    pages = {
        "https://example.com/a": _Resp(url="https://example.com/a",
                                       links=["/b"], text="Alpha page body " * 60),
        "https://example.com/b": _Resp(url="https://example.com/b",
                                       links=[], text="Beta page body " * 60),
    }
    monkeypatch.setattr(scrape, "static_get", lambda url: pages[url])
    monkeypatch.setattr(scrape, "extract_links",
                        lambda resp, base="": [l if l.startswith("http") else "https://example.com" + l
                                              for l in (resp._links or [])])
    text, note = scrape.scrape_high("https://example.com/a", depth=1, limit=5, use_cache=False)
    assert "[1]" in text and "[2]" in text and "high" in note


def test_high_respects_limit_and_depth_validation(monkeypatch, tmp_path):
    _nocache(monkeypatch, tmp_path)
    monkeypatch.setattr(scrape, "static_get", lambda url: _Resp(url=url))
    text, note = scrape.scrape_high("https://example.com/a", depth=9, limit=1, use_cache=False)
    # depth clamps to 2 with a visible note, no error
    assert "[1]" in text and "clamped" in note
    text2, err2 = scrape.scrape_high("https://example.com/a", limit="xx", use_cache=False)
    assert text2 == "" and err2.startswith("ERROR")


def test_ssrf_private_hosts_refused(monkeypatch):
    monkeypatch.setattr(scrape, "check_url_public", _REAL_CHECK_URL_PUBLIC)
    for bad in ("http://localhost/x", "http://127.0.0.1/", "http://192.168.1.1/",
                "http://169.254.169.254/", "http://[::1]/"):
        text, err = scrape.scrape_low(bad, use_cache=False)
        assert text == "" and "refusing" in err, bad
        text, err = scrape.scrape_mid(bad, use_cache=False)
        assert text == "" and "refusing" in err, bad
        text, err = scrape.scrape_high(bad, use_cache=False)
        assert text == "" and "refusing" in err, bad


def test_ssrf_redirect_landing_blocked(monkeypatch, tmp_path):
    _nocache(monkeypatch, tmp_path)
    monkeypatch.setattr(scrape, "check_url_public",
                        lambda url: "" if "example.com" in url else "ERROR: refusing (test).")
    monkeypatch.setattr(scrape, "static_get",
                        lambda url: _Resp(url="http://127.0.0.1/evil"))
    text, err = scrape.scrape_low("https://example.com/a", use_cache=False)
    assert text == "" and "non-public host" in err


def test_ssrf_history_chain_blocked(monkeypatch, tmp_path):
    _nocache(monkeypatch, tmp_path)
    monkeypatch.setattr(scrape, "check_url_public",
                        lambda url: "" if "example.com" in url else "ERROR: refusing (test).")
    via = _Resp(url="https://example.com/go")
    evil = _Resp(url="http://10.0.0.5/x")
    resp = _Resp(url="https://example.com/land")
    resp.history = [via, evil]
    monkeypatch.setattr(scrape, "static_get", lambda url: resp)
    text, err = scrape.scrape_mid("https://example.com/a", use_cache=False)
    assert text == "" and "redirect chain" in err


def test_high_private_link_visible_skip(monkeypatch, tmp_path):
    _nocache(monkeypatch, tmp_path)
    monkeypatch.setattr(scrape, "check_url_public",
                        lambda url: "" if "example.com" in url else "ERROR: refusing (test).")
    monkeypatch.setattr(scrape, "static_get", lambda url: _Resp(url=url, links=["/ok", "http://10.9.9.9/secret"]))
    monkeypatch.setattr(
        scrape, "extract_links",
        lambda resp, base="": ["https://example.com/ok", "http://10.9.9.9/secret"])
    text, note = scrape.scrape_high("https://example.com/a", depth=1, limit=5,
                                    same_domain=False, use_cache=False)
    assert "skipped-private" in text


def test_json_out_always_parses():
    import json
    big = "x" * 20000
    out = scrape.json_out([{"url": "https://example.com", "title": "T", "text": big}], cap=1000)
    payload = json.loads(out)
    assert payload[0]["truncated"] is True and len(out) <= 1000
    small = scrape.json_out([{"url": "u", "fields": {"a": ["1"]}}], cap=8000)
    assert json.loads(small)[0]["fields"] == {"a": ["1"]}


def test_json_out_guarantees():
    import copy
    import json
    # non-list field values are preserved, never char-split
    src = [{"url": "u", "fields": {"k": "notalist", "n": 42, "l": ["a", "b"]}}]
    before = copy.deepcopy(src)
    out = scrape.json_out(src, cap=400)
    assert src == before  # input never mutated
    payload = json.loads(out)
    assert payload[0]["fields"]["k"] == "notalist"
    assert payload[0]["fields"]["n"] == 42
    # adversarial: cap always holds, output always parses
    monster = [{"url": f"https://e.com/{i}", "text": "y" * 5000,
                "fields": {"f": ["z" * 3000] * 5}} for i in range(10)]
    out2 = scrape.json_out(monster, cap=600)
    assert len(out2) <= 600
    assert json.loads(out2)[-1].get("truncated") is True
    # non-dict items survive
    out3 = scrape.json_out(["plain", 7, {"url": "u", "text": "t" * 5000}], cap=500)
    parsed = json.loads(out3)
    assert len(out3) <= 500 and "plain" in json.dumps(parsed)


def test_mid_json_output_parses(monkeypatch, tmp_path):
    import json
    _nocache(monkeypatch, tmp_path)
    monkeypatch.setattr(scrape, "static_get",
                        lambda url: _Resp(text="word " * 5000))
    text, note = scrape.scrape_mid("https://example.com/e", format="json",
                                   max_chars=1200, use_cache=False)
    payload = json.loads(text)
    assert payload[0]["url"].startswith("https://")
    assert "mid" in note


def test_high_multiseed_hosts(monkeypatch, tmp_path):
    _nocache(monkeypatch, tmp_path)
    pages = {
        "https://a.com/1": _Resp(url="https://a.com/1", links=["https://a.com/2", "https://b.com/1"]),
        "https://a.com/2": _Resp(url="https://a.com/2", links=[]),
        "https://b.com/1": _Resp(url="https://b.com/1", links=[]),
    }
    monkeypatch.setattr(scrape, "static_get", lambda url: pages[url])
    monkeypatch.setattr(
        scrape, "extract_links",
        lambda resp, base="": [h if h.startswith("http") else "https://a.com" + h
                               for h in (resp._links or [])])
    text, note = scrape.scrape_high("https://a.com/1 https://b.com/1", depth=1,
                                    limit=10, same_domain=True, use_cache=False)
    assert "https://a.com/2" in text and "https://b.com/1" in text
    # cross-seed link must NOT leak: a.com crawl of depth1 from a/1 sees b/1 only as seed
    text2, _ = scrape.scrape_high("https://a.com/1", depth=1, limit=10,
                                  same_domain=True, use_cache=False)
    assert "https://a.com/2" in text2 and "b.com/1" not in text2


def test_fallback_truncate_caps(monkeypatch, tmp_path):
    import sys
    _nocache(monkeypatch, tmp_path)
    monkeypatch.setitem(sys.modules, "tools.websearch", None)
    out, trunc = scrape.truncate_output("z" * 10000, 1000)
    assert trunc and len(out) < 2000 and out.endswith("z" * 200)


def test_scrapling_noise_filter_drops_fetch_chatter():
    import logging
    scrape._silence_scrapling()
    lg = logging.getLogger("scrapling")
    assert any(isinstance(f, scrape._ScraplingNoiseFilter) for f in lg.filters)
    rec = logging.LogRecord("scrapling", logging.INFO, __file__, 1,
                            "Fetched (200) <GET https://example.com/> (referer: x)", None, None)
    assert lg.filter(rec) is False
    # level reset (what scrapling does per-fetch) must NOT drop the filter
    lg.setLevel(logging.INFO)
    assert any(isinstance(f, scrape._ScraplingNoiseFilter) for f in lg.filters)
    assert lg.filter(rec) is False
    scrape._silence_scrapling()


def test_needs_stealth_structural_only():
    assert scrape.needs_stealth(None)
    assert scrape.needs_stealth(_Resp(status=403, text="x"))
    assert scrape.needs_stealth(_Resp(status=200, text="tiny"))
    assert not scrape.needs_stealth(_Resp(status=200))


def test_kill_switch_filters_tools(monkeypatch):
    import mcpclient.builtin as _b
    monkeypatch.delenv("ZUMBA_NO_SCRAPE", raising=False)
    names = [t["function"]["name"] for t in _b.visible_tools()]
    assert any(n.endswith("__scrape_low") for n in names)
    assert any(n.endswith("__scrape_mid") for n in names)
    assert any(n.endswith("__scrape_high") for n in names)
    monkeypatch.setenv("ZUMBA_NO_SCRAPE", "1")
    names2 = [t["function"]["name"] for t in _b.visible_tools()]
    assert not any("__scrape_" in n for n in names2)


def test_builtin_handle_dispatch(monkeypatch):
    import asyncio
    import mcpclient.builtin as _b

    class _Mgr:
        meta_state = {}

    async def go():
        out = await _b.handle(_Mgr(), "scrape_low", {"url": ""})
        assert out.startswith("ERROR")
        monkeypatch.setattr(scrape, "scrape_low", lambda *a, **k: ("BODY", "(low/static)"))
        out2 = await _b.handle(_Mgr(), "scrape_low", {"url": "https://example.com"})
        assert "BODY" in out2
        out3 = await _b.handle(_Mgr(), "scrape_mid", {"url": ""})
        assert out3.startswith("ERROR")
        out4 = await _b.handle(_Mgr(), "scrape_high", {"urls": ""})
        assert out4.startswith("ERROR")
    asyncio.run(go())
