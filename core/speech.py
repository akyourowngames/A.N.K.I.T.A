"""Shared local speech recognition, with an explicitly configured cloud fallback.

Models must be cached, or downloaded explicitly with desktop/mic_test.py.
Imports and model loading are lazy so text-only startup stays inexpensive.
"""
from __future__ import annotations

import io
import os
import threading
from contextlib import contextmanager
from importlib.util import find_spec

SAMPLE_RATE = 16000
MAX_SECONDS = 60
MAX_BYTES = 10 * 1024 * 1024
_model = None
_model_key = None
_load_lock = threading.Lock()
_inference_lock = threading.Lock()


class STTUnavailable(RuntimeError):
    pass


class InvalidAudio(ValueError):
    pass


def language(value=None):
    value = (value if value is not None else os.getenv('ZUMBA_STT_LANG', 'auto')).strip().lower()
    return None if value in ('', 'auto') else value.replace('_', '-').split('-')[0]


def allowed_languages():
    """Optional user-configured language codes for automatic audio detection."""
    return list(dict.fromkeys(code for item in os.getenv('ZUMBA_STT_LANGUAGES', '').split(',')
                              if (code := language(item))))


def diagnostics():
    return {'engine': 'faster-whisper (local CPU)',
            'model': os.getenv('ZUMBA_STT_MODEL', 'tiny'),
            'language': language() or 'auto',
            'auto_languages': allowed_languages() or 'all',
            'microphone': os.getenv('ZUMBA_MIC_DEVICE') or 'system default (sounddevice)',
            'faster_whisper_installed': find_spec('faster_whisper') is not None,
            'sounddevice_installed': find_spec('sounddevice') is not None,
            'offline': not bool(os.getenv('ZUMBA_STT_CLOUD_URL')),
            'cloud_fallback_configured': bool(os.getenv('ZUMBA_STT_CLOUD_URL')),
            'test': 'python desktop/mic_test.py --file recording.wav'}


def _get_model():
    global _model, _model_key
    key = os.getenv('ZUMBA_STT_MODEL', 'tiny')
    with _load_lock:
        if _model is None or key != _model_key:
            try:
                from core.speech_process import WhisperProcess
                if _model is not None:
                    _model.close()
                _model = WhisperProcess(key)
                _model_key = key
            except Exception as exc:
                raise STTUnavailable('Local STT unavailable. Install requirements-desktop.txt '
                    'and run python desktop/mic_test.py --download-model. ' + str(exc)) from exc
    return _model


@contextmanager
def _inference(abort=None):
    while not _inference_lock.acquire(timeout=.05):
        if abort is not None and abort.is_set():
            raise STTUnavailable('Speech recognition cancelled.')
    try:
        if abort is not None and abort.is_set():
            raise STTUnavailable('Speech recognition cancelled.')
        yield
    finally:
        _inference_lock.release()


def prepare(abort=None):
    with _inference(abort):
        _get_model().prepare(abort=abort)


def _decode(data):
    import numpy as np
    if isinstance(data, np.ndarray):
        samples = np.asarray(data, dtype=np.float32)
        if samples.ndim != 1:
            raise InvalidAudio('Expected mono 16 kHz audio.')
    else:
        if not data or len(data) > MAX_BYTES:
            raise InvalidAudio('Audio must be between 1 byte and 10 MB.')
        try:
            import av
            chunks, size = [], 0
            resampler = av.AudioResampler(format='fltp', layout='mono', rate=SAMPLE_RATE)
            with av.open(io.BytesIO(data)) as container:
                for frame in container.decode(audio=0):
                    for output in resampler.resample(frame):
                        chunk = output.to_ndarray().reshape(-1)
                        size += len(chunk)
                        if size > SAMPLE_RATE * MAX_SECONDS:
                            raise InvalidAudio('Audio exceeds 60 seconds.')
                        chunks.append(chunk)
                for output in resampler.resample(None):
                    chunks.append(output.to_ndarray().reshape(-1))
            samples = np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)
        except InvalidAudio:
            raise
        except Exception as exc:
            raise InvalidAudio('Cannot decode audio. Upload WAV, WebM, Ogg, MP3 or MP4 audio.') from exc
    if len(samples) > SAMPLE_RATE * MAX_SECONDS:
        raise InvalidAudio('Audio exceeds 60 seconds.')
    if not len(samples) or not np.isfinite(samples).all():
        raise InvalidAudio('Audio is empty or invalid.')
    return samples


def _transcribe_local(data, *, lang=None, on_partial=None, abort=None):
    import numpy as np
    samples = _decode(data)
    result = {'transcript': '', 'language': language(lang) or 'auto'}
    if np.max(np.abs(samples)) < .003 or (abort is not None and abort.is_set()):
        return result
    with _inference(abort):
        model = _get_model()
        if abort is not None and abort.is_set():
            return result
        try:
            segments, info = model.transcribe(samples, language=language(lang), task='transcribe',
                beam_size=1, vad_filter=False, condition_on_previous_text=False, abort=abort)
            parts = []
            for segment in segments:
                if abort is not None and abort.is_set():
                    if hasattr(model, 'close'):
                        model.close()
                    return {'transcript': '', 'language': result['language']}
                text = segment.text.strip()
                if text:
                    parts.append(text)
                    if on_partial:
                        on_partial(' '.join(parts))
            result.update(transcript=' '.join(parts), language=info.language)
        except Exception as exc:
            if hasattr(model, 'close'):
                model.close()
            raise STTUnavailable('Local speech recognition failed: ' + str(exc)) from exc
    return result


def transcribe(data, *, lang=None, on_partial=None, abort=None):
    """Use local inference first. No cloud requests unless a fallback URL is set."""
    try:
        return _transcribe_local(data, lang=lang, on_partial=on_partial, abort=abort)
    except STTUnavailable:
        if abort is not None and abort.is_set():
            return {'transcript': '', 'language': language(lang) or 'auto'}
        endpoint = os.getenv('ZUMBA_STT_CLOUD_URL', '').strip()
        if not endpoint:
            raise
        # The same duration/format limits apply to fallback audio.
        import wave
        import numpy as np
        import requests
        samples = _decode(data)
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
        fields = {'model': os.getenv('ZUMBA_STT_CLOUD_MODEL', 'whisper-1')}
        if language(lang):
            fields['language'] = language(lang)
        token = os.getenv('ZUMBA_STT_CLOUD_KEY', '')
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        try:
            response = requests.post(endpoint, headers=headers, data=fields,
                files={'file': ('audio.wav', output.getvalue(), 'audio/wav')}, timeout=(5, 30))
            response.raise_for_status()
            body = response.json()
            text = body.get('text')
            if not isinstance(text, str):
                raise ValueError('Missing transcription text')
            if abort is not None and abort.is_set():
                return {'transcript': '', 'language': language(lang) or 'auto'}
            if text and on_partial:
                on_partial(text.strip())
            return {'transcript': text.strip(), 'language': body.get('language') or language(lang) or 'auto',
                    'engine': 'configured cloud fallback'}
        except Exception as exc:
            raise STTUnavailable('Local STT and configured cloud fallback failed.') from exc
