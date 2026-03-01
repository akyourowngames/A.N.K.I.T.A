"""
GitWatcher — Repository Monitor for A.N.K.I.T.A.

Monitors local git repositories for new commits, branches, and merges.
Optionally polls GitHub API for PRs and issues (requires GITHUB_TOKEN).

Config (git_config.json):
    {
        "enabled": false,
        "poll_interval_sec": 300,
        "repos": [
            "C:/Users/anime/source/repos/HelperID",
            "C:/Users/anime/3D Objects/A.N.K.I.T.A"
        ],
        "github_token_env": "GITHUB_TOKEN"
    }
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from watchdog_manager import BaseWatcher
from proactive import ProactiveEngine


class GitWatcher(BaseWatcher):
    """
    Monitors local git repos for new commits.
    Uses `git log --since=<last_check>` — zero extra dependencies.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        super().__init__(
            name="GitWatcher",
            config=config,
            proactive=proactive,
            workspace_root=workspace_root,
        )
        self.poll_interval = float(config.get("poll_interval_sec", 300))

        # State: {"last_check_time": {repo_path: epoch_float}}
        self.state.setdefault("last_check_time", {})

    def _check(self) -> Optional[str]:
        """Check all configured repos for new commits."""
        repos: List[str] = self.config.get("repos", [])
        if not repos:
            return None

        alerts: List[str] = []

        for repo_path_str in repos:
            repo_path = Path(repo_path_str).expanduser()
            if not (repo_path / ".git").exists():
                print(f"[GitWatcher] Not a git repo: {repo_path}", flush=True)
                continue

            try:
                repo_alerts = self._check_repo(repo_path)
                alerts.extend(repo_alerts)
            except Exception as exc:
                print(f"[GitWatcher] Error checking {repo_path}: {exc}", flush=True)

        self._save_state()

        if alerts:
            return "\n".join(alerts)
        return None

    def _check_repo(self, repo_path: Path) -> List[str]:
        """Check a single repo for new commits since last check."""
        key = str(repo_path)
        last_check = self.state["last_check_time"].get(key)

        now = time.time()
        self.state["last_check_time"][key] = now

        if last_check is None:
            # First run — just record baseline, don't alert
            return []

        # Build `git log` command to get commits since last check
        # Format: hash|author|subject|date
        since_arg = f"--since={int(last_check)}"
        git_cmd = [
            "git", "-C", str(repo_path),
            "log",
            since_arg,
            "--pretty=format:%H|%an|%s|%ar",
            "--all",
        ]

        try:
            result = subprocess.run(
                git_cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            print("[GitWatcher] git not found in PATH", flush=True)
            return []
        except subprocess.TimeoutExpired:
            print(f"[GitWatcher] git log timed out for {repo_path}", flush=True)
            return []

        if result.returncode != 0:
            return []

        output = result.stdout.strip()
        if not output:
            return []

        alerts: List[str] = []
        repo_name = repo_path.name
        lines = output.split("\n")

        for line in lines[:10]:  # Cap at 10 commits per check
            parts = line.split("|", 3)
            if len(parts) < 3:
                continue
            commit_hash = parts[0][:8]
            author = parts[1]
            subject = parts[2]
            date = parts[3] if len(parts) > 3 else ""

            alert = (
                f"🔀 [{repo_name}] New commit by {author} ({date})\n"
                f"   {commit_hash}: {subject}"
            )
            alerts.append(alert)

        if len(lines) > 10:
            alerts.append(f"   ... and {len(lines) - 10} more commits in {repo_name}")

        return alerts

    def _fetch_github_prs(self, owner: str, repo: str, token: str) -> List[str]:
        """
        Optional: Fetch open PRs from GitHub API.
        Called only if GITHUB_TOKEN is set and repo is a GitHub remote.
        """
        try:
            import urllib.request
            import json as _json

            url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=open&per_page=5"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "ANKITA/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                prs = _json.loads(resp.read())

            alerts = []
            for pr in prs:
                title = pr.get("title", "")
                number = pr.get("number", "")
                user = pr.get("user", {}).get("login", "")
                alerts.append(f"🔁 PR #{number} open in {repo}: '{title}' by @{user}")
            return alerts
        except Exception as exc:
            print(f"[GitWatcher] GitHub PR fetch failed: {exc}", flush=True)
            return []
