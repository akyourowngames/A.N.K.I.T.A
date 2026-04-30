# Terminal Tool

Use this when sir explicitly asks to run:

- terminal commands
- PowerShell commands
- git commands
- installs
- process inspection
- filesystem commands
- diagnostics
- fallback commands from another tool

Behavior:

- Execute exactly what sir asks.
- Use the current project directory unless sir gives another location.
- Summarize stdout/stderr and exit code clearly.
- If another tool fails and provides a fallback command, run it through terminal.
- Keep command output readable and compact.
