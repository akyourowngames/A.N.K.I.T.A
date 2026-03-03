"""
System health diagnostics for ANKITA - CPU, RAM, disk, temperature monitoring.
Uses LLM for intelligent health analysis and recommendations.
"""
import psutil
import platform
import subprocess
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from llm.client import LLMRuntime, call_chat_once


def _get_cpu_temp() -> str:
    """Get CPU temperature on Windows."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace 'root/wmi' | "
             "Select-Object -First 1 -ExpandProperty CurrentTemperature"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = int(result.stdout.strip())
            celsius = round((raw / 10) - 273.15, 1)
            return f"{celsius}°C"
    except:
        pass
    return "N/A"


def full_health_report(runtime: Optional[LLMRuntime] = None) -> Dict[str, Any]:
    """Generate comprehensive PC health report with LLM analysis."""
    try:
        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_freq = psutil.cpu_freq()
        cpu = {
            "usage_pct": cpu_percent,
            "cores_physical": psutil.cpu_count(logical=False),
            "cores_logical": psutil.cpu_count(logical=True),
            "freq_mhz": round(cpu_freq.current) if cpu_freq else "N/A",
            "temp": _get_cpu_temp()
        }
        
        # RAM
        ram = psutil.virtual_memory()
        memory = {
            "total_gb": round(ram.total / 1e9, 1),
            "used_gb": round(ram.used / 1e9, 1),
            "available_gb": round(ram.available / 1e9, 1),
            "percent": ram.percent
        }
        
        # Disk
        disks = []
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "drive": part.device,
                    "total_gb": round(usage.total / 1e9, 1),
                    "used_gb": round(usage.used / 1e9, 1),
                    "free_gb": round(usage.free / 1e9, 1),
                    "percent_used": usage.percent
                })
            except:
                pass
        
        # Uptime
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime_seconds = int((datetime.now() - boot_time).total_seconds())
        uptime = str(timedelta(seconds=uptime_seconds))
        
        # Network
        net_io = psutil.net_io_counters()
        network = {
            "bytes_sent_mb": round(net_io.bytes_sent / 1e6, 1),
            "bytes_recv_mb": round(net_io.bytes_recv / 1e6, 1)
        }
        
        report = {
            "ok": True,
            "cpu": cpu,
            "memory": memory,
            "disks": disks,
            "uptime": uptime,
            "network": network,
            "os": platform.platform(),
            "timestamp": datetime.now().isoformat()
        }
        
        # LLM-powered health analysis
        if runtime:
            try:
                analysis_prompt = f"""Analyze this PC health report and provide a brief assessment:
CPU: {cpu_percent}% usage, {cpu['temp']} temp
RAM: {memory['percent']}% used ({memory['used_gb']}/{memory['total_gb']} GB)
Disk: {disks[0]['percent_used']}% used on C: drive
Uptime: {uptime}

Reply with: STATUS (HEALTHY/WARNING/CRITICAL) and brief reason."""
                
                messages = [{"role": "user", "content": analysis_prompt}]
                response = call_chat_once(runtime, messages, tools=None, max_tokens=100)
                report["llm_analysis"] = response.get("content", "").strip()
            except:
                pass
        
        return report
    
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_top_processes(n: int = 5, sort_by: str = "cpu") -> Dict[str, Any]:
    """Get top N processes by CPU or RAM usage."""
    try:
        procs = []
        for p in psutil.process_iter(['name', 'cpu_percent', 'memory_info']):
            try:
                info = p.info
                procs.append({
                    "name": info['name'],
                    "cpu_pct": info.get('cpu_percent', 0) or 0,
                    "ram_mb": round(info['memory_info'].rss / 1e6, 1)
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Sort
        if sort_by == "ram":
            procs.sort(key=lambda x: x['ram_mb'], reverse=True)
        else:
            procs.sort(key=lambda x: x['cpu_pct'], reverse=True)
        
        return {"ok": True, "processes": procs[:n], "sort_by": sort_by}
    
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_disk_health() -> Dict[str, Any]:
    """Check disk health and space warnings."""
    try:
        warnings = []
        disks = []
        
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disk_info = {
                    "drive": part.device,
                    "percent_used": usage.percent,
                    "free_gb": round(usage.free / 1e9, 1)
                }
                disks.append(disk_info)
                
                if usage.percent > 90:
                    warnings.append(f"{part.device} is {usage.percent}% full (only {disk_info['free_gb']} GB free)")
                elif usage.percent > 80:
                    warnings.append(f"{part.device} is {usage.percent}% full")
            except:
                pass
        
        return {
            "ok": True,
            "disks": disks,
            "warnings": warnings,
            "status": "CRITICAL" if any(d['percent_used'] > 90 for d in disks) else "WARNING" if warnings else "HEALTHY"
        }
    
    except Exception as e:
        return {"ok": False, "error": str(e)}


def system_health(action: str, runtime: Optional[LLMRuntime] = None, **kwargs) -> Dict[str, Any]:
    """
    Main system health dispatcher with LLM integration.
    Actions: full_report, top_processes, disk_health
    """
    if action == "full_report":
        return full_health_report(runtime)
    
    elif action == "top_processes":
        n = kwargs.get("n", 5)
        sort_by = kwargs.get("sort_by", "cpu")
        return get_top_processes(n, sort_by)
    
    elif action == "disk_health":
        return check_disk_health()
    
    else:
        return {"ok": False, "error": f"Unknown system_health action: {action}"}
