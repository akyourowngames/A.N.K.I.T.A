from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memory_brain import (
    MemoryBrainConfig,
    graph_export,
    memory_brain_reindex as run_memory_brain_reindex,
    memory_brain_status as get_memory_brain_status,
    project_memory_summary,
    search_memory_brain,
)
from memory_graph import list_entities, load_entity, utc_now
from memory_retrieval import entity_matches_for_query, entity_neighbors, summary_for_type, timeline

from .registry import ToolInputError, optional_text, require_text


def memory_brain_status(params: dict[str, Any]) -> dict[str, Any]:
    status = get_memory_brain_status(Path.cwd())
    counts = status.get("counts", {})
    status["summary"] = (
        f"Memory Brain has {counts.get('facts', 0)} facts, {counts.get('entities', 0)} entities, "
        f"and {counts.get('edges', 0)} edges."
    )
    return status


def memory_brain_reindex(params: dict[str, Any]) -> dict[str, Any]:
    include = params.get("include_transcripts")
    include_transcripts = bool(include) if isinstance(include, bool) else None
    return run_memory_brain_reindex(Path.cwd(), include_transcripts=include_transcripts)


def memory_brain_search(params: dict[str, Any]) -> dict[str, Any]:
    query = require_text(params, "query")
    max_facts = bounded_int(params.get("max_facts"), MemoryBrainConfig.from_env(Path.cwd()).max_facts, 1, 30)
    max_hops = bounded_int(params.get("max_hops"), MemoryBrainConfig.from_env(Path.cwd()).max_hops, 0, 4)
    return search_memory_brain(query, Path.cwd(), max_facts=max_facts, max_hops=max_hops)


def memory_entity_search(params: dict[str, Any]) -> dict[str, Any]:
    query = require_text(params, "query")
    limit = bounded_int(params.get("limit"), 10, 1, 50)
    brain_config = MemoryBrainConfig.from_env(Path.cwd())
    matches = entity_matches_for_query(query, list_entities(brain_config.db_path, limit=1000))[:limit]
    return {
        "query": query,
        "count": len(matches),
        "matches": matches,
        "summary": f"Found {len(matches)} memory entities for {query}.",
    }


def memory_entity_get(params: dict[str, Any]) -> dict[str, Any]:
    entity_id = optional_text(params, "entity_id", "")
    name = optional_text(params, "name", "")
    brain_config = MemoryBrainConfig.from_env(Path.cwd())
    if entity_id:
        entity = load_entity(brain_config.db_path, entity_id)
    elif name:
        matches = entity_matches_for_query(name, list_entities(brain_config.db_path, limit=1000))
        entity = matches[0]["entity"] if matches else None
    else:
        raise ToolInputError("entity_id or name is required")
    if entity is None:
        raise ToolInputError("memory entity not found")
    return entity


def memory_graph_neighbors(params: dict[str, Any]) -> dict[str, Any]:
    entity_id = optional_text(params, "entity_id", "")
    name = optional_text(params, "name", "")
    max_hops = bounded_int(params.get("max_hops"), 1, 1, 4)
    brain_config = MemoryBrainConfig.from_env(Path.cwd())
    if not entity_id and name:
        matches = entity_matches_for_query(name, list_entities(brain_config.db_path, limit=1000))
        entity_id = matches[0]["entity"]["id"] if matches else ""
    if not entity_id:
        raise ToolInputError("entity_id or name is required")
    return entity_neighbors(brain_config.db_path, entity_id, max_hops=max_hops)


def memory_project_summary(params: dict[str, Any]) -> dict[str, Any]:
    project = optional_text(params, "project", "")
    limit = bounded_int(params.get("limit"), 10, 1, 40)
    return project_memory_summary(project, Path.cwd(), limit=limit)


def memory_preference_summary(params: dict[str, Any]) -> dict[str, Any]:
    limit = bounded_int(params.get("limit"), 12, 1, 40)
    brain_config = MemoryBrainConfig.from_env(Path.cwd())
    return summary_for_type(brain_config.db_path, "preference", limit=limit)


def memory_timeline(params: dict[str, Any]) -> dict[str, Any]:
    limit = bounded_int(params.get("limit"), 20, 1, 100)
    fact_type = optional_text(params, "type", "")
    brain_config = MemoryBrainConfig.from_env(Path.cwd())
    return timeline(brain_config.db_path, limit=limit, fact_type=fact_type)


def memory_conflicts(params: dict[str, Any]) -> dict[str, Any]:
    brain_config = MemoryBrainConfig.from_env(Path.cwd())
    conflicts = read_json_file(brain_config.conflicts_path, [])
    return {
        "path": str(brain_config.conflicts_path.resolve()),
        "count": len(conflicts) if isinstance(conflicts, list) else 0,
        "conflicts": conflicts if isinstance(conflicts, list) else [],
        "summary": f"Memory Brain has {len(conflicts) if isinstance(conflicts, list) else 0} unresolved conflicts.",
    }


def memory_forget_request(params: dict[str, Any]) -> dict[str, Any]:
    request = require_text(params, "request")
    brain_config = MemoryBrainConfig.from_env(Path.cwd())
    path = brain_config.graph_dir / "forget_requests.json"
    requests = read_json_file(path, [])
    if not isinstance(requests, list):
        requests = []
    entry = {"request": request, "created_at": utc_now(), "status": "pending_review"}
    requests.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(requests, ensure_ascii=True, indent=2), encoding="utf-8")
    return {
        "recorded": True,
        "path": str(path.resolve()),
        "request": request,
        "summary": "Forget request recorded for human review. TXT memory was not deleted automatically.",
    }


def memory_export(params: dict[str, Any]) -> dict[str, Any]:
    max_nodes = bounded_int(params.get("max_nodes"), 400, 1, 2000)
    max_edges = bounded_int(params.get("max_edges"), 600, 1, 3000)
    graph = graph_export(Path.cwd())
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if isinstance(nodes, list):
        graph["nodes"] = nodes[:max_nodes]
        graph["nodes_truncated"] = len(nodes) > max_nodes
    if isinstance(edges, list):
        graph["edges"] = edges[:max_edges]
        graph["edges_truncated"] = len(edges) > max_edges
    return graph


def read_json_file(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip():
        try:
            number = int(value.strip())
        except ValueError:
            number = fallback
    else:
        number = fallback
    return max(minimum, min(maximum, number))
