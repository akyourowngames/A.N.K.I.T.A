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
              "ZUMBA_NO_CALENDAR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(C, "token_path", lambda: tmp_path / "calendar_token.json")
    C._CACHE.clear()


def test_parse_and_format():
    evs = C.parse_events(SAMPLE)
    assert len(evs) == 2 and evs[0]["summary"] == "Standup"
    assert evs[0]["location"] == "Office" and evs[0]["link"].startswith("https")
    out = C.format_events(evs, "Today")
    assert "Standup" in out and "09:30" in out
    assert C.format_events([], "Today").startswith("Today:")


def test_short_time_all_day():
    assert C._short_time("2026-09-13") == "2026-09-13"
    assert C._short_time("2026-09-13T09:30:00+05:30") == "09:30"


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
    out = C.today()
    assert "Standup" in out
    out2 = C.search("dinner")
    assert "dinner" in out2.lower() or "Family" in out2
    brief = C.brief()
    assert "Calendar brief" in brief and "Standup" in brief
    assert "travel" in brief.lower() or "prep" in brief.lower()
    # cached second call
    assert C.today().endswith("(cached)")


def test_create_validation_and_mock(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.save_token({"access_token": "tok123"})
    assert C.create("", "2026-09-13T09:30:00").startswith("ERROR:")
    assert C.create("t", "").startswith("ERROR:")
    assert C.create("t", "not-a-date").startswith("ERROR:")
    monkeypatch.setattr(C, "_api_post",
                        lambda *a, **k: ({"htmlLink": "https://cal.example/new"}, ""))
    out = C.create("Party", "2026-09-13T18:00:00", location="Home")
    assert out.startswith("Created: Party") and "https://" in out


def test_auth_start_needs_client(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    out = C.auth_start("")
    assert out.startswith("ERROR:") and "client_id" in out.lower()
    out2 = C.auth_start("my-client-id")
    assert "accounts.google.com" in out2 and "my-client-id" in out2


def test_auth_finish_exchange_mock(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.save_token({"client_id": "cid", "client_secret": "csec"})

    def fake_post(url, data=None, timeout=0, **k):
        assert "oauth2.googleapis" in url
        assert data["code"] == "good-code"
        return _Resp(200, {"access_token": "new-access-xyz", "refresh_token": "new-refresh",
                           "expires_in": 3600})
    monkeypatch.setattr(C, "_requests", type("R", (), {"post": staticmethod(fake_post)}))
    out = C.auth_finish("good-code")
    assert out.startswith("Calendar connected")
    assert C.is_connected()

    def fake_bad(url, data=None, timeout=0, **k):
        return _Resp(400, {}, "invalid_grant")
    monkeypatch.setattr(C, "_requests", type("R", (), {"post": staticmethod(fake_bad)}))
    assert C.auth_finish("bad").startswith("ERROR:")


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
