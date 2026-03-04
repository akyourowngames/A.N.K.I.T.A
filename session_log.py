"""
session_log.py
==============
Short-term conversational memory — JSON sliding window.

Stores the last 50 messages per session in a simple JSON file.
Zero latency, no embedding overhead, survives restarts instantly.

This complements ChromaDB (semantic/long-term memory) by providing
fast access to recent conversation history without vector search.

Usage:
    log = SessionLog(workspace_root, "telegram-123456")
    log.append("user", "install speedtest cli")
    log.append("assistant", "Installing... done ✅")
    recent = log.recent(20)  # Get last 20 messages
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List


class SessionLog:
    """
    Fast JSON-based conversation log for recent message history.
    
    Stores last 50 messages per session, auto-rotates.
    Perfect for ContextAgent to understand recent conversation flow.
    """
    
    MAX_MESSAGES = 50
    
    def __init__(self, workspace_root: Path, session_id: str) -> None:
        """
        Initialize session log.
        
        Args:
            workspace_root: Workspace root path
            session_id: Unique session identifier (e.g., "telegram-123456", "cli-session")
        """
        self.session_id = session_id
        self._path = workspace_root / ".ankita" / "session_log" / f"{session_id}.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._messages: List[Dict[str, Any]] = self._load()
    
    def append(self, role: str, content: str) -> None:
        """
        Append a message to the log.
        
        Args:
            role: Message role ("user" or "assistant")
            content: Message content (truncated to 500 chars for storage)
        """
        self._messages.append({
            "role": role,
            "content": content[:500],  # Truncate long messages
            "ts": time.time(),
        })
        
        # Keep only last MAX_MESSAGES
        if len(self._messages) > self.MAX_MESSAGES:
            self._messages = self._messages[-self.MAX_MESSAGES:]
        
        self._save()
    
    def recent(self, n: int = 20) -> List[Dict[str, Any]]:
        """
        Get the N most recent messages.
        
        Args:
            n: Number of recent messages to retrieve (default 20)
        
        Returns:
            List of message dicts with keys: role, content, ts
        """
        return self._messages[-n:] if self._messages else []
    
    def all(self) -> List[Dict[str, Any]]:
        """Get all messages in the log (up to MAX_MESSAGES)."""
        return self._messages.copy()
    
    def clear(self) -> None:
        """Clear all messages from the log."""
        self._messages = []
        self._save()
    
    def _load(self) -> List[Dict[str, Any]]:
        """Load messages from disk."""
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                return data.get("messages", [])
        except Exception as err:
            print(f"[SessionLog] Failed to load {self._path}: {err}", flush=True)
        return []
    
    def _save(self) -> None:
        """Save messages to disk."""
        try:
            data = {
                "session_id": self.session_id,
                "messages": self._messages,
            }
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as err:
            print(f"[SessionLog] Failed to save {self._path}: {err}", flush=True)
