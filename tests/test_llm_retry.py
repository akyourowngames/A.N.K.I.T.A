"""Structured-output resilience: parser shapes + retry/backoff + fallback chain."""

from memory import llm as memory_llm


def test_extract_prose_wrapped_json():
    text = 'Here is the result:\n{"id": null, "reason": "ok"}\nHope that helps.'
    assert memory_llm._extract_json(text) == {"id": None, "reason": "ok"}


def test_extract_brace_inside_string():
    text = 'note {"a": "weird } brace", "b": 1} trailing'
    assert memory_llm._extract_json(text) == {"a": "weird } brace", "b": 1}


def test_extract_unclosed_think_tag():
    text = "<think>hmm let me think..." + '{"x": 1}'
    assert memory_llm._extract_json(text) == {"x": 1}


def test_extract_fenced_then_prose_span():
    text = "```json\nnot json at all\n```\nfinal: {\"y\": 2}"
    assert memory_llm._extract_json(text) == {"y": 2}


def test_extract_skips_broken_first_span():
    text = '{"broken": } garbage {"good": true}'
    assert memory_llm._extract_json(text) == {"good": True}


def test_extract_empty_and_junk():
    assert memory_llm._extract_json("") is None
    assert memory_llm._extract_json("no json here") is None
    assert memory_llm._extract_json("```\nnope\n```") is None


def test_chat_json_retries_then_succeeds(monkeypatch):
    calls = []

    def flaky(prompt, **kw):
        calls.append(prompt)
        if len(calls) < 3:
            return ""  # transient empty content
        return '{"ok": true}'

    monkeypatch.setattr(memory_llm, "chat_text", flaky)
    monkeypatch.setattr(memory_llm, "_backoff", lambda attempt: None)
    out = memory_llm.chat_json('{"a": 1}')
    assert out == {"ok": True}
    assert len(calls) == 3


def test_chat_json_gives_up_with_none(monkeypatch):
    monkeypatch.setattr(memory_llm, "chat_text", lambda *a, **k: "nope")
    monkeypatch.setattr(memory_llm, "_backoff", lambda attempt: None)
    monkeypatch.setenv("ZUMBA_LLM_ATTEMPTS", "2")
    assert memory_llm.chat_json("hi") is None


def test_chat_json_retries_transport_errors(monkeypatch):
    calls = []

    def boom_then_ok(prompt, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("connection reset")
        return '{"ok": 1}'

    monkeypatch.setattr(memory_llm, "chat_text", boom_then_ok)
    monkeypatch.setattr(memory_llm, "_backoff", lambda attempt: None)
    assert memory_llm.chat_json("hi") == {"ok": 1}


def test_reasoning_fallback_chain(monkeypatch):
    from knowledge import reasoning

    seen = []

    def fake_chat_json(prompt, model="", **kw):
        seen.append(model)
        if model == "primary/free":
            return None  # malformed -> next model
        return {"ok": True}

    monkeypatch.setattr(reasoning.memory_llm, "chat_json", fake_chat_json)
    monkeypatch.setattr(reasoning, "_memory_model", lambda: "primary/free")
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_FALLBACK", "second/free, primary/free")
    out = reasoning.chat_json("hi")
    assert out == {"ok": True}
    assert seen == ["primary/free", "second/free"]


def test_reasoning_error_lists_tried_models(monkeypatch):
    from knowledge import reasoning

    monkeypatch.setattr(reasoning.memory_llm, "chat_json", lambda *a, **k: None)
    monkeypatch.setattr(reasoning, "_memory_model", lambda: "only/free")
    monkeypatch.delenv("ZUMBA_KNOWLEDGE_FALLBACK", raising=False)
    try:
        reasoning.chat_json("hi")
    except ValueError as exc:
        assert "only/free" in str(exc)
        return
    raise AssertionError("should have raised")
