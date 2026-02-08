"""
Git Ghost - Auto-detects git commits and drafts social media updates.
"""
import subprocess
import os
import json
from datetime import datetime
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent.parent / "data" / "git_ghost"
STATE_FILE = DATA_DIR / "state.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _get_last_commit(repo_path):
    """Get the latest commit hash and message."""
    try:
        hash = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_path, text=True).strip()
        msg = subprocess.check_output(["git", "log", "-1", "--pretty=format:%s"], cwd=repo_path, text=True).strip()
        author = subprocess.check_output(["git", "log", "-1", "--pretty=format:%an"], cwd=repo_path, text=True).strip()
        return {"hash": hash, "message": msg, "author": author}
    except Exception as e:
        print(f"[GitGhost] Error getting commit: {e}")
        return None


def _get_diff_summary(repo_path):
    """Get a short summary of changed files."""
    try:
        return subprocess.check_output(["git", "diff", "--stat", "HEAD~1", "HEAD"], cwd=repo_path, text=True).strip()
    except:
        return ""


def run(action: str = "check", repo_path: str = None, **kwargs) -> dict:
    """
    Manage the Ghost Committer.
    
    Actions:
        - check: Check for new commits and trigger social post
        - status: Show last posted commit
    """
    action = (action or "check").strip().lower()
    # Default to current project if not provided
    if not repo_path:
        repo_path = r"C:\Users\anime\3D Objects\New folder\A.N.K.I.T.A"

    if action == "check":
        current = _get_last_commit(repo_path)
        if not current:
            return {"status": "fail", "reason": "Not a git repo or git error"}

        # Load state
        state = {"last_posted_hash": ""}
        if STATE_FILE.exists():
            with open(STATE_FILE, "r") as f:
                state = json.load(f)

        if current["hash"] == state["last_posted_hash"]:
            return {"status": "success", "message": "No new commits to post."}

        # NEW COMMIT DETECTED!
        print(f"[GitGhost] New commit detected: {current['message']}")
        
        diff = _get_diff_summary(repo_path)
        
        # 1. Generate Cool Caption
        # In a full run, we would call the LLM here.
        # For this tool, we'll return the draft and let the agent/pulse handle the rest.
        
        caption = f"[GHOST COMMIT] New Update Locked In!\n\nTask: {current['message']}\n\nFiles changed:\n{diff}\n\n#DevLife #OpenClaw #AI #GitHub"
        
        # 2. Save State
        state["last_posted_hash"] = current["hash"]
        state["last_posted_at"] = datetime.now().isoformat()
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

        return {
            "status": "success",
            "message": "New commit detected and drafted",
            "commit": current,
            "draft_caption": caption
        }

    if action == "status":
        if STATE_FILE.exists():
            with open(STATE_FILE, "r") as f:
                return {"status": "success", "state": json.load(f)}
        return {"status": "success", "message": "No history found."}

    return {"status": "fail", "reason": f"Unknown action: {action}"}
