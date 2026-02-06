"""
Clipboard Tool - Read, write, and manage clipboard content.
Polished with better error handling and content preview.
"""


def run(action: str = "read", content: str | None = None, **kwargs) -> dict:
    """
    Manage clipboard operations.
    
    Actions:
        - read/get/show: Read current clipboard content
        - write/copy/set: Copy text to clipboard
        - clear/empty: Clear clipboard
    """
    action = (action or "read").strip().lower()
    
    # Normalize action aliases
    action_aliases = {
        "get": "read",
        "paste": "read",
        "show": "read",
        "status": "read",
        "copy": "write",
        "set": "write",
        "put": "write",
        "empty": "clear",
        "delete": "clear",
        "wipe": "clear",
    }
    action = action_aliases.get(action, action)
    
    # Try pyperclip first, fallback to win32clipboard
    use_pyperclip = False
    try:
        import pyperclip
        use_pyperclip = True
    except ImportError:
        pass
    
    if use_pyperclip:
        try:
            if action == "read":
                data = pyperclip.paste()
                if not data:
                    return {"status": "success", "message": "Clipboard is empty", "content": ""}
                # Truncate for display
                preview = data[:100] + "..." if len(data) > 100 else data
                return {
                    "status": "success", 
                    "message": f"Clipboard contains: {preview}",
                    "content": data,
                    "length": len(data)
                }
            
            if action == "write":
                if content is None:
                    return {"status": "fail", "reason": "No content provided to copy"}
                pyperclip.copy(str(content))
                return {"status": "success", "message": f"Copied {len(str(content))} characters to clipboard"}
            
            if action == "clear":
                pyperclip.copy("")
                return {"status": "success", "message": "Clipboard cleared"}
            
            return {"status": "fail", "reason": f"Unknown action: {action}"}
            
        except Exception as e:
            return {"status": "fail", "reason": "Clipboard operation failed", "error": str(e)}
    
    # Fallback to win32clipboard
    try:
        import win32clipboard
        
        if action == "read":
            try:
                win32clipboard.OpenClipboard()
                try:
                    data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                except TypeError:
                    try:
                        data = win32clipboard.GetClipboardData(win32clipboard.CF_TEXT)
                        if isinstance(data, bytes):
                            data = data.decode("utf-8", errors="ignore")
                    except:
                        data = ""
                win32clipboard.CloseClipboard()
                
                if not data:
                    return {"status": "success", "message": "Clipboard is empty", "content": ""}
                preview = data[:100] + "..." if len(data) > 100 else data
                return {
                    "status": "success", 
                    "message": f"Clipboard contains: {preview}",
                    "content": data,
                    "length": len(data)
                }
            except Exception as e:
                try:
                    win32clipboard.CloseClipboard()
                except:
                    pass
                return {"status": "fail", "reason": "Failed to read clipboard", "error": str(e)}
        
        if action == "write":
            if content is None:
                return {"status": "fail", "reason": "No content provided to copy"}
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(str(content), win32clipboard.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                return {"status": "success", "message": f"Copied {len(str(content))} characters to clipboard"}
            except Exception as e:
                try:
                    win32clipboard.CloseClipboard()
                except:
                    pass
                return {"status": "fail", "reason": "Failed to copy to clipboard", "error": str(e)}
        
        if action == "clear":
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.CloseClipboard()
                return {"status": "success", "message": "Clipboard cleared"}
            except Exception as e:
                try:
                    win32clipboard.CloseClipboard()
                except:
                    pass
                return {"status": "fail", "reason": "Failed to clear clipboard", "error": str(e)}
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
        
    except ImportError:
        return {
            "status": "fail",
            "reason": "Missing dependencies. Install: pip install pyperclip or pywin32"
        }
