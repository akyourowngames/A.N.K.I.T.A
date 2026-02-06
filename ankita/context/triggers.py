"""
Trigger System - Owner-only command detection.

Parses trigger commands like "Ankita answer", "Ankita standby", etc.
Commands are only accepted if they pass owner voice verification.

Usage:
    trigger = parse_trigger("Ankita answer them")
    if trigger == TriggerCommand.ANSWER:
        respond_with_context()
"""

import re
import time
from typing import Optional, Tuple
from . import TriggerCommand


# Trigger patterns (case-insensitive)
TRIGGER_PATTERNS = {
    TriggerCommand.ANSWER: [
        r"\bjarvis\b[,]?\s+answer\b",
        r"\bjarvis\b[,]?\s+answer\s+them\b",
        r"\bjarvis\b[,]?\s+answer\s+that\b",
        r"\bjarvis\b[,]?\s+tell\s+them\b",
        r"\bjarvis\b[,]?\s+respond\b",
    ],
    TriggerCommand.EXPLAIN: [
        r"\bjarvis\b[,]?\s+explain\b",
        r"\bjarvis\b[,]?\s+explain\s+that\b",
        r"\bjarvis\b[,]?\s+elaborate\b",
    ],
    TriggerCommand.STANDBY: [
        r"\bjarvis\b[,]?\s+standby\b",
        r"\bjarvis\b[,]?\s+stand\s+by\b",
        r"\bjarvis\b[,]?\s+pause\b",
        r"\bjarvis\b[,]?\s+stop\s+listening\b",
        r"\bjarvis\b[,]?\s+go\s+quiet\b",
        r"\bjarvis\b[,]?\s+be\s+quiet\b",
    ],
    TriggerCommand.ACTIVE: [
        r"\bjarvis\b[,]?\s+active\b",
        r"\bjarvis\b[,]?\s+start\s+listening\b",
        r"\bjarvis\b[,]?\s+wake\s+up\b",
        r"\bjarvis\b[,]?\s+listen\b",
        r"\bjarvis\b[,]?\s+resume\b",
    ],
    TriggerCommand.STOP: [
        r"\bjarvis\b[,]?\s+stop\b",
        r"\bjarvis\b[,]?\s+quit\b",
        r"\bjarvis\b[,]?\s+exit\b",
        r"\bjarvis\b[,]?\s+shutdown\b",
        r"\bjarvis\b[,]?\s+off\b",
    ],
}


def parse_trigger(text: str) -> Optional[TriggerCommand]:
    """
    Parse text for trigger commands.
    
    Args:
        text: Transcribed text to check
    
    Returns:
        TriggerCommand if found, None otherwise
    """
    if not text:
        return None
    
    text_lower = text.lower().strip()

    # Reduce false triggers: require the phrase to start with Jarvis (optionally preceded by hey/hi)
    if not re.match(r"^(?:hey\s+|hi\s+)?jarvis\b", text_lower):
        return None
    
    for command, patterns in TRIGGER_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                print(f"[Triggers] Detected: {command.value}")
                return command
    
    return None


def is_trigger_text(text: str) -> bool:
    """Check if text contains any trigger command."""
    return parse_trigger(text) is not None


def get_command_description(command: TriggerCommand) -> str:
    """Get human-readable description of a command."""
    descriptions = {
        TriggerCommand.ANSWER: "Answer the last question using context",
        TriggerCommand.EXPLAIN: "Explain or elaborate on the topic",
        TriggerCommand.STANDBY: "Pause listening and stop recording context",
        TriggerCommand.ACTIVE: "Resume listening and recording context",
        TriggerCommand.STOP: "Stop the social assistant completely",
    }
    return descriptions.get(command, "Unknown command")


class TriggerProcessor:
    """Process trigger commands with owner verification."""
    
    def __init__(self):
        from .owner_auth import get_owner_auth
        self._owner_auth = get_owner_auth()
        self._last_command: Optional[TriggerCommand] = None
        self._last_command_ts: float = 0.0
        self._cooldown_s: float = 1.5
    
    def process(self, text: str, audio: Optional[object] = None) -> Tuple[Optional[TriggerCommand], bool]:
        """
        Process potential trigger command.
        
        Args:
            text: Transcribed text
            audio: Audio data for voice verification (optional)
        
        Returns:
            (command, is_authorized)
            - command: The parsed trigger command or None
            - is_authorized: Whether the command is from the owner
        """
        command = parse_trigger(text)
        
        if command is None:
            return None, False

        now = time.time()
        if self._last_command == command and (now - self._last_command_ts) < self._cooldown_s:
            return None, False
        self._last_command = command
        self._last_command_ts = now
        
        # If no audio provided, skip verification
        if audio is None:
            print("[Triggers] No audio for verification - allowing command")
            return command, True
        
        # Verify owner voice
        import numpy as np
        if isinstance(audio, np.ndarray):
            is_owner, similarity = self._owner_auth.verify(audio)
            if is_owner:
                return command, True
            else:
                print(f"[Triggers] Command rejected - not owner (similarity: {similarity:.2%})")
                return command, False
        
        # Unknown audio format
        print("[Triggers] Unknown audio format - allowing command")
        return command, True


# Singleton
_trigger_processor: Optional[TriggerProcessor] = None


def get_trigger_processor() -> TriggerProcessor:
    """Get singleton TriggerProcessor."""
    global _trigger_processor
    if _trigger_processor is None:
        _trigger_processor = TriggerProcessor()
    return _trigger_processor
