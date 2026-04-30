from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tool.registry import ToolRegistry
from tool.terminal import TerminalTool


@dataclass(frozen=True)
class CommandResult:
    command: str
    output: str


class DaemonTools:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.terminal = TerminalTool()
        self.ai_tools = ToolRegistry()

    def run_terminal(self, command: str, timeout: int = 120) -> CommandResult:
        return CommandResult(
            command=command,
            output=self.terminal.run(command, cwd=str(self.project_root), timeout=timeout),
        )

    def run_ai_tool(self, name: str, args: dict[str, Any]) -> str:
        return self.ai_tools.run(name, args)

    def git_status(self) -> str:
        return self._stdout(self.run_terminal("git status --short", timeout=30).output)

    def git_branch(self) -> str:
        return self._clean_terminal_output(self.run_terminal("git branch --show-current", timeout=30).output)

    def git_diff_stat(self) -> str:
        return self._stdout(self.run_terminal("git diff --stat", timeout=30).output)

    def git_log(self, limit: int = 5) -> str:
        return self._stdout(self.run_terminal(f"git log --oneline -{limit}", timeout=30).output)

    def changed_files(self) -> list[str]:
        result = self.git_status()
        files: list[str] = []
        for line in result.splitlines():
            if not line:
                continue
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                files.append(parts[1].strip())
        return files

    def github_summary(self) -> str:
        gh = shutil.which("gh")
        if gh:
            return self._stdout(self.run_terminal("gh repo view --json nameWithOwner,url,defaultBranchRef", timeout=30).output)
        remote = self._stdout(self.run_terminal("git remote -v", timeout=30).output)
        return f"GitHub CLI unavailable. Git remotes:\n{remote}"

    def test_summary(self) -> str:
        return self.run_terminal("python -m unittest discover -s tests -v", timeout=180).output

    @staticmethod
    def _clean_terminal_output(output: str) -> str:
        lines = [
            line.strip()
            for line in output.splitlines()
            if line.strip() and line not in {"stdout:", "stderr:", "<empty>"} and not line.startswith("exit_code:")
        ]
        return "\n".join(lines)

    @staticmethod
    def _stdout(output: str) -> str:
        lines = output.splitlines()
        if "stdout:" not in lines:
            return output.strip()
        start = lines.index("stdout:") + 1
        end = lines.index("stderr:") if "stderr:" in lines else len(lines)
        body = "\n".join(lines[start:end]).strip()
        return "" if body == "<empty>" else body

    def snapshot(self) -> dict[str, Any]:
        return {
            "project": self.project_overview(),
            "branch": self.git_branch(),
            "status": self.git_status(),
            "diff_stat": self.git_diff_stat(),
            "recent_commits": self.git_log(),
            "changed_files": self.changed_files(),
            "file_context": self.file_context(),
            "test_inventory": self.test_inventory(),
            "github": self.github_summary(),
        }

    def project_overview(self) -> dict[str, Any]:
        important_dirs = ["core", "tool", "skills", "daemon", "memory", "tests"]
        important_files = ["main.py", "persona.md", ".env.example"]
        dirs = [name for name in important_dirs if (self.project_root / name).exists()]
        files = [name for name in important_files if (self.project_root / name).exists()]
        python_files = [
            path.relative_to(self.project_root).as_posix()
            for path in self.project_root.rglob("*.py")
            if ".git" not in path.parts and "__pycache__" not in path.parts
        ]
        skill_files = [
            path.relative_to(self.project_root).as_posix()
            for path in (self.project_root / "skills").glob("*.md")
        ] if (self.project_root / "skills").exists() else []

        return {
            "name": self.project_root.name,
            "root": str(self.project_root),
            "directories": dirs,
            "files": files,
            "env_file_present": (self.project_root / ".env").exists(),
            "persona_excerpt": self._read_excerpt(self.project_root / "persona.md", max_chars=1200),
            "python_file_count": len(python_files),
            "python_files": python_files[:80],
            "skill_files": skill_files,
        }

    def file_context(self, max_files: int = 24, max_chars: int = 2500) -> dict[str, str]:
        candidates: list[str] = []
        candidates.extend(self.changed_files())
        project = self.project_overview()
        candidates.extend(project.get("files") or [])
        candidates.extend(project.get("skill_files") or [])
        candidates.extend(
            file_path
            for file_path in project.get("python_files", [])
            if file_path.startswith(("core/", "tool/", "daemon/"))
        )

        context: dict[str, str] = {}
        for relative in self._dedupe(candidates):
            if len(context) >= max_files:
                break
            path = (self.project_root / relative).resolve()
            if not self._is_readable_project_file(path):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            context[relative] = text[:max_chars]
        return context

    def test_inventory(self) -> list[str]:
        tests_dir = self.project_root / "tests"
        if not tests_dir.exists():
            return []

        names: list[str] = []
        for path in tests_dir.rglob("test*.py"):
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("def test_"):
                    test_name = stripped.split("(", 1)[0].removeprefix("def ")
                    names.append(f"{path.relative_to(self.project_root).as_posix()}::{test_name}")
        return names[:200]

    def _is_readable_project_file(self, path: Path) -> bool:
        try:
            path.relative_to(self.project_root.resolve())
        except ValueError:
            return False
        if not path.is_file():
            return False
        if any(part in {".git", "__pycache__", "state"} for part in path.parts):
            return False
        return path.suffix.lower() in {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".example"}

    @staticmethod
    def _read_excerpt(path: Path, max_chars: int) -> str:
        if not path.exists() or not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except OSError:
            return ""

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            normalized = item.replace("\\", "/").strip()
            if normalized and normalized not in seen:
                result.append(normalized)
                seen.add(normalized)
        return result
