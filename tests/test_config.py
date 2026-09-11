import os
from core.config import (
    get_api_key,
    get_base_url,
    get_default_model,
    get_knowledge_api_key,
    get_knowledge_base_url,
    get_knowledge_llm,
    get_knowledge_model,
)
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


def test_knowledge_model_default_is_nex_mini():
    # Verified live: step-3.7-flash:free spends the token budget on hidden
    # reasoning and returns empty on extraction prompts; nex-mini returns
    # valid schema JSON for both extraction and audit passes.
    assert config_mod.KNOWLEDGE_DEFAULT_MODEL == "nex-agi/nex-n2.5-mini:free"


def test_knowledge_model_env_override(monkeypatch):
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_MODEL", "custom/model")
    assert get_knowledge_model() == "custom/model"


def test_knowledge_base_url_prefers_kilo_over_chat(monkeypatch):
    monkeypatch.setenv("ZUMBA_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("KILO_BASE_URL", "https://kilo.example/v1")
    monkeypatch.delenv("ZUMBA_KNOWLEDGE_BASE_URL", raising=False)
    assert get_knowledge_base_url() == "https://kilo.example/v1"
    assert get_base_url() == "https://chat.example/v1"


def test_knowledge_base_url_explicit_override(monkeypatch):
    monkeypatch.setenv("KILO_BASE_URL", "https://kilo.example/v1")
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_BASE_URL", "https://graph.example/v1")
    assert get_knowledge_base_url() == "https://graph.example/v1"


def test_knowledge_api_key_prefers_kilo(monkeypatch):
    monkeypatch.delenv("ZUMBA_KNOWLEDGE_API_KEY", raising=False)
    monkeypatch.setenv("ZUMBA_API_KEY", "chat-key")
    monkeypatch.setenv("KILO_API_KEY", "kilo-key")
    assert get_knowledge_api_key() == "kilo-key"
    assert get_api_key() == "chat-key"


def test_knowledge_llm_triple(monkeypatch):
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_MODEL", "stepfun/step-3.7-flash:free")
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_BASE_URL", "https://graph.example/v1")
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_API_KEY", "graph-key")
    triple = get_knowledge_llm()
    assert triple == {
        "model": "stepfun/step-3.7-flash:free",
        "api_key": "graph-key",
        "base_url": "https://graph.example/v1",
    }


def test_memory_llm_uses_knowledge_provider(monkeypatch):
    from memory import llm as memory_llm

    seen = {}

    class _Result:
        content = '{"ok": true}'

    def fake_chat_completion(msgs, model, api_key="", base_url="", **kw):
        seen.update(model=model, api_key=api_key, base_url=base_url)
        return _Result()

    monkeypatch.setattr(memory_llm, "chat_completion", fake_chat_completion)
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_MODEL", "stepfun/step-3.7-flash:free")
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_BASE_URL", "https://graph.example/v1")
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_API_KEY", "graph-key")
    out = memory_llm.chat_json('{"a": 1}')
    assert out == {"ok": True}
    assert seen["model"] == "stepfun/step-3.7-flash:free"
    assert seen["base_url"] == "https://graph.example/v1"
    assert seen["api_key"] == "graph-key"
