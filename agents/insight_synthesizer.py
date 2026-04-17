"""
InsightSynthesizer for A.N.K.I.T.A — Proactive Intelligence Step 12.

Runs every 12 hours. Analyses recent activity (audit log and tasks)
and generates 1-3 short actionable insights via a single LLM call.

Insights are:
  - Saved to .ankita/state/insights.jsonl
  - Emitted as ProactiveEvent(kind="insight", priority="medium", urgency="next_idle")

Requirements: 8.1, 8.2, 8.3, 8.4
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from proactive_models import ProactiveEvent


class InsightSynthesizer:
    """
    Generates proactive insights from recent ANKITA activity.

    Usage:
        synthesizer = InsightSynthesizer(workspace_root)
        synthesizer.attach_runtime(runtime)
        insights = synthesizer.run()  # Returns list of insight strings

    Each insight is ≤50 words and actionable (not vague platitudes).
    """

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self._state_dir = workspace_root / ".ankita" / "state"
        self._insights_file = self._state_dir / "insights.jsonl"
        self._audit_file = workspace_root / ".ankita" / "audit.jsonl"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._runtime: Optional[Any] = None

    def attach_runtime(self, runtime: Any) -> None:
        """Inject the LLM runtime for insight generation."""
        self._runtime = runtime

    def run(self) -> List[str]:
        """
        Gather recent activity and generate 1-3 actionable insights.

        Returns:
            List of insight strings (empty if generation failed or no data).
        """
        if self._runtime is None:
            print("[InsightSynthesizer] ⚠️  No runtime — skipping insight generation.", flush=True)
            return []

        print("[InsightSynthesizer] 🔍 Gathering recent activity...", flush=True)

        # Gather context from the last 12 hours
        context_blocks: List[str] = []

        audit_summary = self._gather_audit_summary(hours=12)
        if audit_summary:
            context_blocks.append(f"RECENT AGENT ACTIVITY:\n{audit_summary}")

        task_summary = self._gather_task_summary()
        if task_summary:
            context_blocks.append(f"TASK STATUS:\n{task_summary}")

        if not context_blocks:
            print("[InsightSynthesizer] ℹ️  No activity data — skipping.", flush=True)
            return []

        context = "\n\n".join(context_blocks)

        # Generate insights via single LLM call
        try:
            insights = self._call_llm_for_insights(context)
        except Exception as e:
            print(f"[InsightSynthesizer] ❌ LLM call failed: {e}", flush=True)
            return []

        if insights:
            self._save_insights(insights)
            print(
                f"[InsightSynthesizer] ✅ Generated {len(insights)} insight(s).",
                flush=True,
            )

        return insights

    def run_and_emit(self, proactive_engine: Any) -> None:
        """
        Run insight generation and push results as ProactiveEvents.

        Args:
            proactive_engine: Active ProactiveEngine to push events into.
        """
        insights = self.run()
        for insight in insights:
            event = ProactiveEvent(
                kind="insight",
                message=insight,
                data={"insight": insight, "generated_at": datetime.now().isoformat()},
                priority="medium",
                urgency="next_idle",
                interruptible=False,
            )
            if hasattr(proactive_engine, "_queue"):
                proactive_engine._queue.put(event)

    # ------------------------------------------------------------------
    # Context gathering helpers
    # ------------------------------------------------------------------

    def _gather_audit_summary(self, hours: int = 12) -> str:
        """
        Summarise the last N hours of audit.jsonl entries.

        Returns a compact text block for the LLM prompt.
        """
        if not self._audit_file.exists():
            return ""

        cutoff = time.time() - (hours * 3600)
        agent_counts: Dict[str, int] = {}
        error_agents: List[str] = []
        total = 0

        try:
            with open(self._audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts = float(entry.get("ts", 0))
                        if ts < cutoff:
                            continue
                        agent = str(entry.get("agent", "unknown"))
                        agent_counts[agent] = agent_counts.get(agent, 0) + 1
                        total += 1
                        # Track errors
                        preview = str(entry.get("reply_preview", ""))
                        if "[Error]" in preview or "[Timeout]" in preview:
                            error_agents.append(agent)
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception:
            return ""

        if not total:
            return ""

        lines = [f"  Total interactions: {total}"]
        for agent, count in sorted(agent_counts.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  {agent}: {count} times")
        if error_agents:
            lines.append(f"  Errors/timeouts in: {', '.join(set(error_agents))}")

        return "\n".join(lines)

    def _gather_task_summary(self) -> str:
        """Summarise current task state."""
        try:
            from tools.task_ops import task_op  # type: ignore
            result = task_op(action="summary")
            if result.get("status") != "success":
                return ""

            total = result.get("total", 0)
            overdue = result.get("overdue", 0)
            by_status = result.get("by_status", {})
            pending = by_status.get("pending", 0)
            done = by_status.get("done", 0)

            parts = [f"  Total tasks: {total}"]
            if overdue:
                parts.append(f"  ⚠️ Overdue: {overdue}")
            if pending:
                parts.append(f"  Pending: {pending}")
            if done:
                parts.append(f"  Completed recently: {done}")

            return "\n".join(parts)
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # LLM synthesis
    # ------------------------------------------------------------------

    def _call_llm_for_insights(self, context: str) -> List[str]:
        """
        Make a single LLM call to synthesise 1-3 actionable insights.

        Args:
            context: Combined activity context block.

        Returns:
            List of insight strings.
        """
        import re
        from llm.client import call_chat_once  # type: ignore

        system_prompt = (
            "You are ANKITA's insight synthesizer. Analyse the user's recent AI assistant activity "
            "and generate 1 to 3 short, actionable insights. "
            "Each insight must be ≤50 words, specific, and useful (not generic advice). "
            "Output ONLY a JSON array of strings. Example:\n"
            '["You\'ve used CodeAgent 8 times in 2 hours — consider breaking the task into smaller subtasks.", '
            '"2 tasks are overdue — suggest reviewing them next."]'
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Recent activity:\n\n{context}\n\nGenerate insights:"},
        ]

        response = call_chat_once(self._runtime, messages, tools=None, max_tokens=300)
        raw = str(response.get("content", "")).strip()

        # Strip markdown fences
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")

        # Find JSON array
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            # Fallback: try single insight
            if raw:
                return [raw[:200]]
            return []

        parsed = json.loads(match.group())
        if isinstance(parsed, list):
            return [str(item).strip()[:300] for item in parsed if item]
        return []

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_insights(self, insights: List[str]) -> None:
        """Append generated insights to insights.jsonl."""
        try:
            timestamp = datetime.now().isoformat()
            with open(self._insights_file, "a", encoding="utf-8") as f:
                for insight in insights:
                    entry = {"timestamp": timestamp, "insight": insight}
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[InsightSynthesizer] ❌ Failed to save insights: {e}", flush=True)
