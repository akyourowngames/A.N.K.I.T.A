"""
Conversation Memory - Enhanced context-aware memory system.

Features:
- Remember context from recent interactions
- Store user preferences (favorite apps, music, etc.)
- Smart suggestions based on time/context
- Learning mode - learn from corrections and improve

Usage:
    from memory.conversation_memory import ConversationMemory
    memory = ConversationMemory()
    memory.add_context("played lofi music", action="youtube.play", entities={"query": "lofi"})
    suggestions = memory.get_suggestions()
"""

import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from threading import Lock
from collections import defaultdict

# Paths
_MEMORY_DIR = Path(__file__).parent
CONTEXT_PATH = _MEMORY_DIR / "conversation_context.json"
USER_PREFS_PATH = _MEMORY_DIR / "user_preferences.json"
LEARNING_PATH = _MEMORY_DIR / "learning_data.json"
SUGGESTIONS_PATH = _MEMORY_DIR / "smart_suggestions.json"

# Constants
MAX_CONTEXT_ENTRIES = 100
MAX_LEARNING_ENTRIES = 500
CONTEXT_WINDOW_HOURS = 24


class ConversationMemory:
    """Enhanced context-aware memory with learning capabilities."""
    
    def __init__(self):
        self._lock = Lock()
        self._context: List[Dict] = []
        self._user_prefs: Dict[str, Any] = {}
        self._learning_data: Dict[str, Any] = {}
        self._action_patterns: Dict[str, int] = {}
        self._time_patterns: Dict[str, List[str]] = {}
        
        self._load_all()
    
    # ==================== File I/O ====================
    
    def _load_json(self, path: Path, default: Any) -> Any:
        """Load JSON file with fallback."""
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[ConversationMemory] Failed to load {path.name}: {e}")
            return default
    
    def _save_json(self, path: Path, data: Any) -> None:
        """Save data to JSON file."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ConversationMemory] Failed to save {path.name}: {e}")
    
    def _load_all(self) -> None:
        """Load all memory files."""
        self._context = self._load_json(CONTEXT_PATH, [])
        self._user_prefs = self._load_json(USER_PREFS_PATH, self._get_default_prefs())
        self._learning_data = self._load_json(LEARNING_PATH, {
            "corrections": [],
            "action_frequency": {},
            "time_patterns": {},
            "entity_preferences": {}
        })
    
    def _save_all(self) -> None:
        """Persist all memory files."""
        self._save_json(CONTEXT_PATH, self._context[-MAX_CONTEXT_ENTRIES:])
        self._save_json(USER_PREFS_PATH, self._user_prefs)
        self._save_json(LEARNING_PATH, self._learning_data)
    
    def _get_default_prefs(self) -> Dict:
        """Get default user preferences structure."""
        return {
            "favorite_apps": [],
            "favorite_music": [],
            "preferred_volume": 50,
            "preferred_brightness": 70,
            "morning_routine": [],
            "evening_routine": [],
            "work_hours": {"start": "09:00", "end": "18:00"},
            "preferred_browser": "chrome",
            "social_apps": ["instagram", "whatsapp", "discord"],
            "productivity_apps": ["notepad", "vscode", "chrome"],
            "entertainment_apps": ["youtube", "spotify"]
        }
    
    # ==================== Context Management ====================
    
    def add_context(
        self,
        summary: str,
        action: Optional[str] = None,
        entities: Optional[Dict] = None,
        result: Optional[Dict] = None,
        topic: Optional[str] = None
    ) -> None:
        """
        Add a context entry for recent interaction.
        
        Args:
            summary: Human-readable summary of what happened
            action: The intent/action that was performed
            entities: Extracted entities from the command
            result: Result of the action
            topic: Optional topic classification
        """
        with self._lock:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "summary": summary,
                "action": action,
                "entities": entities or {},
                "result": result or {},
                "topic": topic or self._detect_topic(summary, action),
                "hour": datetime.now().hour,
                "day_of_week": datetime.now().strftime("%A")
            }
            
            self._context.append(entry)
            
            # Update action patterns for learning
            if action:
                self._update_action_pattern(action, entry)
            
            # Trim old entries
            if len(self._context) > MAX_CONTEXT_ENTRIES:
                self._context = self._context[-MAX_CONTEXT_ENTRIES:]
            
            self._save_json(CONTEXT_PATH, self._context)
        
        print(f"[ConversationMemory] Added context: {summary[:50]}...")
    
    def get_recent_context(self, limit: int = 10, hours: int = None) -> List[Dict]:
        """Get recent context entries."""
        with self._lock:
            entries = self._context[-limit:] if self._context else []
            
            if hours:
                cutoff = datetime.now() - timedelta(hours=hours)
                entries = [
                    e for e in entries
                    if datetime.fromisoformat(e["timestamp"]) > cutoff
                ]
            
            return entries
    
    def get_context_for_action(self, action: str, limit: int = 5) -> List[Dict]:
        """Get recent context related to a specific action."""
        with self._lock:
            related = [e for e in self._context if e.get("action") == action]
            return related[-limit:]
    
    def get_context_summary(self) -> str:
        """Get a human-readable summary of recent context."""
        recent = self.get_recent_context(limit=5)
        if not recent:
            return "No recent activity recorded."
        
        lines = ["Recent activity:"]
        for entry in recent:
            time_str = self._format_time_ago(entry.get("timestamp"))
            lines.append(f"- {time_str}: {entry.get('summary', 'Unknown action')}")
        
        return "\n".join(lines)
    
    def _detect_topic(self, summary: str, action: Optional[str]) -> str:
        """Detect topic from summary and action."""
        text = f"{summary} {action or ''}".lower()
        
        topic_keywords = {
            "music": ["music", "song", "lofi", "spotify", "play", "beats"],
            "video": ["youtube", "video", "watch", "movie", "stream"],
            "work": ["notepad", "vscode", "code", "write", "document"],
            "social": ["instagram", "whatsapp", "discord", "message", "chat"],
            "system": ["volume", "brightness", "wifi", "bluetooth", "power"],
            "search": ["search", "google", "find", "look up"],
            "schedule": ["remind", "alarm", "timer", "schedule"],
        }
        
        for topic, keywords in topic_keywords.items():
            if any(kw in text for kw in keywords):
                return topic
        
        return "general"
    
    def _format_time_ago(self, timestamp: str) -> str:
        """Format timestamp as relative time."""
        try:
            dt = datetime.fromisoformat(timestamp)
            delta = datetime.now() - dt
            minutes = int(delta.total_seconds() / 60)
            
            if minutes < 1:
                return "Just now"
            elif minutes < 60:
                return f"{minutes}m ago"
            elif minutes < 1440:
                return f"{minutes // 60}h ago"
            else:
                return f"{minutes // 1440}d ago"
        except:
            return "Unknown time"
    
    # ==================== User Preferences ====================
    
    def set_preference(self, key: str, value: Any) -> None:
        """Set a user preference."""
        with self._lock:
            self._user_prefs[key] = value
            self._save_json(USER_PREFS_PATH, self._user_prefs)
        
        print(f"[ConversationMemory] Set preference: {key} = {value}")
    
    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        return self._user_prefs.get(key, default)
    
    def add_favorite(self, category: str, item: str) -> None:
        """Add an item to a favorites list."""
        key = f"favorite_{category}"
        with self._lock:
            if key not in self._user_prefs:
                self._user_prefs[key] = []
            if item not in self._user_prefs[key]:
                self._user_prefs[key].insert(0, item)
                self._user_prefs[key] = self._user_prefs[key][:20]  # Keep top 20
                self._save_json(USER_PREFS_PATH, self._user_prefs)
        
        print(f"[ConversationMemory] Added favorite {category}: {item}")
    
    def get_favorites(self, category: str) -> List[str]:
        """Get favorites for a category."""
        return self._user_prefs.get(f"favorite_{category}", [])
    
    def learn_preference_from_action(self, action: str, entities: Dict) -> None:
        """Learn preferences from user actions."""
        with self._lock:
            # Learn favorite music from youtube plays
            if "youtube" in action and "query" in entities:
                query = entities["query"]
                if any(w in query.lower() for w in ["music", "song", "lofi", "beats"]):
                    self._add_to_list("favorite_music", query)
            
            # Learn favorite apps from app opens
            if "app.open" in action and "app" in entities:
                self._add_to_list("favorite_apps", entities["app"])
            
            # Learn volume/brightness preferences
            if "volume.set" in action and "value" in entities:
                self._user_prefs["preferred_volume"] = entities["value"]
            
            if "brightness.set" in action and "value" in entities:
                self._user_prefs["preferred_brightness"] = entities["value"]
            
            self._save_json(USER_PREFS_PATH, self._user_prefs)
    
    def _add_to_list(self, key: str, item: str) -> None:
        """Add item to a preference list (internal, no lock)."""
        if key not in self._user_prefs:
            self._user_prefs[key] = []
        if item not in self._user_prefs[key]:
            self._user_prefs[key].insert(0, item)
            self._user_prefs[key] = self._user_prefs[key][:20]
    
    def get_all_preferences(self) -> Dict[str, Any]:
        """Get all user preferences."""
        return self._user_prefs.copy()
    
    # ==================== Smart Suggestions ====================
    
    def get_suggestions(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get smart suggestions based on time, context, and patterns.
        
        Returns list of suggestions with:
        - action: The suggested action/intent
        - reason: Why this is suggested
        - confidence: 0-100 confidence score
        - entities: Suggested entities
        """
        suggestions = []
        current_hour = datetime.now().hour
        current_day = datetime.now().strftime("%A")
        
        # Time-based suggestions
        time_suggestions = self._get_time_based_suggestions(current_hour, current_day)
        suggestions.extend(time_suggestions)
        
        # Pattern-based suggestions
        pattern_suggestions = self._get_pattern_based_suggestions()
        suggestions.extend(pattern_suggestions)
        
        # Context continuation suggestions
        context_suggestions = self._get_context_continuation_suggestions()
        suggestions.extend(context_suggestions)
        
        # Sort by confidence and deduplicate
        seen_actions = set()
        unique_suggestions = []
        for s in sorted(suggestions, key=lambda x: x.get("confidence", 0), reverse=True):
            if s["action"] not in seen_actions:
                seen_actions.add(s["action"])
                unique_suggestions.append(s)
        
        return unique_suggestions[:limit]
    
    def _get_time_based_suggestions(self, hour: int, day: str) -> List[Dict]:
        """Get suggestions based on time patterns."""
        suggestions = []
        time_patterns = self._learning_data.get("time_patterns", {})
        
        # Check for patterns at this hour
        hour_key = str(hour)
        if hour_key in time_patterns:
            patterns = time_patterns[hour_key]
            for action, count in patterns.items():
                if count >= 3:  # Need at least 3 occurrences
                    suggestions.append({
                        "action": action,
                        "reason": f"You usually do this around {hour}:00",
                        "confidence": min(count * 10, 80),
                        "entities": {}
                    })
        
        # Morning suggestions (6-9 AM)
        if 6 <= hour <= 9:
            morning_routine = self._user_prefs.get("morning_routine", [])
            for action in morning_routine:
                suggestions.append({
                    "action": action,
                    "reason": "Part of your morning routine",
                    "confidence": 70,
                    "entities": {}
                })
        
        # Evening suggestions (6-10 PM)
        if 18 <= hour <= 22:
            if self._user_prefs.get("favorite_music"):
                suggestions.append({
                    "action": "youtube.play",
                    "reason": "Evening relaxation time",
                    "confidence": 60,
                    "entities": {"query": self._user_prefs["favorite_music"][0]}
                })
        
        return suggestions
    
    def _get_pattern_based_suggestions(self) -> List[Dict]:
        """Get suggestions based on action frequency patterns."""
        suggestions = []
        action_freq = self._learning_data.get("action_frequency", {})
        
        # Get most frequent actions
        sorted_actions = sorted(action_freq.items(), key=lambda x: x[1], reverse=True)
        
        for action, count in sorted_actions[:3]:
            if count >= 5:
                suggestions.append({
                    "action": action,
                    "reason": f"Frequently used ({count} times)",
                    "confidence": min(count * 5, 70),
                    "entities": {}
                })
        
        return suggestions
    
    def _get_context_continuation_suggestions(self) -> List[Dict]:
        """Get suggestions based on recent context."""
        suggestions = []
        recent = self.get_recent_context(limit=3)
        
        if not recent:
            return suggestions
        
        last_action = recent[-1].get("action", "")
        last_topic = recent[-1].get("topic", "")
        
        # Suggest related actions based on last action
        continuations = {
            "youtube.play": [
                {"action": "system.volume.up", "reason": "Adjust volume for playback"},
                {"action": "window_control.fullscreen", "reason": "Watch in fullscreen"}
            ],
            "notepad.open": [
                {"action": "notepad.write", "reason": "Start writing"},
                {"action": "notepad.save", "reason": "Save your work"}
            ],
            "instagram.open": [
                {"action": "instagram.feed", "reason": "Check your feed"},
                {"action": "instagram.reels", "reason": "Watch reels"}
            ],
            "system.app.open": [
                {"action": "window_control.maximize", "reason": "Maximize window"}
            ]
        }
        
        if last_action in continuations:
            for suggestion in continuations[last_action]:
                suggestion["confidence"] = 65
                suggestion["entities"] = {}
                suggestions.append(suggestion)
        
        return suggestions
    
    # ==================== Learning Mode ====================
    
    def record_correction(
        self,
        original_intent: str,
        corrected_intent: str,
        original_entities: Dict,
        corrected_entities: Dict,
        user_input: str
    ) -> None:
        """
        Record when the user corrects Ankita's interpretation.
        
        This helps learn from mistakes and improve over time.
        """
        with self._lock:
            correction = {
                "timestamp": datetime.now().isoformat(),
                "user_input": user_input,
                "original_intent": original_intent,
                "corrected_intent": corrected_intent,
                "original_entities": original_entities,
                "corrected_entities": corrected_entities
            }
            
            if "corrections" not in self._learning_data:
                self._learning_data["corrections"] = []
            
            self._learning_data["corrections"].append(correction)
            
            # Trim old corrections
            if len(self._learning_data["corrections"]) > MAX_LEARNING_ENTRIES:
                self._learning_data["corrections"] = self._learning_data["corrections"][-MAX_LEARNING_ENTRIES:]
            
            self._save_json(LEARNING_PATH, self._learning_data)
        
        print(f"[ConversationMemory] Recorded correction: {original_intent} -> {corrected_intent}")
    
    def _update_action_pattern(self, action: str, entry: Dict) -> None:
        """Update action patterns for learning (internal, no lock needed)."""
        # Update action frequency
        if "action_frequency" not in self._learning_data:
            self._learning_data["action_frequency"] = {}
        
        freq = self._learning_data["action_frequency"]
        freq[action] = freq.get(action, 0) + 1
        
        # Update time patterns
        if "time_patterns" not in self._learning_data:
            self._learning_data["time_patterns"] = {}
        
        hour_key = str(entry.get("hour", datetime.now().hour))
        if hour_key not in self._learning_data["time_patterns"]:
            self._learning_data["time_patterns"][hour_key] = {}
        
        time_patterns = self._learning_data["time_patterns"][hour_key]
        time_patterns[action] = time_patterns.get(action, 0) + 1
        
        self._save_json(LEARNING_PATH, self._learning_data)
    
    def get_learned_patterns(self) -> Dict[str, Any]:
        """Get all learned patterns for analysis."""
        return {
            "action_frequency": self._learning_data.get("action_frequency", {}),
            "time_patterns": self._learning_data.get("time_patterns", {}),
            "corrections_count": len(self._learning_data.get("corrections", [])),
            "entity_preferences": self._learning_data.get("entity_preferences", {})
        }
    
    def get_common_corrections(self) -> List[Tuple[str, str, int]]:
        """
        Get common corrections to identify patterns.
        
        Returns list of (original_intent, corrected_intent, count) tuples.
        """
        corrections = self._learning_data.get("corrections", [])
        pattern_counts = defaultdict(int)
        
        for c in corrections:
            key = (c.get("original_intent", ""), c.get("corrected_intent", ""))
            pattern_counts[key] += 1
        
        return sorted(
            [(k[0], k[1], v) for k, v in pattern_counts.items()],
            key=lambda x: x[2],
            reverse=True
        )[:10]
    
    def should_suggest_correction(self, intent: str, user_input: str) -> Optional[str]:
        """
        Check if a correction should be suggested based on learning.
        
        Returns the suggested corrected intent, or None.
        """
        common_corrections = self.get_common_corrections()
        
        for original, corrected, count in common_corrections:
            if original == intent and count >= 3:
                return corrected
        
        return None
    
    # ==================== Routines ====================
    
    def add_to_routine(self, routine_type: str, action: str) -> None:
        """Add an action to morning/evening routine."""
        key = f"{routine_type}_routine"
        with self._lock:
            if key not in self._user_prefs:
                self._user_prefs[key] = []
            if action not in self._user_prefs[key]:
                self._user_prefs[key].append(action)
                self._save_json(USER_PREFS_PATH, self._user_prefs)
        
        print(f"[ConversationMemory] Added to {routine_type} routine: {action}")
    
    def get_routine(self, routine_type: str) -> List[str]:
        """Get morning/evening routine actions."""
        return self._user_prefs.get(f"{routine_type}_routine", [])
    
    def clear_routine(self, routine_type: str) -> None:
        """Clear a routine."""
        key = f"{routine_type}_routine"
        with self._lock:
            self._user_prefs[key] = []
            self._save_json(USER_PREFS_PATH, self._user_prefs)
    
    # ==================== Cross-Tool Context Sharing ====================
    
    def set_tool_context(self, tool_name: str, key: str, value: Any, ttl_minutes: int = 30) -> None:
        """
        Set context that can be shared between tools.
        
        Args:
            tool_name: Name of the tool setting the context (e.g., 'instagram', 'youtube')
            key: Context key (e.g., 'current_user', 'last_search')
            value: Context value
            ttl_minutes: Time-to-live in minutes (default 30)
        """
        with self._lock:
            if "tool_context" not in self._learning_data:
                self._learning_data["tool_context"] = {}
            
            context_entry = {
                "value": value,
                "set_by": tool_name,
                "timestamp": datetime.now().isoformat(),
                "expires": (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat()
            }
            
            full_key = f"{tool_name}.{key}"
            self._learning_data["tool_context"][full_key] = context_entry
            self._save_json(LEARNING_PATH, self._learning_data)
        
        print(f"[Memory] Set context: {full_key} = {str(value)[:50]}")
    
    def get_tool_context(self, tool_name: str, key: str, default: Any = None) -> Any:
        """
        Get context set by a tool.
        
        Args:
            tool_name: Name of the tool that set the context
            key: Context key
            default: Default value if not found or expired
        """
        with self._lock:
            if "tool_context" not in self._learning_data:
                return default
            
            full_key = f"{tool_name}.{key}"
            entry = self._learning_data["tool_context"].get(full_key)
            
            if not entry:
                return default
            
            # Check expiry
            try:
                expires = datetime.fromisoformat(entry["expires"])
                if datetime.now() > expires:
                    # Expired - remove and return default
                    del self._learning_data["tool_context"][full_key]
                    self._save_json(LEARNING_PATH, self._learning_data)
                    return default
            except:
                pass
            
            return entry.get("value", default)
    
    def get_global_context(self, key: str, default: Any = None) -> Any:
        """Get context from any tool by key (searches all tools)."""
        with self._lock:
            if "tool_context" not in self._learning_data:
                return default
            
            for full_key, entry in self._learning_data["tool_context"].items():
                if full_key.endswith(f".{key}"):
                    # Check expiry
                    try:
                        expires = datetime.fromisoformat(entry["expires"])
                        if datetime.now() > expires:
                            continue
                    except:
                        pass
                    return entry.get("value", default)
            
            return default
    
    def get_last_tool_action(self, tool_name: str = None) -> Optional[Dict]:
        """
        Get the last action for a specific tool or any tool.
        
        Returns dict with: action, entities, result, timestamp
        """
        recent = self.get_recent_context(limit=20)
        
        for entry in reversed(recent):
            action = entry.get("action", "")
            if tool_name is None:
                return entry
            if action.startswith(f"{tool_name}."):
                return entry
        
        return None
    
    def get_cross_tool_suggestions(self, current_tool: str) -> List[Dict]:
        """
        Get suggestions for the current tool based on other tools' context.
        
        For example, if YouTube just played music, Instagram might suggest
        sharing that music or checking related content.
        """
        suggestions = []
        
        # Get recent context from other tools
        recent = self.get_recent_context(limit=10)
        
        # Cross-tool patterns
        cross_patterns = {
            # If user just watched YouTube, suggest Instagram reels
            ("youtube", "instagram"): {
                "trigger_actions": ["youtube.play", "youtube.open"],
                "suggestions": [
                    {"action": "instagram.reels", "reason": "Watch reels after YouTube"},
                ]
            },
            # If user just messaged on Instagram, suggest WhatsApp
            ("instagram", "whatsapp"): {
                "trigger_actions": ["instagram.dm"],
                "suggestions": [
                    {"action": "system.app.open", "reason": "Maybe check WhatsApp too?", "entities": {"app": "whatsapp"}}
                ]
            },
            # If user opened social app, might want music
            ("instagram", "youtube"): {
                "trigger_actions": ["instagram.open", "instagram.feed"],
                "suggestions": [
                    {"action": "youtube.play", "reason": "Play some background music?"}
                ]
            }
        }
        
        for entry in recent:
            action = entry.get("action", "")
            source_tool = action.split(".")[0] if "." in action else action
            
            # Check cross-tool patterns
            pattern_key = (source_tool, current_tool)
            if pattern_key in cross_patterns:
                pattern = cross_patterns[pattern_key]
                if action in pattern["trigger_actions"]:
                    for suggestion in pattern["suggestions"]:
                        suggestion["confidence"] = 50
                        suggestion["source_tool"] = source_tool
                        suggestions.append(suggestion)
        
        return suggestions
    
    def share_content(self, content_type: str, content: Any, source_tool: str) -> None:
        """
        Share content between tools (e.g., share a username, URL, search query).
        
        Args:
            content_type: Type of content ('username', 'url', 'query', 'text')
            content: The actual content
            source_tool: Tool that is sharing this content
        """
        self.set_tool_context("shared", content_type, {
            "value": content,
            "source": source_tool,
            "timestamp": datetime.now().isoformat()
        }, ttl_minutes=60)
        
        # Also store in a quick-access shared list
        with self._lock:
            if "shared_content" not in self._learning_data:
                self._learning_data["shared_content"] = []
            
            self._learning_data["shared_content"].insert(0, {
                "type": content_type,
                "content": content,
                "source": source_tool,
                "timestamp": datetime.now().isoformat()
            })
            
            # Keep last 50 shared items
            self._learning_data["shared_content"] = self._learning_data["shared_content"][:50]
            self._save_json(LEARNING_PATH, self._learning_data)
    
    def get_shared_content(self, content_type: str = None, limit: int = 5) -> List[Dict]:
        """
        Get recently shared content.
        
        Args:
            content_type: Filter by type ('username', 'url', 'query') or None for all
            limit: Maximum items to return
        """
        shared = self._learning_data.get("shared_content", [])
        
        if content_type:
            shared = [s for s in shared if s.get("type") == content_type]
        
        return shared[:limit]
    
    def get_instagram_context(self) -> Dict:
        """Get all Instagram-related context for the tool to use."""
        return {
            "last_profile_viewed": self.get_tool_context("instagram", "last_profile"),
            "last_search": self.get_tool_context("instagram", "last_search"),
            "current_page": self.get_tool_context("instagram", "current_page"),
            "likes_today": self.get_tool_context("instagram", "likes_today", 0),
            "dms_sent": self.get_tool_context("instagram", "dms_sent", 0),
            "favorite_users": self.get_favorites("instagram_users"),
            "recent_dms": self.get_tool_context("instagram", "recent_dms", []),
        }
    
    def get_youtube_context(self) -> Dict:
        """Get all YouTube-related context for the tool to use."""
        return {
            "last_video": self.get_tool_context("youtube", "last_video"),
            "last_search": self.get_tool_context("youtube", "last_search"),
            "is_playing": self.get_tool_context("youtube", "is_playing", False),
            "current_playlist": self.get_tool_context("youtube", "current_playlist"),
            "favorite_music": self.get_favorites("music"),
            "watch_history_today": self.get_tool_context("youtube", "history_count", 0),
        }
    
    def cleanup_expired_context(self) -> int:
        """Remove expired tool context entries. Returns count of removed items."""
        removed = 0
        with self._lock:
            if "tool_context" not in self._learning_data:
                return 0
            
            to_remove = []
            for key, entry in self._learning_data["tool_context"].items():
                try:
                    expires = datetime.fromisoformat(entry.get("expires", ""))
                    if datetime.now() > expires:
                        to_remove.append(key)
                except:
                    pass
            
            for key in to_remove:
                del self._learning_data["tool_context"][key]
                removed += 1
            
            if removed > 0:
                self._save_json(LEARNING_PATH, self._learning_data)
        
        return removed


# Singleton instance
_conversation_memory: Optional[ConversationMemory] = None


def get_conversation_memory() -> ConversationMemory:
    """Get the singleton ConversationMemory instance."""
    global _conversation_memory
    if _conversation_memory is None:
        _conversation_memory = ConversationMemory()
    return _conversation_memory

