from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


PLATFORM = platform.system()
_BLOCKED_PROCESS_NAMES = {
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "explorer.exe",
    "system",
}
_SETTINGS_URIS = {
    "sound": "ms-settings:sound",
    "display": "ms-settings:display",
    "bluetooth": "ms-settings:bluetooth",
    "system": "ms-settings:about",
    "storage": "ms-settings:storagesense",
    "apps": "ms-settings:appsfeatures",
    "notifications": "ms-settings:notifications",
    "privacy": "ms-settings:privacy",
    "taskbar": "ms-settings:taskbar",
    "personalization": "ms-settings:personalization",
}


def _looks_secret(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("key", "token", "secret", "password", "credential"))

_WINDOWS_AUDIO_MANAGER_SOURCE = r'''
$source = @"
using System;
using System.Runtime.InteropServices;
namespace Audio {
  [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IAudioEndpointVolume {
    int RegisterControlChangeNotify(IntPtr pNotify);
    int UnregisterControlChangeNotify(IntPtr pNotify);
    int GetChannelCount(out uint pnChannelCount);
    int SetMasterVolumeLevel(float fLevelDB, Guid pguidEventContext);
    int SetMasterVolumeLevelScalar(float fLevel, Guid pguidEventContext);
    int GetMasterVolumeLevel(out float pfLevelDB);
    int GetMasterVolumeLevelScalar(out float pfLevel);
    int SetChannelVolumeLevel(uint nChannel, float fLevelDB, Guid pguidEventContext);
    int SetChannelVolumeLevelScalar(uint nChannel, float fLevel, Guid pguidEventContext);
    int GetChannelVolumeLevel(uint nChannel, out float pfLevelDB);
    int GetChannelVolumeLevelScalar(uint nChannel, out float pfLevel);
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, Guid pguidEventContext);
    int GetMute(out bool pbMute);
    int GetVolumeStepInfo(out uint pnStep, out uint pnStepCount);
    int VolumeStepUp(Guid pguidEventContext);
    int VolumeStepDown(Guid pguidEventContext);
    int QueryHardwareSupport(out uint pdwHardwareSupportMask);
    int GetVolumeRange(out float pflVolumeMindB, out float pflVolumeMaxdB, out float pflVolumeIncrementdB);
  }

  [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceEnumerator {
    int NotImpl1();
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppDevice);
  }

  [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDevice {
    int Activate(ref Guid iid, int dwClsCtx, IntPtr pActivationParams, out IAudioEndpointVolume ppInterface);
  }

  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
  class MMDeviceEnumeratorComObject {}

  public static class AudioManager {
    static IAudioEndpointVolume GetVolume() {
      IMMDeviceEnumerator enumerator = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
      IMMDevice device;
      Marshal.ThrowExceptionForHR(enumerator.GetDefaultAudioEndpoint(0, 1, out device));
      Guid iid = typeof(IAudioEndpointVolume).GUID;
      IAudioEndpointVolume endpoint;
      Marshal.ThrowExceptionForHR(device.Activate(ref iid, 23, IntPtr.Zero, out endpoint));
      return endpoint;
    }

    public static int GetMasterVolume() {
      float level;
      Marshal.ThrowExceptionForHR(GetVolume().GetMasterVolumeLevelScalar(out level));
      return (int)Math.Round(level * 100f);
    }

    public static void SetMasterVolume(int level) {
      float scalar = Math.Max(0, Math.Min(100, level)) / 100f;
      Marshal.ThrowExceptionForHR(GetVolume().SetMasterVolumeLevelScalar(scalar, Guid.Empty));
    }

    public static bool GetMute() {
      bool mute;
      Marshal.ThrowExceptionForHR(GetVolume().GetMute(out mute));
      return mute;
    }

    public static void SetMute(bool mute) {
      Marshal.ThrowExceptionForHR(GetVolume().SetMute(mute, Guid.Empty));
    }

    public static void StepUp(int count) {
      var endpoint = GetVolume();
      for (int i = 0; i < count; i++) {
        Marshal.ThrowExceptionForHR(endpoint.VolumeStepUp(Guid.Empty));
      }
    }

    public static void StepDown(int count) {
      var endpoint = GetVolume();
      for (int i = 0; i < count; i++) {
        Marshal.ThrowExceptionForHR(endpoint.VolumeStepDown(Guid.Empty));
      }
    }
  }
}
"@
Add-Type -TypeDefinition $source -Language CSharp
'''

_WINDOWS_BLUETOOTH_SCRIPT = r'''
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioKind, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioState, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null

function AwaitOp($asyncOp, $resultType) {
    $method = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.IsGenericMethod
    } | Select-Object -First 1).MakeGenericMethod($resultType)
    $task = $method.Invoke($null, @($asyncOp))
    $task.Wait(-1)
    return $task.Result
}

$access = AwaitOp ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus])
if ($access -ne [Windows.Devices.Radios.RadioAccessStatus]::Allowed) {
    throw "Bluetooth radio access denied: $access"
}

$radios = AwaitOp ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$radio = $radios | Where-Object { $_.Kind -eq [Windows.Devices.Radios.RadioKind]::Bluetooth } | Select-Object -First 1
if (-not $radio) {
    throw "No Bluetooth radio found."
}
'''


class SystemTool(Tool):
    name = "system"
    public = True
    safety = "write"
    description = (
        "Control local Windows system features directly: machine status, volume, brightness, Bluetooth, "
        "recycle bin, power/session actions, app launching, opening paths/URLs/settings, process listing "
        "and lookup, terminal launching, disk/network/environment inspection, executable lookup, waiting, "
        "and non-critical process termination. Wi-Fi controls are intentionally excluded."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "launch_app",
                    "open_path",
                    "open_url",
                    "open_settings",
                    "list_processes",
                    "find_process",
                    "terminate_process",
                    "disk_usage",
                    "network_status",
                    "resolve_executable",
                    "open_terminal",
                    "environment",
                    "wait",
                    "volume",
                    "brightness",
                    "bluetooth",
                    "recycle_bin",
                    "power",
                ],
                "description": "System action to perform.",
            },
            "operation": {
                "type": "string",
                "description": (
                    "Sub-action for controls. "
                    "volume: get|set|up|down|mute|unmute|toggle_mute. "
                    "brightness: get|set|up|down. "
                    "bluetooth: get|on|off|toggle|open_settings. "
                    "recycle_bin: open|empty|count. "
                    "power: lock|sleep|hibernate|shutdown|restart|signout."
                ),
            },
            "target": {
                "type": "string",
                "description": "App path, file path, URL, process name, executable name, env var name, or settings page depending on action.",
            },
            "seconds": {
                "type": "number",
                "description": "Seconds to wait for action=wait. Default 1.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum processes returned for action=list_processes. Default 30.",
            },
            "level": {
                "type": "integer",
                "description": "Absolute level 0-100 for set-style actions like volume/brightness.",
            },
            "step": {
                "type": "integer",
                "description": "Relative step size for up/down actions. Default 10.",
            },
            "cwd": {
                "type": "string",
                "description": "Optional working directory for action=open_terminal.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("seconds", 1)
        args.setdefault("max_results", 30)
        args.setdefault("operation", "get")
        args.setdefault("step", 10)
        args.setdefault("cwd", "")
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "")).strip()
        if action == "status":
            return self._status()
        if action == "wait":
            return self._wait(float(args.get("seconds", 1)))
        if action == "launch_app":
            return self._launch_app(str(args.get("target", "")).strip())
        if action == "open_path":
            return self._open_path(str(args.get("target", "")).strip())
        if action == "open_url":
            return self._open_url(str(args.get("target", "")).strip())
        if action == "open_settings":
            return self._open_settings(str(args.get("target", "")).strip())
        if action == "list_processes":
            return self._list_processes(int(args.get("max_results", 30)))
        if action == "find_process":
            return self._find_process(str(args.get("target", "")).strip(), int(args.get("max_results", 30)))
        if action == "terminate_process":
            return self._terminate_process(str(args.get("target", "")).strip())
        if action == "disk_usage":
            return self._disk_usage(str(args.get("target", "")).strip())
        if action == "network_status":
            return self._network_status()
        if action == "resolve_executable":
            return self._resolve_executable(str(args.get("target", "")).strip())
        if action == "open_terminal":
            return self._open_terminal(str(args.get("cwd", "")).strip() or str(args.get("target", "")).strip())
        if action == "environment":
            return self._environment(str(args.get("target", "")).strip())
        if action == "volume":
            return self._volume(str(args.get("operation", "get")).strip(), args)
        if action == "brightness":
            return self._brightness(str(args.get("operation", "get")).strip(), args)
        if action == "bluetooth":
            return self._bluetooth(str(args.get("operation", "get")).strip())
        if action == "recycle_bin":
            return self._recycle_bin(str(args.get("operation", "open")).strip())
        if action == "power":
            return self._power(str(args.get("operation", "")).strip())
        return ToolResult(ok=False, summary=f"Unknown system action: {action}", data={}, error="unknown_action")

    def _wait(self, seconds: float) -> ToolResult:
        bounded = max(0.0, min(float(seconds), 30.0))
        time.sleep(bounded)
        return ToolResult(ok=True, summary=f"Waited {bounded:.1f}s.", data={"seconds": bounded, "action": "wait"})

    def _disk_usage(self, target: str) -> ToolResult:
        roots: list[Path]
        if target:
            roots = [Path(target).expanduser().resolve()]
        elif PLATFORM == "Windows":
            roots = [Path(f"{letter}:\\") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").exists()]
        else:
            roots = [Path("/")]
        disks: list[dict[str, Any]] = []
        for root in roots:
            try:
                usage = shutil.disk_usage(root)
            except Exception:
                continue
            total = int(usage.total)
            free = int(usage.free)
            used = int(usage.used)
            percent_used = round((used / total) * 100, 1) if total else 0.0
            disks.append(
                {
                    "path": str(root),
                    "total_bytes": total,
                    "used_bytes": used,
                    "free_bytes": free,
                    "percent_used": percent_used,
                }
            )
        if not disks:
            return ToolResult(ok=False, summary="No disk usage information available.", data={}, error="not_found")
        summary = "; ".join(f"{item['path']} {item['percent_used']}% used" for item in disks[:4])
        return ToolResult(ok=True, summary=f"Disk usage: {summary}.", data={"action": "disk_usage", "disks": disks})

    def _network_status(self) -> ToolResult:
        payload: dict[str, Any] = {"action": "network_status", "hostname": socket.gethostname()}
        addresses: list[str] = []
        try:
            for family, _, _, _, sockaddr in socket.getaddrinfo(socket.gethostname(), None):
                if family in {socket.AF_INET, socket.AF_INET6} and sockaddr:
                    address = str(sockaddr[0])
                    if address and address not in addresses:
                        addresses.append(address)
        except Exception:
            pass
        payload["addresses"] = addresses[:12]
        try:
            with socket.create_connection(("1.1.1.1", 53), timeout=3):
                payload["internet_reachable"] = True
        except Exception:
            payload["internet_reachable"] = False
        if PLATFORM == "Windows":
            try:
                output = subprocess.check_output(["ipconfig"], text=True, stderr=subprocess.STDOUT, timeout=8)
                payload["ipconfig_excerpt"] = "\n".join(line.rstrip() for line in output.splitlines()[:80])
            except Exception as exc:  # noqa: BLE001
                payload["ipconfig_error"] = str(exc)[:200]
        summary = "Internet reachable." if payload["internet_reachable"] else "Internet connectivity not proven."
        if addresses:
            summary += f" Local address: {addresses[0]}."
        return ToolResult(ok=True, summary=summary, data=payload)

    def _resolve_executable(self, target: str) -> ToolResult:
        if not target:
            return ToolResult(ok=False, summary="System resolve_executable requires a target.", data={}, error="missing_target")
        resolved = shutil.which(target)
        payload: dict[str, Any] = {"action": "resolve_executable", "target": target, "path": resolved or "", "found": bool(resolved)}
        if resolved:
            return ToolResult(ok=True, summary=f"Resolved {target}: {resolved}", data=payload)
        return ToolResult(ok=True, summary=f"Executable not found on PATH: {target}", data=payload)

    def _open_terminal(self, cwd: str) -> ToolResult:
        base = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
        if not base.exists() or not base.is_dir():
            return ToolResult(ok=False, summary=f"Terminal cwd not found: {base}", data={}, error="cwd_not_found")
        try:
            if PLATFORM == "Windows":
                wt = shutil.which("wt.exe") or shutil.which("wt")
                if wt:
                    subprocess.Popen([wt, "-d", str(base)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(
                        ["powershell", "-NoProfile", "-Command", f"Start-Process powershell -ArgumentList '-NoExit','-NoProfile' -WorkingDirectory '{str(base).replace(chr(39), chr(39) * 2)}'"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            elif PLATFORM == "Darwin":
                subprocess.Popen(["open", "-a", "Terminal", str(base)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                terminal = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal") or shutil.which("konsole")
                if not terminal:
                    return ToolResult(ok=False, summary="No terminal emulator found.", data={}, error="missing_terminal")
                subprocess.Popen([terminal], cwd=str(base), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ToolResult(ok=True, summary=f"Opened terminal at {base}", data={"action": "open_terminal", "cwd": str(base)})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Failed to open terminal at {base}", data={}, error=str(exc))

    def _environment(self, target: str) -> ToolResult:
        if target:
            value = os.environ.get(target, "")
            shown = bool(value)
            redacted = _looks_secret(target) and shown
            return ToolResult(
                ok=True,
                summary=f"Environment variable {target} {'is set' if shown else 'is not set'}.",
                data={"action": "environment", "target": target, "value": "[redacted]" if redacted else value, "set": shown, "redacted": redacted},
            )
        keys = sorted(key for key in os.environ if not _looks_secret(key))[:120]
        return ToolResult(ok=True, summary=f"Environment has {len(keys)} visible key(s).", data={"action": "environment", "keys": keys})

    def _launch_app(self, target: str) -> ToolResult:
        if not target:
            return ToolResult(ok=False, summary="System launch_app requires a target.", data={}, error="missing_target")
        try:
            if PLATFORM == "Windows":
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-Command", f'Start-Process -FilePath "{target.replace(chr(34), chr(34) * 2)}"'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif PLATFORM == "Darwin":
                subprocess.Popen(["open", "-a", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen([target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ToolResult(ok=True, summary=f"Launched app: {target}", data={"action": "launch_app", "target": target})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Failed to launch app: {target}", data={}, error=str(exc))

    def _open_url(self, target: str) -> ToolResult:
        if not target:
            return ToolResult(ok=False, summary="System open_url requires a URL target.", data={}, error="missing_target")
        try:
            if PLATFORM == "Windows":
                safe_target = target.replace("'", "''")
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-Command", f"Start-Process '{safe_target}'"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif PLATFORM == "Darwin":
                subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ToolResult(ok=True, summary=f"Opened URL: {target}", data={"action": "open_url", "target": target})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Failed to open URL: {target}", data={}, error=str(exc))

    def _open_path(self, target: str) -> ToolResult:
        if not target:
            return ToolResult(ok=False, summary="System open_path requires a target path.", data={}, error="missing_target")
        path = Path(target).expanduser()
        if not path.exists():
            return ToolResult(ok=False, summary=f"Path not found: {target}", data={}, error="not_found")
        try:
            if PLATFORM == "Windows":
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-Command", f'Start-Process -FilePath "{str(path).replace(chr(34), chr(34) * 2)}"'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif PLATFORM == "Darwin":
                subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ToolResult(ok=True, summary=f"Opened path: {path}", data={"action": "open_path", "target": str(path)})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Failed to open path: {target}", data={}, error=str(exc))

    def _open_settings(self, target: str) -> ToolResult:
        page = target.strip().lower() or "system"
        if page == "wifi":
            return ToolResult(ok=False, summary="Wi-Fi settings are intentionally excluded.", data={}, error="blocked_feature")
        uri = _SETTINGS_URIS.get(page)
        if not uri:
            supported = ", ".join(sorted(_SETTINGS_URIS))
            return ToolResult(ok=False, summary=f"Unknown settings page: {page}. Supported: {supported}", data={}, error="unknown_target")
        if PLATFORM != "Windows":
            return ToolResult(ok=False, summary="Settings deep links are only implemented on Windows.", data={}, error="unsupported_platform")
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", f"Start-Process '{uri}'"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return ToolResult(ok=True, summary=f"Opened settings page: {page}", data={"action": "open_settings", "target": page, "uri": uri})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Failed to open settings page: {page}", data={}, error=str(exc))

    def _list_processes(self, max_results: int) -> ToolResult:
        limit = max(1, min(max_results, 500))
        try:
            if PLATFORM == "Windows":
                output = subprocess.check_output(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "Get-Process | Sort-Object ProcessName | Select-Object ProcessName,Id,MainWindowTitle | ConvertTo-Json -Compress",
                    ],
                    text=True,
                    stderr=subprocess.STDOUT,
                ).strip()
                parsed = json.loads(output) if output else []
                if isinstance(parsed, dict):
                    parsed = [parsed]
                processes = [
                    {
                        "name": str(item.get("ProcessName", "")),
                        "pid": int(item.get("Id", 0)),
                        "window": str(item.get("MainWindowTitle", "")).strip(),
                    }
                    for item in parsed[:limit]
                ]
            else:
                output = subprocess.check_output(["ps", "-eo", "pid=,comm="], text=True, stderr=subprocess.STDOUT)
                processes = []
                for line in output.splitlines()[:limit]:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = stripped.split(None, 1)
                    if len(parts) != 2:
                        continue
                    processes.append({"pid": int(parts[0]), "name": parts[1], "window": ""})
            return ToolResult(
                ok=True,
                summary=f"Listed {len(processes)} process(es).",
                data={"action": "list_processes", "processes": processes, "count": len(processes)},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Failed to list processes.", data={}, error=str(exc))

    def _find_process(self, target: str, max_results: int) -> ToolResult:
        if not target:
            return ToolResult(ok=False, summary="System find_process requires a target.", data={}, error="missing_target")
        listed = self._list_processes(max(max_results, 120))
        if not listed.ok:
            return listed
        needle = target.lower()
        matches = [
            item
            for item in listed.data.get("processes", [])
            if needle in str(item.get("name", "")).lower() or needle in str(item.get("window", "")).lower()
        ][: max(1, min(max_results, 100))]
        summary = f"Found {len(matches)} process match(es) for {target}." if matches else f"No process match found for {target}."
        return ToolResult(
            ok=True,
            summary=summary,
            data={
                "action": "find_process",
                "target": target,
                "running": bool(matches),
                "matches": matches,
                "count": len(matches),
            },
        )

    def _terminate_process(self, target: str) -> ToolResult:
        if not target:
            return ToolResult(ok=False, summary="System terminate_process requires a process name.", data={}, error="missing_target")
        lowered = target.lower()
        if lowered in _BLOCKED_PROCESS_NAMES:
            return ToolResult(ok=False, summary=f"Blocked process termination: {target}", data={}, error="blocked_process")
        try:
            if PLATFORM == "Windows":
                if target.isdigit():
                    subprocess.check_output(["taskkill", "/PID", target, "/F"], text=True, stderr=subprocess.STDOUT)
                    return ToolResult(ok=True, summary=f"Terminated process id: {target}", data={"action": "terminate_process", "target": target})
                subprocess.check_output(
                    ["taskkill", "/IM", target, "/F"],
                    text=True,
                    stderr=subprocess.STDOUT,
                )
            else:
                if target.isdigit():
                    subprocess.check_output(["kill", target], text=True, stderr=subprocess.STDOUT)
                    return ToolResult(ok=True, summary=f"Terminated process id: {target}", data={"action": "terminate_process", "target": target})
                subprocess.check_output(["pkill", "-f", target], text=True, stderr=subprocess.STDOUT)
            return ToolResult(ok=True, summary=f"Terminated process: {target}", data={"action": "terminate_process", "target": target})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Failed to terminate process: {target}", data={}, error=str(exc))

    def _status(self) -> ToolResult:
        payload: dict[str, Any] = {"action": "status", "platform": PLATFORM}
        warnings: list[str] = []

        machine = self._machine_status()
        if machine.ok:
            payload.update(machine.data)
        elif machine.error:
            warnings.append(machine.error)

        volume = self._volume("get", {})
        if volume.ok:
            payload["volume_level"] = volume.data.get("level")
            payload["volume_muted"] = volume.data.get("muted")
        elif volume.error:
            warnings.append(volume.error)

        brightness = self._brightness("get", {})
        if brightness.ok:
            payload["brightness_level"] = brightness.data.get("level")
        elif brightness.error:
            warnings.append(brightness.error)

        bluetooth = self._bluetooth("get")
        if bluetooth.ok:
            payload["bluetooth_state"] = bluetooth.data.get("state")
            payload["bluetooth_name"] = bluetooth.data.get("name")
        elif bluetooth.error:
            warnings.append(bluetooth.error)

        payload["warnings"] = warnings
        return ToolResult(ok=True, summary=self._status_summary(payload), data=payload)

    def _volume(self, operation: str, args: dict[str, Any]) -> ToolResult:
        if PLATFORM != "Windows":
            return ToolResult(ok=False, summary="Volume control is only implemented on Windows.", data={}, error="unsupported_platform")
        level = self._bounded_percent(args.get("level"))
        step = max(1, min(int(args.get("step", 10)), 100))
        script = _WINDOWS_AUDIO_MANAGER_SOURCE
        script += "$beforeLevel = [Audio.AudioManager]::GetMasterVolume()\n"
        script += "$beforeMuted = [Audio.AudioManager]::GetMute()\n"
        if operation == "get":
            script += self._windows_volume_json(operation)
        elif operation == "set":
            if level is None:
                return ToolResult(ok=False, summary="Volume set requires a level from 0 to 100.", data={}, error="missing_level")
            script += f"[Audio.AudioManager]::SetMasterVolume({level})\n"
            script += self._windows_volume_json(operation)
        elif operation == "up":
            script += f"[Audio.AudioManager]::StepUp({step})\n"
            script += self._windows_volume_json(operation)
        elif operation == "down":
            script += f"[Audio.AudioManager]::StepDown({step})\n"
            script += self._windows_volume_json(operation)
        elif operation == "mute":
            script += "[Audio.AudioManager]::SetMute($true)\n"
            script += self._windows_volume_json(operation)
        elif operation == "unmute":
            script += "[Audio.AudioManager]::SetMute($false)\n"
            script += self._windows_volume_json(operation)
        elif operation == "toggle_mute":
            script += "$currentMute = [Audio.AudioManager]::GetMute()\n"
            script += "[Audio.AudioManager]::SetMute(-not $currentMute)\n"
            script += self._windows_volume_json(operation)
        else:
            return ToolResult(ok=False, summary=f"Unknown volume operation: {operation}", data={}, error="unknown_operation")
        return self._run_windows_json(script, "volume", operation)

    def _brightness(self, operation: str, args: dict[str, Any]) -> ToolResult:
        if PLATFORM != "Windows":
            return ToolResult(ok=False, summary="Brightness control is only implemented on Windows.", data={}, error="unsupported_platform")
        level = self._bounded_percent(args.get("level"))
        step = max(1, min(int(args.get("step", 10)), 100))
        if operation not in {"get", "set", "up", "down"}:
            return ToolResult(ok=False, summary=f"Unknown brightness operation: {operation}", data={}, error="unknown_operation")
        if operation == "set" and level is None:
            return ToolResult(ok=False, summary="Brightness set requires a level from 0 to 100.", data={}, error="missing_level")
        target_expr = {
            "get": "$current",
            "set": str(level),
            "up": f"[Math]::Min(100, $current + {step})",
            "down": f"[Math]::Max(0, $current - {step})",
        }[operation]
        script = f"""
$monitor = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1
$methods = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Select-Object -First 1
if (-not $monitor -or -not $methods) {{
    throw "Brightness control is not available on this device."
}}
$before = [int]$monitor.CurrentBrightness
$current = $before
$target = [int]({target_expr})
if ('{operation}' -ne 'get') {{
    $null = Invoke-CimMethod -InputObject $methods -MethodName WmiSetBrightness -Arguments @{{ Timeout = 1; Brightness = [byte]$target }} -ErrorAction Stop
    Start-Sleep -Milliseconds 150
}}
$updated = [int](Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1).CurrentBrightness
[pscustomobject]@{{ action = 'brightness'; operation = '{operation}'; level = $updated; before = $before }} | ConvertTo-Json -Compress
"""
        result = self._run_windows_json(script, "brightness", operation)
        if result.ok:
            return result
        current = self._brightness_get_current_level()
        if current is not None and operation in {"set", "up", "down"}:
            summary = self._describe_level_change("Brightness", operation, current, current)
            return ToolResult(
                ok=True,
                summary=summary,
                data={"action": "brightness", "operation": operation, "level": current, "before": current, "fallback": True},
            )
        return result

    def _bluetooth(self, operation: str) -> ToolResult:
        if PLATFORM != "Windows":
            return ToolResult(ok=False, summary="Bluetooth control is only implemented on Windows.", data={}, error="unsupported_platform")
        if operation == "open_settings":
            return self._open_settings("bluetooth")
        if operation not in {"get", "on", "off", "toggle"}:
            return ToolResult(ok=False, summary=f"Unknown bluetooth operation: {operation}", data={}, error="unknown_operation")
        state_logic = ""
        if operation == "on":
            state_logic = "$result = AwaitOp ($radio.SetStateAsync([Windows.Devices.Radios.RadioState]::On)) ([Windows.Devices.Radios.RadioAccessStatus])"
        elif operation == "off":
            state_logic = "$result = AwaitOp ($radio.SetStateAsync([Windows.Devices.Radios.RadioState]::Off)) ([Windows.Devices.Radios.RadioAccessStatus])"
        elif operation == "toggle":
            state_logic = """
$desired = if ($radio.State -eq [Windows.Devices.Radios.RadioState]::On) {
    [Windows.Devices.Radios.RadioState]::Off
} else {
    [Windows.Devices.Radios.RadioState]::On
}
$result = AwaitOp ($radio.SetStateAsync($desired)) ([Windows.Devices.Radios.RadioAccessStatus])
"""
        script = _WINDOWS_BLUETOOTH_SCRIPT
        if state_logic:
            script += state_logic + "\n"
            script += "if ($result -ne [Windows.Devices.Radios.RadioAccessStatus]::Allowed) { throw \"Bluetooth state change denied: $result\" }\n"
            script += "$radio = (AwaitOp ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]]) | Where-Object { $_.Kind -eq [Windows.Devices.Radios.RadioKind]::Bluetooth } | Select-Object -First 1)\n"
        script += f"[pscustomobject]@{{ action = 'bluetooth'; operation = '{operation}'; state = [string]$radio.State; name = [string]$radio.Name }} | ConvertTo-Json -Compress\n"
        return self._run_windows_json(script, "bluetooth", operation)

    def _recycle_bin(self, operation: str) -> ToolResult:
        if PLATFORM != "Windows":
            return ToolResult(ok=False, summary="Recycle bin control is only implemented on Windows.", data={}, error="unsupported_platform")
        if operation == "open":
            try:
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-Command", "Start-Process explorer.exe 'shell:RecycleBinFolder'"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return ToolResult(ok=True, summary="Opened recycle bin.", data={"action": "recycle_bin", "operation": "open"})
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, summary="Failed to open recycle bin.", data={}, error=str(exc))
        if operation == "empty":
            script = """
Clear-RecycleBin -Force -Confirm:$false -ErrorAction Stop
[pscustomobject]@{ action = 'recycle_bin'; operation = 'empty'; emptied = $true } | ConvertTo-Json -Compress
"""
            return self._run_windows_json(script, "recycle_bin", operation)
        if operation == "count":
            script = """
$shell = New-Object -ComObject Shell.Application
$folder = $shell.Namespace(10)
$count = if ($folder) { @($folder.Items()).Count } else { 0 }
[pscustomobject]@{ action = 'recycle_bin'; operation = 'count'; count = [int]$count } | ConvertTo-Json -Compress
"""
            return self._run_windows_json(script, "recycle_bin", operation)
        return ToolResult(ok=False, summary=f"Unknown recycle_bin operation: {operation}", data={}, error="unknown_operation")

    def _power(self, operation: str) -> ToolResult:
        if PLATFORM != "Windows":
            return ToolResult(ok=False, summary="Power control is only implemented on Windows.", data={}, error="unsupported_platform")
        commands: dict[str, list[str]] = {
            "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
            "hibernate": ["shutdown", "/h"],
            "shutdown": ["shutdown", "/s", "/t", "0"],
            "restart": ["shutdown", "/r", "/t", "0"],
            "signout": ["shutdown", "/l"],
        }
        if operation == "sleep":
            try:
                subprocess.Popen(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return ToolResult(ok=True, summary="Requested system sleep.", data={"action": "power", "operation": "sleep"})
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, summary="Failed to request sleep.", data={}, error=str(exc))
        command = commands.get(operation)
        if not command:
            return ToolResult(ok=False, summary=f"Unknown power operation: {operation}", data={}, error="unknown_operation")
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ToolResult(ok=True, summary=f"Requested power action: {operation}", data={"action": "power", "operation": operation})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Failed power action: {operation}", data={}, error=str(exc))

    def _run_windows_json(self, script: str, action: str, operation: str) -> ToolResult:
        try:
            output = subprocess.check_output(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                text=True,
                stderr=subprocess.STDOUT,
            ).strip()
            payload = self._parse_windows_json_output(output) if output else {}
            if not isinstance(payload, dict):
                payload = {"value": payload}
            payload.setdefault("action", action)
            payload.setdefault("operation", operation)
            return ToolResult(ok=True, summary=self._summary_from_payload(payload), data=payload)
        except subprocess.CalledProcessError as exc:
            details = (exc.output or str(exc)).strip()
            return ToolResult(ok=False, summary=f"Failed {action} {operation}.", data={}, error=details[:500])
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Failed {action} {operation}.", data={}, error=str(exc))

    @staticmethod
    def _windows_volume_json(operation: str) -> str:
        return (
            f"[pscustomobject]@{{ action = 'volume'; operation = '{operation}'; before = $beforeLevel; before_muted = $beforeMuted; "
            "level = [Audio.AudioManager]::GetMasterVolume(); muted = [Audio.AudioManager]::GetMute() } | ConvertTo-Json -Compress\n"
        )

    @staticmethod
    def _bounded_percent(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return max(0, min(int(value), 100))

    @staticmethod
    def _summary_from_payload(payload: dict[str, Any]) -> str:
        action = str(payload.get("action", "")).strip()
        if action == "volume":
            return SystemTool._describe_volume_change(payload)
        if action == "brightness":
            before = SystemTool._as_int(payload.get("before"))
            after = SystemTool._as_int(payload.get("level"))
            return SystemTool._describe_level_change("Brightness", str(payload.get("operation", "get")).strip(), before, after)
        if action == "bluetooth":
            state = str(payload.get("state", "unknown")).lower()
            return f"Bluetooth is {state}."
        if action == "status":
            return SystemTool._status_summary(payload)
        if action == "recycle_bin":
            operation = str(payload.get("operation", "")).strip()
            if operation == "count":
                return f"Recycle bin has {payload.get('count', 0)} item(s)."
            if operation == "empty":
                return "Recycle bin emptied."
        if action == "find_process":
            return str(payload.get("summary", "Process lookup complete.")).strip()
        return str(payload.get("summary", f"{action} action complete.")).strip()

    def render(self, data: dict[str, Any]) -> str:
        action = str(data.get("action", "")).strip()
        if action == "status":
            lines = [self._status_summary(data)]
            if data.get("battery_present"):
                lines.append(
                    f"Battery: {data.get('battery_percent', '?')}% | AC={data.get('on_ac_power', False)}"
                )
            if data.get("volume_level") is not None:
                lines.append(f"Volume: {data.get('volume_level', '?')}% | muted={data.get('volume_muted', False)}")
            if data.get("brightness_level") is not None:
                lines.append(f"Brightness: {data.get('brightness_level', '?')}%")
            if data.get("bluetooth_state"):
                lines.append(f"Bluetooth: {data.get('bluetooth_state')} ({data.get('bluetooth_name', '')})".strip())
            if data.get("uptime_minutes") is not None:
                lines.append(f"Uptime: {data.get('uptime_minutes')} minute(s)")
            if data.get("process_count") is not None:
                lines.append(f"Processes: {data.get('process_count')}")
            warnings = data.get("warnings", [])
            if isinstance(warnings, list) and warnings:
                lines.append("Warnings: " + " | ".join(str(item)[:120] for item in warnings[:3]))
            return "\n".join(lines)
        if action == "list_processes":
            processes = data.get("processes", [])
            lines = [f"Processes ({len(processes)}):"]
            for item in processes[:20]:
                suffix = f" - {item.get('window', '')}" if item.get("window") else ""
                lines.append(f"  {item.get('name', '')} [{item.get('pid', '')}]{suffix}")
            return "\n".join(lines)
        if action == "find_process":
            matches = data.get("matches", [])
            if not matches:
                return f"No process match found for {data.get('target', '')}".strip()
            lines = [f"Process matches for {data.get('target', '')} ({len(matches)}):".strip()]
            for item in matches[:15]:
                suffix = f" - {item.get('window', '')}" if item.get("window") else ""
                lines.append(f"  {item.get('name', '')} [{item.get('pid', '')}]{suffix}")
            return "\n".join(lines)
        if action == "volume":
            return f"Volume: {data.get('level', '?')}% | muted={data.get('muted', False)}"
        if action == "brightness":
            return f"Brightness: {data.get('level', '?')}%"
        if action == "bluetooth":
            return f"Bluetooth: {data.get('state', 'unknown')} ({data.get('name', '')})".strip()
        if action == "recycle_bin" and data.get("operation") == "count":
            return f"Recycle bin items: {data.get('count', 0)}"
        if action == "disk_usage":
            disks = data.get("disks", [])
            lines = ["Disk usage:"]
            for item in disks[:8] if isinstance(disks, list) else []:
                lines.append(f"  {item.get('path', '')}: {item.get('percent_used', '?')}% used, {item.get('free_bytes', 0)} bytes free")
            return "\n".join(lines)
        if action == "network_status":
            addresses = data.get("addresses", [])
            reachable = data.get("internet_reachable", False)
            return f"Network: internet_reachable={reachable}, addresses={', '.join(addresses[:4]) if isinstance(addresses, list) else ''}"
        if action == "resolve_executable":
            return data.get("path") or f"Executable not found: {data.get('target', '')}"
        if action == "open_terminal":
            return f"Opened terminal at {data.get('cwd', '')}"
        if action == "environment":
            if data.get("target"):
                return f"{data.get('target')}={'[redacted]' if data.get('redacted') else data.get('value', '')}"
            keys = data.get("keys", [])
            return "Environment keys: " + ", ".join(str(item) for item in keys[:40]) if isinstance(keys, list) else "Environment inspected."
        return data.get("summary", "System action complete.")

    @staticmethod
    def _parse_windows_json_output(output: str) -> Any:
        cleaned = output.strip()
        if not cleaned:
            return {}
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            for line in reversed([line.strip() for line in cleaned.splitlines() if line.strip()]):
                if line.startswith("{") or line.startswith("["):
                    return json.loads(line)
            raise

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _describe_level_change(label: str, operation: str, before: int | None, after: int | None) -> str:
        if after is None:
            return f"{label} updated."
        if operation == "get":
            return f"{label} is {after}%."
        if before is None:
            return f"{label} set to {after}%."
        if operation == "up":
            if after > before:
                return f"{label} increased from {before}% to {after}%."
            if after == before:
                return f"{label} stayed at {after}%."
            return f"{label} changed to {after}%."
        if operation == "down":
            if after < before:
                return f"{label} decreased from {before}% to {after}%."
            if after == before:
                return f"{label} stayed at {after}%."
            return f"{label} changed to {after}%."
        if operation == "set":
            if after == before:
                return f"{label} stayed at {after}%."
            return f"{label} changed from {before}% to {after}%."
        return f"{label} set to {after}%."

    @staticmethod
    def _describe_volume_change(payload: dict[str, Any]) -> str:
        operation = str(payload.get("operation", "get")).strip()
        before = SystemTool._as_int(payload.get("before"))
        after = SystemTool._as_int(payload.get("level"))
        muted_before = bool(payload.get("before_muted", False))
        muted_after = bool(payload.get("muted", False))
        if operation in {"get", "set", "up", "down"}:
            return SystemTool._describe_level_change("Volume", operation, before, after)
        if operation == "mute":
            return "Volume muted." if muted_after else "Volume mute request did not change state."
        if operation == "unmute":
            return "Volume unmuted." if not muted_after else "Volume unmute request did not change state."
        if operation == "toggle_mute":
            if muted_after != muted_before:
                return "Volume muted." if muted_after else "Volume unmuted."
            return "Volume mute state did not change."
        return f"Volume is {after}%."

    def _brightness_get_current_level(self) -> int | None:
        script = """
$monitor = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1
if (-not $monitor) { throw "Brightness control is not available on this device." }
[pscustomobject]@{ action = 'brightness'; operation = 'get'; level = [int]$monitor.CurrentBrightness } | ConvertTo-Json -Compress
"""
        try:
            result = self._run_windows_json(script, "brightness", "get")
        except Exception:
            return None
        if not result.ok:
            return None
        return self._as_int(result.data.get("level"))

    def _machine_status(self) -> ToolResult:
        if PLATFORM != "Windows":
            return ToolResult(ok=True, summary=f"Platform: {PLATFORM}", data={"platform": PLATFORM})
        script = """
$os = Get-CimInstance Win32_OperatingSystem
$boot = $os.LastBootUpTime
$uptime = if ($boot) { New-TimeSpan -Start $boot -End (Get-Date) } else { $null }
$battery = Get-CimInstance Win32_Battery | Select-Object -First 1
$batteryPresent = [bool]$battery
$batteryPercent = if ($battery) { [int]$battery.EstimatedChargeRemaining } else { $null }
$onAc = if ($battery) { @('2','6','7','8','9') -contains [string]$battery.BatteryStatus } else { $null }
$processCount = (Get-Process | Measure-Object).Count
[pscustomobject]@{
    action = 'status'
    platform = 'Windows'
    battery_present = $batteryPresent
    battery_percent = $batteryPercent
    on_ac_power = $onAc
    process_count = [int]$processCount
    uptime_minutes = if ($uptime) { [int][Math]::Round($uptime.TotalMinutes) } else { $null }
} | ConvertTo-Json -Compress
"""
        return self._run_windows_json(script, "status", "snapshot")

    @staticmethod
    def _status_summary(payload: dict[str, Any]) -> str:
        parts = [f"PC status on {payload.get('platform', PLATFORM)}"]
        battery_present = bool(payload.get("battery_present"))
        battery_percent = payload.get("battery_percent")
        on_ac_power = payload.get("on_ac_power")
        if battery_present and battery_percent is not None:
            power = "AC" if on_ac_power else "battery"
            parts.append(f"battery {battery_percent}% ({power})")
        volume_level = payload.get("volume_level")
        if volume_level is not None:
            muted = bool(payload.get("volume_muted", False))
            parts.append(f"volume {volume_level}%{' muted' if muted else ''}")
        brightness_level = payload.get("brightness_level")
        if brightness_level is not None:
            parts.append(f"brightness {brightness_level}%")
        bluetooth_state = str(payload.get("bluetooth_state", "")).strip()
        if bluetooth_state:
            parts.append(f"bluetooth {bluetooth_state.lower()}")
        process_count = payload.get("process_count")
        if process_count is not None:
            parts.append(f"{process_count} process(es)")
        return ", ".join(parts) + "."


def register_system_tools(registry: ToolRegistry) -> None:
    registry.register(SystemTool())
