---
name: skill-creator
description: Creates new custom skills for ANKITA (meta-skill for self-expansion)
trigger: create skill, build skill, new skill, design skill, custom workflow, automation
---

## Steps

1. **Understand the requirement**
   - Ask clarifying questions if needed:
     - What should this skill do?
     - What are 1-2 example prompts that should trigger it?
     - Does it need any external APIs or tools?
   - If the user provides clear requirements, proceed directly

2. **Search for existing approaches (REQUIRED)**
   - ALWAYS use search_web tool before drafting:
     - Search for existing implementations or libraries
     - Search for best practices for this type of task
     - Search for API documentation if needed
   - Example searches:
     - "how to [task] in Python"
     - "[library name] API documentation"
     - "best practices for [task]"
   - Don't invent from scratch what already exists

3. **Draft the SKILL.md**
   - Choose appropriate location:
     - workspace: Project-specific skills
     - user: Personal skills across all projects
   - Write clear, specific trigger conditions (comma-separated keywords)
   - Write step-by-step instructions that are:
     - Specific, not vague
     - Actionable by an LLM
     - Include tool calls where needed (search_web, fetch_webpage, execute_terminal_command, etc.)
   - Add safety rules (confirmations, validations)
   - Include examples from your web search

4. **Test the skill**
   - Immediately try triggering the newly created skill
   - Use an example prompt that matches the trigger
   - If it fails, debug and rewrite the SKILL.md
   - Use terminal tool to test any scripts if needed

5. **Register and confirm**
   - Hot-reload picks it up automatically on next turn
   - Log what was created to memory
   - Confirm to user with skill name and trigger keywords

## Rules

- ALWAYS search online first before drafting (use search_web tool - this is MANDATORY)
- Write triggers as comma-separated keywords (e.g., "weather, forecast, temperature")
- Be specific in steps - avoid vague instructions like "do the right thing"
- Include safety rules for destructive operations (delete, send, purchase)
- Test immediately after creation - don't assume it works
- Skills that write files should output to workspace folder by default
- Skills that need secrets should use environment variables, never hardcode
- If a skill is too complex, break it into multiple smaller skills
- Reference the web search results in the skill instructions
- Include tool names explicitly (search_web, fetch_webpage, execute_terminal_command, create_skill)
