"""
Unit tests for ProactiveStatePersistence

Tests state persistence, atomic writes, corruption handling, and field operations.
"""
import json
import tempfile
from pathlib import Path

import pytest

from tools.proactive_state import ProactiveStatePersistence


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_initialization_creates_directory(temp_workspace):
    """Test that initialization creates the state directory."""
    persistence = ProactiveStatePersistence(temp_workspace)
    
    assert persistence.state_dir.exists()
    assert persistence.state_dir.is_dir()


def test_load_state_creates_default_on_missing_file(temp_workspace, capsys):
    """Test that load_state creates default state when file is missing and logs warning."""
    persistence = ProactiveStatePersistence(temp_workspace)
    
    state = persistence.load_state()
    
    # Verify state is initialized with defaults
    assert state is not None
    assert isinstance(state, dict)
    assert "last_morning_briefing_date" in state
    assert "delivered_notification_ids" in state
    assert state["dnd_active"] is False
    assert state["focus_mode"] == "idle"
    assert persistence.state_file.exists()
    
    # Verify warning log was generated
    captured = capsys.readouterr()
    assert "⚠️  State file not found" in captured.out
    assert "Initializing with defaults" in captured.out


def test_save_and_load_state_round_trip(temp_workspace):
    """Test that saving and loading state preserves all data."""
    persistence = ProactiveStatePersistence(temp_workspace)
    
    # Load initial state
    persistence.load_state()
    
    # Modify state
    persistence.update_field("last_morning_briefing_date", "2024-01-15")
    persistence.update_field("dnd_active", True)
    persistence.update_field("delivered_notification_ids", ["notif_123", "notif_456"])
    
    # Create new instance and load
    persistence2 = ProactiveStatePersistence(temp_workspace)
    loaded_state = persistence2.load_state()
    
    assert loaded_state["last_morning_briefing_date"] == "2024-01-15"
    assert loaded_state["dnd_active"] is True
    assert loaded_state["delivered_notification_ids"] == ["notif_123", "notif_456"]


def test_corrupted_state_file_initializes_defaults(temp_workspace, capsys):
    """Test that corrupted state file triggers default initialization and logs warning."""
    persistence = ProactiveStatePersistence(temp_workspace)
    
    # Create corrupted JSON file
    persistence.state_file.parent.mkdir(parents=True, exist_ok=True)
    persistence.state_file.write_text("{ invalid json }", encoding="utf-8")
    
    # Load should handle corruption gracefully
    state = persistence.load_state()
    
    # Verify state is initialized with defaults
    assert state is not None
    assert isinstance(state, dict)
    assert "last_morning_briefing_date" in state
    assert state["dnd_active"] is False
    
    # Verify warning log was generated
    captured = capsys.readouterr()
    assert "⚠️  Corrupted state file" in captured.out
    assert "Initializing with defaults" in captured.out


def test_update_field_saves_to_disk(temp_workspace):
    """Test that update_field persists changes to disk."""
    persistence = ProactiveStatePersistence(temp_workspace)
    persistence.load_state()
    
    persistence.update_field("focus_mode", "deep_work")
    
    # Verify file was written
    assert persistence.state_file.exists()
    
    # Verify content
    with open(persistence.state_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    
    assert saved_data["focus_mode"] == "deep_work"


def test_get_field_returns_value(temp_workspace):
    """Test that get_field returns the correct value."""
    persistence = ProactiveStatePersistence(temp_workspace)
    persistence.load_state()
    
    persistence.update_field("last_intent_refresh", "2024-01-15T08:00:00")
    
    value = persistence.get_field("last_intent_refresh")
    assert value == "2024-01-15T08:00:00"


def test_get_field_returns_default_for_missing_key(temp_workspace):
    """Test that get_field returns default for missing keys."""
    persistence = ProactiveStatePersistence(temp_workspace)
    persistence.load_state()
    
    value = persistence.get_field("nonexistent_key", "default_value")
    assert value == "default_value"


def test_get_state_returns_copy(temp_workspace):
    """Test that get_state returns a copy, not the original."""
    persistence = ProactiveStatePersistence(temp_workspace)
    persistence.load_state()
    
    state1 = persistence.get_state()
    state2 = persistence.get_state()
    
    # Modify one copy
    state1["test_field"] = "modified"
    
    # Other copy should be unchanged
    assert "test_field" not in state2


def test_atomic_write_prevents_corruption(temp_workspace):
    """Test that atomic write pattern prevents partial writes."""
    persistence = ProactiveStatePersistence(temp_workspace)
    persistence.load_state()
    
    # Update multiple times rapidly
    for i in range(10):
        persistence.update_field("counter", i)
    
    # File should always be valid JSON
    with open(persistence.state_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    
    assert "counter" in saved_data
    assert saved_data["counter"] == 9


def test_environment_state_nested_structure(temp_workspace):
    """Test that nested environment_state structure is preserved."""
    persistence = ProactiveStatePersistence(temp_workspace)
    state = persistence.load_state()
    
    assert "environment_state" in state
    assert isinstance(state["environment_state"], dict)
    assert "music_playing" in state["environment_state"]
    assert "brightness" in state["environment_state"]
    assert "notifications_muted" in state["environment_state"]


def test_delivered_notification_ids_list(temp_workspace):
    """Test that delivered_notification_ids is properly managed as a list."""
    persistence = ProactiveStatePersistence(temp_workspace)
    persistence.load_state()
    
    # Add notification IDs
    ids = ["notif_1", "notif_2", "notif_3"]
    persistence.update_field("delivered_notification_ids", ids)
    
    # Reload and verify
    persistence2 = ProactiveStatePersistence(temp_workspace)
    state = persistence2.load_state()
    
    assert state["delivered_notification_ids"] == ids
    assert isinstance(state["delivered_notification_ids"], list)


def test_corrupted_state_file_non_dict_initializes_defaults(temp_workspace, capsys):
    """Test that state file containing non-dict JSON triggers default initialization."""
    persistence = ProactiveStatePersistence(temp_workspace)
    
    # Create state file with valid JSON but not a dictionary
    persistence.state_file.parent.mkdir(parents=True, exist_ok=True)
    persistence.state_file.write_text('["not", "a", "dict"]', encoding="utf-8")
    
    # Load should handle this gracefully
    state = persistence.load_state()
    
    # Verify state is initialized with defaults
    assert state is not None
    assert isinstance(state, dict)
    assert "last_morning_briefing_date" in state
    assert state["dnd_active"] is False
    
    # Verify warning log was generated
    captured = capsys.readouterr()
    assert "⚠️  Corrupted state file" in captured.out
    assert "Initializing with defaults" in captured.out


def test_corrupted_state_file_empty_initializes_defaults(temp_workspace, capsys):
    """Test that empty state file triggers default initialization."""
    persistence = ProactiveStatePersistence(temp_workspace)
    
    # Create empty state file
    persistence.state_file.parent.mkdir(parents=True, exist_ok=True)
    persistence.state_file.write_text("", encoding="utf-8")
    
    # Load should handle this gracefully
    state = persistence.load_state()
    
    # Verify state is initialized with defaults
    assert state is not None
    assert isinstance(state, dict)
    assert "last_morning_briefing_date" in state
    assert state["dnd_active"] is False
    
    # Verify warning log was generated
    captured = capsys.readouterr()
    assert "⚠️  Corrupted state file" in captured.out
    assert "Initializing with defaults" in captured.out


def test_corrupted_state_file_partial_json_initializes_defaults(temp_workspace, capsys):
    """Test that partially written JSON file triggers default initialization."""
    persistence = ProactiveStatePersistence(temp_workspace)
    
    # Create partially written JSON file (simulating crash during write)
    persistence.state_file.parent.mkdir(parents=True, exist_ok=True)
    persistence.state_file.write_text('{"last_morning_briefing_date": "2024-01-15", "dnd_active":', encoding="utf-8")
    
    # Load should handle this gracefully
    state = persistence.load_state()
    
    # Verify state is initialized with defaults
    assert state is not None
    assert isinstance(state, dict)
    assert "last_morning_briefing_date" in state
    assert state["dnd_active"] is False
    
    # Verify warning log was generated
    captured = capsys.readouterr()
    assert "⚠️  Corrupted state file" in captured.out
    assert "Initializing with defaults" in captured.out


def test_state_file_with_extra_fields_preserved(temp_workspace):
    """Test that state file with extra fields preserves them during load."""
    persistence = ProactiveStatePersistence(temp_workspace)
    
    # Create state file with extra fields
    persistence.state_file.parent.mkdir(parents=True, exist_ok=True)
    state_with_extra = {
        **ProactiveStatePersistence.DEFAULT_STATE,
        "custom_field": "custom_value",
        "another_field": 123
    }
    persistence.state_file.write_text(json.dumps(state_with_extra), encoding="utf-8")
    
    # Load state
    state = persistence.load_state()
    
    # Verify extra fields are preserved
    assert state["custom_field"] == "custom_value"
    assert state["another_field"] == 123
    
    # Verify default fields are still present
    assert "last_morning_briefing_date" in state
    assert "dnd_active" in state


def test_state_file_with_missing_fields_filled_with_defaults(temp_workspace):
    """Test that state file with missing fields gets filled with defaults."""
    persistence = ProactiveStatePersistence(temp_workspace)
    
    # Create state file with only some fields
    persistence.state_file.parent.mkdir(parents=True, exist_ok=True)
    partial_state = {
        "last_morning_briefing_date": "2024-01-15",
        "dnd_active": True
    }
    persistence.state_file.write_text(json.dumps(partial_state), encoding="utf-8")
    
    # Load state
    state = persistence.load_state()
    
    # Verify provided fields are preserved
    assert state["last_morning_briefing_date"] == "2024-01-15"
    assert state["dnd_active"] is True
    
    # Verify missing fields are filled with defaults
    assert "delivered_notification_ids" in state
    assert state["delivered_notification_ids"] == []
    assert "focus_mode" in state
    assert state["focus_mode"] == "idle"
    assert "environment_state" in state
