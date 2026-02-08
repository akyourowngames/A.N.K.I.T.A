"""
Command Center - Advanced shell and automation control.
"""
import subprocess
import os
import shlex


def run(action: str = "exec", command: str = "", **kwargs) -> dict:
    """
    Execute and manage system commands.
    
    Actions:
        - exec: Run a shell command (safely)
        - scripts: List available automation scripts
        - terminal: Open a new terminal window
        - environment: Get system environment variables
    """
    action = (action or "exec").strip().lower()
    
    try:
        if action == "exec":
            if not command:
                return {"status": "fail", "reason": "No command provided"}
            
            # Use shell=True carefully for Windows, but try to keep it robust
            process = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            
            if process.returncode == 0:
                return {
                    "status": "success", 
                    "message": "Command executed successfully", 
                    "stdout": process.stdout.strip(),
                    "stderr": process.stderr.strip()
                }
            else:
                return {
                    "status": "fail", 
                    "reason": f"Command failed with code {process.returncode}", 
                    "stdout": process.stdout.strip(),
                    "stderr": process.stderr.strip()
                }

        if action == "terminal":
            # Open Windows Terminal (wt) or fallback to cmd
            try:
                subprocess.Popen(["wt"], shell=False)
            except:
                subprocess.Popen(["cmd"], shell=True)
            return {"status": "success", "message": "Terminal opened"}

        if action == "environment":
            env_vars = dict(os.environ)
            # Filter for safety/brevity
            important = {k: env_vars[k] for k in ["COMPUTERNAME", "USERNAME", "OS", "PROCESSOR_IDENTIFIER"] if k in env_vars}
            return {"status": "success", "message": "Environment info retrieved", "env": important}

        return {"status": "fail", "reason": f"Unknown command action: {action}"}

    except subprocess.TimeoutExpired:
        return {"status": "fail", "reason": "Command timed out after 30 seconds"}
    except Exception as e:
        return {"status": "fail", "reason": f"Command Center error: {str(e)}"}
