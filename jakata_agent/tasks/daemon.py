from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from jakata_agent.tasks.store import TaskStore


@dataclass(slots=True)
class DaemonManager:
    data_dir: Path

    @property
    def daemon_dir(self) -> Path:
        path = self.data_dir / "daemon"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def pid_file(self) -> Path:
        return self.daemon_dir / "daemon.pid"

    @property
    def kill_switch(self) -> Path:
        return self.daemon_dir / "kill.switch"

    def ensure_running(self) -> None:
        pid = self._read_pid()
        if pid and self._pid_alive(pid):
            return
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | 0x00000008
        subprocess.Popen(
            [sys.executable, "-m", "jakata_agent.daemon_entry"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )

    def activate_kill_switch(self) -> None:
        self.kill_switch.write_text("1", encoding="utf-8")

    def clear_kill_switch(self) -> None:
        if self.kill_switch.exists():
            self.kill_switch.unlink()

    def _read_pid(self) -> int | None:
        try:
            return int(self.pid_file.read_text(encoding="utf-8").strip())
        except Exception:
            return None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


class TaskDaemon:
    def __init__(self, *, store: TaskStore, orchestrator, pid_file: Path, kill_switch: Path, poll_seconds: float = 2.0) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.pid_file = pid_file
        self.kill_switch = kill_switch
        self.poll_seconds = poll_seconds
        self.worker_id = f"worker-{os.getpid()}"

    def run_forever(self) -> None:
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(os.getpid()), encoding="utf-8")
        self.store.recover_incomplete_tasks()
        try:
            while True:
                if self.kill_switch.exists():
                    time.sleep(self.poll_seconds)
                    continue
                task = self.store.claim_next_task(self.worker_id)
                if task is None:
                    time.sleep(self.poll_seconds)
                    continue
                self.orchestrator.process_task(task)
        finally:
            try:
                if self.pid_file.exists() and self.pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    self.pid_file.unlink()
            except Exception:
                pass
