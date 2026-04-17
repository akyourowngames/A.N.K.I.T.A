"""
Unit tests for IntentionEngine.

Tests:
- LLM failure fallback to previous intent.json
- JSON validation
- Schedule timing (startup + every 6 hours)

Requirements: 2.6
"""
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proactive_models import IntentModel
from tools.intention_engine import IntentionEngine


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        yield workspace


@pytest.fixture
def intention_engine(temp_workspace):
    """Create an IntentionEngine instance with temp workspace."""
    engine = IntentionEngine(temp_workspace)
    return engine


@pytest.fixture
def mock_runtime():
    """Create a mock LLM runtime."""
    runtime = MagicMock()
    return runtime


@pytest.fixture
def sample_intent_data():
    """Sample valid intent data."""
    return {
        "active_projects": ["ankita-proactive", "helper-id"],
        "open_loops": ["finish report", "review PR #42"],
        "today_deadlines": ["submit proposal by 5pm"],
        "focus_mode": "coding",
        "recommended_music": "lofi",
        "suggested_first_action": "Continue working on the proactive spec",
    }


@pytest.fixture
def sample_context():
    """Sample context data."""
    return {
        "timestamp": datetime.now().isoformat(),
        "chromadb_memories": [
            {"text": "Working on proactive system", "role": "user", "timestamp": 1234567890},
        ],
        "pending_tasks": [
            {"title": "Finish spec", "priority": "high", "deadline": "2024-12-25", "status": "pending"},
        ],
        "cron_jobs_24h": [],
        "recent_git_commits": ["abc123 Add IntentionEngine"],
        "watchdog_states": {},
    }


# ============================================================================
# Test: LLM Failure Fallback
# ============================================================================

def test_llm_failure_uses_previous_intent(intention_engine, temp_workspace, mock_runtime):
    """
    Test that when LLM call fails, the engine falls back to previous intent.json.
    
    Requirement 2.6: IF the IntentionEngine fails to generate an intent model,
    THEN THE system SHALL use the previous intent model and log an error.
    """
    # Create a previous intent.json
    previous_intent = {
        "timestamp": "2024-01-15T08:00:00",
        "active_projects": ["old-project"],
        "open_loops": ["old task"],
        "today_deadlines": [],
        "focus_mode": "idle",
        "recommended_music": "none",
        "suggested_first_action": "Check emails",
    }
    
    intent_file = temp_workspace / ".ankita" / "state" / "intent.json"
    intent_file.parent.mkdir(parents=True, exist_ok=True)
    intent_file.write_text(json.dumps(previous_intent), encoding="utf-8")
    
    # Attach runtime that will fail
    intention_engine.attach_runtime(mock_runtime)
    
    # Mock _call_llm_for_intent to raise an exception
    with patch.object(intention_engine, "_call_llm_for_intent", side_effect=Exception("LLM API error")):
        with patch.object(intention_engine, "_gather_context", return_value={}):
            result = intention_engine.generate_intent_model()
    
    # Should return the previous intent model
    assert result is not None
    assert result.active_projects == ["old-project"]
    assert result.focus_mode == "idle"
    assert result.suggested_first_action == "Check emails"


def test_llm_failure_with_no_previous_intent(intention_engine, mock_runtime):
    """
    Test that when LLM fails and no previous intent exists, returns None.
    """
    intention_engine.attach_runtime(mock_runtime)
    
    # Mock _call_llm_for_intent to raise an exception
    with patch.object(intention_engine, "_call_llm_for_intent", side_effect=Exception("LLM API error")):
        with patch.object(intention_engine, "_gather_context", return_value={}):
            result = intention_engine.generate_intent_model()
    
    # Should return None when no previous intent exists
    assert result is None


# ============================================================================
# Test: JSON Validation
# ============================================================================

def test_json_validation_missing_required_field(intention_engine):
    """
    Test that JSON validation fails when required fields are missing.
    """
    invalid_data = {
        "active_projects": ["project1"],
        # Missing other required fields
    }
    
    with pytest.raises(ValueError, match="Missing required field"):
        intention_engine._parse_and_validate(invalid_data)


def test_json_validation_invalid_field_types(intention_engine):
    """
    Test that JSON validation fails when field types are wrong.
    """
    invalid_data = {
        "active_projects": "not a list",  # Should be list
        "open_loops": [],
        "today_deadlines": [],
        "focus_mode": "coding",
        "recommended_music": "lofi",
        "suggested_first_action": "Do something",
    }
    
    with pytest.raises(ValueError, match="must be a list"):
        intention_engine._parse_and_validate(invalid_data)


def test_json_validation_invalid_focus_mode(intention_engine, sample_intent_data):
    """
    Test that invalid focus_mode is corrected to 'idle'.
    """
    sample_intent_data["focus_mode"] = "invalid_mode"
    
    result = intention_engine._parse_and_validate(sample_intent_data)
    
    # Should default to 'idle'
    assert result.focus_mode == "idle"


def test_json_validation_invalid_music(intention_engine, sample_intent_data):
    """
    Test that invalid recommended_music is corrected to 'none'.
    """
    sample_intent_data["recommended_music"] = "invalid_music"
    
    result = intention_engine._parse_and_validate(sample_intent_data)
    
    # Should default to 'none'
    assert result.recommended_music == "none"


def test_json_validation_valid_data(intention_engine, sample_intent_data):
    """
    Test that valid JSON data is parsed correctly.
    """
    result = intention_engine._parse_and_validate(sample_intent_data)
    
    assert isinstance(result, IntentModel)
    assert result.active_projects == ["ankita-proactive", "helper-id"]
    assert result.open_loops == ["finish report", "review PR #42"]
    assert result.today_deadlines == ["submit proposal by 5pm"]
    assert result.focus_mode == "coding"
    assert result.recommended_music == "lofi"
    assert result.suggested_first_action == "Continue working on the proactive spec"


# ============================================================================
# Test: Atomic Write
# ============================================================================

def test_atomic_write_to_intent_json(intention_engine, sample_intent_data):
    """
    Test that intent model is written atomically to intent.json.
    """
    intent_model = intention_engine._parse_and_validate(sample_intent_data)
    
    # Save the model
    intention_engine._save_intent_model(intent_model)
    
    # Verify file exists
    assert intention_engine.intent_file.exists()
    
    # Verify content
    with open(intention_engine.intent_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    
    assert saved_data["active_projects"] == ["ankita-proactive", "helper-id"]
    assert saved_data["focus_mode"] == "coding"
    assert "timestamp" in saved_data


def test_atomic_write_no_temp_files_left(intention_engine, sample_intent_data):
    """
    Test that atomic write doesn't leave temp files behind.
    """
    intent_model = intention_engine._parse_and_validate(sample_intent_data)
    
    # Save the model
    intention_engine._save_intent_model(intent_model)
    
    # Check for temp files
    state_dir = intention_engine.state_dir
    temp_files = list(state_dir.glob(".intent_*.tmp"))
    
    assert len(temp_files) == 0, "Temp files should be cleaned up"


# ============================================================================
# Test: Context Gathering
# ============================================================================

def test_gather_context_structure(intention_engine):
    """
    Test that _gather_context returns the expected structure.
    """
    # Mock all external dependencies (imports are inside the method)
    with patch("memory.MemoryStore", create=True) as mock_memory:
        with patch("tools.task_ops.task_op") as mock_task_op:
            with patch.object(IntentionEngine, "_load_scheduled_jobs") as mock_load_store:
                with patch("subprocess.run") as mock_subprocess:
                    with patch("watchdog_manager.get_instance", create=True) as mock_get_instance:
                        # Setup mocks
                        mock_memory.return_value.enabled = False
                        mock_task_op.return_value = {"status": "success", "tasks": []}
                        mock_load_store.return_value = {"jobs": []}
                        mock_subprocess.return_value.returncode = 1  # No git repo
                        mock_get_instance.return_value = None
                        
                        context = intention_engine._gather_context()
    
    # Verify structure
    assert "timestamp" in context
    assert "chromadb_memories" in context
    assert "pending_tasks" in context
    assert "cron_jobs_24h" in context
    assert "recent_git_commits" in context
    assert "watchdog_states" in context
    
    # Verify types
    assert isinstance(context["chromadb_memories"], list)
    assert isinstance(context["pending_tasks"], list)
    assert isinstance(context["cron_jobs_24h"], list)
    assert isinstance(context["recent_git_commits"], list)
    assert isinstance(context["watchdog_states"], dict)


# ============================================================================
# Test: Load Intent Model
# ============================================================================

def test_load_intent_model_success(intention_engine, temp_workspace, sample_intent_data):
    """
    Test loading an existing intent model from disk.
    """
    # Create intent.json
    intent_file = temp_workspace / ".ankita" / "state" / "intent.json"
    intent_file.parent.mkdir(parents=True, exist_ok=True)
    
    intent_dict = {
        "timestamp": datetime.now().isoformat(),
        **sample_intent_data,
    }
    intent_file.write_text(json.dumps(intent_dict), encoding="utf-8")
    
    # Load the model
    result = intention_engine.load_intent_model()
    
    assert result is not None
    assert result.active_projects == ["ankita-proactive", "helper-id"]
    assert result.focus_mode == "coding"


def test_load_intent_model_missing_file(intention_engine):
    """
    Test loading when intent.json doesn't exist.
    """
    result = intention_engine.load_intent_model()
    
    assert result is None


def test_load_intent_model_corrupted_file(intention_engine, temp_workspace):
    """
    Test loading when intent.json is corrupted.
    """
    # Create corrupted intent.json
    intent_file = temp_workspace / ".ankita" / "state" / "intent.json"
    intent_file.parent.mkdir(parents=True, exist_ok=True)
    intent_file.write_text("not valid json{{{", encoding="utf-8")
    
    result = intention_engine.load_intent_model()
    
    assert result is None


# ============================================================================
# Test: Runtime Attachment
# ============================================================================

def test_attach_runtime(intention_engine, mock_runtime):
    """
    Test that runtime can be attached to the engine.
    """
    assert intention_engine._runtime is None
    
    intention_engine.attach_runtime(mock_runtime)
    
    assert intention_engine._runtime is mock_runtime


def test_generate_without_runtime(intention_engine):
    """
    Test that generate_intent_model fails gracefully without runtime.
    """
    result = intention_engine.generate_intent_model()
    
    assert result is None


# ============================================================================
# Test: Schedule Timing (Startup + Every 6 Hours)
# ============================================================================

def test_schedule_timing_startup_call(intention_engine, mock_runtime, sample_intent_data):
    """
    Test that IntentionEngine can be called at startup to generate initial intent model.
    
    Requirement 2.1: THE IntentionEngine SHALL run at system startup and every 6 hours thereafter.
    
    This tests the startup scenario where the engine is called for the first time.
    """
    intention_engine.attach_runtime(mock_runtime)
    
    # Mock the LLM call to return valid intent data
    with patch.object(intention_engine, "_call_llm_for_intent", return_value=sample_intent_data):
        with patch.object(intention_engine, "_gather_context", return_value={}):
            result = intention_engine.generate_intent_model()
    
    # Should successfully generate intent model on startup
    assert result is not None
    assert isinstance(result, IntentModel)
    assert result.active_projects == ["ankita-proactive", "helper-id"]
    
    # Verify intent.json was created
    assert intention_engine.intent_file.exists()


def test_schedule_timing_repeated_calls(intention_engine, mock_runtime, sample_intent_data):
    """
    Test that IntentionEngine can be called repeatedly (simulating 6-hour schedule).
    
    Requirement 2.1: THE IntentionEngine SHALL run at system startup and every 6 hours thereafter.
    
    This tests that the engine can be called multiple times and each call produces
    a fresh intent model with updated timestamps.
    """
    intention_engine.attach_runtime(mock_runtime)
    
    # Mock the LLM call to return valid intent data
    with patch.object(intention_engine, "_call_llm_for_intent", return_value=sample_intent_data):
        with patch.object(intention_engine, "_gather_context", return_value={}):
            # First call (startup)
            result1 = intention_engine.generate_intent_model()
            timestamp1 = result1.timestamp
            
            # Simulate time passing (6 hours)
            import time
            time.sleep(0.1)  # Small delay to ensure different timestamps
            
            # Second call (6 hours later)
            result2 = intention_engine.generate_intent_model()
            timestamp2 = result2.timestamp
            
            # Third call (12 hours later)
            time.sleep(0.1)
            result3 = intention_engine.generate_intent_model()
            timestamp3 = result3.timestamp
    
    # All calls should succeed
    assert result1 is not None
    assert result2 is not None
    assert result3 is not None
    
    # Each call should produce a fresh timestamp
    assert timestamp2 > timestamp1
    assert timestamp3 > timestamp2
    
    # Each call should update the intent.json file
    assert intention_engine.intent_file.exists()
    
    # Load the final intent model and verify it's the most recent
    loaded = intention_engine.load_intent_model()
    assert loaded is not None
    assert loaded.timestamp == timestamp3


def test_schedule_timing_timestamp_freshness(intention_engine, mock_runtime, sample_intent_data):
    """
    Test that each intent model generation includes a fresh timestamp.
    
    Requirement 2.3: THE IntentionEngine SHALL produce a Daily Intent Model and save it to .ankita/state/intent.json
    
    This verifies that timestamps are updated on each generation, ensuring the intent
    model reflects the current time of generation.
    """
    intention_engine.attach_runtime(mock_runtime)
    
    # Mock the LLM call
    with patch.object(intention_engine, "_call_llm_for_intent", return_value=sample_intent_data):
        with patch.object(intention_engine, "_gather_context", return_value={}):
            # Generate intent model
            before_generation = datetime.now()
            result = intention_engine.generate_intent_model()
            after_generation = datetime.now()
    
    # Timestamp should be between before and after
    assert result is not None
    assert before_generation <= result.timestamp <= after_generation
    
    # Verify timestamp is saved to file
    with open(intention_engine.intent_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    
    assert "timestamp" in saved_data
    saved_timestamp = datetime.fromisoformat(saved_data["timestamp"])
    assert before_generation <= saved_timestamp <= after_generation


# ============================================================================
# Test: Prompt Building
# ============================================================================

def test_build_intent_prompt_includes_all_sections(intention_engine, sample_context):
    """
    Test that the prompt includes all context sections.
    """
    prompt = intention_engine._build_intent_prompt(sample_context)
    
    # Check for section headers
    assert "Recent Memories" in prompt
    assert "Pending Tasks" in prompt
    assert "Scheduled Jobs" in prompt
    assert "Recent Git Activity" in prompt
    assert "System Watchdogs" in prompt
    
    # Check for output format
    assert "OUTPUT FORMAT" in prompt
    assert "active_projects" in prompt
    assert "focus_mode" in prompt


def test_format_memories_empty(intention_engine):
    """
    Test formatting empty memories list.
    """
    result = intention_engine._format_memories([])
    
    assert "(Memory system currently being rebuilt)" in result


def test_format_tasks_empty(intention_engine):
    """
    Test formatting empty tasks list.
    """
    result = intention_engine._format_tasks([])
    
    assert "(No pending tasks)" in result


def test_format_cron_jobs_empty(intention_engine):
    """
    Test formatting empty cron jobs list.
    """
    result = intention_engine._format_cron_jobs([])
    
    assert "(No scheduled jobs in next 24 hours)" in result


def test_format_git_commits_empty(intention_engine):
    """
    Test formatting empty git commits list.
    """
    result = intention_engine._format_git_commits([])
    
    assert "(No recent git activity)" in result


def test_format_watchdog_states_empty(intention_engine):
    """
    Test formatting empty watchdog states.
    """
    result = intention_engine._format_watchdog_states({})
    
    assert "(No watchdog data)" in result
