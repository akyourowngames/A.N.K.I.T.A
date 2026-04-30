from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.llm_service import load_dotenv


@dataclass(frozen=True)
class DaemonConfig:
    project_root: Path
    state_dir: Path
    interval_seconds: int
    report_path: Path
    run_tests: bool
    default_model: str
    review_model: str
    code_review_model: str
    writing_model: str
    summary_model: str

    @classmethod
    def from_root(cls, project_root: Path) -> "DaemonConfig":
        load_dotenv(project_root / ".env")
        state_dir = project_root / "daemon" / "state"
        return cls(
            project_root=project_root,
            state_dir=state_dir,
            interval_seconds=max(15, int(os.getenv("DAEMON_INTERVAL_SECONDS", "60"))),
            report_path=project_root / os.getenv("DAEMON_REPORT_PATH", "memory/data/daemon-report.md"),
            run_tests=os.getenv("DAEMON_RUN_TESTS", "true").strip().lower() in {"1", "true", "yes", "on"},
            default_model=os.getenv("DAEMON_DEFAULT_MODEL", os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct")),
            review_model=os.getenv("DAEMON_REVIEW_MODEL", os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct")),
            code_review_model=os.getenv("DAEMON_CODE_REVIEW_MODEL", os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct")),
            writing_model=os.getenv("DAEMON_WRITING_MODEL", os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct")),
            summary_model=os.getenv("DAEMON_SUMMARY_MODEL", os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct")),
        )
