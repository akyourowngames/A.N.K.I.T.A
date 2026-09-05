"""MCP server registry: ~/.zumba/mcp.json (Claude-Desktop compatible) + project .mcp.json.

Supported server entry shapes:
  stdio:  {"command": "npx", "args": [...], "env": {...}, "cwd": "..."}
  http:   {"transport": "http", "url": "...", "headers": {...}}
  sse:    {"transport": "sse", "url": "...", "headers": {...}}
Common extras: {"enabled": true} (default), {"timeout": 60} (tool call seconds).
"""
import json
from pathlib import Path
from typing import Any, Optional


def home_config_path() -> Path:
    return Path.home() / ".zumba" / "mcp.json"


def project_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".mcp.json"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    return servers if isinstance(servers, dict) else {}


def _norm(name: str, entry: Any) -> Optional[dict]:
    if not isinstance(entry, dict) or not name.strip():
        return None
    entry = dict(entry)
    entry.setdefault("name", name.strip())
    transport = str(entry.get("transport", "") or "").lower()
    if not transport:
        transport = "http" if entry.get("url") else "stdio"
    entry["transport"] = transport
    if transport == "stdio" and not entry.get("command"):
        return None
    if transport in ("http", "sse") and not entry.get("url"):
        return None
    entry.setdefault("enabled", True)
    entry.setdefault("timeout", 60)
    return entry


def list_servers() -> dict:
    """All registered servers; project .mcp.json entries override home entries on name clash."""
    merged: dict = {}
    for path in (home_config_path(), project_config_path()):
        for name, entry in _read_json(path).items():
            norm = _norm(name, entry)
            if norm:
                merged[name.strip()] = norm
    return merged


def get_server(name: str) -> Optional[dict]:
    servers = list_servers()
    return servers.get(name.strip())


def save_servers(entries: dict, path: Optional[Path] = None) -> Path:
    path = path or home_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"mcpServers": entries}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def add_server(name: str, entry: dict) -> Path:
    servers = _read_json(home_config_path())
    norm = _norm(name, entry)
    if norm is None:
        raise ValueError("Server entry needs a 'command' (stdio) or 'url' (http/sse).")
    servers[name.strip()] = norm
    return save_servers(servers)


def remove_server(name: str) -> bool:
    servers = _read_json(home_config_path())
    name = name.strip()
    if name not in servers:
        return False
    del servers[name]
    save_servers(servers)
    return True
