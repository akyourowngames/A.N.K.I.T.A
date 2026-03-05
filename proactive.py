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

from proactive_models import ProactiveEvent

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

        # Persistent proactive state (.ankita/state/proactive_state.json)
        self._state_path = self.workspace_root / ".ankita" / "state" / "proactive_state.json"
        self._proactive_state: Dict[str, Any] = self._load_state()

        # Thresholds for system alerts (avoid repeated alerts)
        self._alerted_cpu = False
        self._alerted_ram = False
        self._alerted_battery = False
        
        # Cooldown timestamps to prevent spam (30 minutes between same-type alerts)
        self._last_cpu_alert: float = 0
        self._last_ram_alert: float = 0
        self._last_battery_alert: float = 0
        self._alert_cooldown_sec: float = 1800  # 30 minutes

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

        # Sentinel (Screen-watching idle alert) tracking
        self._sentinel_triggered: bool = False       # True once sentinel fires; reset when user returns
        self._runtime: Optional[Any] = None          # LLM runtime injected by caller

        # Morning briefing: only one thread at a time, don't re-run same day
        self._morning_briefing_pending: bool = False

        # ── Proactive Intelligence Components (Steps 5, 7, 9) ──────────────
        # IntentionEngine — refreshes intent.json every 6 hours
        self._intent_refresh_pending: bool = False
        try:
            from tools.intention_engine import IntentionEngine  # type: ignore
            self._intention_engine = IntentionEngine(workspace_root)
        except Exception:
            self._intention_engine = None  # type: ignore

        # BehavioralPatternLearner — analyses patterns weekly (Sunday 22:00-23:00)
        self._pattern_analysis_pending: bool = False
        try:
            from tools.behavioral_pattern_learner import BehavioralPatternLearner  # type: ignore
            self._pattern_learner = BehavioralPatternLearner(workspace_root)
        except Exception:
            self._pattern_learner = None  # type: ignore

        # AnticipatoryActionSystem — pre-fetches likely actions each poll cycle
        self._last_anticipatory_run: float = 0.0
        try:
            from tools.anticipatory_action_system import AnticipatoryActionSystem  # type: ignore
            self._anticipatory = AnticipatoryActionSystem(workspace_root)
        except Exception:
            self._anticipatory = None  # type: ignore

        # AutoExecutor (Step 8) — Class A/B/C autonomous background actions
        try:
            from agents.auto_executor import AutoExecutor  # type: ignore
            self._auto_executor = AutoExecutor(workspace_root)
        except Exception:
            self._auto_executor = None  # type: ignore

        # InsightSynthesizer (Step 12) — 12h insight generation
        self._insight_synthesis_pending: bool = False
        try:
            from agents.insight_synthesizer import InsightSynthesizer  # type: ignore
            self._insight_synthesizer = InsightSynthesizer(workspace_root)
        except Exception:
            self._insight_synthesizer = None  # type: ignore

    # ------------------------------------------------------------------
    # Persistent state helpers
    # ------------------------------------------------------------------

    def _load_state(self) -> Dict[str, Any]:
        """
        Load persistent proactive state from disk.

        Schema (keys may be extended over time):
            - last_morning_briefing_date: str | None (YYYY-MM-DD)
            - last_intent_refresh: float (epoch seconds)
            - last_pattern_analysis: float (epoch seconds)
            - last_insight_synthesis: float (epoch seconds)
            - delivered_notification_ids: list[str]
            - dnd_active: bool
        """
        state_dir = self.workspace_root / ".ankita" / "state"
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # If we cannot create the directory, fall back to in-memory only state.
            pass

        default_state: Dict[str, Any] = {
            "last_morning_briefing_date": None,
            "last_intent_refresh": 0.0,
            "last_pattern_analysis": 0.0,
            "last_insight_synthesis": 0.0,
            "delivered_notification_ids": [],
            "dnd_active": False,
            # Cached value of ANKITA_DND_HOURS at startup (e.g. "22:00-08:00,13:00-14:00")
            "dnd_hours": os.getenv("ANKITA_DND_HOURS", "").strip(),
        }

        try:
            if self._state_path.exists():
                raw = self._state_path.read_text(encoding="utf-8")
                loaded = json.loads(raw) if raw.strip() else {}
                if isinstance(loaded, dict):
                    # Merge any known keys from disk over defaults
                    default_state.update(loaded)
        except Exception:
            # Corrupt or unreadable state file — ignore and start fresh
            pass

        # Normalise types
        if not isinstance(default_state.get("delivered_notification_ids"), list):
            default_state["delivered_notification_ids"] = []
        if not isinstance(default_state.get("last_intent_refresh"), (int, float)):
            default_state["last_intent_refresh"] = 0.0
        if not isinstance(default_state.get("last_pattern_analysis"), (int, float)):
            default_state["last_pattern_analysis"] = 0.0
        if not isinstance(default_state.get("last_insight_synthesis"), (int, float)):
            default_state["last_insight_synthesis"] = 0.0
        if not isinstance(default_state.get("dnd_active"), bool):
            default_state["dnd_active"] = bool(default_state.get("dnd_active"))

        # Persist a clean copy back to disk so future readers have a valid file.
        self._save_state(default_state)
        return default_state

    def _save_state(self, state: Optional[Dict[str, Any]] = None) -> None:
        """Persist the current proactive state to disk (best-effort, non-fatal)."""
        if state is None:
            state = self._proactive_state

        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(self._state_path)
        except Exception:
            # Persistence failures must never crash the engine loop.
            pass

    def update_state(self, **updates: Any) -> None:
        """
        Update in-memory proactive state and persist it.

        Example:
            engine.update_state(last_intent_refresh=time.time())
        """
        self._proactive_state.update(updates)
        self._save_state()

    def get_state(self) -> Dict[str, Any]:
        """Return a shallow copy of the current proactive state."""
        return dict(self._proactive_state)

    # ------------------------------------------------------------------
    # Morning briefing (first boot of day)
    # ------------------------------------------------------------------

    def _check_morning_briefing(self) -> None:
        """
        If it's a new day since last_morning_briefing_date, generate and push
        a morning briefing once. Runs in a daemon thread so the poll loop doesn't block.
        """
        from datetime import datetime as _dt
        today_ymd = _dt.now().strftime("%Y-%m-%d")
        last = self._proactive_state.get("last_morning_briefing_date")
        if last == today_ymd:
            return
        if self._runtime is None or self._morning_briefing_pending:
            return

        self._morning_briefing_pending = True
        runtime = self._runtime
        workspace_root = self.workspace_root

        def _do_briefing() -> None:
            try:
                from agents.morning_agent import generate_briefing  # type: ignore

                # Load intent.json
                intent = {}
                intent_path = workspace_root / ".ankita" / "state" / "intent.json"
                if intent_path.exists():
                    try:
                        intent = json.loads(intent_path.read_text(encoding="utf-8"))
                        if not isinstance(intent, dict):
                            intent = {}
                    except Exception:
                        pass

                # Tasks summary
                tasks_summary = ""
                try:
                    from tools.task_ops import task_op  # type: ignore
                    r = task_op(action="list")
                    if r.get("status") == "success":
                        tasks = r.get("tasks", [])
                        pending = [t for t in tasks if t.get("status") in ("pending", "in_progress")]
                        overdue_r = task_op(action="overdue")
                        overdue = overdue_r.get("tasks", []) if overdue_r.get("status") == "success" else []
                        if pending or overdue:
                            parts = []
                            if overdue:
                                parts.append(f"{len(overdue)} overdue")
                            if pending:
                                parts.append(f"{len(pending)} pending")
                            tasks_summary = "Tasks: " + ", ".join(parts) + ". " + " ".join(
                                t.get("title", "")[:50] for t in (overdue[:2] + pending[:2])
                            )
                except Exception:
                    pass

                # Watchdog status
                watchdog_state = ""
                try:
                    from watchdog_manager import get_instance  # type: ignore
                    mgr = get_instance()
                    if mgr is not None:
                        watchdog_state = mgr.status()
                except Exception:
                    pass

                # System stats (disk, battery)
                system_stats = {}
                if HAS_PSUTIL:
                    try:
                        disk = psutil.disk_usage(str(workspace_root))
                        system_stats["disk_pct"] = round(disk.percent, 0)
                    except Exception:
                        pass
                    try:
                        batt = psutil.sensors_battery()
                        if batt is not None:
                            system_stats["battery_pct"] = batt.percent
                            system_stats["battery_plugged"] = batt.power_plugged
                    except Exception:
                        pass

                # Cron due today (simplified: just next few jobs from corn)
                cron_today = []
                try:
                    corn_file = workspace_root / ".ankita" / "corn" / "jobs.json"
                    if corn_file.exists():
                        data = json.loads(corn_file.read_text(encoding="utf-8"))
                        jobs = data if isinstance(data, list) else []
                        for j in jobs[:5]:
                            if isinstance(j, dict) and j.get("enabled", True):
                                name = j.get("name", j.get("id", "task"))
                                cron_today.append(name)
                except Exception:
                    pass

                briefing = generate_briefing(
                    runtime=runtime,
                    intent=intent,
                    tasks_summary=tasks_summary or None,
                    watchdog_state=watchdog_state or None,
                    system_stats=system_stats or None,
                    cron_today=cron_today or None,
                )
                if briefing:
                    self._queue.put(
                        ProactiveEvent(
                            kind="morning_briefing",
                            message=briefing,
                            data={"text": briefing},
                            priority="high",
                            urgency="immediate",
                            interruptible=True,
                        )
                    )
                    self.update_state(last_morning_briefing_date=today_ymd)
                    print("[ProactiveEngine] Morning briefing sent.", flush=True)
            except Exception as e:
                print(f"[ProactiveEngine] Morning briefing failed: {e}", flush=True)
            finally:
                self._morning_briefing_pending = False

        threading.Thread(target=_do_briefing, daemon=True, name="MorningBriefing").start()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            print("[ProactiveEngine] Already running — skipping start.", flush=True)
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ProactiveEngine")
        self._thread.start()
        print(f"[ProactiveEngine] Thread launched. is_alive={self._thread.is_alive()}", flush=True)
        # Inject queue reference into AnticipatoryActionSystem for environment events
        if self._anticipatory is not None:
            try:
                from tools.anticipatory_action_system import _set_proactive_queue  # type: ignore
                _set_proactive_queue(self._queue)
            except Exception:
                pass

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
        self._queue.put(ProactiveEvent(kind="custom", message=message, data=data or {}))

    def set_last_interaction(self, ts: Optional[float] = None) -> None:
        """
        Record the time of the most recent user interaction.

        Call this from the GUI (on_send, voice done) and from the CLI main
        loop (after reading user input) so the idle tracker stays accurate.

        Args:
            ts: epoch seconds — defaults to now if not provided.
        """
        self._last_interaction = ts if ts is not None else time.time()
        # If the user is back, allow a fresh dream and sentinel on the next idle period
        self._dream_pending = False
        self._sentinel_triggered = False

    def attach_runtime(self, runtime: Any) -> None:
        """
        Inject the LLM runtime so the Sentinel can call the ScreenAgent.

        Call this once after the runtime is built (in chat.py / gui.py).

        Args:
            runtime: The active LLMRuntime instance.
        """
        self._runtime = runtime
        # Propagate runtime to intelligence components that need LLM access
        if self._intention_engine is not None:
            try:
                self._intention_engine.attach_runtime(runtime)
            except Exception:
                pass
        if self._pattern_learner is not None:
            try:
                self._pattern_learner.attach_runtime(runtime)
            except Exception:
                pass
        if self._insight_synthesizer is not None:
            try:
                self._insight_synthesizer.attach_runtime(runtime)
            except Exception:
                pass


    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        print(f"[ProactiveEngine] Started. Poll interval: {self.interval_sec}s", flush=True)
        while not self._stop_event.is_set():
            try:
                self._check_morning_briefing()
                self._check_system_resources()
                self._check_drop_files()
                self._check_cron_overdue()
                self._check_raw_ideas()
                self._check_idle()
                self._check_sentinel()
                # ── Proactive Intelligence Components ─────────────────────
                self._check_intention_engine()   # Step 5: 6-hour intent refresh
                self._check_pattern_learner()    # Step 7: weekly pattern analysis
                self._check_anticipatory()       # Step 9: pre-fetch likely actions
                self._check_auto_executor()      # Step 8: Class A/B/C actions
                self._check_insight_synthesizer()  # Step 12: 12h insight generation
            except Exception as _e:
                print(f"[ProactiveEngine] ERROR in poll cycle: {_e}", flush=True)
            self._stop_event.wait(timeout=self.interval_sec)

    def _check_system_resources(self) -> None:
        if not HAS_PSUTIL:
            return

        now = time.time()

        # CPU
        cpu = psutil.cpu_percent(interval=1)
        if cpu >= _CPU_ALERT_THRESHOLD:
            if not self._alerted_cpu and (now - self._last_cpu_alert) >= self._alert_cooldown_sec:
                self._alerted_cpu = True
                self._last_cpu_alert = now
                self._queue.put(ProactiveEvent(
                    "system",
                    f"⚠️ High CPU usage detected: {cpu:.0f}%. You may want to close some applications.",
                    {"cpu_percent": cpu},
                    priority="high",
                    urgency="immediate",
                ))
        else:
            self._alerted_cpu = False

        # RAM
        ram = psutil.virtual_memory()
        ram_pct = ram.percent
        if ram_pct >= _RAM_ALERT_THRESHOLD:
            if not self._alerted_ram and (now - self._last_ram_alert) >= self._alert_cooldown_sec:
                self._alerted_ram = True
                self._last_ram_alert = now
                used_gb = ram.used / (1024 ** 3)
                total_gb = ram.total / (1024 ** 3)
                self._queue.put(ProactiveEvent(
                    "system",
                    f"⚠️ RAM usage is high: {ram_pct:.0f}% ({used_gb:.1f}/{total_gb:.1f} GB used).",
                    {"ram_percent": ram_pct},
                    priority="high",
                    urgency="immediate",
                ))
        else:
            self._alerted_ram = False

        # Battery
        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                pct = batt.percent
                # Low battery alert (when unplugged)
                if not batt.power_plugged and pct <= _BATTERY_ALERT_THRESHOLD:
                    if not self._alerted_battery and (now - self._last_battery_alert) >= self._alert_cooldown_sec:
                        self._alerted_battery = True
                        self._last_battery_alert = now
                        self._queue.put(ProactiveEvent(
                            "system",
                            f"🔋 Battery low: {pct:.0f}%. Please plug in your charger.",
                            {"battery_percent": pct},
                            priority="high",
                            urgency="immediate",
                        ))
                # Full battery alert (when plugged in) - lower priority, longer cooldown
                elif batt.power_plugged and pct >= 100:
                    # Only alert once per 6 hours for "battery full" messages
                    if (now - self._last_battery_alert) >= (self._alert_cooldown_sec * 12):
                        self._last_battery_alert = now
                        self._queue.put(ProactiveEvent(
                            "system",
                            f"🔋 Battery is at {pct:.0f}% and still charging. Consider unplugging to preserve battery health.",
                            {"battery_percent": pct},
                            priority="low",
                            urgency="next_session",
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
                    self._queue.put(
                        ProactiveEvent(
                            kind="drop_file",
                            message=msg,
                            data=data,
                            priority="medium",
                            urgency="next_idle",
                        )
                    )
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

                self._queue.put(
                    ProactiveEvent(
                        kind="content_request",
                        message=message,
                        data={
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
                        priority="medium",
                        urgency="next_idle",
                        interruptible=True,
                    )
                )
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
        # DreamAgent currently disabled - needs new memory system
        return

    def _check_sentinel(self) -> None:
        """
        Proactive Sentinel — watches the screen when the user is idle.

        When the user hasn't touched the mouse/keyboard for SENTINEL_IDLE_SECONDS
        (default 300 = 5 min), this method:
          1. Captures the screen via the existing capture_screen() tool.
          2. Runs the ScreenAgent with a SYSTEM ALERT prompt (vision-injected).
          3. Pushes the agent's reply as a ProactiveEvent of kind 'sentinel'.
          4. Sets _sentinel_triggered so it fires only ONCE per idle session.

        The trigger resets when set_last_interaction() is called (user returns).

        Requires:
          - attach_runtime(runtime) must be called before starting the engine.
          - mss and Pillow must be installed (for capture_screen).
          - SENTINEL_IDLE_SECONDS env var (default 300).
          - SENTINEL_ENABLED=false to disable (opt-out).
        """
        # Opt-out guard
        if os.getenv("SENTINEL_ENABLED", "true").lower() == "false":
            return

        if self._sentinel_triggered:
            # Check if user has returned (idle dropped below 5s → reset)
            try:
                from tools.idle_ops import get_idle_seconds  # type: ignore
                if get_idle_seconds() < 5.0:
                    print("[Sentinel] 👋 User returned. Resetting watch.", flush=True)
                    self._sentinel_triggered = False
            except Exception:
                pass
            return  # Already fired this idle session — don't fire again

        if self._runtime is None:
            return  # No runtime attached — can't call ScreenAgent

        # Read threshold lazily (load_dotenv already ran by now)
        sentinel_threshold = float(os.getenv("SENTINEL_IDLE_SECONDS", "300"))

        # Use idle_ops for accurate OS-level idle time (mouse + keyboard)
        try:
            from tools.idle_ops import get_idle_seconds  # type: ignore
            idle_sec = get_idle_seconds()
        except Exception:
            # Fallback: use internal last_interaction timestamp
            idle_sec = time.time() - self._last_interaction

        print(f"[Sentinel] Idle: {idle_sec:.1f}s / threshold: {sentinel_threshold}s", flush=True)

        if idle_sec < sentinel_threshold:
            return  # Not idle long enough yet

        # Mark triggered BEFORE spawning thread to prevent duplicate fires
        self._sentinel_triggered = True
        runtime = self._runtime

        def _sentinel_task() -> None:
            print(f"[Sentinel] 🔍 User idle for {idle_sec:.0f}s — capturing screen...", flush=True)
            try:
                from tools.desktop_ops import capture_screen  # type: ignore
                screen = capture_screen(monitor=1)

                if not screen.get("ok"):
                    print(f"[Sentinel] ❌ capture_screen failed: {screen.get('error')}", flush=True)
                    self._sentinel_triggered = False
                    return

                b64 = screen.get("base64", "")
                if not b64:
                    self._sentinel_triggered = False
                    return

                # Build the SYSTEM ALERT prompt for ScreenAgent
                idle_label = f"{idle_sec / 60:.0f} minutes" if idle_sec >= 60 else f"{idle_sec:.0f} seconds"
                system_alert_prompt = (
                    f"SYSTEM ALERT: The user has been idle for {idle_label}. "
                    "Look at the attached screenshot of their screen. "
                    "Identify what they are working on or where they are stuck. "
                    "If you see an error, empty page, or obvious blocker — offer specific actionable help. "
                    "Be brief (1-2 sentences), casual, and low-pressure. "
                    "Do NOT ask generic questions like 'Can I help?' — be specific. "
                    "Examples:\n"
                    "  Good: 'Hey, I see a NameError on line 40 — want me to fix that?'\n"
                    "  Good: 'Looks like your terminal is stuck. Want me to kill that process?'\n"
                    "  Bad: 'Can I help you with something?'"
                )

                # Use call_chat_with_image directly (ScreenAgent specialist flow)
                # This avoids a full orchestrator cycle for the sentinel
                try:
                    from llm.client import call_chat_with_image  # type: ignore
                    reply = call_chat_with_image(
                        runtime,
                        system_alert_prompt,
                        b64,
                        max_tokens=200,
                        temperature=0.7,
                    )
                except Exception as llm_err:
                    print(f"[Sentinel] ❌ LLM call failed: {llm_err}", flush=True)
                    self._sentinel_triggered = False
                    return

                if not reply or not reply.strip():
                    self._sentinel_triggered = False
                    return

                reply = reply.strip()
                print(f"[Sentinel] 💬 Ankita says: {reply}", flush=True)

                self._queue.put(
                    ProactiveEvent(
                        kind="sentinel",
                        message=reply,
                        data={
                            "idle_seconds": idle_sec,
                            "idle_label": idle_label,
                            "screen_path": screen.get("path", ""),
                            "text": reply,
                        },
                        priority="high",
                        urgency="immediate",
                        interruptible=True,
                    )
                )

            except Exception as _e:
                print(f"[Sentinel] ❌ Exception in sentinel task: {_e}", flush=True)
                self._sentinel_triggered = False  # Allow retry

        threading.Thread(target=_sentinel_task, daemon=True, name="SentinelTask").start()

    # ------------------------------------------------------------------
    # Proactive Intelligence Component checks (Steps 5, 7, 9)
    # ------------------------------------------------------------------

    def _check_intention_engine(self) -> None:
        """
        Refresh the daily intent model every 6 hours.

        Spawns a daemon thread to call IntentionEngine.generate_intent_model()
        and writes intent.json to .ankita/state/. The Supervisor reads this
        file on every route() call to inject intent context.
        """
        if self._intention_engine is None:
            return
        if self._intent_refresh_pending:
            return
        if self._runtime is None:
            return

        last_refresh = float(self._proactive_state.get("last_intent_refresh", 0.0))
        _SIX_HOURS = 6 * 3600
        if (time.time() - last_refresh) < _SIX_HOURS:
            return

        self._intent_refresh_pending = True
        engine = self._intention_engine

        def _do_intent() -> None:
            try:
                print("[ProactiveEngine] 🧭 Refreshing intent model...", flush=True)
                engine.generate_intent_model()
                self.update_state(last_intent_refresh=time.time())
                print("[ProactiveEngine] ✅ Intent model refreshed.", flush=True)
            except Exception as _e:
                print(f"[ProactiveEngine] ⚠️  Intent refresh failed: {_e}", flush=True)
            finally:
                self._intent_refresh_pending = False

        threading.Thread(target=_do_intent, daemon=True, name="IntentRefresh").start()

    def _check_pattern_learner(self) -> None:
        """
        Run weekly behavioral pattern analysis on Sunday 22:00-23:00.

        Spawns a daemon thread to call BehavioralPatternLearner.analyze_patterns()
        and writes behavioral_model.json. Also checks a 7-day cooldown so we
        only run this once per week even if the engine restarts.
        """
        if self._pattern_learner is None:
            return
        if self._pattern_analysis_pending:
            return
        if self._runtime is None:
            return

        # Guard: only run weekly (7 days)
        last_analysis = float(self._proactive_state.get("last_pattern_analysis", 0.0))
        _SEVEN_DAYS = 7 * 24 * 3600
        if (time.time() - last_analysis) < _SEVEN_DAYS:
            return

        # Additional guard: only run Sunday 22:00-23:00
        if not self._pattern_learner.should_run_analysis():
            return

        self._pattern_analysis_pending = True
        learner = self._pattern_learner

        def _do_analysis() -> None:
            try:
                print("[ProactiveEngine] 🧠 Running weekly pattern analysis...", flush=True)
                learner.analyze_patterns()
                self.update_state(last_pattern_analysis=time.time())
                print("[ProactiveEngine] ✅ Behavioral model updated.", flush=True)
            except Exception as _e:
                print(f"[ProactiveEngine] ⚠️  Pattern analysis failed: {_e}", flush=True)
            finally:
                self._pattern_analysis_pending = False

        threading.Thread(target=_do_analysis, daemon=True, name="PatternAnalysis").start()

    def _check_anticipatory(self) -> None:
        """
        Run one anticipatory pre-fetch cycle (low-risk read-only actions).

        Rate-limited to at most once every 5 minutes so it doesn't hammer
        the filesystem every polling tick.
        """
        if self._anticipatory is None:
            return

        _FIVE_MIN = 300.0
        if (time.time() - self._last_anticipatory_run) < _FIVE_MIN:
            return

        self._last_anticipatory_run = time.time()
        idle_hours = (time.time() - self._last_interaction) / 3600.0
        anticipatory = self._anticipatory

        try:
            anticipatory.run_anticipatory_cycle(idle_time_hours=idle_hours)
        except Exception as _e:
            print(f"[ProactiveEngine] ⚠️  Anticipatory cycle failed: {_e}", flush=True)

    def _check_auto_executor(self) -> None:
        """
        Step 8: AutoExecutor Class A/B/C tick.

        Called every polling cycle. Rate-limited internally by AutoExecutor
        cooldown table. No additional rate-limiting here — the executor is
        already cheap when cooldowns are active (all guards return early).
        """
        if self._auto_executor is None:
            return
        try:
            self._auto_executor.tick(self)
        except Exception as _e:
            print(f"[ProactiveEngine] ⚠️  AutoExecutor tick failed: {_e}", flush=True)

    def _check_insight_synthesizer(self) -> None:
        """
        Step 12: Generate and emit proactive insights every 12 hours.

        Spawns a daemon thread to avoid blocking the poll loop.
        """
        if self._insight_synthesizer is None:
            return
        if self._insight_synthesis_pending:
            return
        if self._runtime is None:
            return

        _TWELVE_HOURS = 12 * 3600
        last_synthesis = float(self._proactive_state.get("last_insight_synthesis", 0.0))
        if (time.time() - last_synthesis) < _TWELVE_HOURS:
            return

        self._insight_synthesis_pending = True
        synthesizer = self._insight_synthesizer

        def _do_insights() -> None:
            try:
                print("[ProactiveEngine] 💡 Running insight synthesis...", flush=True)
                synthesizer.run_and_emit(self)
                self.update_state(last_insight_synthesis=time.time())
                print("[ProactiveEngine] ✅ Insights emitted.", flush=True)
            except Exception as _e:
                print(f"[ProactiveEngine] ⚠️  Insight synthesis failed: {_e}", flush=True)
            finally:
                self._insight_synthesis_pending = False

        threading.Thread(target=_do_insights, daemon=True, name="InsightSynthesis").start()

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
                    self._queue.put(
                        ProactiveEvent(
                            kind="cron",
                            message=f"🕐 Scheduled task '{name}' is {mins:.0f} min overdue.",
                            data={"job_id": job.get("id"), "overdue_ms": overdue_ms},
                            priority="medium",
                            urgency="next_idle",
                            interruptible=True,
                        )
                    )
        except Exception:
            pass
