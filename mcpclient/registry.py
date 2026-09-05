"""Official MCP registry client.

Default endpoint is the official registry (registry.modelcontextprotocol.io);
override with ZUMBA_MCP_REGISTRY_URL. Lets ZUMBA search for servers and turn
results into installable mcp.json entries without leaving the chat.
"""
from typing import Optional

import requests

from mcpclient import defaults


def _entry_from_remote(remote: dict, name: str) -> Optional[dict]:
    url = str(remote.get("url", "") or "").strip()
    if not url:
        return None
    entry: dict = {"transport": "http", "url": url}
    headers = {}
    needs_key = False
    for h in remote.get("headers") or []:
        if not isinstance(h, dict):
            continue
        if h.get("isRequired") or h.get("value"):
            needs_key = True
        if not h.get("isRequired") and h.get("name"):
            headers[str(h["name"])] = str(h.get("value", ""))
    if headers:
        entry["headers"] = headers
    entry["_needs_key"] = needs_key
    return entry


def _entry_from_package(pkg: dict) -> Optional[dict]:
    reg_type = str(pkg.get("registry_type", pkg.get("registryType", "")) or "").lower()
    ident = str(pkg.get("identifier", "") or "").strip()
    if not ident:
        return None
    args = ["-y", ident]
    for a in pkg.get("package_arguments") or []:
        if isinstance(a, dict):
            val = a.get("value", a.get("name", ""))
            if val:
                args.append(str(val))
    if reg_type == "pypi":
        return {"command": "uvx", "args": [ident]}
    return {"command": "npx", "args": args}  # npm / unknown -> npx


def _parse(server: dict) -> dict:
    name = str(server.get("name", "") or "").split("/")[-1].replace("_", "-") or "server"
    out = {
        "name": name,
        "full_name": str(server.get("name", "") or ""),
        "description": str(server.get("description", "") or "")[:220],
        "version": str(server.get("version", "") or ""),
    }
    entry = None
    for remote in server.get("remotes") or []:
        if isinstance(remote, dict):
            entry = _entry_from_remote(remote, out["name"])
            if entry:
                break
    if entry is None:
        for pkg in server.get("packages") or []:
            if isinstance(pkg, dict):
                entry = _entry_from_package(pkg)
                if entry:
                    break
    out["install"] = entry
    return out


def search(query: str, limit: int = defaults.SEARCH_LIMIT, timeout: float = defaults.SEARCH_TIMEOUT) -> list:
    """Search the registry. Returns [] on any failure (never raises)."""
    try:
        resp = requests.get(
            defaults.REGISTRY_URL,
            params={"search": query.strip(), "limit": str(max(1, min(20, limit)))},
            timeout=timeout,
        )
        if resp.status_code >= 400:
            return []
        servers = resp.json().get("servers", [])
    except Exception:
        return []
    out = []
    for row in servers:
        server = row.get("server") if isinstance(row, dict) else None
        if not isinstance(server, dict):
            continue
        parsed = _parse(server)
        if parsed["install"]:
            out.append(parsed)
    return out
