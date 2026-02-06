"""
Hotspot Tool - Control Windows Mobile Hotspot.

Actions:
- on/enable: Turn on mobile hotspot
- off/disable: Turn off mobile hotspot
- status: Check hotspot status
"""

import subprocess
import ctypes
import sys


def _is_admin() -> bool:
    """Check if running as administrator."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def _run_powershell(script: str) -> tuple[bool, str]:
    """Run a PowerShell script and return (success, output)."""
    try:
        result = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True,
            text=True,
            shell=False,
            timeout=15
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output.strip()
    except Exception as e:
        return False, str(e)


def _run_netsh(args: list[str]) -> tuple[bool, str]:
    """Run netsh command and return (success, output)."""
    try:
        result = subprocess.run(
            ["netsh"] + args,
            capture_output=True,
            text=True,
            shell=False,
            timeout=10
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output.strip()
    except Exception as e:
        return False, str(e)


def run(action: str = "status", **kwargs) -> dict:
    """
    Manage Windows Mobile Hotspot.
    
    Actions:
        - status: Get current hotspot status
        - on/enable: Turn on mobile hotspot
        - off/disable: Turn off mobile hotspot
    """
    action = (action or "status").strip().lower()
    
    # Normalize action aliases
    action_aliases = {
        "enable": "on",
        "start": "on",
        "disable": "off",
        "stop": "off",
        "check": "status",
        "state": "status",
    }
    action = action_aliases.get(action, action)
    
    try:
        if action == "status":
            # Check hotspot status using netsh
            ok, output = _run_netsh(["wlan", "show", "hostednetwork"])
            
            if "not started" in output.lower() or "not configured" in output.lower():
                return {
                    "status": "success",
                    "message": "Mobile Hotspot is off",
                    "hotspot_enabled": False
                }
            elif "started" in output.lower():
                # Parse SSID if available
                ssid = ""
                for line in output.split("\n"):
                    if "ssid" in line.lower() and "name" in line.lower():
                        parts = line.split(":", 1)
                        if len(parts) > 1:
                            ssid = parts[1].strip().strip('"')
                            break
                
                return {
                    "status": "success",
                    "message": f"Mobile Hotspot is on{' - ' + ssid if ssid else ''}",
                    "hotspot_enabled": True,
                    "ssid": ssid
                }
            else:
                # Try Windows Settings approach
                ps_script = """
                try {
                    $tetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
                    $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]::GetInternetConnectionProfile()
                    $manager = $tetheringManager::CreateFromConnectionProfile($connectionProfile)
                    if ($manager.TetheringOperationalState -eq 'On') {
                        Write-Output "HOTSPOT_ON"
                    } else {
                        Write-Output "HOTSPOT_OFF"
                    }
                } catch {
                    Write-Output "UNKNOWN"
                }
                """
                ok, output = _run_powershell(ps_script)
                
                if "HOTSPOT_ON" in output:
                    return {
                        "status": "success",
                        "message": "Mobile Hotspot is on",
                        "hotspot_enabled": True
                    }
                elif "HOTSPOT_OFF" in output:
                    return {
                        "status": "success",
                        "message": "Mobile Hotspot is off",
                        "hotspot_enabled": False
                    }
                
                return {
                    "status": "success",
                    "message": "Mobile Hotspot status unknown",
                    "hotspot_enabled": None
                }
        
        if action == "on":
            # Method 1: Try using Windows API via PowerShell
            ps_script = """
            Add-Type -AssemblyName System.Runtime.WindowsRuntime
            $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
            
            function Await($WinRtTask, $ResultType) {
                $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
                $netTask = $asTask.Invoke($null, @($WinRtTask))
                $netTask.Wait(-1) | Out-Null
                $netTask.Result
            }
            
            $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]::GetInternetConnectionProfile()
            $tetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]::CreateFromConnectionProfile($connectionProfile)
            
            $result = Await ($tetheringManager.StartTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
            
            if ($result.Status -eq 'Success') {
                Write-Output "SUCCESS"
            } else {
                Write-Output "FAILED: $($result.Status)"
            }
            """
            
            ok, output = _run_powershell(ps_script)
            
            if "SUCCESS" in output:
                return {"status": "success", "message": "Mobile Hotspot turned on"}
            
            # Method 2: Try netsh approach
            ok, output = _run_netsh(["wlan", "start", "hostednetwork"])
            if ok:
                return {"status": "success", "message": "Mobile Hotspot turned on"}
            
            if "elevation" in output.lower() or "administrator" in output.lower():
                return {
                    "status": "fail",
                    "reason": "Requires administrator privileges",
                    "hint": "Run as admin to control hotspot"
                }
            
            # Method 3: Open Windows Settings as fallback
            try:
                subprocess.Popen(["start", "ms-settings:network-mobilehotspot"], shell=True)
                return {
                    "status": "partial",
                    "message": "Opened Mobile Hotspot settings - please enable manually",
                    "hint": "Toggle the hotspot switch"
                }
            except:
                pass
            
            return {"status": "fail", "reason": "Could not enable hotspot", "error": output}
        
        if action == "off":
            # Method 1: Try Windows API via PowerShell
            ps_script = """
            Add-Type -AssemblyName System.Runtime.WindowsRuntime
            $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
            
            function Await($WinRtTask, $ResultType) {
                $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
                $netTask = $asTask.Invoke($null, @($WinRtTask))
                $netTask.Wait(-1) | Out-Null
                $netTask.Result
            }
            
            $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]::GetInternetConnectionProfile()
            $tetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]::CreateFromConnectionProfile($connectionProfile)
            
            $result = Await ($tetheringManager.StopTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
            
            if ($result.Status -eq 'Success') {
                Write-Output "SUCCESS"
            } else {
                Write-Output "FAILED: $($result.Status)"
            }
            """
            
            ok, output = _run_powershell(ps_script)
            
            if "SUCCESS" in output:
                return {"status": "success", "message": "Mobile Hotspot turned off"}
            
            # Method 2: Try netsh approach
            ok, output = _run_netsh(["wlan", "stop", "hostednetwork"])
            if ok:
                return {"status": "success", "message": "Mobile Hotspot turned off"}
            
            return {"status": "fail", "reason": "Could not disable hotspot", "error": output}
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
    
    except Exception as e:
        return {"status": "fail", "reason": "Hotspot operation failed", "error": str(e)}
