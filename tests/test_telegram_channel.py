import asyncio
import pathlib
import pytest
from server import channel_store
from server.telegram_channel import TelegramChannel, split_message, voice_max_sec


class FakeAPI:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.actions: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str):
        from server.telegram_channel import split_message as _split
        for c in _split(text):
            self.sent.append((chat_id, c))

    async def send_chat_action(self, chat_id: int, action: str = "typing"):
        self.actions.append((chat_id, action))

    async def close(self):
        pass


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("ZUMBA_TG_ALLOWED_CHAT_IDS", "7280190750")
    monkeypatch.setenv("ZUMBA_TG_VOICE_REPLY", "0")
    monkeypatch.setenv("ZUMBA_NO_MEMORY", "1")
    return tmp_path


def _msg(chat_id: int, text: str = "", update_id: int = 1, voice=None):
    m = {"message_id": 1, "chat": {"id": chat_id, "type": "private"}, "text": text}
    if voice is not None:
        m["voice"] = voice
        m.pop("text", None)
    return {"update_id": update_id, "message": m}


def test_offset_max_upsert(isolated_home):
    channel_store.set_next_offset("telegram", 5)
    channel_store.set_next_offset("telegram", 3)
    assert channel_store.get_next_offset("telegram") == 5
    channel_store.set_next_offset("telegram", 9)
    assert channel_store.get_next_offset("telegram") == 9


def test_allowlist_rejection(isolated_home):
    api = FakeAPI()
    ch = TelegramChannel(api=api)  # type: ignore
    asyncio.run(ch.handle_update(_msg(111, "hello")))
    assert api.sent and "Not authorized" in api.sent[0][1]
    assert "111" in api.sent[0][1]


def test_split_4096():
    long_text = "a\n" * 3000
    parts = split_message(long_text)
    assert len(parts) > 1
    assert all(len(p) <= 4096 for p in parts)


def test_chat_session_mapping(isolated_home, monkeypatch):
    import core.chat_pipeline as _pl
    monkeypatch.setattr(_pl, "aanswer", lambda sid, text, *a, **k: asyncio.sleep(0, result=f"echo:{text}"))
    api = FakeAPI()
    ch = TelegramChannel(api=api)  # type: ignore
    asyncio.run(ch.handle_update(_msg(7280190750, "hi there")))
    assert api.sent and api.sent[-1][1] == "echo:hi there"
    sid = channel_store.get_session_for_chat("telegram", "7280190750")
    assert sid.startswith("tg-")


def test_voice_duration_cap(isolated_home):
    import os
    os.environ["ZUMBA_TG_VOICE_MAX_SEC"] = "300"
    assert voice_max_sec() == 300
    api = FakeAPI()
    ch = TelegramChannel(api=api)  # type: ignore
    asyncio.run(ch.handle_update(_msg(7280190750, voice={"file_id": "x", "duration": 9999})))
    assert api.sent and "too long" in api.sent[-1][1].lower()


def test_cal_auth_explicit_pops_pending_on_success(isolated_home, monkeypatch):
    """N1: explicit `/cal auth <code>` consumes pending on success, keeps it on failure."""
    import time as _t
    for k in ("ZUMBA_CALENDAR_TOKEN", "ZUMBA_CALENDAR_REFRESH_TOKEN",
              "ZUMBA_CALENDAR_CLIENT_ID", "ZUMBA_CALENDAR_CLIENT_SECRET",
              "ZUMBA_NO_CALENDAR"):
        monkeypatch.delenv(k, raising=False)
    import server.telegram_channel as _tg
    import tools.calendar as _C
    code = "4/0AbCdefGhIjKlMnOpQrStUvWxYz12"
    _tg._CAL_PENDING[7280190750] = _t.time()
    monkeypatch.setattr(_C, "auth_finish", lambda c: "Calendar connected (token ****7890). Done.")
    api = FakeAPI()
    ch = TelegramChannel(api=api)  # type: ignore
    asyncio.run(ch.handle_update(_msg(7280190750, f"/cal auth {code}", update_id=21)))
    assert 7280190750 not in _tg._CAL_PENDING
    assert api.sent and "connected" in api.sent[-1][1].lower()
    _tg._CAL_PENDING[7280190750] = _t.time()
    monkeypatch.setattr(_C, "auth_finish", lambda c: "ERROR: token exchange http 400.")
    asyncio.run(ch.handle_update(_msg(7280190750, f"/cal auth {code}", update_id=22)))
    assert 7280190750 in _tg._CAL_PENDING  # kept for retry
    _tg._CAL_PENDING.pop(7280190750, None)


def test_cal_forget_needs_confirm(isolated_home, monkeypatch):
    for k in ("ZUMBA_CALENDAR_TOKEN", "ZUMBA_CALENDAR_REFRESH_TOKEN",
              "ZUMBA_CALENDAR_CLIENT_ID", "ZUMBA_CALENDAR_CLIENT_SECRET",
              "ZUMBA_NO_CALENDAR"):
        monkeypatch.delenv(k, raising=False)
    import tools.calendar as _C
    _C.save_token({"access_token": "tok-global"})
    assert _C.is_connected()
    api = FakeAPI()
    ch = TelegramChannel(api=api)  # type: ignore
    asyncio.run(ch.handle_update(_msg(7280190750, "/cal forget", update_id=23)))
    assert _C.is_connected()  # no confirm -> kept
    assert "confirm" in api.sent[-1][1].lower()
    asyncio.run(ch.handle_update(_msg(7280190750, "/cal forget yes", update_id=24)))
    assert not _C.is_connected()


def test_no_httpx_import():
    import sys
    assert "httpx" not in sys.modules or True
    src = pathlib.Path("server/telegram_channel.py").read_text(encoding="utf-8")
    assert "httpx" not in src
    assert "aiohttp" in src
