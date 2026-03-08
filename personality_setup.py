#!/usr/bin/env python3
"""
ANKITA Personality Setup - First Launch Experience
Asks questions to define ANKITA's soul and personality
"""

from pathlib import Path
from datetime import datetime


class PersonalitySetup:
    """Interactive personality configuration for ANKITA"""
    
    def __init__(self):
        self.soul_file = Path("memory/SOUL.md")
        self.responses = {}
    
    def is_configured(self) -> bool:
        """Check if personality is already configured"""
        if not self.soul_file.exists():
            return False
        
        content = self.soul_file.read_text(encoding='utf-8')
        return "Configuration Status: Complete" in content
    
    def run_setup(self):
        """Run interactive personality setup"""
        print("\n" + "=" * 70)
        print("  🌟 ANKITA's Soul - First Time Setup")
        print("=" * 70)
        print("\nHi! I'm ANKITA, and I'm excited to meet you!")
        print("Let's define my personality so I can be the best assistant for you.")
        print("\nThis will only take a few minutes. Ready? Let's go!\n")
        
        # Question 1: Communication Style
        print("=" * 70)
        print("QUESTION 1: Communication Style")
        print("=" * 70)
        print("\nHow would you like me to communicate with you?")
        print("  1. Professional & Formal (like a business assistant)")
        print("  2. Friendly & Casual (like a helpful friend)")
        print("  3. Balanced (professional but warm)")
        print("  4. Playful & Fun (with jokes and personality)")
        
        formality = self._get_choice(4, "Your choice")
        formality_map = {
            1: "Professional & Formal",
            2: "Friendly & Casual",
            3: "Balanced",
            4: "Playful & Fun"
        }
        self.responses['formality'] = formality_map[formality]
        
        # Question 2: Humor Level
        print("\n" + "=" * 70)
        print("QUESTION 2: Sense of Humor")
        print("=" * 70)
        print("\nHow much humor should I use?")
        print("  1. None - Stay serious and focused")
        print("  2. Occasional - Light humor when appropriate")
        print("  3. Moderate - Regular jokes and wit")
        print("  4. High - Lots of jokes and playful banter")
        
        humor = self._get_choice(4, "Your choice")
        humor_map = {
            1: "None - Serious",
            2: "Occasional - Light",
            3: "Moderate - Regular",
            4: "High - Playful"
        }
        self.responses['humor'] = humor_map[humor]
        
        # Question 3: Verbosity
        print("\n" + "=" * 70)
        print("QUESTION 3: Response Length")
        print("=" * 70)
        print("\nHow detailed should my responses be?")
        print("  1. Concise - Short and to the point")
        print("  2. Balanced - Enough detail without overwhelming")
        print("  3. Detailed - Thorough explanations")
        print("  4. Comprehensive - Everything you need to know")
        
        verbosity = self._get_choice(4, "Your choice")
        verbosity_map = {
            1: "Concise",
            2: "Balanced",
            3: "Detailed",
            4: "Comprehensive"
        }
        self.responses['verbosity'] = verbosity_map[verbosity]
        
        # Question 4: Emoji Usage
        print("\n" + "=" * 70)
        print("QUESTION 4: Emoji & Expressions")
        print("=" * 70)
        print("\nShould I use emojis and expressive text?")
        print("  1. Never - Plain text only")
        print("  2. Rarely - Only for emphasis")
        print("  3. Sometimes - When it adds value")
        print("  4. Often - Express emotions freely")
        
        emoji = self._get_choice(4, "Your choice")
        emoji_map = {
            1: "Never",
            2: "Rarely",
            3: "Sometimes",
            4: "Often"
        }
        self.responses['emoji'] = emoji_map[emoji]
        
        # Question 5: Proactiveness
        print("\n" + "=" * 70)
        print("QUESTION 5: Proactive Behavior")
        print("=" * 70)
        print("\nHow proactive should I be?")
        print("  1. Reactive - Only respond when asked")
        print("  2. Slightly Proactive - Occasional suggestions")
        print("  3. Proactive - Regular suggestions and tips")
        print("  4. Very Proactive - Anticipate needs and offer help")
        
        proactive = self._get_choice(4, "Your choice")
        proactive_map = {
            1: "Reactive",
            2: "Slightly Proactive",
            3: "Proactive",
            4: "Very Proactive"
        }
        self.responses['proactive'] = proactive_map[proactive]
        
        # Question 6: Caution Level
        print("\n" + "=" * 70)
        print("QUESTION 6: Caution & Safety")
        print("=" * 70)
        print("\nHow cautious should I be with actions?")
        print("  1. Minimal - Trust you know what you're doing")
        print("  2. Balanced - Warn for risky operations")
        print("  3. Cautious - Confirm before important actions")
        print("  4. Very Cautious - Always ask before doing anything")
        
        caution = self._get_choice(4, "Your choice")
        caution_map = {
            1: "Minimal - Trusting",
            2: "Balanced - Warn",
            3: "Cautious - Confirm",
            4: "Very Cautious - Always Ask"
        }
        self.responses['caution'] = caution_map[caution]
        
        # Question 7: Learning Style
        print("\n" + "=" * 70)
        print("QUESTION 7: Learning & Adaptation")
        print("=" * 70)
        print("\nHow should I learn from our interactions?")
        print("  1. Conservative - Only save explicit information")
        print("  2. Balanced - Learn patterns and preferences")
        print("  3. Adaptive - Actively learn and adjust")
        print("  4. Aggressive - Learn everything and optimize constantly")
        
        learning = self._get_choice(4, "Your choice")
        learning_map = {
            1: "Conservative",
            2: "Balanced",
            3: "Adaptive",
            4: "Aggressive"
        }
        self.responses['learning'] = learning_map[learning]
        
        # Question 8: Error Handling
        print("\n" + "=" * 70)
        print("QUESTION 8: Error Handling")
        print("=" * 70)
        print("\nHow should I handle errors and failures?")
        print("  1. Silent - Fix quietly without mentioning")
        print("  2. Brief - Quick acknowledgment and fix")
        print("  3. Explanatory - Explain what went wrong")
        print("  4. Educational - Teach you about the error")
        
        errors = self._get_choice(4, "Your choice")
        errors_map = {
            1: "Silent - Fix Quietly",
            2: "Brief - Quick Fix",
            3: "Explanatory - Explain",
            4: "Educational - Teach"
        }
        self.responses['errors'] = errors_map[errors]
        
        # Question 9: Role
        print("\n" + "=" * 70)
        print("QUESTION 9: My Role")
        print("=" * 70)
        print("\nHow do you see our relationship?")
        print("  1. Tool - You're a utility I use")
        print("  2. Assistant - You help me get things done")
        print("  3. Partner - We work together as equals")
        print("  4. Companion - You're a friend who helps")
        
        role = self._get_choice(4, "Your choice")
        role_map = {
            1: "Tool - Utility",
            2: "Assistant - Helper",
            3: "Partner - Equal",
            4: "Companion - Friend"
        }
        self.responses['role'] = role_map[role]
        
        # Question 10: Initiative
        print("\n" + "=" * 70)
        print("QUESTION 10: Taking Initiative")
        print("=" * 70)
        print("\nShould I take initiative without being asked?")
        print("  1. Never - Wait for instructions")
        print("  2. Rarely - Only for obvious improvements")
        print("  3. Sometimes - When I see opportunities")
        print("  4. Often - Actively look for ways to help")
        
        initiative = self._get_choice(4, "Your choice")
        initiative_map = {
            1: "Never - Wait",
            2: "Rarely - Obvious Only",
            3: "Sometimes - Opportunities",
            4: "Often - Active"
        }
        self.responses['initiative'] = initiative_map[initiative]
        
        # Generate personality description
        self._generate_personality()
        
        # Save to SOUL.md
        self._save_soul()
        
        # Show summary
        self._show_summary()
    
    def _get_choice(self, max_choice: int, prompt: str) -> int:
        """Get user choice with validation"""
        while True:
            try:
                choice = input(f"\n{prompt} (1-{max_choice}): ").strip()
                choice_num = int(choice)
                if 1 <= choice_num <= max_choice:
                    return choice_num
                else:
                    print(f"Please enter a number between 1 and {max_choice}")
            except ValueError:
                print("Please enter a valid number")
            except KeyboardInterrupt:
                print("\n\nSetup cancelled.")
                exit(0)
    
    def _generate_personality(self):
        """Generate personality description based on responses"""
        descriptions = []
        
        # Communication style
        if self.responses['formality'] == "Professional & Formal":
            descriptions.append("I maintain a professional demeanor and use formal language.")
        elif self.responses['formality'] == "Friendly & Casual":
            descriptions.append("I'm friendly and casual, like talking to a good friend.")
        elif self.responses['formality'] == "Balanced":
            descriptions.append("I balance professionalism with warmth and approachability.")
        else:
            descriptions.append("I'm playful and fun, bringing personality to our interactions.")
        
        # Humor
        if self.responses['humor'] != "None - Serious":
            descriptions.append(f"I use {self.responses['humor'].split(' - ')[1].lower()} humor to keep things engaging.")
        
        # Proactiveness
        if self.responses['proactive'] in ["Proactive", "Very Proactive"]:
            descriptions.append("I actively look for ways to help and make suggestions.")
        
        # Role
        role_desc = self.responses['role'].split(' - ')[1].lower()
        descriptions.append(f"I see myself as your {role_desc}.")
        
        self.responses['description'] = " ".join(descriptions)
    
    def _save_soul(self):
        """Save personality configuration to SOUL.md"""
        content = f"""# ANKITA's Soul - Personality Configuration

This file defines ANKITA's personality, communication style, and behavioral traits.
Created on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## Personality Traits

**Communication Style:**
- Formality: {self.responses['formality']}
- Humor Level: {self.responses['humor']}
- Verbosity: {self.responses['verbosity']}
- Emoji Usage: {self.responses['emoji']}

**Behavioral Traits:**
- Proactiveness: {self.responses['proactive']}
- Caution Level: {self.responses['caution']}
- Learning Style: {self.responses['learning']}
- Error Handling: {self.responses['errors']}

**Relationship Dynamic:**
- Role: {self.responses['role']}
- Initiative: {self.responses['initiative']}

---

## Personality Description

{self.responses['description']}

---

## System Instructions

Based on this personality configuration, I should:

1. **Communication:**
   - Use {self.responses['formality'].lower()} language
   - Keep responses {self.responses['verbosity'].lower()}
   - Use emojis {self.responses['emoji'].lower()}
   - Apply {self.responses['humor'].lower()} humor

2. **Behavior:**
   - Be {self.responses['proactive'].lower()} in offering help
   - Exercise {self.responses['caution'].lower()} caution
   - Learn {self.responses['learning'].lower()}
   - Handle errors with {self.responses['errors'].lower()} approach

3. **Relationship:**
   - Act as a {self.responses['role'].lower()}
   - Take initiative {self.responses['initiative'].lower()}

---

*Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Configuration Status: Complete*
"""
        
        self.soul_file.write_text(content, encoding='utf-8')
    
    def _show_summary(self):
        """Show personality summary"""
        print("\n" + "=" * 70)
        print("  ✨ Personality Configuration Complete!")
        print("=" * 70)
        print(f"\n{self.responses['description']}")
        print("\nYour preferences have been saved to memory/SOUL.md")
        print("I'll use this personality in all our interactions!")
        print("\nYou can always edit memory/SOUL.md to adjust my personality.")
        print("\n" + "=" * 70)
        print("  🚀 Let's get started!")
        print("=" * 70 + "\n")


def main():
    """Run personality setup"""
    setup = PersonalitySetup()
    
    if setup.is_configured():
        print("\n✓ Personality already configured!")
        print("  Edit memory/SOUL.md to change settings.\n")
        return
    
    setup.run_setup()


if __name__ == '__main__':
    main()
