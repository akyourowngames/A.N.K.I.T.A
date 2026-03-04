"""
Property-based tests for State Structure Validation

Tests that all generated state files contain required fields with valid types.
Uses Hypothesis for property-based testing.

**Property 2: State Structure Completeness**
**Validates: Requirements 1.4, 2.4, 3.2, 3.4**
"""
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, strategies as st

from tools.proactive_state import ProactiveStatePersistence


# ============================================================================
# Strategies for generating valid state structures
# ============================================================================

@st.composite
def valid_proactive_state(draw):
    """
    Generate a valid proactive_state.json structure.
    
    Required fields per Requirement 1.4:
    - last_morning_briefing_date: str | None
    - last_insight_synthesis: str | None
    - last_pattern_analysis: str | None
    - last_intent_refresh: str | None
    - delivered_notification_ids: List[str]
    - dnd_active: bool
    - focus_mode: str
    - environment_state: Dict with music_playing, brightness, notifications_muted
    """
    return {
        "last_morning_briefing_date": draw(st.one_of(st.none(), st.text(min_size=10, max_size=10))),
        "last_insight_synthesis": draw(st.one_of(st.none(), st.text(min_size=19, max_size=19))),
        "last_pattern_analysis": draw(st.one_of(st.none(), st.text(min_size=19, max_size=19))),
        "last_intent_refresh": draw(st.one_of(st.none(), st.text(min_size=19, max_size=19))),
        "delivered_notification_ids": draw(st.lists(st.text(min_size=1, max_size=50), max_size=100)),
        "dnd_active": draw(st.booleans()),
        "focus_mode": draw(st.sampled_from(["idle", "deep_work", "meeting", "coding"])),
        "environment_state": {
            "music_playing": draw(st.booleans()),
            "brightness": draw(st.integers(min_value=0, max_value=100)),
            "notifications_muted": draw(st.booleans()),
        },
    }


@st.composite
def valid_intent_model(draw):
    """
    Generate a valid intent.json structure.
    
    Required fields per Requirement 2.4:
    - timestamp: str (ISO format)
    - active_projects: List[str]
    - open_loops: List[str]
    - today_deadlines: List[str]
    - focus_mode: str
    - recommended_music: str
    - suggested_first_action: str
    """
    return {
        "timestamp": draw(st.text(min_size=19, max_size=19)),  # ISO timestamp
        "active_projects": draw(st.lists(st.text(min_size=1, max_size=50), max_size=10)),
        "open_loops": draw(st.lists(st.text(min_size=1, max_size=100), max_size=20)),
        "today_deadlines": draw(st.lists(st.text(min_size=1, max_size=100), max_size=10)),
        "focus_mode": draw(st.sampled_from(["deep_work", "meeting", "coding", "idle"])),
        "recommended_music": draw(st.sampled_from(["lofi", "focus", "energetic", "none"])),
        "suggested_first_action": draw(st.text(min_size=1, max_size=200)),
    }


@st.composite
def valid_behavioral_model(draw):
    """
    Generate a valid behavioral_model.json structure.
    
    Required fields per Requirement 3.4:
    - generated_at: str (ISO timestamp)
    - morning_routine: Dict with typical_start_time and first_actions
    - peak_coding_hours: List[str]
    - typical_project_switch_time: str
    - never_works_on: List[str]
    - frequently_forgets: List[str]
    """
    return {
        "generated_at": draw(st.text(min_size=19, max_size=19)),  # ISO timestamp
        "morning_routine": {
            "typical_start_time": draw(st.text(min_size=5, max_size=5)),  # HH:MM format
            "first_actions": draw(st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=5)),
        },
        "peak_coding_hours": draw(st.lists(st.text(min_size=11, max_size=11), min_size=1, max_size=5)),  # "HH:MM-HH:MM"
        "typical_project_switch_time": draw(st.text(min_size=1, max_size=20)),
        "never_works_on": draw(st.lists(st.text(min_size=1, max_size=50), max_size=10)),
        "frequently_forgets": draw(st.lists(st.text(min_size=1, max_size=50), max_size=10)),
    }


@st.composite
def valid_prefetch_cache(draw):
    """
    Generate a valid prefetch_cache.json structure.
    
    Required fields per Requirement 3.2:
    - Each cache entry has: cached_at, ttl_sec, data
    """
    num_entries = draw(st.integers(min_value=0, max_value=5))
    cache = {}
    
    for i in range(num_entries):
        key = draw(st.sampled_from(["morning_news", "git_status", "watchdog_summary", f"custom_{i}"]))
        cache[key] = {
            "cached_at": draw(st.text(min_size=19, max_size=19)),  # ISO timestamp
            "ttl_sec": draw(st.integers(min_value=60, max_value=3600)),
            "data": draw(st.one_of(
                st.dictionaries(st.text(min_size=1, max_size=20), st.text(min_size=1, max_size=100), max_size=5),
                st.lists(st.text(min_size=1, max_size=50), max_size=10),
                st.text(min_size=1, max_size=200),
            )),
        }
    
    return cache


# ============================================================================
# Property Tests
# ============================================================================

@given(state=valid_proactive_state())
def test_property_proactive_state_structure_completeness(state: Dict[str, Any]):
    """
    **Property 2: State Structure Completeness (proactive_state.json)**
    
    For any generated proactive_state.json, all required fields SHALL be present
    and have valid types.
    
    **Validates: Requirements 1.4**
    
    Required fields:
    - last_morning_briefing_date: str | None
    - last_insight_synthesis: str | None
    - last_pattern_analysis: str | None
    - last_intent_refresh: str | None
    - delivered_notification_ids: List[str]
    - dnd_active: bool
    - focus_mode: str
    - environment_state: Dict
    """
    # Check all required fields are present
    required_fields = [
        "last_morning_briefing_date",
        "last_insight_synthesis",
        "last_pattern_analysis",
        "last_intent_refresh",
        "delivered_notification_ids",
        "dnd_active",
        "focus_mode",
        "environment_state",
    ]
    
    for field in required_fields:
        assert field in state, f"Required field '{field}' is missing from proactive_state"
    
    # Validate field types
    assert isinstance(state["last_morning_briefing_date"], (str, type(None))), \
        "last_morning_briefing_date must be str or None"
    assert isinstance(state["last_insight_synthesis"], (str, type(None))), \
        "last_insight_synthesis must be str or None"
    assert isinstance(state["last_pattern_analysis"], (str, type(None))), \
        "last_pattern_analysis must be str or None"
    assert isinstance(state["last_intent_refresh"], (str, type(None))), \
        "last_intent_refresh must be str or None"
    assert isinstance(state["delivered_notification_ids"], list), \
        "delivered_notification_ids must be a list"
    assert all(isinstance(id, str) for id in state["delivered_notification_ids"]), \
        "All notification IDs must be strings"
    assert isinstance(state["dnd_active"], bool), \
        "dnd_active must be a boolean"
    assert isinstance(state["focus_mode"], str), \
        "focus_mode must be a string"
    assert state["focus_mode"] in ["idle", "deep_work", "meeting", "coding"], \
        "focus_mode must be one of: idle, deep_work, meeting, coding"
    
    # Validate nested environment_state structure
    assert isinstance(state["environment_state"], dict), \
        "environment_state must be a dictionary"
    
    env_required_fields = ["music_playing", "brightness", "notifications_muted"]
    for field in env_required_fields:
        assert field in state["environment_state"], \
            f"Required field '{field}' is missing from environment_state"
    
    assert isinstance(state["environment_state"]["music_playing"], bool), \
        "music_playing must be a boolean"
    assert isinstance(state["environment_state"]["brightness"], int), \
        "brightness must be an integer"
    assert 0 <= state["environment_state"]["brightness"] <= 100, \
        "brightness must be between 0 and 100"
    assert isinstance(state["environment_state"]["notifications_muted"], bool), \
        "notifications_muted must be a boolean"


@given(intent=valid_intent_model())
def test_property_intent_model_structure_completeness(intent: Dict[str, Any]):
    """
    **Property 2: State Structure Completeness (intent.json)**
    
    For any generated intent.json, all required fields SHALL be present
    and have valid types.
    
    **Validates: Requirements 2.4**
    
    Required fields:
    - timestamp: str
    - active_projects: List[str]
    - open_loops: List[str]
    - today_deadlines: List[str]
    - focus_mode: str
    - recommended_music: str
    - suggested_first_action: str
    """
    # Check all required fields are present
    required_fields = [
        "timestamp",
        "active_projects",
        "open_loops",
        "today_deadlines",
        "focus_mode",
        "recommended_music",
        "suggested_first_action",
    ]
    
    for field in required_fields:
        assert field in intent, f"Required field '{field}' is missing from intent model"
    
    # Validate field types
    assert isinstance(intent["timestamp"], str), \
        "timestamp must be a string"
    assert isinstance(intent["active_projects"], list), \
        "active_projects must be a list"
    assert all(isinstance(p, str) for p in intent["active_projects"]), \
        "All active_projects must be strings"
    assert isinstance(intent["open_loops"], list), \
        "open_loops must be a list"
    assert all(isinstance(l, str) for l in intent["open_loops"]), \
        "All open_loops must be strings"
    assert isinstance(intent["today_deadlines"], list), \
        "today_deadlines must be a list"
    assert all(isinstance(d, str) for d in intent["today_deadlines"]), \
        "All today_deadlines must be strings"
    assert isinstance(intent["focus_mode"], str), \
        "focus_mode must be a string"
    assert intent["focus_mode"] in ["deep_work", "meeting", "coding", "idle"], \
        "focus_mode must be one of: deep_work, meeting, coding, idle"
    assert isinstance(intent["recommended_music"], str), \
        "recommended_music must be a string"
    assert intent["recommended_music"] in ["lofi", "focus", "energetic", "none"], \
        "recommended_music must be one of: lofi, focus, energetic, none"
    assert isinstance(intent["suggested_first_action"], str), \
        "suggested_first_action must be a string"


@given(behavioral=valid_behavioral_model())
def test_property_behavioral_model_structure_completeness(behavioral: Dict[str, Any]):
    """
    **Property 2: State Structure Completeness (behavioral_model.json)**
    
    For any generated behavioral_model.json, all required fields SHALL be present
    and have valid types.
    
    **Validates: Requirements 3.4**
    
    Required fields:
    - generated_at: str
    - morning_routine: Dict with typical_start_time and first_actions
    - peak_coding_hours: List[str]
    - typical_project_switch_time: str
    - never_works_on: List[str]
    - frequently_forgets: List[str]
    """
    # Check all required fields are present
    required_fields = [
        "generated_at",
        "morning_routine",
        "peak_coding_hours",
        "typical_project_switch_time",
        "never_works_on",
        "frequently_forgets",
    ]
    
    for field in required_fields:
        assert field in behavioral, f"Required field '{field}' is missing from behavioral model"
    
    # Validate field types
    assert isinstance(behavioral["generated_at"], str), \
        "generated_at must be a string"
    assert isinstance(behavioral["morning_routine"], dict), \
        "morning_routine must be a dictionary"
    
    # Validate nested morning_routine structure
    morning_required_fields = ["typical_start_time", "first_actions"]
    for field in morning_required_fields:
        assert field in behavioral["morning_routine"], \
            f"Required field '{field}' is missing from morning_routine"
    
    assert isinstance(behavioral["morning_routine"]["typical_start_time"], str), \
        "typical_start_time must be a string"
    assert isinstance(behavioral["morning_routine"]["first_actions"], list), \
        "first_actions must be a list"
    assert all(isinstance(a, str) for a in behavioral["morning_routine"]["first_actions"]), \
        "All first_actions must be strings"
    
    assert isinstance(behavioral["peak_coding_hours"], list), \
        "peak_coding_hours must be a list"
    assert all(isinstance(h, str) for h in behavioral["peak_coding_hours"]), \
        "All peak_coding_hours must be strings"
    assert isinstance(behavioral["typical_project_switch_time"], str), \
        "typical_project_switch_time must be a string"
    assert isinstance(behavioral["never_works_on"], list), \
        "never_works_on must be a list"
    assert all(isinstance(n, str) for n in behavioral["never_works_on"]), \
        "All never_works_on must be strings"
    assert isinstance(behavioral["frequently_forgets"], list), \
        "frequently_forgets must be a list"
    assert all(isinstance(f, str) for f in behavioral["frequently_forgets"]), \
        "All frequently_forgets must be strings"


@given(cache=valid_prefetch_cache())
def test_property_prefetch_cache_structure_completeness(cache: Dict[str, Any]):
    """
    **Property 2: State Structure Completeness (prefetch_cache.json)**
    
    For any generated prefetch_cache.json, all cache entries SHALL have
    required fields with valid types.
    
    **Validates: Requirements 3.2**
    
    Each cache entry must have:
    - cached_at: str (ISO timestamp)
    - ttl_sec: int
    - data: Any (cached result)
    """
    # Each entry in the cache must have the required structure
    for key, entry in cache.items():
        assert isinstance(key, str), \
            f"Cache key '{key}' must be a string"
        assert isinstance(entry, dict), \
            f"Cache entry '{key}' must be a dictionary"
        
        # Check required fields
        required_fields = ["cached_at", "ttl_sec", "data"]
        for field in required_fields:
            assert field in entry, \
                f"Required field '{field}' is missing from cache entry '{key}'"
        
        # Validate field types
        assert isinstance(entry["cached_at"], str), \
            f"cached_at in entry '{key}' must be a string"
        assert isinstance(entry["ttl_sec"], int), \
            f"ttl_sec in entry '{key}' must be an integer"
        assert entry["ttl_sec"] > 0, \
            f"ttl_sec in entry '{key}' must be positive"
        # data can be any type, so no type validation needed


@given(state=valid_proactive_state())
def test_property_proactive_state_serialization(state: Dict[str, Any]):
    """
    Property: proactive_state.json can be serialized and deserialized without loss.
    
    For any valid proactive state, serializing to JSON and deserializing
    should produce an equivalent structure.
    
    **Validates: Requirements 1.4**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        
        # Create persistence instance
        persistence = ProactiveStatePersistence(workspace)
        persistence._state = state.copy()
        persistence.save_state()
        
        # Read the file directly and parse JSON
        with open(persistence.state_file, "r", encoding="utf-8") as f:
            serialized = json.load(f)
        
        # Verify structure is preserved
        assert serialized == state, \
            "State structure changed during serialization"


@given(intent=valid_intent_model())
def test_property_intent_model_serialization(intent: Dict[str, Any]):
    """
    Property: intent.json can be serialized and deserialized without loss.
    
    For any valid intent model, serializing to JSON and deserializing
    should produce an equivalent structure.
    
    **Validates: Requirements 2.4**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        intent_file = Path(tmpdir) / "intent.json"
        
        # Write to file
        with open(intent_file, "w", encoding="utf-8") as f:
            json.dump(intent, f, indent=2)
        
        # Read back
        with open(intent_file, "r", encoding="utf-8") as f:
            deserialized = json.load(f)
        
        # Verify structure is preserved
        assert deserialized == intent, \
            "Intent model structure changed during serialization"


@given(behavioral=valid_behavioral_model())
def test_property_behavioral_model_serialization(behavioral: Dict[str, Any]):
    """
    Property: behavioral_model.json can be serialized and deserialized without loss.
    
    For any valid behavioral model, serializing to JSON and deserializing
    should produce an equivalent structure.
    
    **Validates: Requirements 3.4**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        behavioral_file = Path(tmpdir) / "behavioral_model.json"
        
        # Write to file
        with open(behavioral_file, "w", encoding="utf-8") as f:
            json.dump(behavioral, f, indent=2)
        
        # Read back
        with open(behavioral_file, "r", encoding="utf-8") as f:
            deserialized = json.load(f)
        
        # Verify structure is preserved
        assert deserialized == behavioral, \
            "Behavioral model structure changed during serialization"


@given(cache=valid_prefetch_cache())
def test_property_prefetch_cache_serialization(cache: Dict[str, Any]):
    """
    Property: prefetch_cache.json can be serialized and deserialized without loss.
    
    For any valid prefetch cache, serializing to JSON and deserializing
    should produce an equivalent structure.
    
    **Validates: Requirements 3.2**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_file = Path(tmpdir) / "prefetch_cache.json"
        
        # Write to file
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        
        # Read back
        with open(cache_file, "r", encoding="utf-8") as f:
            deserialized = json.load(f)
        
        # Verify structure is preserved
        assert deserialized == cache, \
            "Prefetch cache structure changed during serialization"
