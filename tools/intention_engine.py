"""
IntentionEngine for the Proactive Intelligence System.

Builds a daily intent model by analyzing user context from multiple sources:
- ChromaDB memory entries (last 30)
- Pending tasks from task_ops
- Cron jobs for next 24 hours
- Recent git commits
- Watchdog states

Generates intent.json every 6 hours with active projects, deadlines, focus mode, etc.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from proactive_models import IntentModel


class IntentionEngine:
    """
    Analyzes user context to build a daily intent model.
    
    Runs at system startup and every 6 hours thereafter to keep the intent
    model fresh and relevant.
    
    The intent model is used by:
    - Supervisor: Injects intent context into agent prompts
    - EnvironmentManager: Adjusts environment based on focus_mode
    - AnticipatoryActionSystem: Pre-executes actions based on intent
    - Proactive systems: consume intent for planning and environment hints
    """
    
    def __init__(self, workspace_root: Path) -> None:
        """
        Initialize the IntentionEngine.
        
        Args:
            workspace_root: Root directory of the workspace (contains .ankita/)
        """
        self.workspace_root = workspace_root
        self.state_dir = workspace_root / ".ankita" / "state"
        self.intent_file = self.state_dir / "intent.json"
        
        # Ensure state directory exists
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # LLM runtime (injected by caller)
        self._runtime: Optional[Any] = None
    
    def attach_runtime(self, runtime: Any) -> None:
        """
        Inject the LLM runtime for intent model generation.
        
        Args:
            runtime: The active LLMRuntime instance
        """
        self._runtime = runtime
    
    def generate_intent_model(self) -> Optional[IntentModel]:
        """
        Generate a new intent model by analyzing user context.
        
        Process:
        1. Gather context from all sources (ChromaDB, tasks, cron, git, watchdogs)
        2. Make single LLM call with structured prompt
        3. Parse and validate JSON response
        4. Write to intent.json atomically
        5. Return the generated model
        
        Returns:
            IntentModel if successful, None if generation failed
        """
        if self._runtime is None:
            print("[IntentionEngine] ⚠️  No runtime attached — cannot generate intent model", flush=True)
            return None
        
        print("[IntentionEngine] 🧠 Generating intent model...", flush=True)
        
        # Step 1: Gather context from all sources
        context = self._gather_context()
        
        # Step 2: Make LLM call with structured prompt
        try:
            intent_data = self._call_llm_for_intent(context)
            if not intent_data:
                raise ValueError("LLM returned empty intent data")
            
            # Step 3: Parse and validate
            intent_model = self._parse_and_validate(intent_data)
            
            # Step 4: Write to intent.json atomically
            self._save_intent_model(intent_model)
            
            print(f"[IntentionEngine] ✅ Intent model generated: {intent_model.focus_mode} mode, {len(intent_model.active_projects)} projects", flush=True)
            return intent_model
            
        except Exception as e:
            print(f"[IntentionEngine] ❌ Failed to generate intent model: {e}", flush=True)
            # Use previous intent.json on failure (Requirement 2.6)
            return self._load_previous_intent()
    
    def _gather_context(self) -> Dict[str, Any]:
        """
        Gather context from all input sources.
        
        Sources:
        - ChromaDB: Last 30 memory entries
        - task_ops: Pending tasks
        - scheduler state: Scheduled jobs for next 24 hours
        - git: Recent commits (last 10)
        
        Returns:
            Dictionary containing all gathered context
        """
        context: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "chromadb_memories": [],
            "pending_tasks": [],
            "cron_jobs_24h": [],
            "recent_git_commits": [],
            "watchdog_states": {},
        }
        
        # ChromaDB memories (DISABLED - rebuilding)
        context["chromadb_memories"] = []
        
        # Gather pending tasks
        try:
            from tools.task_ops import task_op
            result = task_op(action="list", status="pending")
            if result.get("status") == "success":
                context["pending_tasks"] = result.get("tasks", [])
            
            # Also get in_progress tasks
            result = task_op(action="list", status="in_progress")
            if result.get("status") == "success":
                context["pending_tasks"].extend(result.get("tasks", []))
        except Exception as e:
            print(f"[IntentionEngine] ⚠️  Failed to gather tasks: {e}", flush=True)
        
        try:
            context["cron_jobs_24h"] = self._load_scheduled_jobs()
        except Exception as e:
            print(f"[IntentionEngine] ⚠️  Failed to gather scheduled jobs: {e}", flush=True)
        
        # Gather recent git commits (last 10)
        try:
            # Try to get git commits from current directory
            result = subprocess.run(
                ["git", "log", "--oneline", "-10"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                commits = []
                for line in result.stdout.strip().split("\n"):
                    if line:
                        commits.append(line)
                context["recent_git_commits"] = commits
        except Exception as e:
            print(f"[IntentionEngine] ⚠️  Failed to gather git commits: {e}", flush=True)
        
        # Gather watchdog states
        try:
            from watchdog_manager import get_instance
            watchdog_mgr = get_instance()
            if watchdog_mgr:
                states = {}
                for name, watcher in watchdog_mgr._watchers.items():
                    states[name] = {
                        "alive": watcher.is_alive(),
                        "state": watcher.state,
                    }
                context["watchdog_states"] = states
        except Exception as e:
            print(f"[IntentionEngine] ⚠️  Failed to gather watchdog states: {e}", flush=True)
        
        return context
    
    def _call_llm_for_intent(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make a single LLM call to generate the intent model.
        
        Args:
            context: Gathered context from all sources
            
        Returns:
            Parsed JSON dictionary with intent model fields
        """
        # Build structured prompt
        prompt = self._build_intent_prompt(context)
        
        # Make LLM call
        from llm.client import call_chat_once
        
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an intent analysis system for a proactive AI assistant. "
                    "Analyze the user's context and produce a daily intent model in JSON format. "
                    "Output ONLY valid JSON, no markdown fences or explanations."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]
        
        response = call_chat_once(self._runtime, messages, None, max_tokens=800)
        raw_text = str(response.get("content", "")).strip()
        
        # Parse JSON from response (handle markdown fences if present)
        import re
        # Strip markdown fences
        raw_text = re.sub(r"```(?:json)?", "", raw_text).strip().strip("`")
        
        # Find JSON object
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in LLM response: {raw_text[:200]}")
        
        intent_data = json.loads(match.group())
        return intent_data
    
    def _build_intent_prompt(self, context: Dict[str, Any]) -> str:
        """
        Build the structured prompt for intent model generation.
        
        Args:
            context: Gathered context from all sources
            
        Returns:
            Formatted prompt string
        """
        # Format context sections
        memories_section = self._format_memories(context["chromadb_memories"])
        tasks_section = self._format_tasks(context["pending_tasks"])
        cron_section = self._format_cron_jobs(context["cron_jobs_24h"])
        git_section = self._format_git_commits(context["recent_git_commits"])
        watchdog_section = self._format_watchdog_states(context["watchdog_states"])
        prompt = f"""Analyze this user context and produce a daily intent model.

CONTEXT:

Recent Memories:
(Memory system currently being rebuilt)

Pending Tasks:
{tasks_section}

Scheduled Jobs (next 24 hours):
{cron_section}

Recent Git Activity:
{git_section}

System Watchdogs:
{watchdog_section}

OUTPUT FORMAT (JSON only):
{{
  "active_projects": ["project1", "project2"],
  "open_loops": ["incomplete task 1", "pending item 2"],
  "today_deadlines": ["deadline 1", "deadline 2"],
  "focus_mode": "deep_work|meeting|coding|idle",
  "recommended_music": "lofi|focus|energetic|none",
  "suggested_first_action": "Brief suggestion for what to do next"
}}

GUIDELINES:
- active_projects: Extract project names from memories, tasks, and git commits
- open_loops: Identify incomplete tasks or pending items that need attention
- today_deadlines: List any deadlines due today (check task deadlines)
- focus_mode: Infer from context (deep_work for focused coding, meeting if calendar events, coding for general dev work, idle if nothing active)
- recommended_music: Match to focus_mode (lofi for deep_work, none for meetings, focus for coding)
- suggested_first_action: One sentence suggesting the most important next action

Output JSON only:"""
        
        return prompt
    
    def _format_memories(self, _memories: List[Dict[str, Any]]) -> str:
        return "(Memory system currently being rebuilt)"
    
    def _format_tasks(self, tasks: List[Dict[str, Any]]) -> str:
        """Format tasks for prompt."""
        if not tasks:
            return "  (No pending tasks)"
        
        lines = []
        for task in tasks[:15]:  # Limit to 15 tasks
            title = task.get("title", "")
            priority = task.get("priority", "medium")
            deadline = task.get("deadline", "")
            status = task.get("status", "pending")
            
            deadline_str = f" [due: {deadline}]" if deadline else ""
            lines.append(f"  [{priority}] {title} ({status}){deadline_str}")
        
        if len(tasks) > 15:
            lines.append(f"  ... and {len(tasks) - 15} more tasks")
        
        return "\n".join(lines) if lines else "  (No pending tasks)"
    
    def _format_cron_jobs(self, jobs: List[Dict[str, Any]]) -> str:
        """Format cron jobs for prompt."""
        if not jobs:
            return "  (No scheduled jobs in next 24 hours)"
        
        lines = []
        for job in jobs:
            name = job.get("name", "")
            task = job.get("task", "")
            next_run = job.get("next_run", "")
            lines.append(f"  {name}: {task} (at {next_run})")
        
        return "\n".join(lines) if lines else "  (No scheduled jobs in next 24 hours)"

    def _load_scheduled_jobs(self) -> List[Dict[str, Any]]:
        """Return upcoming scheduled jobs if the workspace exposes them."""
        return []
    
    def _format_git_commits(self, commits: List[str]) -> str:
        """Format git commits for prompt."""
        if not commits:
            return "  (No recent git activity)"
        
        lines = [f"  {commit}" for commit in commits[:10]]
        return "\n".join(lines) if lines else "  (No recent git activity)"

    def _format_watchdog_states(self, states: Dict[str, Any]) -> str:
        """Format watchdog states for prompt."""
        if not states:
            return "  (No watchdog data)"
        
        lines = []
        for name, state_data in states.items():
            alive = "✅" if state_data.get("alive") else "❌"
            lines.append(f"  {alive} {name}")
        
        return "\n".join(lines) if lines else "  (No watchdog data)"
    
    def _parse_and_validate(self, intent_data: Dict[str, Any]) -> IntentModel:
        """
        Parse and validate the intent data from LLM.
        
        Args:
            intent_data: Raw JSON dictionary from LLM
            
        Returns:
            Validated IntentModel instance
            
        Raises:
            ValueError: If required fields are missing or invalid
        """
        # Validate required fields
        required_fields = [
            "active_projects",
            "open_loops",
            "today_deadlines",
            "focus_mode",
            "recommended_music",
            "suggested_first_action",
        ]
        
        for field in required_fields:
            if field not in intent_data:
                raise ValueError(f"Missing required field: {field}")
        
        # Validate field types
        if not isinstance(intent_data["active_projects"], list):
            raise ValueError("active_projects must be a list")
        if not isinstance(intent_data["open_loops"], list):
            raise ValueError("open_loops must be a list")
        if not isinstance(intent_data["today_deadlines"], list):
            raise ValueError("today_deadlines must be a list")
        
        # Validate focus_mode
        valid_focus_modes = ["deep_work", "meeting", "coding", "idle"]
        if intent_data["focus_mode"] not in valid_focus_modes:
            print(f"[IntentionEngine] ⚠️  Invalid focus_mode '{intent_data['focus_mode']}', defaulting to 'idle'", flush=True)
            intent_data["focus_mode"] = "idle"
        
        # Validate recommended_music
        valid_music = ["lofi", "focus", "energetic", "none"]
        if intent_data["recommended_music"] not in valid_music:
            print(f"[IntentionEngine] ⚠️  Invalid recommended_music '{intent_data['recommended_music']}', defaulting to 'none'", flush=True)
            intent_data["recommended_music"] = "none"
        
        # Create IntentModel
        intent_model = IntentModel(
            timestamp=datetime.now(),
            active_projects=intent_data["active_projects"],
            open_loops=intent_data["open_loops"],
            today_deadlines=intent_data["today_deadlines"],
            focus_mode=intent_data["focus_mode"],
            recommended_music=intent_data["recommended_music"],
            suggested_first_action=intent_data["suggested_first_action"],
        )
        
        return intent_model
    
    def _save_intent_model(self, intent_model: IntentModel) -> None:
        """
        Save intent model to disk using atomic write pattern.
        
        Args:
            intent_model: The intent model to save
        """
        # Convert to dictionary
        intent_dict = {
            "timestamp": intent_model.timestamp.isoformat(),
            "active_projects": intent_model.active_projects,
            "open_loops": intent_model.open_loops,
            "today_deadlines": intent_model.today_deadlines,
            "focus_mode": intent_model.focus_mode,
            "recommended_music": intent_model.recommended_music,
            "suggested_first_action": intent_model.suggested_first_action,
        }
        
        # Atomic write using temp file + rename
        try:
            fd, temp_path = tempfile.mkstemp(
                dir=self.state_dir,
                prefix=".intent_",
                suffix=".tmp",
                text=True,
            )
            
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(intent_dict, f, indent=2, ensure_ascii=False)
                
                # Atomic rename
                if os.name == "nt" and self.intent_file.exists():
                    self.intent_file.unlink()
                
                os.rename(temp_path, self.intent_file)
                
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                raise
        
        except Exception as e:
            print(f"[IntentionEngine] ❌ Failed to save intent model: {e}", flush=True)
            raise
    
    def _load_previous_intent(self) -> Optional[IntentModel]:
        """
        Load the previous intent model from disk (fallback on error).
        
        Returns:
            IntentModel if file exists and is valid, None otherwise
        """
        if not self.intent_file.exists():
            print("[IntentionEngine] ⚠️  No previous intent.json found", flush=True)
            return None
        
        try:
            with open(self.intent_file, "r", encoding="utf-8") as f:
                intent_dict = json.load(f)
            
            # Parse timestamp
            timestamp = datetime.fromisoformat(intent_dict["timestamp"])
            
            intent_model = IntentModel(
                timestamp=timestamp,
                active_projects=intent_dict["active_projects"],
                open_loops=intent_dict["open_loops"],
                today_deadlines=intent_dict["today_deadlines"],
                focus_mode=intent_dict["focus_mode"],
                recommended_music=intent_dict["recommended_music"],
                suggested_first_action=intent_dict["suggested_first_action"],
            )
            
            print(f"[IntentionEngine] ✅ Loaded previous intent model from {timestamp.isoformat()}", flush=True)
            return intent_model
            
        except Exception as e:
            print(f"[IntentionEngine] ❌ Failed to load previous intent.json: {e}", flush=True)
            return None
    
    def load_intent_model(self) -> Optional[IntentModel]:
        """
        Load the current intent model from disk.
        
        Returns:
            IntentModel if file exists and is valid, None otherwise
        """
        return self._load_previous_intent()
