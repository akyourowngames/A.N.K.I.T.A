"""Local microphone capture with energy VAD and faster-whisper transcription."""
from __future__ import annotations

import collections
import os
import queue
import threading
import time

from core import speech
from core.speech import STTUnavailable


class _Abort:
    def __init__(self, closed, external):
        self.closed, self.external = closed, external

    def is_set(self):
        return self.closed.is_set() or (self.external is not None and self.external.is_set())


class LocalSTT:
    """One microphone owner. Speech onset interrupts before recognition finishes."""

    def __init__(self, lang=None, device=None):
        self.lang = speech.language(lang)
        selected = device if device is not None else os.getenv("ZUMBA_MIC_DEVICE")
        self.device = int(selected) if selected and str(selected).isdigit() else selected or None
        self._lock = threading.Lock()
        self._closed = threading.Event()

    def listen_once(self, timeout=30.0, abort=None, poll=.03,
                    on_interim=None, on_speech=None, on_ready=None,
                    on_stage=None, on_audio=None, on_device=None, finish=None):
        import numpy as np
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise STTUnavailable("Install requirements-desktop.txt to enable the microphone.") from exc
        cancelled = _Abort(self._closed, abort)
        if cancelled.is_set():
            return ""
        def stage(name, text):
            if on_stage and not cancelled.is_set():
                on_stage(name, text)
        stage('device', 'Checking microphone...')
        try:
            device = sd.query_devices(self.device, kind='input')
            if on_device:
                on_device(device['name'])
        except Exception as exc:
            raise STTUnavailable('Microphone not available. Connect your headset or select a Windows input. ' + str(exc)) from exc
        # Prepare before recording: a cold model load must not lose the utterance.
        stage('loading', f'Loading local speech model ({os.getenv("ZUMBA_STT_MODEL", "tiny")})... Wait before speaking.')
        try:
            speech.prepare(abort=cancelled)
        except STTUnavailable:
            if cancelled.is_set():
                return ""
            raise
        while not self._lock.acquire(timeout=.05):
            if cancelled.is_set():
                return ""
        try:
            if cancelled.is_set():
                return ""
            blocks = queue.Queue(maxsize=2100)
            overflow = threading.Event()
            def capture(data, frames, timing, status):
                if status:
                    overflow.set()
                try:
                    blocks.put_nowait(data[:, 0].copy())
                except queue.Full:
                    overflow.set()
            samples, preroll = [], collections.deque(maxlen=10)
            recent_voice = collections.deque(maxlen=5)
            ambient = collections.deque(maxlen=100)
            active, silent, total = False, 0, 0
            configured_threshold = os.getenv('ZUMBA_VAD_THRESHOLD')
            threshold = float(configured_threshold) if configured_threshold else .003
            if not 0 < threshold < 1:
                raise STTUnavailable('Microphone threshold must be between 0 and 1.')
            deadline = time.monotonic() + min(float(timeout), speech.MAX_SECONDS)
            last_audio = time.monotonic()
            try:
                stage('opening', 'Opening microphone...')
                with sd.InputStream(samplerate=speech.SAMPLE_RATE, channels=1,
                                    dtype="float32", blocksize=480, device=self.device,
                                    callback=capture):
                    stage('listening', 'Listening — speak in Hindi or English, then pause.')
                    if on_ready:
                        on_ready()
                    while time.monotonic() < deadline and not cancelled.is_set():
                        if finish is not None and finish.is_set():
                            break
                        if overflow.is_set():
                            raise STTUnavailable("Microphone audio overflow. Select a different input or try again.")
                        try:
                            block = blocks.get(timeout=.05)
                        except queue.Empty:
                            if time.monotonic() - last_audio > 3:
                                raise STTUnavailable('Microphone opened but delivered no audio for 3 seconds. Reconnect the headset or check Windows microphone access.')
                            continue
                        last_audio = time.monotonic()
                        energy = float(np.sqrt(np.mean(block * block)))
                        if on_audio:
                            on_audio(energy, threshold, total / speech.SAMPLE_RATE)
                        if not active:
                            preroll.append(block)
                            recent_voice.append(energy >= threshold)
                            ambient.append(energy)
                            if sum(recent_voice) < 3:
                                if not configured_threshold and len(ambient) >= 10:
                                    threshold = float(np.clip(np.percentile(ambient, 20) * 3, .002, .012))
                                continue
                            active = True
                            samples.extend(preroll)
                            total = sum(map(len, samples))
                            stage('recording', 'Hearing you — pause to send, or click Transcribe now.')
                            if on_speech:
                                on_speech()
                        else:
                            samples.append(block)
                            total += len(block)
                        silent = silent + len(block) if energy < threshold else 0
                        if silent >= speech.SAMPLE_RATE * 1.0 or total >= speech.SAMPLE_RATE * speech.MAX_SECONDS:
                            break
            except (STTUnavailable, ValueError):
                raise
            except Exception as exc:
                raise STTUnavailable("Cannot open microphone. Run python desktop/mic_test.py --list-devices. "
                                     + str(exc)) from exc
            if cancelled.is_set():
                return ""
            if not active:
                stage('no_speech', 'No speech detected. Check the input meter and Windows microphone level; listening will retry.')
                return ''
            # Decode once after capture ends. Snapshot decoding used to occupy the
            # same worker ahead of the final clip, doubling latency on CPU.
            stage('transcribing', f'Transcribing {total / speech.SAMPLE_RATE:.1f}s of audio...')
            result = speech.transcribe(np.concatenate(samples), lang=self.lang,
                                     on_partial=on_interim, abort=cancelled)['transcript']
            if not result:
                stage('no_speech', 'Audio received, but no words recognized. Please try again.')
            return result
        finally:
            self._lock.release()

    def close(self):
        self._closed.set()
