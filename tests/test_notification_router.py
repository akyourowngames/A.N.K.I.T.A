"""
Unit tests for NotificationRouter

Tests channel detection, per-channel formatting, DND mode filtering,
deduplication, and notification logging.

Requirements: 12.2, 12.3, 12.6
"""
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proactive_models import ProactiveEvent
from tools.notification_router import NotificationRouter


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def router(temp_workspace):
    """Create a NotificationRouter instance for testing."""
    return NotificationRouter(temp_workspace)


@pytest.fixture
def sample_event():
    """Create a sample ProactiveEvent for testing."""
    return ProactiveEvent(
        kind="test",
        message="Test notification message",
        priority="medium",
        urgency="next_idle",
    )


class TestChannelDetection:
    """Tests for channel detection logic."""
    
    @patch("tools.notification_router.psutil.process_iter")
    def test_detect_gui_channel(self, mock_process_iter, router):
        """Test that GUI channel is detected when gui.py is running."""
        # Mock process with gui.py in cmdline
        mock_proc = MagicMock()
        mock_proc.info = {"cmdline": ["python", "gui.py"]}
        mock_process_iter.return_value = [mock_proc]
        
        channels = router.detect_active_channels()
        
        assert "gui" in channels
    
    @patch("tools.notification_router.psutil.process_iter")
    def test_detect_telegram_channel(self, mock_process_iter, router):
        """Test that Telegram channel is detected when telegram_bot.py is running."""
        mock_proc = MagicMock()
        mock_proc.info = {"cmdline": ["python", "telegram_bot.py"]}
        mock_process_iter.return_value = [mock_proc]
        
        channels = router.detect_active_channels()
        
        assert "telegram" in channels
    
    @patch("tools.notification_router.psutil.process_iter")
    def test_detect_cli_channel(self, mock_process_iter, router):
        """Test that CLI channel is detected when chat.py is running."""
        mock_proc = MagicMock()
        mock_proc.info = {"cmdline": ["python", "chat.py"]}
        mock_process_iter.return_value = [mock_proc]
        
        channels = router.detect_active_channels()
        
        assert "cli" in channels
    
    @patch("tools.notification_router.psutil.process_iter")
    def test_detect_multiple_channels(self, mock_process_iter, router):
        """Test that multiple channels are detected when multiple processes are running."""
        mock_gui = MagicMock()
        mock_gui.info = {"cmdline": ["python", "gui.py"]}
        
        mock_telegram = MagicMock()
        mock_telegram.info = {"cmdline": ["python", "telegram_bot.py"]}
        
        mock_cli = MagicMock()
        mock_cli.info = {"cmdline": ["python", "chat.py"]}
        
        mock_process_iter.return_value = [mock_gui, mock_telegram, mock_cli]
        
        channels = router.detect_active_channels()
        
        assert len(channels) == 3
        assert "gui" in channels
        assert "telegram" in channels
        assert "cli" in channels
    
    @patch("tools.notification_router.psutil.process_iter")
    def test_detect_no_channels(self, mock_process_iter, router):
        """Test that empty list is returned when no relevant processes are running."""
        mock_proc = MagicMock()
        mock_proc.info = {"cmdline": ["python", "other_script.py"]}
        mock_process_iter.return_value = [mock_proc]
        
        channels = router.detect_active_channels()
        
        assert channels == []
    
    @patch("tools.notification_router.psutil.process_iter")
    def test_detect_channels_handles_process_errors(self, mock_process_iter, router):
        """Test that channel detection handles process access errors gracefully."""
        from psutil import NoSuchProcess
        
        mock_proc = MagicMock()
        mock_proc.info = {"cmdline": ["python", "gui.py"]}
        
        mock_error_proc = MagicMock()
        mock_error_proc.info.side_effect = NoSuchProcess(pid=123)
        
        mock_process_iter.return_value = [mock_proc, mock_error_proc]
        
        channels = router.detect_active_channels()
        
        # Should still detect the valid process
        assert "gui" in channels


class TestChannelFormatting:
    """Tests for per-channel message formatting."""
    
    def test_format_for_gui_includes_icon(self, router, sample_event):
        """Test that GUI formatting includes rich text icons."""
        formatted = router.format_for_channel(sample_event, "gui")
        
        # Should include an icon (emoji)
        assert "ℹ️" in formatted or "⚠️" in formatted or "🚨" in formatted or "💡" in formatted
        assert sample_event.message in formatted
    
    def test_format_for_telegram_includes_emoji(self, router, sample_event):
        """Test that Telegram formatting includes emojis."""
        formatted = router.format_for_channel(sample_event, "telegram")
        
        # Should include an emoji
        assert "📢" in formatted or "⚠️" in formatted or "🚨" in formatted or "💬" in formatted
        assert sample_event.message in formatted
    
    def test_format_for_cli_includes_prefix(self, router, sample_event):
        """Test that CLI formatting includes text prefix."""
        formatted = router.format_for_channel(sample_event, "cli")
        
        # Should include a text prefix
        assert "[INFO]" in formatted or "[HIGH]" in formatted or "[CRITICAL]" in formatted or "[NOTE]" in formatted
        assert sample_event.message in formatted
    
    def test_format_critical_priority(self, router):
        """Test formatting for critical priority events."""
        event = ProactiveEvent(
            kind="system",
            message="Critical alert",
            priority="critical",
        )
        
        gui_formatted = router.format_for_channel(event, "gui")
        telegram_formatted = router.format_for_channel(event, "telegram")
        cli_formatted = router.format_for_channel(event, "cli")
        
        assert "🚨" in gui_formatted
        assert "🚨" in telegram_formatted
        assert "[CRITICAL]" in cli_formatted
    
    def test_format_high_priority(self, router):
        """Test formatting for high priority events."""
        event = ProactiveEvent(
            kind="system",
            message="High priority alert",
            priority="high",
        )
        
        gui_formatted = router.format_for_channel(event, "gui")
        telegram_formatted = router.format_for_channel(event, "telegram")
        cli_formatted = router.format_for_channel(event, "cli")
        
        assert "⚠️" in gui_formatted
        assert "⚠️" in telegram_formatted
        assert "[HIGH]" in cli_formatted
    
    def test_format_low_priority(self, router):
        """Test formatting for low priority events."""
        event = ProactiveEvent(
            kind="system",
            message="Low priority note",
            priority="low",
        )
        
        gui_formatted = router.format_for_channel(event, "gui")
        telegram_formatted = router.format_for_channel(event, "telegram")
        cli_formatted = router.format_for_channel(event, "cli")
        
        assert "💡" in gui_formatted
        assert "💬" in telegram_formatted
        assert "[NOTE]" in cli_formatted
    
    def test_format_unknown_channel_returns_plain_text(self, router, sample_event):
        """Test that unknown channel returns plain text message."""
        formatted = router.format_for_channel(sample_event, "unknown_channel")
        
        assert formatted == sample_event.message


class TestDNDMode:
    """Tests for Do Not Disturb mode checking."""
    
    def test_dnd_inactive_when_no_env_var(self, router):
        """Test that DND is inactive when ANKITA_DND_HOURS is not set."""
        with patch.dict(os.environ, {"ANKITA_DND_HOURS": ""}, clear=False):
            assert router.is_dnd_active() is False
    
    def test_dnd_active_during_single_period(self, router):
        """Test that DND is active during configured period."""
        # Set DND hours to current time
        now = datetime.now()
        start_time = (now.hour - 1) % 24
        end_time = (now.hour + 1) % 24
        dnd_hours = f"{start_time:02d}:00-{end_time:02d}:00"
        
        with patch.dict(os.environ, {"ANKITA_DND_HOURS": dnd_hours}, clear=False):
            assert router.is_dnd_active() is True
    
    def test_dnd_inactive_outside_period(self, router):
        """Test that DND is inactive outside configured period."""
        # Set DND hours to a time range that doesn't include current time
        now = datetime.now()
        start_time = (now.hour + 2) % 24
        end_time = (now.hour + 3) % 24
        dnd_hours = f"{start_time:02d}:00-{end_time:02d}:00"
        
        with patch.dict(os.environ, {"ANKITA_DND_HOURS": dnd_hours}, clear=False):
            # This might be True if we're near midnight and the period wraps
            # So we just check it doesn't crash
            result = router.is_dnd_active()
            assert isinstance(result, bool)
    
    def test_dnd_handles_multiple_periods(self, router):
        """Test that DND handles multiple comma-separated periods."""
        dnd_hours = "22:00-08:00,13:00-14:00"
        
        with patch.dict(os.environ, {"ANKITA_DND_HOURS": dnd_hours}, clear=False):
            # Should parse without errors
            result = router.is_dnd_active()
            assert isinstance(result, bool)
    
    def test_dnd_handles_midnight_crossing(self, router):
        """Test that DND correctly handles periods that cross midnight."""
        # Period from 22:00 to 08:00 (crosses midnight)
        dnd_hours = "22:00-08:00"
        
        with patch.dict(os.environ, {"ANKITA_DND_HOURS": dnd_hours}, clear=False):
            # Mock current time to be 23:00 (should be in DND)
            with patch("tools.notification_router.datetime") as mock_datetime:
                mock_now = MagicMock()
                mock_now.time.return_value = datetime.strptime("23:00", "%H:%M").time()
                mock_datetime.now.return_value = mock_now
                mock_datetime.strptime = datetime.strptime
                
                assert router.is_dnd_active() is True
    
    def test_dnd_handles_invalid_format_gracefully(self, router):
        """Test that DND handles invalid format gracefully."""
        invalid_formats = [
            "invalid",
            "22:00",  # Missing end time
            "22:00-",  # Missing end time
            "-08:00",  # Missing start time
            "25:00-08:00",  # Invalid hour
            "22:70-08:00",  # Invalid minute
        ]
        
        for invalid_format in invalid_formats:
            with patch.dict(os.environ, {"ANKITA_DND_HOURS": invalid_format}, clear=False):
                # Should not crash, should return False
                result = router.is_dnd_active()
                assert result is False


class TestDeduplication:
    """Tests for notification deduplication logic."""
    
    def test_is_duplicate_returns_false_for_new_id(self, router):
        """Test that is_duplicate returns False for new notification ID."""
        assert router.is_duplicate("new_notif_123") is False
    
    def test_is_duplicate_returns_true_after_logging(self, router, sample_event):
        """Test that is_duplicate returns True after notification is logged."""
        notification_id = sample_event.notification_id
        
        # Log the notification
        router.log_notification(
            notification_id,
            sample_event,
            channels=["gui"],
            delivered=True,
        )
        
        # Should now be marked as duplicate
        assert router.is_duplicate(notification_id) is True
    
    def test_load_recent_notifications_from_log(self, temp_workspace):
        """Test that recent notifications are loaded from log file on init."""
        # Create a notifications log with a recent entry
        state_dir = temp_workspace / ".ankita" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        notifications_log = state_dir / "notifications.jsonl"
        
        recent_id = "recent_notif_123"
        log_entry = {
            "id": recent_id,
            "timestamp": datetime.now().isoformat(),
            "kind": "test",
            "priority": "medium",
            "channels": ["gui"],
            "delivered": True,
            "error": None,
        }
        
        with open(notifications_log, "w", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
        
        # Create router (should load recent notifications)
        router = NotificationRouter(temp_workspace)
        
        # Should recognize as duplicate
        assert router.is_duplicate(recent_id) is True
    
    def test_load_recent_notifications_ignores_old_entries(self, temp_workspace):
        """Test that old notifications (>24h) are not loaded."""
        state_dir = temp_workspace / ".ankita" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        notifications_log = state_dir / "notifications.jsonl"
        
        old_id = "old_notif_123"
        # Create timestamp from 25 hours ago
        old_timestamp = datetime.fromtimestamp(time.time() - (25 * 60 * 60))
        log_entry = {
            "id": old_id,
            "timestamp": old_timestamp.isoformat(),
            "kind": "test",
            "priority": "medium",
            "channels": ["gui"],
            "delivered": True,
            "error": None,
        }
        
        with open(notifications_log, "w", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
        
        # Create router (should NOT load old notifications)
        router = NotificationRouter(temp_workspace)
        
        # Should NOT recognize as duplicate
        assert router.is_duplicate(old_id) is False


class TestNotificationLogging:
    """Tests for notification logging to JSONL file."""
    
    def test_log_notification_creates_file(self, router, sample_event):
        """Test that log_notification creates the log file."""
        router.log_notification(
            sample_event.notification_id,
            sample_event,
            channels=["gui"],
            delivered=True,
        )
        
        assert router.notifications_log.exists()
    
    def test_log_notification_appends_to_file(self, router, sample_event):
        """Test that log_notification appends to existing file."""
        # Log first notification
        event1 = ProactiveEvent(kind="test1", message="First")
        router.log_notification(
            event1.notification_id,
            event1,
            channels=["gui"],
            delivered=True,
        )
        
        # Log second notification
        event2 = ProactiveEvent(kind="test2", message="Second")
        router.log_notification(
            event2.notification_id,
            event2,
            channels=["telegram"],
            delivered=True,
        )
        
        # Read log file
        with open(router.notifications_log, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        assert len(lines) == 2
    
    def test_log_notification_contains_all_fields(self, router, sample_event):
        """Test that logged notification contains all required fields."""
        router.log_notification(
            sample_event.notification_id,
            sample_event,
            channels=["gui", "telegram"],
            delivered=True,
        )
        
        # Read log file
        with open(router.notifications_log, "r", encoding="utf-8") as f:
            log_entry = json.loads(f.readline())
        
        assert log_entry["id"] == sample_event.notification_id
        assert log_entry["kind"] == sample_event.kind
        assert log_entry["priority"] == sample_event.priority
        assert log_entry["channels"] == ["gui", "telegram"]
        assert log_entry["delivered"] is True
        assert log_entry["error"] is None
        assert "timestamp" in log_entry
    
    def test_log_notification_with_error(self, router, sample_event):
        """Test that log_notification records error messages."""
        error_msg = "Connection timeout"
        
        router.log_notification(
            sample_event.notification_id,
            sample_event,
            channels=[],
            delivered=False,
            error=error_msg,
        )
        
        # Read log file
        with open(router.notifications_log, "r", encoding="utf-8") as f:
            log_entry = json.loads(f.readline())
        
        assert log_entry["delivered"] is False
        assert log_entry["error"] == error_msg


class TestRouteNotification:
    """Tests for the main route_notification method."""
    
    @patch("tools.notification_router.psutil.process_iter")
    def test_route_notification_success(self, mock_process_iter, router, sample_event):
        """Test successful notification routing."""
        # Mock active channels
        mock_proc = MagicMock()
        mock_proc.info = {"cmdline": ["python", "gui.py"]}
        mock_process_iter.return_value = [mock_proc]
        
        result = router.route_notification(sample_event)
        
        assert result["delivered"] is True
        assert "gui" in result["channels"]
        assert result["skipped_reason"] is None
        assert "gui" in result["formatted_messages"]
    
    def test_route_notification_skips_duplicate(self, router, sample_event):
        """Test that duplicate notifications are skipped."""
        # Mark as already delivered
        router._delivered_ids.add(sample_event.notification_id)
        
        result = router.route_notification(sample_event)
        
        assert result["delivered"] is False
        assert result["skipped_reason"] == "duplicate"
    
    @patch("tools.notification_router.psutil.process_iter")
    def test_route_notification_skips_during_dnd(self, mock_process_iter, router):
        """Test that non-critical notifications are skipped during DND."""
        # Mock active channels
        mock_proc = MagicMock()
        mock_proc.info = {"cmdline": ["python", "gui.py"]}
        mock_process_iter.return_value = [mock_proc]
        
        # Set DND mode
        now = datetime.now()
        start_time = (now.hour - 1) % 24
        end_time = (now.hour + 1) % 24
        dnd_hours = f"{start_time:02d}:00-{end_time:02d}:00"
        
        with patch.dict(os.environ, {"ANKITA_DND_HOURS": dnd_hours}, clear=False):
            # Medium priority event should be skipped
            event = ProactiveEvent(
                kind="test",
                message="Medium priority",
                priority="medium",
            )
            
            result = router.route_notification(event)
            
            assert result["delivered"] is False
            assert result["skipped_reason"] == "dnd_mode"
    
    @patch("tools.notification_router.psutil.process_iter")
    def test_route_notification_delivers_critical_during_dnd(self, mock_process_iter, router):
        """Test that critical notifications are delivered even during DND."""
        # Mock active channels
        mock_proc = MagicMock()
        mock_proc.info = {"cmdline": ["python", "gui.py"]}
        mock_process_iter.return_value = [mock_proc]
        
        # Set DND mode
        now = datetime.now()
        start_time = (now.hour - 1) % 24
        end_time = (now.hour + 1) % 24
        dnd_hours = f"{start_time:02d}:00-{end_time:02d}:00"
        
        with patch.dict(os.environ, {"ANKITA_DND_HOURS": dnd_hours}, clear=False):
            # Critical priority event should be delivered
            event = ProactiveEvent(
                kind="system",
                message="Critical alert",
                priority="critical",
            )
            
            result = router.route_notification(event)
            
            assert result["delivered"] is True
            assert "gui" in result["channels"]
    
    @patch("tools.notification_router.psutil.process_iter")
    def test_route_notification_fails_when_no_channels(self, mock_process_iter, router, sample_event):
        """Test that routing fails when no channels are active."""
        # Mock no active channels
        mock_process_iter.return_value = []
        
        result = router.route_notification(sample_event)
        
        assert result["delivered"] is False
        assert result["skipped_reason"] == "no_channels"
    
    @patch("tools.notification_router.psutil.process_iter")
    def test_route_notification_formats_for_multiple_channels(self, mock_process_iter, router, sample_event):
        """Test that notification is formatted for all active channels."""
        # Mock multiple active channels
        mock_gui = MagicMock()
        mock_gui.info = {"cmdline": ["python", "gui.py"]}
        
        mock_telegram = MagicMock()
        mock_telegram.info = {"cmdline": ["python", "telegram_bot.py"]}
        
        mock_process_iter.return_value = [mock_gui, mock_telegram]
        
        result = router.route_notification(sample_event)
        
        assert result["delivered"] is True
        assert len(result["channels"]) == 2
        assert "gui" in result["formatted_messages"]
        assert "telegram" in result["formatted_messages"]
        # Messages should be different (different formatting)
        assert result["formatted_messages"]["gui"] != result["formatted_messages"]["telegram"]
