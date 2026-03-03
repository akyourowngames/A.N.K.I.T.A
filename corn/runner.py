import threading
import time
from pathlib import Path

from .service import CornService


class CornRunner:
    def __init__(self, workspace_root: Path, poll_interval_sec: float = 5.0, max_jobs_per_tick: int = 5):
        self.workspace_root = workspace_root
        self.poll_interval_sec = max(1.0, min(float(poll_interval_sec), 300.0))
        self.max_jobs_per_tick = max(1, min(int(max_jobs_per_tick), 50))
        self._service = CornService(workspace_root=workspace_root)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ankita-corn-runner", daemon=True)
        self._thread.start()

    def stop(self, timeout_sec: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.1, timeout_sec))

    def tick(self) -> dict:
        return self._service.run_due(max_jobs=self.max_jobs_per_tick)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                # best-effort background worker; keep running
                pass
            self._stop.wait(self.poll_interval_sec)

