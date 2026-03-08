#!/usr/bin/env python3
"""
Terminal Tool - Execute system commands
"""

import subprocess
import platform
from subprocess import DEVNULL


class TerminalTool:
    """Execute terminal/shell commands with full system access"""
    
    @staticmethod
    def get_schema():
        """Return the tool schema for function calling"""
        return {
            "type": "function",
            "function": {
                "name": "execute_terminal_command",
                "description": "Execute a terminal/shell command on the system. Has full access to run any command. Use this to interact with the file system, run programs, install packages, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The command to execute (e.g., 'ls -la', 'python --version', 'npm install')"
                        },
                        "working_directory": {
                            "type": "string",
                            "description": "Optional working directory to run the command in. Defaults to current directory."
                        }
                    },
                    "required": ["command"]
                }
            }
        }
    
    @staticmethod
    def execute(arguments: dict) -> str:
        """
        Execute a terminal command
        
        Args:
            arguments: Dict with 'command' and optional 'working_directory'
        
        Returns:
            Command output or error message
        """
        command = arguments.get("command", "")
        working_dir = arguments.get("working_directory", None)
        
        if not command:
            return "Error: No command provided"
        
        try:
            # Determine shell based on platform
            is_windows = platform.system() == "Windows"
            
            # Check if command opens a GUI app (notepad, code, etc.)
            gui_apps = ['notepad', 'code', 'explorer', 'chrome', 'firefox', 'calc']
            is_gui_app = any(app in command.lower() for app in gui_apps)
            
            # On Windows, use Popen for GUI apps to run non-blocking
            if is_windows and is_gui_app:
                # Use Popen instead of run for non-blocking execution
                process = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=working_dir,
                    stdout=DEVNULL,
                    stderr=DEVNULL
                )
                return f"✓ Opened {command.split()[0]} (non-blocking)"
            
            # For regular commands, use run with timeout
            result = subprocess.run(
                command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout
            )
            
            # Combine stdout and stderr
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            
            # Check exit code
            if result.returncode != 0:
                if not output.strip():
                    return f"Error: Command failed with exit code {result.returncode}"
                return f"Error: Command failed with exit code {result.returncode}\n{output.strip()}"
            
            if not output.strip():
                output = f"Command executed successfully (exit code: {result.returncode})"
            
            return output.strip()
        
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds"
        except Exception as e:
            return f"Error executing command: {str(e)}"
