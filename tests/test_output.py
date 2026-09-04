from output import emoji_supported, is_modern_terminal, remove_emoji_only, strip_emoji
import os


def test_strip_emoji_removes():
    assert "hello" in strip_emoji("hello \U0001F60A world")
    assert "\U0001F60A" not in strip_emoji("hi \U0001F60A")


def test_strip_plain_unchanged():
    assert strip_emoji("plain text") == "plain text"


def test_remove_emoji_only_preserves_spaces():
    assert remove_emoji_only("Hello ") == "Hello "
    assert remove_emoji_only(" nice") == " nice"
    assert remove_emoji_only("Hey \U0001F60A there") == "Hey  there"
    assert "can I help" in remove_emoji_only("can I help")


def test_env_forces(monkeypatch):
    monkeypatch.setenv("ZUMBA_NO_EMOJI", "1")
    monkeypatch.delenv("ZUMBA_FORCE_EMOJI", raising=False)
    assert not is_modern_terminal()
    assert not emoji_supported()
    monkeypatch.delenv("ZUMBA_NO_EMOJI", raising=False)
    monkeypatch.setenv("ZUMBA_FORCE_EMOJI", "1")
    assert is_modern_terminal()
