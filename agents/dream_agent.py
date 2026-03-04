"""
DreamState Agent for A.N.K.I.T.A.

Runs when the user has been idle for a configurable period (default 1 hour).
Retrieves recent ChromaDB memories, finds connections/insights the user may
have missed, and synthesises a short spoken epiphany that ANKITA delivers
autonomously — no user input required.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from memory import MemoryStore  # type: ignore

_DREAM_SYSTEM_PROMPT = """
You are A.N.K.I.T.A's background processor. You analyze the user's recent workspace memories and proactively suggest actionable tasks.

UPGRADE 3 - PROACTIVE TASK SUGGESTIONS:
Your job is to identify:
1. Incomplete tasks: "User started writing a report but never finished"
2. Upcoming deadlines: Check cron jobs for reminders
3. Unacknowledged alerts: Watchdog alerts that were fired but not acted on
4. Patterns: Recurring issues or opportunities

CRITICAL RULES:
1. Focus on ACTIONABLE suggestions, not philosophy
2. If no clear action items, reply with SILENT
3. Prioritize: incomplete tasks > upcoming deadlines > alerts > patterns
4. Be specific: mention file names, task names, exact issues

RESPOND ONLY IN THIS JSON FORMAT:
{
  "has_suggestions": true/false,
  "suggestions": [
    {
      "type": "incomplete_task|deadline|alert|pattern",
      "priority": "high|medium|low",
      "description": "specific actionable suggestion",
      "context": "why this matters"
    }
  ],
  "morning_briefing": "optional: if morning (6-10am), provide a brief summary of the day ahead"
}

If no suggestions, use: {"has_suggestions": false, "suggestions": [], "morning_briefing": ""}
"""

_DREAM_USER_TEMPLATE = """Here are the user's recent workspace memories:

{memory_block}

ADDITIONAL CONTEXT:
- Current time: {current_time}
- Upcoming cron jobs: {cron_jobs}
- Recent watchdog alerts: {watchdog_alerts}
- Incomplete files: {incomplete_files}

Analyze for:
1. Tasks that were started but not completed
2. Deadlines approaching (from cron jobs)
3. Alerts that need attention
4. Patterns or opportunities

If it's morning (6-10am), also provide a brief morning briefing.

Respond in the JSON format specified."""


class DreamAgent:
    """
    Standalone agent that synthesises a spoken epiphany from ChromaDB memories.

    Not routed through the Supervisor — called directly by the ProactiveEngine
    when the idle threshold is crossed.
    """

    def _generate_dynamic_query(self, memory_store: "MemoryStore", session_id: str) -> str:
        """
        Generate a dynamic query based on time of day and recent activity.
        
        Returns a contextual query string instead of the hardcoded generic one.
        """
        from datetime import datetime
        import random
        
        hour = datetime.now().hour
        
        # Time-based focus
        if 6 <= hour < 12:
            time_focus = "morning tasks goals plans priorities"
        elif 12 <= hour < 18:
            time_focus = "work progress challenges blockers"
        elif 18 <= hour < 22:
            time_focus = "accomplishments learnings insights"
        else:
            time_focus = "reflections ideas improvements"
        
        # Try to extract topics from recent memories
        try:
            recent = memory_store.search(query="recent", n=5, session_id=session_id)
            if recent:
                # Extract keywords from recent memories
                topics = []
                for mem in recent[:3]:
                    text = mem.get("text", "").lower()
                    # Extract potential topics (simple keyword extraction)
                    words = text.split()
                    # Look for technical terms, project names, etc.
                    for word in words:
                        if len(word) > 5 and word.isalpha():
                            topics.append(word)
                
                if topics:
                    # Use most common topics
                    from collections import Counter
                    common = Counter(topics).most_common(3)
                    topic_str = " ".join([t[0] for t in common])
                    return f"{topic_str} {time_focus}"
        except Exception:
            pass
        
        # Fallback: vary the generic query with some randomness
        focus_areas = [
            "problems struggles challenges",
            "projects tasks work",
            "ideas insights discoveries",
            "questions uncertainties blockers",
            "progress achievements wins"
        ]
        
        selected_focus = random.choice(focus_areas)
        return f"{selected_focus} {time_focus}"

    def synthesize(
        self,
        memory_store: "MemoryStore",
        session_id: str,
        n_memories: int = 15,
    ) -> Optional[str]:
        """
        Pull recent memories and generate proactive suggestions (UPGRADE 3).

        Args:
            memory_store: The active MemoryStore (ChromaDB-backed).
            session_id:   Current session ID for scoped retrieval.
            n_memories:   How many memory turns to retrieve (default 15).

        Returns:
            The suggestion string, or None if no actionable suggestions.
        """
        # ------------------------------------------------------------------
        # 1. Generate dynamic query based on time and recent activity
        # ------------------------------------------------------------------
        query = self._generate_dynamic_query(memory_store, session_id)
        print(f"[DreamAgent] Using dynamic query: '{query}'", flush=True)
        
        # ------------------------------------------------------------------
        # 2. Retrieve recent memories
        # ------------------------------------------------------------------
        try:
            results = memory_store.search(
                query=query,
                n=n_memories,
                session_id=session_id,
            )
        except Exception as _e:
            print(f"[DreamAgent] Memory search (scoped) failed: {_e} — trying global...", flush=True)
            try:
                results = memory_store.search(
                    query=query,
                    n=n_memories,
                )
            except Exception as _e2:
                print(f"[DreamAgent] Memory search (global) also failed: {_e2}", flush=True)
                return None

        print(f"[DreamAgent] Memory results: {len(results) if results else 0} entries found.", flush=True)

        # Trigger FeedbackEngine self-analysis during idle cycle
        try:
            from tools.feedback_engine import get_instance as _get_fb
            _fb = _get_fb()
            if _fb is not None:
                _fb_summary = _fb.analyze_recent(memories=results)
                if _fb_summary:
                    print(f"[DreamAgent] {_fb_summary}", flush=True)
        except Exception as _fb_exc:
            print(f"[DreamAgent] FeedbackEngine analyze error: {_fb_exc}", flush=True)

        if not results:
            print(f"[DreamAgent] ⚠️  No memories in ChromaDB yet — nothing to dream about.", flush=True)
            return None

        # ------------------------------------------------------------------
        # 2. Format the memory block
        # ------------------------------------------------------------------
        lines = []
        for i, mem in enumerate(results, 1):
            role = mem.get("meta", {}).get("role", "unknown")
            text = mem.get("text", "").strip()
            if text:
                lines.append(f"[{i}] ({role}): {text}")

        if not lines:
            return None

        memory_block = "\n".join(lines)
        
        # ------------------------------------------------------------------
        # 3. Gather additional context (UPGRADE 3)
        # ------------------------------------------------------------------
        from datetime import datetime
        current_time = datetime.now().strftime("%A, %B %d, %Y %I:%M %p")
        
        # Get upcoming cron jobs
        cron_jobs = "None scheduled"
        try:
            from corn.store import CornStore
            from pathlib import Path
            store = CornStore(Path(".ankita"))
            jobs = store.list_jobs()
            if jobs:
                upcoming = []
                for job in jobs[:5]:  # Top 5 upcoming
                    upcoming.append(f"- {job.get('name', 'Unnamed')}: {job.get('schedule', 'unknown')}")
                cron_jobs = "\n".join(upcoming)
        except Exception:
            pass
        
        # Get recent watchdog alerts
        watchdog_alerts = "No recent alerts"
        try:
            from pathlib import Path
            alert_log = Path(".ankita") / "watchdogs" / "alerts.log"
            if alert_log.exists():
                recent_alerts = alert_log.read_text(encoding="utf-8").strip().split("\n")[-5:]
                if recent_alerts:
                    watchdog_alerts = "\n".join([f"- {a}" for a in recent_alerts if a.strip()])
        except Exception:
            pass
        
        # Check for incomplete files (files with TODO, FIXME, etc.)
        incomplete_files = "None detected"
        try:
            from pathlib import Path
            workspace = Path(".")
            incomplete = []
            for py_file in workspace.glob("**/*.py"):
                if py_file.is_file() and ".ankita" not in str(py_file):
                    try:
                        content = py_file.read_text(encoding="utf-8", errors="ignore")
                        if any(marker in content for marker in ["TODO", "FIXME", "HACK", "XXX"]):
                            incomplete.append(str(py_file))
                    except Exception:
                        pass
            if incomplete:
                incomplete_files = "\n".join([f"- {f}" for f in incomplete[:5]])
        except Exception:
            pass
        
        user_prompt = _DREAM_USER_TEMPLATE.format(
            memory_block=memory_block,
            current_time=current_time,
            cron_jobs=cron_jobs,
            watchdog_alerts=watchdog_alerts,
            incomplete_files=incomplete_files,
        )

        # ------------------------------------------------------------------
        # 4. Call the LLM with proactive suggestion prompt
        # ------------------------------------------------------------------
        try:
            import json
            from pathlib import Path
            from llm import build_runtime_from_env, call_chat_once  # type: ignore

            runtime = build_runtime_from_env()
            messages = [
                {"role": "system", "content": _DREAM_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            max_tokens = int(os.getenv("DREAM_MAX_TOKENS", "400"))
            print(f"[DreamAgent] 📡 Calling LLM ({runtime.provider}/{runtime.model}) with {len(lines)} memories...", flush=True)
            response = call_chat_once(runtime, messages, tools=None, max_tokens=max_tokens)
            raw = (response.get("content") or "").strip()
            print(f"[DreamAgent] LLM raw response: {repr(raw[:120]) if raw else 'EMPTY'}", flush=True)

            # ------------------------------------------------------------------
            # Parse structured JSON output
            # ------------------------------------------------------------------
            parsed: dict = {}
            try:
                # Strip markdown code fences if present
                clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                parsed = json.loads(clean)
            except Exception:
                # Fallback: treat raw as old-style solution text
                if raw.upper().startswith("SILENT"):
                    print("[DreamAgent] 🤫 SILENT — no suggestions.", flush=True)
                    return None
                parsed = {"has_suggestions": True, "suggestions": [{"type": "pattern", "priority": "medium", "description": raw, "context": ""}]}

            # Check if there are actionable suggestions
            if not bool(parsed.get("has_suggestions")) or not parsed.get("suggestions"):
                print(f"[DreamAgent] 🤫 No actionable suggestions found.", flush=True)
                return None

            suggestions = parsed.get("suggestions", [])
            morning_briefing = parsed.get("morning_briefing", "")
            
            # Format suggestions
            output_lines = []
            
            # Add morning briefing if present
            hour = datetime.now().hour
            if morning_briefing and 6 <= hour <= 10:
                output_lines.append(f"☀️ Good morning! {morning_briefing}\n")
            
            # Add suggestions by priority
            high_priority = [s for s in suggestions if s.get("priority") == "high"]
            medium_priority = [s for s in suggestions if s.get("priority") == "medium"]
            low_priority = [s for s in suggestions if s.get("priority") == "low"]
            
            if high_priority:
                output_lines.append("🔴 High Priority:")
                for s in high_priority:
                    output_lines.append(f"  • {s.get('description')}")
                    if s.get('context'):
                        output_lines.append(f"    ({s.get('context')})")
            
            if medium_priority:
                output_lines.append("\n🟡 Medium Priority:")
                for s in medium_priority:
                    output_lines.append(f"  • {s.get('description')}")
            
            if low_priority:
                output_lines.append("\n🔵 Low Priority:")
                for s in low_priority:
                    output_lines.append(f"  • {s.get('description')}")
            
            if not output_lines:
                return None
            
            result = "\n".join(output_lines)

            # ------------------------------------------------------------------
            # Write to dream log
            # ------------------------------------------------------------------
            dream_log_path = Path(".ankita") / "dreams.jsonl"
            dream_log_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                import time
                with dream_log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "ts": time.time(),
                        "type": "proactive_suggestions",
                        "suggestions": suggestions,
                        "morning_briefing": morning_briefing,
                    }, ensure_ascii=False) + "\n")
            except Exception as log_err:
                print(f"[DreamAgent] ⚠️  Dream log write failed: {log_err}", flush=True)

            print(f"[DreamAgent] ✅ Proactive suggestions generated: {len(suggestions)} items", flush=True)
            return result

        except Exception as _e:
            print(f"[DreamAgent] ❌ LLM call failed: {_e}", flush=True)
            return None
