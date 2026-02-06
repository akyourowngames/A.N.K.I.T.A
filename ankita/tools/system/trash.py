"""
Recycle Bin (Trash) Tool - Manage Windows Recycle Bin.
"""
import subprocess
import ctypes
from ctypes import wintypes
import os


def _get_recycle_bin_size() -> tuple[int, int]:
    """Get recycle bin item count and size in bytes."""
    try:
        # Use Shell32 to query recycle bin
        shell32 = ctypes.windll.shell32
        
        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong),
            ]
        
        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
        
        result = shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        
        if result == 0:
            return info.i64NumItems, info.i64Size
    except:
        pass
    return 0, 0


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


def run(action: str = "status", **kwargs) -> dict:
    action = (action or "status").strip().lower()
    action_map = {"check": "status", "info": "status", "clear": "empty", "clean": "empty"}
    action = action_map.get(action, action)
    
    try:
        if action == "status":
            items, size = _get_recycle_bin_size()
            size_str = _format_size(size)
            
            if items == 0:
                return {"status": "success", "message": "Recycle Bin is empty", "items": 0, "size": 0}
            
            return {
                "status": "success",
                "message": f"Recycle Bin: {items} item(s), {size_str}",
                "items": items,
                "size": size,
                "size_formatted": size_str
            }
        
        if action == "empty":
            items, _ = _get_recycle_bin_size()
            if items == 0:
                return {"status": "success", "message": "Recycle Bin is already empty"}
            
            # Empty recycle bin using Shell32
            # Flags: SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND = 0x07
            shell32 = ctypes.windll.shell32
            result = shell32.SHEmptyRecycleBinW(None, None, 0x07)
            
            if result == 0:
                return {"status": "success", "message": f"Emptied Recycle Bin ({items} items deleted)"}
            else:
                return {"status": "fail", "reason": f"Failed to empty (error code: {result})"}
        
        if action == "open":
            os.startfile("shell:RecycleBinFolder")
            return {"status": "success", "message": "Opened Recycle Bin"}
        
        if action == "restore":
            # Open recycle bin to allow manual restore
            os.startfile("shell:RecycleBinFolder")
            return {
                "status": "partial",
                "message": "Opened Recycle Bin - select items to restore"
            }
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
    except Exception as e:
        return {"status": "fail", "reason": str(e)}
