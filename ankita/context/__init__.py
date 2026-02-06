"""
Context Module - Social awareness for Ankita.

HYBRID STT ARCHITECTURE:
- Vosk: Passive listening (zero hallucination, fast, silence-aware)
- Faster-Whisper: Commands only (high accuracy, multilingual)

This module enables:
- Owner voice recognition
- Passive group conversation listening (via Vosk)
- High-accuracy command detection (via Whisper)
- Session context memory
- Owner-controlled response triggers

Usage:
    from context import ContextManager
    
    manager = ContextManager()
    manager.set_mode(Mode.ACTIVE)
"""

from enum import Enum
from typing import Optional


class Mode(Enum):
    """Ankita social assistant modes."""
    OFF = "off"           # Mic disabled
    STANDBY = "standby"   # Listens but stores nothing
    ACTIVE = "active"     # Listens + stores context
    RESPONDING = "responding"  # Currently speaking


class TriggerCommand(Enum):
    """Owner-only trigger commands."""
    ANSWER = "answer"       # "Ankita answer them"
    EXPLAIN = "explain"     # "Ankita explain"
    STANDBY = "standby"     # "Ankita standby"
    ACTIVE = "active"       # "Ankita active"
    STOP = "stop"           # "Ankita stop listening"


# Lazy imports to avoid circular dependencies
_context_manager = None
_command_listener = None


def get_context_manager():
    """Get the singleton ContextManager instance."""
    global _context_manager
    if _context_manager is None:
        from .manager import ContextManager
        _context_manager = ContextManager()
    return _context_manager


def get_command_listener():
    """Get the singleton CommandListener instance (Whisper for commands)."""
    global _command_listener
    if _command_listener is None:
        from .command_listener import CommandListener
        _command_listener = CommandListener()
    return _command_listener


__all__ = [
    "Mode",
    "TriggerCommand",
    "get_context_manager",
    "get_command_listener",
]
