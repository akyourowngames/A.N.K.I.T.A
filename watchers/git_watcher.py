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

    def _resolve_github_token(self) -> Optional[str]:
        """
        Resolve the GitHub API token using this priority:
          1. GITHUB_TOKEN / GH_TOKEN env vars
          2. Cached token via auth_manager (device flow cache)
        Does NOT trigger interactive Device Flow here — that must be
        explicitly requested via /reauth github or force_reauth=True.
        """
        # Check env vars first
        for env_name in (self.config.get("github_token_env", "GITHUB_TOKEN"), "GH_TOKEN"):
            token = os.environ.get(env_name, "").strip()
            if token:
                return token
        # Fall back to auth_manager cache (no interactive prompt)
        try:
            from tools.auth_manager import _load_github_token_cache
            return _load_github_token_cache()
        except Exception:
            return None

    def _check(self) -> Optional[str]:
        """Check all configured repos for new commits."""
        repos: List[str] = self.config.get("repos", [])
        if not repos:
            return None

        alerts: List[str] = []
        github_token = self._resolve_github_token()

        for repo_path_str in repos:
            repo_path = Path(repo_path_str).expanduser()
            if not (repo_path / ".git").exists():
                print(f"[GitWatcher] Not a git repo: {repo_path}", flush=True)
                continue

            try:
                repo_alerts = self._check_repo(repo_path, github_token=github_token)
                alerts.extend(repo_alerts)
            except Exception as exc:
                print(f"[GitWatcher] Error checking {repo_path}: {exc}", flush=True)

        self._save_state()

        if alerts:
            return "\n".join(alerts)
        return None

    def _check_repo(self, repo_path: Path, github_token: Optional[str] = None) -> List[str]:
        """Check a single repo for new commits since last check, plus GitHub PRs/CI."""
        key = str(repo_path)
        last_check = self.state["last_check_time"].get(key)

        now = time.time()
        self.state["last_check_time"][key] = now

        if last_check is None:
            # First run — just record baseline, don't alert
            return []

        watch_branches: List[str] = [
            b.lower() for b in self.config.get("watch_branches", [])
        ]

        # Build `git log` command to get commits since last check
        since_arg = f"--since={int(last_check)}"
        git_cmd = [
            "git", "-C", str(repo_path),
            "log",
            since_arg,
            "--pretty=format:%H|%an|%s|%ar|%D",
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

        alerts: List[str] = []
        repo_name = repo_path.name

        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            shown = 0
            for line in lines:
                parts = line.split("|", 4)
                if len(parts) < 3:
                    continue
                commit_hash = parts[0][:8]
                author = parts[1]
                subject = parts[2]
                date = parts[3] if len(parts) > 3 else ""
                refs = parts[4] if len(parts) > 4 else ""

                # Branch filter — only alert on specified branches
                if watch_branches:
                    branch_names = [r.strip().lower() for r in refs.split(",") if r.strip()]
                    # Extract short branch names (strip "origin/", "HEAD -> ")
                    clean_branches = []
                    for b in branch_names:
                        b = re.sub(r'^head\s*->\s*', '', b)
                        b = re.sub(r'^origin/', '', b)
                        clean_branches.append(b.strip())
                    if not any(wb in clean_branches for wb in watch_branches):
                        continue

                alert = (
                    f"🔀 [{repo_name}] New commit by {author} ({date})\n"
                    f"   {commit_hash}: {subject}"
                )
                if refs:
                    # Show branch tags on the alert
                    nice_refs = refs.strip()
                    alert += f"  ({nice_refs})"
                alerts.append(alert)
                shown += 1
                if shown >= 10:
                    remaining = len(lines) - shown
                    if remaining > 0:
                        alerts.append(f"   … and {remaining} more commits in {repo_name}")
                    break

        # GitHub PR + CI alerts (if token available)
        if github_token:
            gh_owner, gh_repo = self._detect_github_remote(repo_path)
            if gh_owner and gh_repo:
                pr_alerts = self._fetch_github_prs(gh_owner, gh_repo, github_token)
                alerts.extend(pr_alerts)

                if self.config.get("check_ci_status", False):
                    ci_alerts = self._fetch_github_ci_status(gh_owner, gh_repo, github_token)
                    alerts.extend(ci_alerts)

        return alerts

    def _detect_github_remote(self, repo_path: Path) -> tuple:
        """
        Detect GitHub owner/repo from git remote URL.
        Returns (owner, repo) or (None, None) if not a GitHub remote.
        """
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return None, None
            url = result.stdout.strip()
            # Match https://github.com/owner/repo or git@github.com:owner/repo
            m = re.search(r'github\.com[:/]([^/]+)/([^/.]+)', url)
            if m:
                return m.group(1), m.group(2).replace(".git", "")
        except Exception:
            pass
        return None, None

    def _fetch_github_prs(self, owner: str, repo: str, token: str) -> List[str]:
        """
        Fetch open PRs from GitHub API. Tracks seen PR numbers to avoid repeat alerts.
        """
        try:
            import urllib.request
            import json as _json

            url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=open&per_page=10&sort=updated&direction=desc"
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

            seen_prs: List[int] = self.state.get("seen_pr_numbers", {}).get(repo, [])
            alerts = []
            new_seen = list(seen_prs)

            for pr in prs:
                number = pr.get("number")
                if number in seen_prs:
                    continue
                title = pr.get("title", "")
                user = pr.get("user", {}).get("login", "")
                draft = " [DRAFT]" if pr.get("draft") else ""
                alerts.append(
                    f"🔁 New PR #{number} in {repo}{draft}: '{title}' by @{user}"
                )
                new_seen.append(number)

            # Persist seen PR numbers
            self.state.setdefault("seen_pr_numbers", {})[repo] = new_seen[-100:]
            return alerts

        except Exception as exc:
            print(f"[GitWatcher] GitHub PR fetch failed: {exc}", flush=True)
            return []

    def _fetch_github_ci_status(self, owner: str, repo: str, token: str) -> List[str]:
        """
        Fetch latest GitHub Actions workflow run status.
        Alerts when a workflow transitions to failure or success.
        """
        try:
            import urllib.request
            import json as _json

            url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs?per_page=5"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "ANKITA/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())

            runs = data.get("workflow_runs", [])
            seen_runs: Dict[str, str] = self.state.get("seen_ci_runs", {})
            alerts = []

            for run in runs:
                run_id = str(run.get("id", ""))
                status = run.get("status", "")      # queued, in_progress, completed
                conclusion = run.get("conclusion")  # success, failure, cancelled, etc.
                name = run.get("name", "CI")
                branch = run.get("head_branch", "")

                prev_conclusion = seen_runs.get(run_id)
                if conclusion and conclusion != prev_conclusion:
                    seen_runs[run_id] = conclusion
                    if conclusion == "failure":
                        alerts.append(
                            f"❌ CI FAILED: [{repo}] '{name}' on branch '{branch}' — check GitHub Actions!"
                        )
                    elif conclusion == "success" and prev_conclusion == "failure":
                        # Only alert on recovery (was failing, now passing)
                        alerts.append(
                            f"✅ CI FIXED: [{repo}] '{name}' on branch '{branch}' is passing again!"
                        )

            # Keep only last 50 run IDs
            self.state["seen_ci_runs"] = dict(list(seen_runs.items())[-50:])
            return alerts

        except Exception as exc:
            print(f"[GitWatcher] GitHub CI status fetch failed: {exc}", flush=True)
            return []
