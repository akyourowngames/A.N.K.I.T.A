"""Tests for the persona layer (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from identity import persona
from identity.persona import DEFAULT_SYSTEM, build_system, resolve_chat_system


def test_composes_with_empty_config(monkeypatch):
    monkeypatch.setattr("core.store.config_get", lambda k, d="": d)
    out = build_system(DEFAULT_SYSTEM)
    assert "Zumba" in out
    assert DEFAULT_SYSTEM in out
    assert "Never say" in out


def test_style_pref_included(monkeypatch):
    monkeypatch.setattr("core.store.config_get", lambda k, d="": "terse, no greetings" if k == "style" else d)
    out = build_system()
    assert "terse, no greetings" in out


def test_flag_system_wins():
    assert resolve_chat_system("Custom sys", "") == "Custom sys"
    assert resolve_chat_system("Custom sys", "Saved sys") == "Custom sys"


def test_saved_system_wins_over_default():
    assert resolve_chat_system(DEFAULT_SYSTEM, "Saved sys") == "Saved sys"


def test_default_gets_persona(monkeypatch):
    monkeypatch.setattr("core.store.config_get", lambda k, d="": d)
    out = resolve_chat_system(DEFAULT_SYSTEM, "")
    assert "Zumba" in out and DEFAULT_SYSTEM in out


def test_tier2_profile_wired(monkeypatch, tmp_path):
    from identity import soul
    home = tmp_path / "phome"
    home.mkdir()
    monkeypatch.setenv("ZUMBA_HOME", str(home))
    monkeypatch.setattr(soul, "_home", lambda: home)
    monkeypatch.setattr("memory.llm.chat_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    soul.bootstrap_flow({"sound": "terse", "keep": "likes Rust"})
    monkeypatch.setattr("core.store.config_get", lambda k, d="": d)
    out = build_system(DEFAULT_SYSTEM)
    assert "soul.md" in out
    assert "user.md" in out or "likes Rust" in out
