"""
Command Listener - High-accuracy STT for triggered commands.

Uses Faster-Whisper exclusively for command transcription.
Called ONLY when a trigger is detected, not for passive listening.

This provides:
- High accuracy for wake words and commands
- Multilingual support
- No hallucination (short focused audio)

Usage:
    listener = CommandListener()
    text = listener.transcribe_command(audio_array)
"""

import os
import numpy as np
from typing import Optional
import tempfile

# Constants
SAMPLE_RATE = 16000


class CommandListener:
    """High-accuracy command transcription using Faster-Whisper."""
    
    def __init__(self):
        self._model = None
        self._unavailable = False
        self._debug = (os.getenv("PASSIVE_DEBUG") or "").strip().lower() in ("1", "true", "yes", "on")
    
    def _load_model(self):
        """Lazy-load Whisper model."""
        if self._unavailable:
            return None
        
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                
                model_size = os.getenv("WHISPER_MODEL_SIZE", "small")
                device = os.getenv("WHISPER_DEVICE", "cpu")
                
                self._model = WhisperModel(
                    model_size,
                    device=device,
                    compute_type="int8"
                )
                print(f"[CommandListener] Whisper '{model_size}' model loaded")
                
            except ImportError:
                self._unavailable = True
                print("[CommandListener] ERROR: faster-whisper not installed")
                return None
            except Exception as e:
                self._unavailable = True
                print(f"[CommandListener] ERROR loading model: {e}")
                return None
        
        return self._model
    
    def transcribe_command(self, audio: np.ndarray, language: str = "en") -> str:
        """
        Transcribe command audio with high accuracy.
        
        Args:
            audio: Audio data as numpy array (float32 or int16)
            language: Language code (default: "en")
        
        Returns:
            Transcribed text
        """
        model = self._load_model()
        if model is None:
            return ""
        
        # Ensure float32
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        
        beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "5") or "5")
        
        try:
            segments, info = model.transcribe(
                audio,
                beam_size=beam_size,
                language=language,
                vad_filter=True,
                temperature=0.0,
                condition_on_previous_text=False,  # Critical: prevents context bleeding
            )
            
            parts = []
            for segment in segments:
                text = getattr(segment, "text", "").strip()
                if text:
                    parts.append(text)
            
            result = " ".join(parts).strip()
            
            if self._debug:
                print(f"[CommandListener] Transcribed: {result}")
            
            return result
            
        except Exception as e:
            print(f"[CommandListener] Transcription error: {e}")
            return ""
    
    def transcribe_file(self, audio_path: str, language: str = "en") -> str:
        """
        Transcribe audio file.
        
        Args:
            audio_path: Path to audio file
            language: Language code
        
        Returns:
            Transcribed text
        """
        model = self._load_model()
        if model is None:
            return ""
        
        beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "5") or "5")
        
        try:
            segments, _ = model.transcribe(
                audio_path,
                beam_size=beam_size,
                language=language,
                vad_filter=True,
                temperature=0.0,
                condition_on_previous_text=False,
            )
            
            return " ".join(seg.text for seg in segments).strip()
            
        except Exception as e:
            print(f"[CommandListener] File transcription error: {e}")
            return ""


# Singleton
_command_listener: Optional[CommandListener] = None


def get_command_listener() -> CommandListener:
    """Get singleton CommandListener."""
    global _command_listener
    if _command_listener is None:
        _command_listener = CommandListener()
    return _command_listener
