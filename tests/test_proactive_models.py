"""
Unit tests for proactive data models.

Tests field types, constraints, serialization/deserialization, and validation
for all data model classes in the Proactive Intelligence System.
"""
import json
import time
from datetime import datetime

import pytest

from proactive_models import (
    AutoAction,
    BehavioralFingerprint,
    BehavioralModel,
    IntentModel,
    NotificationLog,
    ProactiveEvent,
)


class TestIntentModel:
    """Tests for IntentModel dataclass."""
    
    def test_intent_model_creation(self):
        """Test that IntentModel can be created with all required fields."""
        timestamp = datetime.now()
        model = IntentModel(
            timestamp=timestamp,
            active_projects=["project1", "project2"],
            open_loops=["task1", "task2"],
            today_deadlines=["deadline1"],
            focus_mode="deep_work",
            recommended_music="lofi",
            suggested_first_action="Continue writing spec"
        )
        
        assert model.timestamp == timestamp
        assert model.active_projects == ["project1", "project2"]
        assert model.open_loops == ["task1", "task2"]
        assert model.today_deadlines == ["deadline1"]
        assert model.focus_mode == "deep_work"
        assert model.recommended_music == "lofi"
        assert model.suggested_first_action == "Continue writing spec"
    
    def test_intent_model_focus_modes(self):
        """Test that IntentModel accepts all valid focus modes."""
        valid_modes = ["deep_work", "meeting", "coding", "idle"]
        
        for mode in valid_modes:
            model = IntentModel(
                timestamp=datetime.now(),
                active_projects=[],
                open_loops=[],
                today_deadlines=[],
                focus_mode=mode,
                recommended_music="none",
                suggested_first_action=""
            )
            assert model.focus_mode == mode
    
    def test_intent_model_music_recommendations(self):
        """Test that IntentModel accepts all valid music recommendations."""
        valid_music = ["lofi", "focus", "energetic", "none"]
        
        for music in valid_music:
            model = IntentModel(
                timestamp=datetime.now(),
                active_projects=[],
                open_loops=[],
                today_deadlines=[],
                focus_mode="idle",
                recommended_music=music,
                suggested_first_action=""
            )
            assert model.recommended_music == music


class TestBehavioralModel:
    """Tests for BehavioralModel dataclass."""
    
    def test_behavioral_model_creation(self):
        """Test that BehavioralModel can be created with all required fields."""
        generated_at = datetime.now()
        morning_routine = {
            "typical_start_time": "08:30",
            "first_actions": ["check email", "review tasks"]
        }
        
        model = BehavioralModel(
            generated_at=generated_at,
            morning_routine=morning_routine,
            peak_coding_hours=["10:00-12:00", "14:00-17:00"],
            typical_project_switch_time="90 minutes",
            never_works_on=["weekends after 6pm"],
            frequently_forgets=["commit messages"]
        )
        
        assert model.generated_at == generated_at
        assert model.morning_routine == morning_routine
        assert model.peak_coding_hours == ["10:00-12:00", "14:00-17:00"]
        assert model.typical_project_switch_time == "90 minutes"
        assert model.never_works_on == ["weekends after 6pm"]
        assert model.frequently_forgets == ["commit messages"]
    
    def test_behavioral_model_empty_lists(self):
        """Test that BehavioralModel handles empty lists correctly."""
        model = BehavioralModel(
            generated_at=datetime.now(),
            morning_routine={},
            peak_coding_hours=[],
            typical_project_switch_time="",
            never_works_on=[],
            frequently_forgets=[]
        )
        
        assert model.peak_coding_hours == []
        assert model.never_works_on == []
        assert model.frequently_forgets == []


class TestProactiveEvent:
    """Tests for ProactiveEvent dataclass."""
    
    def test_proactive_event_basic_creation(self):
        """Test that ProactiveEvent can be created with minimal fields."""
        event = ProactiveEvent(
            kind="system",
            message="Test message"
        )
        
        assert event.kind == "system"
        assert event.message == "Test message"
        assert event.data == {}
        assert isinstance(event.ts, float)
        assert event.priority == "medium"
        assert event.urgency == "next_idle"
        assert event.interruptible is True
        assert event.notification_id != ""
    
    def test_proactive_event_full_creation(self):
        """Test that ProactiveEvent can be created with all fields."""
        data = {"key": "value"}
        ts = time.time()
        
        event = ProactiveEvent(
            kind="morning_briefing",
            message="Good morning!",
            data=data,
            ts=ts,
            priority="high",
            urgency="immediate",
            interruptible=False,
            notification_id="custom_id"
        )
        
        assert event.kind == "morning_briefing"
        assert event.message == "Good morning!"
        assert event.data == data
        assert event.ts == ts
        assert event.priority == "high"
        assert event.urgency == "immediate"
        assert event.interruptible is False
        assert event.notification_id == "custom_id"
    
    def test_proactive_event_auto_generates_notification_id(self):
        """Test that ProactiveEvent auto-generates notification_id if not provided."""
        event1 = ProactiveEvent(kind="test", message="message1")
        event2 = ProactiveEvent(kind="test", message="message2")
        
        assert event1.notification_id != ""
        assert event2.notification_id != ""
        assert event1.notification_id != event2.notification_id
    
    def test_proactive_event_priority_levels(self):
        """Test that ProactiveEvent accepts all valid priority levels."""
        valid_priorities = ["low", "medium", "high", "critical"]
        
        for priority in valid_priorities:
            event = ProactiveEvent(
                kind="test",
                message="test",
                priority=priority
            )
            assert event.priority == priority
    
    def test_proactive_event_urgency_levels(self):
        """Test that ProactiveEvent accepts all valid urgency levels."""
        valid_urgencies = ["immediate", "next_idle", "next_session"]
        
        for urgency in valid_urgencies:
            event = ProactiveEvent(
                kind="test",
                message="test",
                urgency=urgency
            )
            assert event.urgency == urgency
    
    def test_proactive_event_notification_id_deterministic(self):
        """Test that notification_id is deterministic for same content."""
        ts = time.time()
        event1 = ProactiveEvent(kind="test", message="same", ts=ts)
        event2 = ProactiveEvent(kind="test", message="same", ts=ts)
        
        assert event1.notification_id == event2.notification_id


class TestBehavioralFingerprint:
    """Tests for BehavioralFingerprint dataclass."""
    
    def test_behavioral_fingerprint_creation(self):
        """Test that BehavioralFingerprint can be created with all required fields."""
        timestamp = datetime.now()
        
        fingerprint = BehavioralFingerprint(
            timestamp=timestamp,
            interaction_type="code",
            duration_sec=120,
            tools_used=["write_file", "execute_shell"],
            context="working on proactive spec"
        )
        
        assert fingerprint.timestamp == timestamp
        assert fingerprint.interaction_type == "code"
        assert fingerprint.duration_sec == 120
        assert fingerprint.tools_used == ["write_file", "execute_shell"]
        assert fingerprint.context == "working on proactive spec"
    
    def test_behavioral_fingerprint_interaction_types(self):
        """Test that BehavioralFingerprint accepts all valid interaction types."""
        valid_types = ["code", "write", "search", "system"]
        
        for interaction_type in valid_types:
            fingerprint = BehavioralFingerprint(
                timestamp=datetime.now(),
                interaction_type=interaction_type,
                duration_sec=60,
                tools_used=[],
                context=""
            )
            assert fingerprint.interaction_type == interaction_type
    
    def test_behavioral_fingerprint_empty_tools(self):
        """Test that BehavioralFingerprint handles empty tools list."""
        fingerprint = BehavioralFingerprint(
            timestamp=datetime.now(),
            interaction_type="system",
            duration_sec=30,
            tools_used=[],
            context="idle check"
        )
        
        assert fingerprint.tools_used == []


class TestAutoAction:
    """Tests for AutoAction dataclass."""
    
    def test_auto_action_class_a(self):
        """Test that AutoAction can be created for Class A actions."""
        def dummy_fn():
            return "executed"
        
        action = AutoAction(
            action_class="A",
            action_type="memory_consolidate",
            description="Consolidate memory entries",
            execute_fn=dummy_fn,
            approval_required=False,
            notification_required=False
        )
        
        assert action.action_class == "A"
        assert action.action_type == "memory_consolidate"
        assert action.description == "Consolidate memory entries"
        assert action.execute_fn() == "executed"
        assert action.approval_required is False
        assert action.notification_required is False
    
    def test_auto_action_class_b(self):
        """Test that AutoAction can be created for Class B actions."""
        def dummy_fn():
            return "executed"
        
        action = AutoAction(
            action_class="B",
            action_type="disk_cleanup",
            description="Clean up disk space",
            execute_fn=dummy_fn,
            approval_required=False,
            notification_required=True
        )
        
        assert action.action_class == "B"
        assert action.notification_required is True
        assert action.approval_required is False
    
    def test_auto_action_class_c(self):
        """Test that AutoAction can be created for Class C actions."""
        def dummy_fn():
            return "executed"
        
        action = AutoAction(
            action_class="C",
            action_type="folder_organization",
            description="Organize folders",
            execute_fn=dummy_fn,
            approval_required=True,
            notification_required=True
        )
        
        assert action.action_class == "C"
        assert action.approval_required is True
        assert action.notification_required is True
    
    def test_auto_action_execute_fn_callable(self):
        """Test that AutoAction execute_fn is callable."""
        executed = False
        
        def test_fn():
            nonlocal executed
            executed = True
            return "done"
        
        action = AutoAction(
            action_class="A",
            action_type="test",
            description="Test action",
            execute_fn=test_fn,
            approval_required=False,
            notification_required=False
        )
        
        result = action.execute_fn()
        assert executed is True
        assert result == "done"


class TestNotificationLog:
    """Tests for NotificationLog dataclass."""
    
    def test_notification_log_successful_delivery(self):
        """Test that NotificationLog can record successful delivery."""
        timestamp = datetime.now()
        
        log = NotificationLog(
            id="notif_123",
            timestamp=timestamp,
            kind="morning_briefing",
            priority="high",
            channels=["gui", "telegram"],
            delivered=True,
            error=None
        )
        
        assert log.id == "notif_123"
        assert log.timestamp == timestamp
        assert log.kind == "morning_briefing"
        assert log.priority == "high"
        assert log.channels == ["gui", "telegram"]
        assert log.delivered is True
        assert log.error is None
    
    def test_notification_log_failed_delivery(self):
        """Test that NotificationLog can record failed delivery."""
        log = NotificationLog(
            id="notif_456",
            timestamp=datetime.now(),
            kind="system",
            priority="medium",
            channels=["telegram"],
            delivered=False,
            error="Connection timeout"
        )
        
        assert log.delivered is False
        assert log.error == "Connection timeout"
    
    def test_notification_log_multiple_channels(self):
        """Test that NotificationLog handles multiple channels."""
        log = NotificationLog(
            id="notif_789",
            timestamp=datetime.now(),
            kind="dream_epiphany",
            priority="medium",
            channels=["gui", "telegram", "cli"],
            delivered=True
        )
        
        assert len(log.channels) == 3
        assert "gui" in log.channels
        assert "telegram" in log.channels
        assert "cli" in log.channels


class TestDataModelSerialization:
    """Tests for serialization/deserialization of data models."""
    
    def test_proactive_event_dict_conversion(self):
        """Test that ProactiveEvent can be converted to/from dict."""
        event = ProactiveEvent(
            kind="test",
            message="test message",
            data={"key": "value"},
            priority="high",
            urgency="immediate"
        )
        
        # Convert to dict (using dataclasses.asdict would work)
        event_dict = {
            "kind": event.kind,
            "message": event.message,
            "data": event.data,
            "ts": event.ts,
            "priority": event.priority,
            "urgency": event.urgency,
            "interruptible": event.interruptible,
            "notification_id": event.notification_id
        }
        
        # Verify dict structure
        assert event_dict["kind"] == "test"
        assert event_dict["message"] == "test message"
        assert event_dict["data"] == {"key": "value"}
        assert event_dict["priority"] == "high"
    
    def test_intent_model_json_serialization(self):
        """Test that IntentModel fields can be JSON serialized."""
        model = IntentModel(
            timestamp=datetime.now(),
            active_projects=["project1"],
            open_loops=["task1"],
            today_deadlines=["deadline1"],
            focus_mode="coding",
            recommended_music="focus",
            suggested_first_action="Continue coding"
        )
        
        # Create JSON-serializable dict
        model_dict = {
            "timestamp": model.timestamp.isoformat(),
            "active_projects": model.active_projects,
            "open_loops": model.open_loops,
            "today_deadlines": model.today_deadlines,
            "focus_mode": model.focus_mode,
            "recommended_music": model.recommended_music,
            "suggested_first_action": model.suggested_first_action
        }
        
        # Should be JSON serializable
        json_str = json.dumps(model_dict)
        assert json_str is not None
        
        # Should be deserializable
        loaded = json.loads(json_str)
        assert loaded["focus_mode"] == "coding"
        assert loaded["active_projects"] == ["project1"]
    
    def test_behavioral_model_json_serialization(self):
        """Test that BehavioralModel fields can be JSON serialized."""
        model = BehavioralModel(
            generated_at=datetime.now(),
            morning_routine={"typical_start_time": "08:30"},
            peak_coding_hours=["10:00-12:00"],
            typical_project_switch_time="90 minutes",
            never_works_on=["weekends"],
            frequently_forgets=["commits"]
        )
        
        # Create JSON-serializable dict
        model_dict = {
            "generated_at": model.generated_at.isoformat(),
            "morning_routine": model.morning_routine,
            "peak_coding_hours": model.peak_coding_hours,
            "typical_project_switch_time": model.typical_project_switch_time,
            "never_works_on": model.never_works_on,
            "frequently_forgets": model.frequently_forgets
        }
        
        # Should be JSON serializable
        json_str = json.dumps(model_dict)
        assert json_str is not None
        
        # Should be deserializable
        loaded = json.loads(json_str)
        assert loaded["typical_project_switch_time"] == "90 minutes"
        assert loaded["peak_coding_hours"] == ["10:00-12:00"]
    
    def test_behavioral_fingerprint_json_serialization(self):
        """Test that BehavioralFingerprint fields can be JSON serialized."""
        fingerprint = BehavioralFingerprint(
            timestamp=datetime.now(),
            interaction_type="code",
            duration_sec=120,
            tools_used=["write_file"],
            context="working on spec"
        )
        
        # Create JSON-serializable dict
        fingerprint_dict = {
            "timestamp": fingerprint.timestamp.isoformat(),
            "interaction_type": fingerprint.interaction_type,
            "duration_sec": fingerprint.duration_sec,
            "tools_used": fingerprint.tools_used,
            "context": fingerprint.context
        }
        
        # Should be JSON serializable
        json_str = json.dumps(fingerprint_dict)
        assert json_str is not None
        
        # Should be deserializable
        loaded = json.loads(json_str)
        assert loaded["interaction_type"] == "code"
        assert loaded["duration_sec"] == 120
    
    def test_notification_log_json_serialization(self):
        """Test that NotificationLog fields can be JSON serialized."""
        log = NotificationLog(
            id="notif_123",
            timestamp=datetime.now(),
            kind="system",
            priority="high",
            channels=["gui", "telegram"],
            delivered=True,
            error=None
        )
        
        # Create JSON-serializable dict
        log_dict = {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "kind": log.kind,
            "priority": log.priority,
            "channels": log.channels,
            "delivered": log.delivered,
            "error": log.error
        }
        
        # Should be JSON serializable
        json_str = json.dumps(log_dict)
        assert json_str is not None
        
        # Should be deserializable
        loaded = json.loads(json_str)
        assert loaded["id"] == "notif_123"
        assert loaded["delivered"] is True


class TestDataModelConstraints:
    """Tests for data model field constraints and edge cases."""
    
    def test_intent_model_with_empty_strings(self):
        """Test that IntentModel handles empty strings correctly."""
        model = IntentModel(
            timestamp=datetime.now(),
            active_projects=[],
            open_loops=[],
            today_deadlines=[],
            focus_mode="",
            recommended_music="",
            suggested_first_action=""
        )
        
        assert model.focus_mode == ""
        assert model.recommended_music == ""
        assert model.suggested_first_action == ""
    
    def test_proactive_event_with_empty_data(self):
        """Test that ProactiveEvent handles empty data dict correctly."""
        event = ProactiveEvent(kind="test", message="test")
        
        assert event.data == {}
        assert isinstance(event.data, dict)
    
    def test_proactive_event_with_nested_data(self):
        """Test that ProactiveEvent handles nested data structures."""
        nested_data = {
            "level1": {
                "level2": ["item1", "item2"],
                "count": 42
            }
        }
        
        event = ProactiveEvent(
            kind="test",
            message="test",
            data=nested_data
        )
        
        assert event.data["level1"]["level2"] == ["item1", "item2"]
        assert event.data["level1"]["count"] == 42
    
    def test_behavioral_fingerprint_with_zero_duration(self):
        """Test that BehavioralFingerprint handles zero duration."""
        fingerprint = BehavioralFingerprint(
            timestamp=datetime.now(),
            interaction_type="system",
            duration_sec=0,
            tools_used=[],
            context="instant check"
        )
        
        assert fingerprint.duration_sec == 0
    
    def test_behavioral_fingerprint_with_long_duration(self):
        """Test that BehavioralFingerprint handles long durations."""
        fingerprint = BehavioralFingerprint(
            timestamp=datetime.now(),
            interaction_type="code",
            duration_sec=7200,  # 2 hours
            tools_used=["write_file", "execute_shell"],
            context="long coding session"
        )
        
        assert fingerprint.duration_sec == 7200
    
    def test_notification_log_with_empty_channels(self):
        """Test that NotificationLog handles empty channels list."""
        log = NotificationLog(
            id="notif_empty",
            timestamp=datetime.now(),
            kind="system",
            priority="low",
            channels=[],
            delivered=False,
            error="No channels available"
        )
        
        assert log.channels == []
        assert log.delivered is False
    
    def test_behavioral_model_with_complex_morning_routine(self):
        """Test that BehavioralModel handles complex morning routine data."""
        complex_routine = {
            "typical_start_time": "08:30",
            "first_actions": ["check email", "review tasks", "coffee"],
            "duration_minutes": 45,
            "tools_used": ["email_client", "task_manager"],
            "nested": {
                "preferences": ["quiet", "focused"]
            }
        }
        
        model = BehavioralModel(
            generated_at=datetime.now(),
            morning_routine=complex_routine,
            peak_coding_hours=["10:00-12:00"],
            typical_project_switch_time="90 minutes",
            never_works_on=["weekends"],
            frequently_forgets=["commits"]
        )
        
        assert model.morning_routine["duration_minutes"] == 45
        assert model.morning_routine["nested"]["preferences"] == ["quiet", "focused"]
    
    def test_proactive_event_notification_id_uniqueness(self):
        """Test that different events generate different notification IDs."""
        events = [
            ProactiveEvent(kind=f"test_{i}", message=f"message_{i}")
            for i in range(10)
        ]
        
        notification_ids = [e.notification_id for e in events]
        
        # All IDs should be unique
        assert len(notification_ids) == len(set(notification_ids))
    
    def test_auto_action_with_lambda_function(self):
        """Test that AutoAction works with lambda functions."""
        action = AutoAction(
            action_class="A",
            action_type="test",
            description="Test with lambda",
            execute_fn=lambda: "lambda result",
            approval_required=False,
            notification_required=False
        )
        
        assert action.execute_fn() == "lambda result"
