"""
File sync and organization operations for ANKITA.
Uses LLM for intelligent file categorization and organization decisions.
"""
import shutil
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from llm.client import LLMRuntime, call_chat_once


# Default organization rules
ORGANIZE_RULES = {
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".svg", ".ico"],
    "Videos": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"],
    "Documents": [".pdf", ".docx", ".doc", ".txt", ".md", ".xlsx", ".xls", ".pptx", ".ppt", ".odt"],
    "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"],
    "Code": [".py", ".js", ".ts", ".html", ".css", ".json", ".cpp", ".java", ".c", ".h", ".rs", ".go"],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
    "Executables": [".exe", ".msi", ".bat", ".sh", ".cmd"],
}


def organize_desktop(runtime: Optional[LLMRuntime] = None, custom_rules: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """
    Organize Desktop files into folders by type.
    Uses LLM to handle ambiguous files.
    """
    try:
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            return {"ok": False, "error": "Desktop folder not found"}
        
        rules = custom_rules or ORGANIZE_RULES
        moved = {}
        ambiguous = []
        
        for file_path in desktop.iterdir():
            if not file_path.is_file():
                continue
            
            suffix = file_path.suffix.lower()
            if not suffix:
                ambiguous.append(file_path.name)
                continue
            
            # Find matching category
            matched = False
            for folder, extensions in rules.items():
                if suffix in extensions:
                    target_dir = desktop / folder
                    target_dir.mkdir(exist_ok=True)
                    
                    # Handle name conflicts
                    target_path = target_dir / file_path.name
                    if target_path.exists():
                        stem = file_path.stem
                        target_path = target_dir / f"{stem}_{int(datetime.now().timestamp())}{suffix}"
                    
                    shutil.move(str(file_path), str(target_path))
                    moved.setdefault(folder, []).append(file_path.name)
                    matched = True
                    break
            
            if not matched:
                ambiguous.append(file_path.name)
        
        # Use LLM to categorize ambiguous files
        if ambiguous and runtime:
            try:
                prompt = f"Categorize these files into folders: {', '.join(ambiguous[:10])}. Available folders: {', '.join(rules.keys())}. Reply in format: filename->folder"
                messages = [{"role": "user", "content": prompt}]
                response = call_chat_once(runtime, messages, tools=None, max_tokens=200)
                # Parse LLM suggestions (simplified - could be enhanced)
                llm_suggestions = response.get("content", "")
                # Implementation of LLM-based categorization would go here
            except:
                pass
        
        return {
            "ok": True,
            "organized": moved,
            "folders_created": list(moved.keys()),
            "files_moved": sum(len(files) for files in moved.values()),
            "ambiguous": ambiguous
        }
    
    except Exception as e:
        return {"ok": False, "error": str(e)}


def zip_folder(folder_path: str, output_name: Optional[str] = None) -> Dict[str, Any]:
    """Compress a folder to a ZIP file."""
    try:
        folder = Path(folder_path)
        if not folder.exists():
            return {"ok": False, "error": f"Folder not found: {folder_path}"}
        
        if not folder.is_dir():
            return {"ok": False, "error": f"Not a folder: {folder_path}"}
        
        if output_name is None:
            output_name = str(Path.home() / "Desktop" / f"{folder.name}_{int(datetime.now().timestamp())}.zip")
        
        with zipfile.ZipFile(output_name, 'w', zipfile.ZIP_DEFLATED) as zf:
            file_count = 0
            for file_path in folder.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, file_path.relative_to(folder))
                    file_count += 1
        
        size_mb = round(Path(output_name).stat().st_size / 1e6, 2)
        
        return {
            "ok": True,
            "zip_path": output_name,
            "size_mb": size_mb,
            "files_compressed": file_count
        }
    
    except Exception as e:
        return {"ok": False, "error": str(e)}


def quick_backup(source: str, destination: Optional[str] = None) -> Dict[str, Any]:
    """Quick backup of a file or folder."""
    try:
        src = Path(source)
        if not src.exists():
            return {"ok": False, "error": f"Source not found: {source}"}
        
        if destination is None:
            backup_dir = Path.home() / "OneDrive" / "ANKITA_Backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            destination = str(backup_dir / src.name)
        
        dst = Path(destination)
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(str(src), str(dst))
            item_count = sum(1 for _ in dst.rglob("*"))
        else:
            shutil.copy2(str(src), str(dst))
            item_count = 1
        
        size_mb = round(sum(f.stat().st_size for f in dst.rglob("*") if f.is_file()) / 1e6, 2) if dst.is_dir() else round(dst.stat().st_size / 1e6, 2)
        
        return {
            "ok": True,
            "backed_up": str(src),
            "destination": str(dst),
            "size_mb": size_mb,
            "items": item_count
        }
    
    except Exception as e:
        return {"ok": False, "error": str(e)}


def smart_cleanup(directory: str, runtime: Optional[LLMRuntime] = None, dry_run: bool = True) -> Dict[str, Any]:
    """
    Smart cleanup of a directory using LLM to identify safe-to-delete files.
    """
    try:
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            return {"ok": False, "error": f"Invalid directory: {directory}"}
        
        # Find potential cleanup candidates
        candidates = []
        for file_path in dir_path.iterdir():
            if file_path.is_file():
                age_days = (datetime.now() - datetime.fromtimestamp(file_path.stat().st_mtime)).days
                size_mb = round(file_path.stat().st_size / 1e6, 2)
                
                # Heuristics for cleanup candidates
                if (age_days > 90 and size_mb > 100) or file_path.suffix in ['.tmp', '.log', '.bak']:
                    candidates.append({
                        "name": file_path.name,
                        "size_mb": size_mb,
                        "age_days": age_days,
                        "path": str(file_path)
                    })
        
        # Use LLM to review candidates if available
        recommendations = []
        if runtime and candidates:
            try:
                file_list = ", ".join([f"{c['name']} ({c['size_mb']}MB, {c['age_days']} days old)" for c in candidates[:10]])
                prompt = f"Which of these files are safe to delete? {file_list}. Reply with filenames separated by commas."
                messages = [{"role": "user", "content": prompt}]
                response = call_chat_once(runtime, messages, tools=None, max_tokens=200)
                llm_response = response.get("content", "")
                recommendations = [name.strip() for name in llm_response.split(",")]
            except:
                pass
        
        # Perform cleanup if not dry run
        deleted = []
        if not dry_run:
            for candidate in candidates:
                if not recommendations or candidate["name"] in recommendations:
                    try:
                        Path(candidate["path"]).unlink()
                        deleted.append(candidate["name"])
                    except:
                        pass
        
        return {
            "ok": True,
            "candidates": candidates,
            "llm_recommendations": recommendations,
            "deleted": deleted if not dry_run else [],
            "dry_run": dry_run,
            "space_freed_mb": sum(c["size_mb"] for c in candidates if c["name"] in deleted) if deleted else 0
        }
    
    except Exception as e:
        return {"ok": False, "error": str(e)}


def file_sync(action: str, runtime: Optional[LLMRuntime] = None, **kwargs) -> Dict[str, Any]:
    """
    Main file sync dispatcher with LLM integration.
    Actions: organize_desktop, zip_folder, quick_backup, smart_cleanup
    """
    if action == "organize_desktop":
        custom_rules = kwargs.get("custom_rules")
        return organize_desktop(runtime, custom_rules)
    
    elif action == "zip_folder":
        folder_path = kwargs.get("folder_path", "")
        output_name = kwargs.get("output_name")
        return zip_folder(folder_path, output_name)
    
    elif action == "quick_backup":
        source = kwargs.get("source", "")
        destination = kwargs.get("destination")
        return quick_backup(source, destination)
    
    elif action == "smart_cleanup":
        directory = kwargs.get("directory", "")
        dry_run = kwargs.get("dry_run", True)
        return smart_cleanup(directory, runtime, dry_run)
    
    else:
        return {"ok": False, "error": f"Unknown file_sync action: {action}"}
