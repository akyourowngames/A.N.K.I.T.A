"""
DiskWatcher — Disk Space & Storage Guardian for A.N.K.I.T.A.

Monitors disk usage across all drives. Alerts when free space is critically low,
and identifies the biggest space consumers so ANKITA can suggest cleanup.

Config (disk_config.json):
    {
        "enabled": true,
        "poll_interval_sec": 300,
        "free_space_alert_pct": 10,
        "free_space_critical_pct": 5,
        "watch_paths": ["C:/", "D:/"],
        "track_growth": true,
        "growth_alert_mb_per_hour": 500,
        "cooldown_sec": 1800
    }
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from watchdog_manager import BaseWatcher
from proactive import ProactiveEngine

try:
    import psutil  # type: ignore
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class DiskWatcher(BaseWatcher):
    """
    Monitors disk usage and growth trends.

    - Alerts when free space drops below configurable thresholds (warning + critical)
    - Identifies top space consumers (largest directories)
    - Detects rapid disk growth (e.g. runaway logs, downloads)
    - Tracks per-drive usage history for trend analysis
    """

    def __init__(
        self,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        super().__init__(
            name="DiskWatcher",
            config=config,
            proactive=proactive,
            workspace_root=workspace_root,
        )
        self.poll_interval = float(config.get("poll_interval_sec", 300))
        self.free_alert_pct = float(config.get("free_space_alert_pct", 10))
        self.free_critical_pct = float(config.get("free_space_critical_pct", 5))
        self.growth_alert_mb_hr = float(config.get("growth_alert_mb_per_hour", 500))
        self.cooldown_sec = float(config.get("cooldown_sec", 1800))

        # State
        self.state.setdefault("last_alert_time", {})
        self.state.setdefault("usage_history", {})  # {path: [{ts, used_gb}]}

    def _check(self) -> Optional[str]:
        if not HAS_PSUTIL:
            return None

        watch_paths = self.config.get("watch_paths", [])
        alerts: List[str] = []

        # If no explicit paths, auto-discover all physical disk partitions
        if not watch_paths:
            try:
                watch_paths = [
                    p.mountpoint for p in psutil.disk_partitions(all=False)
                    if p.fstype and "cdrom" not in p.opts
                ]
            except Exception:
                watch_paths = ["C:/"]

        for path_str in watch_paths:
            path = Path(path_str)
            try:
                usage = psutil.disk_usage(str(path))
            except Exception as exc:
                print(f"[DiskWatcher] Cannot stat {path}: {exc}", flush=True)
                continue

            total_gb = usage.total / (1024 ** 3)
            used_gb = usage.used / (1024 ** 3)
            free_gb = usage.free / (1024 ** 3)
            free_pct = usage.percent  # psutil gives used%, so free = 100 - used
            free_pct_actual = 100.0 - usage.percent

            key = str(path)
            print(
                f"[DiskWatcher] {key}: {free_pct_actual:.1f}% free "
                f"({free_gb:.1f} GB free / {total_gb:.1f} GB total)",
                flush=True,
            )

            # Track usage history for growth detection
            if self.config.get("track_growth", True):
                history = self.state["usage_history"].setdefault(key, [])
                history.append({"ts": time.time(), "used_gb": used_gb})
                # Keep last 24 data points
                self.state["usage_history"][key] = history[-24:]

                # Check growth rate
                growth_alert = self._check_growth(key, history)
                if growth_alert:
                    alerts.append(growth_alert)

            # Critical space alert
            if free_pct_actual <= self.free_critical_pct:
                alert = self._maybe_alert(
                    f"{key}_critical",
                    f"🚨 CRITICAL: Drive {path_str} is almost FULL! "
                    f"Only {free_gb:.1f} GB ({free_pct_actual:.1f}%) remaining. "
                    f"Immediate cleanup needed!",
                )
                if alert:
                    alerts.append(alert)
                    # Append top consumers for critical alerts
                    top = self._get_top_consumers(path, n=3)
                    if top:
                        alerts.append(top)

            # Warning space alert
            elif free_pct_actual <= self.free_alert_pct:
                alert = self._maybe_alert(
                    f"{key}_warning",
                    f"⚠️ Drive {path_str} is running low: "
                    f"{free_gb:.1f} GB ({free_pct_actual:.1f}%) free of {total_gb:.1f} GB. "
                    f"Want me to find what's taking up space?",
                )
                if alert:
                    alerts.append(alert)

        self._save_state()

        if alerts:
            return "\n".join(alerts)
        return None

    def _check_growth(self, key: str, history: List[Dict]) -> Optional[str]:
        """
        Detect rapid disk growth by comparing current vs oldest data point.
        Alerts if growth rate exceeds growth_alert_mb_hr MB/hour.
        """
        if len(history) < 2:
            return None
        oldest = history[0]
        newest = history[-1]
        time_diff_hr = (newest["ts"] - oldest["ts"]) / 3600
        if time_diff_hr < 0.1:  # Need at least ~6 minutes of data
            return None
        growth_gb = newest["used_gb"] - oldest["used_gb"]
        growth_mb_hr = (growth_gb * 1024) / time_diff_hr
        if growth_mb_hr >= self.growth_alert_mb_hr:
            alert = self._maybe_alert(
                f"{key}_growth",
                f"📈 Drive {key} is filling up fast! "
                f"Growing at {growth_mb_hr:.0f} MB/hour — "
                f"something may be logging or downloading excessively.",
            )
            return alert
        return None

    def _get_top_consumers(self, base_path: Path, n: int = 5) -> str:
        """
        Find top N largest direct subdirectories under base_path.
        Uses a fast shallow scan (not recursive) to avoid being too slow.
        """
        try:
            sizes = []
            for child in base_path.iterdir():
                try:
                    if child.is_dir():
                        # Estimate size by sampling (fast)
                        size = sum(
                            f.stat().st_size
                            for f in child.iterdir()
                            if f.is_file()
                        )
                        sizes.append((size, child.name))
                except (PermissionError, OSError):
                    continue
            sizes.sort(reverse=True)
            if not sizes:
                return ""
            lines = [f"   📦 Largest folders in {base_path}:"]
            for size_bytes, name in sizes[:n]:
                size_gb = size_bytes / (1024 ** 3)
                lines.append(f"      {name:<35} {size_gb:.2f} GB")
            return "\n".join(lines)
        except Exception:
            return ""

    def _maybe_alert(self, key: str, message: str) -> Optional[str]:
        """Return message if cooldown has elapsed for this key, else None."""
        now = time.time()
        last = self.state["last_alert_time"].get(key, 0)
        if now - last >= self.cooldown_sec:
            self.state["last_alert_time"][key] = now
            return message
        return None

    def get_disk_summary(self) -> str:
        """Return formatted disk summary for all drives (callable by WatchdogAgent)."""
        if not HAS_PSUTIL:
            return "psutil not available."
        lines = ["💾 Disk Usage Summary:"]
        try:
            for part in psutil.disk_partitions(all=False):
                if not part.fstype:
                    continue
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    free_pct = 100.0 - usage.percent
                    free_gb = usage.free / (1024 ** 3)
                    total_gb = usage.total / (1024 ** 3)
                    bar_filled = int(usage.percent / 5)
                    bar = "█" * bar_filled + "░" * (20 - bar_filled)
                    emoji = "🚨" if free_pct <= 5 else ("⚠️" if free_pct <= 10 else "✅")
                    lines.append(
                        f"  {emoji} {part.mountpoint:<8} [{bar}] "
                        f"{usage.percent:.0f}% used  ({free_gb:.1f} GB free / {total_gb:.1f} GB)"
                    )
                except Exception:
                    pass
        except Exception as e:
            return f"Error reading disk info: {e}"
        return "\n".join(lines)
