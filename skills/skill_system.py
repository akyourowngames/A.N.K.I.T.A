#!/usr/bin/env python3
"""
OpenClaw-inspired Skills System for ANKITA
Skills are pre-built workflows that combine multiple tools
"""

import re
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class SkillSystem:
    """Manages skills - pre-built workflows that combine tools"""
    
    def __init__(self):
        # Three-tier skill directories (priority: workspace > user > bundled)
        self.workspace_skills_dir = Path(".kiro/skills")
        self.user_skills_dir = Path.home() / ".kiro" / "skills"
        self.bundled_skills_dir = Path("skills/bundled")
        
        # Create directories
        self.workspace_skills_dir.mkdir(parents=True, exist_ok=True)
        self.user_skills_dir.mkdir(parents=True, exist_ok=True)
        self.bundled_skills_dir.mkdir(parents=True, exist_ok=True)
        
        # Skill cache
        self.skills_cache: Dict[str, Dict] = {}
    
    def scan_skills(self) -> Dict[str, Dict]:
        """
        Scan all skill directories and build skill catalog
        This runs on EVERY prompt for hot-reload (sub-millisecond operation)
        
        Returns:
            Dict mapping skill_name -> skill_metadata
        """
        skills = {}
        
        # Scan in priority order (later overrides earlier)
        for skills_dir in [self.bundled_skills_dir, self.user_skills_dir, self.workspace_skills_dir]:
            if not skills_dir.exists():
                continue
            
            # Each skill is a folder with SKILL.md inside
            for skill_folder in skills_dir.iterdir():
                if not skill_folder.is_dir():
                    continue
                
                skill_file = skill_folder / "SKILL.md"
                if not skill_file.exists():
                    continue
                
                # Parse the skill
                skill_data = self._parse_skill_file(skill_file)
                if skill_data:
                    skill_name = skill_data.get('name', skill_folder.name)
                    skills[skill_name] = {
                        'name': skill_name,
                        'description': skill_data.get('description', ''),
                        'trigger': skill_data.get('trigger', ''),
                        'steps': skill_data.get('steps', ''),
                        'rules': skill_data.get('rules', ''),
                        'path': str(skill_file),
                        'source': skills_dir.name
                    }
        
        self.skills_cache = skills
        return skills
    
    def _parse_skill_file(self, skill_file: Path) -> Optional[Dict]:
        """
        Parse a SKILL.md file
        
        Format:
        ---
        name: skill-name
        description: One-line description
        trigger: When to activate this skill
        ---
        
        ## Steps
        1. Do this
        2. Do that
        
        ## Rules
        - Never do this
        """
        try:
            content = skill_file.read_text(encoding='utf-8')
            
            # Extract YAML frontmatter
            frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)
            if not frontmatter_match:
                return None
            
            frontmatter_text = frontmatter_match.group(1)
            body = frontmatter_match.group(2)
            
            # Parse YAML
            metadata = yaml.safe_load(frontmatter_text) or {}
            
            # Extract sections from body
            steps_match = re.search(r'## Steps\s*\n(.*?)(?=\n##|\Z)', body, re.DOTALL)
            rules_match = re.search(r'## Rules\s*\n(.*?)(?=\n##|\Z)', body, re.DOTALL)
            
            metadata['steps'] = steps_match.group(1).strip() if steps_match else ''
            metadata['rules'] = rules_match.group(1).strip() if rules_match else ''
            
            return metadata
        
        except Exception as e:
            print(f"Warning: Failed to parse {skill_file}: {e}")
            return None
    
    def get_skills_summary(self) -> str:
        """
        Get compact summary of available skills for system prompt injection
        
        Format (OpenClaw-style):
        <skills>
        - skill-name: One-line description
        - another-skill: Another description
        </skills>
        
        Cost: 195 chars base + 97 chars per skill
        """
        skills = self.scan_skills()
        
        if not skills:
            return ""
        
        lines = ["<skills>"]
        for skill_name, skill_data in skills.items():
            desc = skill_data.get('description', 'No description')
            lines.append(f"- {skill_name}: {desc}")
        lines.append("</skills>")
        
        return '\n'.join(lines)
    
    def get_skill_instructions(self, skill_name: str) -> Optional[str]:
        """
        Get full instructions for a specific skill
        Only called when skill is actually triggered
        
        Returns:
            Full skill instructions or None if not found
        """
        skills = self.scan_skills()
        skill = skills.get(skill_name)
        
        if not skill:
            return None
        
        # Build full instructions
        instructions = []
        instructions.append(f"# {skill['name']}")
        instructions.append(f"\n{skill.get('description', '')}\n")
        
        if skill.get('trigger'):
            instructions.append(f"**Trigger:** {skill['trigger']}\n")
        
        if skill.get('steps'):
            instructions.append("## Steps")
            instructions.append(skill['steps'])
        
        if skill.get('rules'):
            instructions.append("\n## Rules")
            instructions.append(skill['rules'])
        
        return '\n'.join(instructions)

    def _keyword_matches(self, keyword: str, message_lower: str) -> bool:
        """Match trigger keywords as whole words or phrases, not loose substrings."""
        cleaned = (keyword or "").strip().lower()
        if not cleaned:
            return False

        escaped = re.escape(cleaned).replace(r"\ ", r"\s+")
        pattern = rf"(?<!\w){escaped}(?!\w)"
        return bool(re.search(pattern, message_lower))
    
    def match_skill(self, user_message: str) -> Optional[Tuple[str, str]]:
        """
        Match user message to a skill based on trigger conditions
        
        Args:
            user_message: User's input message
        
        Returns:
            Tuple of (skill_name, skill_instructions) or None
        """
        skills = self.scan_skills()
        
        for skill_name, skill_data in skills.items():
            trigger = skill_data.get('trigger', '').lower()
            message_lower = user_message.lower()
            
            # Split trigger into individual keywords
            keywords = [kw.strip() for kw in trigger.split(',')]
            
            # Check if any keyword appears in the message
            for keyword in keywords:
                if self._keyword_matches(keyword, message_lower):
                    instructions = self.get_skill_instructions(skill_name)
                    return (skill_name, instructions)
        
        return None
    
    def create_skill(self, skill_name: str, description: str, trigger: str, 
                    steps: str, rules: str = "", location: str = "workspace") -> bool:
        """
        Create a new skill (used by skill-creator meta-skill)
        
        Args:
            skill_name: Name of the skill (will be folder name)
            description: One-line description
            trigger: When to activate (comma-separated keywords)
            steps: Step-by-step instructions
            rules: Rules and constraints
            location: 'workspace', 'user', or 'bundled'
        
        Returns:
            True if successful
        """
        # Choose directory based on location
        if location == "user":
            skills_dir = self.user_skills_dir
        elif location == "bundled":
            skills_dir = self.bundled_skills_dir
        else:
            skills_dir = self.workspace_skills_dir
        
        # Create skill folder
        skill_folder = skills_dir / skill_name
        skill_folder.mkdir(parents=True, exist_ok=True)
        
        # Create SKILL.md
        skill_file = skill_folder / "SKILL.md"
        
        default_rules = '- Follow best practices\n- Ask for confirmation before destructive operations'
        rules_content = rules if rules else default_rules
        
        content = f"""---
name: {skill_name}
description: {description}
trigger: {trigger}
---

## Steps
{steps}

## Rules
{rules_content}
"""
        
        skill_file.write_text(content, encoding='utf-8')
        
        # Clear cache to force rescan
        self.skills_cache = {}
        
        return True
    
    def list_skills(self) -> List[Dict]:
        """Get list of all available skills with metadata"""
        skills = self.scan_skills()
        return list(skills.values())
