"""
BatteryWatcher — Smart Battery Guard for A.N.K.I.T.A.

Smarter than the basic battery check in ProactiveEngine.
Tracks charge/discharge rates, plug events, overcharge protection,
and time-to-empty estimates.

Config (battery_config.json):
    {
        "enabled": true,
        "poll_interval_sec": 60,
        "low_battery_pct": 20,
        "critical_battery_pct": 10,
        "overcharge_pct": 95,
        "alert_on_plug_unplug": true,
        "cooldown_sec": 300
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


class BatteryWatcher(BaseWatcher):
    """
    Advanced battery monitoring — tracks charge rate, plug/unplug events,
    time-to-empty estimation, and overcharge protection alerts.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        super().__init__(
            name="BatteryWatcher",
            config=config,
            proactive=proactive,
            workspace_root=workspace_root,
        )
        self.poll_interval = float(config.get("poll_interval_sec", 60))
        self.low_pct = float(config.get("low_battery_pct", 20))
        self.critical_pct = float(config.get("critical_battery_pct", 10))
        self.overcharge_pct = float(config.get("overcharge_pct", 95))
        self.cooldown_sec = float(config.get("cooldown_sec", 300))
        self.alert_plug_unplug = config.get("alert_on_plug_unplug", True)

        # State
        self.state.setdefault("was_plugged", None)       # None = unknown
        self.state.setdefault("last_pct", None)
        self.state.setdefault("last_alert_time", {})
        self.state.setdefault("pct_history", [])         # [{ts, pct, plugged}]

    def _check(self) -> Optional[str]:
        if not HAS_PSUTIL:
            return None

        try:
            batt = psutil.sensors_battery()
        except Exception:
            return None

        if batt is None:
            return None  # Desktop / no battery

        pct = batt.percent
        plugged = batt.power_plugged
        secsleft = batt.secsleft  # seconds left (negative if unknown/charging)

        alerts: List[str] = []
        now = time.time()

        # Track history for rate calculation
        history = self.state["pct_history"]
        history.append({"ts": now, "pct": pct, "plugged": plugged})
        self.state["pct_history"] = history[-30:]  # Keep 30 data points (~30 min)

        print(
            f"[BatteryWatcher] {pct:.0f}%  {'🔌 Charging' if plugged else '🔋 Discharging'}  "
            f"secsleft={secsleft}",
            flush=True,
        )

        was_plugged = self.state.get("was_plugged")

        # --- Plug / Unplug events ---
        if self.alert_plug_unplug and was_plugged is not None:
            if plugged and not was_plugged:
                alert = self._maybe_alert(
                    "plugged_in",
                    f"🔌 Charger plugged in — battery at {pct:.0f}%.",
                )
                if alert:
                    alerts.append(alert)

            elif not plugged and was_plugged:
                tte = self._estimate_time_remaining(history, charging=False)
                tte_str = f" — estimated ~{tte} remaining." if tte else "."
                alert = self._maybe_alert(
                    "unplugged",
                    f"🔋 Charger unplugged — battery at {pct:.0f}%{tte_str}",
                )
                if alert:
                    alerts.append(alert)

        self.state["was_plugged"] = plugged

        # --- Low battery ---
        if not plugged:
            if pct <= self.critical_pct:
                tte = self._estimate_time_remaining(history, charging=False)
                tte_str = f" (~{tte} left)" if tte else ""
                alert = self._maybe_alert(
                    "critical_battery",
                    f"🚨 CRITICAL: Battery at {pct:.0f}%{tte_str}! Plug in NOW or your work will be lost!",
                )
                if alert:
                    alerts.append(alert)

            elif pct <= self.low_pct:
                tte = self._estimate_time_remaining(history, charging=False)
                tte_str = f" (~{tte} remaining)" if tte else ""
                alert = self._maybe_alert(
                    "low_battery",
                    f"⚠️ Battery low: {pct:.0f}%{tte_str}. Please plug in your charger.",
                )
                if alert:
                    alerts.append(alert)

        # --- Overcharge protection ---
        if plugged and pct >= self.overcharge_pct:
            alert = self._maybe_alert(
                "overcharge",
                f"🔋 Battery is at {pct:.0f}% and still charging. "
                "Consider unplugging to preserve battery health.",
            )
            if alert:
                alerts.append(alert)

        self.state["last_pct"] = pct
        self._save_state()

        if alerts:
            return "\n".join(alerts)
        return None

    def _estimate_time_remaining(
        self, history: List[Dict], charging: bool
    ) -> Optional[str]:
        """
        Estimate time to empty (or full) based on rate of change over last N samples.
        Returns human-readable string like "1h 23m" or None if insufficient data.
        """
        if len(history) < 3:
            return None
        try:
            oldest = history[0]
            newest = history[-1]
            time_diff = newest["ts"] - oldest["ts"]
            pct_diff = newest["pct"] - oldest["pct"]
            if time_diff <= 0 or pct_diff == 0:
                return None
            rate_per_sec = pct_diff / time_diff  # positive = charging, negative = draining
            if charging and rate_per_sec <= 0:
                return None
            if not charging and rate_per_sec >= 0:
                return None
            current_pct = newest["pct"]
            target_pct = 100.0 if charging else 0.0
            secs_left = abs((target_pct - current_pct) / rate_per_sec)
            if secs_left > 86400:  # > 24h — unreliable
                return None
            hrs = int(secs_left // 3600)
            mins = int((secs_left % 3600) // 60)
            if hrs > 0:
                return f"{hrs}h {mins}m"
            return f"{mins}m"
        except Exception:
            return None

    def _maybe_alert(self, key: str, message: str) -> Optional[str]:
        """Return message if cooldown has elapsed for this key, else None."""
        now = time.time()
        last = self.state["last_alert_time"].get(key, 0)
        if now - last >= self.cooldown_sec:
            self.state["last_alert_time"][key] = now
            return message
        return None

    def get_battery_status(self) -> str:
        """Return readable battery status (callable by WatchdogAgent)."""
        if not HAS_PSUTIL:
            return "psutil not available."
        try:
            batt = psutil.sensors_battery()
            if batt is None:
                return "No battery detected (desktop system)."
            history = self.state.get("pct_history", [])
            tte = self._estimate_time_remaining(history, charging=batt.power_plugged)
            tte_str = f" — {tte} to {'full' if batt.power_plugged else 'empty'}" if tte else ""
            status = "🔌 Charging" if batt.power_plugged else "🔋 Discharging"
            return (
                f"Battery: {batt.percent:.0f}%  {status}{tte_str}"
            )
        except Exception as e:
            return f"Battery check failed: {e}"
