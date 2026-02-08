"""
System Sentinel - Proactive system health and resource monitoring.
"""
import psutil
import platform
from datetime import datetime
import os


def _get_size(bytes, suffix="B"):
    """Scale bytes to its proper format (e.g, GB, MB, KB, etc)"""
    factor = 1024
    for unit in ["", "K", "M", "G", "T", "P"]:
        if bytes < factor:
            return f"{bytes:.2f}{unit}{suffix}"
        bytes /= factor


def run(action: str = "health", **kwargs) -> dict:
    """
    Monitor and report on system health and resources.
    
    Actions:
        - health: Comprehensive system health check
        - resources: Real-time CPU/RAM/Disk usage
        - battery: Detailed battery health (for laptops)
        - network: Network speed and usage
        - guardian: Scan for high-resource processes
    """
    action = (action or "health").strip().lower()
    
    try:
        # === System Health Check ===
        if action == "health":
            cpu_usage = psutil.cpu_percent(interval=0.5)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            battery = psutil.sensors_battery()
            
            status = "Optimal"
            if cpu_usage > 85 or memory.percent > 90:
                status = "Warning: High Resource Usage"
            
            report = {
                "system": platform.system(),
                "node": platform.node(),
                "status": status,
                "cpu": f"{cpu_usage}%",
                "memory": f"{memory.percent}% ({_get_size(memory.used)}/{_get_size(memory.total)})",
                "disk": f"{disk.percent}% ({_get_size(disk.free)} free)",
            }
            
            if battery:
                report["battery"] = f"{battery.percent}% ({'Charging' if battery.power_plugged else 'Discharging'})"
            
            message = f"System Health: {status} | CPU: {report['cpu']} | RAM: {report['memory']}"
            return {"status": "success", "message": message, "report": report}

        # === Guardian Mode (Process Policing) ===
        if action == "guardian":
            heavy_procs = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    if proc.info['cpu_percent'] > 50 or proc.info['memory_info'].rss > 1024 * 1024 * 500: # >50% CPU or >500MB RAM
                        heavy_procs.append({
                            "name": proc.info['name'],
                            "pid": proc.info['pid'],
                            "cpu": f"{proc.info['cpu_percent']}%",
                            "ram": _get_size(proc.info['memory_info'].rss)
                        })
                except:
                    pass
            
            if heavy_procs:
                procs_str = ", ".join([f"{p['name']} ({p['cpu']})" for p in heavy_procs])
                return {"status": "warning", "message": f"Guardian Alert: High resource processes detected: {procs_str}", "heavy_processes": heavy_procs}
            return {"status": "success", "message": "Guardian: All processes within normal limits."}

        return {"status": "fail", "reason": f"Unknown sentinel action: {action}"}

    except Exception as e:
        return {"status": "fail", "reason": f"Sentinel error: {str(e)}"}
