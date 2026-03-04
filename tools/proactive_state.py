"""
Proactive State Persistence Layer

Provides atomic state persistence for the Proactive Intelligence System.
Implements load_state(), save_state(), update_field(), and get_field() methods
with atomic writes using temp file + rename pattern.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


class ProactiveStatePersistence:
    """
    Persistent state layer for the Proactive Intelligence System.
    
    Manages state file at .ankita/state/proactive_state.json with atomic writes
    to prevent corruption on crashes.
    
    State Structure:
        {
            "last_morning_briefing_date": "2024-01-15",
            "last_insight_synthesis": "2024-01-15T02:00:00",
            "last_pattern_analysis": "2024-01-14T22:00:00",
            "last_intent_refresh": "2024-01-15T08:00:00",
            "delivered_notification_ids": ["notif_12345", "notif_12346"],
            "dnd_active": false,
            "focus_mode": "coding",
            "environment_state": {
                "music_playing": true,
                "brightness": 80,
                "notifications_muted": false
            }
        }
    """
    
    DEFAULT_STATE: Dict[str, Any] = {
        "last_morning_briefing_date": None,
        "last_insight_synthesis": None,
        "last_pattern_analysis": None,
        "last_intent_refresh": None,
        "delivered_notification_ids": [],
        "dnd_active": False,
        "focus_mode": "idle",
        "environment_state": {
            "music_playing": False,
            "brightness": 100,
            "notifications_muted": False,
        },
    }
    
    def __init__(self, workspace_root: Path) -> None:
        """
        Initialize the state persistence layer.
        
        Args:
            workspace_root: Root directory of the workspace (contains .ankita/)
        """
        self.workspace_root = workspace_root
        self.state_dir = workspace_root / ".ankita" / "state"
        self.state_file = self.state_dir / "proactive_state.json"
        
        # Ensure state directory exists
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory state cache
        self._state: Dict[str, Any] = {}
        
    def load_state(self) -> Dict[str, Any]:
        """
        Load state from disk.
        
        If the file is corrupted or missing, initializes with default values
        and logs a warning.
        
        Returns:
            Dictionary containing the loaded state
        """
        if not self.state_file.exists():
            print(
                f"[ProactiveStatePersistence] ⚠️  State file not found at {self.state_file}. "
                "Initializing with defaults.",
                flush=True,
            )
            self._state = self.DEFAULT_STATE.copy()
            self.save_state()
            return self._state.copy()
        
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                loaded_state = json.load(f)
            
            # Validate that loaded state is a dictionary
            if not isinstance(loaded_state, dict):
                raise ValueError("State file does not contain a valid dictionary")
            
            # Merge with defaults to ensure all required fields exist
            self._state = self.DEFAULT_STATE.copy()
            self._state.update(loaded_state)
            
            print(
                f"[ProactiveStatePersistence] ✅ State loaded successfully from {self.state_file}",
                flush=True,
            )
            return self._state.copy()
            
        except (json.JSONDecodeError, ValueError, IOError) as e:
            print(
                f"[ProactiveStatePersistence] ⚠️  Corrupted state file at {self.state_file}: {e}. "
                "Initializing with defaults.",
                flush=True,
            )
            self._state = self.DEFAULT_STATE.copy()
            self.save_state()
            return self._state.copy()
    
    def save_state(self) -> None:
        """
        Save state to disk using atomic write pattern.
        
        Uses temp file + rename to ensure atomicity and prevent corruption
        on crashes.
        """
        try:
            # Write to temporary file first
            fd, temp_path = tempfile.mkstemp(
                dir=self.state_dir,
                prefix=".proactive_state_",
                suffix=".tmp",
                text=True,
            )
            
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._state, f, indent=2, ensure_ascii=False)
                
                # Atomic rename (overwrites existing file)
                # On Windows, we need to remove the target first
                if os.name == "nt" and self.state_file.exists():
                    self.state_file.unlink()
                
                os.rename(temp_path, self.state_file)
                
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                raise
            
        except Exception as e:
            print(
                f"[ProactiveStatePersistence] ❌ Failed to save state: {e}",
                flush=True,
            )
            raise
    
    def update_field(self, key: str, value: Any) -> None:
        """
        Update a single field in the state and save to disk.
        
        Args:
            key: Field name to update
            value: New value for the field
        """
        self._state[key] = value
        self.save_state()
    
    def get_field(self, key: str, default: Any = None) -> Any:
        """
        Read a single field from the state.
        
        Args:
            key: Field name to read
            default: Default value if field doesn't exist
            
        Returns:
            Value of the field, or default if not found
        """
        return self._state.get(key, default)
    
    def get_state(self) -> Dict[str, Any]:
        """
        Get a copy of the entire state dictionary.
        
        Returns:
            Copy of the current state
        """
        return self._state.copy()
