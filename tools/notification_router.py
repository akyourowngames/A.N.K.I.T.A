"""
NotificationRouter - Central routing system for proactive notifications

Handles priority-based routing, deduplication, per-channel formatting,
and delivery to all active channels (GUI, Telegram, CLI).

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""
from __future__ import annotations

import json
import os
import psutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from proactive_models import NotificationLog, ProactiveEvent


class NotificationRouter:
    """
    Central routing logic for all proactive notifications.
    
    Routes ProactiveEvents from the ProactiveEngine queue to all active
    channels (GUI, Telegram, CLI) with appropriate formatting, deduplication,
    and DND mode filtering.
    
    Attributes:
        workspace_root: Root directory of the workspace (contains .ankita/)
        notifications_log: Path to notifications.jsonl log file
        _delivered_ids: Set of recently delivered notification IDs (in-memory cache)
    """
    
    def __init__(self, workspace_root: Path) -> None:
        """
        Initialize the NotificationRouter.
        
        Args:
            workspace_root: Root directory of the workspace (contains .ankita/)
        """
        self.workspace_root = workspace_root
        self.state_dir = workspace_root / ".ankita" / "state"
        self.notifications_log = self.state_dir / "notifications.jsonl"
        
        # Ensure state directory exists
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache of delivered notification IDs (last 24 hours)
        self._delivered_ids: Set[str] = set()
        self._load_recent_notifications()
    
    def _load_recent_notifications(self) -> None:
        """
        Load recently delivered notification IDs from log file.
        
        Loads notifications from the last 24 hours to prevent duplicates.
        """
        if not self.notifications_log.exists():
            return
        
        try:
            cutoff_time = time.time() - (24 * 60 * 60)  # 24 hours ago
            
            with open(self.notifications_log, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        log_entry = json.loads(line)
                        # Parse timestamp
                        timestamp_str = log_entry.get("timestamp", "")
                        try:
                            timestamp = datetime.fromisoformat(timestamp_str).timestamp()
                        except (ValueError, AttributeError):
                            continue
                        
                        # Only load recent notifications
                        if timestamp >= cutoff_time:
                            self._delivered_ids.add(log_entry.get("id", ""))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(
                f"[NotificationRouter] ⚠️  Failed to load recent notifications: {e}",
                flush=True,
            )
    
    def is_dnd_active(self) -> bool:
        """
        Check if Do Not Disturb mode is currently active.
        
        Reads ANKITA_DND_HOURS environment variable (format: "22:00-08:00,13:00-14:00")
        and checks if current time falls within any DND period.
        
        Returns:
            True if DND mode is active, False otherwise
        """
        dnd_hours = os.getenv("ANKITA_DND_HOURS", "").strip()
        if not dnd_hours:
            return False
        
        try:
            now = datetime.now()
            current_time = now.time()
            
            # Parse DND periods (comma-separated)
            for period in dnd_hours.split(","):
                period = period.strip()
                if not period or "-" not in period:
                    continue
                
                start_str, end_str = period.split("-", 1)
                start_str = start_str.strip()
                end_str = end_str.strip()
                
                # Parse time strings (HH:MM format)
                try:
                    start_hour, start_min = map(int, start_str.split(":"))
                    end_hour, end_min = map(int, end_str.split(":"))
                except (ValueError, AttributeError):
                    continue
                
                start_time = datetime.strptime(f"{start_hour:02d}:{start_min:02d}", "%H:%M").time()
                end_time = datetime.strptime(f"{end_hour:02d}:{end_min:02d}", "%H:%M").time()
                
                # Handle periods that cross midnight
                if start_time <= end_time:
                    # Normal period (e.g., 13:00-14:00)
                    if start_time <= current_time <= end_time:
                        return True
                else:
                    # Period crosses midnight (e.g., 22:00-08:00)
                    if current_time >= start_time or current_time <= end_time:
                        return True
        
        except Exception as e:
            print(
                f"[NotificationRouter] ⚠️  Failed to parse DND_HOURS: {e}",
                flush=True,
            )
        
        return False
    
    def detect_active_channels(self) -> List[str]:
        """
        Detect which notification channels are currently active.
        
        Checks if GUI (gui.py), Telegram (telegram_bot.py), and CLI (chat.py)
        processes are running.
        
        Returns:
            List of active channel names (e.g., ["gui", "telegram"])
        """
        active_channels: List[str] = []
        
        try:
            # Check all running processes
            for proc in psutil.process_iter(["name", "cmdline"]):
                try:
                    cmdline = proc.info.get("cmdline") or []
                    cmdline_str = " ".join(cmdline).lower()
                    
                    # Check for GUI process
                    if "gui.py" in cmdline_str and "python" in cmdline_str:
                        if "gui" not in active_channels:
                            active_channels.append("gui")
                    
                    # Check for Telegram bot process
                    if "telegram_bot.py" in cmdline_str and "python" in cmdline_str:
                        if "telegram" not in active_channels:
                            active_channels.append("telegram")
                    
                    # Check for CLI chat process
                    if "chat.py" in cmdline_str and "python" in cmdline_str:
                        if "cli" not in active_channels:
                            active_channels.append("cli")
                
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        
        except Exception as e:
            print(
                f"[NotificationRouter] ⚠️  Failed to detect active channels: {e}",
                flush=True,
            )
        
        return active_channels
    
    def format_for_channel(self, event: ProactiveEvent, channel: str) -> str:
        """
        Format notification message for a specific channel.
        
        Args:
            event: ProactiveEvent to format
            channel: Target channel ("gui", "telegram", "cli")
        
        Returns:
            Formatted message string
        """
        if channel == "gui":
            # Rich text formatting for GUI (HTML-like)
            # Add icons and styling based on priority
            icon = self._get_priority_icon(event.priority)
            return f"{icon} {event.message}"
        
        elif channel == "telegram":
            # Plain text with emojis for Telegram
            emoji = self._get_priority_emoji(event.priority)
            return f"{emoji} {event.message}"
        
        elif channel == "cli":
            # Plain text for CLI
            prefix = self._get_priority_prefix(event.priority)
            return f"{prefix} {event.message}"
        
        else:
            # Default: plain text
            return event.message
    
    def _get_priority_icon(self, priority: str) -> str:
        """Get icon for GUI based on priority level."""
        icons = {
            "critical": "🚨",
            "high": "⚠️",
            "medium": "ℹ️",
            "low": "💡",
        }
        return icons.get(priority, "ℹ️")
    
    def _get_priority_emoji(self, priority: str) -> str:
        """Get emoji for Telegram based on priority level."""
        emojis = {
            "critical": "🚨",
            "high": "⚠️",
            "medium": "📢",
            "low": "💬",
        }
        return emojis.get(priority, "📢")
    
    def _get_priority_prefix(self, priority: str) -> str:
        """Get text prefix for CLI based on priority level."""
        prefixes = {
            "critical": "[CRITICAL]",
            "high": "[HIGH]",
            "medium": "[INFO]",
            "low": "[NOTE]",
        }
        return prefixes.get(priority, "[INFO]")
    
    def is_duplicate(self, notification_id: str) -> bool:
        """
        Check if notification has already been delivered.
        
        Args:
            notification_id: Unique notification ID to check
        
        Returns:
            True if notification was already delivered, False otherwise
        """
        return notification_id in self._delivered_ids
    
    def log_notification(
        self,
        notification_id: str,
        event: ProactiveEvent,
        channels: List[str],
        delivered: bool,
        error: Optional[str] = None,
    ) -> None:
        """
        Log notification delivery to notifications.jsonl.
        
        Args:
            notification_id: Unique notification ID
            event: ProactiveEvent that was delivered
            channels: List of channels where notification was delivered
            delivered: Whether delivery was successful
            error: Error message if delivery failed (None if successful)
        """
        try:
            log_entry = NotificationLog(
                id=notification_id,
                timestamp=datetime.now(),
                kind=event.kind,
                priority=event.priority,
                channels=channels,
                delivered=delivered,
                error=error,
            )
            
            # Convert to JSON-serializable dict
            log_dict = {
                "id": log_entry.id,
                "timestamp": log_entry.timestamp.isoformat(),
                "kind": log_entry.kind,
                "priority": log_entry.priority,
                "channels": log_entry.channels,
                "delivered": log_entry.delivered,
                "error": log_entry.error,
            }
            
            # Append to JSONL file
            with open(self.notifications_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_dict, ensure_ascii=False) + "\n")
            
            # Add to in-memory cache
            if delivered:
                self._delivered_ids.add(notification_id)
        
        except Exception as e:
            print(
                f"[NotificationRouter] ❌ Failed to log notification: {e}",
                flush=True,
            )
    
    def route_notification(self, event: ProactiveEvent) -> Dict[str, Any]:
        """
        Route a ProactiveEvent to all active channels.
        
        Main routing logic that:
        1. Checks for duplicates
        2. Checks DND mode (skip non-critical)
        3. Detects active channels
        4. Formats message for each channel
        5. Logs delivery
        
        Args:
            event: ProactiveEvent to route
        
        Returns:
            Dictionary with routing result:
            {
                "delivered": bool,
                "channels": List[str],
                "skipped_reason": Optional[str],
                "formatted_messages": Dict[str, str]
            }
        """
        notification_id = event.notification_id
        
        # Check for duplicates
        if self.is_duplicate(notification_id):
            print(
                f"[NotificationRouter] ⏭️  Skipping duplicate notification: {notification_id}",
                flush=True,
            )
            return {
                "delivered": False,
                "channels": [],
                "skipped_reason": "duplicate",
                "formatted_messages": {},
            }
        
        # Check DND mode (skip non-critical notifications)
        if self.is_dnd_active() and event.priority != "critical":
            print(
                f"[NotificationRouter] 🔕 Skipping notification during DND: {event.kind} (priority: {event.priority})",
                flush=True,
            )
            self.log_notification(
                notification_id,
                event,
                channels=[],
                delivered=False,
                error="Suppressed by DND mode",
            )
            return {
                "delivered": False,
                "channels": [],
                "skipped_reason": "dnd_mode",
                "formatted_messages": {},
            }
        
        # Detect active channels
        active_channels = self.detect_active_channels()
        
        if not active_channels:
            print(
                f"[NotificationRouter] ⚠️  No active channels found for notification: {event.kind}",
                flush=True,
            )
            self.log_notification(
                notification_id,
                event,
                channels=[],
                delivered=False,
                error="No active channels",
            )
            return {
                "delivered": False,
                "channels": [],
                "skipped_reason": "no_channels",
                "formatted_messages": {},
            }
        
        # Format message for each channel
        formatted_messages: Dict[str, str] = {}
        for channel in active_channels:
            formatted_messages[channel] = self.format_for_channel(event, channel)
        
        # Log successful routing
        self.log_notification(
            notification_id,
            event,
            channels=active_channels,
            delivered=True,
            error=None,
        )
        
        print(
            f"[NotificationRouter] ✅ Routed notification to {len(active_channels)} channel(s): {', '.join(active_channels)}",
            flush=True,
        )
        
        return {
            "delivered": True,
            "channels": active_channels,
            "skipped_reason": None,
            "formatted_messages": formatted_messages,
        }
