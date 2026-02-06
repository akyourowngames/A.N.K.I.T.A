"""
Context Module - Social awareness for Ankita.

This module enables:
- Owner voice recognition
- Passive group conversation listening
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


def get_context_manager():
    """Get the singleton ContextManager instance."""
    global _context_manager
    if _context_manager is None:
        from .manager import ContextManager
        _context_manager = ContextManager()
    return _context_manager


__all__ = [
    "Mode",
    "TriggerCommand",
    "get_context_manager",
]
