"""
Audio Device Tool - Switch between audio output devices.
"""
import subprocess


def _run_powershell(script: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True, text=True, shell=False, timeout=15
        )
        return result.returncode == 0, (result.stdout or "") + (result.stderr or "")
    except Exception as e:
        return False, str(e)


def run(action: str = "status", device: str = None, **kwargs) -> dict:
    action = (action or "status").strip().lower()
    device = device or kwargs.get("name", "")
    
    try:
        if action in ("status", "list", "devices"):
            # List audio devices using PowerShell
            ps_script = """
            Get-AudioDevice -List | Select-Object Index, Name, Type, Default | Format-Table -AutoSize
            """
            ok, output = _run_powershell(ps_script)
            
            if not ok or "not recognized" in output.lower():
                # AudioDeviceCmdlets not installed, use settings
                subprocess.Popen(["start", "ms-settings:sound"], shell=True)
                return {
                    "status": "partial",
                    "message": "Opened Sound settings - view devices there"
                }
            
            return {"status": "success", "message": "Audio devices listed", "devices": output}
        
        if action in ("switch", "set", "use"):
            if not device:
                subprocess.Popen(["start", "ms-settings:sound"], shell=True)
                return {"status": "partial", "message": "Opened Sound settings - select device"}
            
            # Try to switch using AudioDeviceCmdlets
            device_lower = device.lower()
            
            # Common device mappings
            if any(x in device_lower for x in ["speaker", "speakers"]):
                ps_script = 'Get-AudioDevice -List | Where-Object {$_.Name -like "*Speaker*"} | Set-AudioDevice'
            elif any(x in device_lower for x in ["headphone", "headphones", "headset"]):
                ps_script = 'Get-AudioDevice -List | Where-Object {$_.Name -like "*Headphone*" -or $_.Name -like "*Headset*"} | Set-AudioDevice'
            elif "bluetooth" in device_lower:
                ps_script = 'Get-AudioDevice -List | Where-Object {$_.Name -like "*Bluetooth*"} | Set-AudioDevice'
            else:
                ps_script = f'Get-AudioDevice -List | Where-Object {{$_.Name -like "*{device}*"}} | Set-AudioDevice'
            
            ok, output = _run_powershell(ps_script)
            
            if ok and "not recognized" not in output.lower():
                return {"status": "success", "message": f"Switched to {device}"}
            
            # Fallback to settings
            subprocess.Popen(["start", "ms-settings:sound"], shell=True)
            return {"status": "partial", "message": f"Opened Sound settings - select {device}"}
        
        if action == "settings":
            subprocess.Popen(["start", "ms-settings:sound"], shell=True)
            return {"status": "success", "message": "Opened Sound settings"}
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
    except Exception as e:
        return {"status": "fail", "reason": str(e)}
