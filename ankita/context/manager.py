"""
Context Manager - Central coordinator for social assistant features.

Brings together owner auth, passive listening, session memory, and triggers
into a unified interface for the main application.

Usage:
    manager = ContextManager()
    manager.start()
    manager.set_mode(Mode.ACTIVE)
"""

from typing import Optional, Callable
from . import Mode, TriggerCommand
from .owner_auth import get_owner_auth, OwnerAuth
from .session_memory import get_session_memory, SessionMemory
from .passive_listener import get_passive_listener, PassiveListener
from .triggers import get_trigger_processor


class ContextManager:
    """
    Central coordinator for social assistant features.
    
    Manages:
    - Owner voice authentication
    - Passive listening for group conversations
    - Session context memory
    - Trigger command handling
    """
    
    def __init__(self):
        self._owner_auth: OwnerAuth = get_owner_auth()
        self._session: SessionMemory = get_session_memory()
        self._listener: PassiveListener = get_passive_listener()
        
        self._on_answer_requested: Optional[Callable[[str], None]] = None
        
        # Wire up trigger handling
        self._listener.set_trigger_callback(self._on_trigger)
    
    @property
    def mode(self) -> Mode:
        """Current operating mode."""
        return self._listener.mode
    
    @property
    def is_owner_enrolled(self) -> bool:
        """Whether owner voice is enrolled."""
        return self._owner_auth.is_enrolled
    
    def set_answer_callback(self, callback: Callable[[str], None]) -> None:
        """
        Set callback for when "Ankita answer" is triggered.
        
        Args:
            callback: Function that takes context string and generates response
        """
        self._on_answer_requested = callback
    
    def set_mode_callback(self, callback: Callable[[Mode], None]) -> None:
        """Set callback for mode changes."""
        self._listener.set_mode_change_callback(callback)
    
    def _on_trigger(self, command: TriggerCommand, text: str) -> None:
        """Handle trigger commands."""
        if command == TriggerCommand.ANSWER:
            if self._on_answer_requested:
                context = self.get_context()
                self._on_answer_requested(context)
        
        elif command == TriggerCommand.EXPLAIN:
            if self._on_answer_requested:
                context = self.get_context()
                self._on_answer_requested(f"Please explain: {context}")
    
    def start(self) -> None:
        """Start the context manager (passive listening)."""
        print("[ContextManager] Starting...")
        self._listener.start()
        print("[ContextManager] Ready")
    
    def stop(self) -> None:
        """Stop the context manager."""
        print("[ContextManager] Stopping...")
        self._listener.stop()
        self._session.clear()
        print("[ContextManager] Stopped")
    
    def set_mode(self, mode: Mode) -> None:
        """Set operating mode."""
        self._listener.set_mode(mode)
    
    def get_context(self) -> str:
        """Get current session context summary."""
        return self._session.get_context_summary()
    
    def get_context_entries(self, limit: int = 10) -> list:
        """Get recent context entries as list."""
        return self._session.get_context(limit)
    
    def get_last_question(self) -> Optional[str]:
        """Get the last unanswered question from context."""
        return self._session.get_last_question()
    
    def add_context(self, speaker: str, summary: str, is_owner: bool = False) -> None:
        """Manually add context entry."""
        self._session.add(speaker, summary, is_owner=is_owner)
    
    def clear_context(self) -> None:
        """Clear session context."""
        self._session.clear()
    
    def enroll_owner_voice(self, audio_samples: list) -> tuple:
        """
        Enroll owner voice from audio samples.
        
        Args:
            audio_samples: List of numpy arrays with voice samples
        
        Returns:
            (success, message)
        """
        return self._owner_auth.enroll(audio_samples)
    
    def verify_owner(self, audio) -> tuple:
        """
        Verify if audio is from owner.
        
        Args:
            audio: Audio numpy array
        
        Returns:
            (is_owner, similarity_score)
        """
        return self._owner_auth.verify(audio)
    
    def delete_owner_enrollment(self) -> bool:
        """Delete owner voice enrollment."""
        return self._owner_auth.delete_enrollment()
    
    def get_status(self) -> dict:
        """Get current status summary."""
        return {
            "mode": self.mode.value,
            "owner_enrolled": self.is_owner_enrolled,
            "context_entries": len(self._session.entries),
            "session_id": self._session.session_id[:8] if self._session.session_id else None,
        }
