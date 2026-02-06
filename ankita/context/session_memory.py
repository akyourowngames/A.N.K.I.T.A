"""
Session Memory - Compact conversation context storage.

Stores session context as semantic summaries, not raw audio.
Auto-clears on standby or timeout for privacy.

Usage:
    session = SessionMemory()
    session.add("unknown_1", "talked about college admissions")
    session.add("owner", "mentioned interest in AI")
    context = session.get_context()
"""

import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
from dataclasses import dataclass, asdict
from threading import Lock

# Constants
SESSION_TIMEOUT_MINUTES = 5
MAX_ENTRIES = 50
MAX_SUMMARY_LENGTH = 200

# Paths
_MEMORY_DIR = Path(__file__).parent.parent / "memory"
SESSION_PATH = _MEMORY_DIR / "current_session.json"


@dataclass
class SessionEntry:
    """A single conversation entry."""
    speaker: str  # "owner", "unknown_1", "unknown_2", etc.
    summary: str
    topic: Optional[str] = None
    lang: str = ""  # Optional language tag (e.g. "hi", "en", "unknown")
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class SessionMemory:
    """Compact session context storage with auto-clear."""
    
    def __init__(self, timeout_minutes: int = SESSION_TIMEOUT_MINUTES):
        self.timeout_minutes = timeout_minutes
        self.session_id: str = ""
        self.started_at: Optional[datetime] = None
        self.entries: List[SessionEntry] = []
        self._last_activity: Optional[datetime] = None
        self._lock = Lock()
        self._speaker_counter = 0
        
        # Try to resume existing session
        self._load_session()
    
    def _load_session(self) -> None:
        """Load existing session if valid."""
        if not SESSION_PATH.exists():
            return
        
        try:
            with open(SESSION_PATH, "r") as f:
                data = json.load(f)
            
            started = datetime.fromisoformat(data.get("started_at", ""))
            last_activity = datetime.fromisoformat(data.get("last_activity", ""))
            
            # Check if session expired
            if datetime.now() - last_activity > timedelta(minutes=self.timeout_minutes):
                print("[SessionMemory] Previous session expired - starting fresh")
                self._clear_file()
                return
            
            self.session_id = data.get("session_id", "")
            self.started_at = started
            self._last_activity = last_activity
            self._speaker_counter = data.get("speaker_counter", 0)
            
            self.entries = [
                SessionEntry(**e) for e in data.get("entries", [])
            ]
            
            print(f"[SessionMemory] Resumed session {self.session_id[:8]}... with {len(self.entries)} entries")
            
        except Exception as e:
            print(f"[SessionMemory] Failed to load session: {e}")
            self._clear_file()
    
    def _save_session(self) -> None:
        """Persist session to disk."""
        try:
            SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "session_id": self.session_id,
                "started_at": self.started_at.isoformat() if self.started_at else "",
                "last_activity": self._last_activity.isoformat() if self._last_activity else "",
                "speaker_counter": self._speaker_counter,
                "entries": [asdict(e) for e in self.entries]
            }
            
            with open(SESSION_PATH, "w") as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            print(f"[SessionMemory] Failed to save session: {e}")
    
    def _clear_file(self) -> None:
        """Delete session file."""
        try:
            if SESSION_PATH.exists():
                SESSION_PATH.unlink()
        except Exception:
            pass
    
    def _ensure_session(self) -> None:
        """Ensure a session exists."""
        with self._lock:
            if not self.session_id:
                self.session_id = str(uuid.uuid4())
                self.started_at = datetime.now()
                self.entries = []
                self._speaker_counter = 0
                print(f"[SessionMemory] New session started: {self.session_id[:8]}...")
            self._last_activity = datetime.now()
    
    def _extract_topic(self, text: str) -> Optional[str]:
        """Extract topic from text (simple keyword extraction)."""
        # Common topic keywords
        topic_keywords = {
            "college": "education",
            "university": "education", 
            "school": "education",
            "admission": "education",
            "job": "career",
            "work": "career",
            "interview": "career",
            "project": "work",
            "meeting": "work",
            "weather": "weather",
            "movie": "entertainment",
            "music": "entertainment",
            "game": "entertainment",
            "food": "food",
            "restaurant": "food",
            "travel": "travel",
            "vacation": "travel",
            "health": "health",
            "doctor": "health",
        }
        
        text_lower = text.lower()
        for keyword, topic in topic_keywords.items():
            if keyword in text_lower:
                return topic
        return None
    
    def get_next_speaker_id(self) -> str:
        """Generate next unknown speaker ID."""
        with self._lock:
            self._speaker_counter += 1
            return f"person_{self._speaker_counter}"
    
    def add(
        self,
        speaker: str,
        summary: str,
        topic: Optional[str] = None,
        lang: str = "",
        is_owner: bool = False
    ) -> None:
        """
        Add a conversation entry.
        
        Args:
            speaker: Speaker identifier ("owner" or generated ID)
            summary: What was said (compact form)
            topic: Optional topic tag
            lang: Optional language tag ("hi", "en", "unknown")
            is_owner: Whether speaker is the owner
        """
        self._ensure_session()
        
        # Truncate long summaries
        if len(summary) > MAX_SUMMARY_LENGTH:
            summary = summary[:MAX_SUMMARY_LENGTH-3] + "..."
        
        # Extract topic if not provided
        if topic is None:
            topic = self._extract_topic(summary)
        
        # Use "owner" for owner, keep speaker ID otherwise
        speaker_label = "owner" if is_owner else speaker
        
        entry = SessionEntry(
            speaker=speaker_label,
            summary=summary,
            topic=topic,
            lang=lang or ""
        )
        
        with self._lock:
            self.entries.append(entry)
            
            # Trim old entries
            if len(self.entries) > MAX_ENTRIES:
                self.entries = self.entries[-MAX_ENTRIES:]
            
            self._last_activity = datetime.now()
        
        self._save_session()
        print(f"[SessionMemory] Added: [{speaker_label}] {summary[:50]}...")
    
    def get_context(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent context entries."""
        with self._lock:
            recent = self.entries[-limit:] if self.entries else []
            return [asdict(e) for e in recent]
    
    def get_context_summary(self) -> str:
        """Get a human-readable summary of the session."""
        if not self.entries:
            return "No conversation context yet."
        
        # Group by topic
        topics = {}
        for entry in self.entries:
            topic = entry.topic or "general"
            if topic not in topics:
                topics[topic] = []
            topics[topic].append(entry)
        
        # Build summary
        lines = []
        lines.append(f"Session started {self._format_time_ago(self.started_at)} with {len(self.entries)} exchanges.")
        
        for topic, entries in topics.items():
            speakers = set(e.speaker for e in entries)
            lines.append(f"- {topic.title()}: discussed by {', '.join(speakers)}")
        
        # Last few entries
        if len(self.entries) > 0:
            last = self.entries[-1]
            lines.append(f"Last: {last.speaker} said '{last.summary[:60]}...'")
        
        return "\n".join(lines)
    
    def _format_time_ago(self, dt: Optional[datetime]) -> str:
        """Format datetime as 'X minutes ago'."""
        if not dt:
            return "unknown time"
        
        delta = datetime.now() - dt
        minutes = int(delta.total_seconds() / 60)
        
        if minutes < 1:
            return "just now"
        elif minutes == 1:
            return "1 minute ago"
        elif minutes < 60:
            return f"{minutes} minutes ago"
        else:
            hours = minutes // 60
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
    
    def get_last_question(self) -> Optional[str]:
        """Get the last unanswered question from context."""
        # Look for entries that seem like questions
        for entry in reversed(self.entries):
            text = entry.summary.lower()
            if any(q in text for q in ["?", "what", "how", "why", "when", "where", "who", "can you", "could you"]):
                if entry.speaker != "owner":
                    return entry.summary
        return None
    
    def clear(self) -> None:
        """Clear session and delete file."""
        with self._lock:
            self.session_id = ""
            self.started_at = None
            self.entries = []
            self._last_activity = None
            self._speaker_counter = 0
        
        self._clear_file()
        print("[SessionMemory] Session cleared")
    
    def check_timeout(self) -> bool:
        """Check if session has timed out, clear if so."""
        if self._last_activity is None:
            return False
        
        if datetime.now() - self._last_activity > timedelta(minutes=self.timeout_minutes):
            print(f"[SessionMemory] Session timed out after {self.timeout_minutes} minutes")
            self.clear()
            return True
        return False


# Singleton instance
_session_memory: Optional[SessionMemory] = None


def get_session_memory() -> SessionMemory:
    """Get the singleton SessionMemory instance."""
    global _session_memory
    if _session_memory is None:
        _session_memory = SessionMemory()
    return _session_memory
