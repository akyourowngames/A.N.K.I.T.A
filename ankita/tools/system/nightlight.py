"""
Night Light Tool - Control Windows Night Light.
"""
import subprocess


def _run_powershell(script: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True, text=True, shell=False, timeout=10
        )
        return result.returncode == 0, (result.stdout or "") + (result.stderr or "")
    except Exception as e:
        return False, str(e)


def run(action: str = "status", **kwargs) -> dict:
    action = (action or "status").strip().lower()
    action_map = {"enable": "on", "disable": "off", "check": "status"}
    action = action_map.get(action, action)
    
    try:
        if action == "status":
            subprocess.Popen(["start", "ms-settings:nightlight"], shell=True)
            return {"status": "success", "message": "Opened Night Light settings"}
        
        if action in ("on", "off", "toggle"):
            subprocess.Popen(["start", "ms-settings:nightlight"], shell=True)
            return {
                "status": "partial",
                "message": f"Opened Night Light settings - please toggle manually"
            }
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
    except Exception as e:
        return {"status": "fail", "reason": str(e)}
