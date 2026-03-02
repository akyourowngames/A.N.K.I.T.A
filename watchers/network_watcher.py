"""
NetworkWatcher — Internet & Network Sentinel for A.N.K.I.T.A.

Monitors internet connectivity, latency, VPN status, and network interface health.
Alerts on drops, spikes, and reconnections.

Config (network_config.json):
    {
        "enabled": true,
        "poll_interval_sec": 30,
        "ping_host": "8.8.8.8",
        "ping_timeout_sec": 3,
        "latency_alert_ms": 300,
        "check_vpn": true,
        "vpn_interface_keywords": ["vpn", "tap", "tun", "wg", "nord", "express"],
        "cooldown_sec": 120
    }
"""
from __future__ import annotations

import socket
import subprocess
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


class NetworkWatcher(BaseWatcher):
    """
    Monitors internet connectivity, latency, and VPN status.

    - Detects internet drops and reconnections
    - Alerts on high latency (configurable threshold)
    - Tracks VPN connect/disconnect events
    - Monitors WiFi signal quality (Windows)
    """

    def __init__(
        self,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        super().__init__(
            name="NetworkWatcher",
            config=config,
            proactive=proactive,
            workspace_root=workspace_root,
        )
        self.poll_interval = float(config.get("poll_interval_sec", 30))
        self.ping_host = config.get("ping_host", "8.8.8.8")
        self.ping_timeout = float(config.get("ping_timeout_sec", 3))
        self.latency_alert_ms = float(config.get("latency_alert_ms", 300))
        self.cooldown_sec = float(config.get("cooldown_sec", 120))
        self.vpn_keywords = [
            k.lower() for k in config.get("vpn_interface_keywords",
                ["vpn", "tap", "tun", "wg", "nord", "express", "proton", "surfshark"])
        ]

        # State
        self.state.setdefault("was_online", True)
        self.state.setdefault("vpn_was_active", False)
        self.state.setdefault("last_alert_time", {})
        self.state.setdefault("offline_since", None)

    # ------------------------------------------------------------------
    # Main check
    # ------------------------------------------------------------------

    def _check(self) -> Optional[str]:
        alerts: List[str] = []

        # --- Internet connectivity + latency ---
        latency_ms = self._measure_latency()
        is_online = latency_ms is not None

        was_online = self.state.get("was_online", True)

        if not is_online and was_online:
            # Just went offline
            self.state["was_online"] = False
            self.state["offline_since"] = time.time()
            alert = self._maybe_alert(
                "offline",
                f"📡 Internet connection lost! (Can't reach {self.ping_host}) — "
                "Checking if it comes back...",
            )
            if alert:
                alerts.append(alert)

        elif is_online and not was_online:
            # Just came back online
            offline_since = self.state.get("offline_since")
            duration = ""
            if offline_since:
                secs = int(time.time() - offline_since)
                duration = f" (was down for {secs}s)"
            self.state["was_online"] = True
            self.state["offline_since"] = None
            alert = self._maybe_alert(
                "reconnected",
                f"✅ Internet restored!{duration} — You're back online.",
            )
            if alert:
                alerts.append(alert)

        elif is_online and latency_ms >= self.latency_alert_ms:
            # High latency
            alert = self._maybe_alert(
                "high_latency",
                f"🐢 High network latency detected: {latency_ms:.0f}ms to {self.ping_host}. "
                "Your connection may be congested.",
            )
            if alert:
                alerts.append(alert)

        # --- VPN status ---
        if self.config.get("check_vpn", True):
            vpn_active = self._detect_vpn()
            vpn_was_active = self.state.get("vpn_was_active", False)

            if vpn_active and not vpn_was_active:
                self.state["vpn_was_active"] = True
                alert = self._maybe_alert("vpn_connect", "🔒 VPN connected — your traffic is now encrypted.")
                if alert:
                    alerts.append(alert)
            elif not vpn_active and vpn_was_active:
                self.state["vpn_was_active"] = False
                alert = self._maybe_alert(
                    "vpn_disconnect",
                    "🔓 VPN disconnected! Your IP is now exposed — reconnect if you need privacy.",
                )
                if alert:
                    alerts.append(alert)

        self._save_state()

        if alerts:
            return "\n".join(alerts)
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _measure_latency(self) -> Optional[float]:
        """
        Measure round-trip latency to ping_host in milliseconds.
        Returns None if unreachable.
        Uses a pure-Python TCP connect to port 53 (DNS) — no admin needed.
        """
        try:
            start = time.perf_counter()
            with socket.create_connection((self.ping_host, 53), timeout=self.ping_timeout):
                pass
            elapsed_ms = (time.perf_counter() - start) * 1000
            return elapsed_ms
        except OSError:
            return None

    def _detect_vpn(self) -> bool:
        """
        Detect if a VPN is active by scanning network interface names.
        Checks psutil (preferred) or netsh (Windows fallback).
        """
        if HAS_PSUTIL:
            try:
                for iface_name in psutil.net_if_stats().keys():
                    if any(kw in iface_name.lower() for kw in self.vpn_keywords):
                        stats = psutil.net_if_stats().get(iface_name)
                        if stats and stats.isup:
                            return True
            except Exception:
                pass

        # Windows fallback: parse netsh output
        try:
            result = subprocess.run(
                ["netsh", "interface", "show", "interface"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.lower().splitlines():
                if any(kw in line for kw in self.vpn_keywords) and "connected" in line:
                    return True
        except Exception:
            pass

        return False

    def _maybe_alert(self, key: str, message: str) -> Optional[str]:
        """Return message if cooldown has elapsed for this key, else None."""
        now = time.time()
        last = self.state["last_alert_time"].get(key, 0)
        if now - last >= self.cooldown_sec:
            self.state["last_alert_time"][key] = now
            return message
        return None

    def get_network_status(self) -> str:
        """Return a readable network status summary (callable by WatchdogAgent)."""
        latency = self._measure_latency()
        vpn = self._detect_vpn()
        lines = ["🌐 Network Status:"]
        if latency is not None:
            lines.append(f"  Internet: ✅ Online  (latency: {latency:.0f}ms to {self.ping_host})")
        else:
            lines.append(f"  Internet: ❌ OFFLINE  (can't reach {self.ping_host})")
        lines.append(f"  VPN: {'🔒 Active' if vpn else '🔓 Not connected'}")

        if HAS_PSUTIL:
            try:
                io = psutil.net_io_counters()
                sent_mb = io.bytes_sent / (1024 * 1024)
                recv_mb = io.bytes_recv / (1024 * 1024)
                lines.append(f"  Data: ↑ {sent_mb:.1f} MB sent  ↓ {recv_mb:.1f} MB received (session total)")
            except Exception:
                pass

        return "\n".join(lines)
