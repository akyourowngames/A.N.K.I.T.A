"""The new memory contract: original conversation, no inferred personal facts."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from memory.service import Memory


def test_plain_exchanges_survive_restart_without_enrichment(tmp_path):
    path = tmp_path / "ChatLog.json"
    mem = Memory(path=path)
    mem.capture_async("Launch is Friday.", "Understood.", "first")
    mem.capture_async("Actually, Monday.", "Monday it is.", "second")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [m["content"] for m in saved] == [
        "Launch is Friday.", "Understood.", "Actually, Monday.", "Monday it is."]
    assert [m["role"] for m in saved] == ["user", "assistant", "user", "assistant"]
    text = Memory(path=path).recall("launch")
    assert text.index("Launch is Friday.") < text.index("Actually, Monday.")
    assert set(p.name for p in tmp_path.iterdir()) == {"ChatLog.json", "ChatLog.lock"}


def test_recent_context_is_bounded_and_keeps_latest_correction(tmp_path):
    mem = Memory(path=tmp_path / "ChatLog.json", max_messages=6)
    for i in range(8):
        mem.capture_async(f"Old exchange {i}", "Details " * 300)
    mem.capture_async("Correction: Monday.", "Confirmed.")
    assert mem.stats()["messages"] == 6
    text = mem.recall("", max_bytes=200)
    assert len(text.encode("utf-8")) <= 200
    assert "Correction: Monday." in text
    assert "Old exchange 0" not in text


def test_concurrent_instances_do_not_lose_saves(tmp_path):
    path = tmp_path / "ChatLog.json"
    def save(i):
        Memory(path=path).capture_async(f"Message {i}", "OK")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save, range(15)))
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert {m["content"] for m in rows if m["role"] == "user"} == {f"Message {i}" for i in range(15)}


def test_clear_cannot_restore_old_queue_or_graph(tmp_path):
    path = tmp_path / "ChatLog.json"
    (tmp_path / "memory.db").write_bytes(b"old graph")
    (tmp_path / "memory-inbox.db").write_bytes(b"pending capture")
    (tmp_path / "user.md").write_text("Invented profile", encoding="utf-8")
    mem = Memory(path=path)
    assert mem.recall("profile") == ""
    mem.capture_async("Forget this.", "OK")
    mem.clear()
    assert Memory(path=path).recall("") == ""
    assert json.loads(path.read_text()) == []


def test_disabled_memory_never_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("ZUMBA_NO_MEMORY", "1")
    mem = Memory(path=tmp_path / "ChatLog.json")
    mem.capture_async("Private", "Reply")
    assert not mem.path.exists()
    assert mem.recall("") == ""


def test_corrupt_log_is_reported_without_overwriting_it(tmp_path):
    path = tmp_path / "ChatLog.json"
    path.write_text("broken json", encoding="utf-8")
    with pytest.raises(ValueError):
        Memory(path=path).capture_async("Hello", "Hi")
    assert path.read_text() == "broken json"


def test_default_persona_does_not_inject_derived_profiles(monkeypatch):
    from identity import persona
    monkeypatch.setattr(persona, "soul_block", lambda: "OLD SOUL")
    monkeypatch.setattr(persona, "user_block", lambda: "OLD PROFILE")
    monkeypatch.setattr("core.store.config_get", lambda key, default="": default)
    prompt = persona.build_system()
    assert "OLD SOUL" not in prompt and "OLD PROFILE" not in prompt
    assert "authoritative" not in prompt


def test_window_drops_old_history_without_summarizing(monkeypatch):
    from core import session_context, context_budget
    from core.models import Message
    def forbidden(*args, **kwargs):
        pytest.fail("Conversation memory must not call a summarizer")
    monkeypatch.setattr(context_budget, "_default_summarizer", forbidden)
    old = [Message(role="user", content="Old request " * 800) for _ in range(30)]
    latest = Message(role="user", content="Current request")
    result = session_context.fit([Message(role="system", content="System"), *old, latest], "test")
    assert result[-1].content == "Current request"
    assert sum(context_budget.message_tokens(m) for m in result) <= context_budget.get_context_limit() - 1500


def test_long_assistant_reply_cannot_hide_the_original_user_message(tmp_path):
    mem = Memory(path=tmp_path / "ChatLog.json")
    original = "My birthday is in June. " + "More details " * 1000
    mem.capture_async(original, "Long answer " * 1500)
    assert mem.messages()[0]["content"] == original
    assert "My birthday is in June." in mem.recall("", max_bytes=4000)


def test_forget_removes_both_messages_by_exchange_id(tmp_path):
    mem = Memory(path=tmp_path / "ChatLog.json")
    saved = mem.capture_async("Delete me", "Reply")
    mem.capture_async("Keep me", "Other reply")
    assert saved["id"] in mem.recall("")
    assert mem.forget(saved["id"])["forgot"]
    assert "Delete me" not in mem.recall("")
    assert "Keep me" in mem.recall("")


def test_oversized_current_message_is_rejected_before_model_call():
    from core.models import Message
    from core.session_context import fit
    with pytest.raises(ValueError, match="too long"):
        fit([Message(role="system", content="System"), Message(role="user", content="x" * 50000)])
