from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Any


SnapshotProvider = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class PcMonitorConfig:
    enabled: bool
    interval_seconds: int
    max_records: int
    context_records: int

    @classmethod
    def from_env(cls) -> "PcMonitorConfig":
        return cls(
            enabled=os.getenv("PC_MONITOR_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
            interval_seconds=max(5, int(os.getenv("PC_MONITOR_INTERVAL_SECONDS", "30"))),
            max_records=max(50, int(os.getenv("PC_MONITOR_MAX_RECORDS", "500"))),
            context_records=max(1, int(os.getenv("PC_MONITOR_CONTEXT_RECORDS", "8"))),
        )


class PcMonitor:
    def __init__(
        self,
        store_dir: Path,
        config: PcMonitorConfig | None = None,
        snapshot_provider: SnapshotProvider | None = None,
    ) -> None:
        self.store_dir = store_dir
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.store_dir / "pc_activity.jsonl"
        self.config = config or PcMonitorConfig.from_env()
        self.snapshot_provider = snapshot_provider or self._windows_snapshot
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.config.enabled or self._thread:
            return
        self.sample_once()
        self._thread = threading.Thread(target=self._loop, name="pc-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def sample_once(self) -> dict[str, Any]:
        try:
            snapshot = self.snapshot_provider()
        except Exception as error:
            snapshot = {"timestamp": datetime.now().isoformat(timespec="seconds"), "error": str(error)}

        snapshot.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
        self._append(snapshot)
        self._trim()
        return snapshot

    def recent_records(self, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records[-(limit or self.config.context_records) :]

    def context_for(self, query: str = "") -> str:
        records = self.recent_records()
        if not records:
            return "No PC activity observed yet."

        lines = []
        for record in records:
            lines.append(format_activity_record(record))
        return "\n".join(line for line in lines if line)

    def _loop(self) -> None:
        while not self._stop.wait(self.config.interval_seconds):
            self.sample_once()

    def _append(self, snapshot: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

    def _trim(self) -> None:
        if not self.log_path.exists():
            return
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= self.config.max_records:
            return
        self.log_path.write_text("\n".join(lines[-self.config.max_records :]) + "\n", encoding="utf-8")

    @staticmethod
    def _windows_snapshot() -> dict[str, Any]:
        script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$activeWindow = ''
try {
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class Win32ActiveWindow {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    public static string GetTitle() {
        var buffer = new StringBuilder(512);
        GetWindowText(GetForegroundWindow(), buffer, buffer.Capacity);
        return buffer.ToString();
    }
}
'@
$activeWindow = [Win32ActiveWindow]::GetTitle()
} catch {}

$os = Get-CimInstance Win32_OperatingSystem
$totalMb = [math]::Round($os.TotalVisibleMemorySize / 1024, 0)
$freeMb = [math]::Round($os.FreePhysicalMemory / 1024, 0)
$usedPercent = if ($totalMb -gt 0) { [math]::Round((($totalMb - $freeMb) / $totalMb) * 100, 1) } else { $null }
$battery = Get-CimInstance Win32_Battery | Select-Object -First 1
$top = Get-Process |
    Sort-Object CPU -Descending |
    Select-Object -First 6 @{Name='name';Expression={$_.ProcessName}}, @{Name='id';Expression={$_.Id}}, @{Name='cpu_seconds';Expression={[math]::Round([double]($_.CPU), 1)}}, @{Name='memory_mb';Expression={[math]::Round($_.WorkingSet64 / 1MB, 1)}}

[ordered]@{
    timestamp = (Get-Date).ToString('o')
    active_window = $activeWindow
    memory_percent = $usedPercent
    memory_used_mb = $totalMb - $freeMb
    memory_total_mb = $totalMb
    battery_percent = if ($battery) { $battery.EstimatedChargeRemaining } else { $null }
    battery_status = if ($battery) { $battery.BatteryStatus } else { $null }
    top_processes = @($top)
} | ConvertTo-Json -Depth 5 -Compress
"""
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip() or "PC monitor command failed"}
        return json.loads(result.stdout)


def format_activity_record(record: dict[str, Any]) -> str:
    if record.get("error"):
        return f"{record.get('timestamp', 'unknown time')}: monitor error: {record['error']}"

    processes = record.get("top_processes") or []
    process_names = []
    for process in processes[:4]:
        if isinstance(process, dict) and process.get("name"):
            process_names.append(str(process["name"]))

    parts = [str(record.get("timestamp") or "unknown time")]
    active = str(record.get("active_window") or "").strip()
    if active:
        parts.append(f"active window: {active}")
    if process_names:
        parts.append(f"top apps: {', '.join(process_names)}")
    if record.get("memory_percent") is not None:
        parts.append(f"memory: {record['memory_percent']}%")
    if record.get("battery_percent") is not None:
        parts.append(f"battery: {record['battery_percent']}%")
    return " | ".join(parts)
