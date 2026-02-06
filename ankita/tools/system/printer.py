"""
Printer Tool - Print documents and manage print queue.
"""
import subprocess
import os


def run(action: str = "status", file_path: str = None, **kwargs) -> dict:
    action = (action or "status").strip().lower()
    file_path = file_path or kwargs.get("path", "")
    
    try:
        if action in ("status", "queue", "list"):
            # Open print queue
            subprocess.Popen(["start", "ms-settings:printers"], shell=True)
            return {"status": "success", "message": "Opened Printers & Scanners settings"}
        
        if action == "print":
            if not file_path:
                return {"status": "fail", "reason": "No file specified to print"}
            
            if not os.path.exists(file_path):
                return {"status": "fail", "reason": f"File not found: {file_path}"}
            
            # Print using default application
            os.startfile(file_path, "print")
            return {"status": "success", "message": f"Sent {os.path.basename(file_path)} to printer"}
        
        if action == "settings":
            subprocess.Popen(["start", "ms-settings:printers"], shell=True)
            return {"status": "success", "message": "Opened Printer settings"}
        
        if action in ("cancel", "clear"):
            # Cancel all print jobs
            ps_script = "Get-PrintJob | Remove-PrintJob"
            try:
                subprocess.run(["powershell", "-Command", ps_script], capture_output=True, timeout=10)
                return {"status": "success", "message": "Cleared print queue"}
            except:
                return {"status": "fail", "reason": "Could not clear print queue"}
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
    except Exception as e:
        return {"status": "fail", "reason": str(e)}
