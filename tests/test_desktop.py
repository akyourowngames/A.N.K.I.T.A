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

    def listen_once(self, timeout=30.0, abort=None, on_interim=None, poll=0.4, on_speech=None, on_ready=None, **kwargs):
        self.calls += 1
        if abort is not None and abort.is_set():
            return ""
        if on_ready:
            on_ready()
        if not self.script:
            return ""
        if on_speech:
            on_speech()
        if on_interim is not None:
            on_interim("partial...")
            self.interim_calls.append("partial...")
        return self.script.pop(0)

    def close(self):
        pass


class FakeSpeaker:
    """Slow speaker that honors the stop event like the real pygame loop."""

    def __init__(self, seconds=3.0):
        self.seconds = seconds
        self.spoken = []
        self.summarize_flags = []

    def speak(self, text, stop_event=None, summarize=True, **kwargs):
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
    kw.setdefault("intent_fn", lambda text, wake: {"action": "respond", "text": text})
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
    ctl.handle_query("/stop")
    assert bus.stop_requested()


def test_exit_command_farewells_and_closes():
    bus, ctl = _controller()
    ctl.handle_query("/exit")
    assert bus.shutdown_requested()
    assert any("Goodbye" in m for m in bus.drain_messages())


def test_barge_in_speech_activity_interrupts_and_keeps_utterance():
    bus = DesktopBus()
    bus.set_mic(True)
    ctl = VoiceController(
        bus,
        answer_fn=lambda sid, q: "a long answer worth interrupting",
        speaker=FakeSpeaker(seconds=5.0),
        stt=FakeSTT(script=["I have another question"]),
        barge_in=True,
    )
    # Full path through _speak (watcher + speaker race the stop event).
    ctl._speak("a long answer worth interrupting")
    assert bus.stop_requested()
    assert bus.get_status() == "Available..."
    assert ctl._pending.get_nowait() == "I have another question"
    assert not ctl._barge_thread.is_alive()


def test_hindi_turn_preserves_original_language():
    bus = DesktopBus()
    heard_english = []
    ctl = VoiceController(
        bus,
        answer_fn=lambda sid, q: heard_english.append(q) or "ok",
        speaker=FakeSpeaker(seconds=0.01),
        stt=FakeSTT(script=["namaste, samay kya hai"], lang="hi"),
        intent_fn=lambda text, wake: {"action": "respond", "text": text},
    )
    bus.set_mic(True)
    ctl._listen_turn()
    assert heard_english == ["namaste, samay kya hai"]
    assert any("namaste, samay kya hai" in m for m in bus.drain_messages())


def test_voice_classifier_cannot_replace_user_question_with_answer():
    for question, invented in [('How are you?', "I'm doing well, thank you!"),
                               ('Who made you?', 'I was created by researchers at NVIDIA.'),
                               ('Who are you?', 'I am an AI assistant.')]:
        queries = []
        bus, ctl = _controller(stt=FakeSTT([question]),
            answer_fn=lambda sid, text: queries.append(text) or 'answer',
            intent_fn=lambda text, wake: {'action': 'respond', 'text': invented})
        bus.set_mic(True)
        ctl._listen_turn()
        assert queries == [question]
        assert bus.drain_messages()[0] == 'Sir : ' + question


def test_voice_gate_exposes_actions_only(monkeypatch):
    from core import api_client, config
    from core.models import ChatResult
    from desktop.brain import voice_intent
    monkeypatch.setattr(config, 'get_api_key', lambda **kw: 'test-key')
    monkeypatch.setattr(api_client, 'chat_completion', lambda *a, **kw:
        ChatResult(content='{"action":"respond","text":"invented answer"}'))
    assert voice_intent('Who are you?') == {'action': 'respond'}


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


def test_normal_questions_do_not_trigger_substring_commands():
    bus, ctl = _controller()
    ctl.handle_query("Why do trains stop and how does sleep work?")
    assert not bus.shutdown_requested()
    assert any("echo:" in text for text in bus.drain_messages())


def test_wake_mode_uses_semantic_gate():
    bus, ctl = _controller(stt=FakeSTT(['a television conversation']), wake_word='Hey Ankita',
                           intent_fn=lambda text, wake: {'action': 'ignore'})
    bus.set_mic(True)
    ctl._listen_turn()
    assert not bus.drain_messages()


def test_spoken_exit_uses_semantic_gate():
    bus, ctl = _controller(stt=FakeSTT(['please close the assistant']),
                           intent_fn=lambda text, wake: {'action': 'exit'})
    bus.set_mic(True)
    ctl._listen_turn()
    assert bus.shutdown_requested()


def test_idle_barge_listener_cancelled_when_speaker_finishes():
    cancelled = threading.Event()
    class ListeningSTT(FakeSTT):
        def listen_once(self, abort=None, **kwargs):
            while not abort.is_set():
                time.sleep(.01)
            cancelled.set()
            return ''
    bus, ctl = _controller(stt=ListeningSTT(), barge_in=True)
    bus.set_mic(True)
    ctl._speak('short reply')
    assert cancelled.is_set()
    assert not ctl._barge_thread.is_alive()


def test_shutdown_cancels_active_microphone():
    bus, ctl = _controller()
    ctl.shutdown()
    assert bus.shutdown_requested()
    assert bus.stop_requested()


def test_fast_mute_unmute_discards_the_previous_capture():
    cancelled = []
    class RacingSTT(FakeSTT):
        def listen_once(self, abort=None, **kwargs):
            bus.set_mic(False)
            bus.set_mic(True)
            cancelled.append(abort.is_set())
            return 'stale recording'
    bus, ctl = _controller(stt=RacingSTT())
    bus.set_mic(True)
    ctl._listen_turn()
    assert cancelled == [True]
    assert bus.drain_messages() == []


def test_empty_recognition_and_playback_errors_remain_diagnosable():
    bus, ctl = _controller()
    bus.set_mic(True)
    ctl._listen_turn()
    assert bus.snapshot()['stage'] == 'no_speech'
    class BrokenSpeaker:
        def speak(self, *args, **kwargs):
            raise RuntimeError('output disconnected')
    ctl._speaker = BrokenSpeaker()
    ctl.handle_query('hello')
    assert 'output disconnected' in bus.snapshot()['last_error']
    assert any('output disconnected' in line for line in bus.snapshot()['events'])


def test_muting_releases_capture_state_and_preserves_debug_history():
    bus = DesktopBus()
    bus.set_mic(True)
    bus.set_stage('listening', 'Listening — speak now')
    bus.set_capture(True)
    bus.set_audio(.02, .003, 1.2)
    bus.set_mic(False)
    state = bus.snapshot()
    assert not state['mic_on'] and not state['capture_active']
    assert state['stage'] == 'muted'
    assert state['level'] == 0
    assert any('Listening' in event for event in state['events'])


def test_stop_cancels_speech_download_and_removes_temporary_audio(monkeypatch, tmp_path):
    import asyncio
    import sys
    import types
    import tempfile
    from desktop.tts import Speaker
    stopped = threading.Event()
    cancelled = []
    output = tmp_path / 'speech.mp3'
    class Communicate:
        def __init__(self, *a, **kw):
            pass
        async def save(self, path):
            try:
                stopped.set()
                await asyncio.sleep(10)
            finally:
                cancelled.append(True)
    monkeypatch.setitem(sys.modules, 'edge_tts', types.SimpleNamespace(Communicate=Communicate))
    monkeypatch.setitem(sys.modules, 'pygame', types.SimpleNamespace())
    monkeypatch.setattr(tempfile, 'mkstemp', lambda **kw: (os.open(output, os.O_CREAT | os.O_WRONLY), str(output)))
    assert Speaker().speak('hello', stop_event=stopped) is False
    assert cancelled == [True]
    assert not output.exists()


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
    assert window.voice.status.text().startswith('Listening...')

    window.home.toggle_mic()
    assert bus.mic_on() is True
    window.home.toggle_mic()
    assert bus.mic_on() is False
    window.resize(1280, 720)
    window.show()
    app.processEvents()
    for index in (0, 1):
        window.stacked.setCurrentIndex(index)
        window._refresh()
        app.processEvents()
        assert window.voice.mic.isVisible()
        assert window.voice.mic.text() == 'MIC OFF · Enable'
        assert window.voice.geometry().bottom() <= window.centralWidget().height()
        window.voice.mic.click()
        window._refresh()
        assert bus.mic_on() and window.voice.mic.text() == 'MIC ON · Mute'
        window.voice.mic.click()

    window.chat.input.setText("typed hello")
    window.chat._submit()
    deadline = time.monotonic() + 5
    while not submitted and time.monotonic() < deadline:
        time.sleep(0.05)
    assert submitted == ["typed hello"]
    window.close()
