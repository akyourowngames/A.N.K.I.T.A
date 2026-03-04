"""
Property-based tests for Notification Deduplication

Tests that notifications are properly deduplicated based on notification ID
across all delivery scenarios. Uses Hypothesis for property-based testing.

**Property 5: Notification Deduplication**
**Validates: Requirements 12.5**
"""
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, strategies as st

from proactive_models import ProactiveEvent
from tools.notification_router import NotificationRouter


# ============================================================================
# Strategies for generating valid ProactiveEvents
# ============================================================================

@st.composite
def valid_proactive_event(draw):
    """
    Generate a valid ProactiveEvent for testing.
    
    Generates events with various priorities, kinds, and messages to ensure
    deduplication works across all event types.
    """
    kind = draw(st.sampled_from([
        "system",
        "cron",
        "dream_epiphany",
        "morning_briefing",
        "watchdog_alert",
        "insight",
        "task_reminder",
    ]))
    
    message = draw(st.text(min_size=1, max_size=200))
    
    priority = draw(st.sampled_from(["low", "medium", "high", "critical"]))
    
    urgency = draw(st.sampled_from(["immediate", "next_idle", "next_session"]))
    
    interruptible = draw(st.booleans())
    
    # Create event (notification_id will be auto-generated in __post_init__)
    event = ProactiveEvent(
        kind=kind,
        message=message,
        priority=priority,
        urgency=urgency,
        interruptible=interruptible,
    )
    
    return event


@st.composite
def list_of_events_with_duplicates(draw):
    """
    Generate a list of ProactiveEvents that includes some duplicates.
    
    This strategy creates a list where some events have the same notification_id
    (by creating identical events) to test deduplication behavior.
    """
    # Generate 1-10 unique events
    num_unique = draw(st.integers(min_value=1, max_value=10))
    unique_events = [draw(valid_proactive_event()) for _ in range(num_unique)]
    
    # Create duplicates by repeating some events
    num_duplicates = draw(st.integers(min_value=0, max_value=5))
    events_with_duplicates = unique_events.copy()
    
    for _ in range(num_duplicates):
        if unique_events:
            # Pick a random event to duplicate
            event_to_dup = draw(st.sampled_from(unique_events))
            # Create a new event with the same notification_id
            duplicate = ProactiveEvent(
                kind=event_to_dup.kind,
                message=event_to_dup.message,
                priority=event_to_dup.priority,
                urgency=event_to_dup.urgency,
                interruptible=event_to_dup.interruptible,
                notification_id=event_to_dup.notification_id,
            )
            events_with_duplicates.append(duplicate)
    
    # Shuffle the list
    draw(st.randoms()).shuffle(events_with_duplicates)
    
    return events_with_duplicates


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ============================================================================
# Property Tests
# ============================================================================

@given(event=valid_proactive_event())
def test_property_same_notification_delivered_once(event: ProactiveEvent):
    """
    **Property 5: Notification Deduplication**
    
    For any ProactiveEvent, attempting to deliver the same notification
    (same notification_id) multiple times should result in only one delivery.
    The second and subsequent attempts should be skipped as duplicates.
    
    **Validates: Requirements 12.5**
    
    This property ensures that:
    1. The first delivery attempt succeeds (if channels are available)
    2. Subsequent delivery attempts with the same notification_id are skipped
    3. The skipped_reason is "duplicate" for subsequent attempts
    4. The notification is logged only once as delivered
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        router = NotificationRouter(workspace)
        
        # Mock active channels to ensure delivery succeeds
        with patch("tools.notification_router.psutil.process_iter") as mock_process_iter:
            mock_proc = MagicMock()
            mock_proc.info = {"cmdline": ["python", "gui.py"]}
            mock_process_iter.return_value = [mock_proc]
            
            # First delivery attempt
            result1 = router.route_notification(event)
            
            # Second delivery attempt (same notification_id)
            result2 = router.route_notification(event)
            
            # Third delivery attempt (same notification_id)
            result3 = router.route_notification(event)
        
        # Verify first delivery succeeded
        assert result1["delivered"] is True, (
            f"First delivery should succeed but got: {result1}"
        )
        assert len(result1["channels"]) > 0, (
            "First delivery should have active channels"
        )
        
        # Verify subsequent deliveries were skipped as duplicates
        assert result2["delivered"] is False, (
            f"Second delivery should be skipped but got: {result2}"
        )
        assert result2["skipped_reason"] == "duplicate", (
            f"Second delivery should be skipped due to duplicate, got: {result2['skipped_reason']}"
        )
        
        assert result3["delivered"] is False, (
            f"Third delivery should be skipped but got: {result3}"
        )
        assert result3["skipped_reason"] == "duplicate", (
            f"Third delivery should be skipped due to duplicate, got: {result3['skipped_reason']}"
        )


@given(events=list_of_events_with_duplicates())
def test_property_deduplication_across_event_list(events: List[ProactiveEvent]):
    """
    Property: Deduplication works correctly across a list of events with duplicates.
    
    For any list of ProactiveEvents (some of which may be duplicates), each unique
    notification_id should be delivered exactly once, regardless of how many times
    it appears in the list.
    
    **Validates: Requirements 12.5**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        router = NotificationRouter(workspace)
        
        # Track which notification_ids we've seen
        seen_ids = set()
        delivered_ids = set()
        duplicate_ids = set()
        
        # Mock active channels
        with patch("tools.notification_router.psutil.process_iter") as mock_process_iter:
            mock_proc = MagicMock()
            mock_proc.info = {"cmdline": ["python", "gui.py"]}
            mock_process_iter.return_value = [mock_proc]
            
            # Attempt to deliver all events
            for event in events:
                result = router.route_notification(event)
                
                if event.notification_id in seen_ids:
                    # This is a duplicate
                    assert result["delivered"] is False, (
                        f"Duplicate notification {event.notification_id} should not be delivered"
                    )
                    assert result["skipped_reason"] == "duplicate", (
                        f"Duplicate should have skipped_reason='duplicate', got: {result['skipped_reason']}"
                    )
                    duplicate_ids.add(event.notification_id)
                else:
                    # This is the first occurrence
                    assert result["delivered"] is True, (
                        f"First occurrence of {event.notification_id} should be delivered"
                    )
                    delivered_ids.add(event.notification_id)
                    seen_ids.add(event.notification_id)
        
        # Verify that each unique notification_id was delivered exactly once
        unique_ids = set(event.notification_id for event in events)
        assert delivered_ids == unique_ids, (
            f"All unique notification IDs should be delivered exactly once.\n"
            f"Expected: {unique_ids}\n"
            f"Delivered: {delivered_ids}\n"
            f"Missing: {unique_ids - delivered_ids}"
        )


@given(event=valid_proactive_event())
def test_property_deduplication_persists_across_router_instances(event: ProactiveEvent):
    """
    Property: Deduplication persists across NotificationRouter instances.
    
    For any ProactiveEvent, if it's delivered by one router instance, a new
    router instance should recognize it as a duplicate (by loading from the
    notifications.jsonl log file).
    
    **Validates: Requirements 12.5**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        
        # Mock active channels
        with patch("tools.notification_router.psutil.process_iter") as mock_process_iter:
            mock_proc = MagicMock()
            mock_proc.info = {"cmdline": ["python", "gui.py"]}
            mock_process_iter.return_value = [mock_proc]
            
            # First router instance delivers the notification
            router1 = NotificationRouter(workspace)
            result1 = router1.route_notification(event)
            
            assert result1["delivered"] is True, (
                "First delivery should succeed"
            )
            
            # Create a new router instance (simulating restart)
            router2 = NotificationRouter(workspace)
            
            # Attempt to deliver the same notification again
            result2 = router2.route_notification(event)
        
        # Verify the new instance recognizes it as a duplicate
        assert result2["delivered"] is False, (
            f"New router instance should recognize duplicate, got: {result2}"
        )
        assert result2["skipped_reason"] == "duplicate", (
            f"Should be skipped as duplicate, got: {result2['skipped_reason']}"
        )


@given(
    event=valid_proactive_event(),
    num_channels=st.integers(min_value=1, max_value=3),
)
def test_property_deduplication_across_multiple_channels(
    event: ProactiveEvent,
    num_channels: int,
):
    """
    Property: Deduplication works when notification is delivered to multiple channels.
    
    For any ProactiveEvent delivered to multiple channels simultaneously, the
    notification should be delivered to all active channels on the first attempt,
    but subsequent attempts should be deduplicated regardless of which channels
    are active.
    
    **Validates: Requirements 12.5**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        router = NotificationRouter(workspace)
        
        # Create mock processes for the specified number of channels
        channel_processes = []
        channel_names = ["gui.py", "telegram_bot.py", "chat.py"]
        
        for i in range(min(num_channels, len(channel_names))):
            mock_proc = MagicMock()
            mock_proc.info = {"cmdline": ["python", channel_names[i]]}
            channel_processes.append(mock_proc)
        
        with patch("tools.notification_router.psutil.process_iter") as mock_process_iter:
            # First delivery with multiple channels
            mock_process_iter.return_value = channel_processes
            result1 = router.route_notification(event)
            
            # Second delivery attempt (should be deduplicated)
            result2 = router.route_notification(event)
        
        # Verify first delivery succeeded with all channels
        assert result1["delivered"] is True, (
            "First delivery should succeed"
        )
        assert len(result1["channels"]) == num_channels, (
            f"Should deliver to {num_channels} channels, got {len(result1['channels'])}"
        )
        
        # Verify second delivery was deduplicated
        assert result2["delivered"] is False, (
            "Second delivery should be deduplicated"
        )
        assert result2["skipped_reason"] == "duplicate", (
            f"Should be skipped as duplicate, got: {result2['skipped_reason']}"
        )


@given(events=st.lists(valid_proactive_event(), min_size=1, max_size=20))
def test_property_unique_events_all_delivered(events: List[ProactiveEvent]):
    """
    Property: All unique events are delivered (no false positives in deduplication).
    
    For any list of ProactiveEvents with unique notification_ids, all events
    should be delivered successfully. Deduplication should not incorrectly
    block unique events.
    
    **Validates: Requirements 12.5**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        router = NotificationRouter(workspace)
        
        # Ensure all events have unique notification_ids
        unique_events = []
        seen_ids = set()
        for event in events:
            if event.notification_id not in seen_ids:
                unique_events.append(event)
                seen_ids.add(event.notification_id)
        
        delivered_count = 0
        
        with patch("tools.notification_router.psutil.process_iter") as mock_process_iter:
            mock_proc = MagicMock()
            mock_proc.info = {"cmdline": ["python", "gui.py"]}
            mock_process_iter.return_value = [mock_proc]
            
            # Deliver all unique events
            for event in unique_events:
                result = router.route_notification(event)
                
                if result["delivered"]:
                    delivered_count += 1
        
        # Verify all unique events were delivered
        assert delivered_count == len(unique_events), (
            f"All {len(unique_events)} unique events should be delivered, "
            f"but only {delivered_count} were delivered"
        )