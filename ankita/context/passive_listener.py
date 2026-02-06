"""
Passive Listener - Background audio processing for group conversations.

Continuously listens and transcribes in the background, storing context
without interrupting. Only stores when in ACTIVE mode.

Usage:
    listener = PassiveListener()
    listener.start()  # Run in background thread
    listener.set_mode(Mode.ACTIVE)  # Start recording context
"""

import os
import threading
import queue
import time
import numpy as np
from datetime import datetime
from typing import Optional, Callable, Tuple
from . import Mode, TriggerCommand
from .session_memory import get_session_memory
from .triggers import parse_trigger, get_trigger_processor


# Constants
SAMPLE_RATE = 16000
CHUNK_DURATION = 3.0  # seconds per transcription chunk
VAD_AGGRESSIVENESS = 2  # 0-3, higher = more aggressive filtering
MIN_SPEECH_DURATION = 0.5  # seconds


class PassiveListener:
    """Background audio listener for group conversation context."""
    
    def __init__(self):
        self._mode = Mode.OFF
        self._mode_lock = threading.Lock()
        
        self._whisper_model = None
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
        
        # Speaker tracking (simple)
        self._current_speaker_id: Optional[str] = None
    
    def _load_whisper(self):
        """Lazy-load Whisper model."""
        if self._whisper_model is None:
            try:
                from faster_whisper import WhisperModel
                # Use small model for speed, can upgrade to medium for accuracy
                model_size = os.getenv("WHISPER_MODEL_SIZE", "small")
                self._whisper_model = WhisperModel(
                    model_size,
                    device="cpu",  # Use "cuda" if GPU available
                    compute_type="int8"
                )
                print(f"[PassiveListener] Whisper '{model_size}' model loaded")
            except ImportError:
                print("[PassiveListener] ERROR: faster-whisper not installed. Run: pip install faster-whisper")
                raise
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
                self._vad = False  # Mark as unavailable
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
        vad = self._load_vad()
        if vad is None:
            return True  # Assume speech if VAD unavailable
        
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
        return speech_ratio > 0.1  # At least 10% speech
    
    def _transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio to text."""
        model = self._load_whisper()
        
        # Ensure float32
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        
        try:
            segments, info = model.transcribe(
                audio,
                beam_size=5,
                language="en",  # Can be None for auto-detect
                vad_filter=True,
            )
            
            text = " ".join(segment.text.strip() for segment in segments)
            return text.strip()
        except Exception as e:
            print(f"[PassiveListener] Transcription error: {e}")
            return ""
    
    def _summarize(self, text: str) -> str:
        """Create compact summary of text."""
        # For now, just truncate. Can use LLM for better summaries.
        if len(text) > 100:
            return text[:97] + "..."
        return text
    
    def _audio_listener(self) -> None:
        """Background thread: capture audio chunks."""
        try:
            import sounddevice as sd
        except ImportError:
            print("[PassiveListener] ERROR: sounddevice not installed")
            return
        
        chunk_samples = int(CHUNK_DURATION * SAMPLE_RATE)
        
        print("[PassiveListener] Audio capture started")
        
        while self._running:
            try:
                # Only capture when ACTIVE
                if self.mode not in (Mode.ACTIVE, Mode.RESPONDING):
                    time.sleep(0.1)
                    continue
                
                # Record chunk
                audio = sd.rec(
                    chunk_samples,
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype='float32'
                )
                sd.wait()
                
                audio = audio.flatten()
                
                # Check for speech
                if self._has_speech(audio):
                    self._audio_queue.put(audio)
                    
            except Exception as e:
                print(f"[PassiveListener] Audio capture error: {e}")
                time.sleep(0.5)
        
        print("[PassiveListener] Audio capture stopped")
    
    def _audio_processor(self) -> None:
        """Background thread: process audio queue."""
        print("[PassiveListener] Audio processor started")
        
        while self._running:
            try:
                # Get audio chunk (with timeout)
                try:
                    audio = self._audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Store for owner verification
                self._current_audio = audio
                
                # Transcribe
                text = self._transcribe(audio)
                
                if not text:
                    continue
                
                print(f"[PassiveListener] Heard: {text[:60]}...")
                
                # Check for trigger commands
                trigger = parse_trigger(text)
                if trigger:
                    command, is_authorized = self._trigger_processor.process(text, audio)
                    if command and is_authorized:
                        self._handle_trigger(command, text)
                    continue
                
                # Store in session (if ACTIVE)
                if self.mode == Mode.ACTIVE:
                    # Determine speaker (simplified - no diarization yet)
                    if self._current_speaker_id is None:
                        self._current_speaker_id = self._session.get_next_speaker_id()
                    
                    summary = self._summarize(text)
                    self._session.add(
                        speaker=self._current_speaker_id,
                        summary=summary,
                        is_owner=False  # We'll improve this with owner detection
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
        
        self._running = True
        self.set_mode(Mode.STANDBY)  # Start in standby
        
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
        
        print("[PassiveListener] Started in STANDBY mode")
    
    def stop(self) -> None:
        """Stop passive listening."""
        self._running = False
        self.set_mode(Mode.OFF)
        
        if self._listener_thread:
            self._listener_thread.join(timeout=2.0)
        if self._processor_thread:
            self._processor_thread.join(timeout=2.0)
        
        print("[PassiveListener] Stopped")
    
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
