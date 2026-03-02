"""
AnomalyWatcher — Behavioral Anomaly Detector for A.N.K.I.T.A.

Builds a baseline of normal system behavior (CPU, RAM, network, disk I/O)
over time and alerts when current metrics deviate significantly from the norm.

True Jarvis behavior: "Something's off — your RAM is 40% higher than usual at this hour."

Config (anomaly_config.json):
    {
        "enabled": true,
        "poll_interval_sec": 60,
        "baseline_samples": 168,
        "z_score_threshold": 2.5,
        "min_samples_before_alert": 24,
        "cooldown_sec": 600
    }
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from watchdog_manager import BaseWatcher
from proactive import ProactiveEngine

try:
    import psutil  # type: ignore
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class AnomalyWatcher(BaseWatcher):
    """
    Detects abnormal system behavior by comparing current metrics to a
    rolling historical baseline using Z-score analysis.

    Metrics tracked:
      - CPU usage %
      - RAM usage %
      - Disk I/O (read + write MB/s)
      - Network I/O (sent + recv MB/s)

    Alert fires when a metric's Z-score exceeds z_score_threshold
    (default 2.5 standard deviations from the mean).
    """

    METRICS = ["cpu_pct", "ram_pct", "disk_io_mbps", "net_io_mbps"]

    def __init__(
        self,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        super().__init__(
            name="AnomalyWatcher",
            config=config,
            proactive=proactive,
            workspace_root=workspace_root,
        )
        self.poll_interval = float(config.get("poll_interval_sec", 60))
        self.baseline_samples = int(config.get("baseline_samples", 168))  # 1 week at 1/hr
        self.z_threshold = float(config.get("z_score_threshold", 2.5))
        self.min_samples = int(config.get("min_samples_before_alert", 24))
        self.cooldown_sec = float(config.get("cooldown_sec", 600))

        # State: rolling baseline history per metric
        self.state.setdefault("baseline", {m: [] for m in self.METRICS})
        self.state.setdefault("last_alert_time", {})

        # I/O counters for delta calculation
        self._last_disk_io = None
        self._last_net_io = None
        self._last_io_ts = None

    # ------------------------------------------------------------------
    # Main check
    # ------------------------------------------------------------------

    def _check(self) -> Optional[str]:
        if not HAS_PSUTIL:
            return None

        snapshot = self._collect_metrics()
        if snapshot is None:
            return None

        alerts: List[str] = []
        baseline = self.state["baseline"]

        for metric, value in snapshot.items():
            history = baseline.get(metric, [])

            # Add current value to baseline
            history.append({"ts": time.time(), "val": value})
            # Keep only the most recent N samples
            baseline[metric] = history[-self.baseline_samples:]

            # Need enough data before alerting
            if len(history) < self.min_samples:
                print(
                    f"[AnomalyWatcher] {metric}: {value:.2f} "
                    f"(collecting baseline {len(history)}/{self.min_samples})",
                    flush=True,
                )
                continue

            # Calculate Z-score
            vals = [h["val"] for h in history[:-1]]  # exclude current point
            mean, std = self._mean_std(vals)
            if std < 0.5:
                continue  # Too stable to generate meaningful anomaly scores

            z_score = (value - mean) / std
            print(
                f"[AnomalyWatcher] {metric}: {value:.2f}  mean={mean:.2f}  "
                f"std={std:.2f}  z={z_score:.2f}",
                flush=True,
            )

            if abs(z_score) >= self.z_threshold:
                alert = self._maybe_alert(
                    metric,
                    self._format_anomaly_alert(metric, value, mean, std, z_score),
                )
                if alert:
                    alerts.append(alert)

        self.state["baseline"] = baseline
        self._save_state()

        if alerts:
            return "\n".join(alerts)
        return None

    # ------------------------------------------------------------------
    # Metric collection
    # ------------------------------------------------------------------

    def _collect_metrics(self) -> Optional[Dict[str, float]]:
        """Collect current system metrics snapshot."""
        try:
            cpu_pct = psutil.cpu_percent(interval=1)
            ram_pct = psutil.virtual_memory().percent

            # Disk I/O delta (MB/s)
            disk_io_mbps = 0.0
            try:
                now_disk = psutil.disk_io_counters()
                now_ts = time.time()
                if self._last_disk_io and self._last_io_ts:
                    dt = now_ts - self._last_io_ts
                    if dt > 0:
                        read_bytes = now_disk.read_bytes - self._last_disk_io.read_bytes
                        write_bytes = now_disk.write_bytes - self._last_disk_io.write_bytes
                        disk_io_mbps = (read_bytes + write_bytes) / (1024 * 1024 * dt)
                self._last_disk_io = now_disk
            except Exception:
                pass

            # Network I/O delta (MB/s)
            net_io_mbps = 0.0
            try:
                now_net = psutil.net_io_counters()
                now_ts = time.time()
                if self._last_net_io and self._last_io_ts:
                    dt = now_ts - self._last_io_ts
                    if dt > 0:
                        sent_bytes = now_net.bytes_sent - self._last_net_io.bytes_sent
                        recv_bytes = now_net.bytes_recv - self._last_net_io.bytes_recv
                        net_io_mbps = (sent_bytes + recv_bytes) / (1024 * 1024 * dt)
                self._last_net_io = now_net
            except Exception:
                pass

            self._last_io_ts = time.time()

            return {
                "cpu_pct": cpu_pct,
                "ram_pct": ram_pct,
                "disk_io_mbps": disk_io_mbps,
                "net_io_mbps": net_io_mbps,
            }
        except Exception as exc:
            print(f"[AnomalyWatcher] Metric collection failed: {exc}", flush=True)
            return None

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    @staticmethod
    def _mean_std(values: List[float]) -> Tuple[float, float]:
        """Calculate mean and standard deviation of a list of floats."""
        if not values:
            return 0.0, 0.0
        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n
        std = math.sqrt(variance)
        return mean, std

    # ------------------------------------------------------------------
    # Alert formatting
    # ------------------------------------------------------------------

    def _format_anomaly_alert(
        self, metric: str, value: float, mean: float, std: float, z_score: float
    ) -> str:
        direction = "higher" if z_score > 0 else "lower"
        pct_diff = abs((value - mean) / mean * 100) if mean > 0 else 0

        labels = {
            "cpu_pct": ("CPU usage", f"{value:.0f}%", f"{mean:.0f}%"),
            "ram_pct": ("RAM usage", f"{value:.0f}%", f"{mean:.0f}%"),
            "disk_io_mbps": ("Disk I/O", f"{value:.1f} MB/s", f"{mean:.1f} MB/s"),
            "net_io_mbps": ("Network I/O", f"{value:.1f} MB/s", f"{mean:.1f} MB/s"),
        }
        metric_name, current_str, normal_str = labels.get(
            metric, (metric, f"{value:.2f}", f"{mean:.2f}")
        )

        emoji = "🔥" if metric == "cpu_pct" else (
            "🧠" if metric == "ram_pct" else (
                "💿" if metric == "disk_io_mbps" else "🌐"
            )
        )

        return (
            f"{emoji} Anomaly detected: {metric_name} is {pct_diff:.0f}% {direction} than usual!\n"
            f"   Current: {current_str}  |  Normal: ~{normal_str}  |  Z-score: {z_score:+.1f}\n"
            f"   Something may be running in the background. Want me to check?"
        )

    def _maybe_alert(self, key: str, message: str) -> Optional[str]:
        """Return message if cooldown has elapsed for this key, else None."""
        now = time.time()
        last = self.state["last_alert_time"].get(key, 0)
        if now - last >= self.cooldown_sec:
            self.state["last_alert_time"][key] = now
            return message
        return None

    def get_baseline_summary(self) -> str:
        """Return a summary of learned baselines (callable by WatchdogAgent)."""
        baseline = self.state.get("baseline", {})
        lines = ["📊 AnomalyWatcher Baseline Summary:"]
        for metric, history in baseline.items():
            if not history:
                lines.append(f"  {metric}: no data yet")
                continue
            vals = [h["val"] for h in history]
            mean, std = self._mean_std(vals)
            labels = {
                "cpu_pct": "CPU", "ram_pct": "RAM",
                "disk_io_mbps": "Disk I/O", "net_io_mbps": "Net I/O",
            }
            unit = "%" if "pct" in metric else " MB/s"
            lines.append(
                f"  {labels.get(metric, metric):<12} "
                f"mean={mean:.1f}{unit}  std={std:.1f}{unit}  "
                f"samples={len(vals)}"
            )
        return "\n".join(lines)
