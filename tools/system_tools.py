from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any


def get_system_info(params: dict[str, Any]) -> dict[str, Any]:
    include_env_keys = bool(params.get("include_env_keys"))
    result: dict[str, Any] = {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "architecture": architecture_label(platform.machine()),
        "processor": platform.processor(),
        "cwd": str(Path.cwd()),
    }
    if include_env_keys:
        result["env_keys"] = sorted(os.environ.keys())
    return result


def get_pc_status(params: dict[str, Any]) -> dict[str, Any]:
    cwd = Path.cwd()
    usage = shutil.disk_usage(cwd.anchor or cwd)
    memory = memory_status()
    result: dict[str, Any] = {
        "os": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "architecture": architecture_label(platform.machine()),
        "reported_machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_cores": os.cpu_count(),
        "cwd": str(cwd),
        "disk_total_gb": bytes_to_gb(usage.total),
        "disk_free_gb": bytes_to_gb(usage.free),
        "disk_used_gb": bytes_to_gb(usage.used),
    }
    result.update(memory)
    result["summary"] = pc_status_summary(result)
    return result


def architecture_label(machine: str) -> str:
    text = machine.strip()
    if text.upper() == "AMD64":
        return "x64"
    return text or "unknown"


def bytes_to_gb(value: int) -> float:
    return round(value / (1024 ** 3), 2)


def memory_status() -> dict[str, Any]:
    if platform.system().lower() != "windows":
        return {}

    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {
                "memory_load_percent": int(status.memory_load),
                "memory_total_gb": bytes_to_gb(status.total_physical),
                "memory_available_gb": bytes_to_gb(status.available_physical),
            }
    except Exception:
        return {}
    return {}


def pc_status_summary(result: dict[str, Any]) -> str:
    lines = [
        f"OS: {result['system']} {result['release']}",
        f"Architecture: {result['architecture']}",
        f"CPU cores: {result['cpu_cores']}",
        f"Disk: {result['disk_free_gb']} GB free of {result['disk_total_gb']} GB",
        f"Workspace: {result['cwd']}",
    ]
    if "memory_total_gb" in result:
        lines.insert(3, f"Memory: {result['memory_available_gb']} GB free of {result['memory_total_gb']} GB ({result['memory_load_percent']}% used)")
    processor = str(result.get("processor", "unknown"))
    if processor and processor != "unknown":
        lines.insert(3, f"Processor: {processor}")
    return "\n".join(lines)
