"""
Autonomous Operations Engine for A.N.K.I.T.A

Inspired by OpenClaw's system.run philosophy: the agent has FULL access to the host
system and can install, configure, build, and execute anything autonomously.

Key capabilities:
- Tool auto-discovery and installation
- Script generation and execution
- Persistent shell sessions with environment inheritance
- Multi-step task pipelines
- Self-healing execution loops
- Package manager intelligence across ecosystems
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# TOOL DISCOVERY — detect what's installed and what's available
# ─────────────────────────────────────────────────────────────────────────────

# Package manager detection
_PACKAGE_MANAGERS = {
    "winget": {"check": "winget --version", "install": "winget install {pkg} --accept-package-agreements --accept-source-agreements"},
    "choco": {"check": "choco --version", "install": "choco install {pkg} -y"},
    "scoop": {"check": "scoop --version", "install": "scoop install {pkg}"},
    "pip": {"check": "pip --version", "install": "pip install {pkg}"},
    "pip3": {"check": "pip3 --version", "install": "pip3 install {pkg}"},
    "npm": {"check": "npm --version", "install": "npm install -g {pkg}"},
    "cargo": {"check": "cargo --version", "install": "cargo install {pkg}"},
    "go": {"check": "go version", "install": "go install {pkg}@latest"},
}

# Well-known CLI tool → package manager mappings
_TOOL_INSTALL_MAP = {
    # Dev tools
    "git": {"winget": "Git.Git", "choco": "git", "scoop": "git"},
    "node": {"winget": "OpenJS.NodeJS.LTS", "choco": "nodejs-lts", "scoop": "nodejs-lts"},
    "nodejs": {"winget": "OpenJS.NodeJS.LTS", "choco": "nodejs-lts", "scoop": "nodejs-lts"},
    "python": {"winget": "Python.Python.3.12", "choco": "python3", "scoop": "python"},
    "python3": {"winget": "Python.Python.3.12", "choco": "python3", "scoop": "python"},
    "rust": {"winget": "Rustlang.Rustup", "choco": "rustup.install"},
    "go": {"winget": "GoLang.Go", "choco": "golang", "scoop": "go"},
    "java": {"winget": "Oracle.JDK.21", "choco": "openjdk"},
    "docker": {"winget": "Docker.DockerDesktop", "choco": "docker-desktop"},

    # CLI utilities
    "curl": {"winget": "cURL.cURL", "choco": "curl", "scoop": "curl"},
    "wget": {"winget": "JernejSimoncic.Wget", "choco": "wget", "scoop": "wget"},
    "jq": {"winget": "jqlang.jq", "choco": "jq", "scoop": "jq"},
    "ripgrep": {"winget": "BurntSushi.ripgrep.MSVC", "choco": "ripgrep", "scoop": "ripgrep", "cargo": "ripgrep"},
    "rg": {"winget": "BurntSushi.ripgrep.MSVC", "choco": "ripgrep", "scoop": "ripgrep"},
    "fd": {"winget": "sharkdp.fd", "choco": "fd", "scoop": "fd", "cargo": "fd-find"},
    "bat": {"winget": "sharkdp.bat", "choco": "bat", "scoop": "bat", "cargo": "bat"},
    "fzf": {"winget": "junegunn.fzf", "choco": "fzf", "scoop": "fzf"},
    "htop": {"scoop": "htop"},
    "tree": {"choco": "tree"},
    "neovim": {"winget": "Neovim.Neovim", "choco": "neovim", "scoop": "neovim"},
    "nvim": {"winget": "Neovim.Neovim", "choco": "neovim", "scoop": "neovim"},
    "ffmpeg": {"winget": "Gyan.FFmpeg", "choco": "ffmpeg", "scoop": "ffmpeg"},
    "imagemagick": {"winget": "ImageMagick.ImageMagick", "choco": "imagemagick"},
    "7zip": {"winget": "7zip.7zip", "choco": "7zip", "scoop": "7zip"},
    "ssh": {"winget": "Microsoft.OpenSSH.Beta"},
    "terraform": {"winget": "Hashicorp.Terraform", "choco": "terraform", "scoop": "terraform"},
    "kubectl": {"winget": "Kubernetes.kubectl", "choco": "kubernetes-cli", "scoop": "kubectl"},
    "aws": {"winget": "Amazon.AWSCLI", "choco": "awscli", "pip": "awscli"},
    "az": {"winget": "Microsoft.AzureCLI", "choco": "azure-cli", "pip": "azure-cli"},
    "gcloud": {"winget": "Google.CloudSDK", "choco": "gcloudsdk"},
    "gh": {"winget": "GitHub.cli", "choco": "gh", "scoop": "gh"},
    "speedtest": {"winget": "Ookla.Speedtest.CLI", "pip": "speedtest-cli"},

    # Editors & IDEs
    "code": {"winget": "Microsoft.VisualStudioCode", "choco": "vscode"},
    "vscode": {"winget": "Microsoft.VisualStudioCode", "choco": "vscode"},
    "sublime": {"winget": "SublimeHQ.SublimeText.4", "choco": "sublimetext4"},
    "notepad++": {"winget": "Notepad++.Notepad++", "choco": "notepadplusplus"},

    # Browsers
    "chrome": {"winget": "Google.Chrome", "choco": "googlechrome"},
    "firefox": {"winget": "Mozilla.Firefox", "choco": "firefox"},
    "brave": {"winget": "Brave.Brave", "choco": "brave"},

    # Communication
    "discord": {"winget": "Discord.Discord", "choco": "discord"},
    "slack": {"winget": "SlackTechnologies.Slack", "choco": "slack"},
    "zoom": {"winget": "Zoom.Zoom", "choco": "zoom"},
    "telegram": {"winget": "Telegram.TelegramDesktop", "choco": "telegram"},

    # Database tools  
    "mysql": {"winget": "Oracle.MySQL", "choco": "mysql"},
    "psql": {"winget": "PostgreSQL.PostgreSQL", "choco": "postgresql"},
    "redis": {"choco": "redis-64", "scoop": "redis"},
    "mongosh": {"winget": "MongoDB.Shell", "npm": "mongosh"},
    "sqlite3": {"choco": "sqlite", "scoop": "sqlite"},

    # Monitoring / DevOps
    "ngrok": {"winget": "Ngrok.Ngrok", "choco": "ngrok", "scoop": "ngrok"},
    "pm2": {"npm": "pm2"},
    "nodemon": {"npm": "nodemon"},
    "ts-node": {"npm": "ts-node"},
    "typescript": {"npm": "typescript"},
    "prettier": {"npm": "prettier"},
    "eslint": {"npm": "eslint"},
    "ruff": {"pip": "ruff"},
    "black": {"pip": "black"},
    "mypy": {"pip": "mypy"},
    "pytest": {"pip": "pytest"},
    "flask": {"pip": "flask"},
    "fastapi": {"pip": "fastapi"},
    "django": {"pip": "django"},
    "uvicorn": {"pip": "uvicorn"},
    "gunicorn": {"pip": "gunicorn"},
    "httpie": {"pip": "httpie", "winget": "HTTPie.HTTPie"},
}

# Python package name → pip package mapping (common mismatches)
_PIP_ALIASES = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "gi": "PyGObject",
    "serial": "pyserial",
    "usb": "pyusb",
    "crypto": "pycryptodome",
    "jwt": "PyJWT",
    "lxml": "lxml",
    "magic": "python-magic",
    "playwright": "playwright",
    "wx": "wxPython",
    "tk": "tk",
    "skimage": "scikit-image",
    "telegram": "python-telegram-bot",
    "discord": "discord.py",
    "flask_cors": "flask-cors",
    "flask_socketio": "flask-socketio",
    "sqlalchemy": "SQLAlchemy",
    "pydantic": "pydantic",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "websockets": "websockets",
    "rich": "rich",
    "typer": "typer",
    "click": "click",
}


def _run_silent(cmd: str, timeout: int = 15) -> Dict[str, Any]:
    """Run a command silently and return result."""
    try:
        if os.name == "nt":
            argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
        else:
            argv = ["/bin/sh", "-c", cmd]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, shell=False)
        return {
            "ok": proc.returncode == 0,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
            "exit_code": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "timeout", "exit_code": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "exit_code": -1}


def discover_tools() -> Dict[str, Any]:
    """
    Scan the system for available CLI tools, package managers, and runtimes.
    Returns a comprehensive inventory of what's installed.
    """
    inventory: Dict[str, Any] = {
        "package_managers": {},
        "runtimes": {},
        "cli_tools": {},
        "shells": {},
    }

    # Detect package managers
    for name, info in _PACKAGE_MANAGERS.items():
        result = _run_silent(info["check"])
        if result["ok"]:
            inventory["package_managers"][name] = {
                "available": True,
                "version": result["stdout"].split("\n")[0][:80],
            }

    # Detect common runtimes
    runtimes = {
        "python": "python --version",
        "node": "node --version",
        "npm": "npm --version",
        "cargo": "cargo --version",
        "go": "go version",
        "java": "java --version",
        "dotnet": "dotnet --version",
        "ruby": "ruby --version",
        "php": "php --version",
    }
    for name, cmd in runtimes.items():
        result = _run_silent(cmd)
        if result["ok"]:
            version_text = result["stdout"].split("\n")[0][:80]
            inventory["runtimes"][name] = version_text

    # Detect key CLI tools
    cli_tools = [
        "git", "docker", "kubectl", "terraform", "aws", "az", "gcloud", "gh",
        "curl", "wget", "jq", "rg", "fd", "bat", "fzf", "ffmpeg", "ssh",
        "ngrok", "pm2", "speedtest", "sqlite3", "mysql", "psql", "redis-cli",
    ]
    for tool in cli_tools:
        if shutil.which(tool):
            inventory["cli_tools"][tool] = True

    # Detect shells
    shells = {"powershell": "powershell", "pwsh": "pwsh", "cmd": "cmd", "bash": "bash", "sh": "sh", "zsh": "zsh"}
    for name, exe in shells.items():
        if shutil.which(exe):
            inventory["shells"][name] = True

    return {
        "ok": True,
        "kind": "tool_discovery",
        "inventory": inventory,
        "summary": (
            f"{len(inventory['package_managers'])} package managers, "
            f"{len(inventory['runtimes'])} runtimes, "
            f"{len(inventory['cli_tools'])} CLI tools, "
            f"{len(inventory['shells'])} shells"
        ),
    }


def auto_install_tool(tool_name: str, prefer_manager: str | None = None) -> Dict[str, Any]:
    """
    Automatically install a CLI tool or package using the best available package manager.

    Strategy:
    1. Check if already installed → skip
    2. Look up in _TOOL_INSTALL_MAP for known packages
    3. Try preferred package manager first, then fallback chain
    4. Verify installation after
    """
    name = tool_name.strip().lower()
    if not name:
        return {"ok": False, "error": "Tool name is required"}

    # Check if already installed
    if shutil.which(name):
        version_result = _run_silent(f"{name} --version")
        return {
            "ok": True,
            "kind": "auto_install",
            "tool": name,
            "already_installed": True,
            "version": version_result["stdout"][:120] if version_result["ok"] else "unknown",
        }

    # Look up known install commands
    known = _TOOL_INSTALL_MAP.get(name, {})
    if not known:
        # Try winget search as fallback
        winget_search = _run_silent(f'winget search "{name}" --count 3', timeout=20)
        if winget_search["ok"] and name.lower() in winget_search["stdout"].lower():
            return {
                "ok": False,
                "kind": "auto_install", 
                "tool": name,
                "not_in_map": True,
                "suggestion": f"Tool '{name}' found via winget search but not in known map. "
                              f"Try: winget install {name}",
                "winget_results": winget_search["stdout"][:500],
            }
        return {
            "ok": False,
            "kind": "auto_install",
            "tool": name,
            "error": f"Unknown tool '{name}'. Not in install map and not found via winget search.",
        }

    # Determine manager priority
    if prefer_manager and prefer_manager in known:
        managers = [prefer_manager] + [m for m in known if m != prefer_manager]
    else:
        # Priority: winget > scoop > choco > pip > npm > cargo > go
        priority = ["winget", "scoop", "choco", "pip", "pip3", "npm", "cargo", "go"]
        managers = [m for m in priority if m in known]

    # Find available manager
    errors = []
    for mgr in managers:
        mgr_info = _PACKAGE_MANAGERS.get(mgr)
        if not mgr_info:
            continue
        # Verify manager is available
        check = _run_silent(mgr_info["check"])
        if not check["ok"]:
            continue

        # Execute install
        pkg = known[mgr]
        install_cmd = mgr_info["install"].format(pkg=pkg)
        result = _run_silent(install_cmd, timeout=300)

        if result["ok"]:
            # Verify installation
            time.sleep(1)
            verify = shutil.which(name)
            version_result = _run_silent(f"{name} --version") if verify else {"ok": False, "stdout": ""}
            return {
                "ok": True,
                "kind": "auto_install",
                "tool": name,
                "installed_via": mgr,
                "package": pkg,
                "verified": verify is not None,
                "version": version_result["stdout"][:120] if version_result["ok"] else "pending PATH refresh",
                "note": "You may need to restart your terminal for PATH changes to take effect." if not verify else "",
            }
        else:
            errors.append(f"{mgr}: {result['stderr'][:200]}")

    return {
        "ok": False,
        "kind": "auto_install",
        "tool": name,
        "error": f"Failed to install '{name}' with any available package manager.",
        "attempts": errors,
    }


def auto_install_python_package(package: str) -> Dict[str, Any]:
    """
    Install a Python package, handling common aliases and edge cases.
    """
    pkg = package.strip()
    if not pkg:
        return {"ok": False, "error": "Package name is required"}

    # Check alias mapping (import_name → pip_name)
    actual_pkg = _PIP_ALIASES.get(pkg, pkg)

    # Build reverse map (pip_name → import_name) for import checking 
    _reverse_aliases = {v.lower(): k for k, v in _PIP_ALIASES.items()}
    
    # Determine the correct import name to test
    import_name = pkg
    if "-" in pkg or pkg.lower() in _reverse_aliases:
        # User gave pip name (e.g. "opencv-python") — find the import name
        import_name = _reverse_aliases.get(pkg.lower(), pkg.replace("-", "_"))
    
    # Try import first to see if already installed
    check = _run_silent(f'python -c "import {import_name}"')
    if check["ok"]:
        version_check = _run_silent(f'python -c "import {import_name}; print(getattr({import_name}, \'__version__\', \'installed\'))"')
        return {
            "ok": True,
            "kind": "pip_install",
            "package": actual_pkg,
            "already_installed": True,
            "version": version_check["stdout"][:80] if version_check["ok"] else "installed",
        }

    # Install cascade: pip → pip3 → python -m pip
    methods = [
        f"pip install {actual_pkg}",
        f"pip3 install {actual_pkg}",
        f"python -m pip install {actual_pkg}",
    ]

    for cmd in methods:
        result = _run_silent(cmd, timeout=120)
        if result["ok"]:
            return {
                "ok": True,
                "kind": "pip_install",
                "package": actual_pkg,
                "original_name": pkg if pkg != actual_pkg else None,
                "installed": True,
                "output": result["stdout"][-200:],
            }

    return {
        "ok": False,
        "kind": "pip_install",
        "package": actual_pkg,
        "error": f"Failed to install '{actual_pkg}' via pip. Check if pip is installed and accessible.",
    }


def generate_and_run_script(
    description: str,
    language: str = "powershell",
    script_content: str = "",
    args: List[str] | None = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    """
    Generate (or receive) a script, save it to a temp file, execute it, and return results.
    This is the core of autonomous task execution — ANKITA writes scripts and runs them.

    Args:
        description: What the script does (for logging)
        language: powershell, python, bash, bat, node
        script_content: The actual script code to execute
        args: Optional arguments to pass to the script
        timeout: Max seconds to wait
    """
    if not script_content.strip():
        return {"ok": False, "error": "Script content is required"}

    # Map language to file extension and executor
    lang_map = {
        "powershell": {"ext": ".ps1", "exec": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]},
        "python": {"ext": ".py", "exec": ["python"]},
        "bash": {"ext": ".sh", "exec": ["bash"]},
        "bat": {"ext": ".bat", "exec": ["cmd", "/c"]},
        "node": {"ext": ".js", "exec": ["node"]},
        "typescript": {"ext": ".ts", "exec": ["npx", "ts-node"]},
    }

    lang = language.lower()
    if lang not in lang_map:
        return {"ok": False, "error": f"Unsupported language: {language}. Use: {list(lang_map.keys())}"}

    info = lang_map[lang]

    # Write script to temp file
    ankita_temp = Path(os.environ.get("TEMP", tempfile.gettempdir())) / "ankita_scripts"
    ankita_temp.mkdir(exist_ok=True)
    timestamp = int(time.time())
    script_file = ankita_temp / f"script_{timestamp}{info['ext']}"

    try:
        script_file.write_text(script_content, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"Failed to write script: {e}"}

    # Build command
    argv = info["exec"] + [str(script_file)]
    if args:
        argv.extend([str(a) for a in args])

    # Execute
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            cwd=str(Path.home()),
        )

        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()

        # Truncate if needed
        if len(output) > 8000:
            output = output[:4000] + "\n...[truncated]...\n" + output[-2000:]

        # PowerShell writes non-terminating errors to stderr even with exit code 0
        # Detect this: if exit_code is 0 but stderr has substantial error content, mark as partial success
        ok = result.returncode == 0
        if ok and error and ("is not recognized" in error or "FullyQualifiedErrorId" in error):
            ok = False  # PowerShell-specific: non-terminating errors indicate script issues

        return {
            "ok": ok,
            "kind": "script_execution",
            "description": description,
            "language": lang,
            "script_path": str(script_file),
            "exit_code": result.returncode,
            "output": output if output else "(no output)",
            "error": error,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "kind": "script_execution",
            "description": description,
            "error": f"Script timed out after {timeout}s",
            "script_path": str(script_file),
        }
    except Exception as e:
        return {
            "ok": False,
            "kind": "script_execution",
            "description": description,
            "error": str(e),
            "script_path": str(script_file),
        }


def execute_pipeline(steps: List[Dict[str, str]], stop_on_error: bool = True) -> Dict[str, Any]:
    """
    Execute a multi-step command pipeline sequentially.
    Each step is {"command": "...", "description": "..."}.
    
    Inspired by OpenClaw's ability to chain system.run commands in sequence.
    """
    if not steps:
        return {"ok": False, "error": "Pipeline requires at least one step"}

    results = []
    overall_ok = True

    for i, step in enumerate(steps):
        cmd = step.get("command", "").strip()
        desc = step.get("description", f"Step {i + 1}")

        if not cmd:
            results.append({"step": i + 1, "description": desc, "ok": False, "error": "Empty command"})
            if stop_on_error:
                overall_ok = False
                break
            continue

        # Execute step — on Windows, convert && to ; for PowerShell 5.x compat
        if os.name == "nt":
            # PowerShell 5.x doesn't support &&, replace with ; for compatibility
            ps_cmd = cmd.replace(" && ", " ; ")
            argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd]
        else:
            argv = ["/bin/sh", "-c", cmd]

        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=300, shell=False
            )
            output = (proc.stdout or "").strip()
            error = (proc.stderr or "").strip()

            step_result = {
                "step": i + 1,
                "description": desc,
                "command": cmd,
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "output": output[:2000] if output else "",
                "error": error[:500] if error else "",
            }
            results.append(step_result)

            if not step_result["ok"] and stop_on_error:
                overall_ok = False
                break

        except subprocess.TimeoutExpired:
            results.append({
                "step": i + 1, "description": desc, "ok": False,
                "error": "Timed out after 300s",
            })
            if stop_on_error:
                overall_ok = False
                break
        except Exception as e:
            results.append({
                "step": i + 1, "description": desc, "ok": False,
                "error": str(e),
            })
            if stop_on_error:
                overall_ok = False
                break

    completed = sum(1 for r in results if r.get("ok"))
    return {
        "ok": overall_ok,
        "kind": "pipeline",
        "total_steps": len(steps),
        "completed": completed,
        "failed": len(results) - completed,
        "results": results,
    }


def environment_setup(
    project_type: str,
    project_path: str | None = None,
) -> Dict[str, Any]:
    """
    Auto-detect and set up a development environment for a project.
    
    Scans the project directory, detects the stack, installs dependencies,
    and configures the environment — all autonomously.
    """
    proj_path = Path(project_path).resolve() if project_path else Path.cwd()
    if not proj_path.exists():
        return {"ok": False, "error": f"Project path not found: {proj_path}"}

    detected = {
        "type": project_type,
        "path": str(proj_path),
        "actions_taken": [],
        "warnings": [],
    }

    # Auto-detect from files
    files = {f.name for f in proj_path.iterdir() if f.is_file()} if proj_path.is_dir() else set()

    # Auto-detect project type from files present
    if project_type == "auto":
        if "requirements.txt" in files or "pyproject.toml" in files or "setup.py" in files or "Pipfile" in files:
            project_type = "python"
        elif "package.json" in files:
            project_type = "node"
        elif "Cargo.toml" in files:
            project_type = "rust"
        elif "go.mod" in files:
            project_type = "go"
        elif "pom.xml" in files or "build.gradle" in files:
            project_type = "java"
        elif "CMakeLists.txt" in files or "Makefile" in files:
            project_type = "cpp"
        else:
            detected["warnings"].append(f"Could not auto-detect project type from files in {proj_path}")
            detected["ok"] = False
            return detected
        detected["type"] = project_type

    # Python project
    if project_type == "python" or "requirements.txt" in files or "pyproject.toml" in files or "setup.py" in files:
        detected["type"] = "python"

        # Create venv if missing
        venv_path = proj_path / ".venv"
        if not venv_path.exists():
            result = _run_silent(f'python -m venv "{venv_path}"', timeout=60)
            if result["ok"]:
                detected["actions_taken"].append("Created .venv virtual environment")
            else:
                detected["warnings"].append(f"Failed to create venv: {result['stderr'][:200]}")

        # Install deps
        if "requirements.txt" in files:
            activate = str(venv_path / "Scripts" / "Activate.ps1") if os.name == "nt" else f"source {venv_path / 'bin' / 'activate'}"
            pip_cmd = str(venv_path / "Scripts" / "pip") if os.name == "nt" else str(venv_path / "bin" / "pip")
            result = _run_silent(f'"{pip_cmd}" install -r "{proj_path / "requirements.txt"}"', timeout=300)
            if result["ok"]:
                detected["actions_taken"].append("Installed requirements.txt dependencies")
            else:
                detected["warnings"].append(f"pip install failed: {result['stderr'][:200]}")
        elif "pyproject.toml" in files:
            result = _run_silent(f'cd "{proj_path}" && pip install -e .', timeout=300)
            if result["ok"]:
                detected["actions_taken"].append("Installed project via pyproject.toml (editable)")

    # Node.js project
    elif project_type == "node" or "package.json" in files:
        detected["type"] = "node"
        if "pnpm-lock.yaml" in files:
            result = _run_silent(f'cd "{proj_path}" && pnpm install', timeout=300)
            mgr = "pnpm"
        elif "yarn.lock" in files:
            result = _run_silent(f'cd "{proj_path}" && yarn install', timeout=300)
            mgr = "yarn"
        else:
            result = _run_silent(f'cd "{proj_path}" && npm install', timeout=300)
            mgr = "npm"

        if result["ok"]:
            detected["actions_taken"].append(f"Installed dependencies via {mgr}")
        else:
            detected["warnings"].append(f"{mgr} install failed: {result['stderr'][:200]}")

    # Rust project
    elif project_type == "rust" or "Cargo.toml" in files:
        detected["type"] = "rust"
        result = _run_silent(f'cd "{proj_path}" && cargo build', timeout=600)
        if result["ok"]:
            detected["actions_taken"].append("Built Rust project (cargo build)")

    # Go project
    elif project_type == "go" or "go.mod" in files:
        detected["type"] = "go"
        result = _run_silent(f'cd "{proj_path}" && go mod download', timeout=120)
        if result["ok"]:
            detected["actions_taken"].append("Downloaded Go dependencies")

    else:
        detected["warnings"].append(f"Unknown project type: {project_type}")

    detected["ok"] = len(detected["warnings"]) == 0
    return detected


def system_audit() -> Dict[str, Any]:
    """
    Comprehensive system audit — OS info, hardware, disk, network, running services.
    Used by ANKITA to understand the host environment before taking autonomous actions.
    """
    audit: Dict[str, Any] = {"ok": True, "kind": "system_audit"}

    # OS info
    os_info = _run_silent('Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,OSArchitecture | Format-List')
    audit["os"] = os_info["stdout"][:500] if os_info["ok"] else "unknown"

    # Hardware
    cpu = _run_silent('(Get-CimInstance Win32_Processor).Name')
    ram = _run_silent('[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)')
    audit["cpu"] = cpu["stdout"][:120] if cpu["ok"] else "unknown"
    audit["ram_gb"] = ram["stdout"][:20] if ram["ok"] else "unknown"

    # Disk
    disk = _run_silent('Get-PSDrive -PSProvider FileSystem | Select-Object Name,@{N="UsedGB";E={[math]::Round($_.Used/1GB,1)}},@{N="FreeGB";E={[math]::Round($_.Free/1GB,1)}} | Format-Table -AutoSize')
    audit["disk"] = disk["stdout"][:500] if disk["ok"] else "unknown"

    # Network
    ip = _run_silent('(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.InterfaceAlias -notmatch "Loopback"}).IPAddress')
    audit["local_ip"] = ip["stdout"][:200] if ip["ok"] else "unknown"

    # Running services count
    services = _run_silent('(Get-Service | Where-Object {$_.Status -eq "Running"}).Count')
    audit["running_services"] = services["stdout"][:20] if services["ok"] else "unknown"

    # Python environment
    py = _run_silent("python --version")
    audit["python"] = py["stdout"][:80] if py["ok"] else "not found"

    return audit
