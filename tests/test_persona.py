"""Tests for the persona layer (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import persona
from persona import DEFAULT_SYSTEM, build_system, resolve_chat_system


def test_composes_with_empty_config(monkeypatch):
    monkeypatch.setattr("store.config_get", lambda k, d="": d)
    out = build_system(DEFAULT_SYSTEM)
    assert "Zumba" in out
    assert DEFAULT_SYSTEM in out
    assert "Never say" in out


def test_style_pref_included(monkeypatch):
    monkeypatch.setattr("store.config_get", lambda k, d="": "terse, no greetings" if k == "style" else d)
    out = build_system()
    assert "terse, no greetings" in out


def test_flag_system_wins():
    assert resolve_chat_system("Custom sys", "") == "Custom sys"
    assert resolve_chat_system("Custom sys", "Saved sys") == "Custom sys"


def test_saved_system_wins_over_default():
    assert resolve_chat_system(DEFAULT_SYSTEM, "Saved sys") == "Saved sys"


def test_default_gets_persona(monkeypatch):
    monkeypatch.setattr("store.config_get", lambda k, d="": d)
    out = resolve_chat_system(DEFAULT_SYSTEM, "")
    assert "Zumba" in out and DEFAULT_SYSTEM in out


def test_tier2_marker_present():
    src = Path(__file__).resolve().parent.parent / "persona.py"
    assert "TODO(tier2-profile)" in src.read_text(encoding="utf-8")
