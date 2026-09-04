from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import string
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def chunk_text(text: str, max_chars: int = 900) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if not current:
            current = paragraph
        elif len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


TERM_TRANSLATION = str.maketrans({character: " " for character in string.punctuation})
CHAT_INDEX_VERSION = "chat-turns-v3"


def text_terms(text: str) -> set[str]:
    return {
        term
        for term in text.lower().translate(TERM_TRANSLATION).split()
        if len(term) > 1 and not term.isdigit()
    }


def term_weight_map(documents: Iterable[set[str]]) -> dict[str, float]:
    document_terms = list(documents)
    if not document_terms:
        return {}
    frequencies: dict[str, int] = {}
    for terms in document_terms:
        for term in terms:
            frequencies[term] = frequencies.get(term, 0) + 1
    total = len(document_terms)
    return {
        term: math.log((total + 1) / (frequency + 1)) + 1.0
        for term, frequency in frequencies.items()
    }


def text_rank_score(query_terms: set[str], memory_terms: set[str], weights: dict[str, float] | None = None) -> float:
    if not query_terms or not memory_terms:
        return 0.0
    overlap = query_terms.intersection(memory_terms)
    if not overlap:
        return 0.0
    novel_terms = memory_terms.difference(query_terms)
    score = sum((weights or {}).get(term, 1.0) for term in overlap) + min(len(novel_terms), 8) * 0.05
    if not novel_terms:
        score -= 1.0
    return max(score, 0.0)


def merge_ranked_hits(rankings: list[list[MemoryHit]], top_k: int, weights: list[float] | None = None) -> list[MemoryHit]:
    combined: dict[tuple[str, str, str], MemoryHit] = {}
    scores: dict[tuple[str, str, str], float] = {}
    rank_weights = weights or [1.0] * len(rankings)
    for ranking_index, ranking in enumerate(rankings):
        weight = rank_weights[ranking_index] if ranking_index < len(rank_weights) else 1.0
        for rank, hit in enumerate(ranking):
            key = (hit.kind, hit.source, hit.text)
            combined[key] = hit
            scores[key] = scores.get(key, 0.0) + weight / (rank + 1)

    hits = [
        MemoryHit(text=hit.text, source=hit.source, kind=hit.kind, score=scores[key])
        for key, hit in combined.items()
    ]
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return select_diverse_hits(hits, top_k)


def term_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))


def select_diverse_hits(hits: list[MemoryHit], top_k: int) -> list[MemoryHit]:
    if top_k <= 0:
        return []
    selected: list[MemoryHit] = []
    deferred: list[MemoryHit] = []
    selected_terms: list[set[str]] = []
    threshold = float(os.getenv("MEMORY_DIVERSITY_SIMILARITY", "0.82"))

    for hit in hits:
        terms = text_terms(hit.text)
        if not selected_terms or all(term_similarity(terms, existing) < threshold for existing in selected_terms):
            selected.append(hit)
            selected_terms.append(terms)
        else:
            deferred.append(hit)
        if len(selected) >= top_k:
            return selected[:top_k]

    selected.extend(deferred)
    return selected[:top_k]


class EmbeddingModel:
    def __init__(
        self,
        model_name: str | None = None,
        dimensions: int = 384,
        use_sentence_transformers: bool | None = None,
    ) -> None:
        self.model_name = model_name or os.getenv("MEMORY_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.dimensions = int(os.getenv("MEMORY_EMBEDDING_DIMENSIONS", str(dimensions)))
        self.backend = "hash"
        self._model = None
        backend = os.getenv("MEMORY_BACKEND", "fast").strip().lower()
        self.requested_backend = backend
        self._cache: dict[tuple[str, str], list[float]] = {}
        self.use_sentence_transformers = (
            backend in {"semantic", "minilm", "sentence-transformers"}
            if use_sentence_transformers is None
            else use_sentence_transformers
        )

    def _load_model(self) -> None:
        if self._model is None and self.use_sentence_transformers:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.model_name)
                self.backend = "sentence-transformers"
            except Exception:
                self._model = None

    def embed(self, text: str) -> list[float]:
        return self.embed_document(text)

    def embed_document(self, text: str) -> list[float]:
        return self._embed(text, input_type="passage")

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text, input_type="query")

    @property
    def cache_key(self) -> str:
        return f"{self.requested_backend}:{self.model_name}:{self.dimensions}"

    def _embed(self, text: str, input_type: str) -> list[float]:
        clean = " ".join(text.split())
        key = (input_type, clean)
        if key in self._cache:
            return self._cache[key]

        if self.requested_backend in {"nvidia", "nv"}:
            try:
                vector = self._nvidia_embed(clean, input_type=input_type)
                self.backend = "nvidia"
                self._cache[key] = vector
                return vector
            except Exception:
                if os.getenv("MEMORY_ALLOW_HASH_FALLBACK", "false").strip().lower() not in {"1", "true", "yes", "on"}:
                    raise
                self.backend = "hash"

        self._load_model()
        if self._model is not None:
            vector = self._model.encode(text, normalize_embeddings=True)
            result = [float(value) for value in vector]
            self._cache[key] = result
            return result

        result = self._hash_embed(text)
        self._cache[key] = result
        return result

    def _nvidia_embed(self, text: str, input_type: str) -> list[float]:
        api_key = os.getenv("NVIDIA_API_KEY", "").strip()
        base_url = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
        if not api_key:
            raise ValueError("Missing NVIDIA_API_KEY for NVIDIA memory embeddings.")

        payload = {
            "model": self.model_name,
            "input": [text],
            "input_type": input_type,
            "dimensions": self.dimensions,
        }
        request = urllib.request.Request(
            f"{base_url}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            timeout = int(os.getenv("MEMORY_EMBEDDING_TIMEOUT_SECONDS", "5"))
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"NVIDIA embedding failed: {error.code} {details}") from error
        vector = body["data"][0]["embedding"]
        norm = math.sqrt(sum(float(value) * float(value) for value in vector)) or 1.0
        return [float(value) / norm for value in vector]

    def _hash_embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


@dataclass(frozen=True)
class MemoryHit:
    text: str
    source: str
    kind: str
    score: float


class PermanentMemory:
    def __init__(self, memory_root: Path, embedding_model: EmbeddingModel | None = None) -> None:
        self.root = memory_root
        self.chats_dir = memory_root / "chats"
        self.data_dir = memory_root / "data"
        self.store_dir = memory_root / "store"
        self.db_path = self.store_dir / "memory.sqlite"
        self.embedding_model = embedding_model or EmbeddingModel()
        self._embedding_lock = threading.RLock()
        self._background_lock = threading.Lock()
        self._index_thread: threading.Thread | None = None
        self._warming_queries: set[str] = set()

        for folder in (self.root, self.chats_dir, self.data_dir, self.store_dir):
            folder.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(kind, source_hash)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_sources (
                    source TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    embedding_key TEXT NOT NULL DEFAULT '',
                    indexed_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    cache_key TEXT PRIMARY KEY,
                    embedding TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(connection, "memories", "embedding_key", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "memory_sources", "embedding_key", "TEXT NOT NULL DEFAULT ''")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind)"
            )

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = [row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def add(self, text: str, source: str, kind: str = "fact") -> None:
        clean = normalize_memory_text(text)
        if not clean:
            return

        source_hash = hashlib.sha256(f"{kind}:{source}:{clean}".encode("utf-8")).hexdigest()
        with self._embedding_lock:
            embedding = json.dumps(self.embedding_model.embed_document(clean))
        embedding_key = self.embedding_model.cache_key
        now = utc_now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memories (kind, source, source_hash, text, embedding, embedding_key, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kind, source_hash) DO UPDATE SET
                    text = excluded.text,
                    embedding = excluded.embedding,
                    embedding_key = excluded.embedding_key,
                    updated_at = excluded.updated_at
                """,
                (kind, source, source_hash, clean, embedding, embedding_key, now, now),
            )

    def ingest_data_files(self) -> int:
        count = 0
        for file_path in self._memory_data_files():
            text = file_path.read_text(encoding="utf-8").strip()
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if self._source_is_current(file_path.name, content_hash):
                continue

            self._delete_file_memories(file_path.name)
            for index, chunk in enumerate(chunk_text(text)):
                self.add(chunk, source=f"{file_path.name}#{index}", kind="user_data")
                count += 1
            self._mark_source_current(file_path.name, content_hash)
        return count

    def ingest_chat_files(self) -> int:
        count = 0
        for file_path in self._chat_files():
            chunks = chat_file_transcript_chunks(file_path)
            transcript = "\n\n".join(chunks)
            content_hash = hashlib.sha256(f"{CHAT_INDEX_VERSION}\n{transcript}".encode("utf-8")).hexdigest()
            source = f"chat:{file_path.name}"
            if self._source_is_current(source, content_hash):
                continue

            self._delete_source_memories("chat_session", source)
            for index, chunk in enumerate(chunks):
                self.add(chunk, source=f"{source}#{index}", kind="chat_session")
                count += 1
            self._mark_source_current(source, content_hash)
        return count

    def refresh_index(self) -> int:
        return self.ingest_data_files() + self.ingest_chat_files()

    def refresh_index_async(self) -> int:
        if not self._async_enabled():
            return self.refresh_index()
        with self._background_lock:
            if self._index_thread is not None and self._index_thread.is_alive():
                return 0
            self._index_thread = threading.Thread(target=self._refresh_index_quietly, daemon=True)
            self._index_thread.start()
        return 0

    def _refresh_index_quietly(self) -> None:
        try:
            self.refresh_index()
        except Exception:
            return

    def _source_is_current(self, source: str, content_hash: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash, embedding_key FROM memory_sources WHERE source = ?",
                (source,),
            ).fetchone()
        return bool(
            row
            and row["content_hash"] == content_hash
            and row["embedding_key"] == self.embedding_model.cache_key
        )

    def _mark_source_current(self, source: str, content_hash: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_sources (source, content_hash, embedding_key, indexed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    embedding_key = excluded.embedding_key,
                    indexed_at = excluded.indexed_at
                """,
                (source, content_hash, self.embedding_model.cache_key, utc_now()),
            )

    def _delete_file_memories(self, source: str) -> None:
        self._delete_source_memories("user_data", source)

    def _delete_source_memories(self, kind: str, source: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM memories WHERE kind = ? AND source LIKE ?",
                (kind, f"{source}#%"),
            )

    def remember_from_user_text(self, user_text: str) -> int:
        memories = list(extract_durable_memories(user_text))
        for memory in memories:
            self.add(memory, source="chat_extracted", kind="chat_fact")
        return len(memories)

    def remember_from_user_text_async(self, user_text: str) -> int:
        return self.remember_from_user_text(user_text)

    def cleanup(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM memories WHERE kind = 'chat_fact'")
            return cursor.rowcount if cursor.rowcount is not None else 0

    def search(self, query: str, top_k: int = 6) -> list[MemoryHit]:
        mode = os.getenv("MEMORY_SEARCH_MODE", "hybrid").strip().lower()
        if mode in {"off", "none"}:
            return []
        if mode in {"fast", "lexical"}:
            return self.lexical_search(query, top_k=top_k)
        if self._low_latency_enabled():
            lexical_hits = self.lexical_search(query, top_k=top_k)
            if len(lexical_hits) >= min(top_k, self._low_latency_min_text_hits()):
                return lexical_hits
            query_vector = self._cached_query_embedding(query, compute=False)
            if query_vector is not None:
                semantic_hits = self._semantic_search_with_vector(query_vector, top_k=top_k, query=query)
                return merge_ranked_hits([semantic_hits, lexical_hits], top_k=top_k, weights=[1.0, 1.25])
            self._warm_query_embedding_async(query)
            return lexical_hits
        return self.semantic_search(query, top_k=top_k)

    def semantic_search(self, query: str, top_k: int = 6) -> list[MemoryHit]:
        query_vector = self._cached_query_embedding(query)
        return self._semantic_search_with_vector(query_vector, top_k=top_k, query=query)

    def _semantic_search_with_vector(self, query_vector: list[float], top_k: int = 6, query: str = "") -> list[MemoryHit]:
        query_terms = text_terms(query)
        hits: list[MemoryHit] = []

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT text, source, kind, embedding, embedding_key FROM memories"
            ).fetchall()
        row_terms = [text_terms(row["text"]) for row in rows]
        weights = term_weight_map([query_terms, *row_terms])

        for row, memory_terms in zip(rows, row_terms):
            if row["embedding_key"] != self.embedding_model.cache_key:
                continue
            embedding = json.loads(row["embedding"])
            score = cosine_similarity(query_vector, embedding) + text_rank_score(query_terms, memory_terms, weights) * 0.08
            hits.append(
                MemoryHit(
                    text=row["text"],
                    source=row["source"],
                    kind=row["kind"],
                    score=score,
                )
            )

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return select_diverse_hits([hit for hit in hits if hit.score > -1], top_k)

    def lexical_search(self, query: str, top_k: int = 6) -> list[MemoryHit]:
        query_terms = text_terms(query)
        if not query_terms:
            return []
        hits: list[MemoryHit] = []

        with self._connect() as connection:
            rows = connection.execute("SELECT text, source, kind FROM memories").fetchall()
        row_terms = [text_terms(row["text"]) for row in rows]
        weights = term_weight_map([query_terms, *row_terms])

        for row, memory_terms in zip(rows, row_terms):
            score = text_rank_score(query_terms, memory_terms, weights)
            if score <= 0:
                continue
            hits.append(
                MemoryHit(
                    text=row["text"],
                    source=row["source"],
                    kind=row["kind"],
                    score=score,
                )
            )

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return select_diverse_hits(hits, top_k)

    def _cached_query_embedding(self, query: str, *, compute: bool = True) -> list[float] | None:
        clean = " ".join(query.split())
        digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()
        cache_key = f"{self.embedding_model.cache_key}:query:{digest}"

        with self._connect() as connection:
            row = connection.execute(
                "SELECT embedding FROM embedding_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row:
                return json.loads(row["embedding"])

        if not compute:
            return None

        with self._embedding_lock:
            embedding = self.embedding_model.embed_query(clean)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO embedding_cache (cache_key, embedding, created_at)
                VALUES (?, ?, ?)
                """,
                (cache_key, json.dumps(embedding), utc_now()),
            )
        return embedding

    def _warm_query_embedding_async(self, query: str) -> None:
        clean = " ".join(query.split())
        if not clean:
            return
        digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()
        with self._background_lock:
            if digest in self._warming_queries:
                return
            self._warming_queries.add(digest)
        threading.Thread(target=self._warm_query_embedding_quietly, args=(query, digest), daemon=True).start()

    def _warm_query_embedding_quietly(self, query: str, digest: str) -> None:
        try:
            self._cached_query_embedding(query)
        except Exception:
            pass
        finally:
            with self._background_lock:
                self._warming_queries.discard(digest)

    def context_for(self, query: str, top_k: int | None = None) -> str:
        limit = top_k or int(os.getenv("MEMORY_TOP_K", "6"))
        profile = self.profile_context()
        fresh_hits = self._fresh_data_file_hits(query, top_k=limit)
        self.refresh_index_async()
        hits = self.search(query, top_k=limit)
        if fresh_hits:
            hits = merge_ranked_hits([fresh_hits, hits], top_k=limit, weights=[1.35, 1.0])
        if not hits and not profile:
            return "No relevant permanent memories found."

        lines = []
        if profile:
            lines.extend(profile)
            if hits:
                lines.append("")
        for hit in hits:
            if hit.text not in lines:
                lines.append(hit.text)
        return "\n".join(lines)

    def _fresh_data_file_hits(self, query: str, top_k: int = 6) -> list[MemoryHit]:
        query_terms = text_terms(query)
        if not query_terms or top_k <= 0:
            return []

        max_bytes = int(os.getenv("MEMORY_FRESH_FILE_MAX_BYTES", "262144"))
        max_files = int(os.getenv("MEMORY_FRESH_FILE_MAX_FILES", "24"))
        max_chunks_per_file = int(os.getenv("MEMORY_FRESH_FILE_MAX_CHUNKS", "16"))
        candidates: list[tuple[str, str, str, set[str]]] = []

        for file_path in self._memory_data_files()[:max_files]:
            try:
                if max_bytes > 0 and file_path.stat().st_size > max_bytes:
                    continue
                text = file_path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeDecodeError):
                continue
            if not text:
                continue

            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if self._source_is_current(file_path.name, content_hash):
                continue

            for index, chunk in enumerate(chunk_text(text)[:max_chunks_per_file]):
                ranking_terms = text_terms(f"{file_path.name} {chunk}")
                candidates.append((chunk, f"{file_path.name}#fresh:{index}", "user_data", ranking_terms))

        if not candidates:
            return []

        weights = term_weight_map([query_terms, *[candidate[3] for candidate in candidates]])
        hits: list[MemoryHit] = []
        for text, source, kind, memory_terms in candidates:
            score = text_rank_score(query_terms, memory_terms, weights)
            if score <= 0:
                continue
            hits.append(MemoryHit(text=text, source=source, kind=kind, score=score))

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return select_diverse_hits(hits, top_k)

    def profile_context(self) -> list[str]:
        pinned: list[str] = []
        for file_path in self._memory_data_files():
            text = file_path.read_text(encoding="utf-8").strip()
            for line in text.splitlines():
                key, value = parse_key_value_line(line)
                if key and value:
                    pinned.append(f"{key}: {value}")
        return pinned[:20]

    def profile_value(self, key_name: str) -> str | None:
        wanted = key_name.strip().lower()
        for file_path in self._memory_data_files():
            for line in file_path.read_text(encoding="utf-8").splitlines():
                key, value = parse_key_value_line(line)
                if key.lower() == wanted and value:
                    return value
        return None

    def _memory_data_files(self) -> list[Path]:
        return [
            file_path
            for file_path in sorted([*self.data_dir.glob("*.txt"), *self.data_dir.glob("*.md")])
            if file_path.stem.lower() != "readme"
        ]

    def _chat_files(self) -> list[Path]:
        return sorted(self.chats_dir.glob("*.jsonl"))

    @staticmethod
    def _async_enabled() -> bool:
        return os.getenv("MEMORY_WRITE_ASYNC", "false").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _low_latency_enabled() -> bool:
        value = os.getenv("MEMORY_LOW_LATENCY", os.getenv("MEMORY_WRITE_ASYNC", "false"))
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _low_latency_min_text_hits() -> int:
        return max(1, int(os.getenv("MEMORY_LOW_LATENCY_MIN_TEXT_HITS", "3")))


def chat_file_transcript(file_path: Path) -> str:
    return "\n\n".join(chat_file_transcript_chunks(file_path))


def chat_file_transcript_chunks(file_path: Path) -> list[str]:
    lines: list[str] = []
    if not file_path.exists():
        return []

    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        speaker = str(record.get("speaker") or "").strip()
        text = " ".join(str(record.get("text") or "").split())
        if not speaker or not text:
            continue
        lines.extend(chunk_text(f"{speaker}: {text}"))

    return lines


def parse_key_value_line(line: str) -> tuple[str, str]:
    clean = line.strip()
    if not clean or ":" not in clean:
        return "", ""
    key, value = clean.split(":", 1)
    return key.strip(), value.strip()


def normalize_memory_text(text: str) -> str:
    clean = " ".join(text.strip().split()).strip(" .")
    return clean


def extract_durable_memories(user_text: str) -> Iterable[str]:
    return ()
