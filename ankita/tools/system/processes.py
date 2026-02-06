"""
Process Management Tool - View and kill processes.
"""
import subprocess
import psutil


def _format_size(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def run(action: str = "status", name: str = None, **kwargs) -> dict:
    action = (action or "status").strip().lower()
    name = name or kwargs.get("process", "") or kwargs.get("app", "")
    
    try:
        if action in ("status", "info", "top", "cpu", "memory"):
            # Get top processes by CPU/memory
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    pinfo = proc.info
                    processes.append({
                        "pid": pinfo['pid'],
                        "name": pinfo['name'],
                        "cpu": pinfo['cpu_percent'] or 0,
                        "memory": pinfo['memory_info'].rss if pinfo['memory_info'] else 0
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Sort by CPU for 'cpu' action, memory for 'memory' action
            if action == "memory":
                processes.sort(key=lambda x: x['memory'], reverse=True)
                top_procs = processes[:5]
                lines = [f"{p['name']}: {_format_size(p['memory'])}" for p in top_procs]
                message = "Top memory: " + ", ".join(lines)
            else:
                # Give processes a moment to calculate CPU
                import time
                time.sleep(0.1)
                for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                    try:
                        for p in processes:
                            if p['pid'] == proc.pid:
                                p['cpu'] = proc.cpu_percent()
                    except:
                        pass
                
                processes.sort(key=lambda x: x['cpu'], reverse=True)
                top_procs = processes[:5]
                lines = [f"{p['name']}: {p['cpu']:.1f}%" for p in top_procs]
                message = "Top CPU: " + ", ".join(lines)
            
            return {
                "status": "success",
                "message": message,
                "processes": top_procs
            }
        
        if action in ("kill", "end", "terminate", "stop"):
            if not name:
                return {"status": "fail", "reason": "No process name specified"}
            
            name_lower = name.lower()
            killed = 0
            
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if name_lower in proc.info['name'].lower():
                        proc.kill()
                        killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            if killed > 0:
                return {"status": "success", "message": f"Killed {killed} process(es) matching '{name}'"}
            return {"status": "fail", "reason": f"No process found matching '{name}'"}
        
        if action in ("find", "search"):
            if not name:
                return {"status": "fail", "reason": "No process name specified"}
            
            name_lower = name.lower()
            found = []
            
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    if name_lower in proc.info['name'].lower():
                        found.append({
                            "pid": proc.info['pid'],
                            "name": proc.info['name'],
                            "memory": _format_size(proc.info['memory_info'].rss)
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            if found:
                lines = [f"{p['name']} (PID: {p['pid']}, {p['memory']})" for p in found[:5]]
                return {"status": "success", "message": "Found: " + ", ".join(lines), "processes": found}
            return {"status": "success", "message": f"No processes found matching '{name}'", "processes": []}
        
        if action in ("manager", "taskmgr", "open"):
            subprocess.Popen(["taskmgr"], shell=False)
            return {"status": "success", "message": "Opened Task Manager"}
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
    except Exception as e:
        return {"status": "fail", "reason": str(e)}
