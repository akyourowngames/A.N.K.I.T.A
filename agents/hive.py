"""
A.N.K.I.T.A — Hive Mind 🐝
============================
True async multitasking: heavy tasks run in background drones while
Ankita stays fully responsive for new commands.

Architecture:
    User says "research quantum computing and write a report"
    → HiveMind detects heavy task (research + write)
    → Spawns a daemon DroneTask thread instantly
    → Returns "Started 🐝 [ID: a3f2]" immediately to user
    → Drone runs orchestrator in background
    → On completion: send_fn("🔔 [a3f2] Done: research quantum...") fires
    → User can say "show a3f2" anytime to see the full result

Classes:
    DroneTask   — a single background task unit
    HiveMind    — the manager that spawns + tracks drones
"""
from __future__ import annotations

import queue
import random
import string
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# LLM-POWERED TASK CLASSIFIER — replaces all keyword hardcoding
# ─────────────────────────────────────────────────────────────────────────────

import functools
import json

_CLASSIFIER_SYSTEM_PROMPT = """You are ANKITA's Task Classifier. Your ONLY job is to classify a user request into one of three modes.

MODES:
- "instant"  → Pure chat/greeting, time/date query, status check. Completes in <0.5s. No tools needed. Examples: "hi", "what time is it", "who are you", "/hive"
- "normal"   → Single-step action with tools. Completes in 1-10s. Examples: "open notepad", "take a photo", "scan wifi", "volume up", "play music", "check my speed", "take screenshot", "turn off wifi", "lock screen", "what's my battery"
- "heavy"    → Multi-step, multi-agent, long-running task. Takes 10s+. Needs background drone. Examples: "research X and write a report", "deep analysis of Y", "build a project", "batch process all files", "write a comprehensive essay"

RULES:
- ALL single system commands → "normal" (never "heavy"): scan wifi, take photo, check speed, open app, close app, volume, brightness, screenshot, lock, shutdown
- ANY research + write combo → "heavy"
- ANY single web search (not write) → "normal"  
- Greetings/meta questions → "instant"
- When in doubt between normal and heavy → "normal"

Respond ONLY with valid JSON. No explanation. No markdown.
{"mode": "instant" | "normal" | "heavy", "reason": "<one sentence>"}"""

# Zero-latency bypass for obvious greetings — no LLM call needed
_ZERO_LATENCY_INSTANT = {"hi", "hey", "hello", "hlo", "ok", "okay", 
                          "thanks", "thank you", "/hive", "/memory", "/reset"}


@functools.lru_cache(maxsize=256)
def _classify_task(text: str) -> str:
    """
    Ask the LLM to classify the task. Returns "instant", "normal", or "heavy".
    Falls back to "normal" on any error — safe default.
    LRU cache prevents duplicate API calls for identical inputs.
    """
    try:
        from llm import build_runtime_from_env, call_chat_once
        
        runtime = build_runtime_from_env()
        messages = [
            {"role": "system", "content": _CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        response = call_chat_once(runtime, messages, tools=None, max_tokens=60)
        raw = (response.get("content") or "").strip()

        # Parse JSON — strip fences if present
        clean = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(clean)
        mode = str(parsed.get("mode", "normal")).lower()

        if mode in ("instant", "normal", "heavy"):
            print(f"[HiveClassifier] '{text[:50]}' → {mode} ({parsed.get('reason','')})", flush=True)
            return mode
    except Exception as e:
        print(f"[HiveClassifier] ⚠️ LLM classify failed: {e} — defaulting to 'normal'", flush=True)
    
    return "normal"  # safe fallback


def _make_id(n: int = 4) -> str:
    """Generate a short random alphanumeric task ID, e.g. 'a3f2'."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


# ─────────────────────────────────────────────────────────────────────────────
# DroneTask
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DroneTask:
    id: str
    prompt: str
    status: str = "queued"        # queued | running | done | error
    result: Optional[str] = None
    error: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    task_type: str = "heavy"

    @property
    def elapsed(self) -> str:
        end = self.end_time or time.time()
        secs = int(end - self.start_time)
        if secs < 60:
            return f"{secs}s"
        return f"{secs // 60}m {secs % 60}s"

    @property
    def short_prompt(self) -> str:
        return self.prompt[:40] + ("…" if len(self.prompt) > 40 else "")

    def to_row(self) -> str:
        status_icon = {"queued": "⏳", "running": "🔄", "done": "✅", "error": "❌"}.get(self.status, "?")
        return f"  [{self.id}] {status_icon} {self.status:<8} {self.elapsed:<6} {self.short_prompt}"


# ─────────────────────────────────────────────────────────────────────────────
# HiveMind
# ─────────────────────────────────────────────────────────────────────────────

class HiveMind:
    """
    Manages background drone tasks for heavy operations.

    Usage:
        hive = HiveMind(orchestrator=orch, agent_runtime=agent)
        reply = hive.delegate(user_text, messages, send_fn=print)
        # → immediate reply for light tasks
        # → "Started 🐝 [ID: a3f2]" for heavy tasks
    """

    def __init__(
        self,
        orchestrator: Any = None,
        agent_runtime: Any = None,
        use_multi_agent: bool = True,
    ) -> None:
        self.orchestrator = orchestrator
        self.agent_runtime = agent_runtime
        self.use_multi_agent = use_multi_agent

        self._active: Dict[str, DroneTask] = {}       # running/queued drones
        self._completed: Dict[str, DroneTask] = {}    # finished drones (kept for recall)
        self._lock = threading.Lock()
        self._notify_queue: queue.Queue[str] = queue.Queue()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def delegate(
        self,
        user_input: str,
        messages: List[Dict[str, Any]],
        send_fn: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Route ALL tasks to background drone threads — Ankita NEVER blocks.

        Every command spawns a daemon thread instantly. The difference is:
        - INSTANT tasks (hello, time, etc): tiny tasks where send_fn delivers
          the reply directly and returns empty string to caller.
        - NORMAL tasks: drone runs, send_fn delivers reply, returns "" to caller.
        - HEAVY tasks: returns "Started 🐝 [ID: xxxx]" immediately AND
          send_fn delivers full result when done.

        Args:
            user_input: The raw user message.
            messages:   Current conversation history (deep-copied for the drone).
            send_fn:    Callback for replies/notifications. REQUIRED for async mode.
                        Called with the reply string when the drone finishes.

        Returns:
            - Heavy task: "Started 🐝 [ID: xxxx]" acknowledgement string.
            - All others: "" (reply comes via send_fn callback).
        """
        if send_fn is None:
            # Fallback: no callback provided — run synchronously (legacy path)
            return self._run_immediate(user_input, messages)

        t = user_input.strip().lower()
        
        # Zero-latency bypass for obvious greetings — no LLM call needed
        if t in _ZERO_LATENCY_INSTANT:
            return self._run_immediate(user_input, self._trim_instant_context(messages))
        
        # LLM classification for everything else
        mode = _classify_task(user_input.strip())

        if mode == "instant":
            return self._run_immediate(user_input, self._trim_instant_context(messages))
        elif mode == "heavy":
            # Heavy: return "Started" immediately, full result via send_fn later
            return self._spawn_drone(user_input, list(messages), send_fn, announce=True)
        else:  # "normal"
            # Normal: spawn silently, result comes via send_fn
            self._spawn_drone(user_input, list(messages), send_fn, announce=False)
            return ""  # caller gets nothing — reply arrives via send_fn

    def check_notifications(self) -> List[str]:
        """Drain all pending drone completion notifications (non-blocking)."""
        notes: List[str] = []
        while True:
            try:
                notes.append(self._notify_queue.get_nowait())
            except queue.Empty:
                break
        return notes

    def get_result(self, task_id: str) -> str:
        """Retrieve the result of a drone task by ID."""
        task_id = task_id.strip().lower()

        with self._lock:
            task = self._active.get(task_id) or self._completed.get(task_id)

        if not task:
            return f"No task found with ID '{task_id}'. Use /hive to see active tasks."

        if task.status in ("queued", "running"):
            return f"🔄 [{task.id}] Still running… ({task.elapsed} elapsed)\nTask: {task.short_prompt}"

        if task.status == "error":
            return f"❌ [{task.id}] Failed after {task.elapsed}:\n{task.error}"

        return f"✅ [{task.id}] Done in {task.elapsed}:\n\n{task.result}"

    def list_tasks(self) -> str:
        """Return a formatted table of all active + completed drone tasks."""
        with self._lock:
            active = list(self._active.values())
            completed = list(self._completed.values())

        if not active and not completed:
            return "🐝 Hive Mind: No drone tasks yet. Heavy tasks (research, write, analyze…) spawn drones automatically."

        lines = ["🐝 Hive Mind Task Board", "─" * 50]
        if active:
            lines.append("ACTIVE:")
            for t in sorted(active, key=lambda x: x.start_time):
                lines.append(t.to_row())
        if completed:
            lines.append("COMPLETED (last 10):")
            for t in sorted(completed, key=lambda x: x.end_time or 0, reverse=True)[:10]:
                lines.append(t.to_row())
        lines.append("─" * 50)
        lines.append("Tip: say 'show <id>' to see the full result of any task.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _trim_instant_context(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        For instant replies (greetings, time, etc), trim context to just system + last 2 messages.
        No need to send full conversation history for trivial queries.
        """
        if len(messages) <= 3:
            return messages
        # Keep system message (if present) + last 2 messages
        system_msg = [messages[0]] if messages and messages[0].get("role") == "system" else []
        return system_msg + messages[-2:]

    def _run_immediate(self, user_input: str, messages: List[Dict[str, Any]]) -> str:
        """Run a light task synchronously and return its result."""
        try:
            if self.use_multi_agent and self.orchestrator:
                result = self.orchestrator.run(user_input, messages)
                # orchestrator.run() may return a dict {"reply": "..."} or a plain string
                if isinstance(result, dict):
                    return result.get("reply", str(result))
                return str(result)
            elif self.agent_runtime:
                return self.agent_runtime.process_user_text(user_input, messages)
            else:
                return "[HiveMind] No runtime available."
        except Exception as err:
            return f"[HiveMind error] {err}"

    def _spawn_drone(
        self,
        user_input: str,
        messages: List[Dict[str, Any]],
        send_fn: Optional[Callable[[str], None]],
        announce: bool = False,
    ) -> str:
        """Spawn a background daemon thread for any task."""
        task_id = _make_id()

        # Avoid ID collision (rare but possible)
        with self._lock:
            while task_id in self._active or task_id in self._completed:
                task_id = _make_id()

        task = DroneTask(id=task_id, prompt=user_input, status="queued")

        with self._lock:
            self._active[task_id] = task

        def worker() -> None:
            task.status = "running"
            task.start_time = time.time()
            try:
                if self.use_multi_agent and self.orchestrator:
                    result = self.orchestrator.run(user_input, messages)
                    # orchestrator.run() may return a dict {"reply": "..."} or a plain string
                    if isinstance(result, dict):
                        task.result = result.get("reply", str(result))
                    else:
                        task.result = str(result)
                elif self.agent_runtime:
                    task.result = self.agent_runtime.process_user_text(user_input, list(messages))
                else:
                    task.result = "[HiveMind] No runtime available."
                task.status = "done"
            except Exception as err:
                task.status = "error"
                task.error = str(err)
            finally:
                task.end_time = time.time()
                # Move to completed
                with self._lock:
                    self._active.pop(task_id, None)
                    self._completed[task_id] = task

                if send_fn:
                    try:
                        if announce:
                            # Heavy task: send a 🔔 notification with result summary
                            short = user_input[:40] + ("…" if len(user_input) > 40 else "")
                            if task.status == "done":
                                note = f"🔔 [{task_id}] Done ({task.elapsed}): {short}\n\n{task.result}"
                            else:
                                note = f"❌ [{task_id}] Failed ({task.elapsed}): {task.error}"
                            self._notify_queue.put(note)
                            send_fn(note)
                        else:
                            # Normal task: send the reply directly (like a normal chat response)
                            if task.status == "done":
                                send_fn(task.result or "")
                            else:
                                send_fn(f"⚠️ Error: {task.error}")
                    except Exception:
                        pass

        thread = threading.Thread(target=worker, daemon=True, name=f"drone-{task_id}")
        thread.start()

        if announce:
            return (
                f"🐝 Started background task [ID: **{task_id}**]\n"
                f"Task: {user_input[:60]}{'…' if len(user_input) > 60 else ''}\n"
                f"I'll ping you when it's done. Say `/hive` to check status or `show {task_id}` to get the result."
            )
        return ""  # reply comes via send_fn
