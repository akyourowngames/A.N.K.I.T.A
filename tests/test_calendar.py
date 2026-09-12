"""Tests for Google Calendar integration (Issue #5, mocked HTTP/files)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import calendar as C


SAMPLE = {
    "items": [
        {"id": "1", "summary": "Standup", "start": {"dateTime": "2026-09-13T09:30:00+05:30"},
         "end": {"dateTime": "2026-09-13T10:00:00+05:30"}, "location": "Office",
         "htmlLink": "https://cal.example/e1", "attendees": [{"email": "a@x.com"}]},
        {"id": "2", "summary": "Family dinner", "start": {"date": "2026-09-13"},
         "end": {"date": "2026-09-14"}, "location": "Home"},
    ]
}


class _Resp:
    def __init__(self, status=200, json_data=None, text=""):
        self.status_code = status
        self._json = json_data if json_data is not None else {}
        self.text = text or "{}"

    def json(self):
        return self._json


def _isolate(monkeypatch, tmp_path):
    for k in ("ZUMBA_CALENDAR_TOKEN", "ZUMBA_CALENDAR_REFRESH_TOKEN",
              "ZUMBA_CALENDAR_CLIENT_ID", "ZUMBA_CALENDAR_CLIENT_SECRET",
              "ZUMBA_NO_CALENDAR", "ZUMBA_TZ", "ZUMBA_CALENDAR_TIMEOUT",
              "ZUMBA_CALENDAR_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(C, "token_path", lambda: tmp_path / "calendar_token.json")
    C._CACHE.clear()


def test_parse_and_format():
    evs = C.parse_events(SAMPLE)
    assert len(evs) == 2 and evs[0]["summary"] == "Standup"
    assert evs[0]["location"] == "Office" and evs[0]["link"].startswith("https")
    out = C.format_events(evs, "Today")
    # Time renders in LOCAL tz — compare against the helper, not a fixed clock.
    assert "Standup" in out and C._short_time("2026-09-13T09:30:00+05:30") in out
    assert C.format_events([], "Today").startswith("Today:")


def test_short_time_all_day():
    import re
    assert C._short_time("2026-09-13") == "2026-09-13"
    assert re.fullmatch(r"\d{2}:\d{2}", C._short_time("2026-09-13T09:30:00+05:30"))
    assert C._short_time("") == "??:??"


def test_local_day_bounds_not_utc(monkeypatch, tmp_path):
    import datetime as _dt
    _isolate(monkeypatch, tmp_path)
    tmin, tmax, daykey = C._day_bounds_local()
    local_today = _dt.datetime.now(C.local_tz()).strftime("%Y-%m-%d")
    assert daykey == local_today
    assert tmin[:10] == local_today and tmax[:10] >= local_today
    # Bounds carry a UTC offset (local midnight), never bare UTC midnight.
    assert ("+" in tmin or tmin.endswith("Z") or _dt.datetime.now().astimezone().utcoffset() == _dt.timedelta(0))


def test_is_auth_code_shape():
    assert C.is_auth_code("4/0AbCdefGhIjKlMnOpQrStUvWxYz12")
    assert not C.is_auth_code("ya29.a0AfH6SMBxyc789")
    assert not C.is_auth_code("hello world this is chat")
    assert not C.is_auth_code("short")
    assert not C.is_auth_code("")


def test_kill_switch(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("ZUMBA_NO_CALENDAR", "1")
    assert not C.enabled()
    assert C.today().startswith("ERROR:")
    assert C.search("x").startswith("ERROR:")
    assert C.create("t", "2026-09-13T09:30:00").startswith("ERROR:")
    assert C.brief().startswith("ERROR:")
    assert C.auth_start("cid").startswith("ERROR:")
    assert C.set_token("abc").startswith("ERROR:")


def test_not_connected_honest(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert not C.is_connected()
    for out in (C.today(), C.search("standup"), C.create("t", "2026-09-13T09:30:00"), C.brief()):
        assert "not connected" in out.lower()
        assert "standup" not in out.lower() or "matches" in out.lower()


def test_status_redacts_token(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.save_token({"access_token": "ya29.supersecretvalue12345"})
    out = C.status_text()
    assert "connected: yes" in out
    assert "supersecretvalue" not in out
    assert "2345" in out  # last 4 only


def test_today_search_brief_mocked(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.save_token({"access_token": "tok123"})
    monkeypatch.setattr(C, "_api_get", lambda *a, **k: (SAMPLE, ""))
    monkeypatch.setattr(C, "_travel_between", lambda *a, **k: "")
    out = C.today()
    assert "Standup" in out
    out2 = C.search("dinner")
    assert "dinner" in out2.lower() or "Family" in out2
    brief = C.brief()
    assert "Calendar brief" in brief and "Standup" in brief
    assert "travel" in brief.lower() or "prep" in brief.lower()
    # cached second call
    assert C.today().endswith("(cached)")


def test_today_uses_local_bounds_and_timezone(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.save_token({"access_token": "tok123"})
    seen = {}

    def fake_get(path, params=None, timeout=0):
        seen.update(params or {})
        return SAMPLE, ""
    monkeypatch.setattr(C, "_api_get", fake_get)
    C.today()
    import datetime as _dt
    assert seen["timeMin"][:10] == _dt.datetime.now(C.local_tz()).strftime("%Y-%m-%d")
    assert "Z" not in seen["timeMin"] or "+" in seen["timeMin"] or seen["timeMin"].endswith("+00:00")


def test_travel_between_real_estimate(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert C._travel_between("", "Office") == ""
    import tools.geo as _G
    monkeypatch.setattr(_G, "enabled", lambda: True)
    monkeypatch.setattr(_G, "route", lambda a, b, m="drive": "Route: 12.0 km, ~25 min\n- step")
    assert C._travel_between("Home", "Office") == "~25 min drive (12.0 km)"
    monkeypatch.setattr(_G, "route", lambda a, b, m="drive": "ERROR: routing down.")
    assert C._travel_between("Home", "Office") == ""


def test_create_validation_and_mock(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.save_token({"access_token": "tok123"})
    assert C.create("", "2026-09-13T09:30:00").startswith("ERROR:")
    assert C.create("t", "").startswith("ERROR:")
    assert C.create("t", "not-a-date").startswith("ERROR:")
    assert C.create("t", "2026-09-13T10:00:00", end="2026-09-13T09:00:00").startswith("ERROR:")
    assert C.create("t", "2026-09-13T10:00:00", end="nope").startswith("ERROR:")
    bodies = {}

    def fake_post(path, body=None, timeout=0):
        bodies.update(body or {})
        return {"htmlLink": "https://cal.example/new"}, ""
    monkeypatch.setattr(C, "_api_post", fake_post)
    out = C.create("Party", "2026-09-13T18:00:00", location="Home")
    assert out.startswith("Created: Party") and "https://" in out
    # Naive local input gets an offset + timeZone (m2), never bare UTC assumption.
    assert "+" in bodies["start"]["dateTime"] or bodies["start"]["dateTime"].endswith("Z")
    assert bodies["start"].get("timeZone") and bodies["end"].get("timeZone")


def test_auth_start_needs_client(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    out = C.auth_start("")
    assert out.startswith("ERROR:") and "client_id" in out.lower()
    out2 = C.auth_start("my-client-id")
    assert "accounts.google.com" in out2 and "my-client-id" in out2


GOOD_CODE = "4/0AbCdefGhIjKlMnOpQrStUvWxYz1234567890"


def test_auth_finish_exchange_mock(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.save_token({"client_id": "cid", "client_secret": "csec"})

    def fake_post(url, data=None, timeout=0, **k):
        assert "oauth2.googleapis" in url
        assert data["code"] == GOOD_CODE
        return _Resp(200, {"access_token": "new-access-xyz", "refresh_token": "new-refresh",
                           "expires_in": 3600})
    monkeypatch.setattr(C, "_requests", type("R", (), {"post": staticmethod(fake_post)}))
    out = C.auth_finish(GOOD_CODE)
    assert out.startswith("Calendar connected")
    assert C.is_connected()

    def fake_bad(url, data=None, timeout=0, **k):
        return _Resp(400, {}, "invalid_grant")
    monkeypatch.setattr(C, "_requests", type("R", (), {"post": staticmethod(fake_bad)}))
    assert C.auth_finish(GOOD_CODE).startswith("ERROR:")


def test_auth_finish_rejects_non_code(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.save_token({"client_id": "cid", "client_secret": "csec"})
    out = C.auth_finish("ya29.a0AfH6SMBpastetokenhere")
    assert out.startswith("ERROR:") and "token" in out.lower()
    assert C.auth_finish("just some chat text here").startswith("ERROR:")


def test_auth_state_verified(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.save_token({"client_id": "cid", "client_secret": "csec"})
    C.auth_start("cid")  # stores pending_state
    import json
    stored = json.loads((tmp_path / "calendar_token.json").read_text(encoding="utf-8"))
    assert stored.get("pending_state")

    def fake_post(url, data=None, timeout=0, **k):
        return _Resp(200, {"access_token": "tok-state-ok", "expires_in": 3600})
    monkeypatch.setattr(C, "_requests", type("R", (), {"post": staticmethod(fake_post)}))
    assert C.auth_finish(GOOD_CODE, state="wrong-state").startswith("ERROR:")
    assert C.auth_finish(GOOD_CODE, state=stored["pending_state"]).startswith("Calendar connected")
    # One-time state is dropped after success.
    stored2 = json.loads((tmp_path / "calendar_token.json").read_text(encoding="utf-8"))
    assert "pending_state" not in stored2


def test_set_token_paste(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert C.set_token("").startswith("ERROR:")
    out = C.set_token("ya29.pasted-token-9999", "refresh-1")
    assert "saved" in out.lower() and "pasted-token" not in out
    assert C.is_connected()


def test_builtin_registered_and_filtered(monkeypatch):
    import mcpclient.builtin as _b
    monkeypatch.delenv("ZUMBA_NO_CALENDAR", raising=False)
    assert _b.TOOL_ACCESS["calendar_today"] == "read"
    assert _b.TOOL_ACCESS["calendar_search"] == "read"
    assert _b.TOOL_ACCESS["calendar_brief"] == "read"
    assert _b.TOOL_ACCESS["calendar_status"] == "read"
    assert _b.TOOL_ACCESS["calendar_create"] == "local"
    names = [t["function"]["name"] for t in _b.BUILTIN_TOOLS]
    for n in ("calendar_today", "calendar_search", "calendar_create",
              "calendar_brief", "calendar_status"):
        assert any(x.endswith("__" + n) for x in names), n
    monkeypatch.setenv("ZUMBA_NO_CALENDAR", "1")
    vis = [t["function"]["name"] for t in _b.visible_tools()]
    assert not any("__calendar_" in v for v in vis)


def test_builtin_handle_dispatch(monkeypatch, tmp_path):
    import asyncio
    import mcpclient.builtin as _b
    _isolate(monkeypatch, tmp_path)
    monkeypatch.delenv("ZUMBA_NO_CALENDAR", raising=False)

    class _Mgr:
        meta_state = {}

    async def go():
        out = await _b.handle(_Mgr(), "calendar_search", {"query": ""})
        assert "not connected" in out.lower() or out.startswith("ERROR")
        out2 = await _b.handle(_Mgr(), "calendar_create", {"summary": "", "start": ""})
        assert out2.startswith("ERROR") or "not connected" in out2.lower()
        monkeypatch.setattr(C, "today", lambda *a, **k: "Today (1):\n- 09:30 Standup")
        assert "Standup" in await _b.handle(_Mgr(), "calendar_today", {})
        monkeypatch.setattr(C, "brief", lambda *a, **k: "Calendar brief (1 today):\n1. Standup")
        assert "brief" in (await _b.handle(_Mgr(), "calendar_brief", {})).lower()
        monkeypatch.setattr(C, "status_text", lambda: "Calendar status — connected: yes")
        assert "connected" in await _b.handle(_Mgr(), "calendar_status", {})
    asyncio.run(go())


def test_cache_keyed_by_identity(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.save_token({"access_token": "tok-one"})
    calls = []

    def fake_get(path, params=None, timeout=0):
        calls.append(1)
        return SAMPLE, ""
    monkeypatch.setattr(C, "_api_get", fake_get)
    C.today()
    C.today()
    assert len(calls) == 1  # cached
    C.save_token({"access_token": "tok-two"})  # login change invalidates
    C.today()
    assert len(calls) == 2


def test_token_file_and_dir_perms(monkeypatch, tmp_path):
    import os
    _isolate(monkeypatch, tmp_path)
    p = C.save_token({"access_token": "tok-perm-check"})
    assert p.exists()
    assert "tok-perm-check" not in C.status_text()  # redacted everywhere
    if os.name == "posix":
        assert (p.stat().st_mode & 0o777) == 0o600
        assert (p.parent.stat().st_mode & 0o777) == 0o700


def test_web_writes_gated(monkeypatch, tmp_path):
    import types
    _isolate(monkeypatch, tmp_path)
    from server import calendar_api as _api
    req = types.SimpleNamespace(headers={})
    monkeypatch.setenv("ZUMBA_NO_CALENDAR", "1")
    import pytest as _pt
    with _pt.raises(Exception):
        _api.auth_start(_api.AuthStart(), req)
    with _pt.raises(Exception):
        _api.save_token(_api.TokenSave(access_token="x"), req)
    monkeypatch.delenv("ZUMBA_NO_CALENDAR", raising=False)
    # No shared secret configured -> allowed, kill-switch off.
    out = _api.status()
    assert out["enabled"] is True
    monkeypatch.setenv("ZUMBA_CALENDAR_API_KEY", "s3cret")
    bad = types.SimpleNamespace(headers={})
    with _pt.raises(Exception):
        _api.save_token(_api.TokenSave(access_token="x"), bad)
    ok_req = types.SimpleNamespace(headers={"x-zumba-key": "s3cret"})
    C.save_token({"access_token": "web-tok-ok"})
    assert C.is_connected()


def test_telegram_code_detector_strict():
    from server.telegram_channel import _cal_looks_like_code, _CAL_PENDING, _cal_prune_pending
    import time as _t
    assert _cal_looks_like_code("4/0AbCdefGhIjKlMnOpQrStUvWxYz12")
    assert not _cal_looks_like_code("ya29.a0AfH6SMBpastetokenhere")
    assert not _cal_looks_like_code("just chatting about lunch plans today")
    assert not _cal_looks_like_code("/cal auth 4/0AbCdefGhIjKlMnOpQrStUvWxYz12")
    assert not _cal_looks_like_code("")
    _CAL_PENDING[12345] = _t.time() - 3600
    _cal_prune_pending()
    assert 12345 not in _CAL_PENDING


def test_daily_includes_calendar(monkeypatch):
    from memory import briefing as _br
    import tools.calendar as _cal
    monkeypatch.setattr(_cal, "enabled", lambda: True)
    monkeypatch.setattr(_cal, "is_connected", lambda: True)
    monkeypatch.setattr(_cal, "brief", lambda *a, **k: "Calendar brief (1 today):\n1. 09:30 Standup")
    monkeypatch.setattr(_br, "community_digest", lambda con, limit=3: [])
    monkeypatch.setattr(_br, "on_this_day", lambda con, limit=5: [])
    monkeypatch.setattr(_br, "date_lines", lambda con, limit=8: [])
    monkeypatch.setattr(_br, "goals_digest", lambda con, limit=3: "")
    monkeypatch.setattr("memory.reflection.open_follow_ups", lambda con, limit=10: [])
    monkeypatch.setattr("memory.mood.mood_context", lambda con: "")
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    out = _br.compose_daily(con, use_llm=False)
    assert "Standup" in out
    monkeypatch.setattr(_cal, "is_connected", lambda: False)
    out2 = _br.compose_daily(con, use_llm=False)
    assert "Standup" not in out2


def test_daily_skips_calendar_errors(monkeypatch):
    """M4: HTTP failures must not stall the brief or leak ERROR: into the LLM prompt."""
    from memory import briefing as _br
    import tools.calendar as _cal
    monkeypatch.setattr(_cal, "enabled", lambda: True)
    monkeypatch.setattr(_cal, "is_connected", lambda: True)
    seen = {}

    def fake_brief(timeout=0):
        seen["timeout"] = timeout
        return "ERROR: calendar http 500 (overloaded)."
    monkeypatch.setattr(_cal, "brief", fake_brief)
    monkeypatch.setattr(_br, "community_digest", lambda con, limit=3: [])
    monkeypatch.setattr(_br, "on_this_day", lambda con, limit=5: [])
    monkeypatch.setattr(_br, "date_lines", lambda con, limit=8: [])
    monkeypatch.setattr(_br, "goals_digest", lambda con, limit=3: "")
    monkeypatch.setattr("memory.reflection.open_follow_ups", lambda con, limit=10: [])
    monkeypatch.setattr("memory.mood.mood_context", lambda con: "")
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    out = _br.compose_daily(con, use_llm=False)
    assert "ERROR: calendar" not in out
    assert seen.get("timeout", 0) > 0  # daily uses a short timeout, not 10s
