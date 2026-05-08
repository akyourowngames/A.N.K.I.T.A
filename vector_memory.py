from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from jarvis_nim import JarvisConfig, NimChatError
from memory_system import MemoryConfig, ensure_memory_workspace, is_relative_to, memory_files


EmbeddingFn = Callable[[list[str], str], list[list[float]]]


@dataclass(frozen=True)
class VectorMemoryConfig:
    root: Path
    index_path: Path
    model: str
    chunk_chars: int
    max_index_files: int
    max_index_chunks: int
    search_top_k: int
    min_score: float
    context_chars: int
    active: bool
    query_timeout_seconds: float
    include_transcripts: bool
    background_reindex: bool

    @classmethod
    def from_env(cls, workspace: Path) -> "VectorMemoryConfig":
        memory_root = Path(os.environ.get("JARVIS_MEMORY_DIR", str(workspace / "memory")))
        index_path = Path(os.environ.get("MEMORY_VECTOR_INDEX_PATH", str(memory_root / "vector" / "index.json")))
        return cls(
            root=memory_root,
            index_path=index_path,
            model=os.environ.get("NVIDIA_EMBEDDING_MODEL", "nvidia/nv-embedqa-e5-v5").strip()
            or "nvidia/nv-embedqa-e5-v5",
            chunk_chars=env_int("MEMORY_VECTOR_CHUNK_CHARS", 900),
            max_index_files=env_int("MEMORY_VECTOR_MAX_FILES", 200),
            max_index_chunks=env_int("MEMORY_VECTOR_MAX_CHUNKS", 600),
            search_top_k=env_int("MEMORY_VECTOR_TOP_K", 5),
            min_score=env_float("MEMORY_VECTOR_MIN_SCORE", 0.15),
            context_chars=env_int("MEMORY_VECTOR_CONTEXT_CHARS", 1600),
            active=env_bool("MEMORY_VECTOR_ACTIVE", False),
            query_timeout_seconds=env_float("MEMORY_VECTOR_QUERY_TIMEOUT_SECONDS", 2.5),
            include_transcripts=env_bool("MEMORY_VECTOR_INCLUDE_TRANSCRIPTS", False),
            background_reindex=env_bool("MEMORY_VECTOR_BACKGROUND_REINDEX", True),
        )


def env_int(name: str, fallback: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def env_float(name: str, fallback: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return float(value)
    except ValueError:
        return fallback


def env_bool(name: str, fallback: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return fallback
    return value in {"1", "true", "yes", "on"}


def embedding_url(config: JarvisConfig) -> str:
    base = config.chat_url
    suffix = "/chat/completions"
    if base.endswith(suffix):
        return base[: -len(suffix)] + "/embeddings"
    return base.rstrip("/") + "/embeddings"


def embed_texts(
    config: JarvisConfig,
    texts: list[str],
    input_type: str,
    timeout_seconds: float | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    payload = {
        "model": VectorMemoryConfig.from_env(Path.cwd()).model,
        "input": texts,
        "input_type": input_type,
    }
    request = urllib.request.Request(
        embedding_url(config),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds or config.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise NimChatError(f"NIM embedding request failed: {error.code} {error.reason}\n{detail}") from error
    except urllib.error.URLError as error:
        raise NimChatError(f"NIM embedding request failed: {error.reason}") from error
    except TimeoutError as error:
        raise NimChatError("NIM embedding request timed out.") from error

    rows = data.get("data", []) if isinstance(data, dict) else []
    embeddings: list[list[float]] = []
    for row in rows:
        embedding = row.get("embedding") if isinstance(row, dict) else None
        if not isinstance(embedding, list):
            continue
        values = [float(value) for value in embedding if isinstance(value, (int, float))]
        embeddings.append(values)
    if len(embeddings) != len(texts):
        raise NimChatError("NIM embedding response did not include every input.")
    return embeddings


def build_vector_index(
    memory_config: MemoryConfig,
    vector_config: VectorMemoryConfig,
    nim_config: JarvisConfig,
    embedder: EmbeddingFn | None = None,
) -> dict[str, Any]:
    ensure_memory_workspace(memory_config)
    previous = load_index(vector_config.index_path)
    previous_chunks = previous_chunks_by_id(previous)
    chunks = memory_chunks(memory_config, vector_config)
    indexed_chunks: list[dict[str, Any]] = []
    missing_texts: list[str] = []
    missing_refs: list[dict[str, Any]] = []
    for chunk in chunks:
        previous_chunk = previous_chunks.get(chunk["id"])
        if previous_chunk and isinstance(previous_chunk.get("embedding"), list):
            indexed_chunks.append({**chunk, "embedding": previous_chunk["embedding"]})
            continue
        missing_texts.append(chunk["text"])
        missing_refs.append(chunk)

    if missing_texts:
        embeddings = call_embedder(embedder, nim_config, missing_texts, "passage")
        for chunk, embedding in zip(missing_refs, embeddings):
            indexed_chunks.append({**chunk, "embedding": embedding})

    indexed_chunks.sort(key=lambda item: (str(item.get("path", "")), int(item.get("chunk_index", 0))))
    index = {
        "version": 1,
        "model": vector_config.model,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "chunk_count": len(indexed_chunks),
        "chunks": indexed_chunks,
    }
    vector_config.index_path.parent.mkdir(parents=True, exist_ok=True)
    vector_config.index_path.write_text(json.dumps(index, ensure_ascii=True, indent=2), encoding="utf-8")
    return {
        "indexed_files": len({chunk["path"] for chunk in indexed_chunks}),
        "indexed_chunks": len(indexed_chunks),
        "embedded_new_chunks": len(missing_refs),
        "model": vector_config.model,
        "index_path": str(vector_config.index_path.resolve()),
    }


def memory_chunks(memory_config: MemoryConfig, vector_config: VectorMemoryConfig) -> list[dict[str, Any]]:
    files = memory_files(memory_config.root, include_transcripts=vector_config.include_transcripts)
    chunks: list[dict[str, Any]] = []
    for path in files[: vector_config.max_index_files]:
        if is_relative_to(path, vector_config.index_path.parent):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(memory_config.root).as_posix()
        stat = path.stat()
        for index, chunk_text in enumerate(split_text_chunks(text, vector_config.chunk_chars)):
            item_hash = stable_hash(f"{relative}\n{index}\n{chunk_text}")
            chunks.append(
                {
                    "id": f"{relative}:{index}:{item_hash[:16]}",
                    "path": relative,
                    "chunk_index": index,
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                    "hash": item_hash,
                    "text": chunk_text,
                }
            )
            if len(chunks) >= vector_config.max_index_chunks:
                return chunks
    return chunks


def split_text_chunks(text: str, max_chars: int) -> list[str]:
    clean = text.strip()
    if not clean:
        return []
    paragraphs = split_paragraphs(clean)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(split_long_text(paragraph, max_chars))
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) > max_chars and current:
            chunks.append(current.strip())
            current = paragraph
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return chunks


def split_paragraphs(text: str) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip():
            current.append(line.strip())
            continue
        if current:
            paragraphs.append("\n".join(current))
            current = []
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs


def split_long_text(text: str, max_chars: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunks.append(text[start:end].strip())
        start = end
    return [chunk for chunk in chunks if chunk]


def vector_search(
    query: str,
    vector_config: VectorMemoryConfig,
    nim_config: JarvisConfig,
    embedder: EmbeddingFn | None = None,
) -> dict[str, Any]:
    index = load_index(vector_config.index_path)
    chunks = index.get("chunks", []) if isinstance(index, dict) else []
    if not isinstance(chunks, list) or not chunks:
        return {
            "query": query,
            "matches": [],
            "summary": "Vector memory index is empty. Run memory_vector_reindex first.",
        }
    query_embedding = call_embedder(embedder, nim_config, [query], "query", vector_config.query_timeout_seconds)[0]
    scored: list[dict[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        embedding = chunk.get("embedding")
        text = chunk.get("text")
        path = chunk.get("path")
        if not isinstance(embedding, list) or not isinstance(text, str) or not isinstance(path, str):
            continue
        score = cosine_similarity(query_embedding, embedding)
        if score < vector_config.min_score:
            continue
        scored.append(
            {
                "score": round(score, 6),
                "path": path,
                "chunk_index": chunk.get("chunk_index", 0),
                "text": text,
            }
        )
    scored.sort(key=lambda item: float(item["score"]), reverse=True)
    matches = scored[: vector_config.search_top_k]
    return {
        "query": query,
        "model": index.get("model", vector_config.model),
        "matches": matches,
        "summary": vector_summary(query, matches),
    }


def load_vector_memory_context(
    user_text: str,
    memory_config: MemoryConfig,
    vector_config: VectorMemoryConfig,
    nim_config: JarvisConfig,
) -> str:
    if not vector_config.active or not user_text.strip() or not vector_config.index_path.exists():
        return ""
    started = time.perf_counter()
    try:
        result = vector_search(user_text, vector_config, nim_config)
    except Exception:
        return ""
    if time.perf_counter() - started > vector_config.query_timeout_seconds + 0.5:
        return ""
    matches = result.get("matches")
    if not isinstance(matches, list) or not matches:
        return ""
    lines = ["Relevant vector memory:"]
    used = len(lines[0])
    for match in matches:
        if not isinstance(match, dict):
            continue
        text = str(match.get("text", "")).strip()
        path = str(match.get("path", "memory"))
        score = match.get("score", "")
        block = f"\nSource: {path} score={score}\n{text}\n"
        if used + len(block) > vector_config.context_chars:
            break
        lines.append(block.strip())
        used += len(block)
    return "\n\n".join(lines).strip()


def load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def call_embedder(
    embedder: EmbeddingFn | None,
    nim_config: JarvisConfig,
    texts: list[str],
    input_type: str,
    timeout_seconds: float | None = None,
) -> list[list[float]]:
    if embedder is not None:
        return embedder(texts, input_type)
    return embed_texts(nim_config, texts, input_type, timeout_seconds)


def previous_chunks_by_id(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    chunks = index.get("chunks", [])
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(chunks, list):
        return result
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        chunk_id = chunk.get("id")
        if isinstance(chunk_id, str):
            result[chunk_id] = chunk
    return result


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    count = min(len(left), len(right))
    if count == 0:
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for index in range(count):
        a = float(left[index])
        b = float(right[index])
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


def vector_summary(query: str, matches: list[dict[str, Any]]) -> str:
    if not matches:
        return f"No vector memory matches for {query}."
    lines = [f"Vector memory matches for {query}:"]
    for match in matches:
        text = " ".join(str(match.get("text", "")).split())
        lines.append(f"- {match.get('path')} score={match.get('score')}: {text[:220]}")
    return "\n".join(lines)
