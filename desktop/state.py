"""Thread-safe bus between the voice controller and the Qt GUI.

The Jarvis reference bridges its threads through Mic.data / Status.data /
Responses.data files. A single-process desktop app does not need files, so
this module provides the same three channels in memory:

- mic      : listening enabled or not (the mic toggle button)
- status   : one-line assistant state ("Listening...", "Thinking...", ...)
- messages : chat lines appended to the chat screen
- stop     : interruption flag (mic-off, "stop", barge-in keyword)
- shutdown : app-close request (voice "exit" or the window close button)
"""

from __future__ import annotations

import collections
import threading
from typing import Callable, Deque, List, Optional


class DesktopBus:
    def __init__(self, assistant_name: str = "Zumba", username: str = "Sir"):
        self.assistant_name = assistant_name
        self.username = username
        self._lock = threading.Lock()
        self._mic_on = False
        self._status = "Available..."
        self._messages: Deque[str] = collections.deque()
        self._stop_speech = threading.Event()
        self._shutdown = threading.Event()
        self._on_close: Optional[Callable[[], None]] = None

    # -- microphone -----------------------------------------------------
    def set_mic(self, on: bool) -> None:
        with self._lock:
            self._mic_on = bool(on)
        if not on:
            # Turning the mic off while the assistant speaks interrupts it,
            # mirroring the Jarvis mic toggle.
            self._stop_speech.set()

    def mic_on(self) -> bool:
        with self._lock:
            return self._mic_on

    # -- status line ----------------------------------------------------
    def set_status(self, text: str) -> None:
        with self._lock:
            self._status = text

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
