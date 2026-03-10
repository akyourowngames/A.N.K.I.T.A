#!/usr/bin/env python3
"""
Memory System inspired by OpenClaw
- Daily JSONL logs for 24-hour conversation tracking
- Markdown files for long-term curated memory
- Automatic extraction of user preferences and important info
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any


class MemorySystem:
    """Manages conversation memory with daily logs and curated knowledge"""
    
    def __init__(self, memory_dir: str = "memory"):
        self.memory_dir = Path(memory_dir)
        self.daily_dir = self.memory_dir / "daily"
        
        # Create directories
        self.memory_dir.mkdir(exist_ok=True)
        self.daily_dir.mkdir(exist_ok=True)
        
        # Memory files
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.preferences_file = self.memory_dir / "preferences.md"
        
        # Initialize files if they don't exist
        self._init_memory_files()
    
    def _init_memory_files(self):
        """Initialize memory files with templates"""
        if not self.memory_file.exists():
            self.memory_file.write_text(
                "# Long-Term Memory\n\n"
                "This file contains curated, long-term knowledge about the user.\n\n"
                "## Important Facts\n\n"
                "## Ongoing Projects\n\n"
                "## Decisions & Patterns\n\n"
            )
        
        if not self.preferences_file.exists():
            self.preferences_file.write_text(
                "# User Preferences\n\n"
                "## Personal Information\n\n"
                "## Communication Style\n\n"
                "## Technical Preferences\n\n"
            )
    
    def get_today_log_file(self) -> Path:
        """Get today's JSONL log file"""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.daily_dir / f"{today}.jsonl"
    
    def log_conversation(self, role: str, content: str, metadata: Dict[str, Any] = None):
        """
        Log a conversation turn to today's JSONL file
        
        Args:
            role: 'user' or 'assistant'
            content: The message content
            metadata: Optional metadata (timestamp, etc.)
        """
        log_file = self.get_today_log_file()
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "content": content
        }
        
        if metadata:
            entry.update(metadata)
        
        # Append to JSONL file
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def extract_and_save_preferences(self, user_message: str, assistant_response: str) -> List[str]:
        """
        Automatically extract preferences and important info from conversation
        Uses regex patterns to detect common preference indicators
        """
        extractions = []
        lowered_message = user_message.lower()
        compact_fragments = [fragment.strip() for fragment in re.split(r"[,|/]", lowered_message) if fragment.strip()]
        
        # Pattern 1: "My name is X" or "I'm X"
        name_patterns = [
            r"my name is (\w+)",
            r"i'm (\w+)",
            r"i am (\w+)",
            r"call me (\w+)"
        ]
        for pattern in name_patterns:
            match = re.search(pattern, lowered_message)
            if match:
                name = match.group(1).capitalize()
                extractions.append(("name", f"User's name: {name}"))
        
        # Pattern 2: "I prefer X" or "I like X"
        preference_patterns = [
            r"i prefer ([^.!?]+)",
            r"i like ([^.!?]+)",
            r"i love ([^.!?]+)",
            r"i want ([^.!?]+)"
        ]
        for pattern in preference_patterns:
            match = re.search(pattern, lowered_message)
            if match:
                pref = match.group(1).strip()
                extractions.append(("preference", f"Preference: {pref}"))
        
        # Pattern 3: "I don't like X" or "I hate X"
        dislike_patterns = [
            r"i don't like ([^.!?]+)",
            r"i hate ([^.!?]+)",
            r"i dislike ([^.!?]+)"
        ]
        for pattern in dislike_patterns:
            match = re.search(pattern, lowered_message)
            if match:
                dislike = match.group(1).strip()
                extractions.append(("dislike", f"Dislikes: {dislike}"))

        # Pattern 4: Age mentions
        age_patterns = [
            r"\bage\s*(?:is|:)?\s*(\d{1,3})\b",
            r"\bi(?:'m| am)\s+(\d{1,3})\b",
            r"\b(\d{1,3})\s*(?:years old|yrs old|yrs|yo)\b",
        ]
        for pattern in age_patterns:
            match = re.search(pattern, lowered_message)
            if match:
                age = int(match.group(1))
                if 1 <= age <= 120:
                    extractions.append(("age", f"Age: {age}"))
                    break

        for fragment in compact_fragments:
            if re.fullmatch(r"\d{1,3}", fragment):
                age = int(fragment)
                if 1 <= age <= 120:
                    extractions.append(("age", f"Age: {age}"))
                    break

        # Pattern 5: Gender mentions
        gender_map = {
            "male": "male",
            "man": "male",
            "boy": "male",
            "female": "female",
            "woman": "female",
            "girl": "female",
            "nonbinary": "non-binary",
            "non-binary": "non-binary",
        }
        gender_patterns = [
            r"\bgender\s*(?:is|:)?\s*(male|female|man|woman|boy|girl|nonbinary|non-binary)\b",
            r"\b(male|female|man|woman|boy|girl|nonbinary|non-binary)\b",
        ]
        for pattern in gender_patterns:
            match = re.search(pattern, lowered_message)
            if match:
                normalized_gender = gender_map[match.group(1)]
                extractions.append(("gender", f"Gender: {normalized_gender}"))
                break
        
        # Pattern 6: Location mentions
        location_pattern = r"i (?:live|am) (?:in|from|at) ([^.!?]+)"
        match = re.search(location_pattern, lowered_message)
        if match:
            location = match.group(1).strip()
            extractions.append(("location", f"Location: {location}"))
        
        # Pattern 7: Project/work mentions
        project_patterns = [
            r"working on ([^.!?]+)",
            r"building ([^.!?]+)",
            r"creating ([^.!?]+)",
            r"my project (?:is )?([^.!?]+)"
        ]
        for pattern in project_patterns:
            match = re.search(pattern, lowered_message)
            if match:
                project = match.group(1).strip()
                extractions.append(("project", f"Project: {project}"))
        
        # Save extractions to preferences file
        if extractions:
            return self._append_to_preferences(extractions)

        return []
    
    def _append_to_preferences(self, extractions: List[tuple]) -> List[str]:
        """Append extracted preferences to preferences.md"""
        content = self.preferences_file.read_text(encoding='utf-8')
        existing_lines = {
            line.strip() for line in content.splitlines()
            if line.strip().startswith("- ")
        }

        unique_entries = []
        for _, text in extractions:
            if not text or not text.strip():
                continue
            bullet = f"- {text}"
            if bullet not in existing_lines:
                unique_entries.append(text)
                existing_lines.add(bullet)

        if not unique_entries:
            return []
        
        # Add timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_entries = f"\n## Extracted on {timestamp}\n\n"
        
        for text in unique_entries:
            new_entries += f"- {text}\n"
        
        # Append to file
        self.preferences_file.write_text(content + new_entries, encoding='utf-8')
        return unique_entries
    
    def add_to_memory(self, category: str, content: str) -> bool:
        """
        Manually add content to long-term memory
        
        Args:
            category: Section name (e.g., "Important Facts", "Decisions")
            content: Content to add
        """
        content = (content or "").strip()
        if not content:
            return False

        memory_content = self.memory_file.read_text(encoding='utf-8')
        
        # Find the category section
        category_header = f"## {category}"
        if category_header not in memory_content:
            # Add new category
            memory_content += f"\n{category_header}\n\n"
        
        # Add content under category
        timestamp = datetime.now().strftime("%Y-%m-%d")
        new_entry = f"- [{timestamp}] {content}\n"
        
        # Insert after category header
        lines = memory_content.split('\n')
        new_lines = []
        found_category = False
        
        for line in lines:
            new_lines.append(line)
            if line.strip() == category_header:
                found_category = True
                # Skip empty lines after header
                continue
            if found_category and line.strip() and not line.startswith('#'):
                # Insert before next content
                new_lines.insert(-1, new_entry)
                found_category = False
        
        if found_category:
            # Category was last, append
            new_lines.append(new_entry)
        
        self.memory_file.write_text('\n'.join(new_lines), encoding='utf-8')
        return True
    
    def get_recent_context(self, days: int = 2) -> str:
        """
        Get recent conversation context from daily logs
        
        Args:
            days: Number of days to look back
        
        Returns:
            Formatted context string
        """
        context_parts = []
        
        for i in range(days):
            date = datetime.now()
            if i > 0:
                from datetime import timedelta
                date = date - timedelta(days=i)
            
            log_file = self.daily_dir / f"{date.strftime('%Y-%m-%d')}.jsonl"
            
            if log_file.exists():
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    # Get last 10 messages
                    recent = lines[-10:] if len(lines) > 10 else lines
                    
                    for line in recent:
                        try:
                            entry = json.loads(line)
                            role = entry.get('role', 'unknown')
                            content = entry.get('content', '')
                            context_parts.append(f"{role}: {content[:100]}...")
                        except:
                            continue
        
        return '\n'.join(context_parts) if context_parts else "No recent context"
    
    def get_memory_context(self) -> str:
        """Get personality, long-term memory, preferences, and recent conversation history for context"""
        context = []
        
        # Add personality (SOUL.md) - highest priority
        soul_file = self.memory_dir / "SOUL.md"
        if soul_file.exists():
            soul_content = soul_file.read_text(encoding='utf-8')
            if "Configuration Status: Complete" in soul_content:
                context.append("=== ANKITA'S PERSONALITY (SOUL) ===")
                context.append(soul_content)
        
        # Add preferences
        if self.preferences_file.exists():
            prefs = self.preferences_file.read_text()
            context.append("\n=== USER PREFERENCES ===")
            context.append(prefs)
        
        # Add long-term memory
        if self.memory_file.exists():
            memory = self.memory_file.read_text()
            context.append("\n=== LONG-TERM MEMORY ===")
            context.append(memory)
        
        # Add recent conversation history from daily logs
        recent = self.get_recent_context(days=1)
        if recent and recent != "No recent context":
            context.append("\n=== RECENT CONVERSATION (Today) ===")
            context.append(recent)
        
        return '\n'.join(context)
    
    def search_memory(self, query: str, include_logs: bool = False) -> List[str]:
        """
        Search stored memory files, with optional conversation log search
        
        Args:
            query: Search query
            include_logs: Include daily conversation logs in results
        
        Returns:
            List of matching lines
        """
        results = []
        query_lower = query.lower()
        
        # Search in all markdown files
        for md_file in self.memory_dir.glob("*.md"):
            content = md_file.read_text()
            for line in content.split('\n'):
                if query_lower in line.lower():
                    results.append(f"[{md_file.name}] {line.strip()}")
        
        if include_logs:
            # Search in recent daily logs
            for log_file in sorted(self.daily_dir.glob("*.jsonl"), reverse=True)[:7]:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            entry = json.loads(line)
                            content = entry.get('content', '')
                            if query_lower in content.lower():
                                results.append(f"[{log_file.name}] {content[:100]}...")
                        except:
                            continue
        
        return results[:10]  # Return top 10 results
