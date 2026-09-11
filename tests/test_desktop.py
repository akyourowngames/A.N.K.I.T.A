import os
import threading
import time

from desktop.brain import VoiceController
from desktop.state import DesktopBus


class FakeSTT:
    def __init__(self, script=(), lang="en"):
        self.script = list(script)
        self.calls = 0
        self.lang = lang
        self.interim_calls = []

    def listen_once(self, timeout=30.0, abort=None, on_interim=None, poll=0.4):
        self.calls += 1
        if abort is not None and abort.is_set():
            return ""
        if not self.script:
            return ""
        if on_interim is not None:
            on_interim("partial...")
            self.interim_calls.append("partial...")
        return self.script.pop(0)


class FakeSpeaker:
    """Slow speaker that honors the stop event like the real pygame loop."""

    def __init__(self, seconds=3.0):
        self.seconds = seconds
        self.spoken = []
        self.summarize_flags = []

    def speak(self, text, stop_event=None, summarize=True):
        self.spoken.append(text)
        self.summarize_flags.append(summarize)
        deadline = time.monotonic() + self.seconds
        while time.monotonic() < deadline:
            if stop_event is not None and stop_event.is_set():
                return False
            time.sleep(0.02)
        return True


def _controller(**kw):
    bus = DesktopBus()
    kw.setdefault("answer_fn", lambda sid, q: f"echo:{q}")
    kw.setdefault("speaker", FakeSpeaker(seconds=0.01))
    kw.setdefault("stt", FakeSTT())
    return bus, VoiceController(bus, **kw)


def test_normal_query_posts_full_answer_and_speaks():
    bus, ctl = _controller()
    ctl.handle_query("hello there")
    messages = bus.drain_messages()
    assert messages[0] == "Sir : hello there"
    assert messages[1] == "Zumba : echo:hello there"
    assert ctl._speaker.spoken == ["echo:hello there"]
    assert bus.get_status() == "Available..."


def test_stop_command_requests_stop():
    bus, ctl = _controller()
    ctl.handle_query("please stop talking")
    assert bus.stop_requested()
    assert any("Stopped." in m for m in bus.drain_messages())


def test_exit_command_farewells_and_closes():
    bus, ctl = _controller()
    ctl.handle_query("bye zumba, exit now")
    assert bus.shutdown_requested()
    assert ctl._speaker.spoken  # farewell spoken before close


def test_barge_in_keyword_interrupts_speech():
    bus = DesktopBus()
    ctl = VoiceController(
        bus,
        answer_fn=lambda sid, q: "a long answer worth interrupting",
        speaker=FakeSpeaker(seconds=5.0),
        stt=FakeSTT(script=["stop"]),  # barge-in watcher hears this mid-speech
    )
    # Full path through _speak (watcher + speaker race the stop event).
    ctl._speak("a long answer worth interrupting")
    assert bus.stop_requested()
    assert bus.get_status() == "Available..."


def test_hindi_turn_translates_before_answering(monkeypatch):
    import desktop.translate as translate_mod

    bus = DesktopBus()
    heard_english = []
    ctl = VoiceController(
        bus,
        answer_fn=lambda sid, q: heard_english.append(q) or "ok",
        speaker=FakeSpeaker(seconds=0.01),
        stt=FakeSTT(script=["namaste, samay kya hai"], lang="hi"),
    )
    monkeypatch.setattr(translate_mod, "to_english", lambda text, lang="hi": "hello, what is the time")
    # Route the brain's lazy import through the patched module.
    import desktop.brain as brain_mod

    monkeypatch.setitem(__import__("sys").modules, "desktop.translate", translate_mod)
    bus.set_mic(True)
    ctl._listen_turn()
    assert heard_english == ["hello, what is the time"]
    assert any("hello, what is the time" in m for m in bus.drain_messages())


def test_translation_helpers():
    from desktop.translate import needs_translation, to_english

    assert needs_translation("en-US") is False
    assert needs_translation("hi") is True
    assert to_english("hello", "en-US") == "hello"
    # Broken translator falls back to the original text.
    import sys as _sys

    class _Boom:
        @staticmethod
        def translate(*args, **kwargs):
            raise RuntimeError("offline")

    monkeypatched = _sys.modules.get("mtranslate")
    _sys.modules["mtranslate"] = _Boom
    try:
        assert to_english("namaste", "hi") == "namaste"
    finally:
        if monkeypatched is not None:
            _sys.modules["mtranslate"] = monkeypatched
        else:
            del _sys.modules["mtranslate"]


def test_stt_does_not_use_fake_audio_device():
    import pathlib

    src = pathlib.Path("desktop/stt.py").read_text(encoding="utf-8")
    assert "add_argument(\"--use-fake-device-for-media-stream\")" not in src
    assert "--use-fake-ui-for-media-stream" in src  # auto-grant stays
    from desktop import stt as stt_mod

    assert "interimResults = true" in stt_mod.HTML_PAGE


def test_gui_offscreen_renders_and_submits():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        return  # desktop GUI deps not installed; brain tests above still ran
    from desktop.gui import MainWindow

    app = QApplication.instance() or QApplication([])
    bus = DesktopBus()
    submitted = []
    window = MainWindow(bus, submitted.append)
    bus.post_message("Zumba : Online.")
    bus.set_status("Listening...")
    window._refresh()
    assert "Online." in window.chat.chat.toPlainText()
    assert window.chat.status.text() == "Listening..."
    assert window.home.status.text() == "Listening..."

    window.home.toggle_mic()
    assert bus.mic_on() is True
    window.home.toggle_mic()
    assert bus.mic_on() is False

    window.chat.input.setText("typed hello")
    window.chat._submit()
    deadline = time.monotonic() + 5
    while not submitted and time.monotonic() < deadline:
        time.sleep(0.05)
    assert submitted == ["typed hello"]
    window.close()
