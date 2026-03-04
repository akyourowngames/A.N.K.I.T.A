"""
System audit and logging operations for ANKITA.
Reads Windows Event Logs, login history, crash reports, and security events.
All operations are read-only and use PowerShell/WMI under the hood.
"""
import subprocess
import json
from datetime import datetime
from typing import Any, Dict, Optional


def _run_powershell(script: str, timeout: int = 30) -> Dict[str, Any]:
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


def read_event_log(
    log_name: str = "System",
    level: str = "all",
    max_entries: int = 20,
) -> Dict[str, Any]:
    """Read Windows Event Log entries.

    Args:
        log_name: Event log name — System, Application, Security, Setup
        level: Filter by level — all, error, warning, critical, information
        max_entries: Max entries to return (default 20, max 50)
    """
    max_entries = min(max(1, max_entries), 50)
    log_name = log_name.strip() or "System"

    # Build level filter
    level_filter = ""
    level_map = {
        "critical": "Level=1",
        "error": "Level=2",
        "warning": "Level=3",
        "information": "Level=4",
    }
    if level.lower() in level_map:
        level_filter = f" -and {level_map[level.lower()]}"

    script = (
        f"Get-WinEvent -LogName '{log_name}' -MaxEvents {max_entries} "
        f"-ErrorAction SilentlyContinue | "
        "Select-Object TimeCreated, Id, LevelDisplayName, ProviderName, Message | "
        "ForEach-Object { "
        "  $obj = [ordered]@{"
        "    time = $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss');"
        "    id = $_.Id;"
        "    level = $_.LevelDisplayName;"
        "    source = $_.ProviderName;"
        "    message = ($_.Message -replace '\\r?\\n', ' ').Substring(0, [Math]::Min(200, $_.Message.Length))"
        "  };"
        "  $obj | ConvertTo-Json -Compress"
        "}"
    )

    try:
        res = _run_powershell(script, timeout=15)
        if res["exit_code"] != 0:
            return {"ok": False, "error": res["stderr"] or "Failed to read event log"}

        entries = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        return {
            "ok": True,
            "log_name": log_name,
            "count": len(entries),
            "entries": entries,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Event log query timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_login_history(max_entries: int = 15) -> Dict[str, Any]:
    """Get recent login/logout events from Windows Security log."""
    max_entries = min(max(1, max_entries), 30)

    # Event IDs: 4624=logon, 4625=failed logon, 4634=logoff, 4648=explicit logon
    script = (
        "try { "
        f"  $events = Get-WinEvent -FilterHashtable @{{LogName='Security'; Id=4624,4625,4634}} "
        f"  -MaxEvents {max_entries} -ErrorAction Stop; "
        "  $events | ForEach-Object { "
        "    $type = switch ($_.Id) { 4624 {'LOGIN'} 4625 {'FAILED_LOGIN'} 4634 {'LOGOUT'} default {'OTHER'} }; "
        "    $obj = [ordered]@{"
        "      time = $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss');"
        "      event = $type;"
        "      event_id = $_.Id;"
        "      message = ($_.Message -replace '\\r?\\n', ' ').Substring(0, [Math]::Min(150, $_.Message.Length))"
        "    }; "
        "    $obj | ConvertTo-Json -Compress"
        "  } "
        "} catch { "
        "  Write-Output ('{\"ok\":false,\"error\":\"' + $_.Exception.Message + '\"}') "
        "}"
    )

    try:
        res = _run_powershell(script, timeout=15)
        entries = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    parsed = json.loads(line)
                    if "error" in parsed and not parsed.get("ok", True):
                        return {"ok": False, "error": parsed["error"]}
                    entries.append(parsed)
                except json.JSONDecodeError:
                    pass

        if not entries and res["stderr"]:
            # Security log often requires admin privileges
            return {
                "ok": False,
                "error": "Cannot read Security log — requires admin privileges. "
                         "Try running ANKITA as Administrator.",
            }

        return {
            "ok": True,
            "count": len(entries),
            "entries": entries,
            "note": "Security log events (4624=login, 4625=failed, 4634=logout)",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Login history query timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_crash_reports(max_entries: int = 10) -> Dict[str, Any]:
    """Get recent application crash and hang reports from Windows Error Reporting."""
    max_entries = min(max(1, max_entries), 30)

    script = (
        "Get-WinEvent -FilterHashtable @{LogName='Application'; "
        "ProviderName='Windows Error Reporting','Application Error','Application Hang'} "
        f"-MaxEvents {max_entries} -ErrorAction SilentlyContinue | "
        "ForEach-Object { "
        "  $obj = [ordered]@{"
        "    time = $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss');"
        "    source = $_.ProviderName;"
        "    level = $_.LevelDisplayName;"
        "    message = ($_.Message -replace '\\r?\\n', ' ').Substring(0, [Math]::Min(250, $_.Message.Length))"
        "  }; "
        "  $obj | ConvertTo-Json -Compress"
        "}"
    )

    try:
        res = _run_powershell(script, timeout=15)
        entries = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        return {
            "ok": True,
            "count": len(entries),
            "entries": entries,
            "note": "Application crashes and error reports",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_security_events(max_entries: int = 15) -> Dict[str, Any]:
    """Get security-relevant events: firewall changes, audit policy, privilege use."""
    max_entries = min(max(1, max_entries), 30)

    # Security events: 4719=audit policy changed, 4946/4947=firewall rule changed,
    # 4672=special privileges assigned, 4688=new process created
    script = (
        "try { "
        f"  $events = Get-WinEvent -FilterHashtable @{{LogName='Security'; Id=4672,4688,4719,4946,4947}} "
        f"  -MaxEvents {max_entries} -ErrorAction Stop; "
        "  $events | ForEach-Object { "
        "    $type = switch ($_.Id) { "
        "      4672 {'SPECIAL_PRIVILEGES'} "
        "      4688 {'PROCESS_CREATED'} "
        "      4719 {'AUDIT_POLICY_CHANGED'} "
        "      4946 {'FIREWALL_RULE_ADDED'} "
        "      4947 {'FIREWALL_RULE_CHANGED'} "
        "      default {'OTHER'} }; "
        "    $obj = [ordered]@{"
        "      time = $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss');"
        "      event = $type;"
        "      event_id = $_.Id;"
        "      message = ($_.Message -replace '\\r?\\n', ' ').Substring(0, [Math]::Min(200, $_.Message.Length))"
        "    }; "
        "    $obj | ConvertTo-Json -Compress"
        "  } "
        "} catch { "
        "  Write-Output ('{\"ok\":false,\"error\":\"' + $_.Exception.Message + '\"}') "
        "}"
    )

    try:
        res = _run_powershell(script, timeout=15)
        entries = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    parsed = json.loads(line)
                    if "error" in parsed and not parsed.get("ok", True):
                        return {"ok": False, "error": parsed["error"]}
                    entries.append(parsed)
                except json.JSONDecodeError:
                    pass

        if not entries and res["stderr"]:
            return {
                "ok": False,
                "error": "Cannot read Security log — requires admin privileges.",
            }

        return {
            "ok": True,
            "count": len(entries),
            "entries": entries,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_startup_shutdown_log(max_entries: int = 15) -> Dict[str, Any]:
    """Get system startup and shutdown events."""
    max_entries = min(max(1, max_entries), 30)

    # Event IDs: 6005=event log service started (boot), 6006=event log service stopped (shutdown),
    # 6008=unexpected shutdown, 6009=OS version at boot, 1074=user-initiated shutdown
    script = (
        f"Get-WinEvent -FilterHashtable @{{LogName='System'; Id=6005,6006,6008,6009,1074}} "
        f"-MaxEvents {max_entries} -ErrorAction SilentlyContinue | "
        "ForEach-Object { "
        "  $type = switch ($_.Id) { "
        "    6005 {'BOOT'} "
        "    6006 {'CLEAN_SHUTDOWN'} "
        "    6008 {'UNEXPECTED_SHUTDOWN'} "
        "    6009 {'BOOT_INFO'} "
        "    1074 {'USER_SHUTDOWN'} "
        "    default {'OTHER'} }; "
        "  $obj = [ordered]@{"
        "    time = $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss');"
        "    event = $type;"
        "    event_id = $_.Id;"
        "    message = ($_.Message -replace '\\r?\\n', ' ').Substring(0, [Math]::Min(200, $_.Message.Length))"
        "  }; "
        "  $obj | ConvertTo-Json -Compress"
        "}"
    )

    try:
        res = _run_powershell(script, timeout=15)
        entries = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        return {
            "ok": True,
            "count": len(entries),
            "entries": entries,
            "note": "6005=boot, 6006=clean shutdown, 6008=unexpected shutdown, 1074=user-initiated",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def system_audit(action: str, **kwargs) -> Dict[str, Any]:
    """
    Main system audit dispatcher.
    Actions: read_event_log, get_login_history, get_crash_reports,
             security_events, startup_shutdown_log
    """
    if action == "read_event_log":
        return read_event_log(
            log_name=kwargs.get("log_name", "System"),
            level=kwargs.get("level", "all"),
            max_entries=int(kwargs.get("max_entries", 20)),
        )
    elif action == "get_login_history":
        return get_login_history(
            max_entries=int(kwargs.get("max_entries", 15)),
        )
    elif action == "get_crash_reports":
        return get_crash_reports(
            max_entries=int(kwargs.get("max_entries", 10)),
        )
    elif action == "security_events":
        return get_security_events(
            max_entries=int(kwargs.get("max_entries", 15)),
        )
    elif action == "startup_shutdown_log":
        return get_startup_shutdown_log(
            max_entries=int(kwargs.get("max_entries", 15)),
        )
    else:
        return {
            "ok": False,
            "error": f"Unknown system_audit action: {action}. "
                     "Supported: read_event_log, get_login_history, get_crash_reports, "
                     "security_events, startup_shutdown_log",
        }
