from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Any

from memory_graph import graph_json_from_db, graph_status, write_graph_index
from memory_ingest import build_memory_graph, source_paths
from memory_profile import project_summary, read_profile_summary, write_profile_summary
from memory_retrieval import MemorySearchOptions, memory_brain_search
from memory_system import MemoryConfig, ensure_memory_workspace


@dataclass(frozen=True)
class MemoryBrainConfig:
    root: Path
    graph_dir: Path
    db_path: Path
    graph_json_path: Path
    entity_index_path: Path
    conflicts_path: Path
    retrieval_cache_path: Path
    profile_summary_path: Path
    enabled: bool
    auto_reindex: bool
    search_timeout_ms: int
    max_facts: int
    max_hops: int
    include_transcripts: bool
    write_structured: bool
    debug: bool

    @classmethod
    def from_env(cls, workspace: Path) -> "MemoryBrainConfig":
        memory_root = Path(os.environ.get("JARVIS_MEMORY_DIR", str(workspace / "memory")))
        graph_dir = Path(os.environ.get("MEMORY_BRAIN_GRAPH_DIR", str(memory_root / "graph")))
        return cls(
            root=memory_root,
            graph_dir=graph_dir,
            db_path=Path(os.environ.get("MEMORY_BRAIN_DB_PATH", str(graph_dir / "memory.db"))),
            graph_json_path=Path(os.environ.get("MEMORY_BRAIN_GRAPH_JSON", str(graph_dir / "graph.json"))),
            entity_index_path=Path(os.environ.get("MEMORY_BRAIN_ENTITY_INDEX", str(graph_dir / "entity_index.json"))),
            conflicts_path=Path(os.environ.get("MEMORY_BRAIN_CONFLICTS", str(graph_dir / "unresolved_conflicts.json"))),
            retrieval_cache_path=Path(os.environ.get("MEMORY_BRAIN_RETRIEVAL_CACHE", str(graph_dir / "retrieval_cache.json"))),
            profile_summary_path=Path(os.environ.get("MEMORY_BRAIN_PROFILE_SUMMARY", str(graph_dir / "profile_summary.txt"))),
            enabled=env_bool("MEMORY_BRAIN_ENABLED", True),
            auto_reindex=env_bool("MEMORY_BRAIN_AUTO_REINDEX", True),
            search_timeout_ms=env_int("MEMORY_BRAIN_SEARCH_TIMEOUT_MS", 250),
            max_facts=env_int("MEMORY_BRAIN_MAX_FACTS", 6),
            max_hops=env_int("MEMORY_BRAIN_MAX_HOPS", 2),
            include_transcripts=env_bool("MEMORY_BRAIN_INCLUDE_TRANSCRIPTS", False),
            write_structured=env_bool("MEMORY_BRAIN_WRITE_STRUCTURED", True),
            debug=env_bool("MEMORY_BRAIN_DEBUG", False),
        )


def memory_brain_reindex(
    workspace: Path | None = None,
    memory_config: MemoryConfig | None = None,
    include_transcripts: bool | None = None,
) -> dict[str, Any]:
    root = workspace or Path.cwd()
    config = memory_config or MemoryConfig.from_env(root)
    brain_config = brain_config_for_memory(config)
    ensure_memory_workspace(config)
    brain_config.graph_dir.mkdir(parents=True, exist_ok=True)
    include = brain_config.include_transcripts if include_transcripts is None else include_transcripts
    built = build_memory_graph(config, include_transcripts=include)
    result = write_graph_index(
        brain_config.db_path,
        brain_config.graph_json_path,
        brain_config.entity_index_path,
        brain_config.conflicts_path,
        built["entities"],
        built["facts"],
        built["edges"],
        built["episodes"],
        built["conflicts"],
    )
    profile = write_profile_summary(brain_config.db_path, brain_config.profile_summary_path)
    if not brain_config.retrieval_cache_path.exists():
        brain_config.retrieval_cache_path.write_text('{"version": 1, "entries": []}\n', encoding="utf-8")
    result["profile_summary_path"] = profile["path"]
    result["retrieval_cache_path"] = str(brain_config.retrieval_cache_path.resolve())
    result["source_files"] = built.get("source_files", [])
    result["summary"] = (
        f"Memory Brain indexed {result['facts']} facts, {result['entities']} entities, "
        f"and {result['edges']} edges from TXT memory."
    )
    return result


def memory_brain_status(workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or Path.cwd()
    brain_config = MemoryBrainConfig.from_env(root)
    status = graph_status(brain_config.db_path, brain_config.graph_json_path, brain_config.conflicts_path)
    status.update(
        {
            "enabled": brain_config.enabled,
            "auto_reindex": brain_config.auto_reindex,
            "profile_summary_path": str(brain_config.profile_summary_path.resolve()),
            "profile_summary_exists": brain_config.profile_summary_path.exists(),
            "search_timeout_ms": brain_config.search_timeout_ms,
            "max_facts": brain_config.max_facts,
            "max_hops": brain_config.max_hops,
            "include_transcripts": brain_config.include_transcripts,
            "write_structured": brain_config.write_structured,
            "stale": graph_is_stale(root),
        }
    )
    return status


def graph_is_stale(workspace: Path | None = None) -> bool:
    root = workspace or Path.cwd()
    brain_config = MemoryBrainConfig.from_env(root)
    memory_config = MemoryConfig.from_env(root)
    return graph_is_stale_for_config(memory_config, brain_config)


def graph_is_stale_for_config(memory_config: MemoryConfig, brain_config: MemoryBrainConfig) -> bool:
    if not brain_config.db_path.exists():
        return True
    try:
        graph_mtime = brain_config.db_path.stat().st_mtime
    except OSError:
        return True
    for path in source_paths(memory_config, brain_config.include_transcripts):
        try:
            if path.stat().st_mtime > graph_mtime:
                return True
        except OSError:
            continue
    return False


def search_memory_brain(query: str, workspace: Path | None = None, **overrides: Any) -> dict[str, Any]:
    root = workspace or Path.cwd()
    brain_config = MemoryBrainConfig.from_env(root)
    options = MemorySearchOptions(
        max_facts=int(overrides.get("max_facts") or brain_config.max_facts),
        max_hops=int(overrides.get("max_hops") or brain_config.max_hops),
        timeout_ms=int(overrides.get("timeout_ms") or brain_config.search_timeout_ms),
    )
    return memory_brain_search(brain_config.db_path, query, options)


def load_memory_brain_context(
    user_text: str,
    memory_config: MemoryConfig,
    include_dynamic: bool = True,
) -> str:
    brain_config = brain_config_for_memory(memory_config)
    if not brain_config.enabled:
        return ""
    ensure_memory_workspace(memory_config)
    if brain_config.auto_reindex and brain_config.db_path.exists() and graph_is_stale_for_config(memory_config, brain_config):
        schedule_memory_brain_reindex(memory_config)
    parts: list[str] = []
    profile = read_profile_summary(brain_config.profile_summary_path)
    if profile:
        parts.append(compact_profile_context(profile))
    else:
        stable = stable_profile_from_txt(memory_config)
        if stable:
            parts.append(stable)
    if include_dynamic and user_text.strip() and brain_config.db_path.exists():
        from memory_retrieval import MemorySearchOptions
        from memory_retrieval import memory_brain_search as search_graph

        result = search_graph(
            brain_config.db_path,
            user_text,
            MemorySearchOptions(
                max_facts=brain_config.max_facts,
                max_hops=brain_config.max_hops,
                timeout_ms=brain_config.search_timeout_ms,
            ),
        )
        dynamic = memory_context_from_search(result, brain_config.max_facts)
        if dynamic:
            parts.append(dynamic)
    return "\n\n".join(part for part in parts if part.strip()).strip()


def brain_config_for_memory(memory_config: MemoryConfig) -> MemoryBrainConfig:
    config = MemoryBrainConfig.from_env(Path.cwd())
    try:
        same_root = memory_config.root.resolve() == config.root.resolve()
    except OSError:
        same_root = False
    if same_root:
        return config
    graph_dir = memory_config.root / "graph"
    return replace(
        config,
        root=memory_config.root,
        graph_dir=graph_dir,
        db_path=graph_dir / "memory.db",
        graph_json_path=graph_dir / "graph.json",
        entity_index_path=graph_dir / "entity_index.json",
        conflicts_path=graph_dir / "unresolved_conflicts.json",
        retrieval_cache_path=graph_dir / "retrieval_cache.json",
        profile_summary_path=graph_dir / "profile_summary.txt",
    )


def compact_profile_context(profile: str) -> str:
    lines = []
    for line in profile.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("Generated Profile Summary") or stripped.startswith("Updated:"):
            continue
        lines.append(stripped)
    if not lines:
        return ""
    return "Stable profile memory:\n" + "\n".join(lines[:10])


def stable_profile_from_txt(memory_config: MemoryConfig) -> str:
    user_path = memory_config.root / "user.txt"
    if not user_path.exists():
        return ""
    try:
        text = user_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    clean = text.strip()
    if not clean:
        return ""
    return "Stable profile memory:\n" + clean[-memory_config.max_file_chars :]


def memory_context_from_search(result: dict[str, Any], max_facts: int) -> str:
    facts = result.get("answer_relevant_facts", [])
    if not isinstance(facts, list) or not facts:
        return ""
    lines = ["Relevant memory:"]
    count = 0
    for item in facts:
        if not isinstance(item, dict):
            continue
        fact = item.get("fact")
        if not isinstance(fact, dict):
            continue
        fact_type = fact.get("type", "fact")
        source = fact.get("source_path", "memory")
        text = " ".join(str(fact.get("text", "")).split())
        if not text:
            continue
        lines.append(f"- [{fact_type}, source: memory/{source}] {text}")
        count += 1
        if count >= max_facts:
            break
    warnings = result.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("- Some matched memory may be stale or superseded; check source before treating it as current.")
    return "\n".join(lines)


def schedule_memory_brain_reindex(memory_config: MemoryConfig) -> None:
    if not brain_config_for_memory(memory_config).auto_reindex:
        return
    thread = threading.Thread(
        target=reindex_memory_brain_safely,
        args=(memory_config,),
        daemon=True,
        name="memory-brain-reindex",
    )
    thread.start()


def reindex_memory_brain_safely(memory_config: MemoryConfig) -> None:
    try:
        memory_brain_reindex(Path.cwd(), memory_config)
    except Exception:
        return


def graph_export(workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or Path.cwd()
    brain_config = MemoryBrainConfig.from_env(root)
    return graph_json_from_db(brain_config.db_path)


def project_memory_summary(project_query: str = "", workspace: Path | None = None, limit: int = 10) -> dict[str, Any]:
    root = workspace or Path.cwd()
    brain_config = MemoryBrainConfig.from_env(root)
    return project_summary(brain_config.db_path, project_query, limit=limit)


def env_int(name: str, fallback: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def env_bool(name: str, fallback: bool) -> bool:
    value = os.environ.get(name, "").strip().casefold()
    if not value:
        return fallback
    return value in {"1", "true", "yes", "on"}
