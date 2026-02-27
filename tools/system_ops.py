import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional


def _run_powershell(script: str) -> Dict[str, Any]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        shell=False,
        check=False,
        timeout=15,
    )
    return {
        "exit_code": out.returncode,
        "stdout": (out.stdout or "").strip(),
        "stderr": (out.stderr or "").strip(),
    }


def _ensure_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("system_control is currently supported on Windows only")


def _safe_out_path(workspace_root: Optional[Path], raw_path: str) -> Path:
    base = workspace_root.resolve() if workspace_root is not None else Path.cwd().resolve()
    value = str(raw_path or "").strip().strip("\"'")
    target = (base / value).resolve() if value else base
    target.parent.mkdir(parents=True, exist_ok=True)
    if workspace_root is not None:
        try:
            target.relative_to(base)
        except ValueError as err:
            raise ValueError(f"path escapes workspace: {raw_path}") from err
    return target


def system_control(
    action: str,
    amount: int = 1,
    path: Optional[str] = None,
    workspace_root: Optional[Path] = None,
) -> Dict[str, Any]:
    _ensure_windows()
    op = str(action or "").strip().lower()
    n = max(1, min(int(amount), 50))

    # keybd_event wrapper for media/system keys
    header = (
        "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
        "public class K { [DllImport(\"user32.dll\")] public static extern void keybd_event(byte bVk, byte bScan, int dwFlags, int dwExtraInfo);}'; "
        "function Press([byte]$vk){ [K]::keybd_event($vk,0,0,0); Start-Sleep -Milliseconds 20; [K]::keybd_event($vk,0,2,0) }; "
    )

    if op == "volume_up":
        script = header + f"for($i=0;$i -lt {n};$i++){{ Press 0xAF }}; Write-Output 'ok'"
    elif op == "volume_down":
        script = header + f"for($i=0;$i -lt {n};$i++){{ Press 0xAE }}; Write-Output 'ok'"
    elif op in {"mute_toggle", "mute", "unmute"}:
        script = header + "Press 0xAD; Write-Output 'ok'"
    elif op == "show_desktop":
        script = (
            header
            + "[K]::keybd_event(0x5B,0,0,0); [K]::keybd_event(0x44,0,0,0); "
            + "[K]::keybd_event(0x44,0,2,0); [K]::keybd_event(0x5B,0,2,0); Write-Output 'ok'"
        )
    elif op == "media_play_pause":
        script = header + "Press 0xB3; Write-Output 'ok'"
    elif op == "media_next":
        script = header + "Press 0xB0; Write-Output 'ok'"
    elif op == "media_prev":
        script = header + "Press 0xB1; Write-Output 'ok'"
    elif op == "lock_screen":
        script = "rundll32.exe user32.dll,LockWorkStation; Write-Output 'ok'"
    elif op == "window_minimize_all":
        script = (
            header
            + "[K]::keybd_event(0x5B,0,0,0); [K]::keybd_event(0x4D,0,0,0); "
            + "[K]::keybd_event(0x4D,0,2,0); [K]::keybd_event(0x5B,0,2,0); Write-Output 'ok'"
        )
    elif op == "window_restore_all":
        script = (
            header
            + "[K]::keybd_event(0x5B,0,0,0); [K]::keybd_event(0x10,0,0,0); [K]::keybd_event(0x4D,0,0,0); "
            + "[K]::keybd_event(0x4D,0,2,0); [K]::keybd_event(0x10,0,2,0); [K]::keybd_event(0x5B,0,2,0); Write-Output 'ok'"
        )
    elif op in {"brightness_up", "brightness_down", "brightness_set"}:
        if op == "brightness_set":
            target_brightness = max(1, min(int(amount), 100))
            expr = f"{target_brightness}"
        else:
            delta = n if op == "brightness_up" else -n
            expr = (
                "$b=Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness | Select-Object -First 1; "
                f"[Math]::Max(1,[Math]::Min(100,([int]$b.CurrentBrightness + ({delta}))))"
            )
        script = (
            "$target=[int]("
            + expr
            + "); "
            + "$m=Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods | Select-Object -First 1; "
            + "$m.WmiSetBrightness(1,$target) | Out-Null; "
            + "Write-Output (\"brightness=\" + $target)"
        )
    elif op in {"wifi_on", "wifi_off"}:
        admin = "ENABLED" if op == "wifi_on" else "DISABLED"
        state_label = "enabled" if op == "wifi_on" else "disabled"
        script = (
            "$target=(Get-NetAdapter -ErrorAction SilentlyContinue | "
            r"Where-Object { $_.Name -match '\bwi-?fi\b|\bwlan\b' -or $_.InterfaceDescription -match '\bwireless\b|\bwi-?fi\b|\bwlan\b' } | "
            "Select-Object -First 1).Name; "
            "if(-not $target){$target='Wi-Fi'}; "
            f"netsh interface set interface name=\"$target\" admin={admin}; "
            "if($LASTEXITCODE -ne 0){ throw 'failed to toggle wifi adapter' }; "
            f"Write-Output ('wifi={state_label} adapter=' + $target)"
        )
    elif op in {"bluetooth_on", "bluetooth_off"}:
        cmd = "Enable-PnpDevice" if op == "bluetooth_on" else "Disable-PnpDevice"
        bt_state = op.split("_", 1)[1]  # "on" or "off" — extracted before the f-string
        script = (
            "$devs=Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue; "
            "if(-not $devs){ throw 'no bluetooth adapter found' }; "
            f"$devs | ForEach-Object {{ {cmd} -InstanceId $_.InstanceId -Confirm:$false -ErrorAction Stop }}; "
            f"Write-Output 'bluetooth={bt_state}'"
        )
    elif op == "screenshot":
        stamp = int(time.time())
        default_name = f"screenshots/screenshot-{stamp}.png"
        out_path = _safe_out_path(workspace_root, path or default_name)
        escaped = str(out_path).replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            "$bounds=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$bmp=New-Object System.Drawing.Bitmap $bounds.Width,$bounds.Height; "
            "$g=[System.Drawing.Graphics]::FromImage($bmp); "
            "$g.CopyFromScreen($bounds.Location,[System.Drawing.Point]::Empty,$bounds.Size); "
            f"$bmp.Save('{escaped}',[System.Drawing.Imaging.ImageFormat]::Png); "
            "$g.Dispose(); $bmp.Dispose(); "
            f"Write-Output '{escaped}'"
        )
    elif op == "open_url":
        # Open a URL in the default browser
        url = str(path or "").strip().strip("\"'")
        if not url:
            raise ValueError("open_url requires a url — pass it via the 'path' parameter")
        if not url.startswith(("http://", "https://", "ftp://")):
            url = "https://" + url
        escaped_url = url.replace("'", "''")
        script = f"Start-Process '{escaped_url}'; Write-Output 'opened: {escaped_url}'"
    elif op == "sleep_display":
        # Turn off monitor without locking — sends SC_MONITORPOWER=2
        script = (
            "Add-Type -TypeDefinition '"
            "using System; using System.Runtime.InteropServices; "
            "public class Disp { "
            "[DllImport(\"user32.dll\")] public static extern IntPtr SendMessage("
            "IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam); }'; "
            "[Disp]::SendMessage([IntPtr]-1, 0x0112, [IntPtr]0xF170, [IntPtr]2) | Out-Null; "
            "Write-Output 'display_sleep=ok'"
        )
    elif op == "empty_recycle_bin":
        script = "Clear-RecycleBin -Force -ErrorAction SilentlyContinue; Write-Output 'recycle_bin=emptied'"
    elif op == "get_system_info":
        script = (
            "$os=(Get-WmiObject Win32_OperatingSystem); "
            "$cpu=[Math]::Round((Get-WmiObject Win32_Processor | "
            "Measure-Object -Property LoadPercentage -Average).Average, 1); "
            "$totalRam=[Math]::Round($os.TotalVisibleMemorySize/1MB, 2); "
            "$freeRam=[Math]::Round($os.FreePhysicalMemory/1MB, 2); "
            "$usedRam=[Math]::Round($totalRam - $freeRam, 2); "
            "$ramPct=[Math]::Round(($usedRam/$totalRam)*100, 1); "
            "$uptime=(Get-Date) - $os.ConvertToDateTime($os.LastBootUpTime); "
            "$uptimeStr=('{0}d {1}h {2}m' -f [int]$uptime.TotalDays, $uptime.Hours, $uptime.Minutes); "
            "Write-Output ('os=' + $os.Caption + ' | cpu=' + $cpu + '% | ram=' + $usedRam + '/' + $totalRam + 'GB (' + $ramPct + '%) | uptime=' + $uptimeStr)"
        )
    else:
        raise ValueError(
            "unsupported action. use: volume_up, volume_down, mute_toggle, show_desktop, "
            "media_play_pause, media_next, media_prev, lock_screen, window_minimize_all, "
            "window_restore_all, brightness_up, brightness_down, brightness_set, wifi_on, wifi_off, "
            "bluetooth_on, bluetooth_off, screenshot, open_url, sleep_display, "
            "empty_recycle_bin, get_system_info"
        )

    res = _run_powershell(script)
    ok = int(res["exit_code"]) == 0
    out: Dict[str, Any] = {
        "kind": "system_control",
        "ok": ok,
        "action": op,
        "amount": n,
        "stdout": res["stdout"],
        "stderr": res["stderr"],
        "exit_code": res["exit_code"],
    }
    if op == "screenshot" and ok:
        out["path"] = res["stdout"]
    return out
