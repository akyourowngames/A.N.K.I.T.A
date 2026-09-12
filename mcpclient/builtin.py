"""Built-in meta-tools exposed as a virtual server (defaults.META_SERVER).

Lets the MODEL itself search the registry, install, remove and list MCP
servers mid-session — no restart, no manual config editing. All names and
tunables come from mcpclient.defaults; state lives on the manager instance.
"""
from typing import Any
import os

from mcpclient import config as mcp_config
from mcpclient import defaults
from mcpclient import registry

# Author-declared capabilities, keyed by exact tool identity, not language cues.
# Unknown/new tools require approval until their capability is explicitly declared.
TOOL_ACCESS = {
    'mcp_search': 'read', 'mcp_list': 'read', 'shell_jobs': 'read',
    'web_search': 'read', 'web_news': 'read', 'web_fetch': 'read',
    'scrape_low': 'read', 'scrape_mid': 'read', 'scrape_high': 'read',
    'fs_read': 'read', 'fs_grep': 'read', 'fs_find': 'read', 'fs_list': 'read',
    'fs_info': 'read', 'fs_glob': 'read', 'fs_tree': 'read',
    'fs_write': 'local', 'fs_edit': 'local', 'fs_insert': 'local',
    'fs_replace_lines': 'local', 'fs_apply_patch': 'local', 'fs_batch': 'local',
    'fs_undo': 'local', 'fs_mkdir': 'local', 'fs_move': 'local', 'fs_delete': 'local',
    'vault_search': 'read', 'vault_doc': 'read', 'vault_read': 'read',
    'goal_show': 'read', 'goal_list': 'read', 'memory_search': 'read',
    'brief': 'read', 'soul_show': 'read', 'soul_diff': 'read', 'me_show': 'read',
    'vault_ask': 'read', 'vault_status': 'read', 'geo_geocode': 'read',
    'geo_reverse': 'read', 'geo_route': 'read', 'geo_traffic': 'read',
    'geo_nearby': 'read', 'geo_weather': 'read', 'geo_maps_link': 'read',
    'geo_whereami': 'read', 'task_list': 'read',
    'calendar_today': 'read', 'calendar_search': 'read', 'calendar_brief': 'read',
    'calendar_status': 'read',
    'goal_add': 'local', 'goal_complete_step': 'local', 'remind_add': 'local',
    'memory_remember': 'local', 'soul_propose': 'local', 'task_update': 'local',
    'calendar_create': 'local',
}

# These capabilities share mutable session state even when a call is a read.
TOOL_GROUP = {'mcp_search': 'registry', 'mcp_add': 'registry',
              'mcp_remove': 'registry', 'mcp_list': 'registry',
              'shell_run': 'shell', 'shell_jobs': 'shell', 'shell_kill': 'shell',
              'fs_write': 'fs', 'fs_edit': 'fs', 'fs_insert': 'fs',
              'fs_replace_lines': 'fs', 'fs_apply_patch': 'fs', 'fs_batch': 'fs',
              'fs_undo': 'fs', 'fs_mkdir': 'fs', 'fs_move': 'fs', 'fs_delete': 'fs'}


def _graph_profile() -> str:
    """Profile straight from the knowledge graph (user_facts table).

    user.md is deleted by design; this is what me_show returns so the agent
    never concludes "no profile" from a missing file.
    """
    try:
        from memory import db as _db
        con = _db.connect()
        try:
            rows = con.execute(
                "SELECT key, value FROM user_facts ORDER BY updated_at DESC LIMIT 40"
            ).fetchall()
        finally:
            con.close()
    except Exception as exc:
        return f"ERROR: profile unavailable ({str(exc)[:150]})."
    if not rows:
        return "(no profile facts stored yet — durable facts land here as chat is consolidated)"
    return "[graph profile — durable user facts]\n" + "\n".join(
        f"- {r['key']}: {r['value']}" for r in rows)


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
          "state (cd, $env:X=...) instead of re-stating it. Follow channel approval controls; "
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
          "Use after web_search/web_news to read the best result in full. "
          "This is GENERAL reading — NOT scraping. When the user asks to 'scrape', "
          "use scrape_low / scrape_mid / scrape_high instead.",
          {"url": {"type": "string", "description": "http(s) URL to read"},
           "max_chars": {"type": "integer", "description": "Max chars (default 8000)"}}, ["url"]),
    _tool("scrape_low",
          "SCRAPE tier LOW: fast single-page scrape (Scrapling static Fetcher with "
          "browser impersonation, no headless browser). Use when the user asks to scrape "
          "one simple page. Returns readable markdown/text. If blocked or JS-heavy, "
          "escalate to scrape_mid.",
          {"url": {"type": "string", "description": "http(s) URL to scrape"},
           "format": {"type": "string", "description": "markdown (default), text, or json"},
           "max_chars": {"type": "integer", "description": "Max chars (default 8000)"}}, ["url"]),
    _tool("scrape_mid",
          "SCRAPE tier MID: single-page scrape with auto stealth fallback "
          "(static Fetcher first, StealthyFetcher with Cloudflare solver on 403/429/503 "
          "or thin pages). Use when the user asks to scrape a blocked/JS page or needs "
          "named fields. selectors: field->CSS map (or 'xpath:...'), e.g. "
          "{'title': 'h1::text', 'price': '.price::text'}. mode: auto (default), static, stealth.",
          {"url": {"type": "string", "description": "http(s) URL to scrape"},
           "selectors": {"type": "string", "description": "JSON object or 'k=css, k2=css' field map (optional)"},
           "format": {"type": "string", "description": "markdown (default), text, or json"},
           "mode": {"type": "string", "description": "auto (default), static, stealth"},
           "wait_selector": {"type": "string", "description": "CSS selector stealth should wait for (optional)"},
           "max_chars": {"type": "integer", "description": "Max chars (default 8000)"}}, ["url"]),
    _tool("scrape_high",
          "SCRAPE tier HIGH: multi-page crawl (BFS, depth 0-2, up to 20 pages, "
          "same-domain default, shared stealth session for blocked pages). Use ONLY when "
          "the user asks to scrape/crawl multiple pages, a whole section, or a listing. "
          "Prefer scrape_low/scrape_mid for single pages.",
          {"urls": {"type": "string", "description": "Seed URL(s), comma/space separated"},
           "depth": {"type": "integer", "description": "Link-follow depth 0-2 (default 1)"},
           "limit": {"type": "integer", "description": "Max pages (default 8, cap 20)"},
           "same_domain": {"type": "boolean", "description": "Stay on seed domain (default true)"},
           "selectors": {"type": "string", "description": "JSON object or 'k=css' field map applied per page (optional)"},
           "mode": {"type": "string", "description": "auto (default), static, stealth"}}, ["urls"]),
    _tool("fs_read",
          "Read a local text file with line numbers + nearby import/scope context. "
          "Use instead of shell (Get-Content/cat) for ALL file reading.",
          {"path": {"type": "string", "description": "File path"},
           "start_line": {"type": "integer", "description": "First line (default 1)"},
           "num_lines": {"type": "integer", "description": "Max lines (default 200)"}}, ["path"]),
    _tool("fs_grep",
          "Search file CONTENTS for a pattern (ripgrep-fast, Python fallback). "
          "Use instead of shell grep/Select-String. Returns path:line:excerpt.",
          {"pattern": {"type": "string", "description": "Regex/text to find"},
           "path": {"type": "string", "description": "Directory or file (default .)"},
           "glob": {"type": "string", "description": "File glob like *.py (optional)"},
           "context": {"type": "integer", "description": "Context lines (default 0)"},
           "case_sensitive": {"type": "boolean", "description": "Case-sensitive (default false)"},
           "max_results": {"type": "integer", "description": "Max hits (default 100)"}}, ["pattern"]),
    _tool("fs_find",
          "Instantly locate files by NAME anywhere (rg --files + fuzzy rank). "
          "Use instead of shell Get-ChildItem -Recurse / find for filename lookup.",
          {"name": {"type": "string", "description": "Filename or fragment"},
           "path": {"type": "string", "description": "Root to search from (default .)"},
           "max_results": {"type": "integer", "description": "Max paths (default 50)"}}, ["name"]),
    _tool("fs_list",
          "List a directory with sizes. Use instead of shell ls/Get-ChildItem.",
          {"path": {"type": "string", "description": "Directory (default .)"},
           "max_items": {"type": "integer", "description": "Max items (default 30)"},
           "sort": {"type": "string", "description": "name (default), mtime, size"}}, []),
    _tool("fs_info",
          "File metadata: type, size, timestamps, binary/symlink status.",
          {"path": {"type": "string", "description": "File or directory"}}, ["path"]),
    _tool("fs_glob",
          "Find files by glob pattern (e.g. **/*.py). Ignore-aware.",
          {"pattern": {"type": "string", "description": "Glob pattern"},
           "path": {"type": "string", "description": "Root (default .)"},
           "max_results": {"type": "integer", "description": "Max files (default 50)"}}, ["pattern"]),
    _tool("fs_tree",
          "Directory tree view (like tree). Depth-capped.",
          {"path": {"type": "string", "description": "Root (default .)"},
           "max_depth": {"type": "integer", "description": "Depth 1-10 (default 3)"}}, []),
    _tool("fs_write",
          "Create or FULLY OVERWRITE a file (atomic, auto-backup, diff in result, audit-logged). "
          "For targeted changes use fs_edit/fs_insert/fs_replace_lines instead.",
          {"path": {"type": "string", "description": "File path"},
           "content": {"type": "string", "description": "Full file content"},
           "dry_run": {"type": "boolean", "description": "Preview diff without writing"}}, ["path", "content"]),
    _tool("fs_edit",
          "Targeted edit: replace uniquely-matching old_text with new_text "
          "(exact -> occurrence -> whitespace-normalized -> did-you-mean). Auto-backup + diff. "
          "Use instead of shell sed/AWK for file edits.",
          {"path": {"type": "string", "description": "File path"},
           "old_text": {"type": "string", "description": "Text to find (must be unique unless occurrence given)"},
           "new_text": {"type": "string", "description": "Replacement"},
           "occurrence": {"type": "integer", "description": "Which match 1..N when repeated (default 0 = require unique)"},
           "dry_run": {"type": "boolean", "description": "Preview diff without writing"}}, ["path", "old_text", "new_text"]),
    _tool("fs_insert",
          "Insert text before/after a 1-based line number. Auto-backup + diff.",
          {"path": {"type": "string", "description": "File path"},
           "line": {"type": "integer", "description": "1-based line number"},
           "text": {"type": "string", "description": "Text to insert"},
           "position": {"type": "string", "description": "before or after (default after)"},
           "dry_run": {"type": "boolean", "description": "Preview without writing"}}, ["path", "line", "text"]),
    _tool("fs_replace_lines",
          "Inline edit: replace inclusive 1-based line range with new text. Auto-backup + diff.",
          {"path": {"type": "string", "description": "File path"},
           "start": {"type": "integer", "description": "First line"},
           "end": {"type": "integer", "description": "Last line (inclusive)"},
           "new_text": {"type": "string", "description": "Replacement text"},
           "dry_run": {"type": "boolean", "description": "Preview without writing"}}, ["path", "start", "end", "new_text"]),
    _tool("fs_apply_patch",
          "Multi-file atomic patch (V4A context-anchored diffs: *** Add/Update/Delete File, "
          "@@ anchors, -/+ lines). Validates ALL files in memory first; nothing touches disk "
          "unless everything applies. Use for refactors across files.",
          {"patch": {"type": "string", "description": "V4A patch text"},
           "dry_run": {"type": "boolean", "description": "Validate only, show diffs"}}, ["patch"]),
    _tool("fs_batch",
          "Transactional multi-operation edit (write/edit/insert/replace_lines/delete/move/mkdir). "
          "Rolls back ALL files if any operation fails.",
          {"operations": {"type": "array", "items": {"type": "object"},
                          "description": "List of {action, path, ...} ops"},
           "dry_run": {"type": "boolean", "description": "Validate without changing files"}}, ["operations"]),
    _tool("fs_undo",
          "Restore a file from its newest auto-backup.",
          {"path": {"type": "string", "description": "File path"},
           "dry_run": {"type": "boolean", "description": "Preview restore diff"}}, ["path"]),
    _tool("fs_mkdir",
          "Create a directory with parents (mkdir -p).",
          {"path": {"type": "string", "description": "Directory path"}}, ["path"]),
    _tool("fs_move",
          "Move/rename a file or directory (creates destination parents).",
          {"source": {"type": "string", "description": "Current path"},
           "destination": {"type": "string", "description": "New path"}}, ["source", "destination"]),
    _tool("fs_delete",
          "Delete a file or EMPTY directory. Requires confirm=true.",
          {"path": {"type": "string", "description": "Path to delete"},
           "confirm": {"type": "boolean", "description": "Must be true"}}, ["path"]),
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
    _tool("goal_list",
          "List goals with progress bars and next steps. Filter by status: active (default), all, done.",
          {"status": {"type": "string", "description": "active, all, or done"}}, []),
    _tool('task_list', 'List retained tasks with IDs, expiry and attention state. Dormant or expired tasks are history, not instructions. Use to find a task the user wants to dismiss or explicitly resume.', {}, []),
    _tool('task_update', 'Dismiss an unfinished task without deleting its history, or explicitly reactivate it ONLY when the current user asks to resume it. Reactivation requires a future until epoch; expired time-bound plans require a new expires_at. Never renew a task merely because it was recalled.',
          {'kind': {'type': 'string', 'enum': ['goal', 'follow_up']},
           'id': {'type': 'integer'}, 'action': {'type': 'string', 'enum': ['dismiss', 'reactivate']},
           'until': {'type': 'number', 'description': 'Future epoch at which unsolicited attention stops'},
           'expires_at': {'type': 'number', 'description': 'New future epoch when this action ceases to be useful'}}, ['kind', 'id', 'action']),
    _tool("memory_remember",
          "Store a fact in long-term memory (goes through the full salience/extraction pipeline). "
          "Use when the user says 'remember ...' or shares a durable fact/preference.",
          {"text": {"type": "string", "description": "Fact to remember"}}, ["text"]),
    _tool("memory_search",
          "Search long-term memory (hybrid vector + BM25 + graph recall). "
          "Use before answering 'what do you remember about ...' questions.",
          {"query": {"type": "string", "description": "Memory query"},
           "top_k": {"type": "integer", "description": "Max hits (default 8)"}}, ["query"]),
    _tool("memory_forget",
          "Invalidate facts about an entity (bi-temporal invalidate, history kept).",
          {"name": {"type": "string", "description": "Entity name to forget"}}, ["name"]),
    _tool("brief",
          "Daily briefing from memory: follow-ups, deadlines, on-this-day resurfaces.",
          {}, []),
    _tool("soul_show",
          "Show Zumba's self-authored identity file (soul.md: voice/values/boundaries).",
          {}, []),
    _tool("soul_propose",
          "Draft a FULL rewritten soul.md and save it as a proposal (soul.proposed.md). "
          "Read the current file with soul_show first, keep frontmatter + Identity/Voice/Values/Boundaries structure, "
          "stay under ~4000 chars. Then show soul_diff and ASK the user to confirm before calling soul_accept. "
          "Never call soul_accept without explicit user confirmation.",
          {"content": {"type": "string", "description": "Full new soul.md content"}}, ["content"]),
    _tool("soul_diff",
          "Show the unified diff between soul.md and the pending proposal.",
          {}, []),
    _tool("soul_accept",
          "Apply the pending soul proposal (only after the user explicitly confirmed).",
          {}, []),
    _tool("soul_reject",
          "Discard the pending soul proposal.",
          {}, []),
    _tool("me_show",
          "Show the user's graph-backed profile (durable facts: identity, contact, prefs). Secondary to the Relevant memory block already in context.",
          {}, []),
    _tool("vault_ask",
          "Answer from local documents with [Title p.N] citations. "
          "Use for 'what does my doc/lease/contract say' questions.",
          {"question": {"type": "string", "description": "Question about the documents"},
           "k": {"type": "integer", "description": "Max hits (default 6)"}}, ["question"]),
    _tool("vault_status",
          "Vault health: docs, chunks, index state, watched paths.",
          {}, []),
    _tool("geo_geocode", "Fuzzy place name to lat/lon candidates (top 3). Use for 'how far is X', 'cafes near Y'.",
          {"place": {"type": "string"}}, ["place"]),
    _tool("geo_reverse", "Lat/lon to human-readable address.",
          {"lat": {"type": "number"}, "lon": {"type": "number"}}, ["lat", "lon"]),
    _tool("geo_route", "Origin to destination distance/duration/steps. Origin/dest accept 'lat,lon' or place names. mode=drive|walk|bike.",
          {"origin": {"type": "string"}, "destination": {"type": "string"}, "mode": {"type": "string"}}, ["origin", "destination"]),
    _tool("geo_traffic", "Live traffic delta vs free-flow (needs ZUMBA_TT_KEY, else honest no-data).",
          {"origin": {"type": "string"}, "destination": {"type": "string"}}, ["origin", "destination"]),
    _tool("geo_nearby", "POIs near lat/lon. Category is free text (e.g. 'cafes', 'parking').",
          {"lat": {"type": "number"}, "lon": {"type": "number"}, "category": {"type": "string"}, "limit": {"type": "integer"}}, ["lat", "lon", "category"]),
    _tool("geo_weather", "Weather now (+ at arrival via eta_hours) for lat/lon.",
          {"lat": {"type": "number"}, "lon": {"type": "number"}, "eta_hours": {"type": "number"}}, ["lat", "lon"]),
    _tool("geo_maps_link", "One-tap Google/OSM deep link for a place or 'lat,lon'.",
          {"place_or_coords": {"type": "string"}}, ["place_or_coords"]),
    _tool("geo_track_start", "Watch live location for N minutes.",
          {"chat_id": {"type": "string"}, "minutes": {"type": "number"}}, ["chat_id"]),
    _tool("geo_track_stop", "Stop live-location tracking.", {"chat_id": {"type": "string"}}, ["chat_id"]),
    _tool("geo_whereami", "Last known location or error if never shared.", {"chat_id": {"type": "string"}}, []),
    _tool("geo_visit_log", "Record/query place visits. action=list|add|forget.",
          {"chat_id": {"type": "string"}, "action": {"type": "string"}, "place_name": {"type": "string"},
           "lat": {"type": "number"}, "lon": {"type": "number"}, "note": {"type": "string"}, "since": {"type": "string"}, "forget": {"type": "boolean"}}, []),
    _tool("calendar_today", "Today's Google Calendar events (honest 'not connected' when no OAuth, never hallucinate).",
          {"limit": {"type": "integer"}, "calendar_id": {"type": "string"}}, []),
    _tool("calendar_search", "Search Google Calendar events by text.",
          {"query": {"type": "string"}, "max_results": {"type": "integer"}, "calendar_id": {"type": "string"}}, ["query"]),
    _tool("calendar_create", "Create a Google Calendar event (needs OAuth; start ISO e.g. 2026-09-13T09:30:00).",
          {"summary": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
           "location": {"type": "string"}, "description": {"type": "string"}, "calendar_id": {"type": "string"}}, ["summary", "start"]),
    _tool("calendar_brief", "Meetings + travel/maps links + prep links for today.",
          {"limit": {"type": "integer"}, "calendar_id": {"type": "string"}}, []),
    _tool("calendar_status", "Calendar connection status (no secrets echoed).",
          {}, []),
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
        from tools import scrape as _scrape

        if not _scrape.enabled():
            raise RuntimeError("scrape disabled")
    except Exception:
        tools = [t for t in tools if not str(t.get("function", {}).get("name", "")).endswith(
            ("__scrape_low", "__scrape_mid", "__scrape_high"))]
    try:
        from vault import service as _vault

        if not _vault.enabled():
            raise RuntimeError("vault disabled")
    except Exception:
        tools = [t for t in tools if not str(t.get("function", {}).get("name", "")).endswith(
            ("__vault_search", "__vault_doc", "__vault_read", "__vault_ask", "__vault_status"))]
    if os.getenv("ZUMBA_NO_MEMORY", "") == "1":
        tools = [t for t in tools if not str(t.get("function", {}).get("name", "")).endswith(
            ("__memory_remember", "__memory_search", "__memory_forget", "__brief",
             "__goal_add", "__goal_list", "__goal_show", "__goal_complete_step", "__remind_add", "__task_list", "__task_update"))]
    if os.getenv("ZUMBA_NO_GEO", "") == "1":
        tools = [t for t in tools if not str(t.get("function", {}).get("name", "")).endswith(
            ("__geo_geocode", "__geo_reverse", "__geo_route", "__geo_traffic", "__geo_nearby",
             "__geo_weather", "__geo_maps_link", "__geo_track_start", "__geo_track_stop",
             "__geo_whereami", "__geo_visit_log"))]
    if os.getenv("ZUMBA_NO_CALENDAR", "") == "1":
        tools = [t for t in tools if not str(t.get("function", {}).get("name", "")).endswith(
            ("__calendar_today", "__calendar_search", "__calendar_create",
             "__calendar_brief", "__calendar_status"))]
    try:
        from tools import filesystem as _fs

        if not _fs.enabled():
            raise RuntimeError("fs disabled")
    except Exception:
        tools = [t for t in tools if not str(t.get("function", {}).get("name", "")).endswith(
            ("__fs_read", "__fs_grep", "__fs_find", "__fs_list", "__fs_info",
             "__fs_glob", "__fs_tree", "__fs_write", "__fs_edit", "__fs_insert",
             "__fs_replace_lines", "__fs_apply_patch", "__fs_batch", "__fs_undo",
             "__fs_mkdir", "__fs_move", "__fs_delete"))]
    return tools

# (search results live in mgr.meta_state["last_search"] — per-instance, no globals)


async def handle(mgr: Any, tool: str, arguments: dict) -> str:
    """Execute a META_SERVER meta-tool (async). Returns plain text for the model."""
    args = arguments or {}
    if tool in ('task_list', 'task_update'):
        import asyncio
        import json
        from memory import task_lifecycle
        return json.dumps(await asyncio.to_thread(task_lifecycle.tool_request, tool, args), ensure_ascii=False)
    if tool == "mcp_search":
        query = str(args.get("query", "")).strip()
        if not query:
            return "ERROR: 'query' is required."
        import asyncio
        results = await asyncio.to_thread(registry.search, query, limit=int(args.get("limit", defaults.SEARCH_LIMIT) or defaults.SEARCH_LIMIT))
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
        lines = [f"{r['name']}: {r['status']} ({r['transport']}) — {r['tool_count']} tool(s) {r['tools'] or ''}" for r in rows] if rows else []
        try:
            builtin_names = [t["function"]["name"] for t in visible_tools()]
        except Exception:
            builtin_names = []
        if builtin_names:
            lines.append(f"zumba: online (built-in) — {len(builtin_names)} tool(s) {builtin_names}")
        if not lines:
            return "No MCP servers configured. Use zumba__mcp_search to find one."
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

    if tool in ("scrape_low", "scrape_mid", "scrape_high"):
        import asyncio as _asyncio2b
        import json as _json2
        from tools import scrape as _scrape

        if not _scrape.enabled():
            return "ERROR: scrape tools are disabled (ZUMBA_NO_SCRAPE=1)."
        if tool == "scrape_low":
            url = str(args.get("url", "") or "").strip()
            if not url:
                return "ERROR: 'url' is required."
            try:
                mc = int(args.get("max_chars", 0) or 0)
            except Exception:
                return "ERROR: 'max_chars' must be a number."
            text, note = await _asyncio2b.to_thread(
                _scrape.scrape_low, url, str(args.get("format", "markdown") or "markdown"), mc)
            return (text + (f"\n{note}" if note and text else "")) if text else (note or "ERROR: scrape failed.")
        if tool == "scrape_mid":
            url = str(args.get("url", "") or "").strip()
            if not url:
                return "ERROR: 'url' is required."
            try:
                mc = int(args.get("max_chars", 0) or 0)
            except Exception:
                return "ERROR: 'max_chars' must be a number."
            sels = args.get("selectors", "")
            if isinstance(sels, dict):
                sels = _json2.dumps(sels)
            text, note = await _asyncio2b.to_thread(
                _scrape.scrape_mid, url, sels or "",
                str(args.get("format", "markdown") or "markdown"),
                str(args.get("mode", "auto") or "auto"),
                str(args.get("wait_selector", "") or ""), mc)
            return (text + (f"\n{note}" if note and text else "")) if text else (note or "ERROR: scrape failed.")
        urls = args.get("urls", "") or args.get("url", "")
        if isinstance(urls, list):
            urls = " ".join(str(u) for u in urls)
        urls = str(urls or "").strip()
        if not urls:
            return "ERROR: 'urls' is required."
        try:
            depth = int(args.get("depth", 1) if args.get("depth", 1) is not None else 1)
        except Exception:
            return "ERROR: 'depth' must be a number."
        try:
            limit = int(args.get("limit", 8) if args.get("limit", 8) is not None else 8)
        except Exception:
            return "ERROR: 'limit' must be a number."
        sels = args.get("selectors", "")
        if isinstance(sels, dict):
            sels = _json2.dumps(sels)
        text, note = await _asyncio2b.to_thread(
            _scrape.scrape_high, urls, depth, limit,
            bool(args.get("same_domain", True)), sels or "",
            str(args.get("mode", "auto") or "auto"))
        return (text + (f"\n{note}" if note and text else "")) if text else (note or "ERROR: crawl failed.")

    if tool in ("fs_read", "fs_grep", "fs_find", "fs_list", "fs_info", "fs_glob",
                "fs_tree", "fs_write", "fs_edit", "fs_insert", "fs_replace_lines",
                "fs_apply_patch", "fs_batch", "fs_undo", "fs_mkdir", "fs_move", "fs_delete"):
        import asyncio as _asyncio2c
        from tools import filesystem as _fs

        if not _fs.enabled():
            return "ERROR: filesystem tools are disabled (ZUMBA_NO_FS=1)."

        def _num(v, default=0):
            try:
                return int(v)
            except Exception:
                return default

        if tool == "fs_read":
            path = str(args.get("path", "") or "").strip()
            if not path:
                return "ERROR: 'path' is required."
            return await _asyncio2c.to_thread(
                _fs.fs_read, path, _num(args.get("start_line", 1), 1) or 1,
                _num(args.get("num_lines", 200), 200) or 200)
        if tool == "fs_grep":
            pattern = str(args.get("pattern", "") or "")
            if not pattern.strip():
                return "ERROR: 'pattern' is required."
            return await _asyncio2c.to_thread(
                _fs.fs_grep, pattern, str(args.get("path", ".") or "."),
                str(args.get("glob", "") or ""), _num(args.get("context", 0)),
                bool(args.get("case_sensitive", False)),
                _num(args.get("max_results", 100), 100) or 100)
        if tool == "fs_find":
            name = str(args.get("name", "") or "")
            if not name.strip():
                return "ERROR: 'name' is required."
            return await _asyncio2c.to_thread(
                _fs.fs_find, name, str(args.get("path", ".") or "."),
                _num(args.get("max_results", 50), 50) or 50)
        if tool == "fs_list":
            return await _asyncio2c.to_thread(
                _fs.fs_list, str(args.get("path", ".") or "."),
                _num(args.get("max_items", 30), 30) or 30,
                str(args.get("sort", "name") or "name"))
        if tool == "fs_info":
            path = str(args.get("path", "") or "").strip()
            if not path:
                return "ERROR: 'path' is required."
            return await _asyncio2c.to_thread(_fs.fs_info, path)
        if tool == "fs_glob":
            pattern = str(args.get("pattern", "") or "")
            if not pattern.strip():
                return "ERROR: 'pattern' is required."
            return await _asyncio2c.to_thread(
                _fs.fs_glob, pattern, str(args.get("path", ".") or "."),
                _num(args.get("max_results", 50), 50) or 50)
        if tool == "fs_tree":
            return await _asyncio2c.to_thread(
                _fs.fs_tree, str(args.get("path", ".") or "."),
                _num(args.get("max_depth", 3), 3) or 3)
        if tool == "fs_write":
            path = str(args.get("path", "") or "").strip()
            if not path:
                return "ERROR: 'path' is required."
            if args.get("content") is None:
                return "ERROR: 'content' is required."
            return await _asyncio2c.to_thread(
                _fs.fs_write, path, str(args.get("content", "")),
                bool(args.get("dry_run", False)))
        if tool == "fs_edit":
            path = str(args.get("path", "") or "").strip()
            if not path:
                return "ERROR: 'path' is required."
            if not str(args.get("old_text", "") or ""):
                return "ERROR: 'old_text' is required."
            if args.get("new_text") is None:
                return "ERROR: 'new_text' is required."
            return await _asyncio2c.to_thread(
                _fs.fs_edit, path, str(args.get("old_text", "")),
                str(args.get("new_text", "")), _num(args.get("occurrence", 0)),
                bool(args.get("dry_run", False)))
        if tool == "fs_insert":
            path = str(args.get("path", "") or "").strip()
            if not path:
                return "ERROR: 'path' is required."
            if args.get("text") is None:
                return "ERROR: 'text' is required."
            try:
                line = int(args.get("line", 0) or 0)
            except Exception:
                return "ERROR: 'line' must be a number."
            return await _asyncio2c.to_thread(
                _fs.fs_insert, path, line, str(args.get("text", "")),
                str(args.get("position", "after") or "after"),
                bool(args.get("dry_run", False)))
        if tool == "fs_replace_lines":
            path = str(args.get("path", "") or "").strip()
            if not path:
                return "ERROR: 'path' is required."
            if args.get("new_text") is None:
                return "ERROR: 'new_text' is required."
            try:
                start = int(args.get("start", 0) or 0)
                end = int(args.get("end", 0) or 0)
            except Exception:
                return "ERROR: 'start'/'end' must be numbers."
            return await _asyncio2c.to_thread(
                _fs.fs_replace_lines, path, start, end,
                str(args.get("new_text", "")), bool(args.get("dry_run", False)))
        if tool == "fs_apply_patch":
            patch = str(args.get("patch", "") or "")
            if not patch.strip():
                return "ERROR: 'patch' is required."
            return await _asyncio2c.to_thread(
                _fs.fs_apply_patch, patch, bool(args.get("dry_run", False)))
        if tool == "fs_batch":
            ops = args.get("operations", [])
            if not isinstance(ops, list) or not ops:
                return "ERROR: 'operations' must be a non-empty list."
            return await _asyncio2c.to_thread(
                _fs.fs_batch, ops, bool(args.get("dry_run", False)))
        if tool == "fs_undo":
            path = str(args.get("path", "") or "").strip()
            if not path:
                return "ERROR: 'path' is required."
            return await _asyncio2c.to_thread(
                _fs.fs_undo, path, bool(args.get("dry_run", False)))
        if tool == "fs_mkdir":
            path = str(args.get("path", "") or "").strip()
            if not path:
                return "ERROR: 'path' is required."
            return await _asyncio2c.to_thread(_fs.fs_mkdir, path)
        if tool == "fs_move":
            src = str(args.get("source", "") or "").strip()
            dst = str(args.get("destination", "") or "").strip()
            if not src or not dst:
                return "ERROR: 'source' and 'destination' are required."
            return await _asyncio2c.to_thread(_fs.fs_move, src, dst)
        path = str(args.get("path", "") or "").strip()
        if not path:
            return "ERROR: 'path' is required."
        return await _asyncio2c.to_thread(
            _fs.fs_delete, path, bool(args.get("confirm", False)))

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

    if tool == "goal_list":
        import asyncio as _asyncio5
        from memory import db as _mdb5
        from memory import goals as _goals5

        status = str(args.get("status", "") or "active").strip().lower() or "active"
        if status not in ("active", "all", "done"):
            return "ERROR: 'status' must be active, all, or done."
        con = _mdb5.connect()
        try:
            _mdb5.ensure_tier3(con)
            goals = await _asyncio5.to_thread(_goals5.list_goals, con, status)
            if not goals:
                return "No goals yet. Create one with goal_add."
            return await _asyncio5.to_thread(_goals5.render_list, goals, con)
        finally:
            try:
                con.close()
            except Exception:
                pass

    if tool in ("memory_remember", "memory_search", "memory_forget"):
        import asyncio as _asyncio6

        try:
            from memory import get_memory as _get_mem
            mem = _get_mem()
        except Exception as exc:
            return f"ERROR: memory unavailable ({str(exc)[:150]})."
        if tool == "memory_remember":
            text = str(args.get("text", "") or "").strip()
            if not text:
                return "ERROR: 'text' is required."
            await _asyncio6.to_thread(mem.capture_async, text, "", "tool", "remember")
            return "Saved to the durable memory inbox. Extraction/indexing continues in the background; the original text is already available to recall."
        if tool == "memory_search":
            query = str(args.get("query", "") or "").strip()
            if not query:
                return "ERROR: 'query' is required."
            try:
                k = int(args.get("top_k", 8) or 8)
            except Exception:
                return "ERROR: 'top_k' must be a number."
            hits = await _asyncio6.to_thread(mem.recall, query, k, 4500)
            return hits or "(nothing recalled)"
        target = str(args.get("name", "") or "").strip()
        if not target:
            return "ERROR: 'name' is required."
        r = await _asyncio6.to_thread(mem.forget, target)
        return "Forgot." if r.get("forgot") else "No facts found for that name."

    if tool == "brief":
        import asyncio as _asyncio7
        from memory import briefing as _br

        try:
            from memory import get_memory as _get_mem7
            mem = _get_mem7()
        except Exception as exc:
            return f"ERROR: memory unavailable ({str(exc)[:150]})."
        con = mem._open()
        try:
            return await _asyncio7.to_thread(_br.compose_daily, con, True)
        finally:
            try:
                if getattr(mem, "_own", True):
                    con.close()
            except Exception:
                pass

    if tool in ("soul_show", "me_show", "soul_diff", "soul_accept", "soul_reject", "soul_propose"):
        if tool == "soul_show":
            try:
                from identity import soul as _soul
                return _soul.load() or "(no soul.md yet — chat /soul wingit to draft one)"
            except Exception as exc:
                return f"ERROR: soul unavailable ({str(exc)[:150]})."
        try:
            from identity import soul as _soul2
        except Exception as exc:
            return f"ERROR: soul unavailable ({str(exc)[:150]})."
        if tool == "soul_propose":
            content = str(args.get("content", "") or "")
            if len(content.strip()) < 50:
                return "ERROR: 'content' must be the full new soul.md (too short)."
            path = _soul2.propose_update(content)
            return f"Proposal saved to {path}. Show soul_diff and ask the user to confirm."
        if tool == "soul_diff":
            return _soul2.diff_proposed()
        if tool == "soul_accept":
            if not _soul2.has_proposal():
                return "ERROR: no pending proposal — call soul_propose first."
            return "Soul updated." if _soul2.apply_proposal() else "ERROR: apply failed."
        if tool == "soul_reject":
            _soul2.reject_proposal()
            return "Proposal discarded."
        if tool == "me_show":
            return _graph_profile()
        try:
            return _graph_profile()
        except Exception as exc:
            return f"ERROR: profile unavailable ({str(exc)[:150]})."

    if tool in ("vault_ask", "vault_status"):
        import asyncio as _asyncio8
        from vault import service as _vault8

        if not _vault8.enabled():
            return "ERROR: vault is disabled (ZUMBA_NO_VAULT=1)."
        v = _vault8.get_vault()
        if tool == "vault_status":
            st = await _asyncio8.to_thread(v.status)
            if not isinstance(st, dict):
                return str(st)
            lines = [f"{k}: {st[k]}" for k in sorted(st)]
            return "\n".join(lines) or "(empty vault)"
        question = str(args.get("question", "") or "").strip()
        if not question:
            return "ERROR: 'question' is required."
        try:
            k = int(args.get("k", 6) or 6)
        except Exception:
            return "ERROR: 'k' must be a number."
        return await _asyncio8.to_thread(v.ask, question, k, True)

    if tool in ("geo_geocode", "geo_reverse", "geo_route", "geo_traffic", "geo_nearby",
                  "geo_weather", "geo_maps_link", "geo_track_start", "geo_track_stop",
                  "geo_whereami", "geo_visit_log"):
        import asyncio as _asyncio9
        from tools import geo as _geo
        if not _geo.enabled():
            return "ERROR: geo tools are disabled (ZUMBA_NO_GEO=1)."
        def _num(v, d=0.0):
            try: return float(v)
            except Exception: return d
        if tool == "geo_geocode":
            return await _asyncio9.to_thread(_geo.geocode, str(args.get("place", "") or ""))
        if tool == "geo_reverse":
            return await _asyncio9.to_thread(_geo.reverse, _num(args.get("lat")), _num(args.get("lon")))
        if tool == "geo_route":
            return await _asyncio9.to_thread(_geo.route, str(args.get("origin", "") or ""),
                                             str(args.get("destination", "") or ""), str(args.get("mode", "drive") or "drive"))
        if tool == "geo_traffic":
            return await _asyncio9.to_thread(_geo.traffic, str(args.get("origin", "") or ""), str(args.get("destination", "") or ""))
        if tool == "geo_nearby":
            try: lim = int(args.get("limit", 8) or 8)
            except Exception: return "ERROR: 'limit' must be a number."
            return await _asyncio9.to_thread(_geo.nearby, _num(args.get("lat")), _num(args.get("lon")),
                                             str(args.get("category", "") or ""), lim)
        if tool == "geo_weather":
            return await _asyncio9.to_thread(_geo.weather, _num(args.get("lat")), _num(args.get("lon")), _num(args.get("eta_hours", 0)))
        if tool == "geo_maps_link":
            return _geo.maps_link(str(args.get("place_or_coords", "") or ""))
        if tool == "geo_track_start":
            try: mins = float(args.get("minutes", 15) or 15)
            except Exception: return "ERROR: 'minutes' must be a number."
            return await _asyncio9.to_thread(_geo.track_start_fn, str(args.get("chat_id", "") or "default"), mins)
        if tool == "geo_track_stop":
            return await _asyncio9.to_thread(_geo.track_stop_fn, str(args.get("chat_id", "") or "default"))
        if tool == "geo_whereami":
            return await _asyncio9.to_thread(_geo.whereami, str(args.get("chat_id", "") or "default"))
        return await _asyncio9.to_thread(_geo.visit_log, str(args.get("chat_id", "") or "default"),
                                         str(args.get("action", "list") or "list"), str(args.get("place_name", "") or ""),
                                         _num(args.get("lat", 0)), _num(args.get("lon", 0)),
                                         str(args.get("note", "") or ""), str(args.get("since", "") or ""),
                                         bool(args.get("forget", False)))

    if tool in ("calendar_today", "calendar_search", "calendar_create",
                "calendar_brief", "calendar_status"):
        import asyncio as _asyncio10
        from tools import calendar as _cal
        if not _cal.enabled():
            return "ERROR: calendar tools are disabled (ZUMBA_NO_CALENDAR=1)."
        if tool == "calendar_status":
            return await _asyncio10.to_thread(_cal.status_text)
        if tool == "calendar_today":
            try: lim = int(args.get("limit", 10) or 10)
            except Exception: return "ERROR: 'limit' must be a number."
            return await _asyncio10.to_thread(_cal.today, lim, str(args.get("calendar_id", "") or ""))
        if tool == "calendar_search":
            try: lim = int(args.get("max_results", 10) or 10)
            except Exception: return "ERROR: 'max_results' must be a number."
            return await _asyncio10.to_thread(_cal.search, str(args.get("query", "") or ""),
                                              lim, str(args.get("calendar_id", "") or ""))
        if tool == "calendar_brief":
            try: lim = int(args.get("limit", 10) or 10)
            except Exception: return "ERROR: 'limit' must be a number."
            return await _asyncio10.to_thread(_cal.brief, str(args.get("calendar_id", "") or ""), lim)
        return await _asyncio10.to_thread(
            _cal.create, str(args.get("summary", "") or ""), str(args.get("start", "") or ""),
            str(args.get("end", "") or ""), str(args.get("location", "") or ""),
            str(args.get("description", "") or ""), str(args.get("calendar_id", "") or ""))

    return f"ERROR: unknown meta-tool '{tool}'."


async def _areload(mgr: Any) -> str:
    summary = await mgr.reload()
    parts = [f"{k}: {','.join(v) if isinstance(v, list) else v}" for k, v in summary.items() if v]
    return "; ".join(parts) or "no changes"
