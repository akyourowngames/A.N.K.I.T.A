"""
Airplane Mode Tool - Toggle Windows Airplane Mode.
"""
import subprocess


def run(action: str = "status", **kwargs) -> dict:
    action = (action or "status").strip().lower()
    action_map = {"enable": "on", "disable": "off", "check": "status"}
    action = action_map.get(action, action)
    
    try:
        if action in ("status", "on", "off", "toggle"):
            subprocess.Popen(["start", "ms-settings:network-airplanemode"], shell=True)
            return {
                "status": "partial",
                "message": "Opened Airplane Mode settings - please toggle manually"
            }
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
    except Exception as e:
        return {"status": "fail", "reason": str(e)}
