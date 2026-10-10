# Startup timings

Board idea: per-plugin and per-skill startup profiler.

The real skill parser and MCP handshake record milliseconds, including failed
loads. The interactive terminal prints a boot breakdown; desktop Plugins → Skills
shows the same live report, with a refresh button for background connections.
Each entry points to the existing MCP disable command or skill disable control.
Repeated skill cache hits retain the original measurements; reloads replace them.
Reports contain names, duration and status, not connection arguments or errors.

Verification includes successful and malformed on-disk skills, a real local HTTP
MCP handshake, a failed process launch, bounded records and the desktop engine
adapter. Cold remote package download timing varies with network conditions;
the profiler records it rather than promising a fixed startup duration.

Evidence: the focused profiler/skill/plugin checks passed 18/18; the live HTTP
handshake and failed launch both returned measured status. `npm run desktop:build`
passed. The real Vite desktop renderer in Chromium, with a fixture IPC transport
calling the real engine, returned:
`STARTUP_PROFILE_UI_LIVE report=true refresh=true existingDisable=true rendererErrors=0 transport=fixture engine=real`.
The packaged Electron binary is not exercised by this renderer check.
