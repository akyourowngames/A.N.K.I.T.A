"""
DND (Do Not Disturb) / Focus Mode Tool - Control Windows Focus Assist
"""
import subprocess
import winreg


def _get_focus_assist_status():
    """Get current Focus Assist state from registry"""
    try:
        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\Current\default$windows.data.notifications.quiethourssettings"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, "Data")
        winreg.CloseKey(key)
        
        # Check byte at position 2 (0=off, 1=priority, 2=alarms)
        if len(value) > 2:
            state = value[2]
            return {0: "off", 1: "priority", 2: "alarms"}.get(state, "unknown")
        return "unknown"
    except Exception as e:
        return "unknown"


def _set_focus_assist(mode):
    """Set Focus Assist mode using PowerShell"""
    try:
        # Mode: 0=Off, 1=Priority, 2=Alarms Only
        ps_script = f"""
        $path = 'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\CloudStore\\Store\\DefaultAccount\\Current\\default$windows.data.notifications.quiethourssettings'
        if (Test-Path $path) {{
            $value = Get-ItemProperty -Path $path -Name "Data"
            $bytes = $value.Data
            $bytes[2] = {mode}
            Set-ItemProperty -Path $path -Name "Data" -Value $bytes -Type Binary
        }}
        """
        subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True,
            timeout=5
        )
        return True
    except Exception as e:
        print(f"[DND] Error setting focus assist: {e}")
        return False


def run(action: str = "on", **kwargs):
    """
    DND/Focus Mode tool
    
    Args:
        action: on, off, priority, alarms, status
    """
    action = action.lower().strip()
    
    if action == "status":
        state = _get_focus_assist_status()
        return {
            "status": "success",
            "dnd_state": state,
            "message": f"Focus Assist is {state}"
        }
    
    elif action == "on":
        # Priority only mode
        if _set_focus_assist(1):
            return {
                "status": "success",
                "message": "Focus mode on (priority notifications only)"
            }
        else:
            return {"status": "fail", "reason": "could_not_enable"}
    
    elif action == "off":
        if _set_focus_assist(0):
            return {
                "status": "success",
                "message": "Focus mode off (all notifications enabled)"
            }
        else:
            return {"status": "fail", "reason": "could_not_disable"}
    
    elif action == "priority":
        if _set_focus_assist(1):
            return {
                "status": "success",
                "message": "Priority only mode enabled"
            }
        else:
            return {"status": "fail", "reason": "could_not_set"}
    
    elif action == "alarms":
        if _set_focus_assist(2):
            return {
                "status": "success",
                "message": "Alarms only mode enabled"
            }
        else:
            return {"status": "fail", "reason": "could_not_set"}
    
    else:
        return {"status": "fail", "reason": "invalid_action"}
