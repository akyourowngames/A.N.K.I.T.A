"""
Application manager for ANKITA - full app lifecycle with LLM-powered fuzzy matching.
"""
import subprocess
import psutil
import difflib
import time
from typing import Optional, Dict, Any, List
from llm.client import LLMRuntime, call_chat_once


def list_running_apps() -> List[Dict[str, Any]]:
    """List all windows with their process name + CPU + RAM."""
    apps = []
    
    # Collect processes and start CPU measurement
    processes = []
    for p in psutil.process_iter(['pid', 'name', 'memory_info']):
        try:
            if p.info['memory_info'].rss > 10_000_000:  # > 10MB = real app
                p.cpu_percent(interval=None)  # Start measuring
                processes.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    # Wait for CPU measurement to accumulate (0.5 seconds for better accuracy)
    time.sleep(0.5)
    
    # Collect final data with CPU readings
    for p in processes:
        try:
            cpu_usage = p.cpu_percent(interval=None)
            memory_info = p.memory_info()
            
            apps.append({
                "pid": p.pid,
                "name": p.name(),
                "ram_mb": round(memory_info.rss / 1e6, 1),
                "cpu_pct": round(cpu_usage, 1)
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    return sorted(apps, key=lambda x: x['ram_mb'], reverse=True)[:20]


def find_process_by_name(fuzzy_name: str, runtime: Optional[LLMRuntime] = None) -> Optional[psutil.Process]:
    """
    Fuzzy match process name with LLM fallback for ambiguous cases.
    Handles 'chrome' → 'chrome.exe', 'vscode' → 'Code.exe', etc.
    """
    fuzzy_name_lower = fuzzy_name.lower()
    
    # Get all running processes
    procs = {}
    for p in psutil.process_iter(['name']):
        try:
            procs[p.name().lower()] = p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    # Exact match first
    if fuzzy_name_lower in procs:
        return procs[fuzzy_name_lower]
    
    # Try with .exe extension
    if f"{fuzzy_name_lower}.exe" in procs:
        return procs[f"{fuzzy_name_lower}.exe"]
    
    # Fuzzy match using difflib
    matches = difflib.get_close_matches(fuzzy_name_lower, procs.keys(), n=3, cutoff=0.6)
    
    if not matches:
        return None
    
    if len(matches) == 1:
        return procs[matches[0]]
    
    # Multiple matches - use LLM to disambiguate if available
    if runtime and len(matches) > 1:
        try:
            prompt = f"User wants to close '{fuzzy_name}'. Which process matches best? Options: {', '.join(matches)}. Reply with ONLY the exact process name."
            messages = [{"role": "user", "content": prompt}]
            response = call_chat_once(runtime, messages, tools=None, max_tokens=50)
            llm_choice = response.get("content", "").strip().lower()
            
            # Find the LLM's choice in our matches
            for match in matches:
                if match in llm_choice or llm_choice in match:
                    return procs[match]
        except:
            pass  # Fall back to first match
    
    # Default to first match
    return procs[matches[0]]


def close_app(name: str, force: bool = False, runtime: Optional[LLMRuntime] = None) -> Dict[str, Any]:
    """Close an app gracefully or forcefully."""
    proc = find_process_by_name(name, runtime)
    if not proc:
        return {"ok": False, "error": f"No app found matching '{name}'"}
    
    try:
        proc_name = proc.name()
        proc_pid = proc.pid
        
        if force:
            proc.kill()
        else:
            proc.terminate()
        
        # Wait for process to actually terminate
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            if not force:
                proc.kill()  # Force kill if graceful termination failed
        
        return {"ok": True, "closed": proc_name, "pid": proc_pid, "forced": force}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def restart_app(name: str, runtime: Optional[LLMRuntime] = None) -> Dict[str, Any]:
    """Restart an application."""
    proc = find_process_by_name(name, runtime)
    if not proc:
        return {"ok": False, "error": f"App '{name}' not found"}
    
    try:
        exe_path = proc.exe()
        proc_name = proc.name()
        
        # Kill the process
        proc.kill()
        proc.wait(timeout=3)
        
        # Restart it
        subprocess.Popen([exe_path], shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        return {"ok": True, "restarted": proc_name, "exe": exe_path}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_top_ram_hog() -> Dict[str, Any]:
    """Get the process using the most RAM."""
    apps = list_running_apps()
    if apps:
        return {"ok": True, "top_hog": apps[0]}
    return {"ok": False, "error": "No apps found"}


def app_manager(action: str, runtime: Optional[LLMRuntime] = None, **kwargs) -> Dict[str, Any]:
    """
    Main app manager dispatcher with LLM integration.
    Actions: list_running, close_app, restart_app, top_ram_hog
    """
    if action == "list_running":
        apps = list_running_apps()
        return {"ok": True, "apps": apps, "count": len(apps)}
    
    elif action == "close_app":
        name = kwargs.get("name", "")
        force = kwargs.get("force", False)
        return close_app(name, force, runtime)
    
    elif action == "restart_app":
        name = kwargs.get("name", "")
        return restart_app(name, runtime)
    
    elif action == "top_ram_hog":
        return get_top_ram_hog()
    
    else:
        return {"ok": False, "error": f"Unknown app_manager action: {action}"}
