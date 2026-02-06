"""
Hybrid STT Passive Listener - Background audio processing for group conversations.

Uses Vosk for passive listening (zero hallucination, silence-aware)
Uses Faster-Whisper only for triggered commands (high accuracy)

This prevents the "phantom transcription" issue where Whisper hallucinates
text when there's ambient silence or noise.

Usage:
    listener = PassiveListener()
    listener.start()  # Run in background thread
    listener.set_mode(Mode.ACTIVE)  # Start recording context
"""

import os
import threading
import queue
import time
import json
import collections
import tempfile
import wave
import numpy as np
from datetime import datetime
from typing import Optional, Callable, Tuple
from . import Mode, TriggerCommand
from .session_memory import get_session_memory
from .triggers import parse_trigger, get_trigger_processor

# Constants
SAMPLE_RATE = 16000
CHUNK_SIZE = 4000  # ~250ms chunks for Vosk streaming
VAD_AGGRESSIVENESS = 1  # 0-3, higher = more aggressive filtering (1 = less strict)
COMMAND_RECORD_DURATION = 3.0  # seconds to record for command transcription
SPEECH_RATIO_THRESHOLD = 0.03  # 3% of frames need speech (was 10%, too strict)


class PassiveListener:
    """Hybrid STT Background listener for group conversation context."""
    
    def __init__(self):
        self._mode = Mode.OFF
        self._mode_lock = threading.Lock()
        
        # Vosk for passive listening (zero hallucination)
        self._vosk_model = None
        self._vosk_recognizer = None
        self._vosk_unavailable = False
        
        # Whisper for commands only (high accuracy)
        self._whisper_model = None
        self._whisper_unavailable = False
        self._whisper_warned = False
        
        self._vad = None
        
        self._audio_queue: queue.Queue = queue.Queue()
        self._listener_thread: Optional[threading.Thread] = None
        self._processor_thread: Optional[threading.Thread] = None
        self._running = False
        
        self._session = get_session_memory()
        self._trigger_processor = get_trigger_processor()
        
        self._on_trigger: Optional[Callable[[TriggerCommand, str], None]] = None
        self._on_mode_change: Optional[Callable[[Mode], None]] = None
        
        # Current audio buffer for owner verification
        self._current_audio: Optional[np.ndarray] = None
        
        # Command audio buffer (for Whisper)
        self._command_buffer: list = []
        self._collecting_command = False
        self._recent_audio: collections.deque[bytes] = collections.deque()
        self._recent_audio_max_bytes = int(COMMAND_RECORD_DURATION * SAMPLE_RATE * 2)
        
        # Speaker tracking (simple)
        self._current_speaker_id: Optional[str] = None
        self._debug = (os.getenv("PASSIVE_DEBUG") or "").strip().lower() in ("1", "true", "yes", "on")
        
        # Silence tracking
        self._silence_duration = 0.0
        self._min_text_length = 3  # Ignore very short transcripts
    
    def _load_vosk(self):
        """Lazy-load Vosk model for passive listening."""
        if self._vosk_unavailable:
            return None
        
        if self._vosk_model is None:
            try:
                from vosk import Model, KaldiRecognizer
                
                # Try different model paths (prefer Hindi model if available)
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                model_paths = [
                    os.getenv("VOSK_MODEL_PATH", ""),
                    # Hindi (recommended for Hindi-first environments)
                    os.path.join(project_root, "vosk-model-hi-0.22"),
                    "vosk-model-hi-0.22",
                    os.path.expanduser("~/.vosk/vosk-model-hi-0.22"),
                ]
                
                model_loaded = False
                for path in model_paths:
                    if path and os.path.exists(path):
                        try:
                            self._vosk_model = Model(path)
                            model_loaded = True
                            print(f"[PassiveListener] Vosk model loaded from: {path}")
                            break
                        except Exception as e:
                            if self._debug:
                                print(f"[PassiveListener] Failed to load Vosk from {path}: {e}")
                
                if not model_loaded:
                    # Try loading without path (use default/auto-download)
                    try:
                        self._vosk_model = Model(lang="hi")
                        print("[PassiveListener] Vosk model loaded (auto)")
                    except Exception as e:
                        raise ImportError(f"Could not load Vosk model: {e}")
                
                # Create recognizer
                self._vosk_recognizer = KaldiRecognizer(self._vosk_model, SAMPLE_RATE)
                self._vosk_recognizer.SetWords(False)  # Don't need word-level timing
                
            except ImportError:
                self._vosk_unavailable = True
                print("[PassiveListener] ERROR: vosk not installed. Run: pip install vosk")
                print("[PassiveListener] Also download a model: https://alphacephei.com/vosk/models")
                return None
            except Exception as e:
                self._vosk_unavailable = True
                print(f"[PassiveListener] ERROR loading Vosk: {e}")
                return None
        
        return self._vosk_recognizer
    
    def _load_whisper(self):
        """Lazy-load Whisper model for commands only."""
        if self._whisper_unavailable:
            return None
        
        if self._whisper_model is None:
            try:
                from faster_whisper import WhisperModel
                model_size = os.getenv("WHISPER_MODEL_SIZE", "small")
                self._whisper_model = WhisperModel(
                    model_size,
                    device="cpu",
                    compute_type="int8"
                )
                print(f"[PassiveListener] Whisper '{model_size}' model loaded (commands only)")
            except ImportError:
                self._whisper_unavailable = True
                if not self._whisper_warned:
                    print("[PassiveListener] ERROR: faster-whisper not installed. Run: pip install faster-whisper")
                    self._whisper_warned = True
                return None
        return self._whisper_model
    
    def _load_vad(self):
        """Lazy-load Voice Activity Detection."""
        if self._vad is None:
            try:
                import webrtcvad
                self._vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
                print("[PassiveListener] VAD loaded")
            except ImportError:
                print("[PassiveListener] webrtcvad not available - VAD disabled")
                self._vad = False
        return self._vad if self._vad is not False else None
    
    @property
    def mode(self) -> Mode:
        """Current listening mode."""
        with self._mode_lock:
            return self._mode
    
    def set_mode(self, mode: Mode) -> None:
        """Set listening mode."""
        with self._mode_lock:
            old_mode = self._mode
            self._mode = mode
        
        if old_mode != mode:
            print(f"[PassiveListener] Mode: {old_mode.value} → {mode.value}")
            
            # Clear session on standby
            if mode == Mode.STANDBY:
                self._session.clear()
            
            if self._on_mode_change:
                self._on_mode_change(mode)
    
    def set_trigger_callback(self, callback: Callable[[TriggerCommand, str], None]) -> None:
        """Set callback for trigger commands."""
        self._on_trigger = callback
    
    def set_mode_change_callback(self, callback: Callable[[Mode], None]) -> None:
        """Set callback for mode changes."""
        self._on_mode_change = callback
    
    def _has_speech(self, audio: np.ndarray) -> bool:
        """Check if audio contains speech using VAD."""
        try:
            if isinstance(audio, np.ndarray) and audio.size:
                rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float32)))))
                if self._debug:
                    print(f"[PassiveListener] audio rms={rms:.4f}")
                # Only skip if it's basically silent (very low threshold)
                if rms < 0.001:
                    return False
                # If RMS is reasonable, assume there's speech (skip VAD for now)
                if rms > 0.01:
                    if self._debug:
                        print(f"[PassiveListener] RMS {rms:.4f} > 0.01, assuming speech")
                    return True
        except Exception:
            pass

        vad = self._load_vad()
        if vad is None:
            return True
        
        # Convert to int16 bytes for webrtcvad
        if audio.dtype == np.float32:
            audio_int16 = (audio * 32767).astype(np.int16)
        else:
            audio_int16 = audio.astype(np.int16)
        
        # Check 30ms frames
        frame_size = int(SAMPLE_RATE * 0.03)
        speech_frames = 0
        total_frames = 0
        
        for i in range(0, len(audio_int16) - frame_size, frame_size):
            frame = audio_int16[i:i + frame_size].tobytes()
            try:
                if vad.is_speech(frame, SAMPLE_RATE):
                    speech_frames += 1
            except Exception:
                pass
            total_frames += 1
        
        if total_frames == 0:
            return False
        
        speech_ratio = speech_frames / total_frames
        if self._debug:
            print(f"[PassiveListener] VAD speech_ratio={speech_ratio:.1%}")
        return speech_ratio > SPEECH_RATIO_THRESHOLD
    
    def _transcribe_passive(self, audio: np.ndarray) -> str:
        """
        Transcribe using Vosk (passive listening).
        
        ONLY returns text that was actually spoken.
        No hallucination, no filler, no guessing.
        """
        rec = self._load_vosk()
        if rec is None:
            return ""
        
        # Convert to int16 bytes
        if audio.dtype == np.float32:
            audio_bytes = (audio * 32767).astype(np.int16).tobytes()
        else:
            audio_bytes = audio.astype(np.int16).tobytes()
        
        try:
            # Process in chunks
            text_parts = []
            chunk_size = 8000  # Process 0.5s at a time
            
            for i in range(0, len(audio_bytes), chunk_size * 2):  # *2 for int16
                chunk = audio_bytes[i:i + chunk_size * 2]
                if rec.AcceptWaveform(chunk):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").strip()
                    if text and len(text) >= self._min_text_length:
                        text_parts.append(text)
            
            # Get final result
            result = json.loads(rec.FinalResult())
            text = result.get("text", "").strip()
            if text and len(text) >= self._min_text_length:
                text_parts.append(text)
            
            return " ".join(text_parts).strip()
            
        except Exception as e:
            print(f"[PassiveListener] Vosk transcription error: {e}")
            return ""
    
    def _transcribe_command(self, audio: np.ndarray) -> str:
        """
        Transcribe using Faster-Whisper (commands only).
        
        High accuracy for wake words, commands, and answers.
        Only used when triggered, not for passive listening.
        """
        model = self._load_whisper()
        if model is None:
            # Fallback to Vosk
            return self._transcribe_passive(audio)
        
        beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "5") or "5")
        
        # Ensure float32
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        
        try:
            segments, _ = model.transcribe(
                audio,
                beam_size=beam_size,
                language="en",
                vad_filter=True,
                temperature=0.0,
                condition_on_previous_text=False,  # Prevent context bleeding
            )
            
            text = " ".join(seg.text for seg in segments).strip()
            return text
            
        except Exception as e:
            print(f"[PassiveListener] Whisper transcription error: {e}")
            return ""
    
    def _summarize(self, text: str) -> str:
        """Create compact summary of text."""
        if len(text) > 100:
            return text[:97] + "..."
        return text
    
    def _audio_listener(self) -> None:
        """Background thread: capture audio chunks using streaming."""
        try:
            import sounddevice as sd
        except ImportError:
            print("[PassiveListener] ERROR: sounddevice not installed")
            return

        print("[PassiveListener] Audio capture started (hybrid STT)")

        min_rms = float(os.getenv("PASSIVE_MIN_RMS", "0.008") or "0.008")
        blocksize = int(os.getenv("PASSIVE_BLOCKSIZE", str(CHUNK_SIZE)) or str(CHUNK_SIZE))

        try:
            with sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=blocksize,
                dtype="int16",
                channels=1,
            ) as stream:
                while self._running:
                    try:
                        if self.mode not in (Mode.STANDBY, Mode.ACTIVE, Mode.RESPONDING):
                            time.sleep(0.1)
                            continue

                        data_mv, _overflowed = stream.read(blocksize)
                        data = bytes(data_mv)
                        if not data:
                            continue

                        try:
                            x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                            rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
                        except Exception:
                            rms = 0.0

                        if self._debug:
                            print(f"[PassiveListener] chunk rms={rms:.4f}")

                        if rms < min_rms:
                            continue

                        # Keep short rolling buffer for trigger verification (Whisper + owner auth)
                        self._recent_audio.append(data)
                        total = sum(len(b) for b in self._recent_audio)
                        while total > self._recent_audio_max_bytes and self._recent_audio:
                            removed = self._recent_audio.popleft()
                            total -= len(removed)

                        self._audio_queue.put(data)

                    except Exception as e:
                        print(f"[PassiveListener] Audio capture error: {e}")
                        time.sleep(0.2)
        except Exception as e:
            print(f"[PassiveListener] Audio capture error: {e}")
            time.sleep(0.5)
        
        print("[PassiveListener] Audio capture stopped")
    
    def _audio_processor(self) -> None:
        """Background thread: process audio queue."""
        print("[PassiveListener] Audio processor started (Vosk passive, Whisper commands)")
        
        while self._running:
            try:
                # Get audio chunk
                try:
                    audio = self._audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                audio_bytes = audio
                rec = self._load_vosk()
                if rec is None:
                    continue

                if rec.AcceptWaveform(audio_bytes):
                    result = json.loads(rec.Result() or "{}")
                    text = (result.get("text") or "").strip()
                else:
                    continue
                
                if self._debug and not text:
                    print("[PassiveListener] no transcription (Vosk)")
                
                if not text:
                    continue
                
                # Check if this looks like a trigger
                trigger = parse_trigger(text)
                
                if trigger:
                    try:
                        combined = b"".join(list(self._recent_audio))
                    except Exception:
                        combined = audio_bytes

                    audio_i16 = np.frombuffer(combined, dtype=np.int16)
                    audio_f32 = audio_i16.astype(np.float32) / 32768.0

                    self._current_audio = audio_f32

                    print(f"[PassiveListener] Potential trigger detected, verifying with Whisper...")
                    whisper_text = self._transcribe_command(audio_f32)
                    
                    if whisper_text:
                        text = whisper_text
                        trigger = parse_trigger(whisper_text)
                    
                    if trigger:
                        command, is_authorized = self._trigger_processor.process(text, audio_f32)
                        if command and is_authorized:
                            self._handle_trigger(command, text)
                        continue
                
                # Log what we heard (from Vosk - honest transcription)
                print(f"[PassiveListener] Heard: {text[:60]}{'...' if len(text) > 60 else ''}")
                
                # Store in session (if ACTIVE)
                if self.mode == Mode.ACTIVE:
                    if self._current_speaker_id is None:
                        self._current_speaker_id = self._session.get_next_speaker_id()
                    
                    summary = self._summarize(text)
                    lang = ""
                    try:
                        from langdetect import detect as _ld_detect  # type: ignore
                        try:
                            lang = _ld_detect(text)
                        except Exception:
                            lang = "unknown"
                    except Exception:
                        lang = ""
                    self._session.add(
                        speaker=self._current_speaker_id,
                        summary=summary,
                        lang=lang,
                        is_owner=False
                    )
                
            except Exception as e:
                print(f"[PassiveListener] Processor error: {e}")
        
        print("[PassiveListener] Audio processor stopped")
    
    def _handle_trigger(self, command: TriggerCommand, text: str) -> None:
        """Handle a trigger command."""
        print(f"[PassiveListener] Trigger: {command.value}")
        
        # Handle mode changes
        if command == TriggerCommand.STANDBY:
            self.set_mode(Mode.STANDBY)
        elif command == TriggerCommand.ACTIVE:
            self.set_mode(Mode.ACTIVE)
        elif command == TriggerCommand.STOP:
            self.set_mode(Mode.OFF)
        
        # Fire callback
        if self._on_trigger:
            self._on_trigger(command, text)
    
    def start(self) -> None:
        """Start passive listening in background."""
        if self._running:
            return
        
        # Pre-load Vosk
        vosk = self._load_vosk()
        if vosk is None:
            print("[PassiveListener] WARNING: Vosk not available - falling back to Whisper only")
        
        self._running = True
        self.set_mode(Mode.STANDBY)
        
        self._listener_thread = threading.Thread(
            target=self._audio_listener,
            daemon=True,
            name="PassiveListener-Capture"
        )
        self._processor_thread = threading.Thread(
            target=self._audio_processor,
            daemon=True,
            name="PassiveListener-Process"
        )
        
        self._listener_thread.start()
        self._processor_thread.start()
        
        print("[PassiveListener] Started in STANDBY mode (Hybrid STT: Vosk passive + Whisper commands)")
    
    def stop(self) -> None:
        """Stop passive listening."""
        self._running = False
        self.set_mode(Mode.OFF)
        
        if self._listener_thread:
            self._listener_thread.join(timeout=2.0)
        if self._processor_thread:
            self._processor_thread.join(timeout=2.0)
        
        print("[PassiveListener] Stopped")

    def export_recent_audio_wav(self, seconds: float = 30.0) -> Optional[str]:
        """Export the last N seconds of captured audio to a temp WAV file."""
        try:
            seconds = float(seconds)
        except Exception:
            seconds = 30.0
        if seconds <= 0:
            seconds = 30.0

        # int16 mono => 2 bytes per sample
        bytes_per_second = int(SAMPLE_RATE * 2)
        max_bytes = int(seconds * bytes_per_second)

        try:
            combined = b"".join(list(self._recent_audio))
        except Exception:
            combined = b""
        if not combined:
            return None

        if len(combined) > max_bytes:
            combined = combined[-max_bytes:]

        out_path = os.path.join(tempfile.gettempdir(), "ankita_recent_audio.wav")
        try:
            with wave.open(out_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(combined)
            return out_path
        except Exception:
            return None
    
    def get_context(self) -> str:
        """Get current session context as text."""
        return self._session.get_context_summary()
    
    def get_last_question(self) -> Optional[str]:
        """Get the last unanswered question."""
        return self._session.get_last_question()


# Singleton
_passive_listener: Optional[PassiveListener] = None


def get_passive_listener() -> PassiveListener:
    """Get singleton PassiveListener."""
    global _passive_listener
    if _passive_listener is None:
        _passive_listener = PassiveListener()
    return _passive_listener
