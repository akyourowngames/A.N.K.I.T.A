"""Thread-safe bus between the voice controller and the Qt GUI.

The Jarvis reference bridges its threads through Mic.data / Status.data /
Responses.data files. A single-process desktop app does not need files, so
this module provides the same three channels in memory:

- mic      : listening enabled or not (the mic toggle button)
- status   : one-line assistant state ("Listening...", "Thinking...", ...)
- messages : chat lines appended to the chat screen
- stop     : interruption flag (mic-off, /stop, microphone speech activity)
- shutdown : app-close request (voice "exit" or the window close button)
"""

from __future__ import annotations

import collections
import threading
import time
from typing import Callable, Deque, List, Optional


class DesktopBus:
    def __init__(self, assistant_name: str = "Zumba", username: str = "Sir"):
        self.assistant_name = assistant_name
        self.username = username
        self._lock = threading.Lock()
        self._mic_on = False
        self._mic_generation = 0
        self._status = "Mic muted. Enable it to speak."
        self._stage = "muted"
        self._stage_started = time.monotonic()
        self._events = collections.deque(maxlen=80)
        self._capture_active = False
        self._level = self._threshold = self._audio_seconds = 0.0
        self._device = "Windows default input"
        self._transcript = ""
        self._last_error = ""
        self.finish_recording = threading.Event()
        self._messages: Deque[str] = collections.deque()
        self._stop_speech = threading.Event()
        self._shutdown = threading.Event()
        self._on_close: Optional[Callable[[], None]] = None

    # -- microphone -----------------------------------------------------
    def set_mic(self, on: bool) -> None:
        with self._lock:
            if self._mic_on == bool(on):
                return
            self._mic_on = bool(on)
            self._mic_generation += 1
            if not on:
                self._capture_active = False
                self._level = 0.0
            if self._stage in ('muted', 'idle', 'starting', 'device', 'loading', 'opening',
                               'listening', 'recording', 'transcribing', 'transcript',
                               'checking', 'no_speech', 'ignored', 'error'):
                self._set_stage('starting' if on else 'muted',
                    'Starting microphone...' if on else 'Mic muted. Enable it to speak.')
            else:
                self._events.append(time.strftime('%H:%M:%S') + ('  Mic enabled' if on else '  Mic muted'))
        if not on:
            # Turning the mic off while the assistant speaks interrupts it,
            # mirroring the Jarvis mic toggle.
            self._stop_speech.set()

    def mic_on(self) -> bool:
        with self._lock:
            return self._mic_on

    def mic_generation(self) -> int:
        with self._lock:
            return self._mic_generation

    def _set_stage(self, stage, text):
        if (stage, text) != (self._stage, self._status):
            elapsed = time.monotonic() - self._stage_started
            self._events.append(f'{time.strftime("%H:%M:%S")}  {text}  (previous: {elapsed:.1f}s)')
            self._stage_started = time.monotonic()
        self._stage, self._status = stage, text

    def set_stage(self, stage, text):
        with self._lock:
            self._set_stage(stage, text)

    def set_capture(self, active):
        with self._lock:
            self._capture_active = bool(active) and self._mic_on
            if not active:
                self._level = 0.0

    def set_audio(self, level, threshold, seconds):
        with self._lock:
            if self._capture_active:
                self._level, self._threshold, self._audio_seconds = level, threshold, seconds

    def set_device(self, name):
        with self._lock:
            self._device = name

    def set_transcript(self, text):
        with self._lock:
            self._transcript = text

    def set_error(self, text):
        with self._lock:
            self._last_error = text
            self._set_stage('error', text)

    def snapshot(self):
        with self._lock:
            return dict(mic_on=self._mic_on, capture_active=self._capture_active,
                stage=self._stage, status=self._status,
                elapsed=time.monotonic() - self._stage_started,
                level=self._level, threshold=self._threshold, audio_seconds=self._audio_seconds,
                device=self._device, transcript=self._transcript, last_error=self._last_error,
                events=list(self._events))

    # -- status line ----------------------------------------------------
    def set_status(self, text: str) -> None:
        with self._lock:
            self._set_stage(self._stage, text)

    def get_status(self) -> str:
        with self._lock:
            return self._status

    # -- chat messages --------------------------------------------------
    def post_message(self, text: str) -> None:
        with self._lock:
            self._messages.append(text)

    def drain_messages(self) -> List[str]:
        with self._lock:
            out = list(self._messages)
            self._messages.clear()
            return out

    # -- speech interruption -------------------------------------------
    def request_stop(self) -> None:
        """Interrupt the current utterance (voice 'stop', mic toggle, barge-in)."""
        self._stop_speech.set()

    def clear_stop(self) -> None:
        self._stop_speech.clear()

    def stop_requested(self) -> bool:
        return self._stop_speech.is_set()

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_speech

    # -- shutdown -------------------------------------------------------
    def on_close(self, callback: Callable[[], None]) -> None:
        self._on_close = callback

    def request_close(self) -> None:
        self._shutdown.set()
        self._stop_speech.set()
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:
                pass

    def shutdown_requested(self) -> bool:
        return self._shutdown.is_set()
