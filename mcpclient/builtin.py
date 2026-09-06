"""Built-in meta-tools exposed as a virtual server (defaults.META_SERVER).

Lets the MODEL itself search the registry, install, remove and list MCP
servers mid-session — no restart, no manual config editing. All names and
tunables come from mcpclient.defaults; state lives on the manager instance.
"""
from typing import Any

from mcpclient import config as mcp_config
from mcpclient import defaults
from mcpclient import registry


def _tool(name: str, description: str, props: dict, required: list) -> dict:
    return {
        "type": "function",
        "function": {
            "name": f"{defaults.META_SERVER}{defaults.SEP}{name}",
            "description": description,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


BUILTIN_TOOLS = [
    _tool("mcp_search",
          "Search the REGISTRY for installable MCP servers (candidates only — "
          "they are NOT connected). Pass a capability keyword (e.g. 'github', "
          "'filesystem', 'web fetch'), not the user's literal words. Check what is "
          "actually connected with mcp_list before claiming anything. Install with "
          "mcp_add using install_index.",
          {"query": {"type": "string", "description": "Capability keyword to search for"},
           "limit": {"type": "integer", "description": "Max results (default 5)"}}, ["query"]),
    _tool("mcp_add",
          "Install and connect an MCP server immediately. Provide install_index from "
          "a previous mcp_search result, or name+command for stdio, or "
          "name+url for remote. Explicit command/url args always win over "
          "install_index. Applies live, no restart. If the server ends up offline, "
          "report its error text verbatim instead of claiming success.",
          {"install_index": {"type": "integer", "description": "1-based index of a previous mcp_search result"},
           "name": {"type": "string", "description": "Short server name (used as tool prefix)"},
           "command": {"type": "string", "description": "Executable for stdio servers (e.g. npx, python)"},
           "args": {"type": "array", "items": {"type": "string"}, "description": "Args after the command"},
           "url": {"type": "string", "description": "URL for remote (http) servers"}}, []),
    _tool("mcp_remove", "Remove and disconnect a registered MCP server by name.",
          {"name": {"type": "string"}}, ["name"]),
    _tool("mcp_list", "List CONFIGURED MCP servers with live status and their tools. "
          "This is the ONLY source of truth for what is connected — never claim a "
          "server is connected/installed based on search results or memory. Call it "
          "before answering any 'what servers / are you connected' question.", {}, []),
    _tool("shell_run",
          "Run an UNRESTRICTED shell command (Windows PowerShell ONLY) in a PERSISTENT "
          "session — cwd, env vars and files carry over between calls, so chain "
          "state (cd, $env:X=...) instead of re-stating it. No approval needed; "
          "every command is audit-logged. Prefer one chained command over many "
          "small ones. Interactive commands (needing stdin) are NOT supported. "
          "PowerShell syntax REQUIRED: Get-ChildItem (not ls), Get-Content (not cat), "
          "Get-Location (not pwd), Select-String (not grep). Never use bash flags "
          "like -la/-rf. Examples: Get-ChildItem; Get-Content .\\soul.py.",
          {"command": {"type": "string", "description": "PowerShell command to run (e.g. Get-ChildItem, NOT ls -la)"},
           "timeout_s": {"type": "number", "description": "Timeout in seconds (default 60)"},
           "cwd": {"type": "string", "description": "Working directory (persists for later calls)"},
           "run_in_background": {"type": "boolean", "description": "Return immediately with a job id; poll via shell_jobs"}}, ["command"]),
    _tool("shell_jobs", "List background shell jobs started with run_in_background, with status.",
          {}, []),
    _tool("shell_kill", "Stop a background shell job by id (see shell_jobs).",
          {"job_id": {"type": "string"}}, ["job_id"]),
]


def visible_tools() -> list:
    """BUILTIN_TOOLS minus shell tools when ZUMBA_NO_SHELL=1."""
    try:
        import shelltool

        if shelltool.enabled():
            return BUILTIN_TOOLS
    except Exception:
        pass
    return [t for t in BUILTIN_TOOLS if not str(t.get("function", {}).get("name", "")).endswith(
        ("__shell_run", "__shell_jobs", "__shell_kill"))]

# (search results live in mgr.meta_state["last_search"] — per-instance, no globals)


async def handle(mgr: Any, tool: str, arguments: dict) -> str:
    """Execute a META_SERVER meta-tool (async). Returns plain text for the model."""
    args = arguments or {}
    if tool == "mcp_search":
        query = str(args.get("query", "")).strip()
        if not query:
            return "ERROR: 'query' is required."
        results = registry.search(query, limit=int(args.get("limit", defaults.SEARCH_LIMIT) or defaults.SEARCH_LIMIT))
        mgr.meta_state["last_search"] = results
        if not results:
            return f"No MCP servers found in the registry for '{query}'."
        lines = [f"Found {len(results)} server(s) in the registry (use install_index with {defaults.META_SERVER}{defaults.SEP}mcp_add to install):"]
        for i, r in enumerate(results, 1):
            inst = r["install"]
            kind = "remote http" if inst.get("url") else f"stdio: {inst.get('command')} {' '.join(inst.get('args', []))[:80]}"
            key = " (needs API key header)" if inst.get("_needs_key") else ""
            lines.append(f"[{i}] {r['name']} v{r['version']} — {r['description']}\n    install: {kind}{key}\n    id: {r['full_name']}")
        return "\n".join(lines)

    if tool == "mcp_add":
        name = str(args.get("name", "") or "").strip()
        entry = None
        if args.get("url"):
            entry = {"transport": "http", "url": str(args["url"])}
        elif args.get("command"):
            entry = {"command": str(args["command"]), "args": [str(a) for a in (args.get("args") or [])]}
        elif args.get("install_index") is not None:
            idx = args.get("install_index")
            try:
                r = mgr.meta_state["last_search"][int(idx) - 1]
            except (ValueError, IndexError, KeyError):
                return "ERROR: install_index out of range — run zumba__mcp_search first."
            entry = dict(r["install"])
            entry.pop("_needs_key", None)
            name = name or r["name"]
        if not entry or not name:
            return "ERROR: provide install_index (from mcp_search), or name+command, or name+url."
        if name == defaults.META_SERVER:
            return f"ERROR: '{defaults.META_SERVER}' is reserved for built-in tools."
        mcp_config.add_server(name, entry)
        summary = await _areload(mgr)
        st = mgr.servers.get(name)
        status = st.status if st else "unknown"
        err = (st.error or "") if st else ""
        tools = [t["function"]["name"] for t in mgr.all_tools() if t["function"]["name"].startswith(name + "__")]
        if status != "online":
            return (f"Installed '{name}' ({summary}). Status: {status}"
                    f"{(': ' + err) if err else ''}. "
                    f"NOT usable yet — tell the user it failed to start (e.g. bad npx "
                    f"package, missing binary, network) and suggest checking the entry "
                    f"or running /mcp reload to retry. Do NOT claim its tools work.")
        return (f"Installed '{name}' ({summary}). Status: {status}. "
                f"Now available: {', '.join(tools) if tools else '(no tools listed)'}.")

    if tool == "mcp_remove":
        name = str(args.get("name", "") or "").strip()
        if not name:
            return "ERROR: 'name' is required."
        if not mcp_config.remove_server(name):
            return f"ERROR: server '{name}' not found in the registry."
        summary = await _areload(mgr)
        return f"Removed '{name}' ({summary})."

    if tool == "mcp_list":
        rows = mgr.status_rows()
        if not rows:
            return "No MCP servers configured. Use zumba__mcp_search to find one."
        lines = [f"{r['name']}: {r['status']} ({r['transport']}) — {r['tool_count']} tool(s) {r['tools'] or ''}" for r in rows]
        return "\n".join(lines)

    if tool in ("shell_run", "shell_jobs", "shell_kill"):
        import asyncio as _asyncio
        import shelltool as _shell

        if not _shell.enabled():
            return "ERROR: shell tool is disabled (ZUMBA_NO_SHELL=1)."
        if tool == "shell_jobs":
            jobs = _shell.get_session().job_list()
            if not jobs:
                return "No background shell jobs."
            lines = []
            for j in jobs:
                state = "running" if j["running"] else "done exit=%s" % (j["exit_code"],)
                lines.append("[%s] %s (%ss) :: %s" % (j["job_id"], state, j["elapsed_s"], j["command"]))
            return "\n".join(lines)
        if tool == "shell_kill":
            job_id = str(args.get("job_id", "") or "").strip()
            if not job_id:
                return "ERROR: 'job_id' is required."
            return _shell.get_session().job_kill(job_id)
        command = str(args.get("command", "") or "")
        if not command.strip():
            return "ERROR: 'command' is required."
        try:
            timeout_s = float(args.get("timeout_s") or 0) or 0
        except Exception:
            return "ERROR: 'timeout_s' must be a number."
        res = await _asyncio.to_thread(
            _shell.run, command,
            timeout_s=timeout_s, cwd=(str(args.get("cwd") or "") or None),
            run_in_background=bool(args.get("run_in_background", False)))
        if res.get("job_id"):
            return str(res.get("stdout", ""))
        return _shell.format_result(res, cwd=_shell.get_session().cwd)

    return f"ERROR: unknown meta-tool '{tool}'."


async def _areload(mgr: Any) -> str:
    summary = await mgr.reload()
    parts = [f"{k}: {','.join(v) if isinstance(v, list) else v}" for k, v in summary.items() if v]
    return "; ".join(parts) or "no changes"
