import ctypes
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_powershell(script: str, timeout: int = 15) -> Dict[str, Any]:
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


# ---------------------------------------------------------------------------
# Volume helpers — use winmm.dll waveOut* (works on all Windows audio setups)
# ---------------------------------------------------------------------------

def _get_master_volume_pct() -> int:
    """Return current master volume as integer 0-100."""
    vol = ctypes.c_uint32(0)
    ctypes.windll.winmm.waveOutGetVolume(None, ctypes.byref(vol))
    left = (vol.value & 0xFFFF) / 0xFFFF * 100
    return round(left)


def _set_master_volume_pct(pct: int) -> None:
    """Set master volume to pct (0-100)."""
    pct = max(0, min(100, pct))
    word = int(pct / 100.0 * 0xFFFF)
    packed = (word & 0xFFFF) | ((word & 0xFFFF) << 16)
    ctypes.windll.winmm.waveOutSetVolume(None, packed)


# ---------------------------------------------------------------------------
# Brightness helpers — WMI (laptop/built-in) with keybd fallback
# ---------------------------------------------------------------------------

def _wmi_set_brightness(level: int) -> bool:
    """Try WMI brightness set. Returns True if succeeded."""
    r = _run_powershell(
        f"$m=Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods "
        f"-ErrorAction SilentlyContinue | Select-Object -First 1; "
        f"if($m){{ $m.WmiSetBrightness(1,{level}) | Out-Null; Write-Output 'ok' }} "
        f"else {{ Write-Output 'no_wmi' }}"
    )
    return r["stdout"].strip() == "ok"


def _wmi_get_brightness() -> Optional[int]:
    """Return current brightness 0-100, or None if WMI not available."""
    r = _run_powershell(
        "$b=Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness "
        "-ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if($b){ Write-Output $b.CurrentBrightness } else { Write-Output 'no_wmi' }"
    )
    v = r["stdout"].strip()
    if v == "no_wmi" or not v.isdigit():
        return None
    return int(v)


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

    # ------------------------------------------------------------------
    # Volume — Python-native via winmm.dll (reliable on all Windows)
    # ------------------------------------------------------------------
    if op == "volume_up":
        cur = _get_master_volume_pct()
        new_vol = min(100, cur + n * 2)
        _set_master_volume_pct(new_vol)
        return {
            "kind": "system_control", "ok": True, "action": op,
            "stdout": f"volume={new_vol}% (was {cur}%)", "stderr": "", "exit_code": 0, "amount": n,
        }
    elif op == "volume_down":
        cur = _get_master_volume_pct()
        new_vol = max(0, cur - n * 2)
        _set_master_volume_pct(new_vol)
        return {
            "kind": "system_control", "ok": True, "action": op,
            "stdout": f"volume={new_vol}% (was {cur}%)", "stderr": "", "exit_code": 0, "amount": n,
        }
    elif op in {"mute_toggle", "mute", "unmute"}:
        # Use keybd_event for mute toggle (reliable)
        keybd = ctypes.windll.user32.keybd_event
        keybd(0xAD, 0, 0, 0); time.sleep(0.02); keybd(0xAD, 0, 2, 0)
        return {
            "kind": "system_control", "ok": True, "action": op,
            "stdout": "mute_toggled=ok", "stderr": "", "exit_code": 0, "amount": n,
        }
    elif op == "volume_set":
        level = max(0, min(int(amount), 100))
        _set_master_volume_pct(level)
        actual = _get_master_volume_pct()
        return {
            "kind": "system_control", "ok": True, "action": op,
            "stdout": f"volume={actual}%", "stderr": "", "exit_code": 0, "amount": level,
        }
    elif op == "get_volume":
        cur = _get_master_volume_pct()
        return {
            "kind": "system_control", "ok": True, "action": op,
            "stdout": f"volume={cur}%", "stderr": "", "exit_code": 0, "amount": n,
        }

    # ------------------------------------------------------------------
    # Brightness — WMI for laptop/built-in displays; honest error for external
    # ------------------------------------------------------------------
    elif op in {"brightness_up", "brightness_down", "brightness_set", "get_brightness"}:
        if op == "get_brightness":
            cur_b = _wmi_get_brightness()
            if cur_b is None:
                return {
                    "kind": "system_control", "ok": False, "action": op,
                    "stdout": "",
                    "stderr": (
                        "brightness_unavailable: This monitor does not support software brightness control. "
                        "WMI brightness is only supported on laptop built-in displays (LVDS/eDP). "
                        "For external monitors, adjust brightness using the physical buttons on the monitor."
                    ),
                    "exit_code": 1, "amount": n,
                }
            return {
                "kind": "system_control", "ok": True, "action": op,
                "stdout": f"brightness={cur_b}%", "stderr": "", "exit_code": 0, "amount": n,
            }
        elif op == "brightness_set":
            target_b = max(1, min(int(amount), 100))
        else:
            cur_b = _wmi_get_brightness()
            if cur_b is None:
                cur_b = 50  # assume midpoint if can't read
            delta = n * 5 if op == "brightness_up" else -n * 5
            target_b = max(1, min(100, cur_b + delta))
        ok_b = _wmi_set_brightness(target_b)
        if not ok_b:
            return {
                "kind": "system_control", "ok": False, "action": op,
                "stdout": "",
                "stderr": (
                    "brightness_unavailable: This monitor does not support software brightness control via WMI. "
                    "WMI brightness only works on laptop built-in displays. "
                    "For external/desktop monitors, use the physical buttons on the monitor."
                ),
                "exit_code": 1, "amount": n,
            }
        return {
            "kind": "system_control", "ok": True, "action": op,
            "stdout": f"brightness={target_b}%", "stderr": "", "exit_code": 0, "amount": n,
        }

    # ------------------------------------------------------------------
    # Wi-Fi / Bluetooth
    # ------------------------------------------------------------------
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
        bt_state = op.split("_", 1)[1]
        script = (
            "$devs=Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue; "
            "if(-not $devs){ throw 'no bluetooth adapter found' }; "
            f"$devs | ForEach-Object {{ {cmd} -InstanceId $_.InstanceId -Confirm:$false -ErrorAction Stop }}; "
            f"Write-Output 'bluetooth={bt_state}'"
        )

    # ------------------------------------------------------------------
    # Battery & Power
    # ------------------------------------------------------------------
    elif op == "get_battery_status":
        script = (
            "$b=Get-WmiObject Win32_Battery -ErrorAction SilentlyContinue; "
            "if(-not $b){ Write-Output 'battery=not_found (desktop or battery not detected)' } else { "
            "$pct=$b.EstimatedChargeRemaining; "
            "$status=switch($b.BatteryStatus){ 1{'discharging'} 2{'plugged_in'} 3{'fully_charged'} 4{'low'} 5{'critical'} 6{'charging'} 7{'charging_high'} 8{'charging_low'} 9{'charging_critical'} default{'unknown'} }; "
            "$mins=$b.EstimatedRunTime; "
            "if($mins -eq 71582788){ $timeStr='unknown' } else { $h=[Math]::Floor($mins/60); $m=$mins%60; $timeStr=('{0}h {1}m' -f $h,$m) }; "
            "Write-Output ('battery=' + $pct + '% | status=' + $status + ' | time_remaining=' + $timeStr) }"
        )
    elif op == "set_power_plan":
        plan = str(path or "balanced").strip().lower()
        plan_guids = {
            "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
            "performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
            "high_performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
            "power_saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
            "saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
        }
        guid = plan_guids.get(plan, plan_guids["balanced"])
        script = (
            f"powercfg /setactive {guid}; "
            f"if($LASTEXITCODE -eq 0){{ Write-Output 'power_plan={plan}' }} else {{ Write-Error 'Failed to set power plan' }}"
        )

    # ------------------------------------------------------------------
    # Network Status
    # ------------------------------------------------------------------
    elif op == "get_network_status":
        script = (
            "$adapters=Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' }; "
            "$adapterList=($adapters | ForEach-Object { $_.Name + '(' + $_.LinkSpeed + ')' }) -join ', '; "
            "$ip=(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notmatch '^127\\.' } | Select-Object -First 1).IPAddress; "
            "try { $pub=(Invoke-WebRequest -Uri 'https://api.ipify.org' -UseBasicParsing -TimeoutSec 5).Content.Trim() } catch { $pub='unavailable' }; "
            "$dns=(Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -First 1).ServerAddresses -join ', '; "
            "Write-Output ('adapters=' + $adapterList + ' | local_ip=' + $ip + ' | public_ip=' + $pub + ' | dns=' + $dns)"
        )

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------
    elif op == "get_clipboard":
        script = (
            "$c=Get-Clipboard -ErrorAction SilentlyContinue; "
            "if($null -eq $c -or $c -eq ''){ Write-Output 'clipboard=(empty)' } else { Write-Output ('clipboard=' + ($c -join ' ')) }"
        )
    elif op == "set_clipboard":
        text = str(path or "").strip().strip("\"'").replace("'", "''")
        script = f"Set-Clipboard -Value '{text}'; Write-Output 'clipboard_set=ok'"

    # ------------------------------------------------------------------
    # Process Manager
    # ------------------------------------------------------------------
    elif op == "list_processes":
        script = (
            "$procs = Get-Process -ErrorAction SilentlyContinue | "
            "Sort-Object CPU -Descending | Select-Object -First 15 | "
            "ForEach-Object { $_.Name + '(cpu=' + [Math]::Round($_.CPU,1) + 's mem=' + [Math]::Round($_.WorkingSet64/1MB,1) + 'MB pid=' + $_.Id + ')' }; "
            "Write-Output ($procs -join ' | ')"
        )
    elif op == "kill_process":
        proc_name = str(path or "").strip().strip("\"'").replace("'", "''")
        if not proc_name:
            raise ValueError("kill_process requires a process name — pass it via the 'path' parameter")
        script = (
            f"$p=Get-Process -Name '{proc_name}' -ErrorAction SilentlyContinue; "
            "if(-not $p){ Write-Error 'process not found' } else { "
            f"Stop-Process -Name '{proc_name}' -Force -ErrorAction Stop; "
            f"Write-Output 'killed={proc_name}' }}"
        )

    # ------------------------------------------------------------------
    # Shutdown / Restart / Hibernate / Sign Out
    # ------------------------------------------------------------------
    elif op == "shutdown":
        script = "shutdown /s /t 5; Write-Output 'shutdown=scheduled_in_5s'"
    elif op == "restart":
        script = "shutdown /r /t 5; Write-Output 'restart=scheduled_in_5s'"
    elif op == "hibernate":
        script = "shutdown /h; Write-Output 'hibernate=ok'"
    elif op == "sign_out":
        script = "shutdown /l; Write-Output 'sign_out=ok'"
    elif op == "cancel_shutdown":
        script = "shutdown /a; Write-Output 'shutdown=cancelled'"

    # ------------------------------------------------------------------
    # Night Light / Dark Mode
    # ------------------------------------------------------------------
    elif op in {"night_light_on", "night_light_off"}:
        # Toggle Windows Night Light via registry + action center key
        enable = "1" if op == "night_light_on" else "0"
        state = "on" if op == "night_light_on" else "off"
        script = (
            "$regPath='HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\CloudStore\\Store\\DefaultAccount\\Current\\default$windows.data.bluelightreduction.bluelightreductionstate\\windows.data.bluelightreduction.bluelightreductionstate'; "
            "if(Test-Path $regPath){ "
            "$data=(Get-ItemProperty -Path $regPath -Name Data -ErrorAction SilentlyContinue).Data; "
            "if($data){ "
            # Byte 18 controls the toggle: 0x13=on, 0x15=off (Windows internal)
            f"$data[18] = if('{state}' -eq 'on'){{ 0x13 }} else {{ 0x15 }}; "
            "Set-ItemProperty -Path $regPath -Name Data -Value $data; "
            f"Write-Output 'night_light={state}' "
            "} else { Write-Error 'Night light registry data not found' } "
            "} else { Write-Error 'Night light registry path not found — feature may not be supported on this build' }"
        )
    elif op in {"dark_mode_on", "dark_mode_off", "light_mode_on", "light_mode_off"}:
        # dark_mode_on → apps & system use dark (value=0)
        # dark_mode_off / light_mode_on → apps & system use light (value=1)
        use_dark = op in {"dark_mode_on", "light_mode_off"}
        apps_val = "0" if use_dark else "1"
        sys_val = "0" if use_dark else "1"
        mode_label = "dark" if use_dark else "light"
        script = (
            "$regPath='HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize'; "
            f"Set-ItemProperty -Path $regPath -Name AppsUseLightTheme -Value {apps_val} -Type DWord -Force; "
            f"Set-ItemProperty -Path $regPath -Name SystemUsesLightTheme -Value {sys_val} -Type DWord -Force; "
            f"Write-Output 'theme={mode_label}_mode'"
        )

    # ------------------------------------------------------------------
    # Windows Toast Notification
    # ------------------------------------------------------------------
    elif op == "notify":
        message = str(path or "").strip().strip("\"'").replace("'", "''").replace('"', '""')
        if not message:
            raise ValueError("notify requires a message — pass it via the 'path' parameter")
        title = "A.N.K.I.T.A"
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null; "
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null; "
            f"$template = '<toast><visual><binding template=\"ToastText02\"><text id=\"1\">{title}</text><text id=\"2\">{message}</text></binding></visual></toast>'; "
            "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; "
            "$xml.LoadXml($template); "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
            "$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('ANKITA'); "
            "$notifier.Show($toast); "
            "Write-Output 'notify=sent'"
        )

    # ------------------------------------------------------------------
    # Existing: Window / Desktop / Media / Screenshot / URL / Display
    # ------------------------------------------------------------------
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
        url = str(path or "").strip().strip("\"'")
        if not url:
            raise ValueError("open_url requires a url — pass it via the 'path' parameter")
        if not url.startswith(("http://", "https://", "ftp://")):
            url = "https://" + url
        escaped_url = url.replace("'", "''")
        script = f"Start-Process '{escaped_url}'; Write-Output 'opened: {escaped_url}'"
    elif op == "sleep_display":
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
            "unsupported action. Supported actions: "
            "volume_up, volume_down, volume_set, get_volume, mute_toggle, "
            "brightness_up, brightness_down, brightness_set, get_brightness, "
            "wifi_on, wifi_off, bluetooth_on, bluetooth_off, "
            "get_battery_status, set_power_plan, "
            "get_network_status, get_clipboard, set_clipboard, "
            "list_processes, kill_process, "
            "shutdown, restart, hibernate, sign_out, cancel_shutdown, "
            "night_light_on, night_light_off, dark_mode_on, dark_mode_off, "
            "notify, show_desktop, lock_screen, "
            "window_minimize_all, window_restore_all, "
            "media_play_pause, media_next, media_prev, "
            "screenshot, open_url, sleep_display, "
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
