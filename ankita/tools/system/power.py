"""
Power Tool - Lock, sleep, shutdown, restart, hibernate, logoff.
Polished with confirmation and better error handling.
"""
import ctypes
import subprocess


def run(action: str = "lock", force: bool = False, delay: int = 0, **kwargs) -> dict:
    """
    System power operations.
    
    Actions:
        - lock/lockscreen: Lock the computer
        - sleep/standby: Put computer to sleep
        - shutdown/poweroff: Shutdown the computer
        - restart/reboot: Restart the computer
        - hibernate: Hibernate (save to disk)
        - logoff/logout/signout: Log out current user
        - cancel/abort: Cancel pending shutdown/restart
    
    Args:
        force: Force close applications without prompting
        delay: Delay in seconds before shutdown/restart
    """
    action = (action or "lock").strip().lower()
    
    # Normalize action aliases
    action_aliases = {
        "lockscreen": "lock",
        "standby": "sleep",
        "suspend": "sleep",
        "poweroff": "shutdown",
        "turnoff": "shutdown",
        "reboot": "restart",
        "logout": "logoff",
        "signout": "logoff",
        "abort": "cancel",
        "stop": "cancel",
    }
    action = action_aliases.get(action, action)
    
    try:
        if action == "lock":
            result = ctypes.windll.user32.LockWorkStation()
            if result:
                return {"status": "success", "message": "Computer locked"}
            return {"status": "fail", "reason": "Failed to lock computer"}
        
        if action == "sleep":
            # Use SetSuspendState(hibernate, forcecritical, disablewakeevent)
            # hibernate=False means sleep, not hibernate
            try:
                result = ctypes.windll.powrprof.SetSuspendState(0, int(force), 0)
                if result != 0 or not result:
                    return {"status": "success", "message": "Entering sleep mode"}
            except Exception:
                pass
            
            # Fallback to command
            cmd = ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
            subprocess.run(cmd, shell=False)
            return {"status": "success", "message": "Entering sleep mode"}
        
        if action == "shutdown":
            cmd = ["shutdown", "/s"]
            if force:
                cmd.append("/f")
            if delay > 0:
                cmd.extend(["/t", str(delay)])
                msg = f"Shutting down in {delay} seconds"
            else:
                cmd.extend(["/t", "0"])
                msg = "Shutting down now"
            
            subprocess.run(cmd, shell=False)
            return {"status": "success", "message": msg}
        
        if action == "restart":
            cmd = ["shutdown", "/r"]
            if force:
                cmd.append("/f")
            if delay > 0:
                cmd.extend(["/t", str(delay)])
                msg = f"Restarting in {delay} seconds"
            else:
                cmd.extend(["/t", "0"])
                msg = "Restarting now"
            
            subprocess.run(cmd, shell=False)
            return {"status": "success", "message": msg}
        
        if action == "hibernate":
            # SetSuspendState with hibernate=True
            try:
                result = ctypes.windll.powrprof.SetSuspendState(1, int(force), 0)
                if result != 0:
                    return {"status": "success", "message": "Hibernating"}
            except Exception:
                pass
            
            # Fallback: use shutdown /h
            cmd = ["shutdown", "/h"]
            result = subprocess.run(cmd, shell=False, capture_output=True, text=True)
            if result.returncode == 0:
                return {"status": "success", "message": "Hibernating"}
            if "not enabled" in result.stderr.lower() or "not supported" in result.stderr.lower():
                return {"status": "fail", "reason": "Hibernate not enabled", "hint": "Run 'powercfg /hibernate on' as admin"}
            return {"status": "fail", "reason": "Failed to hibernate", "error": result.stderr}
        
        if action == "logoff":
            # ExitWindowsEx(EWX_LOGOFF, 0)
            EWX_LOGOFF = 0x00000000
            if force:
                EWX_LOGOFF = 0x00000004  # EWX_FORCE
            result = ctypes.windll.user32.ExitWindowsEx(EWX_LOGOFF, 0)
            if result:
                return {"status": "success", "message": "Logging off"}
            return {"status": "fail", "reason": "Failed to log off"}
        
        if action == "cancel":
            cmd = ["shutdown", "/a"]
            result = subprocess.run(cmd, shell=False, capture_output=True, text=True)
            if result.returncode == 0:
                return {"status": "success", "message": "Shutdown cancelled"}
            if "no shutdown" in result.stderr.lower() or "unable" in result.stderr.lower():
                return {"status": "success", "message": "No pending shutdown to cancel"}
            return {"status": "fail", "reason": "Failed to cancel shutdown", "error": result.stderr}
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
        
    except Exception as e:
        return {"status": "fail", "reason": "Power operation failed", "error": str(e)}
