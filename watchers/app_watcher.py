"""
AppWatcher — Process & Application Health Monitor for A.N.K.I.T.A.

Monitors running processes for crashes, resource hogs, and unresponsive apps.
Alerts when apps are consuming too much CPU/RAM or have crashed.

Config (app_config.json):
    {
        "enabled": true,
        "poll_interval_sec": 30,
        "cpu_threshold_pct": 80,
        "ram_threshold_mb": 1500,
        "watch_processes": ["chrome", "code", "python", "node"],
        "alert_on_crash": true,
        "cooldown_sec": 300
    }
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set
from pathlib import Path

from watchdog_manager import BaseWatcher
from proactive import ProactiveEngine

try:
    import psutil  # type: ignore
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class AppWatcher(BaseWatcher):
    """
    Monitors running processes for CPU/RAM hogs, crashes, and unresponsive states.

    - Tracks a baseline of running processes to detect crashes (process disappeared)
    - Alerts when a watched process exceeds CPU or RAM thresholds
    - Cooldown per-process to prevent alert spam
    """

    def __init__(
        self,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        super().__init__(
            name="AppWatcher",
            config=config,
            proactive=proactive,
            workspace_root=workspace_root,
        )
        self.poll_interval = float(config.get("poll_interval_sec", 30))
        self.cpu_threshold = float(config.get("cpu_threshold_pct", 80))
        self.ram_threshold_mb = float(config.get("ram_threshold_mb", 1500))
        self.cooldown_sec = float(config.get("cooldown_sec", 300))

        # State: previously seen PIDs → process name mapping for crash detection
        self.state.setdefault("known_pids", {})          # {pid_str: name}
        self.state.setdefault("last_alert_time", {})     # {name: epoch}
        self.state.setdefault("crash_history", {})       # {name: count}

        # In-memory set of PIDs we have seen (rebuilt each cycle)
        self._prev_pids: Dict[int, str] = {
            int(k): v for k, v in self.state.get("known_pids", {}).items()
        }

    def _check(self) -> Optional[str]:
        if not HAS_PSUTIL:
            return None

        watch_procs: List[str] = [
            p.lower() for p in self.config.get("watch_processes", [])
        ]
        alert_on_crash: bool = self.config.get("alert_on_crash", True)

        alerts: List[str] = []
        current_pids: Dict[int, str] = {}

        # Scan all running processes
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status"]):
            try:
                pid = proc.info["pid"]
                name = (proc.info["name"] or "").lower()
                status = proc.info.get("status", "")
                current_pids[pid] = name

                # Only alert on watched processes (or all if list is empty)
                is_watched = not watch_procs or any(w in name for w in watch_procs)
                if not is_watched:
                    continue

                # Check if process is a zombie / unresponsive
                if status in ("zombie", "dead"):
                    alert = self._maybe_alert(
                        name,
                        f"💀 Process '{proc.info['name']}' (PID {pid}) is unresponsive/zombie.",
                    )
                    if alert:
                        alerts.append(alert)
                    continue

                # CPU hog check
                cpu_pct = proc.info.get("cpu_percent") or 0.0
                if cpu_pct >= self.cpu_threshold:
                    alert = self._maybe_alert(
                        f"{name}_cpu",
                        f"🔥 '{proc.info['name']}' is eating {cpu_pct:.0f}% CPU! "
                        f"(PID {pid}) — want me to restart it?",
                    )
                    if alert:
                        alerts.append(alert)

                # RAM hog check
                mem_info = proc.info.get("memory_info")
                if mem_info:
                    ram_mb = mem_info.rss / (1024 * 1024)
                    if ram_mb >= self.ram_threshold_mb:
                        alert = self._maybe_alert(
                            f"{name}_ram",
                            f"🧠 '{proc.info['name']}' is using {ram_mb:.0f} MB RAM! "
                            f"(PID {pid}) — want me to restart it?",
                        )
                        if alert:
                            alerts.append(alert)

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        # Crash detection — process that was watched is now gone
        if alert_on_crash and self._prev_pids:
            for pid, name in self._prev_pids.items():
                is_watched = not watch_procs or any(w in name for w in watch_procs)
                if not is_watched:
                    continue
                if pid not in current_pids:
                    # Process disappeared — potential crash
                    clean_name = name.replace(".exe", "").title()
                    crash_count = self.state["crash_history"].get(name, 0) + 1
                    self.state["crash_history"][name] = crash_count
                    alert = self._maybe_alert(
                        f"{name}_crash",
                        f"💥 '{clean_name}' just crashed or closed unexpectedly! "
                        f"(PID {pid} gone, crash #{crash_count}) — want me to relaunch it?",
                    )
                    if alert:
                        alerts.append(alert)

        # Update known PIDs for next cycle
        self._prev_pids = current_pids
        self.state["known_pids"] = {str(k): v for k, v in current_pids.items()}
        self._save_state()

        if alerts:
            return "\n".join(alerts)
        return None

    def _maybe_alert(self, key: str, message: str) -> Optional[str]:
        """Return message if cooldown has elapsed for this key, else None."""
        now = time.time()
        last = self.state["last_alert_time"].get(key, 0)
        if now - last >= self.cooldown_sec:
            self.state["last_alert_time"][key] = now
            return message
        return None

    def get_top_processes(self, n: int = 5) -> str:
        """Return top N processes by CPU usage (callable by WatchdogAgent)."""
        if not HAS_PSUTIL:
            return "psutil not installed."
        procs = []
        for proc in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
            try:
                cpu = proc.info.get("cpu_percent") or 0.0
                mem_mb = (proc.info.get("memory_info") or type("", (), {"rss": 0})()).rss / (1024 * 1024)
                procs.append((cpu, mem_mb, proc.info["name"] or "?"))
            except Exception:
                continue
        procs.sort(reverse=True)
        lines = [f"🔝 Top {n} processes by CPU:"]
        for cpu, mem, name in procs[:n]:
            lines.append(f"  {name:<30} CPU: {cpu:5.1f}%  RAM: {mem:.0f} MB")
        return "\n".join(lines)
