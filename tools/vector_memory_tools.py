from __future__ import annotations

from pathlib import Path
from typing import Any

from jarvis_nim import JarvisConfig, load_dotenv
from memory_system import MemoryConfig
from vector_memory import VectorMemoryConfig, build_vector_index, load_index, vector_search

from .registry import optional_text, require_text


def memory_vector_status(params: dict[str, Any]) -> dict[str, Any]:
    config = VectorMemoryConfig.from_env(Path.cwd())
    index = load_index(config.index_path)
    chunks = index.get("chunks", []) if isinstance(index, dict) else []
    chunk_count = len(chunks) if isinstance(chunks, list) else 0
    return {
        "index_path": str(config.index_path.resolve()),
        "exists": config.index_path.exists(),
        "model": index.get("model", config.model) if isinstance(index, dict) else config.model,
        "chunk_count": chunk_count,
        "active": config.active,
        "summary": f"Vector memory index has {chunk_count} chunks at {config.index_path.resolve()}.",
    }


def memory_vector_reindex(params: dict[str, Any]) -> dict[str, Any]:
    load_dotenv(Path.cwd() / ".env")
    memory_config = MemoryConfig.from_env(Path.cwd())
    vector_config = VectorMemoryConfig.from_env(Path.cwd())
    nim_config = JarvisConfig.from_env()
    result = build_vector_index(memory_config, vector_config, nim_config)
    result["summary"] = (
        f"Vector memory indexed {result['indexed_chunks']} chunks from "
        f"{result['indexed_files']} files using {result['model']}."
    )
    return result


def memory_vector_search(params: dict[str, Any]) -> dict[str, Any]:
    load_dotenv(Path.cwd() / ".env")
    query = require_text(params, "query")
    vector_config = VectorMemoryConfig.from_env(Path.cwd())
    top_k_raw = params.get("top_k")
    if top_k_raw is not None:
        try:
            top_k = int(top_k_raw)
        except (TypeError, ValueError):
            top_k = vector_config.search_top_k
        vector_config = VectorMemoryConfig(
            root=vector_config.root,
            index_path=vector_config.index_path,
            model=vector_config.model,
            chunk_chars=vector_config.chunk_chars,
            max_index_files=vector_config.max_index_files,
            max_index_chunks=vector_config.max_index_chunks,
            search_top_k=max(1, min(20, top_k)),
            min_score=vector_config.min_score,
            context_chars=vector_config.context_chars,
            active=vector_config.active,
            query_timeout_seconds=vector_config.query_timeout_seconds,
            include_transcripts=vector_config.include_transcripts,
            background_reindex=vector_config.background_reindex,
        )
    nim_config = JarvisConfig.from_env()
    return vector_search(query, vector_config, nim_config)
