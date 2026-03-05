"""
Property-based tests for ProactiveStatePersistence

Tests universal properties that should hold across all valid state configurations.
Uses Hypothesis for property-based testing.

**Validates: Requirements 1.2, 1.3**
"""
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, strategies as st

from tools.proactive_state import ProactiveStatePersistence


# Strategy for generating valid state values
@st.composite
def valid_state_values(draw):
    """Generate valid values for state fields."""
    return draw(
        st.one_of(
            st.none(),
            st.booleans(),
            st.integers(min_value=0, max_value=100),
            st.text(min_size=0, max_size=100),
            st.lists(st.text(min_size=1, max_size=50), max_size=20),
            st.dictionaries(
                st.text(min_size=1, max_size=20),
                st.one_of(st.booleans(), st.integers(min_value=0, max_value=100)),
                max_size=10,
            ),
        )
    )


# Strategy for generating valid proactive states
@st.composite
def valid_proactive_state(draw):
    """
    Generate a valid proactive state dictionary.
    
    Ensures all required fields are present with appropriate types.
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


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@given(state=valid_proactive_state())
def test_property_state_persistence_round_trip(state: Dict[str, Any]):
    """
    **Property 1: State Persistence Round-Trip**
    
    For any valid proactive state, saving then loading should produce an 
    equivalent state with all fields preserved.
    
    **Validates: Requirements 1.2, 1.3**
    
    This property ensures that:
    1. Any valid state can be saved to disk
    2. Loading the saved state produces an equivalent state
    3. All fields are preserved exactly (no data loss)
    4. The round-trip is idempotent (save-load-save-load produces same result)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        
        # Create persistence instance
        persistence = ProactiveStatePersistence(workspace)
        
        # Set the state directly (simulating a valid state)
        persistence._state = state.copy()
        
        # Save the state
        persistence.save_state()
        
        # Create a new instance and load the state
        persistence2 = ProactiveStatePersistence(workspace)
        loaded_state = persistence2.load_state()
        
        # Verify all fields are preserved
        assert loaded_state == state, (
            f"State round-trip failed!\n"
            f"Original: {state}\n"
            f"Loaded: {loaded_state}\n"
            f"Difference: {set(state.items()) ^ set(loaded_state.items())}"
        )
        
        # Verify idempotency: save-load again should produce same result
        persistence2.save_state()
        persistence3 = ProactiveStatePersistence(workspace)
        loaded_state2 = persistence3.load_state()
        
        assert loaded_state2 == state, (
            f"State round-trip is not idempotent!\n"
            f"First load: {loaded_state}\n"
            f"Second load: {loaded_state2}"
        )


@given(
    field_name=st.sampled_from([
        "last_morning_briefing_date",
        "last_insight_synthesis",
        "last_pattern_analysis",
        "last_intent_refresh",
        "dnd_active",
        "focus_mode",
    ]),
    field_value=valid_state_values(),
)
def test_property_update_field_persists(field_name: str, field_value: Any):
    """
    Property: Updating a field persists the change across instances.
    
    For any valid field name and value, updating the field should persist
    the change such that a new instance can read the updated value.
    
    **Validates: Requirements 1.3**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        
        # Create persistence instance and load initial state
        persistence = ProactiveStatePersistence(workspace)
        persistence.load_state()
        
        # Update the field
        persistence.update_field(field_name, field_value)
        
        # Create new instance and verify the field was persisted
        persistence2 = ProactiveStatePersistence(workspace)
        loaded_state = persistence2.load_state()
        
        assert loaded_state[field_name] == field_value, (
            f"Field '{field_name}' was not persisted correctly!\n"
            f"Expected: {field_value}\n"
            f"Got: {loaded_state[field_name]}"
        )


@given(notification_ids=st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=100))
def test_property_notification_ids_list_preserved(notification_ids: List[str]):
    """
    Property: Notification IDs list is preserved exactly.
    
    For any list of notification IDs, saving and loading should preserve
    the exact list with all elements in order.
    
    **Validates: Requirements 1.2, 1.3**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        
        persistence = ProactiveStatePersistence(workspace)
        persistence.load_state()
        
        # Update notification IDs
        persistence.update_field("delivered_notification_ids", notification_ids)
        
        # Load in new instance
        persistence2 = ProactiveStatePersistence(workspace)
        loaded_state = persistence2.load_state()
        
        assert loaded_state["delivered_notification_ids"] == notification_ids, (
            f"Notification IDs list was not preserved!\n"
            f"Expected: {notification_ids}\n"
            f"Got: {loaded_state['delivered_notification_ids']}"
        )
        assert isinstance(loaded_state["delivered_notification_ids"], list), (
            "Notification IDs should be a list"
        )


@given(
    music_playing=st.booleans(),
    brightness=st.integers(min_value=0, max_value=100),
    notifications_muted=st.booleans(),
)
def test_property_environment_state_nested_preserved(
    music_playing: bool,
    brightness: int,
    notifications_muted: bool,
):
    """
    Property: Nested environment_state structure is preserved.
    
    For any valid environment state values, the nested structure should
    be preserved exactly across save/load cycles.
    
    **Validates: Requirements 1.2, 1.3**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        
        persistence = ProactiveStatePersistence(workspace)
        persistence.load_state()
        
        # Update environment state
        env_state = {
            "music_playing": music_playing,
            "brightness": brightness,
            "notifications_muted": notifications_muted,
        }
        persistence.update_field("environment_state", env_state)
        
        # Load in new instance
        persistence2 = ProactiveStatePersistence(workspace)
        loaded_state = persistence2.load_state()
        
        assert loaded_state["environment_state"] == env_state, (
            f"Environment state was not preserved!\n"
            f"Expected: {env_state}\n"
            f"Got: {loaded_state['environment_state']}"
        )
        assert isinstance(loaded_state["environment_state"], dict), (
            "Environment state should be a dictionary"
        )


@given(state=valid_proactive_state())
def test_property_multiple_save_load_cycles(state: Dict[str, Any]):
    """
    Property: Multiple save/load cycles preserve state integrity.
    
    For any valid state, performing multiple save/load cycles should
    always preserve the state exactly without degradation.
    
    **Validates: Requirements 1.2, 1.3**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        
        # Perform 5 save/load cycles
        current_state = state.copy()
        for i in range(5):
            persistence = ProactiveStatePersistence(workspace)
            persistence._state = current_state.copy()
            persistence.save_state()
            
            # Load in new instance
            persistence2 = ProactiveStatePersistence(workspace)
            loaded_state = persistence2.load_state()
            
            assert loaded_state == current_state, (
                f"State degraded after {i+1} cycles!\n"
                f"Expected: {current_state}\n"
                f"Got: {loaded_state}"
            )
            
            current_state = loaded_state


@given(state=valid_proactive_state())
def test_property_concurrent_instances_see_updates(state: Dict[str, Any]):
    """
    Property: Updates are visible to all instances after save.
    
    For any valid state, when one instance saves a state, all other
    instances should be able to load the updated state.
    
    **Validates: Requirements 1.3**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        
        # Create first instance and save state
        persistence1 = ProactiveStatePersistence(workspace)
        persistence1._state = state.copy()
        persistence1.save_state()
        
        # Create multiple instances and verify they all see the same state
        for i in range(3):
            persistence = ProactiveStatePersistence(workspace)
            loaded_state = persistence.load_state()
            
            assert loaded_state == state, (
                f"Instance {i+1} did not see the correct state!\n"
                f"Expected: {state}\n"
                f"Got: {loaded_state}"
            )
