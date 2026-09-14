import io
import threading
from types import SimpleNamespace

import numpy as np
import pytest


def test_local_transcription_language_segments_and_silence(monkeypatch):
    from core import speech
    calls = []
    class Model:
        def transcribe(self, audio, **kwargs):
            calls.append(kwargs)
            return iter([SimpleNamespace(text=' Hello world.', start=0, end=2)]), SimpleNamespace(language='en')
    monkeypatch.setattr(speech, '_get_model', lambda: Model())
    monkeypatch.setenv('ZUMBA_STT_LANG', 'en-US')
    partials = []
    assert speech.transcribe(np.ones(16000, dtype=np.float32), on_partial=partials.append)['transcript'] == 'Hello world.'
    assert partials == ['Hello world.']
    assert calls[0]['language'] == 'en'
    assert speech.transcribe(np.zeros(96000, dtype=np.float32))['transcript'] == ''
    assert len(calls) == 1


def test_audio_limits_and_invalid_input():
    from core import speech
    with pytest.raises(speech.InvalidAudio):
        speech.transcribe(b'not an audio file')
    with pytest.raises(speech.InvalidAudio):
        speech.transcribe(np.ones(speech.SAMPLE_RATE * (speech.MAX_SECONDS + 1), dtype=np.float32))


def test_auto_language_uses_audio_model_within_user_language_choices():
    from core.speech_worker import recognize
    calls = []
    class Model:
        def transcribe(self, samples, language=None, **kwargs):
            calls.append(language)
            return iter([]), SimpleNamespace(language=language or 'pt',
                all_language_probs=[('pt', .7), ('hi', .2), ('en', .1)])
    _, info = recognize(Model(), np.ones(16000), languages=['hi', 'en'])
    assert info.language == 'hi'
    assert calls == [None, 'hi']
    calls.clear()
    _, info = recognize(Model(), np.ones(16000), language='en', languages=['hi', 'en'])
    assert calls == ['en']


def test_microphone_speech_onset_and_release(monkeypatch):
    from desktop.stt import LocalSTT
    from core import speech
    closed, onset = [], []
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
        def __enter__(self):
            for level in [0, .1, .1, .1, .1] + [0] * 30:
                self.callback(np.full((480, 1), level, np.float32), 480, None, None)
            return self
        def __exit__(self, *args):
            closed.append(True)
    import sounddevice
    monkeypatch.setattr(sounddevice, 'InputStream', Stream)
    monkeypatch.setattr(sounddevice, 'query_devices', lambda *a, **kw: {'name': 'Test mic'})
    monkeypatch.setattr(speech, 'prepare', lambda **kw: None)
    monkeypatch.setattr(speech, 'transcribe', lambda *args, **kwargs: {'transcript': 'hello'})
    stt = LocalSTT()
    assert stt.listen_once(timeout=.3, on_speech=lambda: onset.append(True)) == 'hello'
    assert onset == [True]
    assert closed == [True]
    stop = threading.Event()
    stop.set()
    assert stt.listen_once(abort=stop) == ''


def test_quiet_speech_is_transcribed_once_after_capture_closes(monkeypatch):
    from desktop.stt import LocalSTT
    from core import speech
    import sounddevice
    stages, levels, calls = [], [], []
    opened = []
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
        def __enter__(self):
            opened.append(True)
            # Quiet speech below the old .012 gate, with brief gaps, then a pause.
            for level in [.0003] * 10 + [.006, .0003, .006, .006] + [.006] * 80 + [0] * 35:
                self.callback(np.full((480, 1), level, np.float32), 480, None, None)
            return self
        def __exit__(self, *args):
            opened.clear()
    def transcribe(samples, **kwargs):
        assert not opened, 'Recognition must not compete with microphone capture'
        assert stages[-1] == 'transcribing'
        calls.append(len(samples))
        return {'transcript': 'quiet question'}
    monkeypatch.delenv('ZUMBA_VAD_THRESHOLD', raising=False)
    monkeypatch.setattr(sounddevice, 'InputStream', Stream)
    monkeypatch.setattr(sounddevice, 'query_devices', lambda *a, **kw: {'name': 'Test default mic'})
    monkeypatch.setattr(speech, 'prepare', lambda **kw: None)
    monkeypatch.setattr(speech, 'transcribe', transcribe)
    assert LocalSTT().listen_once(timeout=2, on_interim=lambda text: None,
        on_stage=lambda stage, text: stages.append(stage),
        on_audio=lambda *args: levels.append(args)) == 'quiet question'
    assert len(calls) == 1
    assert stages.index('loading') < stages.index('listening') < stages.index('recording') < stages.index('transcribing')
    assert levels and max(row[0] for row in levels) >= .005


def test_microphone_silence_never_runs_recognition(monkeypatch):
    from desktop.stt import LocalSTT
    from core import speech
    import sounddevice
    stages = []
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
        def __enter__(self):
            for _ in range(20):
                self.callback(np.zeros((480, 1), np.float32), 480, None, None)
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(sounddevice, 'InputStream', Stream)
    monkeypatch.setattr(sounddevice, 'query_devices', lambda *a, **kw: {'name': 'Test mic'})
    monkeypatch.setattr(speech, 'prepare', lambda **kw: None)
    monkeypatch.setattr(speech, 'transcribe', lambda *a, **kw: pytest.fail('Transcribed silence'))
    assert LocalSTT().listen_once(timeout=.05, on_stage=lambda stage, text: stages.append(stage)) == ''
    assert stages[-1] == 'no_speech'


def test_manual_finish_sends_captured_speech_without_waiting_for_silence(monkeypatch):
    from desktop.stt import LocalSTT
    from core import speech
    import sounddevice
    finish = threading.Event()
    lengths = []
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
        def __enter__(self):
            for _ in range(100):
                self.callback(np.full((480, 1), .02, np.float32), 480, None, None)
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(sounddevice, 'InputStream', Stream)
    monkeypatch.setattr(sounddevice, 'query_devices', lambda *a, **kw: {'name': 'Test mic'})
    monkeypatch.setattr(speech, 'prepare', lambda **kw: None)
    def recognize(samples, **kwargs):
        lengths.append(len(samples))
        return {'transcript': 'send now'}
    monkeypatch.setattr(speech, 'transcribe', recognize)
    def meter(level, threshold, seconds):
        if seconds >= .3:
            finish.set()
    assert LocalSTT().listen_once(timeout=2, finish=finish, on_audio=meter) == 'send now'
    assert speech.SAMPLE_RATE * .3 <= lengths[0] < speech.SAMPLE_RATE * .5


def test_brief_pause_within_a_question_does_not_cut_off_the_rest(monkeypatch):
    from desktop.stt import LocalSTT
    from core import speech
    import sounddevice
    lengths = []
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
        def __enter__(self):
            for level in [.02] * 20 + [0] * 28 + [.02] * 20 + [0] * 40:
                self.callback(np.full((480, 1), level, np.float32), 480, None, None)
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(sounddevice, 'InputStream', Stream)
    monkeypatch.setattr(sounddevice, 'query_devices', lambda *a, **kw: {'name': 'Test mic'})
    monkeypatch.setattr(speech, 'prepare', lambda **kw: None)
    def recognize(samples, **kwargs):
        lengths.append(len(samples))
        return {'transcript': 'whole question'}
    monkeypatch.setattr(speech, 'transcribe', recognize)
    assert LocalSTT().listen_once(timeout=.2) == 'whole question'
    assert lengths[0] >= 68 * 480, 'Recognition cut off speech after a brief pause'


def test_stt_endpoint_returns_transcript_and_rejects_bad_audio(monkeypatch):
    from fastapi.testclient import TestClient
    from core import speech
    from server.app import app
    client = TestClient(app)
    monkeypatch.setattr(speech, 'transcribe', lambda data, **kw: {'transcript': 'hello', 'language': 'en'})
    response = client.post('/api/voice/stt', files={'file': ('audio.wav', b'audio', 'audio/wav')})
    assert response.status_code == 200
    assert response.json()['transcript'] == 'hello'
    assert client.post('/api/voice/stt', files={'file': ('empty.wav', b'', 'audio/wav')}).status_code == 400
    def broken(*args, **kwargs):
        raise speech.STTUnavailable('model missing')
    monkeypatch.setattr(speech, 'transcribe', broken)
    assert client.post('/api/voice/stt', files={'file': ('a.wav', b'audio')}).status_code == 503


def test_streaming_and_websocket_emit_real_partial_and_final(monkeypatch):
    import base64
    from fastapi.testclient import TestClient
    from core import speech
    from server.app import app
    def recognize(data, on_partial=None, **kwargs):
        assert data == b'audio'
        on_partial('hello')
        return {'transcript': 'hello world', 'language': 'en'}
    monkeypatch.setattr(speech, 'transcribe', recognize)
    client = TestClient(app)
    response = client.post('/api/voice/stt?stream=true', files={'file': ('a.wav', b'audio')})
    assert 'event: partial' in response.text
    assert 'event: done' in response.text
    assert 'hello world' in response.text
    with client.websocket_connect('/ws/voice') as ws:
        assert ws.receive_json()['type'] == 'ready'
        ws.send_json({'audio_chunk_b64': base64.b64encode(b'audio').decode(), 'finish': True})
        assert ws.receive_json()['type'] == 'start'
        assert ws.receive_json() == {'type': 'partial', 'transcript': 'hello'}
        assert ws.receive_json()['transcript'] == 'hello world'
        ws.send_json({'audio_chunk_b64': 'not base64!'})
        assert ws.receive_json()['type'] == 'error'


def test_cloud_fallback_requires_explicit_configuration(monkeypatch):
    import requests
    from core import speech
    def unavailable():
        raise speech.STTUnavailable('missing model')
    monkeypatch.setattr(speech, '_get_model', unavailable)
    monkeypatch.delenv('ZUMBA_STT_CLOUD_URL', raising=False)
    sent = []
    def post(url, **kwargs):
        sent.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'text': 'fallback text'})
    monkeypatch.setattr(requests, 'post', post)
    audio = np.ones(16000, dtype=np.float32)
    with pytest.raises(speech.STTUnavailable):
        speech.transcribe(audio)
    assert not sent
    monkeypatch.setenv('ZUMBA_STT_CLOUD_URL', 'https://example.test/transcriptions')
    assert speech.transcribe(audio)['transcript'] == 'fallback text'
    assert sent[0][1]['files']['file'][1].startswith(b'RIFF')


def test_native_worker_failure_becomes_recoverable_error():
    import queue
    from core.speech import STTUnavailable
    from core.speech_process import WhisperProcess
    worker = WhisperProcess('tiny')
    worker.events = queue.Queue()
    worker.events.put({'type': 'error', 'error': 'native worker crashed'})
    with pytest.raises(STTUnavailable, match='native worker crashed'):
        worker._next()
    assert worker.process is None


def test_worker_cancellation_is_an_empty_transcript(monkeypatch):
    from core import speech
    stop = threading.Event()
    def cancelled(*args, **kwargs):
        stop.set()
        raise speech.STTUnavailable('cancelled')
    monkeypatch.setattr(speech, '_transcribe_local', cancelled)
    assert speech.transcribe(np.ones(16000), abort=stop)['transcript'] == ''


@pytest.mark.skipif(__import__('os').getenv('ZUMBA_TEST_LOCAL_STT') != '1', reason='opt-in cached model integration')
def test_six_second_fixture_offline(monkeypatch):
    import wave
    from pathlib import Path
    from core import speech
    monkeypatch.delenv('ZUMBA_STT_CLOUD_URL', raising=False)
    path = Path(__file__).parent / 'fixtures' / 'stt-six-seconds.wav'
    with wave.open(str(path)) as wav:
        assert wav.getnframes() / wav.getframerate() == 6
    result = speech.transcribe(path.read_bytes(), lang='en')
    assert 'please tell me what time it is' in result['transcript'].lower()
