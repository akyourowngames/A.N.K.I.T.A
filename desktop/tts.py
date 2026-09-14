"""Interruptible text-to-speech: edge-tts -> mp3 -> pygame playback.

Mirrors the Jarvis TextToSpeech.py contract: playback polls a stop callback
(about 10x/second) and aborts the moment it fires, so the mic toggle, the
explicit stop command or microphone speech activity cuts speech instead of
waiting for the utterance to finish. Long answers are summarized aloud
(first sentences + pointer to the chat screen) while the full text stays
visible in the GUI.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import threading

LONG_TEXT_CHARS = 250
LEAD_SENTENCES = 2


def split_sentences(text: str):
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p for p in (s.strip() for s in parts) if p]


def spoken_summary(full_text: str) -> tuple[str, bool]:
    """Return (text_to_speak, was_shortened)."""
    text = (full_text or "").strip()
    if not text:
        return "", False
    sentences = split_sentences(text)
    if len(sentences) > 4 and len(text) >= LONG_TEXT_CHARS:
        lead = " ".join(sentences[:LEAD_SENTENCES])
        return lead + " The rest of the result is on the chat screen.", True
    return text, False


class Speaker:
    def __init__(self, voice: str = "", rate: str = "+13%", pitch: str = "+5Hz"):
        self.voice = voice or os.getenv("ZUMBA_TTS_VOICE", "en-US-GuyNeural")
        self.rate = rate
        self.pitch = pitch

    def _synthesize(self, text: str, stop_event=None) -> str:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is not installed (pip install -r requirements-desktop.txt)"
            ) from exc

        async def _save(path: str) -> None:
            communicate = edge_tts.Communicate(
                text, self.voice, rate=self.rate, pitch=self.pitch
            )
            task = asyncio.create_task(communicate.save(path))
            try:
                deadline = asyncio.get_running_loop().time() + 25
                while not task.done():
                    if stop_event is not None and stop_event.is_set():
                        return
                    if asyncio.get_running_loop().time() >= deadline:
                        raise RuntimeError('Speech service timed out after 25 seconds')
                    await asyncio.wait({task}, timeout=.1)
                await task
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        fd, path = tempfile.mkstemp(prefix="zumba_say_", suffix=".mp3")
        os.close(fd)
        try:
            asyncio.run(_save(path))
        except BaseException:
            os.remove(path)
            raise
        return path

    def speak(self, text: str, stop_event: "threading.Event | None" = None,
              summarize: bool = True, on_stage=None) -> bool:
        """Speak text. Returns True if finished, False if interrupted.

        Raises RuntimeError when the audio stack is unavailable so callers
        can fall back to text-only mode.
        """
        say, _shortened = spoken_summary(text) if summarize else ((text or "").strip(), False)
        if not say:
            return True
        try:
            import pygame
        except ImportError as exc:
            raise RuntimeError(
                "pygame is not installed (pip install -r requirements-desktop.txt)"
            ) from exc
        if stop_event is not None and stop_event.is_set():
            return False
        if on_stage:
            on_stage('synthesizing', 'Generating speech...')
        path = self._synthesize(say, stop_event=stop_event)
        try:
            if stop_event is not None and stop_event.is_set():
                return False
            if on_stage:
                on_stage('playback', 'Opening speaker...')
            pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            if on_stage:
                on_stage('speaking', 'Speaking...')
            clock = pygame.time.Clock()
            while pygame.mixer.music.get_busy():
                if stop_event is not None and stop_event.is_set():
                    return False
                clock.tick(10)
            return True
        finally:
            try:
                pygame.mixer.music.stop()
                pygame.mixer.quit()
            except Exception:
                pass
            try:
                os.remove(path)
            except Exception:
                pass
