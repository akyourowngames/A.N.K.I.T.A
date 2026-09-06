"""Tier 2 FEATURE S: soul.md self-authored identity (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import soul


def _isolate(tmp_path, monkeypatch):
    home = tmp_path / "zhome"
    home.mkdir()
    monkeypatch.setenv("ZUMBA_HOME", str(home))
    import store
    monkeypatch.setattr(store, "zumba_home", lambda: home)
    monkeypatch.setattr("soul._home", lambda: home)
    return home


def test_onboarding_triggers_once_then_skips(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert soul.needs_bootstrap() is True
    monkeypatch.setattr("memory.llm.chat_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    r = soul.bootstrap_flow({"sound": "terse", "keep": "builds robots", "boundaries": "none"})
    assert soul.exists() and soul.user_path().exists()
    assert soul.needs_bootstrap() is False
    assert r["soul_chars"] <= soul.SOUL_CAP


def test_injection_ordering_with_memory_block(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr("memory.llm.chat_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    soul.bootstrap_flow({"sound": "warm", "keep": "x", "off_limits": "y"})
    import persona
    monkeypatch.setattr("store.config_get", lambda k, d="": d)
    out = persona.build_system("base")
    soul_idx = out.find("soul.md")
    assert soul_idx != -1 and soul_idx < out.find("You are Zumba")
    assert "base" in out


def test_propose_accept_reject_lifecycle(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr("memory.llm.chat_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    soul.bootstrap_flow({"sound": "terse"})
    assert not soul.has_proposal()
    soul.propose_update(soul.load() + "\nExtra line.\n")
    assert soul.has_proposal()
    assert "soul.proposed.md" in soul.diff_proposed() or "Extra line" in soul.diff_proposed()
    assert soul.apply_proposal() is True
    assert not soul.has_proposal()
    assert "Extra line" in soul.load()
    soul.propose_update(soul.load() + "\nNope.\n")
    assert soul.reject_proposal() is True
    assert "Nope" not in soul.load()


def test_cap_enforcement(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    big = "# x\n" + ("word " * 2000)
    capped = soul.enforce_cap(big)
    assert len(capped) <= soul.SOUL_CAP + 100
    monkeypatch.setattr("memory.llm.chat_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    soul.bootstrap_flow({"sound": "terse"})
    soul.propose_update(big)
    soul.apply_proposal()
    assert len(soul.load()) <= soul.SOUL_CAP + 100


def test_user_md_companion_created(tmp_path, monkeypatch):
    home = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr("memory.llm.chat_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    soul.bootstrap_flow({"sound": "terse", "keep": "likes Rust"})
    text = (home / "user.md").read_text(encoding="utf-8")
    assert "likes Rust" in text
    assert "## Preferences" in text
