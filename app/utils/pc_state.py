import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("J.A.R.V.I.S")


@dataclass
class PCStateResult:
    ok: bool
    message: str
    snapshot: Optional[dict] = None


class PCStateInspector:
    def inspect(self, query: str = "") -> PCStateResult:
        scope = self._scope(query)
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", self._script(scope)],
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return PCStateResult(False, "PC inspection timed out.")
        except Exception as exc:
            logger.warning("[PC-STATE] Inspection failed to start: %s", exc)
            return PCStateResult(False, "I couldn't inspect the PC state.")

        if completed.returncode != 0:
            logger.warning("[PC-STATE] Inspection failed: %s", (completed.stderr or "")[:300])
            return PCStateResult(False, "I couldn't inspect the PC state.")

        try:
            snapshot = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            logger.warning("[PC-STATE] Bad inspection JSON: %s", exc)
            return PCStateResult(False, "I inspected the PC, but couldn't read the result.")

        return PCStateResult(True, self._format(snapshot), snapshot=snapshot)

    def _scope(self, query: str) -> str:
        q = (query or "").lower()
        if "download" in q or "file" in q:
            return "downloads"
        if "cpu" in q or "processor" in q:
            return "cpu"
        if any(term in q for term in ("slow", "performance", "lag", "hang")):
            return "performance"
        if "ram" in q or "memory" in q:
            return "memory"
        if "port" in q or "server" in q:
            return "ports"
        if "battery" in q:
            return "battery"
        if "disk" in q or "space" in q or "storage" in q:
            return "disks"
        if any(term in q for term in ("window", "apps are open", "open apps", "active apps")):
            return "windows"
        return "full"

    def format_focused(self, query: str, snapshot: dict) -> str:
        if not snapshot:
            return "PC state:\n\n- I couldn't read the PC snapshot this time."

        query_l = (query or "").lower()

        if "cpu" in query_l or "processor" in query_l:
            return self._format_cpu(snapshot)

        if any(term in query_l for term in ("slow", "performance", "lag", "hang")):
            return self._format_performance(snapshot)

        if any(term in query_l for term in ("download", "file")):
            if any(term in query_l for term in ("just", "latest", "last", "most recent")):
                return self._format_latest_download(snapshot)
            return self._format_downloads(snapshot)

        if any(term in query_l for term in ("window", "app", "open")):
            return self._format_windows(snapshot)

        if "port" in query_l or "server" in query_l:
            return self._format_ports(snapshot)

        if "battery" in query_l:
            return self._format_battery(snapshot)

        if "disk" in query_l or "space" in query_l or "storage" in query_l:
            return self._format_disks(snapshot)

        return self._format(snapshot)

    def focused_snapshot(self, query: str, snapshot: dict) -> dict:
        if not snapshot:
            return {}

        query_l = (query or "").lower()
        base = {"captured_at": snapshot.get("captured_at")}

        if "download" in query_l or "file" in query_l:
            downloads = self._as_list(snapshot.get("recent_downloads"))
            if any(term in query_l for term in ("just", "latest", "last", "most recent")):
                return {"captured_at": snapshot.get("captured_at"), "latest_download": downloads[0] if downloads else None}
            return {**base, "latest_download": downloads[0] if downloads else None, "recent_downloads": downloads[:3]}

        if "cpu" in query_l or "processor" in query_l:
            return {
                **base,
                "top_cpu": [
                    {"name": p.get("name"), "pid": p.get("pid"), "cpu_percent": p.get("cpu_percent")}
                    for p in self._as_list(snapshot.get("top_cpu"))[:6]
                ],
            }

        if any(term in query_l for term in ("slow", "performance", "lag", "hang")):
            return {
                **base,
                "memory": snapshot.get("memory"),
                "top_cpu": self._as_list(snapshot.get("top_cpu"))[:5],
                "top_memory": self._as_list(snapshot.get("top_memory"))[:5],
                "disks": self._as_list(snapshot.get("disks"))[:3],
                "slowdown_hints": self._slowdown_hints(snapshot),
            }

        if any(term in query_l for term in ("window", "app", "open")):
            return {**base, "windows": self._as_list(snapshot.get("windows"))[:8]}

        if "port" in query_l or "server" in query_l:
            return {**base, "listening_ports": self._as_list(snapshot.get("listening_ports"))[:12]}

        if "battery" in query_l:
            return {**base, "battery": snapshot.get("battery")}

        if "disk" in query_l or "space" in query_l or "storage" in query_l:
            return {**base, "disks": self._as_list(snapshot.get("disks"))[:5]}

        return {
            **base,
            "memory": snapshot.get("memory"),
            "battery": snapshot.get("battery"),
            "disks": self._as_list(snapshot.get("disks"))[:3],
            "windows": self._as_list(snapshot.get("windows"))[:5],
            "top_cpu": self._as_list(snapshot.get("top_cpu"))[:5],
            "recent_downloads": self._as_list(snapshot.get("recent_downloads"))[:3],
            "listening_ports": self._as_list(snapshot.get("listening_ports"))[:8],
            "slowdown_hints": self._slowdown_hints(snapshot),
        }

    def _format_performance(self, snapshot: dict) -> str:
        lines = ["PC performance right now:", ""]
        memory = snapshot.get("memory") or {}
        if memory:
            lines.append(f"- RAM is {memory.get('used_percent', '?')}% used, with {memory.get('free_gb', '?')} GB free.")

        top_cpu = self._as_list(snapshot.get("top_cpu"))
        if top_cpu:
            lines.append("- Top CPU users:")
            for process in top_cpu[:5]:
                lines.append(
                    f"  - {process.get('name', '?')}: {process.get('cpu_percent', 0)}% CPU, "
                    f"{process.get('memory_mb', 0)} MB RAM"
                )

        hints = self._slowdown_hints(snapshot)
        if hints:
            lines.append("")
            lines.extend(f"- {hint}" for hint in hints)
        return "\n".join(lines)

    def _format_cpu(self, snapshot: dict) -> str:
        top_cpu = self._as_list(snapshot.get("top_cpu"))
        if not top_cpu:
            return "CPU usage:\n\n- No active CPU-heavy processes showed up in this sample."

        lines = ["CPU usage right now:", ""]
        for process in top_cpu[:6]:
            lines.append(f"- {process.get('name', '?')}: {process.get('cpu_percent', 0)}% CPU")
        return "\n".join(lines)

    def _format_downloads(self, snapshot: dict) -> str:
        downloads = self._as_list(snapshot.get("recent_downloads"))
        if not downloads:
            return "Recent downloads:\n\n- I couldn't find any files in Downloads."

        if len(downloads) == 1:
            item = downloads[0]
            return (
                "Latest download:\n\n"
                f"- {item.get('name', '?')} - {item.get('modified', '?')} - {item.get('size_mb', '?')} MB"
            )

        lines = ["Most recent downloads:", ""]
        for item in downloads[:5]:
            lines.append(f"- {item.get('name', '?')} - {item.get('modified', '?')} - {item.get('size_mb', '?')} MB")
        return "\n".join(lines)

    def _format_latest_download(self, snapshot: dict) -> str:
        downloads = self._as_list(snapshot.get("recent_downloads"))
        if not downloads:
            return "Latest download:\n\n- I couldn't find any files in Downloads."

        item = downloads[0]
        return (
            "Latest download:\n\n"
            f"- {item.get('name', '?')} - {item.get('modified', '?')} - {item.get('size_mb', '?')} MB"
        )

    def _format_windows(self, snapshot: dict) -> str:
        windows = self._as_list(snapshot.get("windows"))
        if not windows:
            return "Open windows:\n\n- No titled app windows found."

        lines = ["Open windows I can see:", ""]
        for window in windows[:8]:
            title = window.get("title") or "no title"
            lines.append(f"- {window.get('app', '?')}: {title}")
        return "\n".join(lines)

    def _format_ports(self, snapshot: dict) -> str:
        ports = self._as_list(snapshot.get("listening_ports"))
        if not ports:
            return "Listening ports:\n\n- No listening ports found."

        lines = ["Listening ports:", ""]
        for port in ports[:12]:
            lines.append(f"- {port.get('port', '?')}: {port.get('process', '?')}")
        return "\n".join(lines)

    def _format_battery(self, snapshot: dict) -> str:
        battery = snapshot.get("battery") or {}
        if not battery:
            return "Battery:\n\n- I couldn't read battery state on this device."
        return f"Battery:\n\n- {battery.get('percent', '?')}% ({battery.get('status', 'unknown')})."

    def _format_disks(self, snapshot: dict) -> str:
        disks = self._as_list(snapshot.get("disks"))
        if not disks:
            return "Disk space:\n\n- I couldn't read disk state."

        lines = ["Disk space:", ""]
        for disk in disks[:5]:
            lines.append(
                f"- {disk.get('drive', '?')}: {disk.get('free_gb', '?')} GB free of "
                f"{disk.get('size_gb', '?')} GB ({disk.get('free_percent', '?')}% free)"
            )
        return "\n".join(lines)

    def _format(self, snapshot: dict) -> str:
        lines = ["Here is the grounded PC state I can see right now:"]

        memory = snapshot.get("memory") or {}
        if memory:
            lines.append(
                f"Memory: {memory.get('used_percent', '?')}% used "
                f"({memory.get('free_gb', '?')} GB free of {memory.get('total_gb', '?')} GB)."
            )

        battery = snapshot.get("battery") or {}
        if battery:
            status = battery.get("status") or "unknown"
            lines.append(f"Battery: {battery.get('percent', '?')}% ({status}).")

        disks = self._as_list(snapshot.get("disks"))
        if disks:
            lines.append("Disk: " + "; ".join(
                f"{d.get('drive', '?')} {d.get('free_gb', '?')} GB free of {d.get('size_gb', '?')} GB"
                for d in disks[:3]
            ) + ".")

        windows = self._as_list(snapshot.get("windows"))
        if windows:
            lines.append("Active windows: " + "; ".join(
                f"{w.get('app', '?')} - {w.get('title', '')}".strip(" -")
                for w in windows[:5]
            ) + ".")
        else:
            lines.append("Active windows: no titled app windows found.")

        top_cpu = self._as_list(snapshot.get("top_cpu"))
        if top_cpu:
            lines.append("Top CPU now: " + "; ".join(
                f"{p.get('name', '?')} ({p.get('cpu_percent', 0)}%, {p.get('memory_mb', 0)} MB)"
                for p in top_cpu[:5]
            ) + ".")

        top_memory = self._as_list(snapshot.get("top_memory"))
        if top_memory:
            lines.append("Top memory: " + "; ".join(
                f"{p.get('name', '?')} ({p.get('memory_mb', 0)} MB)"
                for p in top_memory[:5]
            ) + ".")

        downloads = self._as_list(snapshot.get("recent_downloads"))
        if downloads:
            lines.append("Recent downloads: " + "; ".join(
                f"{d.get('name', '?')} ({d.get('modified', '?')}, {d.get('size_mb', '?')} MB)"
                for d in downloads[:5]
            ) + ".")

        ports = self._as_list(snapshot.get("listening_ports"))
        if ports:
            lines.append("Listening ports: " + "; ".join(
                f"{p.get('port', '?')}:{p.get('process', '?')}"
                for p in ports[:12]
            ) + ".")

        hints = self._slowdown_hints(snapshot)
        if hints:
            lines.append("Possible slowdown signals: " + " ".join(hints))

        return "\n".join(lines)

    def _slowdown_hints(self, snapshot: dict) -> list[str]:
        hints = []
        memory = snapshot.get("memory") or {}
        used = self._number(memory.get("used_percent"))
        if used is not None and used >= 85:
            hints.append(f"RAM is high at {used}%.")

        for disk in self._as_list(snapshot.get("disks")):
            free_percent = self._number(disk.get("free_percent"))
            if free_percent is not None and free_percent < 10:
                hints.append(f"{disk.get('drive', 'A drive')} is low on space ({free_percent}% free).")

        top_cpu = self._as_list(snapshot.get("top_cpu"))
        if top_cpu:
            leader = top_cpu[0]
            cpu = self._number(leader.get("cpu_percent"))
            if cpu is not None and cpu >= 35:
                hints.append(f"{leader.get('name', 'A process')} is currently using the most CPU ({cpu}%).")

        return hints

    def _number(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _as_list(self, value: Any) -> list:
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    def _script(self, scope: str) -> str:
        return r"""
$ErrorActionPreference = 'SilentlyContinue'
$scope = '__PC_SCOPE__'
$needCpu = $scope -in @('cpu', 'performance', 'full')
$needTopMemory = $scope -in @('memory', 'performance', 'full')
$needMemory = $scope -in @('memory', 'performance', 'full')
$needWindows = $scope -in @('windows', 'full')
$needDownloads = $scope -in @('downloads', 'full')
$needDisks = $scope -in @('disks', 'performance', 'full')
$needBattery = $scope -in @('battery', 'full')
$needPorts = $scope -in @('ports', 'full')

$topCpu = @()
if ($needCpu) {
$sampleMs = 650
$cpuStart = Get-Process | Where-Object { $null -ne $_.CPU } | Select-Object Id, ProcessName, CPU
Start-Sleep -Milliseconds $sampleMs
$cpuEnd = Get-Process | Where-Object { $null -ne $_.CPU } | Select-Object Id, ProcessName, CPU, WorkingSet64
$startMap = @{}
foreach ($p in $cpuStart) { $startMap[$p.Id] = $p.CPU }
$cores = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
if (-not $cores) { $cores = 1 }
$topCpu = @(foreach ($p in $cpuEnd) {
    if ($startMap.ContainsKey($p.Id)) {
        $delta = [double]$p.CPU - [double]$startMap[$p.Id]
        if ($delta -gt 0) {
            [pscustomobject]@{
                name = $p.ProcessName
                pid = $p.Id
                cpu_percent = [math]::Round(($delta / ($sampleMs / 1000) / $cores) * 100, 1)
                memory_mb = [math]::Round($p.WorkingSet64 / 1MB, 1)
            }
        }
    }
}) | Sort-Object cpu_percent -Descending | Select-Object -First 8
}

$topMemory = @()
if ($needTopMemory) {
$topMemory = Get-Process |
    Sort-Object WorkingSet64 -Descending |
    Select-Object -First 8 @{Name='name';Expression={$_.ProcessName}}, @{Name='pid';Expression={$_.Id}}, @{Name='memory_mb';Expression={[math]::Round($_.WorkingSet64 / 1MB, 1)}}
}

$windows = @()
if ($needWindows) {
$windows = Get-Process |
    Where-Object { $_.MainWindowTitle } |
    Sort-Object ProcessName |
    Select-Object -First 12 @{Name='app';Expression={$_.ProcessName}}, @{Name='pid';Expression={$_.Id}}, @{Name='title';Expression={$_.MainWindowTitle}}
}

$downloadsPath = Join-Path $HOME 'Downloads'
$downloads = @()
if ($needDownloads -and (Test-Path $downloadsPath)) {
    $downloads = Get-ChildItem -Path $downloadsPath -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 8 @{Name='name';Expression={$_.Name}}, @{Name='modified';Expression={$_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')}}, @{Name='size_mb';Expression={[math]::Round($_.Length / 1MB, 2)}}
}

$memory = $null
if ($needMemory) {
$os = Get-CimInstance Win32_OperatingSystem
$totalGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
$freeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$usedPercent = if ($totalGb -gt 0) { [math]::Round((($totalGb - $freeGb) / $totalGb) * 100, 1) } else { 0 }
$memory = [pscustomobject]@{ total_gb = $totalGb; free_gb = $freeGb; used_percent = $usedPercent }
}

$disks = @()
if ($needDisks) {
$disks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
    Select-Object @{Name='drive';Expression={$_.DeviceID}}, @{Name='free_gb';Expression={[math]::Round($_.FreeSpace / 1GB, 1)}}, @{Name='size_gb';Expression={[math]::Round($_.Size / 1GB, 1)}}, @{Name='free_percent';Expression={if ($_.Size) {[math]::Round(($_.FreeSpace / $_.Size) * 100, 1)} else {0}}}
}

$battery = $null
if ($needBattery) {
    $batteryObj = Get-CimInstance Win32_Battery | Select-Object -First 1
    if ($batteryObj) {
    $battery = [pscustomobject]@{
        percent = $batteryObj.EstimatedChargeRemaining
        status = switch ($batteryObj.BatteryStatus) {
            1 { 'discharging' }
            2 { 'plugged in' }
            3 { 'fully charged' }
            default { 'unknown' }
        }
    }
    }
}

$ports = @()
if ($needPorts) {
$ports = Get-NetTCPConnection -State Listen |
    Sort-Object LocalPort |
    Select-Object -First 16 @{Name='port';Expression={$_.LocalPort}}, @{Name='address';Expression={$_.LocalAddress}}, @{Name='process';Expression={(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName}}
}

[pscustomobject]@{
    captured_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    memory = $memory
    battery = $battery
    disks = $disks
    windows = $windows
    top_cpu = $topCpu
    top_memory = $topMemory
    recent_downloads = $downloads
    listening_ports = $ports
} | ConvertTo-Json -Depth 5 -Compress
""".replace("__PC_SCOPE__", scope)
