import pathlib
import pytest
import store


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def test_config_roundtrip(isolated_home):
    store.config_set("default_model", "x/y:free")
    assert store.config_get("default_model") == "x/y:free"


def test_session_lifecycle(isolated_home):
    sid = store.new_session_id()
    store.create_session(sid, "m", "sys", title="Hello world test")
    store.add_message(sid, "user", "Hello world test")
    store.add_message(sid, "assistant", "Hi there")
    data = store.get_session(sid)
    assert data is not None
    assert len(data["messages"]) == 2
    rows = store.list_sessions(search="Hello world")
    assert any(r["id"] == sid for r in rows)
    assert store.delete_session(sid)
    assert store.get_session(sid) is None
