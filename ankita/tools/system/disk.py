"""
Disk Tool - Get disk space and storage information.
"""
import shutil
import os


def _format_size(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def run(action: str = "status", drive: str = None, **kwargs) -> dict:
    action = (action or "status").strip().lower()
    drive = drive or kwargs.get("path", "C:")
    
    # Ensure drive has proper format
    if len(drive) == 1:
        drive = f"{drive}:"
    if not drive.endswith(":"):
        drive = f"{drive}:"
    
    try:
        if action in ("status", "info", "space", "check"):
            # Check if we should get all drives or specific
            if drive.upper() == "ALL:":
                drives_info = []
                for letter in "CDEFGHIJ":
                    drive_path = f"{letter}:\\"
                    if os.path.exists(drive_path):
                        try:
                            total, used, free = shutil.disk_usage(drive_path)
                            percent_used = (used / total) * 100
                            drives_info.append({
                                "drive": f"{letter}:",
                                "total": _format_size(total),
                                "used": _format_size(used),
                                "free": _format_size(free),
                                "percent_used": round(percent_used, 1)
                            })
                        except:
                            pass
                
                if drives_info:
                    summary = ", ".join([f"{d['drive']} {d['free']} free" for d in drives_info])
                    return {
                        "status": "success",
                        "message": summary,
                        "drives": drives_info
                    }
                return {"status": "fail", "reason": "Could not get disk info"}
            
            # Single drive
            drive_path = f"{drive}\\"
            if not os.path.exists(drive_path):
                return {"status": "fail", "reason": f"Drive {drive} not found"}
            
            total, used, free = shutil.disk_usage(drive_path)
            percent_used = (used / total) * 100
            percent_free = 100 - percent_used
            
            message = f"{drive} has {_format_size(free)} free of {_format_size(total)} ({percent_free:.1f}% free)"
            
            return {
                "status": "success",
                "message": message,
                "drive": drive,
                "total": total,
                "used": used,
                "free": free,
                "total_formatted": _format_size(total),
                "used_formatted": _format_size(used),
                "free_formatted": _format_size(free),
                "percent_used": round(percent_used, 1),
                "percent_free": round(percent_free, 1)
            }
        
        if action == "cleanup":
            # Open Disk Cleanup
            import subprocess
            subprocess.Popen(["cleanmgr", "/d", drive[0]], shell=False)
            return {"status": "success", "message": f"Opened Disk Cleanup for {drive}"}
        
        if action == "settings":
            import subprocess
            subprocess.Popen(["start", "ms-settings:storagesense"], shell=True)
            return {"status": "success", "message": "Opened Storage settings"}
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
    except Exception as e:
        return {"status": "fail", "reason": str(e)}
