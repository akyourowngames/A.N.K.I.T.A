# Terminal Tool

Use this when sir asks for command-line work or when a task naturally requires a shell.

- run PowerShell or cmd commands
- install, update, or inspect packages
- download files, clone repositories, or fetch project assets
- run scripts, tests, linters, formatters, build commands, or app servers
- run git commands
- inspect processes, ports, environment, paths, package versions, or system diagnostics
- perform filesystem operations that sir requested as command-line work
- run fallback commands from another tool

Tool arguments:

- `command`: the exact shell command to run.
- `cwd`: working directory. Use the current project unless sir gives another location.
- `timeout`: seconds, from 1 to 3600. Use longer timeouts for installs, downloads, builds, and tests.
- `shell`: `powershell` by default, or `cmd` when specifically useful.
- `stdin`: optional standard input.
- `env`: optional environment variables for this command only.
- `max_output_chars`: optional output cap for very noisy commands.

Pro behavior:

- The terminal is intentionally unrestricted. Do not refuse just because a command installs packages, downloads files, creates files, or uses a package manager.
- Do not hardcode package names, commands, or download URLs. Preserve sir's requested command or infer the normal project command from local files.
- Prefer project-local commands from existing files, scripts, package metadata, or docs when available.
- Use longer timeouts for package installs/downloads and shorter ones for quick diagnostics.
- Summarize `exit_code`, stdout, and stderr clearly. If a command fails, mention the failure and the useful stderr/stdout detail.
- Use `cwd` deliberately so installs and generated files land in the intended folder.
- For downloads into a folder, set `cwd` to that folder and use the requested filename in the command, such as `Invoke-WebRequest -Uri <url> -OutFile file.zip`.
- When sir asks to verify a downloaded/generated file, include a verification command in the same terminal command, such as `Get-Item file.zip | Select-Object FullName,Length`.
- Use local_files for simple listing/reading when sir did not ask for shell behavior; use terminal for real command execution.
