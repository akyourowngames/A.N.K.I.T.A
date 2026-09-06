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
    _tool("web_search",
          "Realtime web search (zero-API-key: DuckDuckGo + Wikipedia + HN). Use for ANY time-sensitive, "
          "current-events, or 'latest' question instead of guessing. Returns [i] title — source / snippet / URL. "
          "Call web_fetch on the top URL for depth.",
          {"query": {"type": "string", "description": "Search query"},
           "backend": {"type": "string", "description": "auto (default), web, wikipedia, hn, reddit"},
           "when": {"type": "string", "description": "Freshness: 1h, 1d, 7d, 30d, 1y (empty = any time)"},
           "limit": {"type": "integer", "description": "Max results (default 8)"}}, ["query"]),
    _tool("web_news",
          "Realtime news via Google News RSS (zero-API-key). Use for 'what happened today / latest news' questions. "
          "Supports query operators (when:1d, site:, after:, before:).",
          {"query": {"type": "string", "description": "News query"},
           "when": {"type": "string", "description": "Recency window, default 1d"},
           "limit": {"type": "integer", "description": "Max items (default 8)"}}, ["query"]),
    _tool("web_fetch",
          "Download a URL and extract readable text (zero-API-key page reader, Jina fallback). "
          "Use after web_search/web_news to read the best result in full.",
          {"url": {"type": "string", "description": "http(s) URL to read"},
           "max_chars": {"type": "integer", "description": "Max chars (default 8000)"}}, ["url"]),
    _tool("vault_search",
          "Search the local document vault (user files: contracts, leases, emails, PDFs). "
          "Use for 'what does my doc say / find the email / summarize the contract' questions. "
          "Returns ranked hits with exact quotes and [Title p.N] citations.",
          {"query": {"type": "string", "description": "Question about the documents"},
           "doc_filter": {"type": "string", "description": "Optional title substring to restrict to one doc"},
           "k": {"type": "integer", "description": "Max hits (default 6)"}}, ["query"]),
    _tool("vault_doc",
          "Show a vault document's outline + summary (drill-in before reading).",
          {"doc": {"type": "string", "description": "Doc id or title substring"}}, ["doc"]),
    _tool("vault_read",
          "Read one full vault section ('turn the page').",
          {"doc": {"type": "string", "description": "Doc id or title substring"},
           "section": {"type": "string", "description": "Section heading substring"}}, ["doc", "section"]),
    _tool("goal_add",
          "Create a proactive goal (auto-decomposed into steps with micro-deadlines). "
          "Use when the user states an intent like 'I want to pass IELTS by December'.",
          {"title": {"type": "string", "description": "Goal title"},
           "deadline": {"type": "string", "description": "Deadline YYYY-MM-DD (optional)"},
           "priority": {"type": "integer", "description": "1 (critical) to 5 (whenever), default 3"}}, ["title"]),
    _tool("goal_complete_step",
          "Mark a goal step done by step id (see goal_show for ids). Progress recomputes.",
          {"step_id": {"type": "integer", "description": "goal_steps id"}}, ["step_id"]),
    _tool("goal_show",
          "Show a goal: steps, research, reminders, timeline.",
          {"goal_id": {"type": "integer", "description": "Goal id"}}, ["goal_id"]),
    _tool("remind_add",
          "Schedule a reminder in natural time ('tomorrow 9am', 'in 3 days', 'friday 5pm').",
          {"message": {"type": "string", "description": "Reminder text"},
           "when": {"type": "string", "description": "Natural time expression"},
           "goal_id": {"type": "integer", "description": "Optional goal id to attach"}}, ["message", "when"]),
]


def visible_tools() -> list:
    """BUILTIN_TOOLS minus shell tools when ZUMBA_NO_SHELL=1, minus web tools when ZUMBA_NO_WEB=1."""
    tools = list(BUILTIN_TOOLS)
    try:
        from tools import shelltool

        if not shelltool.enabled():
            raise RuntimeError("shell disabled")
    except Exception:
        tools = [t for t in tools if not str(t.get("function", {}).get("name", "")).endswith(
            ("__shell_run", "__shell_jobs", "__shell_kill"))]
    try:
        from tools import websearch as _web

        if not _web.enabled():
            raise RuntimeError("web disabled")
    except Exception:
        tools = [t for t in tools if not str(t.get("function", {}).get("name", "")).endswith(
            ("__web_search", "__web_news", "__web_fetch"))]
    try:
        from vault import service as _vault

        if not _vault.enabled():
            raise RuntimeError("vault disabled")
    except Exception:
        tools = [t for t in tools if not str(t.get("function", {}).get("name", "")).endswith(
            ("__vault_search", "__vault_doc", "__vault_read"))]
    return tools

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
        from tools import shelltool as _shell

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

    if tool in ("web_search", "web_news", "web_fetch"):
        import asyncio as _asyncio2
        from tools import websearch as _web

        if not _web.enabled():
            return "ERROR: web tools are disabled (ZUMBA_NO_WEB=1)."
        if tool == "web_search":
            query = str(args.get("query", "") or "").strip()
            if not query:
                return "ERROR: 'query' is required."
            try:
                limit = int(args.get("limit", 8) or 8)
            except Exception:
                return "ERROR: 'limit' must be a number."
            res, note = await _asyncio2.to_thread(
                _web.search, query, str(args.get("backend", "auto") or "auto"),
                str(args.get("when", "") or ""), limit)
            return _web.format_search(res, note)
        if tool == "web_news":
            query = str(args.get("query", "") or "").strip()
            if not query:
                return "ERROR: 'query' is required."
            try:
                limit = int(args.get("limit", 8) or 8)
            except Exception:
                return "ERROR: 'limit' must be a number."
            res, note = await _asyncio2.to_thread(
                _web.news, query, str(args.get("when", "1d") or "1d"), limit)
            return _web.format_news(res, note)
        url = str(args.get("url", "") or "").strip()
        if not url:
            return "ERROR: 'url' is required."
        try:
            mc = int(args.get("max_chars", 0) or 0)
        except Exception:
            return "ERROR: 'max_chars' must be a number."
        text, err = await _asyncio2.to_thread(_web.fetch, url, mc)
        return text if text else (err or "ERROR: fetch failed.")

    if tool in ("vault_search", "vault_doc", "vault_read"):
        import asyncio as _asyncio3
        from vault import service as _vault

        if not _vault.enabled():
            return "ERROR: vault is disabled (ZUMBA_NO_VAULT=1)."
        v = _vault.get_vault()
        if tool == "vault_search":
            query = str(args.get("query", "") or "").strip()
            if not query:
                return "ERROR: 'query' is required."
            try:
                k = int(args.get("k", 6) or 6)
            except Exception:
                return "ERROR: 'k' must be a number."
            hits = await _asyncio3.to_thread(v.find, query, k, str(args.get("doc_filter", "") or ""))
            if not hits:
                return "ERROR: nothing in the vault answers that yet."
            lines = []
            for i, h in enumerate(hits, 1):
                m = h.get("meta", {})
                lines.append(f"[{i}] {m.get('citation', m.get('doc', ''))} :: {(h.get('text', '') or '')[:600]}")
            return "\n".join(lines)
        if tool == "vault_doc":
            doc = str(args.get("doc", "") or "").strip()
            if not doc:
                return "ERROR: 'doc' is required."
            return await _asyncio3.to_thread(v.doc, doc)
        doc = str(args.get("doc", "") or "").strip()
        section = str(args.get("section", "") or "").strip()
        if not doc or not section:
            return "ERROR: 'doc' and 'section' are required."
        return await _asyncio3.to_thread(v.read_section, doc, section)

    if tool in ("goal_add", "goal_complete_step", "goal_show", "remind_add"):
        import asyncio as _asyncio4
        from memory import db as _mdb
        from memory import goals as _goals
        from memory import reminders as _rem

        def _open():
            con = _mdb.connect()
            _mdb.ensure_tier3(con)
            return con

        if tool == "goal_add":
            title = str(args.get("title", "") or "").strip()
            if not title:
                return "ERROR: 'title' is required."
            dl = 0.0
            if str(args.get("deadline", "") or "").strip():
                try:
                    import datetime as _dt
                    dl = _dt.datetime.strptime(str(args["deadline"]).strip()[:10], "%Y-%m-%d").timestamp()
                except Exception:
                    return "ERROR: 'deadline' must be YYYY-MM-DD."
            try:
                pri = int(args.get("priority", 3) or 3)
            except Exception:
                return "ERROR: 'priority' must be a number 1-5."
            con = _open()
            try:
                r = await _asyncio4.to_thread(_goals.create_goal, con, title, "", dl or None, pri)
                if not r.get("created"):
                    return f"ERROR: {r.get('reason', 'not created')}."
                return await _asyncio4.to_thread(_goals.render_show, con, r["id"])
            finally:
                try:
                    con.close()
                except Exception:
                    pass
        if tool == "goal_complete_step":
            try:
                sid = int(args.get("step_id", 0) or 0)
            except Exception:
                return "ERROR: 'step_id' must be a number."
            con = _open()
            try:
                r = await _asyncio4.to_thread(_goals.complete_step, con, sid)
                if not r.get("done"):
                    return f"ERROR: {r.get('reason', 'not done')}."
                return f"Step done. Goal #{r.get('goal_id')} now {int(r.get('progress', 0)*100)}%."
            finally:
                try:
                    con.close()
                except Exception:
                    pass
        if tool == "goal_show":
            try:
                gid = int(args.get("goal_id", 0) or 0)
            except Exception:
                return "ERROR: 'goal_id' must be a number."
            con = _open()
            try:
                return await _asyncio4.to_thread(_goals.render_show, con, gid)
            finally:
                try:
                    con.close()
                except Exception:
                    pass
        message = str(args.get("message", "") or "").strip()
        when = str(args.get("when", "") or "").strip()
        if not message or not when:
            return "ERROR: 'message' and 'when' are required."
        try:
            gid = int(args.get("goal_id", 0) or 0) or None
        except Exception:
            gid = None
        con = _open()
        try:
            r = await _asyncio4.to_thread(_rem.schedule, con, message, when, gid)
            if not r.get("scheduled"):
                return f"ERROR: {r.get('reason', 'not scheduled')}."
            import datetime as _dt
            ft = _dt.datetime.fromtimestamp(float(r["fire_at"])).strftime("%m-%d %H:%M")
            return f"Reminder #{r['id']} set for {ft}: {message[:150]}"
        finally:
            try:
                con.close()
            except Exception:
                pass

    return f"ERROR: unknown meta-tool '{tool}'."


async def _areload(mgr: Any) -> str:
    summary = await mgr.reload()
    parts = [f"{k}: {','.join(v) if isinstance(v, list) else v}" for k, v in summary.items() if v]
    return "; ".join(parts) or "no changes"
