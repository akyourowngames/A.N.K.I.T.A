"""Voice controller: listen -> think (zumba) -> speak, with stop/exit handling.

Loop (same shape as the Jarvis MainExecution):
  mic on  -> status "Listening..." -> STT utterance
          -> status "Thinking..."  -> zumba answer (posted in full to chat)
          -> status "Answering..." -> interruptible speech
          -> status "Available..."

Commands (voice or typed):
  "stop" / "quiet" / ...   interrupt the current utterance immediately
  "exit" / "bye" / ...     farewell, then close the app (same as the X button)

Interruption has three sources, all funnelling into one stop event:
  1. the mic toggle switched off mid-speech (see state.DesktopBus.set_mic),
  2. a stop-word arriving as the next query,
  3. a barge-in watcher: while speaking, a background listen accepts only
     stop/exit keywords, so talking over the assistant cuts it off.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

from .state import DesktopBus

STOP_WORDS = ("stop", "quiet", "hold on", "shut up", "enough", "cancel", "pause")
EXIT_WORDS = ("exit", "quit", "goodbye", "bye", "shutdown", "close", "sleep", "see you")

FAREWELLS = ("Goodbye!", "Shutting down. Goodbye!", "Okay, bye!")


def _contains(text: str, words) -> Optional[str]:
    lowered = (text or "").lower()
    for word in words:
        if word in lowered:
            return word
    return None


def default_answer_fn(session_id: str, text: str) -> str:
    from core.chat_pipeline import answer as _answer

    return _answer(session_id, text)


class VoiceController:
    def __init__(self, bus: DesktopBus, session_id: str = "desktop",
                 answer_fn: Optional[Callable[[str, str], str]] = None,
                 stt=None, speaker=None):
        self.bus = bus
        self.session_id = session_id
        self.answer_fn = answer_fn or default_answer_fn
        self._stt = stt  # ChromeSTT or fake (tests); None until needed
        self._speaker = speaker  # Speaker or fake; None until needed
        self._thread: Optional[threading.Thread] = None
        self._barge_thread: Optional[threading.Thread] = None

    # -- lazy audio stack (voice degrades to text-only when missing) ------
    def _get_stt(self):
        if self._stt is None:
            from .stt import ChromeSTT

            lang = os.getenv("ZUMBA_STT_LANG", "hi")
            self._stt = ChromeSTT(lang=lang)
        return self._stt

    def _stt_lang(self) -> str:
        stt = self._stt
        lang = getattr(stt, "lang", "") or os.getenv("ZUMBA_STT_LANG", "hi")
        return lang

    def _get_speaker(self):
        if self._speaker is None:
            from .tts import Speaker

            self._speaker = Speaker()
        return self._speaker

    # -- main loop ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run, daemon=True, name="zumba-voice")
        self._thread.start()

    def run(self) -> None:
        bus = self.bus
        bus.post_message(f"{bus.assistant_name}: Online. Turn the mic on and speak.")
        while not bus.shutdown_requested():
            if not bus.mic_on():
                if bus.get_status() not in ("Available...",):
                    bus.set_status("Available...")
                time.sleep(0.1)
                continue
            self._listen_turn()

    def _listen_turn(self) -> None:
        bus = self.bus
        bus.clear_stop()
        bus.set_status("Listening...")

        def _live(partial: str) -> None:
            if bus.mic_on() and not bus.shutdown_requested():
                bus.set_status(f"Listening... {partial[:80]}")

        try:
            heard = self._get_stt().listen_once(
                timeout=30.0, abort=bus.stop_event, on_interim=_live)
        except Exception as exc:
            bus.set_status(f"Voice unavailable ({exc}). Type instead...")
            bus.set_mic(False)
            return
        if bus.shutdown_requested() or not bus.mic_on():
            bus.set_status("Available...")
            return
        if not (heard or "").strip():
            return  # timeout: stay in the loop, keep listening
        # Non-English speech (Hindi by default) is translated to English
        # first, exactly like the Jarvis UniversalTranslator step.
        from .translate import needs_translation, to_english

        lang = self._stt_lang()
        if needs_translation(lang):
            bus.set_status("Translating...")
            heard = to_english(heard, lang)
        self.handle_query(heard)

    # -- one query (voice utterance or typed submit) ------------------------
    def handle_query(self, query: str) -> None:
        bus = self.bus
        query = (query or "").strip()
        if not query:
            return
        bus.post_message(f"{bus.username} : {query}")

        if _contains(query, EXIT_WORDS):
            self._exit_flow()
            return
        if _contains(query, STOP_WORDS):
            bus.request_stop()
            bus.post_message(f"{bus.assistant_name} : Stopped.")
            bus.set_status("Available...")
            return

        bus.set_status("Thinking...")
        try:
            full = (self.answer_fn(self.session_id, query) or "").strip()
        except Exception as exc:
            full = f"Sorry, I ran into an error: {exc}"
        if not full:
            full = "Sorry, I came back empty. Try again?"
        bus.post_message(f"{bus.assistant_name} : {full}")
        self._speak(full)

    # -- speech with barge-in -----------------------------------------------
    def _speak(self, text: str) -> None:
        bus = self.bus
        bus.clear_stop()
        bus.set_status("Answering...")
        self._start_barge_watcher(text)
        try:
            self._get_speaker().speak(text, stop_event=bus.stop_event)
        except Exception:
            # Audio stack missing/broken: the full answer is already on screen.
            pass
        finally:
            if not bus.shutdown_requested():
                bus.set_status("Available...")

    def _start_barge_watcher(self, text: str) -> None:
        """Background listen that only accepts stop/exit keywords mid-speech."""
        bus = self.bus

        def _watch():
            try:
                stt = self._get_stt()
            except Exception:
                return
            # Rough speech duration: ~15 chars/sec + headroom, capped at 90s.
            budget = min(90.0, max(8.0, len(text or "") / 15.0 + 6.0))
            try:
                heard = stt.listen_once(timeout=budget, abort=bus.stop_event)
            except Exception:
                return
            if not (heard or "").strip():
                return
            if _contains(heard, EXIT_WORDS):
                bus.request_stop()
                self._exit_flow()
            elif _contains(heard, STOP_WORDS):
                # Leave the flag set: the next listen/speak turn clears it
                # when it starts, and mic-off intent must survive.
                bus.request_stop()
                bus.set_status("Interrupted. Listening...")

        old = self._barge_thread
        if old is not None and old.is_alive():
            return  # previous utterance watcher still draining; leave it
        self._barge_thread = threading.Thread(target=_watch, daemon=True, name="zumba-barge")
        self._barge_thread.start()

    # -- closing --------------------------------------------------------------
    def _exit_flow(self) -> None:
        bus = self.bus
        farewell = FAREWELLS[0].replace("Goodbye", f"Goodbye {bus.username}")
        bus.post_message(f"{bus.assistant_name} : {farewell}")
        bus.set_status("Closing...")
        try:
            self._get_speaker().speak(farewell, stop_event=None, summarize=False)
        except Exception:
            pass
        bus.request_close()

    def shutdown(self) -> None:
        """Release audio resources (called on app quit)."""
        try:
            if self._stt is not None and hasattr(self._stt, "close"):
                self._stt.close()
        except Exception:
            pass
