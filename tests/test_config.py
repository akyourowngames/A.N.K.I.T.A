import os
from core.config import get_api_key, get_base_url, get_default_model
from core import config as config_mod


def test_base_url_default(monkeypatch):
    monkeypatch.delenv("ZUMBA_BASE_URL", raising=False)
    monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    monkeypatch.delenv("KILO_BASE_URL", raising=False)
    monkeypatch.delenv("OPENCODE_BASE_URL", raising=False)
    assert "nvidia.com" in get_base_url()


def test_base_url_legacy_fallback(monkeypatch):
    monkeypatch.delenv("ZUMBA_BASE_URL", raising=False)
    monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    monkeypatch.setenv("KILO_BASE_URL", "https://legacy.example/v1")
    assert get_base_url() == "https://legacy.example/v1"


def test_api_key_require_raises(monkeypatch):
    monkeypatch.delenv("ZUMBA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("KILO_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    try:
        get_api_key(require=True)
    except RuntimeError as exc:
        assert "ZUMBA_API_KEY" in str(exc)
        return
    raise AssertionError("should have raised")


def test_api_key_legacy_fallback(monkeypatch):
    monkeypatch.delenv("ZUMBA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("KILO_API_KEY", "legacy-key")
    assert get_api_key(require=True) == "legacy-key"


def test_api_key_nvidia_fallback(monkeypatch):
    monkeypatch.delenv("ZUMBA_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    assert get_api_key(require=True) == "nvapi-test"


def test_default_model_env(monkeypatch):
    monkeypatch.setenv("ZUMBA_MODEL", "nvidia/nemotron-3-super-120b-a12b")
    assert get_default_model() == "nvidia/nemotron-3-super-120b-a12b"


def test_default_model_is_nim():
    assert config_mod.DEFAULT_MODEL == "nvidia/nemotron-3-super-120b-a12b"
