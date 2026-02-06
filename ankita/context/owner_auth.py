"""
Owner Authentication - Voice-based identity verification.

Uses voice embeddings (resemblyzer) to verify if the speaker is the owner.
Only the owner can issue control commands to Ankita.

Usage:
    auth = OwnerAuth()
    auth.enroll(audio_samples)  # One-time enrollment
    is_owner = auth.verify(audio)  # Runtime verification
"""

import os
import numpy as np
from typing import Optional, List, Tuple
from pathlib import Path

# Constants
SAMPLE_RATE = 16000
MIN_AUDIO_LENGTH = 1.0  # seconds
SIMILARITY_THRESHOLD = 0.75
ENROLLMENT_PHRASES = 3

# Paths
_MEMORY_DIR = Path(__file__).parent.parent / "memory"
OWNER_VOICE_PATH = _MEMORY_DIR / "owner_voice.npy"
OWNER_BACKUP_PATH = _MEMORY_DIR / "owner_voice_backup.npy"


class OwnerAuth:
    """Voice-based owner authentication using speaker embeddings."""
    
    def __init__(self, threshold: float = SIMILARITY_THRESHOLD):
        self.threshold = threshold
        self._encoder = None
        self._owner_embedding: Optional[np.ndarray] = None
        self._load_owner_embedding()
    
    def _get_encoder(self):
        """Lazy-load the voice encoder."""
        if self._encoder is None:
            try:
                from resemblyzer import VoiceEncoder
                self._encoder = VoiceEncoder()
                print("[OwnerAuth] Voice encoder loaded")
            except ImportError:
                print("[OwnerAuth] ERROR: resemblyzer not installed. Run: pip install resemblyzer")
                raise
        return self._encoder
    
    def _load_owner_embedding(self) -> None:
        """Load saved owner voice embedding if exists."""
        if OWNER_VOICE_PATH.exists():
            try:
                self._owner_embedding = np.load(OWNER_VOICE_PATH)
                print(f"[OwnerAuth] Owner voice loaded from {OWNER_VOICE_PATH}")
            except Exception as e:
                print(f"[OwnerAuth] Failed to load owner voice: {e}")
                self._owner_embedding = None
    
    def _save_owner_embedding(self, embedding: np.ndarray) -> bool:
        """Save owner voice embedding to disk."""
        try:
            # Backup existing if present
            if OWNER_VOICE_PATH.exists():
                np.save(OWNER_BACKUP_PATH, np.load(OWNER_VOICE_PATH))
            
            # Ensure directory exists
            OWNER_VOICE_PATH.parent.mkdir(parents=True, exist_ok=True)
            
            np.save(OWNER_VOICE_PATH, embedding)
            print(f"[OwnerAuth] Owner voice saved to {OWNER_VOICE_PATH}")
            return True
        except Exception as e:
            print(f"[OwnerAuth] Failed to save owner voice: {e}")
            return False
    
    @property
    def is_enrolled(self) -> bool:
        """Check if owner voice has been enrolled."""
        return self._owner_embedding is not None
    
    def _preprocess_audio(self, audio: np.ndarray) -> np.ndarray:
        """Preprocess audio for embedding generation."""
        from resemblyzer import preprocess_wav
        
        # Ensure float32 and correct shape
        if audio.dtype != np.float32:
            if audio.dtype in (np.int16, np.int32):
                audio = audio.astype(np.float32) / 32768.0
            else:
                audio = audio.astype(np.float32)
        
        # Flatten if needed
        if audio.ndim > 1:
            audio = audio.flatten()
        
        # Preprocess (normalize, remove silence, etc.)
        return preprocess_wav(audio, SAMPLE_RATE)
    
    def _generate_embedding(self, audio: np.ndarray) -> Optional[np.ndarray]:
        """Generate voice embedding from audio."""
        try:
            encoder = self._get_encoder()
            processed = self._preprocess_audio(audio)
            
            # Check minimum length
            if len(processed) < MIN_AUDIO_LENGTH * SAMPLE_RATE:
                print(f"[OwnerAuth] Audio too short: {len(processed)/SAMPLE_RATE:.2f}s < {MIN_AUDIO_LENGTH}s")
                return None
            
            embedding = encoder.embed_utterance(processed)
            return embedding
        except Exception as e:
            print(f"[OwnerAuth] Embedding generation failed: {e}")
            return None
    
    def enroll(self, audio_samples: List[np.ndarray]) -> Tuple[bool, str]:
        """
        Enroll owner voice from multiple audio samples.
        
        Args:
            audio_samples: List of audio arrays (at least 3 recommended)
        
        Returns:
            (success, message)
        """
        if len(audio_samples) < ENROLLMENT_PHRASES:
            return False, f"Need at least {ENROLLMENT_PHRASES} samples, got {len(audio_samples)}"
        
        embeddings = []
        for i, audio in enumerate(audio_samples):
            embedding = self._generate_embedding(audio)
            if embedding is not None:
                embeddings.append(embedding)
                print(f"[OwnerAuth] Sample {i+1}/{len(audio_samples)} processed")
            else:
                print(f"[OwnerAuth] Sample {i+1} failed - skipping")
        
        if len(embeddings) < 2:
            return False, "Too few valid samples. Please speak clearly and try again."
        
        # Average embeddings for robustness
        owner_embedding = np.mean(embeddings, axis=0)
        
        # Normalize
        owner_embedding = owner_embedding / np.linalg.norm(owner_embedding)
        
        # Save
        if self._save_owner_embedding(owner_embedding):
            self._owner_embedding = owner_embedding
            return True, f"Voice enrolled successfully with {len(embeddings)} samples"
        else:
            return False, "Failed to save voice profile"
    
    def verify(self, audio: np.ndarray) -> Tuple[bool, float]:
        """
        Verify if audio matches the owner's voice.
        
        Args:
            audio: Audio array to verify
        
        Returns:
            (is_owner, similarity_score)
        """
        if not self.is_enrolled:
            print("[OwnerAuth] No owner enrolled - verification skipped")
            return True, 1.0  # Allow if not enrolled
        
        embedding = self._generate_embedding(audio)
        if embedding is None:
            return False, 0.0
        
        # Cosine similarity
        embedding = embedding / np.linalg.norm(embedding)
        similarity = float(np.dot(self._owner_embedding, embedding))
        
        is_owner = similarity >= self.threshold
        
        if is_owner:
            print(f"[OwnerAuth] ✓ Owner verified (similarity: {similarity:.2%})")
        else:
            print(f"[OwnerAuth] ✗ Not owner (similarity: {similarity:.2%} < {self.threshold:.2%})")
        
        return is_owner, similarity
    
    def delete_enrollment(self) -> bool:
        """Delete owner voice enrollment."""
        try:
            if OWNER_VOICE_PATH.exists():
                OWNER_VOICE_PATH.unlink()
            self._owner_embedding = None
            print("[OwnerAuth] Owner voice enrollment deleted")
            return True
        except Exception as e:
            print(f"[OwnerAuth] Failed to delete enrollment: {e}")
            return False


# Singleton instance
_owner_auth: Optional[OwnerAuth] = None


def get_owner_auth() -> OwnerAuth:
    """Get the singleton OwnerAuth instance."""
    global _owner_auth
    if _owner_auth is None:
        _owner_auth = OwnerAuth()
    return _owner_auth
