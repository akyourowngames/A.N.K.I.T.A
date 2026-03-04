"""
Property-based tests for behavioral fingerprint recording.

Tests that all interactions result in complete fingerprint records with all
required fields. Uses Hypothesis for property-based testing.

**Property 6: Fingerprint Recording Completeness**

*For any* interaction with valid parameters (interaction_type, duration, tools_used, context),
recording a fingerprint SHALL:
1. Create a new entry in patterns.jsonl
2. Include all required fields: timestamp, interaction_type, duration_sec, tools_used, context
3. Preserve all field values exactly as provided
4. Use valid JSON format that can be parsed

**Validates: Requirements 3.1, 3.2**
"""
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytest
from hypothesis import given, strategies as st

from tools.behavioral_pattern_learner import BehavioralPatternLearner

# ============================================================================
# Strategies for generating valid interaction parameters
# ============================================================================


@st.composite
def valid_interaction_type(draw):
    """Generate valid interaction types."""
    return draw(st.sampled_from(["code", "write", "search", "system"]))


@st.composite
def valid_duration(draw):
    """Generate valid duration in seconds (0 to 2 hours)."""
    return draw(st.integers(min_value=0, max_value=7200))


@st.composite
def valid_tools_list(draw):
    """Generate valid list of tool names."""
    tool_names = st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"),
        min_size=1,
        max_size=30
    )
    return draw(st.lists(tool_names, min_size=0, max_size=10))


@st.composite
def valid_context_string(draw):
    """Generate valid context description."""
    return draw(st.text(min_size=0, max_size=200))


@st.composite
def valid_interaction_params(draw):
    """Generate a complete set of valid interaction parameters."""
    return {
        "interaction_type": draw(valid_interaction_type()),
        "duration_sec": draw(valid_duration()),
        "tools_used": draw(valid_tools_list()),
        "context": draw(valid_context_string())
    }


# ============================================================================
# Property Tests
# ============================================================================


@given(params=valid_interaction_params())
def test_property_fingerprint_recording_creates_entry(params: Dict[str, Any]):
    """
    Property: Recording a fingerprint SHALL create a new entry in patterns.jsonl.
    
    For any valid interaction parameters, calling record_fingerprint should:
    1. Create or append to patterns.jsonl
    2. Add exactly one new line to the file
    
    **Validates: Requirement 3.1**
    """
    # Create temporary workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_root = Path(tmpdir)
        learner = BehavioralPatternLearner(workspace_root)
        
        # Count lines before recording
        patterns_file = workspace_root / ".ankita" / "state" / "patterns.jsonl"
        lines_before = 0
        if patterns_file.exists():
            with open(patterns_file, "r", encoding="utf-8") as f:
                lines_before = sum(1 for _ in f)
        
        # Record fingerprint
        learner.record_fingerprint(
            interaction_type=params["interaction_type"],
            duration_sec=params["duration_sec"],
            tools_used=params["tools_used"],
            context=params["context"]
        )
        
        # Verify file exists and has one more line
        assert patterns_file.exists(), "patterns.jsonl should be created"
        
        with open(patterns_file, "r", encoding="utf-8") as f:
            lines_after = sum(1 for _ in f)
        
        assert lines_after == lines_before + 1, "Exactly one line should be added"


@given(params=valid_interaction_params())
def test_property_fingerprint_contains_all_required_fields(params: Dict[str, Any]):
    """
    Property: Recorded fingerprint SHALL include all required fields.
    
    For any valid interaction parameters, the recorded fingerprint must contain:
    - timestamp (ISO format datetime string)
    - interaction_type (exactly as provided)
    - duration_sec (exactly as provided)
    - tools_used (exactly as provided)
    - context (exactly as provided)
    
    **Validates: Requirement 3.2**
    """
    # Create temporary workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_root = Path(tmpdir)
        learner = BehavioralPatternLearner(workspace_root)
        
        # Record fingerprint
        before_timestamp = datetime.now()
        learner.record_fingerprint(
            interaction_type=params["interaction_type"],
            duration_sec=params["duration_sec"],
            tools_used=params["tools_used"],
            context=params["context"]
        )
        after_timestamp = datetime.now()
        
        # Read the recorded fingerprint
        patterns_file = workspace_root / ".ankita" / "state" / "patterns.jsonl"
        with open(patterns_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        assert len(lines) == 1, "Should have exactly one fingerprint"
        
        # Parse JSON
        fingerprint = json.loads(lines[0])
        
        # Verify all required fields are present
        required_fields = ["timestamp", "interaction_type", "duration_sec", "tools_used", "context"]
        for field in required_fields:
            assert field in fingerprint, f"Field '{field}' must be present"
        
        # Verify field values match input
        assert fingerprint["interaction_type"] == params["interaction_type"]
        assert fingerprint["duration_sec"] == params["duration_sec"]
        assert fingerprint["tools_used"] == params["tools_used"]
        assert fingerprint["context"] == params["context"]
        
        # Verify timestamp is valid ISO format and within reasonable time window
        timestamp = datetime.fromisoformat(fingerprint["timestamp"])
        assert before_timestamp <= timestamp <= after_timestamp, "Timestamp should be current time"


@given(params=valid_interaction_params())
def test_property_fingerprint_is_valid_json(params: Dict[str, Any]):
    """
    Property: Recorded fingerprint SHALL be valid JSON.
    
    For any valid interaction parameters, the recorded fingerprint must:
    1. Be parseable as JSON
    2. Not contain syntax errors
    3. Be on a single line (JSONL format)
    
    **Validates: Requirement 3.1**
    """
    # Create temporary workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_root = Path(tmpdir)
        learner = BehavioralPatternLearner(workspace_root)
        
        # Record fingerprint
        learner.record_fingerprint(
            interaction_type=params["interaction_type"],
            duration_sec=params["duration_sec"],
            tools_used=params["tools_used"],
            context=params["context"]
        )
        
        # Read the recorded line
        patterns_file = workspace_root / ".ankita" / "state" / "patterns.jsonl"
        with open(patterns_file, "r", encoding="utf-8") as f:
            line = f.readline().strip()
        
        # Should not contain newlines (single line)
        assert "\n" not in line, "Fingerprint should be on a single line"
        
        # Should be valid JSON
        try:
            fingerprint = json.loads(line)
            assert isinstance(fingerprint, dict), "Fingerprint should be a JSON object"
        except json.JSONDecodeError as e:
            pytest.fail(f"Fingerprint is not valid JSON: {e}")


@given(params_list=st.lists(valid_interaction_params(), min_size=1, max_size=20))
def test_property_multiple_fingerprints_all_recorded(params_list: List[Dict[str, Any]]):
    """
    Property: Multiple fingerprints SHALL all be recorded independently.
    
    For any sequence of valid interaction parameters, recording multiple fingerprints should:
    1. Create one entry per fingerprint
    2. Preserve all entries in order
    3. Not overwrite or corrupt previous entries
    
    **Validates: Requirement 3.1**
    """
    # Create temporary workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_root = Path(tmpdir)
        learner = BehavioralPatternLearner(workspace_root)
        
        # Record all fingerprints
        for params in params_list:
            learner.record_fingerprint(
                interaction_type=params["interaction_type"],
                duration_sec=params["duration_sec"],
                tools_used=params["tools_used"],
                context=params["context"]
            )
        
        # Read all recorded fingerprints
        patterns_file = workspace_root / ".ankita" / "state" / "patterns.jsonl"
        with open(patterns_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        # Verify count matches
        assert len(lines) == len(params_list), "All fingerprints should be recorded"
        
        # Verify each fingerprint is valid and matches input
        for i, (line, params) in enumerate(zip(lines, params_list)):
            fingerprint = json.loads(line.strip())
            
            # Verify all required fields present
            assert "timestamp" in fingerprint
            assert "interaction_type" in fingerprint
            assert "duration_sec" in fingerprint
            assert "tools_used" in fingerprint
            assert "context" in fingerprint
            
            # Verify values match
            assert fingerprint["interaction_type"] == params["interaction_type"]
            assert fingerprint["duration_sec"] == params["duration_sec"]
            assert fingerprint["tools_used"] == params["tools_used"]
            assert fingerprint["context"] == params["context"]


@given(params=valid_interaction_params())
def test_property_fingerprint_appends_not_overwrites(params: Dict[str, Any]):
    """
    Property: Recording fingerprints SHALL append, not overwrite.
    
    For any valid interaction parameters, recording a new fingerprint should:
    1. Preserve all existing fingerprints
    2. Append the new fingerprint to the end
    3. Not modify or delete existing entries
    
    **Validates: Requirement 3.1**
    """
    # Create temporary workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_root = Path(tmpdir)
        learner = BehavioralPatternLearner(workspace_root)
        
        # Record first fingerprint
        first_params = {
            "interaction_type": "code",
            "duration_sec": 100,
            "tools_used": ["tool1"],
            "context": "first interaction"
        }
        learner.record_fingerprint(**first_params)
        
        # Read first fingerprint
        patterns_file = workspace_root / ".ankita" / "state" / "patterns.jsonl"
        with open(patterns_file, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        first_fingerprint = json.loads(first_line)
        
        # Record second fingerprint
        learner.record_fingerprint(
            interaction_type=params["interaction_type"],
            duration_sec=params["duration_sec"],
            tools_used=params["tools_used"],
            context=params["context"]
        )
        
        # Read all fingerprints
        with open(patterns_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        assert len(lines) == 2, "Should have two fingerprints"
        
        # Verify first fingerprint is unchanged
        first_fingerprint_after = json.loads(lines[0].strip())
        assert first_fingerprint_after == first_fingerprint, "First fingerprint should be unchanged"
        
        # Verify second fingerprint is correct
        second_fingerprint = json.loads(lines[1].strip())
        assert second_fingerprint["interaction_type"] == params["interaction_type"]
        assert second_fingerprint["duration_sec"] == params["duration_sec"]
        assert second_fingerprint["tools_used"] == params["tools_used"]
        assert second_fingerprint["context"] == params["context"]


@given(
    params=valid_interaction_params(),
    num_recordings=st.integers(min_value=1, max_value=5)
)
def test_property_fingerprint_idempotent_structure(params: Dict[str, Any], num_recordings: int):
    """
    Property: Recording the same interaction multiple times SHALL produce consistent structure.
    
    For any valid interaction parameters, recording the same interaction multiple times should:
    1. Produce fingerprints with identical structure
    2. Have the same fields in each recording
    3. Preserve field types consistently
    
    Note: Timestamps will differ, but structure should be identical.
    
    **Validates: Requirement 3.2**
    """
    # Create temporary workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_root = Path(tmpdir)
        learner = BehavioralPatternLearner(workspace_root)
        
        # Record same interaction multiple times
        for _ in range(num_recordings):
            learner.record_fingerprint(
                interaction_type=params["interaction_type"],
                duration_sec=params["duration_sec"],
                tools_used=params["tools_used"],
                context=params["context"]
            )
        
        # Read all fingerprints
        patterns_file = workspace_root / ".ankita" / "state" / "patterns.jsonl"
        with open(patterns_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        assert len(lines) == num_recordings
        
        # Parse all fingerprints
        fingerprints = [json.loads(line.strip()) for line in lines]
        
        # Verify all have same structure (same keys)
        first_keys = set(fingerprints[0].keys())
        for fingerprint in fingerprints[1:]:
            assert set(fingerprint.keys()) == first_keys, "All fingerprints should have same structure"
        
        # Verify all have same field types (except timestamp which varies)
        for fingerprint in fingerprints:
            assert isinstance(fingerprint["timestamp"], str)
            assert isinstance(fingerprint["interaction_type"], str)
            assert isinstance(fingerprint["duration_sec"], int)
            assert isinstance(fingerprint["tools_used"], list)
            assert isinstance(fingerprint["context"], str)
            
            # Verify values match input (except timestamp)
            assert fingerprint["interaction_type"] == params["interaction_type"]
            assert fingerprint["duration_sec"] == params["duration_sec"]
            assert fingerprint["tools_used"] == params["tools_used"]
            assert fingerprint["context"] == params["context"]
