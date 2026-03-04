"""
Device management operations for ANKITA.
Detect and control connected devices: USB, Bluetooth, audio devices, peripherals.
Uses PowerShell PnP and WMI for device enumeration and control.
"""
import subprocess
import json
from typing import Any, Dict, Optional


def _run_powershell(script: str, timeout: int = 20) -> Dict[str, Any]:
    """Run a PowerShell command and return structured result."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        shell=False,
        check=False,
        timeout=timeout,
    )
    return {
        "exit_code": out.returncode,
        "stdout": (out.stdout or "").strip(),
        "stderr": (out.stderr or "").strip(),
    }


def list_devices(device_class: str = "all") -> Dict[str, Any]:
    """List connected devices, optionally filtered by class.

    Args:
        device_class: Device class filter — all, USB, Bluetooth, Audio, Display,
                     HIDClass, Mouse, Keyboard, Net, DiskDrive
    """
    class_filter = ""
    if device_class.lower() != "all":
        # Map common names to PnP device classes
        class_map = {
            "usb": "USB",
            "bluetooth": "Bluetooth",
            "audio": "AudioEndpoint",
            "display": "Display",
            "hid": "HIDClass",
            "hidclass": "HIDClass",
            "mouse": "Mouse",
            "keyboard": "Keyboard",
            "net": "Net",
            "network": "Net",
            "disk": "DiskDrive",
            "diskdrive": "DiskDrive",
            "camera": "Camera",
            "image": "Image",
        }
        mapped = class_map.get(device_class.lower(), device_class)
        class_filter = f" -Class '{mapped}'"

    script = (
        f"Get-PnpDevice{class_filter} -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Status -eq 'OK' -or $_.Status -eq 'Degraded' } | "
        "Select-Object -First 30 | "
        "ForEach-Object { "
        "  $obj = [ordered]@{"
        "    name = $_.FriendlyName;"
        "    class = $_.Class;"
        "    status = $_.Status;"
        "    manufacturer = $_.Manufacturer;"
        "    instance_id = $_.InstanceId"
        "  }; "
        "  $obj | ConvertTo-Json -Compress"
        "}"
    )

    try:
        res = _run_powershell(script, timeout=15)
        devices = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    devices.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        return {
            "ok": True,
            "filter": device_class,
            "count": len(devices),
            "devices": devices,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_device_info(device_name: str) -> Dict[str, Any]:
    """Get detailed info about a specific device by name (fuzzy match)."""
    safe_name = device_name.replace("'", "''")

    script = (
        f"$dev = Get-PnpDevice -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.FriendlyName -like '*{safe_name}*' }} | "
        "Select-Object -First 1; "
        "if ($dev) { "
        "  $prop = Get-PnpDeviceProperty -InstanceId $dev.InstanceId -ErrorAction SilentlyContinue | "
        "    Where-Object { $_.Data -ne $null -and $_.Data -ne '' } | "
        "    Select-Object -First 20; "
        "  $obj = [ordered]@{"
        "    name = $dev.FriendlyName;"
        "    class = $dev.Class;"
        "    status = $dev.Status;"
        "    manufacturer = $dev.Manufacturer;"
        "    instance_id = $dev.InstanceId;"
        "    driver_version = ($prop | Where-Object { $_.KeyName -like '*DriverVersion*' }).Data;"
        "    driver_date = ($prop | Where-Object { $_.KeyName -like '*DriverDate*' }).Data;"
        "    hardware_ids = ($prop | Where-Object { $_.KeyName -like '*HardwareIds*' }).Data"
        "  }; "
        "  $obj | ConvertTo-Json -Compress"
        "} else { "
        "  Write-Output ('{\"ok\":false,\"error\":\"Device not found: " + safe_name + "\"}') "
        "}"
    )

    try:
        res = _run_powershell(script, timeout=10)
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    parsed = json.loads(line)
                    if "error" in parsed and not parsed.get("ok", True):
                        return parsed
                    return {"ok": True, "device": parsed}
                except json.JSONDecodeError:
                    pass

        return {"ok": False, "error": f"Device not found matching: {device_name}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_audio_devices() -> Dict[str, Any]:
    """List all audio playback and recording devices."""
    script = (
        "Get-PnpDevice -Class AudioEndpoint -ErrorAction SilentlyContinue | "
        "ForEach-Object { "
        "  $obj = [ordered]@{"
        "    name = $_.FriendlyName;"
        "    status = $_.Status;"
        "    instance_id = $_.InstanceId"
        "  }; "
        "  $obj | ConvertTo-Json -Compress"
        "}"
    )

    try:
        res = _run_powershell(script, timeout=10)
        devices = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    devices.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        return {
            "ok": True,
            "count": len(devices),
            "audio_devices": devices,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def switch_audio_device(device_name: str) -> Dict[str, Any]:
    """Switch default audio playback device by name.

    Note: Requires AudioDeviceCmdlets module or nircmd. Falls back to PowerShell.
    """
    safe_name = device_name.replace("'", "''")

    # Try using PowerShell AudioDeviceCmdlets module first
    script = (
        "try { "
        f"  $dev = Get-AudioDevice -List | Where-Object {{ $_.Name -like '*{safe_name}*' -and $_.Type -eq 'Playback' }} | "
        "  Select-Object -First 1; "
        "  if ($dev) { "
        "    Set-AudioDevice -ID $dev.ID | Out-Null; "
        "    Write-Output ('{\"ok\":true,\"switched_to\":\"' + $dev.Name + '\"}') "
        "  } else { "
        "    Write-Output ('{\"ok\":false,\"error\":\"Audio device not found matching: " + safe_name + "\"}') "
        "  } "
        "} catch { "
        # Fallback: use nircmd if available
        "  $nircmd = Get-Command nircmd -ErrorAction SilentlyContinue; "
        "  if ($nircmd) { "
        f"    nircmd setdefaultsounddevice '{safe_name}'; "
        "    Write-Output ('{\"ok\":true,\"switched_to\":\"" + safe_name + "\",\"method\":\"nircmd\"}') "
        "  } else { "
        "    Write-Output ('{\"ok\":false,\"error\":\"AudioDeviceCmdlets not installed. Run: Install-Module AudioDeviceCmdlets -Force\"}') "
        "  } "
        "}"
    )

    try:
        res = _run_powershell(script, timeout=10)
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    pass

        return {"ok": False, "error": "Failed to switch audio device"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_usb_devices() -> Dict[str, Any]:
    """List all connected USB devices with details."""
    script = (
        "Get-PnpDevice -Class USB -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Status -eq 'OK' } | "
        "Select-Object -First 20 | "
        "ForEach-Object { "
        "  $obj = [ordered]@{"
        "    name = $_.FriendlyName;"
        "    status = $_.Status;"
        "    manufacturer = $_.Manufacturer;"
        "    instance_id = $_.InstanceId"
        "  }; "
        "  $obj | ConvertTo-Json -Compress"
        "}"
    )

    try:
        res = _run_powershell(script, timeout=10)
        devices = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    devices.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        return {"ok": True, "count": len(devices), "usb_devices": devices}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_driver_info(device_name: str = "") -> Dict[str, Any]:
    """Get driver information for devices, optionally filtered by name."""
    safe_name = device_name.replace("'", "''") if device_name else ""
    name_filter = f"Where-Object {{ $_.DeviceName -like '*{safe_name}*' }} | " if safe_name else ""

    script = (
        "Get-WmiObject Win32_PnPSignedDriver -ErrorAction SilentlyContinue | "
        f"{name_filter}"
        "Select-Object -First 20 DeviceName, DriverVersion, DriverDate, Manufacturer, DriverProviderName | "
        "ForEach-Object { "
        "  $obj = [ordered]@{"
        "    device = $_.DeviceName;"
        "    version = $_.DriverVersion;"
        "    date = $_.DriverDate;"
        "    manufacturer = $_.Manufacturer;"
        "    provider = $_.DriverProviderName"
        "  }; "
        "  $obj | ConvertTo-Json -Compress"
        "}"
    )

    try:
        res = _run_powershell(script, timeout=15)
        drivers = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    drivers.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        return {"ok": True, "count": len(drivers), "drivers": drivers}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def device_control(action: str, **kwargs) -> Dict[str, Any]:
    """
    Main device control dispatcher.
    Actions: list_devices, get_device_info, list_audio, switch_audio,
             list_usb, get_drivers
    """
    if action == "list_devices":
        return list_devices(
            device_class=kwargs.get("device_class", "all"),
        )
    elif action == "get_device_info":
        name = kwargs.get("device_name", "")
        if not name:
            return {"ok": False, "error": "device_name is required"}
        return get_device_info(device_name=name)
    elif action == "list_audio":
        return list_audio_devices()
    elif action == "switch_audio":
        name = kwargs.get("device_name", "")
        if not name:
            return {"ok": False, "error": "device_name is required"}
        return switch_audio_device(device_name=name)
    elif action == "list_usb":
        return get_usb_devices()
    elif action == "get_drivers":
        return get_driver_info(
            device_name=kwargs.get("device_name", ""),
        )
    else:
        return {
            "ok": False,
            "error": f"Unknown device_control action: {action}. "
                     "Supported: list_devices, get_device_info, list_audio, "
                     "switch_audio, list_usb, get_drivers",
        }
