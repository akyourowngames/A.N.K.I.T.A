import os
from core.config import get_api_key, get_base_url, get_default_model


def test_base_url_default():
    os.environ.pop("KILO_BASE_URL", None)
    os.environ.pop("OPENCODE_BASE_URL", None)
    assert "opencode.ai" in get_base_url()


def test_api_key_require_raises(monkeypatch):
    monkeypatch.delenv("KILO_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    try:
        get_api_key(require=True)
    except RuntimeError:
        return
    raise AssertionError("should have raised")


def test_default_model_env(monkeypatch):
    monkeypatch.setenv("ZUMBA_MODEL", "x/y:free")
    assert get_default_model() == "x/y:free"
