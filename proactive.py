"""
Proactive engine for A.N.K.I.T.A.

Runs background checks and feeds events into a queue so the GUI/chat
can display unsolicited alerts — making ANKITA feel truly proactive.

Checks:
  - System resources (CPU, RAM, battery) via psutil (optional)
  - Due cron jobs
  - Drop-file events in .ankita/proactive_events/ directory
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import psutil  # type: ignore

    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False


_DEFAULT_INTERVAL = float(os.getenv("PROACTIVE_INTERVAL_SEC", "15"))
_CPU_ALERT_THRESHOLD = float(os.getenv("PROACTIVE_CPU_THRESHOLD", "85"))
_RAM_ALERT_THRESHOLD = float(os.getenv("PROACTIVE_RAM_THRESHOLD", "88"))
_BATTERY_ALERT_THRESHOLD = float(os.getenv("PROACTIVE_BATTERY_THRESHOLD", "15"))
# NOTE: _IDLE_THRESHOLD_SEC is intentionally NOT read here at module level,
# because load_dotenv() runs after import. It is read lazily inside _check_idle().


class ProactiveEvent:
    """A single proactive notification from the background engine."""

    def __init__(self, kind: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        self.kind = kind  # "system", "cron", "drop_file", "custom"
        self.message = message
        self.data = data or {}
        self.ts = time.time()

    def __repr__(self) -> str:
        return f"<ProactiveEvent kind={self.kind!r} message={self.message[:60]!r}>"


class ProactiveEngine:
    """
    Background thread that emits proactive events.

    Usage:
        engine = ProactiveEngine(workspace_root)
        engine.start()
        # In your UI loop:
        for event in engine.get_pending_events():
            show_notification(event.message)
        engine.stop()
    """

    def __init__(self, workspace_root: Path, interval_sec: float = _DEFAULT_INTERVAL) -> None:
        self.workspace_root = workspace_root
        self.interval_sec = interval_sec
        self._queue: queue.Queue[ProactiveEvent] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Thresholds for system alerts (avoid repeated alerts)
        self._alerted_cpu = False
        self._alerted_ram = False
        self._alerted_battery = False

        # Track seen drop-files
        self._seen_drop_files: set = set()

        # Drop-file directory
        self._drop_dir = workspace_root / ".ankita" / "proactive_events"
        self._drop_dir.mkdir(parents=True, exist_ok=True)

        # Raw-ideas directory (ContentAgent trigger)
        self._raw_ideas_dir = workspace_root / ".ankita" / "raw_ideas"
        self._raw_ideas_dir.mkdir(parents=True, exist_ok=True)
        self._seen_raw_ideas: set = set()

        # Idle / DreamState tracking
        self._last_interaction: float = time.time()  # epoch seconds
        self._dream_pending: bool = False             # True while dream is queued or synthesizing
        self._memory_store: Optional[Any] = None     # injected by caller after init
        self._session_id: str = "default"            # injected by caller

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            print("[ProactiveEngine] Already running — skipping start.", flush=True)
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ProactiveEngine")
        self._thread.start()
        print(f"[ProactiveEngine] Thread launched. is_alive={self._thread.is_alive()}", flush=True)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_sec + 2)

    def get_pending_events(self) -> List[ProactiveEvent]:
        """Drain and return all pending events (non-blocking)."""
        events: List[ProactiveEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def push_custom(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Manually push a custom event (e.g. from cron worker)."""
        self._queue.put(ProactiveEvent("custom", message, data))

    def set_last_interaction(self, ts: Optional[float] = None) -> None:
        """
        Record the time of the most recent user interaction.

        Call this from the GUI (on_send, voice done) and from the CLI main
        loop (after reading user input) so the idle tracker stays accurate.

        Args:
            ts: epoch seconds — defaults to now if not provided.
        """
        self._last_interaction = ts if ts is not None else time.time()
        # If the user is back, allow a fresh dream on the next idle period
        self._dream_pending = False

    def attach_memory(self, memory_store: Any, session_id: str = "default") -> None:
        """
        Attach the MemoryStore so the DreamAgent can retrieve ChromaDB memories.

        Call this once after both ProactiveEngine and MemoryStore are initialized.

        Args:
            memory_store: The active MemoryStore instance.
            session_id:   The current chat session ID.
        """
        self._memory_store = memory_store
        self._session_id = session_id

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        print(f"[ProactiveEngine] Started. Poll interval: {self.interval_sec}s", flush=True)
        while not self._stop_event.is_set():
            try:
                self._check_system_resources()
                self._check_drop_files()
                self._check_cron_overdue()
                self._check_raw_ideas()
                self._check_idle()
            except Exception as _e:
                print(f"[ProactiveEngine] ERROR in poll cycle: {_e}", flush=True)
            self._stop_event.wait(timeout=self.interval_sec)

    def _check_system_resources(self) -> None:
        if not HAS_PSUTIL:
            return

        # CPU
        cpu = psutil.cpu_percent(interval=1)
        if cpu >= _CPU_ALERT_THRESHOLD:
            if not self._alerted_cpu:
                self._alerted_cpu = True
                self._queue.put(ProactiveEvent(
                    "system",
                    f"⚠️ High CPU usage detected: {cpu:.0f}%. You may want to close some applications.",
                    {"cpu_percent": cpu},
                ))
        else:
            self._alerted_cpu = False

        # RAM
        ram = psutil.virtual_memory()
        ram_pct = ram.percent
        if ram_pct >= _RAM_ALERT_THRESHOLD:
            if not self._alerted_ram:
                self._alerted_ram = True
                used_gb = ram.used / (1024 ** 3)
                total_gb = ram.total / (1024 ** 3)
                self._queue.put(ProactiveEvent(
                    "system",
                    f"⚠️ RAM usage is high: {ram_pct:.0f}% ({used_gb:.1f}/{total_gb:.1f} GB used).",
                    {"ram_percent": ram_pct},
                ))
        else:
            self._alerted_ram = False

        # Battery
        try:
            batt = psutil.sensors_battery()
            if batt is not None and not batt.power_plugged:
                pct = batt.percent
                if pct <= _BATTERY_ALERT_THRESHOLD:
                    if not self._alerted_battery:
                        self._alerted_battery = True
                        self._queue.put(ProactiveEvent(
                            "system",
                            f"🔋 Battery low: {pct:.0f}%. Please plug in your charger.",
                            {"battery_percent": pct},
                        ))
                else:
                    self._alerted_battery = False
            else:
                self._alerted_battery = False
        except Exception:
            pass

    def _check_drop_files(self) -> None:
        """Process any JSON or .txt files dropped into .ankita/proactive_events/."""
        try:
            for fpath in sorted(self._drop_dir.iterdir()):
                if fpath.name in self._seen_drop_files:
                    continue
                if not fpath.is_file():
                    continue
                self._seen_drop_files.add(fpath.name)
                try:
                    text = fpath.read_text(encoding="utf-8").strip()
                    if fpath.suffix == ".json":
                        payload = json.loads(text)
                        msg = str(payload.get("message", text[:200]))
                        data = payload if isinstance(payload, dict) else {}
                    else:
                        msg = text[:500]
                        data = {}
                    self._queue.put(ProactiveEvent("drop_file", msg, data))
                    # Remove after processing
                    try:
                        fpath.unlink()
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass

    def _check_raw_ideas(self) -> None:
        """
        Watch .ankita/raw_ideas/ for new .txt files dropped by the user.

        When a new file is detected it is read, marked as seen, and a
        ProactiveEvent of kind 'content_request' is pushed to the queue.
        The consumer (GUI / chat loop) should forward this to the
        Orchestrator → ContentAgent, which will call write_content and
        speak the result via TTS.

        The raw file is NOT deleted here — the ContentAgent may want to
        read it directly via read_file as extra_context.
        """
        try:
            for fpath in sorted(self._raw_ideas_dir.iterdir()):
                if fpath.name in self._seen_raw_ideas:
                    continue
                if not fpath.is_file():
                    continue
                if fpath.suffix.lower() not in {".txt", ".md", ".text"}:
                    continue

                self._seen_raw_ideas.add(fpath.name)
                try:
                    raw_text = fpath.read_text(encoding="utf-8", errors="replace").strip()
                except Exception:
                    raw_text = ""

                # Auto-detect format and topic from filename + file content
                stem = fpath.stem.replace("_", " ").replace("-", " ").strip()
                try:
                    from tools.content_ops import detect_format_type  # type: ignore
                    detected_format, detected_topic = detect_format_type(stem, raw_text)
                except Exception:
                    detected_format = "content"
                    detected_topic = stem if stem else "your raw notes"

                message = (
                    f"📝 New idea file detected: '{fpath.name}'. "
                    f"Generating a {detected_format} about '{detected_topic}' now."
                )

                self._queue.put(ProactiveEvent(
                    "content_request",
                    message,
                    {
                        "file_path": str(fpath),
                        "file_name": fpath.name,
                        "topic": detected_topic,
                        "format_type": detected_format,
                        "raw_text": raw_text[:2000],   # Cap preview; agent reads full file
                        "suggested_prompt": (
                            f"Write a {detected_format} about '{detected_topic}'. "
                            f"Use these rough notes as context: {raw_text[:1000]}"
                            if raw_text else
                            f"Write a {detected_format} about '{detected_topic}' and save it to the Desktop."
                        ),
                    },
                ))
        except Exception:
            pass

    def _check_idle(self) -> None:
        """
        Check if the user has been idle long enough to trigger a DreamState.

        Fires at most once per idle session (reset by set_last_interaction).
        Runs the DreamAgent in a separate daemon thread so the poll loop
        never blocks waiting for the LLM.
        """
        if self._dream_pending:
            print(f"[DreamAgent] Skipping — dream already pending.", flush=True)
            return  # Already synthesising or queued — don't pile up dreams

        # Read lazily so load_dotenv() in chat.py/gui.py has already run by now
        idle_threshold = float(os.getenv("ANKITA_IDLE_SECONDS", "3600"))

        idle_sec = time.time() - self._last_interaction
        print(f"[DreamAgent] Idle: {idle_sec:.1f}s / threshold: {idle_threshold}s  memory={'attached' if self._memory_store else 'MISSING'}", flush=True)

        if idle_sec < idle_threshold:
            return  # Not idle long enough yet

        if self._memory_store is None:
            print(f"[DreamAgent] ⚠️  No memory store attached — cannot synthesize.", flush=True)
            return  # No memory attached — skip silently

        print(f"[DreamAgent] 🌙 Idle threshold crossed! Spawning DreamSynthesis thread...", flush=True)

        # Mark as pending so we don't spawn duplicate threads
        self._dream_pending = True

        memory_store = self._memory_store
        session_id = self._session_id

        def _synthesize() -> None:
            print(f"[DreamAgent] 🧠 Synthesizing epiphany from memory (session={session_id})...", flush=True)
            try:
                from agents.dream_agent import DreamAgent  # type: ignore
                agent = DreamAgent()
                epiphany = agent.synthesize(
                    memory_store=memory_store,
                    session_id=session_id,
                )
                if epiphany:
                    print(f"[DreamAgent] ✅ Epiphany generated: {epiphany[:80]}...", flush=True)
                    idle_hrs = idle_sec / 3600
                    idle_label = (
                        f"{idle_hrs:.1f} hours" if idle_hrs >= 1
                        else f"{idle_sec / 60:.0f} minutes"
                    )
                    self._queue.put(ProactiveEvent(
                        "dream_epiphany",
                        epiphany,
                        {
                            "text": epiphany,
                            "idle_seconds": idle_sec,
                            "idle_label": idle_label,
                        },
                    ))
                else:
                    print(f"[DreamAgent] ⚠️  No epiphany returned (empty or None) — will retry next cycle.", flush=True)
                    # No epiphany generated — reset so it can try next cycle
                    self._dream_pending = False
            except Exception as _e:
                print(f"[DreamAgent] ❌ Exception in synthesis: {_e}", flush=True)
                self._dream_pending = False  # Allow retry on next idle check

        threading.Thread(target=_synthesize, daemon=True, name="DreamSynthesis").start()

    def _check_cron_overdue(self) -> None:
        """Check if any cron jobs are significantly overdue."""
        jobs_file = self.workspace_root / ".ankita" / "corn" / "jobs.json"
        if not jobs_file.exists():
            return
        try:
            data = json.loads(jobs_file.read_text(encoding="utf-8"))
            jobs = data if isinstance(data, list) else []
            now_ms = time.time() * 1000
            overdue_threshold_ms = 5 * 60 * 1000  # 5 minutes overdue
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                if not job.get("enabled", True):
                    continue
                state = job.get("state", {})
                if not isinstance(state, dict):
                    continue
                next_run = state.get("next_run_at_ms")
                if next_run is None:
                    continue
                overdue_ms = now_ms - next_run
                if overdue_ms >= overdue_threshold_ms:
                    name = job.get("name", job.get("id", "unknown"))
                    mins = overdue_ms / 60000
                    self._queue.put(ProactiveEvent(
                        "cron",
                        f"🕐 Scheduled task '{name}' is {mins:.0f} min overdue.",
                        {"job_id": job.get("id"), "overdue_ms": overdue_ms},
                    ))
        except Exception:
            pass
