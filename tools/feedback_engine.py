"""
tools/feedback_engine.py
========================
A.N.K.I.T.A Self-Improvement / Feedback Engine
-----------------------------------------------
Collects implicit and explicit feedback on every response, persists it to
.ankita/feedback/, and exposes methods that the Supervisor and runtime
use to inject learned patterns back into routing + generation.

Architecture
────────────
  FeedbackEngine (singleton, thread-safe)
  ├── record_interaction()   → called after every run_turn() completes
  ├── record_feedback()      → called on explicit 👍/👎 or "good"/"bad"
  ├── record_routing()       → called by Orchestrator after Supervisor routes
  ├── start_agent_task()     → called before each specialist runs
  ├── end_agent_task()       → called after each specialist returns
  ├── analyze_recent()       → distills lessons from recent interactions
  │     └─ uses LLM to distill lessons from recent interactions
  ├── get_injected_patterns() → returns text block to inject into Supervisor prompt
  └── get_stats()            → returns human-readable status string

Storage
───────
  .ankita/feedback/
  ├── interactions.jsonl   – one JSON line per interaction
  ├── explicit.jsonl       – explicit 👍/👎 feedback lines
  ├── patterns.json        – distilled lessons from feedback analysis
  └── stats.json           – running aggregate stats
"""

from __future__ import annotations

import json
import os
import time
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Singleton registry for the active feedback engine
# ---------------------------------------------------------------------------

_INSTANCE: "Optional[FeedbackEngine]" = None


def get_instance() -> "Optional[FeedbackEngine]":
    """Return the running FeedbackEngine, or None if not started."""
    return _INSTANCE


def init_engine(workspace_root: Path, llm_runtime: Any = None) -> "FeedbackEngine":
    """Create (or return existing) FeedbackEngine instance."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = FeedbackEngine(workspace_root=workspace_root, llm_runtime=llm_runtime)
    return _INSTANCE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jsonl_append(path: Path, record: Dict[str, Any]) -> None:
    """Append a single JSON record as a line to a .jsonl file (thread-safe)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_jsonl(path: Path, max_lines: int = 500) -> List[Dict[str, Any]]:
    """Load last N lines from a .jsonl file."""
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        records = []
        for line in lines[-max_lines:]:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
        return records
    except Exception:
        return []


# ---------------------------------------------------------------------------
# FeedbackEngine
# ---------------------------------------------------------------------------

class FeedbackEngine:
    """
    Thread-safe self-improvement feedback loop for A.N.K.I.T.A.

    Typical lifecycle per interaction
    ──────────────────────────────────
    1.  Orchestrator calls record_routing(agents, reasoning, user_text)
    2.  Orchestrator calls start_agent_task(interaction_id, agent_name)
    3.  Specialist runs ...
    4.  Orchestrator calls end_agent_task(interaction_id, agent_name, result_len)
    5.  agent_runtime calls record_interaction(interaction_id, prompt, response)
    6.  (Optional) gui/chat calls record_feedback(interaction_id, rating)
    7.  Background analysis calls analyze_recent() when enough feedback exists
    8.  Supervisor calls get_injected_patterns() to enrich its routing prompt
    """

    # How many recent interactions to analyze in one feedback pass
    ANALYZE_WINDOW = 50

    # Minimum interactions before feedback analysis is triggered
    MIN_INTERACTIONS_FOR_ANALYSIS = 10

    # Explicit positive keywords recognized in plain text feedback
    POSITIVE_KEYWORDS = {"good", "great", "perfect", "correct", "nice", "thanks", "thank you",
                         "well done", "excellent", "awesome", "brilliant", "👍", "✅", "yes",
                         "exactly", "right", "that's right", "thats right"}

    # Explicit negative keywords
    NEGATIVE_KEYWORDS = {"bad", "wrong", "no", "incorrect", "terrible", "awful", "useless",
                         "stop", "not right", "not what i wanted", "👎", "❌", "mistake",
                         "fix it", "redo", "again", "that's wrong", "thats wrong"}

    def __init__(self, workspace_root: Path, llm_runtime: Any = None) -> None:
        self.workspace_root = workspace_root
        self.llm_runtime = llm_runtime  # Can be set later via set_runtime()
        self._lock = threading.Lock()

        self._fb_dir = workspace_root / ".ankita" / "feedback"
        self._fb_dir.mkdir(parents=True, exist_ok=True)

        self._interactions_path = self._fb_dir / "interactions.jsonl"
        self._explicit_path = self._fb_dir / "explicit.jsonl"
        self._patterns_path = self._fb_dir / "patterns.json"
        self._stats_path = self._fb_dir / "stats.json"

        # In-memory tracking for active interactions
        self._active: Dict[str, Dict[str, Any]] = {}  # interaction_id → metadata

        # Cached patterns (loaded from disk, refreshed after analysis)
        self._patterns: List[str] = []
        self._load_patterns()

        # Running stats
        self._stats: Dict[str, Any] = self._load_stats()

        print("[FeedbackEngine] Initialized ✅", flush=True)

    # ------------------------------------------------------------------
    # Runtime wiring
    # ------------------------------------------------------------------

    def set_runtime(self, llm_runtime: Any) -> None:
        """Wire in the LLM runtime after construction (avoids circular imports)."""
        self.llm_runtime = llm_runtime

    # ------------------------------------------------------------------
    # Interaction lifecycle
    # ------------------------------------------------------------------

    def new_interaction(self) -> str:
        """Generate and register a fresh interaction ID."""
        interaction_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._active[interaction_id] = {
                "id": interaction_id,
                "ts": time.time(),
                "agents": [],
                "agent_times": {},
                "routing_reasoning": "",
                "prompt": "",
                "response": "",
                "feedback": None,
            }
        return interaction_id

    def record_routing(
        self,
        interaction_id: str,
        agents: List[str],
        reasoning: str,
        user_text: str = "",
    ) -> None:
        """Record which agents the Supervisor chose and why."""
        with self._lock:
            rec = self._active.get(interaction_id)
            if rec is None:
                return
            rec["agents"] = agents
            rec["routing_reasoning"] = reasoning
            rec["prompt"] = user_text[:500]

    def start_agent_task(self, interaction_id: str, agent_name: str) -> None:
        """Mark the start of a specialist agent task."""
        with self._lock:
            rec = self._active.get(interaction_id)
            if rec is None:
                return
            if agent_name not in rec["agents"]:
                rec["agents"].append(agent_name)
            rec["agent_times"][agent_name] = time.time()

    def end_agent_task(
        self,
        interaction_id: str,
        agent_name: str,
        result_len: int = 0,
    ) -> None:
        """Mark the end of a specialist agent task."""
        with self._lock:
            rec = self._active.get(interaction_id)
            if rec is None:
                return
            start_t = rec["agent_times"].get(agent_name)
            if start_t:
                elapsed = round(time.time() - start_t, 2)
                rec["agent_times"][agent_name] = elapsed
            rec[f"{agent_name}_result_len"] = result_len

    def record_interaction(
        self,
        interaction_id: str,
        prompt: str,
        response: str,
    ) -> None:
        """
        Called after run_turn() completes.
        Finalizes the interaction record and persists it to disk.
        """
        with self._lock:
            rec = self._active.pop(interaction_id, None)
            if rec is None:
                # Create a minimal record if lifecycle wasn't fully tracked
                rec = {
                    "id": interaction_id,
                    "ts": time.time(),
                    "agents": [],
                    "agent_times": {},
                    "routing_reasoning": "",
                    "prompt": prompt[:500],
                    "response": response[:1000],
                    "feedback": None,
                }

        rec["prompt"] = prompt[:500]
        rec["response"] = response[:1000]
        rec["response_len"] = len(response)
        rec["ts_end"] = time.time()
        rec["duration"] = round(rec["ts_end"] - rec.get("ts", rec["ts_end"]), 2)

        _jsonl_append(self._interactions_path, rec)
        self._update_stats(agents=rec.get("agents", []), duration=rec.get("duration", 0))

    # ------------------------------------------------------------------
    # Explicit feedback (👍/👎)
    # ------------------------------------------------------------------

    def record_feedback(self, interaction_id: str, rating: str, comment: str = "") -> None:
        """
        Record explicit user feedback for a specific interaction.
        rating: "positive" | "negative" | "👍" | "👎"
        """
        normalized = "positive" if rating in ("positive", "👍", "good", "✅") else "negative"
        record = {
            "interaction_id": interaction_id,
            "rating": normalized,
            "comment": comment[:200],
            "ts": time.time(),
        }
        _jsonl_append(self._explicit_path, record)

        with self._lock:
            stats = self._stats
            if normalized == "positive":
                stats["positive_feedback"] = stats.get("positive_feedback", 0) + 1
            else:
                stats["negative_feedback"] = stats.get("negative_feedback", 0) + 1
        self._save_stats()
        print(f"[FeedbackEngine] Feedback recorded: {normalized} for {interaction_id}", flush=True)

    def detect_implicit_feedback(
        self,
        user_text: str,
        last_interaction_id: Optional[str],
    ) -> Optional[str]:
        """
        Detect if the user's text is implicit feedback (not a new query).
        Returns "positive" | "negative" | None.
        If feedback detected and last_interaction_id given, records it.
        """
        lower = user_text.lower().strip()
        if lower in self.POSITIVE_KEYWORDS:
            if last_interaction_id:
                self.record_feedback(last_interaction_id, "positive", comment=user_text)
            return "positive"
        if lower in self.NEGATIVE_KEYWORDS:
            if last_interaction_id:
                self.record_feedback(last_interaction_id, "negative", comment=user_text)
            return "negative"
        return None

    # ------------------------------------------------------------------
    # Feedback analysis
    # ------------------------------------------------------------------

    def analyze_recent(self, _memories: Optional[List[Any]] = None) -> Optional[str]:
        """
        Called by background analysis to distill recent interaction lessons.
        Uses LLM to distill lessons from recent interactions + explicit feedback.
        Returns a summary of what was learned (or None if not enough data).
        """
        if self.llm_runtime is None:
            return None

        interactions = _load_jsonl(self._interactions_path, max_lines=self.ANALYZE_WINDOW)
        if len(interactions) < self.MIN_INTERACTIONS_FOR_ANALYSIS:
            print(
                f"[FeedbackEngine] Only {len(interactions)} interactions — skipping analysis "
                f"(need {self.MIN_INTERACTIONS_FOR_ANALYSIS})",
                flush=True,
            )
            return None

        explicit = _load_jsonl(self._explicit_path, max_lines=100)

        # Build a compact summary for the LLM
        interaction_summary = []
        for ix in interactions[-30:]:
            agents = ", ".join(ix.get("agents", ["GeneralAgent"]))
            duration = ix.get("duration", "?")
            rlen = ix.get("response_len", 0)
            prompt_snippet = ix.get("prompt", "")[:80]
            interaction_summary.append(
                f"- agents={agents}, duration={duration}s, response_len={rlen}, "
                f'prompt="{prompt_snippet}"'
            )

        explicit_summary = []
        for fb in explicit[-20:]:
            rating = fb.get("rating", "?")
            comment = fb.get("comment", "")[:60]
            explicit_summary.append(f"- {rating}: \"{comment}\"")

        analysis_prompt = f"""You are A.N.K.I.T.A's self-improvement module.
Analyze these recent interactions and explicit feedback to extract actionable improvement patterns.

RECENT INTERACTIONS (last {len(interaction_summary)}):
{chr(10).join(interaction_summary) or "none"}

EXPLICIT USER FEEDBACK:
{chr(10).join(explicit_summary) or "none"}

Output 3-7 concrete, specific patterns in this exact format (one per line):
PATTERN: <agent_or_topic> | <observation> | <improvement_suggestion>

Examples:
PATTERN: FileAgent | Users often ask for summaries of PDFs | Always provide a brief abstract + key points
PATTERN: routing | Math questions go to GeneralAgent but are slow | Route math to SpecialistAgent instead
PATTERN: response_style | Users gave thumbs-down when response > 800 chars | Prefer concise answers < 400 chars

Be specific. Only output PATTERN: lines. No prose."""

        try:
            from llm.client import call_chat_once  # type: ignore
            resp = call_chat_once(
                self.llm_runtime,
                [{"role": "user", "content": analysis_prompt}],
                tools=None,
                max_tokens=512,
            )
            raw = (resp.get("content") or "").strip()
            patterns = [
                line.replace("PATTERN:", "").strip()
                for line in raw.splitlines()
                if line.startswith("PATTERN:")
            ]
            if patterns:
                self._save_patterns(patterns)
                print(f"[FeedbackEngine] 🧠 Learned {len(patterns)} new patterns", flush=True)
                return f"FeedbackEngine learned {len(patterns)} patterns:\n" + "\n".join(
                    f"  • {p}" for p in patterns
                )
        except Exception as exc:
            print(f"[FeedbackEngine] analyze_recent error: {exc}", flush=True)

        return None

    # ------------------------------------------------------------------
    # Pattern injection for Supervisor
    # ------------------------------------------------------------------

    def get_injected_patterns(self) -> str:
        """
        Returns a text block to prepend to the Supervisor's system prompt
        so the LLM uses learned routing improvements.
        Returns empty string if no patterns yet.
        """
        if not self._patterns:
            return ""
        lines = [
            "## Learned Improvement Patterns (from self-analysis — follow these):",
        ]
        for p in self._patterns[-10:]:  # cap at 10 most recent
            lines.append(f"  • {p}")
        lines.append("")  # trailing newline
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Stats & status
    # ------------------------------------------------------------------

    def get_stats(self) -> str:
        """Return a human-readable status string."""
        s = self._stats
        total = s.get("total_interactions", 0)
        pos = s.get("positive_feedback", 0)
        neg = s.get("negative_feedback", 0)
        avg_dur = round(s.get("total_duration", 0) / max(total, 1), 2)
        patterns_count = len(self._patterns)
        return (
            f"📊 FeedbackEngine Status\n"
            f"  Total interactions : {total}\n"
            f"  Avg response time  : {avg_dur}s\n"
            f"  👍 Positive        : {pos}\n"
            f"  👎 Negative        : {neg}\n"
            f"  🧠 Learned patterns: {patterns_count}\n"
            f"  Data dir           : {self._fb_dir}"
        )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_patterns(self) -> None:
        if self._patterns_path.exists():
            try:
                data = json.loads(self._patterns_path.read_text(encoding="utf-8"))
                self._patterns = list(data.get("patterns", []))
            except Exception:
                self._patterns = []
        else:
            self._patterns = []

    def _save_patterns(self, new_patterns: List[str]) -> None:
        with self._lock:
            # Merge: keep old patterns not superseded + add new ones
            merged = list(dict.fromkeys(self._patterns + new_patterns))[-20:]
            self._patterns = merged
        self._patterns_path.write_text(
            json.dumps({"patterns": merged, "updated_at": time.time()}, indent=2),
            encoding="utf-8",
        )

    def _load_stats(self) -> Dict[str, Any]:
        if self._stats_path.exists():
            try:
                return json.loads(self._stats_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "total_interactions": 0,
            "total_duration": 0.0,
            "positive_feedback": 0,
            "negative_feedback": 0,
            "agent_usage": {},
        }

    def _save_stats(self) -> None:
        try:
            self._stats_path.write_text(
                json.dumps(self._stats, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _update_stats(self, agents: List[str], duration: float) -> None:
        with self._lock:
            self._stats["total_interactions"] = self._stats.get("total_interactions", 0) + 1
            self._stats["total_duration"] = self._stats.get("total_duration", 0.0) + duration
            usage = self._stats.setdefault("agent_usage", {})
            for a in agents:
                usage[a] = usage.get(a, 0) + 1
        self._save_stats()
