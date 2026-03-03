"""
Figma Connector for A.N.K.I.T.A 🎨

Gives ANKITA design assistant superpowers — check design feedback
without opening the heavy Figma app:
  - list_files         : "What are the latest design files in my project?"
  - read_comments      : "Did the client leave feedback on the Homepage?"
  - get_node_properties: "What is the hex code of the primary button?"
  - list_projects      : "What Figma projects am I in?"
  - post_comment       : "Reply to the client on the Homepage file"

Authentication: Figma Personal Access Token via auth_manager.get_figma_token()
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

_FIGMA_BASE = "https://api.figma.com/v1"


def _headers() -> Dict[str, str]:
    """Return auth headers for Figma REST API."""
    from tools.auth_manager import get_figma_token
    token = get_figma_token()
    return {"X-Figma-Token": token}


def _get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Make a GET request to the Figma API."""
    url = f"{_FIGMA_BASE}/{endpoint.lstrip('/')}"
    try:
        resp = requests.get(url, headers=_headers(), params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        return {"error": str(e), "status_code": getattr(e.response, "status_code", None)}
    except Exception as e:
        return {"error": str(e)}


def _post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Make a POST request to the Figma API."""
    url = f"{_FIGMA_BASE}/{endpoint.lstrip('/')}"
    try:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        return {"error": str(e), "status_code": getattr(e.response, "status_code", None)}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Public API functions (called by engine.py dispatcher)
# ---------------------------------------------------------------------------

def _sanitize_comments(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Prism Protocol — Comment Sanitizer 🎨
    Strips coordinates, reaction data, and timestamps from Figma comments.
    Keeps only: id, author, message, resolved status.
    """
    return [
        {
            "id":       c.get("id", ""),
            "author":   c.get("author", c.get("user", {}).get("handle", "Unknown")),
            "message":  c.get("message", ""),
            "resolved": c.get("resolved", c.get("resolved_at") is not None),
        }
        for c in comments
    ]


def _sanitize_figma_nodes(nodes: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prism Protocol — Node Sanitizer 🎨
    Strips layout/coordinate/style bloat from Figma node data.
    Keeps only: name, type, text content, fill hex codes, width, height, font.
    """
    clean: Dict[str, Any] = {}
    for nid, ndata in nodes.items():
        doc = ndata.get("document", ndata)  # support both raw and pre-parsed nodes
        fills_raw = doc.get("fills", [])
        fills_clean = []
        for fill in fills_raw:
            if fill.get("type") == "SOLID":
                c = fill.get("color", {})
                r = int(c.get("r", 0) * 255)
                g = int(c.get("g", 0) * 255)
                b = int(c.get("b", 0) * 255)
                fills_clean.append({"type": "SOLID", "hex": f"#{r:02X}{g:02X}{b:02X}"})
            else:
                fills_clean.append({"type": fill.get("type", "UNKNOWN")})

        clean[nid] = {
            "name":      doc.get("name", ""),
            "type":      doc.get("type", ""),
            "text":      doc.get("characters", ""),
            "fills":     fills_clean,
            "width":     doc.get("absoluteBoundingBox", {}).get("width"),
            "height":    doc.get("absoluteBoundingBox", {}).get("height"),
            "font_name": doc.get("style", {}).get("fontFamily"),
            "font_size": doc.get("style", {}).get("fontSize"),
        }
    return clean


def list_projects(team_id: str) -> Dict[str, Any]:
    """
    List all projects in a Figma team.

    Args:
        team_id: Figma Team ID (found in team URL)

    Returns:
        {"status": "success", "projects": [{"id": ..., "name": ...}, ...]}
    """
    data = _get(f"teams/{team_id}/projects")
    if "error" in data:
        return {"status": "error", "message": data["error"]}

    projects = [
        {"id": p["id"], "name": p["name"]}
        for p in data.get("projects", [])
    ]
    return {"status": "success", "projects": projects, "count": len(projects)}


def list_files(project_id: str) -> Dict[str, Any]:
    """
    List all design files in a Figma project.

    Args:
        project_id: Figma Project ID

    Returns:
        {"status": "success", "files": [{"key": ..., "name": ..., "last_modified": ...}, ...]}
    """
    data = _get(f"projects/{project_id}/files")
    if "error" in data:
        return {"status": "error", "message": data["error"]}

    files = [
        {
            "key":           f["key"],
            "name":          f["name"],
            "last_modified": f.get("last_modified", ""),
            "url":           f"https://www.figma.com/file/{f['key']}",
        }
        for f in data.get("files", [])
    ]
    return {"status": "success", "files": files, "count": len(files)}


def read_comments(file_key: str) -> Dict[str, Any]:
    """
    Read all comments on a Figma file.

    Args:
        file_key: The Figma file key (from the URL: figma.com/file/<KEY>)

    Returns:
        {"status": "success", "comments": [{"id", "author", "message", "created_at"}, ...]}
    """
    data = _get(f"files/{file_key}/comments")
    if "error" in data:
        return {"status": "error", "message": data["error"]}

    # 💎 Prism Protocol: strip coords/timestamps — keep only essential fields
    comments = _sanitize_comments(data.get("comments", []))
    return {
        "status":   "success",
        "file_key": file_key,
        "comments": comments,
        "count":    len(comments),
    }


def post_comment(file_key: str, message: str, node_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Post a comment on a Figma file (optionally on a specific node/frame).

    Args:
        file_key: The Figma file key
        message: The comment text
        node_id: Optional node ID to anchor the comment to a specific element

    Returns:
        {"status": "success", "comment_id": ..., "message": ...}
    """
    payload: Dict[str, Any] = {"message": message}
    if node_id:
        payload["client_meta"] = {"node_id": node_id}

    data = _post(f"files/{file_key}/comments", payload)
    if "error" in data:
        return {"status": "error", "message": data["error"]}

    return {
        "status":     "success",
        "comment_id": data.get("id"),
        "message":    message,
        "file_key":   file_key,
    }


def get_node_properties(file_key: str, node_ids: str) -> Dict[str, Any]:
    """
    Get properties of specific nodes in a Figma file (colours, typography, dimensions).

    Args:
        file_key: The Figma file key
        node_ids: Comma-separated node IDs, e.g. "1:2,1:3"

    Returns:
        {"status": "success", "nodes": {node_id: {name, type, fills, strokes, ...}}}
    """
    data = _get(f"files/{file_key}/nodes", params={"ids": node_ids})
    if "error" in data:
        return {"status": "error", "message": data["error"]}

    # 💎 Prism Protocol: strip coordinate/layout bloat — keep only name, type, fills, font
    parsed = _sanitize_figma_nodes(data.get("nodes", {}))
    return {
        "status":   "success",
        "file_key": file_key,
        "nodes":    parsed,
    }


def get_file_info(file_key: str) -> Dict[str, Any]:
    """
    Get metadata about a Figma file (name, last modified, version, pages).

    Args:
        file_key: The Figma file key

    Returns:
        {"status": "success", "name": ..., "last_modified": ..., "pages": [...]}
    """
    data = _get(f"files/{file_key}", params={"depth": 1})
    if "error" in data:
        return {"status": "error", "message": data["error"]}

    pages = [
        {"id": page["id"], "name": page["name"]}
        for page in data.get("document", {}).get("children", [])
    ]
    return {
        "status":        "success",
        "name":          data.get("name", ""),
        "last_modified": data.get("lastModified", ""),
        "version":       data.get("version", ""),
        "pages":         pages,
        "url":           f"https://www.figma.com/file/{file_key}",
    }
