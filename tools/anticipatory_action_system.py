"""
AnticipatoryActionSystem for the Proactive Intelligence System.

Pre-executes low-risk actions based on predictions from behavioral_model.json
and intent.json. Caches results with 30-minute TTL for instant serving when
the user requests the action.

Low-risk actions include:
- Morning news search (read-only)
- Git status checks (read-only)
- Watchdog summary preparation (read-only)

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
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


# ---------------------------------------------------------------------------
# Module-level helpers used by _manage_environment
# ---------------------------------------------------------------------------

# Module-level queue reference — set by ProactiveEngine.start()
# so _manage_environment can push events without a circular import.
_PROACTIVE_QUEUE_REF: Any = None


def _set_proactive_queue(q: Any) -> None:
    """Called by ProactiveEngine to inject a queue reference."""
    global _PROACTIVE_QUEUE_REF
    _PROACTIVE_QUEUE_REF = q


def _push_proactive_event(event: Any) -> None:
    """Push a ProactiveEvent into the engine queue if available."""
    if _PROACTIVE_QUEUE_REF is not None:
        try:
            _PROACTIVE_QUEUE_REF.put(event)
        except Exception:
            pass


def _hour_in_range(hour: int, time_range: str) -> bool:
    """
    Return True if `hour` falls within `time_range` (format: "HH:MM-HH:MM").

    Args:
        hour: Integer hour (0-23)
        time_range: Range string like "09:00-12:00"
    """
    try:
        start_str, end_str = time_range.split("-")
        start_hour = int(start_str.split(":")[0])
        end_hour = int(end_str.split(":")[0])
        if start_hour <= end_hour:
            return start_hour <= hour < end_hour
        # Overnight range (e.g. "22:00-02:00")
        return hour >= start_hour or hour < end_hour
    except (ValueError, AttributeError):
        return False


def _log_auto_action(state_dir: Path, cls: str, action: str, desc: str) -> None:
    """Append to auto_actions_log.json (best-effort)."""
    try:
        log_file = state_dir / "auto_actions_log.json"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "class": cls,
            "action": action,
            "description": desc[:200],
        }
        log: List[Dict[str, Any]] = []
        if log_file.exists():
            try:
                raw = log_file.read_text(encoding="utf-8")
                loaded = json.loads(raw)
                if isinstance(loaded, list):
                    log = loaded
            except Exception:
                pass
        log.append(entry)
        if len(log) > 200:
            log = log[-200:]
        log_file.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


class AnticipatoryActionSystem:
    """
    Pre-executes low-risk actions based on behavioral and intent models.
    
    Runs continuously as part of the ProactiveEngine polling loop, checking
    for predictable actions and pre-executing them to cache results.
    
    The cached results are served when the user requests the action, providing
    instant responses for common queries.
    
    Low-Risk Action Criteria:
    - Read-only operations
    - No external API calls with side effects
    - No file writes (except cache)
    - No system state changes
    """
    
    # Cache TTL in seconds (30 minutes)
    CACHE_TTL_SEC = 1800
    
    def __init__(self, workspace_root: Path) -> None:
        """
        Initialize the AnticipatoryActionSystem.
        
        Args:
            workspace_root: Root directory of the workspace (contains .ankita/)
        """
        self.workspace_root = workspace_root
        self.state_dir = workspace_root / ".ankita" / "state"
        self.cache_file = self.state_dir / "prefetch_cache.json"
        self.intent_file = self.state_dir / "intent.json"
        self.behavioral_model_file = self.state_dir / "behavioral_model.json"
        
        # Ensure state directory exists
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache
        self._cache: Dict[str, Dict[str, Any]] = {}
        
        # Load cache from disk on initialization
        self._load_cache()
    
    def _load_cache(self) -> None:
        """
        Load cache from disk on startup.
        """
        if not self.cache_file.exists():
            self._cache = {}
            return
        
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
            
            print(
                f"[AnticipatoryActionSystem] ✅ Cache loaded with {len(self._cache)} entries",
                flush=True,
            )
        except Exception as e:
            print(
                f"[AnticipatoryActionSystem] ⚠️  Failed to load cache: {e}",
                flush=True,
            )
            self._cache = {}
    
    def _save_cache(self) -> None:
        """
        Save cache to disk using atomic write pattern.
        """
        try:
            # Write to temporary file first
            fd, temp_path = tempfile.mkstemp(
                dir=self.state_dir,
                prefix=".prefetch_cache_",
                suffix=".tmp",
                text=True,
            )
            
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._cache, f, indent=2, ensure_ascii=False)
                
                # Atomic rename
                if os.name == "nt" and self.cache_file.exists():
                    self.cache_file.unlink()
                
                os.rename(temp_path, self.cache_file)
                
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                raise
        
        except Exception as e:
            print(
                f"[AnticipatoryActionSystem] ❌ Failed to save cache: {e}",
                flush=True,
            )
    
    def _is_cache_fresh(self, cache_entry: Dict[str, Any]) -> bool:
        """
        Check if a cache entry is still fresh (within TTL).
        
        Args:
            cache_entry: Cache entry dictionary with cached_at and ttl_sec fields
            
        Returns:
            True if cache is fresh, False if expired
        """
        cached_at = cache_entry.get("cached_at")
        ttl_sec = cache_entry.get("ttl_sec", self.CACHE_TTL_SEC)
        
        if not cached_at:
            return False
        
        try:
            cached_time = datetime.fromisoformat(cached_at)
            age_sec = (datetime.now() - cached_time).total_seconds()
            return age_sec < ttl_sec
        except (ValueError, TypeError):
            return False
    
    def _cache_action(self, action_key: str, data: Any) -> None:
        """
        Cache the result of a pre-executed action.
        
        Args:
            action_key: Unique key for the action (e.g., "morning_news", "git_status")
            data: Data to cache
        """
        self._cache[action_key] = {
            "cached_at": datetime.now().isoformat(),
            "ttl_sec": self.CACHE_TTL_SEC,
            "data": data,
        }
        
        self._save_cache()
    
    def get_cached_action(self, action_key: str) -> Optional[Any]:
        """
        Get cached action result if fresh.
        
        Args:
            action_key: Unique key for the action
            
        Returns:
            Cached data if fresh, None if expired or not found
        """
        cache_entry = self._cache.get(action_key)
        
        if not cache_entry:
            return None
        
        if not self._is_cache_fresh(cache_entry):
            # Remove expired entry
            del self._cache[action_key]
            self._save_cache()
            return None
        
        return cache_entry.get("data")
    
    def _load_intent_model(self) -> Optional[Dict[str, Any]]:
        """
        Load the current intent model from disk.
        
        Returns:
            Intent model dictionary if exists, None otherwise
        """
        if not self.intent_file.exists():
            return None
        
        try:
            with open(self.intent_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(
                f"[AnticipatoryActionSystem] ⚠️  Failed to load intent model: {e}",
                flush=True,
            )
            return None
    
    def _load_behavioral_model(self) -> Optional[Dict[str, Any]]:
        """
        Load the current behavioral model from disk.
        
        Returns:
            Behavioral model dictionary if exists, None otherwise
        """
        if not self.behavioral_model_file.exists():
            return None
        
        try:
            with open(self.behavioral_model_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(
                f"[AnticipatoryActionSystem] ⚠️  Failed to load behavioral model: {e}",
                flush=True,
            )
            return None
    
    def _should_prefetch_morning_news(
        self,
        behavioral_model: Dict[str, Any],
        current_time: datetime,
    ) -> bool:
        """
        Check if we should pre-fetch morning news based on behavioral patterns.
        
        Pre-fetches 5 minutes before typical morning routine start time.
        
        Args:
            behavioral_model: Behavioral model dictionary
            current_time: Current datetime
            
        Returns:
            True if we should pre-fetch, False otherwise
        """
        morning_routine = behavioral_model.get("morning_routine", {})
        typical_start_time = morning_routine.get("typical_start_time")
        
        if not typical_start_time:
            return False
        
        try:
            # Parse typical start time (format: "HH:MM")
            hour, minute = map(int, typical_start_time.split(":"))
            
            # Calculate pre-fetch time (5 minutes before)
            prefetch_hour = hour
            prefetch_minute = minute - 5
            
            if prefetch_minute < 0:
                prefetch_minute += 60
                prefetch_hour -= 1
            
            # Check if current time matches pre-fetch time (within 1-minute window)
            current_hour = current_time.hour
            current_minute = current_time.minute
            
            # Allow 1-minute window for pre-fetching (to account for polling intervals)
            if current_hour == prefetch_hour:
                if abs(current_minute - prefetch_minute) <= 1:
                    return True
        
        except (ValueError, AttributeError):
            pass
        
        return False
    
    def _should_prefetch_git_status(
        self,
        behavioral_model: Dict[str, Any],
        current_time: datetime,
    ) -> bool:
        """
        Check if we should pre-fetch git status based on peak coding hours.
        
        Pre-fetches during peak coding hours.
        
        Args:
            behavioral_model: Behavioral model dictionary
            current_time: Current datetime
            
        Returns:
            True if we should pre-fetch, False otherwise
        """
        peak_coding_hours = behavioral_model.get("peak_coding_hours", [])
        
        if not peak_coding_hours:
            return False
        
        current_hour = current_time.hour
        current_minute = current_time.minute
        
        for time_range in peak_coding_hours:
            try:
                # Parse time range (format: "HH:MM-HH:MM")
                start_str, end_str = time_range.split("-")
                start_hour, start_minute = map(int, start_str.split(":"))
                end_hour, end_minute = map(int, end_str.split(":"))
                
                # Convert to minutes for easier comparison
                current_minutes = current_hour * 60 + current_minute
                start_minutes = start_hour * 60 + start_minute
                end_minutes = end_hour * 60 + end_minute
                
                if start_minutes <= current_minutes <= end_minutes:
                    return True
            
            except (ValueError, AttributeError):
                continue
        
        return False
    
    def _should_prefetch_watchdog_summary(
        self,
        idle_time_hours: float,
    ) -> bool:
        """
        Check if we should pre-fetch watchdog summary based on idle time.
        
        Pre-fetches after 3 hours of idle time.
        
        Args:
            idle_time_hours: Hours since last user activity
            
        Returns:
            True if we should pre-fetch, False otherwise
        """
        return idle_time_hours >= 3.0
    
    def _prefetch_morning_news(self) -> None:
        """
        Pre-fetch morning news (low-risk read-only action).
        
        This is a placeholder that would integrate with a news search API
        or web search tool in the actual implementation.
        """
        try:
            # Placeholder: In actual implementation, this would call a news search API
            # For now, we'll create a simple mock result
            news_data = {
                "articles": [
                    {
                        "title": "Morning news placeholder",
                        "source": "News API",
                        "timestamp": datetime.now().isoformat(),
                    }
                ],
                "prefetched": True,
            }
            
            self._cache_action("morning_news", news_data)
            
            print(
                "[AnticipatoryActionSystem] 📰 Pre-fetched morning news",
                flush=True,
            )
        
        except Exception as e:
            print(
                f"[AnticipatoryActionSystem] ⚠️  Failed to pre-fetch morning news: {e}",
                flush=True,
            )
    
    def _prefetch_git_status(self) -> None:
        """
        Pre-fetch git status (low-risk read-only action).
        
        Runs 'git status --porcelain' to get repository status.
        """
        try:
            # Run git status
            result = subprocess.run(
                ["git", "status", "--porcelain", "--branch"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            if result.returncode == 0:
                # Parse git status output
                lines = result.stdout.strip().split("\n")
                branch_line = lines[0] if lines else ""
                
                # Extract branch name
                branch = "unknown"
                if branch_line.startswith("## "):
                    branch_info = branch_line[3:]
                    if "..." in branch_info:
                        branch = branch_info.split("...")[0]
                    else:
                        branch = branch_info.split()[0] if branch_info else "unknown"
                
                # Count changes
                modified = 0
                untracked = 0
                staged = 0
                
                for line in lines[1:]:
                    if not line:
                        continue
                    
                    status_code = line[:2]
                    
                    if status_code[0] in ["M", "A", "D", "R", "C"]:
                        staged += 1
                    if status_code[1] in ["M", "D"]:
                        modified += 1
                    if status_code == "??":
                        untracked += 1
                
                git_data = {
                    "status": "clean" if not (modified + untracked + staged) else "dirty",
                    "branch": branch,
                    "modified": modified,
                    "untracked": untracked,
                    "staged": staged,
                    "prefetched": True,
                }
                
                self._cache_action("git_status", git_data)
                
                print(
                    f"[AnticipatoryActionSystem] 🔧 Pre-fetched git status: {branch} ({git_data['status']})",
                    flush=True,
                )
            else:
                # Not a git repository or error
                print(
                    f"[AnticipatoryActionSystem] ⚠️  Git status failed: {result.stderr}",
                    flush=True,
                )
        
        except Exception as e:
            print(
                f"[AnticipatoryActionSystem] ⚠️  Failed to pre-fetch git status: {e}",
                flush=True,
            )
    
    def _prefetch_watchdog_summary(self) -> None:
        """
        Pre-fetch watchdog summary (low-risk read-only action).
        
        Gathers current state of all watchdogs.
        """
        try:
            # Try to get watchdog states
            from watchdog_manager import get_instance
            
            watchdog_mgr = get_instance()
            if not watchdog_mgr:
                return
            
            summary = {
                "watchers": {},
                "total_alerts": 0,
                "prefetched": True,
            }
            
            for name, watcher in watchdog_mgr._watchers.items():
                watcher_info = {
                    "alive": watcher.is_alive(),
                    "state": watcher.state,
                }
                
                # Count alerts if available
                if hasattr(watcher, "alerts"):
                    alert_count = len(watcher.alerts)
                    watcher_info["alert_count"] = alert_count
                    summary["total_alerts"] += alert_count
                
                summary["watchers"][name] = watcher_info
            
            self._cache_action("watchdog_summary", summary)
            
            print(
                f"[AnticipatoryActionSystem] 👁️  Pre-fetched watchdog summary: {len(summary['watchers'])} watchers",
                flush=True,
            )
        
        except Exception as e:
            print(
                f"[AnticipatoryActionSystem] ⚠️  Failed to pre-fetch watchdog summary: {e}",
                flush=True,
            )
    
    def run_anticipatory_cycle(self, idle_time_hours: float = 0.0) -> None:
        """
        Run one cycle of anticipatory action pre-execution.
        
        Called by ProactiveEngine in its polling loop to check for predictable
        actions and pre-execute them.
        
        Args:
            idle_time_hours: Hours since last user activity (for watchdog summary)
        """
        # Load models
        intent_model = self._load_intent_model()
        behavioral_model = self._load_behavioral_model()
        
        if not behavioral_model:
            # No behavioral model yet, skip anticipatory actions
            return
        
        current_time = datetime.now()
        
        # Check if we should pre-fetch morning news
        if self._should_prefetch_morning_news(behavioral_model, current_time):
            # Only pre-fetch if not already cached
            if not self.get_cached_action("morning_news"):
                self._prefetch_morning_news()
        
        # Check if we should pre-fetch git status
        if self._should_prefetch_git_status(behavioral_model, current_time):
            # Only pre-fetch if not already cached
            if not self.get_cached_action("git_status"):
                self._prefetch_git_status()
        
        # Check if we should pre-fetch watchdog summary
        if self._should_prefetch_watchdog_summary(idle_time_hours):
            # Only pre-fetch if not already cached
            if not self.get_cached_action("watchdog_summary"):
                self._prefetch_watchdog_summary()

        # Step 11: Environment management (deep_work music + health reminder)
        self._manage_environment(intent_model, behavioral_model)

    def _manage_environment(
        self,
        intent_model: Optional[Dict[str, Any]],
        behavioral_model: Dict[str, Any],
    ) -> None:
        """
        Step 11: Environment management based on focus_mode and coding time.

        Rules:
          1. focus_mode == "deep_work" → suggest lofi music (once per session, low priority).
          2. Continuous active coding > 2h → emit a health/break reminder (medium priority).

        All suggestions are emitted as ProactiveEvents via a lightweight
        module-level _proactive_queue probe, logged to auto_actions_log.json.
        """
        now = datetime.now()
        _HEALTH_KEY = "health_reminder"
        _MUSIC_KEY = "deep_work_music"

        # --- Guard: only emit each nudge once per 2 hours via cache ---
        health_entry = self._cache.get(_HEALTH_KEY)
        music_entry = self._cache.get(_MUSIC_KEY)

        # 1. Deep-work music suggestion
        focus_mode = (intent_model or {}).get("focus_mode", "")
        if focus_mode == "deep_work":
            if not (music_entry and self._is_cache_fresh(music_entry)):
                try:
                    from proactive_models import ProactiveEvent  # type: ignore
                    msg = (
                        "🎵 Deep-work mode detected. Want me to start some lofi music "
                        "to keep you in flow? (say 'play lofi')"
                    )
                    _push_proactive_event(ProactiveEvent(
                        kind="auto_action",
                        message=msg,
                        data={"action": "deep_work_music"},
                        priority="low",
                        urgency="next_idle",
                        interruptible=False,
                    ))
                    self._cache_action(_MUSIC_KEY, {"suggested": True})
                    _log_auto_action(self.state_dir, "A", "deep_work_music", msg)
                    print("[AnticipatoryActionSystem] 🎵 Deep-work music suggestion emitted.", flush=True)
                except Exception as _e:
                    print(f"[AnticipatoryActionSystem] ⚠️  Music suggestion failed: {_e}", flush=True)

        # 2. Health/break reminder after 2h of continuous work
        peak_coding_hours = behavioral_model.get("peak_coding_hours", [])
        current_hour = now.hour
        in_peak = any(
            _hour_in_range(current_hour, r) for r in peak_coding_hours
        )

        if in_peak and not (health_entry and self._is_cache_fresh(health_entry)):
            # Rate-limit: TTL of 2 hours for health reminder
            try:
                from proactive_models import ProactiveEvent  # type: ignore
                msg = (
                    "🧘 You've been coding for a while. Time for a short break — "
                    "stand up, stretch, and grab some water! 💧"
                )
                _push_proactive_event(ProactiveEvent(
                    kind="auto_action",
                    message=msg,
                    data={"action": "health_reminder"},
                    priority="medium",
                    urgency="next_idle",
                    interruptible=False,
                ))
                self._cache[_HEALTH_KEY] = {
                    "cached_at": now.isoformat(),
                    "ttl_sec": 7200,  # 2 hours
                    "data": {"reminded": True},
                }
                self._save_cache()
                _log_auto_action(self.state_dir, "B", "health_reminder", msg)
                print("[AnticipatoryActionSystem] 🧘 Health reminder emitted.", flush=True)
            except Exception as _e:
                print(f"[AnticipatoryActionSystem] ⚠️  Health reminder failed: {_e}", flush=True)
    
    def clear_cache(self) -> None:
        """
        Clear all cached actions.
        
        Useful for testing or manual cache invalidation.
        """
        self._cache = {}
        self._save_cache()
        
        print(
            "[AnticipatoryActionSystem] 🗑️  Cache cleared",
            flush=True,
        )
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the current cache.
        
        Returns:
            Dictionary with cache statistics
        """
        total_entries = len(self._cache)
        fresh_entries = 0
        expired_entries = 0
        
        for entry in self._cache.values():
            if self._is_cache_fresh(entry):
                fresh_entries += 1
            else:
                expired_entries += 1
        
        return {
            "total_entries": total_entries,
            "fresh_entries": fresh_entries,
            "expired_entries": expired_entries,
            "cache_file": str(self.cache_file),
        }
