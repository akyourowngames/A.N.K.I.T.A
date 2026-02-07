"""
Files Tool - Quick access to common folders and recent files
"""
import os
import subprocess
import glob
from pathlib import Path


def run(action: str = "open", path: str = "", **kwargs):
    """
    Files tool
    
    Args:
        action: open, downloads, documents, desktop, recent, pictures
        path: Custom path to open (for open action)
    """
    action = action.lower().strip()
    
    user_home = Path.home()
    
    try:
        if action == "open":
            if not path:
                # Open file explorer at home
                path = str(user_home)
            
            if os.path.exists(path):
                subprocess.Popen(f'explorer "{path}"')
                return {
                    "status": "success",
                    "message": f"Opened {path}"
                }
            else:
                return {"status": "fail", "reason": "path_not_found"}
        
        elif action == "downloads":
            downloads = user_home / "Downloads"
            if downloads.exists():
                subprocess.Popen(f'explorer "{downloads}"')
                return {
                    "status": "success",
                    "message": f"Opened Downloads folder"
                }
            else:
                return {"status": "fail", "reason": "folder_not_found"}
        
        elif action == "documents":
            documents = user_home / "Documents"
            if documents.exists():
                subprocess.Popen(f'explorer "{documents}"')
                return {
                    "status": "success",
                    "message": f"Opened Documents folder"
                }
            else:
                return {"status": "fail", "reason": "folder_not_found"}
        
        elif action == "desktop":
            desktop = user_home / "Desktop"
            if desktop.exists():
                subprocess.Popen(f'explorer "{desktop}"')
                return {
                    "status": "success",
                    "message": f"Opened Desktop"
                }
            else:
                return {"status": "fail", "reason": "folder_not_found"}
        
        elif action == "pictures":
            pictures = user_home / "Pictures"
            if pictures.exists():
                subprocess.Popen(f'explorer "{pictures}"')
                return {
                    "status": "success",
                    "message": f"Opened Pictures folder"
                }
            else:
                return {"status": "fail", "reason": "folder_not_found"}
        
        elif action == "recent":
            # Show recent files (Windows Recent folder)
            recent_folder = user_home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Recent"
            if recent_folder.exists():
                subprocess.Popen(f'explorer "{recent_folder}"')
                return {
                    "status": "success",
                    "message": f"Opened recent files"
                }
            else:
                return {"status": "fail", "reason": "folder_not_found"}
        
        else:
            return {"status": "fail", "reason": "invalid_action"}
    
    except Exception as e:
        return {"status": "error", "error": str(e)}
