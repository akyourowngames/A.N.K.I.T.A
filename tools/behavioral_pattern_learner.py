"""
BehavioralPatternLearner for the Proactive Intelligence System.

Learns user behavioral patterns over time by:
1. Recording behavioral fingerprints after every Orchestrator interaction
2. Analyzing patterns weekly (Sunday 22:00-23:00)
3. Synthesizing patterns using LLM
4. Writing behavioral_model.json
5. Pruning old patterns (>30 days)

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from proactive_models import BehavioralFingerprint, BehavioralModel


class BehavioralPatternLearner:
    """
    Learns user behavioral patterns over time.
    
    Records fingerprints after every interaction and performs weekly analysis
    to identify patterns like morning routines, peak coding hours, and common
    mistakes.
    
    The behavioral model is used by:
    - AnticipatoryActionSystem: Pre-executes actions based on patterns
    - DeadlineCascadePredictor: Estimates task complexity from historical data
    - EnvironmentManager: Adjusts environment based on typical work patterns
    """
    
    def __init__(self, workspace_root: Path) -> None:
        """
        Initialize the BehavioralPatternLearner.
        
        Args:
            workspace_root: Root directory of the workspace (contains .ankita/)
        """
        self.workspace_root = workspace_root
        self.state_dir = workspace_root / ".ankita" / "state"
        self.patterns_file = self.state_dir / "patterns.jsonl"
        self.behavioral_model_file = self.state_dir / "behavioral_model.json"
        
        # Ensure state directory exists
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # LLM runtime (injected by caller)
        self._runtime: Optional[Any] = None
    
    def attach_runtime(self, runtime: Any) -> None:
        """
        Inject the LLM runtime for pattern synthesis.
        
        Args:
            runtime: The active LLMRuntime instance
        """
        self._runtime = runtime
    
    def record_fingerprint(
        self,
        interaction_type: str,
        duration_sec: int,
        tools_used: List[str],
        context: str,
    ) -> None:
        """
        Record a behavioral fingerprint after an Orchestrator interaction.
        
        Appends a single line to patterns.jsonl with the interaction details.
        
        Args:
            interaction_type: Type of interaction ("code", "write", "search", "system")
            duration_sec: How long the interaction took in seconds
            tools_used: List of tool names used during the interaction
            context: Brief description of what the user was working on
        """
        fingerprint = BehavioralFingerprint(
            timestamp=datetime.now(),
            interaction_type=interaction_type,
            duration_sec=duration_sec,
            tools_used=tools_used,
            context=context,
        )
        
        # Convert to dictionary for JSON serialization
        fingerprint_dict = {
            "timestamp": fingerprint.timestamp.isoformat(),
            "interaction_type": fingerprint.interaction_type,
            "duration_sec": fingerprint.duration_sec,
            "tools_used": fingerprint.tools_used,
            "context": fingerprint.context,
        }
        
        # Append to patterns.jsonl
        try:
            with open(self.patterns_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(fingerprint_dict, ensure_ascii=False) + "\n")
        except Exception as e:
            print(
                f"[BehavioralPatternLearner] ❌ Failed to record fingerprint: {e}",
                flush=True,
            )
    
    def should_run_analysis(self) -> bool:
        """
        Check if it's time to run weekly analysis.
        
        Analysis runs on Sunday between 22:00-23:00.
        
        Returns:
            True if current time is Sunday 22:00-23:00, False otherwise
        """
        now = datetime.now()
        
        # Check if it's Sunday (weekday() returns 6 for Sunday)
        if now.weekday() != 6:
            return False
        
        # Check if it's between 22:00 and 23:00
        if not (22 <= now.hour < 23):
            return False
        
        return True
    
    def analyze_patterns(self) -> Optional[BehavioralModel]:
        """
        Analyze the last 4 weeks of patterns and generate a behavioral model.
        
        Process:
        1. Load last 4 weeks of patterns from patterns.jsonl
        2. Make single LLM call to synthesize patterns
        3. Parse and validate JSON response
        4. Write to behavioral_model.json atomically
        5. Prune patterns older than 30 days
        6. Return the generated model
        
        Returns:
            BehavioralModel if successful, None if analysis failed
        """
        if self._runtime is None:
            print(
                "[BehavioralPatternLearner] ⚠️  No runtime attached — cannot analyze patterns",
                flush=True,
            )
            return None
        
        print("[BehavioralPatternLearner] 🧠 Analyzing behavioral patterns...", flush=True)
        
        # Step 1: Load last 4 weeks of patterns
        patterns = self._load_recent_patterns(weeks=4)
        
        if not patterns:
            print(
                "[BehavioralPatternLearner] ⚠️  No patterns found — skipping analysis",
                flush=True,
            )
            return None
        
        print(
            f"[BehavioralPatternLearner] Loaded {len(patterns)} patterns from last 4 weeks",
            flush=True,
        )
        
        # Step 2: Make LLM call to synthesize patterns
        try:
            behavioral_data = self._call_llm_for_patterns(patterns)
            if not behavioral_data:
                raise ValueError("LLM returned empty behavioral data")
            
            # Step 3: Parse and validate
            behavioral_model = self._parse_and_validate(behavioral_data)
            
            # Step 4: Write to behavioral_model.json atomically
            self._save_behavioral_model(behavioral_model)
            
            # Step 5: Prune old patterns (>30 days)
            self._prune_old_patterns(days=30)
            
            print(
                f"[BehavioralPatternLearner] ✅ Behavioral model generated with {len(behavioral_model.peak_coding_hours)} peak hours",
                flush=True,
            )
            return behavioral_model
            
        except Exception as e:
            print(
                f"[BehavioralPatternLearner] ❌ Failed to analyze patterns: {e}",
                flush=True,
            )
            # Keep previous behavioral_model.json on failure (Requirement 3.5)
            return self._load_previous_model()
    
    def _load_recent_patterns(self, weeks: int = 4) -> List[Dict[str, Any]]:
        """
        Load patterns from the last N weeks.
        
        Args:
            weeks: Number of weeks to look back
            
        Returns:
            List of pattern dictionaries
        """
        if not self.patterns_file.exists():
            return []
        
        cutoff_date = datetime.now() - timedelta(weeks=weeks)
        patterns: List[Dict[str, Any]] = []
        
        try:
            with open(self.patterns_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        pattern = json.loads(line)
                        
                        # Parse timestamp
                        timestamp_str = pattern.get("timestamp", "")
                        if not timestamp_str:
                            continue
                        
                        timestamp = datetime.fromisoformat(timestamp_str)
                        
                        # Filter by cutoff date
                        if timestamp >= cutoff_date:
                            patterns.append(pattern)
                    
                    except (json.JSONDecodeError, ValueError):
                        # Skip malformed lines
                        continue
        
        except Exception as e:
            print(
                f"[BehavioralPatternLearner] ⚠️  Failed to load patterns: {e}",
                flush=True,
            )
            return []
        
        return patterns
    
    def _call_llm_for_patterns(self, patterns: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Make a single LLM call to synthesize behavioral patterns.
        
        Args:
            patterns: List of pattern dictionaries from patterns.jsonl
            
        Returns:
            Parsed JSON dictionary with behavioral model fields
        """
        # Build structured prompt
        prompt = self._build_pattern_prompt(patterns)
        
        # Make LLM call
        from llm.client import call_chat_once
        
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a behavioral pattern analysis system for a proactive AI assistant. "
                    "Analyze the user's interaction patterns and produce a behavioral model in JSON format. "
                    "Output ONLY valid JSON, no markdown fences or explanations."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]
        
        response = call_chat_once(self._runtime, messages, None, max_tokens=1000)
        raw_text = str(response.get("content", "")).strip()
        
        # Parse JSON from response (handle markdown fences if present)
        import re
        # Strip markdown fences
        raw_text = re.sub(r"```(?:json)?", "", raw_text).strip().strip("`")
        
        # Find JSON object
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in LLM response: {raw_text[:200]}")
        
        behavioral_data = json.loads(match.group())
        return behavioral_data
    
    def _build_pattern_prompt(self, patterns: List[Dict[str, Any]]) -> str:
        """
        Build the structured prompt for pattern synthesis.
        
        Args:
            patterns: List of pattern dictionaries
            
        Returns:
            Formatted prompt string
        """
        # Aggregate patterns by hour of day, day of week, interaction type
        hourly_activity = {}
        daily_activity = {}
        type_counts = {}
        tool_usage = {}
        contexts = []
        
        for pattern in patterns:
            # Parse timestamp
            try:
                timestamp = datetime.fromisoformat(pattern["timestamp"])
            except (ValueError, KeyError):
                continue
            
            # Hour of day
            hour = timestamp.hour
            hourly_activity[hour] = hourly_activity.get(hour, 0) + 1
            
            # Day of week
            day = timestamp.strftime("%A")
            daily_activity[day] = daily_activity.get(day, 0) + 1
            
            # Interaction type
            itype = pattern.get("interaction_type", "unknown")
            type_counts[itype] = type_counts.get(itype, 0) + 1
            
            # Tools used
            for tool in pattern.get("tools_used", []):
                tool_usage[tool] = tool_usage.get(tool, 0) + 1
            
            # Context samples (take first 20)
            if len(contexts) < 20:
                ctx = pattern.get("context", "")
                if ctx:
                    contexts.append(ctx)
        
        # Format aggregated data
        hourly_summary = "\n".join(
            f"  {hour:02d}:00 - {count} interactions"
            for hour, count in sorted(hourly_activity.items(), key=lambda x: -x[1])[:10]
        )
        
        daily_summary = "\n".join(
            f"  {day}: {count} interactions"
            for day, count in sorted(daily_activity.items(), key=lambda x: -x[1])
        )
        
        type_summary = "\n".join(
            f"  {itype}: {count} times"
            for itype, count in sorted(type_counts.items(), key=lambda x: -x[1])
        )
        
        tool_summary = "\n".join(
            f"  {tool}: {count} times"
            for tool, count in sorted(tool_usage.items(), key=lambda x: -x[1])[:15]
        )
        
        context_summary = "\n".join(f"  - {ctx[:100]}" for ctx in contexts[:10])
        
        prompt = f"""Analyze these user interaction patterns from the last 4 weeks and produce a behavioral model.

PATTERN DATA:

Total Interactions: {len(patterns)}

Activity by Hour (top 10):
{hourly_summary}

Activity by Day:
{daily_summary}

Interaction Types:
{type_summary}

Most Used Tools:
{tool_summary}

Sample Contexts:
{context_summary}

OUTPUT FORMAT (JSON only):
{{
  "morning_routine": {{
    "typical_start_time": "HH:MM",
    "first_actions": ["action1", "action2"]
  }},
  "peak_coding_hours": ["HH:MM-HH:MM", "HH:MM-HH:MM"],
  "typical_project_switch_time": "N minutes",
  "never_works_on": ["time period 1", "time period 2"],
  "frequently_forgets": ["thing1", "thing2"]
}}

GUIDELINES:
- morning_routine: Identify typical start time and first actions based on early hour activity
- peak_coding_hours: Find 2-3 time ranges with highest activity (use 24-hour format)
- typical_project_switch_time: Estimate average time before context switches (based on interaction durations)
- never_works_on: Identify time periods with consistently zero activity (e.g., "weekends after 6pm")
- frequently_forgets: Infer common mistakes or omissions from tool usage patterns (e.g., if git_commit is rare, "commit messages")

Output JSON only:"""
        
        return prompt
    
    def _parse_and_validate(self, behavioral_data: Dict[str, Any]) -> BehavioralModel:
        """
        Parse and validate the behavioral data from LLM.
        
        Args:
            behavioral_data: Raw JSON dictionary from LLM
            
        Returns:
            Validated BehavioralModel instance
            
        Raises:
            ValueError: If required fields are missing or invalid
        """
        # Validate required fields
        required_fields = [
            "morning_routine",
            "peak_coding_hours",
            "typical_project_switch_time",
            "never_works_on",
            "frequently_forgets",
        ]
        
        for field in required_fields:
            if field not in behavioral_data:
                raise ValueError(f"Missing required field: {field}")
        
        # Validate field types
        if not isinstance(behavioral_data["morning_routine"], dict):
            raise ValueError("morning_routine must be a dictionary")
        if not isinstance(behavioral_data["peak_coding_hours"], list):
            raise ValueError("peak_coding_hours must be a list")
        if not isinstance(behavioral_data["never_works_on"], list):
            raise ValueError("never_works_on must be a list")
        if not isinstance(behavioral_data["frequently_forgets"], list):
            raise ValueError("frequently_forgets must be a list")
        
        # Create BehavioralModel
        behavioral_model = BehavioralModel(
            generated_at=datetime.now(),
            morning_routine=behavioral_data["morning_routine"],
            peak_coding_hours=behavioral_data["peak_coding_hours"],
            typical_project_switch_time=behavioral_data["typical_project_switch_time"],
            never_works_on=behavioral_data["never_works_on"],
            frequently_forgets=behavioral_data["frequently_forgets"],
        )
        
        return behavioral_model
    
    def _save_behavioral_model(self, behavioral_model: BehavioralModel) -> None:
        """
        Save behavioral model to disk using atomic write pattern.
        
        Args:
            behavioral_model: The behavioral model to save
        """
        # Convert to dictionary
        model_dict = {
            "generated_at": behavioral_model.generated_at.isoformat(),
            "morning_routine": behavioral_model.morning_routine,
            "peak_coding_hours": behavioral_model.peak_coding_hours,
            "typical_project_switch_time": behavioral_model.typical_project_switch_time,
            "never_works_on": behavioral_model.never_works_on,
            "frequently_forgets": behavioral_model.frequently_forgets,
        }
        
        # Atomic write using temp file + rename
        try:
            fd, temp_path = tempfile.mkstemp(
                dir=self.state_dir,
                prefix=".behavioral_model_",
                suffix=".tmp",
                text=True,
            )
            
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(model_dict, f, indent=2, ensure_ascii=False)
                
                # Atomic rename
                if os.name == "nt" and self.behavioral_model_file.exists():
                    self.behavioral_model_file.unlink()
                
                os.rename(temp_path, self.behavioral_model_file)
                
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                raise
        
        except Exception as e:
            print(
                f"[BehavioralPatternLearner] ❌ Failed to save behavioral model: {e}",
                flush=True,
            )
            raise
    
    def _prune_old_patterns(self, days: int = 30) -> None:
        """
        Prune patterns older than N days from patterns.jsonl.
        
        Rewrites the file with only recent patterns to prevent unbounded growth.
        
        Args:
            days: Number of days to keep (default 30)
        """
        if not self.patterns_file.exists():
            return
        
        cutoff_date = datetime.now() - timedelta(days=days)
        recent_patterns: List[str] = []
        pruned_count = 0
        total_lines = 0
        
        try:
            # Read all patterns and filter by date
            with open(self.patterns_file, "r", encoding="utf-8") as f:
                for line in f:
                    total_lines += 1
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        pattern = json.loads(line)
                        timestamp_str = pattern.get("timestamp", "")
                        if not timestamp_str:
                            continue
                        
                        timestamp = datetime.fromisoformat(timestamp_str)
                        
                        if timestamp >= cutoff_date:
                            recent_patterns.append(line)
                        else:
                            pruned_count += 1
                    
                    except (json.JSONDecodeError, ValueError):
                        # Skip malformed lines (counts as pruned)
                        pruned_count += 1
                        continue
            
            # Rewrite file with only recent patterns (atomic)
            # Rewrite if we pruned anything (old patterns or malformed lines)
            if pruned_count > 0:
                fd, temp_path = tempfile.mkstemp(
                    dir=self.state_dir,
                    prefix=".patterns_",
                    suffix=".tmp",
                    text=True,
                )
                
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        for line in recent_patterns:
                            f.write(line + "\n")
                    
                    # Atomic rename
                    if os.name == "nt" and self.patterns_file.exists():
                        self.patterns_file.unlink()
                    
                    os.rename(temp_path, self.patterns_file)
                    
                    print(
                        f"[BehavioralPatternLearner] 🗑️  Pruned {pruned_count} old/malformed patterns (>{days} days)",
                        flush=True,
                    )
                
                except Exception:
                    # Clean up temp file on error
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
                    raise
        
        except Exception as e:
            print(
                f"[BehavioralPatternLearner] ⚠️  Failed to prune old patterns: {e}",
                flush=True,
            )
    
    def _load_previous_model(self) -> Optional[BehavioralModel]:
        """
        Load the previous behavioral model from disk (fallback on error).
        
        Returns:
            BehavioralModel if file exists and is valid, None otherwise
        """
        if not self.behavioral_model_file.exists():
            print(
                "[BehavioralPatternLearner] ⚠️  No previous behavioral_model.json found",
                flush=True,
            )
            return None
        
        try:
            with open(self.behavioral_model_file, "r", encoding="utf-8") as f:
                model_dict = json.load(f)
            
            # Parse timestamp
            generated_at = datetime.fromisoformat(model_dict["generated_at"])
            
            behavioral_model = BehavioralModel(
                generated_at=generated_at,
                morning_routine=model_dict["morning_routine"],
                peak_coding_hours=model_dict["peak_coding_hours"],
                typical_project_switch_time=model_dict["typical_project_switch_time"],
                never_works_on=model_dict["never_works_on"],
                frequently_forgets=model_dict["frequently_forgets"],
            )
            
            print(
                f"[BehavioralPatternLearner] ✅ Loaded previous behavioral model from {generated_at.isoformat()}",
                flush=True,
            )
            return behavioral_model
            
        except Exception as e:
            print(
                f"[BehavioralPatternLearner] ❌ Failed to load previous behavioral_model.json: {e}",
                flush=True,
            )
            return None
    
    def load_behavioral_model(self) -> Optional[BehavioralModel]:
        """
        Load the current behavioral model from disk.
        
        Returns:
            BehavioralModel if file exists and is valid, None otherwise
        """
        return self._load_previous_model()
