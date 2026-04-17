"""
AutoExecutor for A.N.K.I.T.A — Autonomous Background Action System.

Executes low-risk background actions with three safety tiers:
  - Class A: Always automatic / silent (no notification to user)
  - Class B: Automatic with notification
  - Class C: Queued for user approval — NEVER auto-executed

Requirements: 5.1, 5.2, 5.3, 5.4

Called by ProactiveEngine.tick() on every polling cycle.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from proactive_models import ProactiveEvent


class AutoExecutor:
    """
    Autonomous background action executor with Class A/B/C safety tiers.

    Class A — Always automatic, silent execution:
        - Daily disk usage analysis (read-only, cached)
        - Nightly memory consolidation (compacts patterns.jsonl)

    Class B — Automatic with ProactiveEvent notification:
        - Battery < 20% and unplugged → alert

    Class C — Queue for user approval (NEVER auto-execute):
        - Stale Downloads folder items (> 30 days) → ask user

    Each action is guarded by a cooldown so it doesn't fire repeatedly.
    All executions are logged to .ankita/state/auto_actions_log.json.
    """

    # Cooldowns (seconds between re-runs of the same action)
    _COOLDOWNS: Dict[str, float] = {
        "disk_analysis": 24 * 3600,      # once per day
        "memory_consolidate": 24 * 3600,  # once per night
        "battery_alert": 30 * 60,         # once per 30 minutes
        "stale_downloads": 7 * 24 * 3600, # once per week
    }

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self._state_dir = workspace_root / ".ankita" / "state"
        self._log_file = self._state_dir / "auto_actions_log.json"
        self._state_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cooldown tracker: {action_id: last_run_epoch}
        self._last_run: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def tick(self, proactive_engine: Any) -> None:
        """
        Run one executor tick — check all actions and execute if eligible.

        Args:
            proactive_engine: The active ProactiveEngine instance used to
                              push ProactiveEvents for Class B actions.
        """
        self._run_class_a()
        self._run_class_b(proactive_engine)
        self._run_class_c(proactive_engine)

    # ------------------------------------------------------------------
    # Class A — Silent automatic actions
    # ------------------------------------------------------------------

    def _run_class_a(self) -> None:
        """Execute silent automatic actions (Class A)."""
        self._action_disk_analysis()
        self._action_memory_consolidate()

    def _action_disk_analysis(self) -> None:
        """
        Class A: Analyse disk usage once per day (read-only).

        Caches the result so other components (for example InsightSynthesizer)
        can read it without re-running the expensive disk scan.
        """
        if not self._is_due("disk_analysis"):
            return

        try:
            import psutil  # type: ignore
            disk = psutil.disk_usage(str(self.workspace_root))
            result = {
                "total_gb": round(disk.total / (1024 ** 3), 1),
                "used_gb": round(disk.used / (1024 ** 3), 1),
                "free_gb": round(disk.free / (1024 ** 3), 1),
                "percent": round(disk.percent, 1),
            }
            self._log_action("A", "disk_analysis", "Disk usage analysed", result)
            self._mark_run("disk_analysis")
        except ImportError:
            pass
        except Exception as e:
            print(f"[AutoExecutor] disk_analysis failed: {e}", flush=True)

    def _action_memory_consolidate(self) -> None:
        """
        Class A: Consolidate long-term memory once per night.

        Triggers the MemoryManager's consolidation/summarisation so the
        context window stays lean over time.
        """
        now = datetime.now()
        # Only run between 00:00 and 05:00
        if not (0 <= now.hour < 5):
            return
        if not self._is_due("memory_consolidate"):
            return

        try:
            from memory import get_memory_manager  # type: ignore
            mgr = get_memory_manager(self.workspace_root)
            if hasattr(mgr, "consolidate"):
                mgr.consolidate()
            self._log_action("A", "memory_consolidate", "Long-term memory consolidated", {})
            self._mark_run("memory_consolidate")
        except Exception as e:
            print(f"[AutoExecutor] memory_consolidate failed: {e}", flush=True)

    # ------------------------------------------------------------------
    # Class B — Automatic with notification
    # ------------------------------------------------------------------

    def _run_class_b(self, proactive_engine: Any) -> None:
        """Execute actions that notify the user (Class B)."""
        self._action_battery_alert(proactive_engine)

    def _action_battery_alert(self, proactive_engine: Any) -> None:
        """
        Class B: Alert when battery < 20% and unplugged.

        Emits a high-priority ProactiveEvent so the user is notified via
        whatever channel (GUI, Telegram, CLI) is active.
        """
        if not self._is_due("battery_alert"):
            return

        try:
            import psutil  # type: ignore
            batt = psutil.sensors_battery()
            if batt is None:
                return
            if batt.power_plugged or batt.percent > 20:
                return

            pct = round(batt.percent, 0)
            msg = f"🔋 AutoExecutor: Battery at {pct:.0f}% and unplugged. Please charge soon."
            event = ProactiveEvent(
                kind="auto_action",
                message=msg,
                data={"action": "battery_alert", "battery_pct": pct},
                priority="high",
                urgency="immediate",
                interruptible=True,
            )
            if hasattr(proactive_engine, "_queue"):
                proactive_engine._queue.put(event)

            self._log_action("B", "battery_alert", msg, {"battery_pct": pct})
            self._mark_run("battery_alert")

        except ImportError:
            pass
        except Exception as e:
            print(f"[AutoExecutor] battery_alert failed: {e}", flush=True)

    # ------------------------------------------------------------------
    # Class C — Queued for user approval (NO auto-execution)
    # ------------------------------------------------------------------

    def _run_class_c(self, proactive_engine: Any) -> None:
        """Surface Class C approval-required suggestions."""
        self._action_stale_downloads(proactive_engine)

    def _action_stale_downloads(self, proactive_engine: Any) -> None:
        """
        Class C: Suggest cleaning stale Downloads items (> 30 days).

        NEVER deletes anything automatically. Only asks the user once per week.
        """
        if not self._is_due("stale_downloads"):
            return

        try:
            downloads_dir = Path.home() / "Downloads"
            if not downloads_dir.exists():
                return

            cutoff = time.time() - (30 * 24 * 3600)
            stale: List[str] = []
            for item in downloads_dir.iterdir():
                try:
                    if item.stat().st_mtime < cutoff:
                        stale.append(item.name)
                except Exception:
                    pass

            if not stale:
                return

            preview = ", ".join(stale[:3])
            if len(stale) > 3:
                preview += f" and {len(stale) - 3} more"

            msg = (
                f"🗂️ Your Downloads folder has {len(stale)} items older than 30 days "
                f"({preview}). Want me to help clean them up?"
            )
            event = ProactiveEvent(
                kind="auto_action",
                message=msg,
                data={"action": "stale_downloads", "count": len(stale), "items": stale[:10]},
                priority="low",
                urgency="next_session",
                interruptible=False,
            )
            if hasattr(proactive_engine, "_queue"):
                proactive_engine._queue.put(event)

            self._log_action("C", "stale_downloads", msg, {"count": len(stale)})
            self._mark_run("stale_downloads")

        except Exception as e:
            print(f"[AutoExecutor] stale_downloads failed: {e}", flush=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_due(self, action_id: str) -> bool:
        """Return True if the action cooldown has expired."""
        cooldown = self._COOLDOWNS.get(action_id, 3600)
        last = self._last_run.get(action_id, 0.0)
        return (time.time() - last) >= cooldown

    def _mark_run(self, action_id: str) -> None:
        """Mark action as run now."""
        self._last_run[action_id] = time.time()

    def _log_action(
        self,
        action_class: str,
        action_type: str,
        description: str,
        outcome: Dict[str, Any],
    ) -> None:
        """Append an entry to auto_actions_log.json."""
        try:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "class": action_class,
                "action": action_type,
                "description": description,
                "outcome": outcome,
            }
            # Load existing log
            log: List[Dict[str, Any]] = []
            if self._log_file.exists():
                try:
                    raw = self._log_file.read_text(encoding="utf-8")
                    loaded = json.loads(raw)
                    if isinstance(loaded, list):
                        log = loaded
                except Exception:
                    pass

            log.append(entry)

            # Keep last 500 entries
            if len(log) > 500:
                log = log[-500:]

            self._log_file.write_text(
                json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(
                f"[AutoExecutor] Class {action_class} — {action_type}: {description[:60]}",
                flush=True,
            )
        except Exception as e:
            print(f"[AutoExecutor] Failed to log action: {e}", flush=True)
