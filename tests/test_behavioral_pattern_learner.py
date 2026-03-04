"""
Unit tests for BehavioralPatternLearner.

Tests:
- Weekly analysis timing
- patterns.jsonl pruning
- LLM failure handling

Requirements: 3.3, 3.5
"""
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proactive_models import BehavioralModel
from tools.behavioral_pattern_learner import BehavioralPatternLearner


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        yield workspace


@pytest.fixture
def pattern_learner(temp_workspace):
    """Create a BehavioralPatternLearner instance with temp workspace."""
    learner = BehavioralPatternLearner(temp_workspace)
    return learner


@pytest.fixture
def mock_runtime():
    """Create a mock LLM runtime."""
    runtime = MagicMock()
    return runtime


@pytest.fixture
def sample_behavioral_data():
    """Sample valid behavioral data."""
    return {
        "morning_routine": {
            "typical_start_time": "08:30",
            "first_actions": ["check email", "review tasks"],
        },
        "peak_coding_hours": ["10:00-12:00", "14:00-17:00"],
        "typical_project_switch_time": "90 minutes",
        "never_works_on": ["weekends after 6pm"],
        "frequently_forgets": ["commit messages", "closing files"],
    }


# ============================================================================
# Test: Fingerprint Recording
# ============================================================================

def test_record_fingerprint_creates_file(pattern_learner):
    """
    Test that recording a fingerprint creates patterns.jsonl.
    """
    pattern_learner.record_fingerprint(
        interaction_type="code",
        duration_sec=120,
        tools_used=["write_file", "execute_shell"],
        context="working on proactive spec",
    )
    
    # Verify file exists
    assert pattern_learner.patterns_file.exists()


def test_record_fingerprint_appends_to_file(pattern_learner):
    """
    Test that multiple fingerprints are appended to patterns.jsonl.
    """
    # Record first fingerprint
    pattern_learner.record_fingerprint(
        interaction_type="code",
        duration_sec=120,
        tools_used=["write_file"],
        context="task 1",
    )
    
    # Record second fingerprint
    pattern_learner.record_fingerprint(
        interaction_type="search",
        duration_sec=60,
        tools_used=["web_search"],
        context="task 2",
    )
    
    # Read file and verify both entries
    with open(pattern_learner.patterns_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    assert len(lines) == 2
    
    # Parse and verify first entry
    entry1 = json.loads(lines[0])
    assert entry1["interaction_type"] == "code"
    assert entry1["duration_sec"] == 120
    assert entry1["tools_used"] == ["write_file"]
    assert entry1["context"] == "task 1"
    
    # Parse and verify second entry
    entry2 = json.loads(lines[1])
    assert entry2["interaction_type"] == "search"
    assert entry2["duration_sec"] == 60
    assert entry2["tools_used"] == ["web_search"]
    assert entry2["context"] == "task 2"


def test_record_fingerprint_includes_timestamp(pattern_learner):
    """
    Test that fingerprints include ISO format timestamps.
    """
    before = datetime.now()
    
    pattern_learner.record_fingerprint(
        interaction_type="code",
        duration_sec=120,
        tools_used=["write_file"],
        context="test",
    )
    
    after = datetime.now()
    
    # Read and parse the fingerprint
    with open(pattern_learner.patterns_file, "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
    
    assert "timestamp" in entry
    timestamp = datetime.fromisoformat(entry["timestamp"])
    
    # Timestamp should be between before and after
    assert before <= timestamp <= after


def test_record_fingerprint_handles_errors_gracefully(pattern_learner):
    """
    Test that recording errors don't crash the system.
    """
    # Make patterns_file unwritable by pointing to invalid location
    pattern_learner.patterns_file = Path("/invalid/path/patterns.jsonl")
    
    # Should not raise exception
    pattern_learner.record_fingerprint(
        interaction_type="code",
        duration_sec=120,
        tools_used=["write_file"],
        context="test",
    )


# ============================================================================
# Test: Weekly Analysis Timing
# ============================================================================

def test_should_run_analysis_on_sunday_22_00(pattern_learner):
    """
    Test that analysis should run on Sunday at 22:00.
    
    Requirement 3.3: WHEN Sunday night arrives (between 22:00-23:00),
    THE BehavioralPatternLearner SHALL analyze the last 4 weeks of patterns.
    """
    # Mock datetime to return Sunday 22:00
    sunday_22 = datetime(2024, 1, 14, 22, 0, 0)  # Sunday
    
    with patch("tools.behavioral_pattern_learner.datetime") as mock_datetime:
        mock_datetime.now.return_value = sunday_22
        mock_datetime.fromisoformat = datetime.fromisoformat
        
        result = pattern_learner.should_run_analysis()
    
    assert result is True


def test_should_run_analysis_on_sunday_22_30(pattern_learner):
    """
    Test that analysis should run on Sunday at 22:30 (within window).
    """
    sunday_22_30 = datetime(2024, 1, 14, 22, 30, 0)  # Sunday
    
    with patch("tools.behavioral_pattern_learner.datetime") as mock_datetime:
        mock_datetime.now.return_value = sunday_22_30
        mock_datetime.fromisoformat = datetime.fromisoformat
        
        result = pattern_learner.should_run_analysis()
    
    assert result is True


def test_should_not_run_analysis_on_sunday_23_00(pattern_learner):
    """
    Test that analysis should NOT run on Sunday at 23:00 (outside window).
    """
    sunday_23 = datetime(2024, 1, 14, 23, 0, 0)  # Sunday
    
    with patch("tools.behavioral_pattern_learner.datetime") as mock_datetime:
        mock_datetime.now.return_value = sunday_23
        mock_datetime.fromisoformat = datetime.fromisoformat
        
        result = pattern_learner.should_run_analysis()
    
    assert result is False


def test_should_not_run_analysis_on_monday(pattern_learner):
    """
    Test that analysis should NOT run on Monday.
    """
    monday_22 = datetime(2024, 1, 15, 22, 0, 0)  # Monday
    
    with patch("tools.behavioral_pattern_learner.datetime") as mock_datetime:
        mock_datetime.now.return_value = monday_22
        mock_datetime.fromisoformat = datetime.fromisoformat
        
        result = pattern_learner.should_run_analysis()
    
    assert result is False


def test_should_not_run_analysis_on_sunday_morning(pattern_learner):
    """
    Test that analysis should NOT run on Sunday morning.
    """
    sunday_08 = datetime(2024, 1, 14, 8, 0, 0)  # Sunday morning
    
    with patch("tools.behavioral_pattern_learner.datetime") as mock_datetime:
        mock_datetime.now.return_value = sunday_08
        mock_datetime.fromisoformat = datetime.fromisoformat
        
        result = pattern_learner.should_run_analysis()
    
    assert result is False


# ============================================================================
# Test: Patterns.jsonl Pruning
# ============================================================================

def test_prune_old_patterns_removes_old_entries(pattern_learner, temp_workspace):
    """
    Test that pruning removes patterns older than 30 days.
    
    Requirement 3.5: Implement patterns.jsonl pruning (>30 days)
    """
    # Create patterns with various ages
    now = datetime.now()
    old_pattern = {
        "timestamp": (now - timedelta(days=35)).isoformat(),
        "interaction_type": "code",
        "duration_sec": 120,
        "tools_used": ["write_file"],
        "context": "old task",
    }
    recent_pattern = {
        "timestamp": (now - timedelta(days=10)).isoformat(),
        "interaction_type": "code",
        "duration_sec": 60,
        "tools_used": ["read_file"],
        "context": "recent task",
    }
    
    # Write patterns to file
    patterns_file = temp_workspace / ".ankita" / "state" / "patterns.jsonl"
    patterns_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(patterns_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(old_pattern) + "\n")
        f.write(json.dumps(recent_pattern) + "\n")
    
    # Prune old patterns
    pattern_learner._prune_old_patterns(days=30)
    
    # Read remaining patterns
    with open(patterns_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Should only have 1 pattern (the recent one)
    assert len(lines) == 1
    
    remaining = json.loads(lines[0])
    assert remaining["context"] == "recent task"


def test_prune_old_patterns_keeps_recent_entries(pattern_learner, temp_workspace):
    """
    Test that pruning keeps patterns within 30 days.
    """
    # Create multiple recent patterns
    now = datetime.now()
    patterns = []
    for i in range(5):
        pattern = {
            "timestamp": (now - timedelta(days=i * 5)).isoformat(),  # 0, 5, 10, 15, 20 days old
            "interaction_type": "code",
            "duration_sec": 60,
            "tools_used": ["tool"],
            "context": f"task {i}",
        }
        patterns.append(pattern)
    
    # Write patterns to file
    patterns_file = temp_workspace / ".ankita" / "state" / "patterns.jsonl"
    patterns_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(patterns_file, "w", encoding="utf-8") as f:
        for pattern in patterns:
            f.write(json.dumps(pattern) + "\n")
    
    # Prune old patterns
    pattern_learner._prune_old_patterns(days=30)
    
    # Read remaining patterns
    with open(patterns_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Should keep all 5 patterns (all within 30 days)
    assert len(lines) == 5


def test_prune_old_patterns_handles_missing_file(pattern_learner):
    """
    Test that pruning handles missing patterns.jsonl gracefully.
    """
    # Should not raise exception
    pattern_learner._prune_old_patterns(days=30)


def test_prune_old_patterns_handles_malformed_lines(pattern_learner, temp_workspace):
    """
    Test that pruning skips malformed JSON lines.
    """
    # Create patterns with one malformed line
    now = datetime.now()
    good_pattern = {
        "timestamp": (now - timedelta(days=10)).isoformat(),
        "interaction_type": "code",
        "duration_sec": 60,
        "tools_used": ["tool"],
        "context": "good task",
    }
    
    # Write patterns to file
    patterns_file = temp_workspace / ".ankita" / "state" / "patterns.jsonl"
    patterns_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(patterns_file, "w", encoding="utf-8") as f:
        f.write("not valid json{{{" + "\n")
        f.write(json.dumps(good_pattern) + "\n")
    
    # Prune old patterns (should skip malformed line)
    pattern_learner._prune_old_patterns(days=30)
    
    # Read remaining patterns
    with open(patterns_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Should only have 1 pattern (the good one)
    assert len(lines) == 1
    
    remaining = json.loads(lines[0])
    assert remaining["context"] == "good task"


# ============================================================================
# Test: LLM Failure Handling
# ============================================================================

def test_llm_failure_keeps_previous_model(pattern_learner, temp_workspace, mock_runtime):
    """
    Test that when LLM call fails, the learner keeps previous behavioral_model.json.
    
    Requirement 3.5: Add error handling to keep previous behavioral_model.json on failure
    """
    # Create a previous behavioral_model.json
    previous_model = {
        "generated_at": "2024-01-07T22:00:00",
        "morning_routine": {
            "typical_start_time": "09:00",
            "first_actions": ["check email"],
        },
        "peak_coding_hours": ["10:00-12:00"],
        "typical_project_switch_time": "60 minutes",
        "never_works_on": ["weekends"],
        "frequently_forgets": ["git push"],
    }
    
    model_file = temp_workspace / ".ankita" / "state" / "behavioral_model.json"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text(json.dumps(previous_model), encoding="utf-8")
    
    # Create some patterns
    pattern_learner.record_fingerprint(
        interaction_type="code",
        duration_sec=120,
        tools_used=["write_file"],
        context="test",
    )
    
    # Attach runtime that will fail
    pattern_learner.attach_runtime(mock_runtime)
    
    # Mock _call_llm_for_patterns to raise an exception
    with patch.object(pattern_learner, "_call_llm_for_patterns", side_effect=Exception("LLM API error")):
        result = pattern_learner.analyze_patterns()
    
    # Should return the previous behavioral model
    assert result is not None
    assert result.morning_routine["typical_start_time"] == "09:00"
    assert result.peak_coding_hours == ["10:00-12:00"]
    
    # Previous file should still exist and be unchanged
    assert model_file.exists()
    with open(model_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data["generated_at"] == "2024-01-07T22:00:00"


def test_llm_failure_with_no_previous_model(pattern_learner, mock_runtime):
    """
    Test that when LLM fails and no previous model exists, returns None.
    """
    # Create some patterns
    pattern_learner.record_fingerprint(
        interaction_type="code",
        duration_sec=120,
        tools_used=["write_file"],
        context="test",
    )
    
    pattern_learner.attach_runtime(mock_runtime)
    
    # Mock _call_llm_for_patterns to raise an exception
    with patch.object(pattern_learner, "_call_llm_for_patterns", side_effect=Exception("LLM API error")):
        result = pattern_learner.analyze_patterns()
    
    # Should return None when no previous model exists
    assert result is None


def test_analyze_without_runtime(pattern_learner):
    """
    Test that analyze_patterns fails gracefully without runtime.
    """
    result = pattern_learner.analyze_patterns()
    
    assert result is None


def test_analyze_with_no_patterns(pattern_learner, mock_runtime):
    """
    Test that analyze_patterns skips when no patterns exist.
    """
    pattern_learner.attach_runtime(mock_runtime)
    
    result = pattern_learner.analyze_patterns()
    
    assert result is None


# ============================================================================
# Test: JSON Validation
# ============================================================================

def test_json_validation_missing_required_field(pattern_learner):
    """
    Test that JSON validation fails when required fields are missing.
    """
    invalid_data = {
        "morning_routine": {},
        # Missing other required fields
    }
    
    with pytest.raises(ValueError, match="Missing required field"):
        pattern_learner._parse_and_validate(invalid_data)


def test_json_validation_invalid_field_types(pattern_learner):
    """
    Test that JSON validation fails when field types are wrong.
    """
    invalid_data = {
        "morning_routine": "not a dict",  # Should be dict
        "peak_coding_hours": [],
        "typical_project_switch_time": "90 minutes",
        "never_works_on": [],
        "frequently_forgets": [],
    }
    
    with pytest.raises(ValueError, match="must be a dictionary"):
        pattern_learner._parse_and_validate(invalid_data)


def test_json_validation_valid_data(pattern_learner, sample_behavioral_data):
    """
    Test that valid JSON data is parsed correctly.
    """
    result = pattern_learner._parse_and_validate(sample_behavioral_data)
    
    assert isinstance(result, BehavioralModel)
    assert result.morning_routine["typical_start_time"] == "08:30"
    assert result.peak_coding_hours == ["10:00-12:00", "14:00-17:00"]
    assert result.typical_project_switch_time == "90 minutes"
    assert result.never_works_on == ["weekends after 6pm"]
    assert result.frequently_forgets == ["commit messages", "closing files"]


# ============================================================================
# Test: Atomic Write
# ============================================================================

def test_atomic_write_to_behavioral_model_json(pattern_learner, sample_behavioral_data):
    """
    Test that behavioral model is written atomically to behavioral_model.json.
    """
    behavioral_model = pattern_learner._parse_and_validate(sample_behavioral_data)
    
    # Save the model
    pattern_learner._save_behavioral_model(behavioral_model)
    
    # Verify file exists
    assert pattern_learner.behavioral_model_file.exists()
    
    # Verify content
    with open(pattern_learner.behavioral_model_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    
    assert saved_data["peak_coding_hours"] == ["10:00-12:00", "14:00-17:00"]
    assert saved_data["typical_project_switch_time"] == "90 minutes"
    assert "generated_at" in saved_data


def test_atomic_write_no_temp_files_left(pattern_learner, sample_behavioral_data):
    """
    Test that atomic write doesn't leave temp files behind.
    """
    behavioral_model = pattern_learner._parse_and_validate(sample_behavioral_data)
    
    # Save the model
    pattern_learner._save_behavioral_model(behavioral_model)
    
    # Check for temp files
    state_dir = pattern_learner.state_dir
    temp_files = list(state_dir.glob(".behavioral_model_*.tmp"))
    
    assert len(temp_files) == 0, "Temp files should be cleaned up"


# ============================================================================
# Test: Load Behavioral Model
# ============================================================================

def test_load_behavioral_model_success(pattern_learner, temp_workspace, sample_behavioral_data):
    """
    Test loading an existing behavioral model from disk.
    """
    # Create behavioral_model.json
    model_file = temp_workspace / ".ankita" / "state" / "behavioral_model.json"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    
    model_dict = {
        "generated_at": datetime.now().isoformat(),
        **sample_behavioral_data,
    }
    model_file.write_text(json.dumps(model_dict), encoding="utf-8")
    
    # Load the model
    result = pattern_learner.load_behavioral_model()
    
    assert result is not None
    assert result.peak_coding_hours == ["10:00-12:00", "14:00-17:00"]
    assert result.typical_project_switch_time == "90 minutes"


def test_load_behavioral_model_missing_file(pattern_learner):
    """
    Test loading when behavioral_model.json doesn't exist.
    """
    result = pattern_learner.load_behavioral_model()
    
    assert result is None


def test_load_behavioral_model_corrupted_file(pattern_learner, temp_workspace):
    """
    Test loading when behavioral_model.json is corrupted.
    """
    # Create corrupted behavioral_model.json
    model_file = temp_workspace / ".ankita" / "state" / "behavioral_model.json"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("not valid json{{{", encoding="utf-8")
    
    result = pattern_learner.load_behavioral_model()
    
    assert result is None


# ============================================================================
# Test: Runtime Attachment
# ============================================================================

def test_attach_runtime(pattern_learner, mock_runtime):
    """
    Test that runtime can be attached to the learner.
    """
    assert pattern_learner._runtime is None
    
    pattern_learner.attach_runtime(mock_runtime)
    
    assert pattern_learner._runtime is mock_runtime


# ============================================================================
# Test: Load Recent Patterns
# ============================================================================

def test_load_recent_patterns_filters_by_date(pattern_learner, temp_workspace):
    """
    Test that _load_recent_patterns only loads patterns from last N weeks.
    """
    # Create patterns with various ages
    now = datetime.now()
    patterns = []
    
    # Old pattern (5 weeks ago)
    patterns.append({
        "timestamp": (now - timedelta(weeks=5)).isoformat(),
        "interaction_type": "code",
        "duration_sec": 60,
        "tools_used": ["tool"],
        "context": "old",
    })
    
    # Recent patterns (1-3 weeks ago)
    for i in range(3):
        patterns.append({
            "timestamp": (now - timedelta(weeks=i + 1)).isoformat(),
            "interaction_type": "code",
            "duration_sec": 60,
            "tools_used": ["tool"],
            "context": f"recent {i}",
        })
    
    # Write patterns to file
    patterns_file = temp_workspace / ".ankita" / "state" / "patterns.jsonl"
    patterns_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(patterns_file, "w", encoding="utf-8") as f:
        for pattern in patterns:
            f.write(json.dumps(pattern) + "\n")
    
    # Load recent patterns (last 4 weeks)
    recent = pattern_learner._load_recent_patterns(weeks=4)
    
    # Should only have 3 patterns (the recent ones)
    assert len(recent) == 3
    
    # Verify old pattern is not included
    contexts = [p["context"] for p in recent]
    assert "old" not in contexts


def test_load_recent_patterns_handles_missing_file(pattern_learner):
    """
    Test that _load_recent_patterns handles missing file gracefully.
    """
    result = pattern_learner._load_recent_patterns(weeks=4)
    
    assert result == []


def test_load_recent_patterns_skips_malformed_lines(pattern_learner, temp_workspace):
    """
    Test that _load_recent_patterns skips malformed JSON lines.
    """
    # Create patterns with one malformed line
    now = datetime.now()
    good_pattern = {
        "timestamp": (now - timedelta(days=10)).isoformat(),
        "interaction_type": "code",
        "duration_sec": 60,
        "tools_used": ["tool"],
        "context": "good",
    }
    
    # Write patterns to file
    patterns_file = temp_workspace / ".ankita" / "state" / "patterns.jsonl"
    patterns_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(patterns_file, "w", encoding="utf-8") as f:
        f.write("not valid json{{{" + "\n")
        f.write(json.dumps(good_pattern) + "\n")
    
    # Load recent patterns (should skip malformed line)
    recent = pattern_learner._load_recent_patterns(weeks=4)
    
    # Should only have 1 pattern (the good one)
    assert len(recent) == 1
    assert recent[0]["context"] == "good"
