import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .service import CornService


# Type for the callback that delivers heartbeat results to the user
# Signature: deliver_fn(job_name: str, result_text: str) -> None
HeartbeatDeliveryFn = Callable[[str, str], None]


class CornRunner:
    """Background poller that fires due cron jobs every N seconds.

    Supports three payload kinds:
      - command: run a shell command (original)
      - note:    fire-and-forget text (original)
      - agent:   route a prompt through the full ANKITA orchestrator pipeline
                  and deliver the result via ``delivery_fn`` (OpenClaw-style heartbeat)
    """

    def __init__(
        self,
        workspace_root: Path,
        poll_interval_sec: float = 5.0,
        max_jobs_per_tick: int = 5,
    ):
        self.workspace_root = workspace_root
        self.poll_interval_sec = max(1.0, min(float(poll_interval_sec), 300.0))
        self.max_jobs_per_tick = max(1, min(int(max_jobs_per_tick), 50))
        self._service = CornService(workspace_root=workspace_root)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # --- Heartbeat wiring ---
        # Set these after construction to enable agent-payload execution.
        self._orchestrator: Any = None       # agents.Orchestrator instance
        self._runtime: Any = None            # LLMRuntime instance
        self._delivery_fn: Optional[HeartbeatDeliveryFn] = None

    # ── Public API ──────────────────────────────────────────────────────
    def attach_orchestrator(self, orchestrator: Any, runtime: Any) -> None:
        """Wire up the agent pipeline so ``agent`` payloads can execute."""
        self._orchestrator = orchestrator
        self._runtime = runtime

    def set_delivery_fn(self, fn: HeartbeatDeliveryFn) -> None:
        """Set the callback that delivers heartbeat results (e.g. Telegram send)."""
        self._delivery_fn = fn

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
        return self._service.run_due(
            max_jobs=self.max_jobs_per_tick,
            executor=self._heartbeat_executor,
        )

    # ── Heartbeat executor ──────────────────────────────────────────────
    def _heartbeat_executor(self, payload: Dict[str, Any], workspace_root: Path) -> Dict[str, Any]:
        """Custom executor that intercepts ``agent`` payload kinds and runs
        the prompt through the full orchestrator, then delivers via callback."""
        kind = str(payload.get("kind", "")).strip().lower()
        if kind != "agent":
            # Fall through to default (command / note) handled by CornService
            # Remove injected metadata before passing back
            clean = {k: v for k, v in payload.items() if not k.startswith("_")}
            return self._service._execute_payload({"payload": clean}, executor=None)

        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            return {"ok": False, "error": "agent payload missing prompt"}

        if self._orchestrator is None or self._runtime is None:
            return {"ok": False, "error": "orchestrator not attached — agent jobs disabled"}

        try:
            from agent_runtime import new_session
            messages = new_session(prompt)
            reply = self._orchestrator.run(user_text=prompt, messages=messages)
            result_text = reply or "(empty response)"

            # Deliver to user (Telegram, CLI, etc.)
            if self._delivery_fn:
                job_name = payload.get("_job_name", "Scheduled Task")
                try:
                    self._delivery_fn(job_name, result_text)
                except Exception as dfn_err:
                    print(f"[heartbeat-delivery-error] {dfn_err}")

            return {"ok": True, "reply": result_text[:500]}
        except Exception as exc:
            error_msg = f"agent execution failed: {exc}"
            print(f"[heartbeat-agent-error] {error_msg}")
            return {"ok": False, "error": error_msg}

    # ── Background loop ─────────────────────────────────────────────────
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as err:
                print(f"[corn-runner-error] {err}")
            self._stop.wait(self.poll_interval_sec)

