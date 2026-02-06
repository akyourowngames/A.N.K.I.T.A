"""
Display Tool - Control display settings (rotation, extend, etc.)
"""
import subprocess
import ctypes


def run(action: str = "status", **kwargs) -> dict:
    action = (action or "status").strip().lower()
    
    try:
        if action == "status":
            subprocess.Popen(["start", "ms-settings:display"], shell=True)
            return {"status": "success", "message": "Opened Display settings"}
        
        if action in ("rotate", "rotation"):
            direction = kwargs.get("direction", "normal").lower()
            # Display rotation values: 0=normal, 1=90, 2=180, 3=270
            rotation_map = {"normal": 0, "90": 1, "180": 2, "270": 3, "left": 3, "right": 1}
            
            if direction in rotation_map:
                # Use display settings
                subprocess.Popen(["start", "ms-settings:display"], shell=True)
                return {"status": "partial", "message": f"Opened display settings - rotate to {direction}"}
            return {"status": "fail", "reason": f"Unknown rotation: {direction}"}
        
        if action == "extend":
            # Win+P for projection, then select extend
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)  # Win down
            ctypes.windll.user32.keybd_event(0x50, 0, 0, 0)  # P down
            ctypes.windll.user32.keybd_event(0x50, 0, 2, 0)  # P up
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)  # Win up
            return {"status": "success", "message": "Opened projection menu (Win+P)"}
        
        if action == "duplicate":
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x50, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x50, 0, 2, 0)
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)
            return {"status": "success", "message": "Opened projection menu (Win+P)"}
        
        if action == "projector" or action == "second":
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x50, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x50, 0, 2, 0)
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)
            return {"status": "success", "message": "Opened projection menu (Win+P)"}
        
        if action == "settings":
            subprocess.Popen(["start", "ms-settings:display"], shell=True)
            return {"status": "success", "message": "Opened Display settings"}
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
    except Exception as e:
        return {"status": "fail", "reason": str(e)}
