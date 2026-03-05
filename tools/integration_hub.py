"""
Integration Hub for A.N.K.I.T.A — External Service Integrations

Inspired by OpenClaw's channel/integration architecture.
Provides unified interface to external services through CLI tools and APIs.

Integrations:
- GitHub (via gh CLI)
- Docker (via docker CLI)
- Cloud CLIs (AWS, Azure, GCloud)
- Database operations
- API testing (httpie/curl)
- Server management
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.autonomous_ops import _run_silent, auto_install_tool


# ─────────────────────────────────────────────────────────────────────────────
# GITHUB INTEGRATION (via gh CLI)
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_gh() -> Dict[str, Any] | None:
    """Ensure gh CLI is installed. Returns error dict if not available."""
    if shutil.which("gh"):
        return None
    # Try to install
    result = auto_install_tool("gh")
    if result.get("ok"):
        return None
    return {"ok": False, "error": "GitHub CLI (gh) is not installed. Run: winget install GitHub.cli"}


def github_op(
    action: str,
    repo: str | None = None,
    title: str | None = None,
    body: str | None = None,
    branch: str | None = None,
    label: str | None = None,
    query: str | None = None,
    number: int | None = None,
    path: str | None = None,
    extra_args: str | None = None,
) -> Dict[str, Any]:
    """
    GitHub operations via the gh CLI.

    Actions:
        repo_view         - View current repo info
        repo_clone        - Clone a repository
        pr_list           - List pull requests
        pr_create         - Create a pull request
        pr_view           - View a specific PR
        pr_merge          - Merge a PR
        pr_checkout       - Checkout a PR branch
        issue_list        - List issues
        issue_create      - Create an issue
        issue_view        - View a specific issue
        issue_close       - Close an issue
        release_list      - List releases
        release_create    - Create a release
        workflow_list     - List GitHub Actions workflows
        workflow_run      - Trigger a workflow
        gist_create       - Create a gist
        repo_fork         - Fork a repository
        search_repos      - Search GitHub repositories
        search_code       - Search code on GitHub
        auth_status       - Check auth status
    """
    err = _ensure_gh()
    if err:
        return err

    cwd = path or str(Path.cwd())
    action = action.strip().lower()

    cmd_map = {
        "repo_view": "gh repo view --json name,description,url,stargazerCount,forkCount,isPrivate",
        "repo_clone": f"gh repo clone {repo}" if repo else None,
        "pr_list": f"gh pr list {'--repo ' + repo if repo else ''} --limit 20",
        "pr_create": None,  # Built dynamically
        "pr_view": f"gh pr view {number}" if number else None,
        "pr_merge": f"gh pr merge {number} --merge" if number else None,
        "pr_checkout": f"gh pr checkout {number}" if number else None,
        "issue_list": f"gh issue list {'--repo ' + repo if repo else ''} --limit 20 {'--label ' + label if label else ''}",
        "issue_create": None,  # Built dynamically
        "issue_view": f"gh issue view {number}" if number else None,
        "issue_close": f"gh issue close {number}" if number else None,
        "release_list": f"gh release list {'--repo ' + repo if repo else ''} --limit 10",
        "release_create": f'gh release create {branch or "v0.0.0"} --title "{title or "Release"}" --notes "{body or "New release"}"' if branch or title else None,
        "workflow_list": "gh workflow list",
        "workflow_run": f"gh workflow run {query}" if query else None,
        "gist_create": None,  # Special handling
        "repo_fork": f"gh repo fork {repo} --clone" if repo else None,
        "search_repos": f'gh search repos "{query}" --limit 10 --json name,description,url,stargazerCount' if query else None,
        "search_code": f'gh search code "{query}" --limit 10' if query else None,
        "auth_status": "gh auth status",
    }

    # Dynamic command building
    if action == "pr_create":
        if not title:
            return {"ok": False, "error": "PR title is required"}
        cmd = f'gh pr create --title "{title}"'
        if body:
            cmd += f' --body "{body}"'
        if branch:
            cmd += f' --base {branch}'
        if label:
            cmd += f' --label {label}'
    elif action == "issue_create":
        if not title:
            return {"ok": False, "error": "Issue title is required"}
        cmd = f'gh issue create --title "{title}"'
        if body:
            cmd += f' --body "{body}"'
        if label:
            cmd += f' --label {label}'
    elif action == "gist_create":
        if not path:
            return {"ok": False, "error": "File path is required for gist creation"}
        desc = title or "Created by ANKITA"
        cmd = f'gh gist create "{path}" --desc "{desc}"'
    else:
        cmd = cmd_map.get(action)

    if cmd is None:
        return {"ok": False, "error": f"Invalid action: {action}. Available: {list(cmd_map.keys())}"}

    if extra_args:
        cmd += f" {extra_args}"

    result = _run_silent(cmd, timeout=60)
    return {
        "ok": result["ok"],
        "kind": "github",
        "action": action,
        "output": result["stdout"][:4000] if result["stdout"] else "",
        "error": result["stderr"][:1000] if result["stderr"] and not result["ok"] else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# DOCKER INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────

def docker_op(
    action: str,
    image: str | None = None,
    container: str | None = None,
    command: str | None = None,
    ports: str | None = None,
    volumes: str | None = None,
    env_vars: Dict[str, str] | None = None,
    compose_file: str | None = None,
    extra_args: str | None = None,
) -> Dict[str, Any]:
    """
    Docker operations — containers, images, compose, and system management.

    Actions:
        ps                - List running containers
        ps_all            - List all containers
        images            - List images
        run               - Run a container
        stop              - Stop a container
        rm                - Remove a container
        logs              - Get container logs
        exec              - Execute command in container
        build             - Build an image from Dockerfile
        pull              - Pull an image
        compose_up        - Docker compose up
        compose_down      - Docker compose down
        compose_logs      - Docker compose logs
        system_info       - Docker system info
        system_prune      - Clean up unused resources
        network_list      - List networks
        volume_list       - List volumes
    """
    if not shutil.which("docker"):
        return {"ok": False, "error": "Docker is not installed. Run: winget install Docker.DockerDesktop"}

    action = action.strip().lower()
    timeout = 120  # Docker commands can be slow

    cmd_map = {
        "ps": "docker ps --format 'table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Names}}'",
        "ps_all": "docker ps -a --format 'table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}'",
        "images": "docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}'",
        "stop": f"docker stop {container}" if container else None,
        "rm": f"docker rm {container}" if container else None,
        "logs": f"docker logs {container} --tail 100" if container else None,
        "pull": f"docker pull {image}" if image else None,
        "system_info": "docker system df",
        "system_prune": "docker system prune -f",
        "network_list": "docker network ls",
        "volume_list": "docker volume ls",
        "compose_down": f"docker compose {'-f ' + compose_file if compose_file else ''} down",
        "compose_logs": f"docker compose {'-f ' + compose_file if compose_file else ''} logs --tail 100",
    }

    if action == "run":
        if not image:
            return {"ok": False, "error": "Image is required for 'run' action"}
        cmd = f"docker run -d"
        if container:
            cmd += f" --name {container}"
        if ports:
            cmd += f" -p {ports}"
        if volumes:
            cmd += f" -v {volumes}"
        if env_vars:
            for k, v in env_vars.items():
                cmd += f' -e {k}="{v}"'
        cmd += f" {image}"
        if command:
            cmd += f" {command}"
        timeout = 300
    elif action == "exec":
        if not container:
            return {"ok": False, "error": "Container name is required for 'exec'"}
        cmd = f"docker exec {container} {command or 'sh'}"
    elif action == "build":
        cmd = f"docker build -t {image or 'ankita-build'} ."
        if extra_args:
            cmd += f" {extra_args}"
        timeout = 600
    elif action == "compose_up":
        cmd = f"docker compose {'-f ' + compose_file if compose_file else ''} up -d"
        timeout = 300
    else:
        cmd = cmd_map.get(action)

    if cmd is None:
        return {"ok": False, "error": f"Invalid action: {action}. Available: {list(cmd_map.keys()) + ['run', 'exec', 'build', 'compose_up']}"}

    if extra_args and action not in ("run", "build"):
        cmd += f" {extra_args}"

    result = _run_silent(cmd, timeout=timeout)
    return {
        "ok": result["ok"],
        "kind": "docker",
        "action": action,
        "output": result["stdout"][:4000] if result["stdout"] else "",
        "error": result["stderr"][:1000] if result["stderr"] and not result["ok"] else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# SSH / REMOTE OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def ssh_op(
    action: str,
    host: str | None = None,
    command: str | None = None,
    user: str | None = None,
    key_path: str | None = None,
    port: int = 22,
    local_path: str | None = None,
    remote_path: str | None = None,
) -> Dict[str, Any]:
    """
    SSH and SCP operations for remote server management.

    Actions:
        run               - Execute command on remote host
        copy_to           - SCP file to remote host
        copy_from         - SCP file from remote host
        tunnel            - Create SSH tunnel (background)
        test              - Test SSH connection
    """
    if not shutil.which("ssh"):
        return {"ok": False, "error": "SSH is not available. Install OpenSSH client."}

    action = action.strip().lower()

    if not host:
        return {"ok": False, "error": "Host is required"}

    user_prefix = f"{user}@" if user else ""
    key_flag = f'-i "{key_path}"' if key_path else ""
    port_flag = f"-p {port}" if port != 22 else ""

    if action == "run":
        if not command:
            return {"ok": False, "error": "Command is required for 'run' action"}
        cmd = f'ssh {key_flag} {port_flag} {user_prefix}{host} "{command}"'
    elif action == "copy_to":
        if not local_path or not remote_path:
            return {"ok": False, "error": "local_path and remote_path are required"}
        scp_port = f"-P {port}" if port != 22 else ""
        cmd = f'scp {key_flag} {scp_port} "{local_path}" {user_prefix}{host}:"{remote_path}"'
    elif action == "copy_from":
        if not local_path or not remote_path:
            return {"ok": False, "error": "local_path and remote_path are required"}
        scp_port = f"-P {port}" if port != 22 else ""
        cmd = f'scp {key_flag} {scp_port} {user_prefix}{host}:"{remote_path}" "{local_path}"'
    elif action == "test":
        cmd = f'ssh {key_flag} {port_flag} -o ConnectTimeout=10 {user_prefix}{host} "echo CONNECTION_OK"'
    else:
        return {"ok": False, "error": f"Invalid action: {action}. Use: run, copy_to, copy_from, test"}

    result = _run_silent(cmd, timeout=60)
    return {
        "ok": result["ok"],
        "kind": "ssh",
        "action": action,
        "host": host,
        "output": result["stdout"][:4000],
        "error": result["stderr"][:1000] if not result["ok"] else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# API TESTING (httpie / curl wrapper)
# ─────────────────────────────────────────────────────────────────────────────

def api_test(
    method: str = "GET",
    url: str = "",
    headers: Dict[str, str] | None = None,
    body: str | None = None,
    auth: str | None = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Test API endpoints using curl (universally available).

    Args:
        method: HTTP method (GET, POST, PUT, DELETE, PATCH)
        url: The URL to request
        headers: Dict of headers
        body: Request body (JSON string)
        auth: Basic auth in format "user:password"
        timeout: Request timeout in seconds
    """
    if not url:
        return {"ok": False, "error": "URL is required"}

    # Use curl.exe on Windows to avoid PowerShell's Invoke-WebRequest alias
    curl_bin = "curl.exe" if os.name == "nt" else "curl"
    cmd = f'{curl_bin} -s -w "\n---HTTP_STATUS:%{{http_code}}---" -X {method.upper()}'
    cmd += f" --max-time {timeout}"

    if headers:
        for k, v in headers.items():
            cmd += f' -H "{k}: {v}"'

    if body:
        cmd += f" -H \"Content-Type: application/json\" -d '{body}'"

    if auth:
        cmd += f' -u "{auth}"'

    cmd += f' "{url}"'

    result = _run_silent(cmd, timeout=timeout + 10)

    # Parse HTTP status from output
    output = result["stdout"]
    status_code = None
    response_body = output

    if "---HTTP_STATUS:" in output:
        parts = output.rsplit("---HTTP_STATUS:", 1)
        response_body = parts[0].strip()
        status_match = parts[1].replace("---", "").strip()
        try:
            status_code = int(status_match)
        except ValueError:
            pass

    # Try to parse JSON response
    parsed_json = None
    try:
        parsed_json = json.loads(response_body)
    except (json.JSONDecodeError, TypeError):
        pass

    return {
        "ok": result["ok"] and (status_code is not None and status_code < 400),
        "kind": "api_test",
        "method": method.upper(),
        "url": url,
        "status_code": status_code,
        "response": parsed_json if parsed_json else response_body[:4000],
        "is_json": parsed_json is not None,
        "error": result["stderr"][:500] if not result["ok"] else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE QUICK-OPS (sqlite, postgres, mysql via CLI)
# ─────────────────────────────────────────────────────────────────────────────

def db_query(
    engine: str,
    query: str,
    database: str | None = None,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
) -> Dict[str, Any]:
    """
    Execute database queries via CLI tools.

    Engines: sqlite, postgres, mysql, redis
    """
    engine = engine.strip().lower()

    if engine == "sqlite":
        if not database:
            return {"ok": False, "error": "Database file path is required for SQLite"}
        cmd = f'sqlite3 "{database}" "{query}"'
    elif engine == "postgres":
        pg_cmd = "psql"
        if host:
            pg_cmd += f" -h {host}"
        if port:
            pg_cmd += f" -p {port}"
        if user:
            pg_cmd += f" -U {user}"
        if database:
            pg_cmd += f" -d {database}"
        cmd = f'{pg_cmd} -c "{query}"'
        if password:
            cmd = f'$env:PGPASSWORD="{password}"; {cmd}'
    elif engine == "mysql":
        my_cmd = "mysql"
        if host:
            my_cmd += f" -h {host}"
        if port:
            my_cmd += f" -P {port}"
        if user:
            my_cmd += f" -u {user}"
        if password:
            my_cmd += f" -p{password}"
        if database:
            my_cmd += f" {database}"
        cmd = f'{my_cmd} -e "{query}"'
    elif engine == "redis":
        redis_cmd = "redis-cli"
        if host:
            redis_cmd += f" -h {host}"
        if port:
            redis_cmd += f" -p {port}"
        if password:
            redis_cmd += f" -a {password}"
        cmd = f'{redis_cmd} {query}'
    else:
        return {"ok": False, "error": f"Unsupported engine: {engine}. Use: sqlite, postgres, mysql, redis"}

    result = _run_silent(cmd, timeout=30)
    return {
        "ok": result["ok"],
        "kind": "db_query",
        "engine": engine,
        "output": result["stdout"][:4000] if result["stdout"] else "(no output)",
        "error": result["stderr"][:1000] if not result["ok"] else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE MANAGEMENT (systemd-like management for Windows services/tasks)
# ─────────────────────────────────────────────────────────────────────────────

def service_op(
    action: str,
    name: str | None = None,
    command: str | None = None,
    schedule: str | None = None,
) -> Dict[str, Any]:
    """
    Windows service and scheduled task management.

    Actions:
        list_services     - List running Windows services
        start_service     - Start a service
        stop_service      - Stop a service
        restart_service   - Restart a service
        create_task       - Create a scheduled task
        list_tasks        - List scheduled tasks
        delete_task       - Delete a scheduled task
        startup_add       - Add program to startup
        startup_list      - List startup programs
    """
    action = action.strip().lower()

    cmd_map = {
        "list_services": "Get-Service | Where-Object {$_.Status -eq 'Running'} | Select-Object -First 30 Name,DisplayName,Status | Format-Table -AutoSize",
        "start_service": f"Start-Service -Name '{name}'" if name else None,
        "stop_service": f"Stop-Service -Name '{name}'" if name else None,
        "restart_service": f"Restart-Service -Name '{name}'" if name else None,
        "list_tasks": "Get-ScheduledTask | Where-Object {$_.State -ne 'Disabled'} | Select-Object -First 20 TaskName,State | Format-Table",
        "delete_task": f"Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false" if name else None,
        "startup_list": "Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location | Format-Table -AutoSize",
    }

    if action == "create_task":
        if not name or not command:
            return {"ok": False, "error": "Name and command are required for create_task"}
        if schedule:
            cmd = (
                f"$action = New-ScheduledTaskAction -Execute 'powershell' -Argument '-NoProfile -Command \"{command}\"'; "
                f"$trigger = New-ScheduledTaskTrigger -Daily -At {schedule}; "
                f"Register-ScheduledTask -TaskName '{name}' -Action $action -Trigger $trigger -RunLevel Highest"
            )
        else:
            cmd = (
                f"$action = New-ScheduledTaskAction -Execute 'powershell' -Argument '-NoProfile -Command \"{command}\"'; "
                f"$trigger = New-ScheduledTaskTrigger -AtLogon; "
                f"Register-ScheduledTask -TaskName '{name}' -Action $action -Trigger $trigger"
            )
    elif action == "startup_add":
        if not name or not command:
            return {"ok": False, "error": "Name and command are required for startup_add"}
        startup_path = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        shortcut_path = startup_path / f"{name}.bat"
        cmd = f'Set-Content -Path "{shortcut_path}" -Value "@echo off`n{command}"'
    else:
        cmd = cmd_map.get(action)

    if cmd is None:
        return {"ok": False, "error": f"Invalid action: {action}. Available: {list(cmd_map.keys()) + ['create_task', 'startup_add']}"}

    result = _run_silent(cmd, timeout=30)
    return {
        "ok": result["ok"],
        "kind": "service",
        "action": action,
        "output": result["stdout"][:4000] if result["stdout"] else "",
        "error": result["stderr"][:1000] if not result["ok"] else "",
    }
