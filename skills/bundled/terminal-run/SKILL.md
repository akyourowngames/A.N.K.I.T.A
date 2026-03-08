---
name: terminal-run
description: Execute terminal commands safely with proper error handling
trigger: run command, execute, terminal, shell, command line, list files, show directory
---

## Steps

1. **Understand the command**
   - Identify what command the user wants to run
   - Check if it's a destructive operation (rm, del, format, etc.)
   - If destructive, ask for explicit confirmation

2. **Validate and fix the command**
   - Check if required tools are available
   - Verify paths exist if needed
   - Fix common mistakes:
     - Windows: Use proper path format (e.g., %USERPROFILE%\Desktop not ~/Desktop)
     - Use correct commands for OS (dir on Windows, ls on Linux/Mac)
     - Escape special characters
   - Suggest safer alternatives if command is risky

3. **Execute with execute_terminal_command tool**
   - Use the tool with proper arguments
   - Set working_directory if needed
   - Capture both stdout and stderr

4. **Handle results**
   - If successful: Show output clearly
   - If failed with path error: Suggest correct path format
   - If failed with command not found: Suggest installing the tool
   - If failed with permission denied: Explain and suggest sudo/admin
   - For other errors: Explain in plain language

5. **Follow-up actions**
   - Offer to run related commands if needed
   - Save output to file if it's substantial
   - Log important results to memory if requested

## Rules

- ALWAYS ask for confirmation before destructive operations
- Never run commands with hardcoded secrets or passwords
- Explain what the command does before running it
- If command fails, DON'T just retry - diagnose the issue first
- For long-running commands (servers, watchers), warn the user
- Use appropriate shell for the OS (cmd on Windows, bash on Linux/Mac)
- If output is too long, offer to save to file instead of printing
- Never run commands that could harm the system (format, rm -rf /, etc.)
- For path errors, suggest using environment variables (%USERPROFILE%, $HOME, etc.)
- If user says "desktop" or "dekstop", use %USERPROFILE%\Desktop on Windows
