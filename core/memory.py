from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
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


class EmbeddingModel:
    def __init__(
        self,
        model_name: str | None = None,
        dimensions: int = 384,
        use_sentence_transformers: bool | None = None,
    ) -> None:
        self.model_name = model_name or os.getenv("MEMORY_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.dimensions = dimensions
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
            with urllib.request.urlopen(request, timeout=20) as response:
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


STOPWORDS = {
    "a",
    "an",
    "and",
    "about",
    "am",
    "are",
    "do",
    "does",
    "i",
    "is",
    "me",
    "my",
    "of",
    "the",
    "to",
    "what",
    "who",
}


def normalized_tokens(text: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[a-zA-Z0-9_]+", text.lower()):
        if token in STOPWORDS:
            continue
        if len(token) > 3 and token.endswith("s"):
            token = token[:-1]
        tokens.add(token)
    return tokens


def token_score(query: str, text: str) -> float:
    query_tokens = normalized_tokens(query)
    text_tokens = normalized_tokens(text)
    if not query_tokens or not text_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / len(query_tokens)


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
        for file_path in sorted([*self.data_dir.glob("*.txt"), *self.data_dir.glob("*.md")]):
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
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM memories WHERE kind = 'user_data' AND source LIKE ?",
                (f"{source}#%",),
            )

    def remember_from_user_text(self, user_text: str) -> int:
        memories = list(extract_durable_memories(user_text))
        for memory in memories:
            self.add(memory, source="chat_extracted", kind="chat_fact")
        return len(memories)

    def cleanup(self) -> int:
        removed = 0
        updated = 0
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, text FROM memories WHERE kind = 'chat_fact'"
            ).fetchall()
            for row in rows:
                normalized = normalize_memory_text(row["text"])
                if not normalized:
                    connection.execute("DELETE FROM memories WHERE id = ?", (row["id"],))
                    removed += 1
                elif normalized != row["text"]:
                    connection.execute(
                        "UPDATE memories SET text = ?, updated_at = ? WHERE id = ?",
                        (normalized, utc_now(), row["id"]),
                    )
                    updated += 1
        return removed + updated

    def search(self, query: str, top_k: int = 6) -> list[MemoryHit]:
        mode = os.getenv("MEMORY_SEARCH_MODE", "hybrid").strip().lower()
        lexical_hits = self.keyword_search(query, top_k=top_k)
        if mode in {"fast", "keyword", "lexical"}:
            return lexical_hits

        if mode == "hybrid" and lexical_hits and lexical_hits[0].score >= 0.25:
            return lexical_hits

        return self.semantic_search(query, top_k=top_k)

    def keyword_search(self, query: str, top_k: int = 6) -> list[MemoryHit]:
        hits: list[MemoryHit] = []

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT text, source, kind FROM memories"
            ).fetchall()

        for row in rows:
            score = token_score(query, row["text"])
            if score > 0:
                hits.append(
                    MemoryHit(
                        text=row["text"],
                        source=row["source"],
                        kind=row["kind"],
                        score=score,
                    )
                )

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    def semantic_search(self, query: str, top_k: int = 6) -> list[MemoryHit]:
        query_vector = self._cached_query_embedding(query)
        hits: list[MemoryHit] = []

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT text, source, kind, embedding, embedding_key FROM memories"
            ).fetchall()

        for row in rows:
            if row["embedding_key"] != self.embedding_model.cache_key:
                continue
            embedding = json.loads(row["embedding"])
            score = cosine_similarity(query_vector, embedding)
            hits.append(
                MemoryHit(
                    text=row["text"],
                    source=row["source"],
                    kind=row["kind"],
                    score=score,
                )
            )

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return [hit for hit in hits[:top_k] if hit.score > -1]

    def _cached_query_embedding(self, query: str) -> list[float]:
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

    def context_for(self, query: str, top_k: int | None = None) -> str:
        self.ingest_data_files()
        limit = top_k or int(os.getenv("MEMORY_TOP_K", "6"))
        profile = self.profile_context()
        hits = self.search(query, top_k=limit)
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

    def profile_context(self) -> list[str]:
        pinned: list[str] = []
        for file_path in sorted([*self.data_dir.glob("*.txt"), *self.data_dir.glob("*.md")]):
            text = file_path.read_text(encoding="utf-8").strip()
            for line in text.splitlines():
                key, value = parse_key_value_line(line)
                if key and value:
                    pinned.append(f"{key}: {value}")
        return pinned[:20]

    def profile_value(self, key_name: str) -> str | None:
        wanted = key_name.strip().lower()
        for file_path in sorted([*self.data_dir.glob("*.txt"), *self.data_dir.glob("*.md")]):
            for line in file_path.read_text(encoding="utf-8").splitlines():
                key, value = parse_key_value_line(line)
                if key.lower() == wanted and value:
                    return value
        return None


def parse_key_value_line(line: str) -> tuple[str, str]:
    clean = line.strip()
    if not clean or ":" not in clean:
        return "", ""
    key, value = clean.split(":", 1)
    return key.strip(), value.strip()


def normalize_memory_text(text: str) -> str:
    clean = " ".join(text.strip().split()).strip(" .")
    if not clean:
        return ""

    lowered = clean.lower()
    transient_states = {
        "i am good",
        "i'm good",
        "i am fine",
        "i'm fine",
        "i am ok",
        "i'm ok",
        "i am okay",
        "i'm okay",
        "i am tired",
        "i'm tired",
        "i am sad",
        "i'm sad",
        "i am happy",
        "i'm happy",
        "i am bored",
        "i'm bored",
        "i am busy",
        "i'm busy",
        "i am hungry",
        "i'm hungry",
    }
    if lowered in transient_states:
        return ""

    patterns = [
        (r"^my name is\s+(.+)$", "Name: {value}"),
        (r"^call me\s+(.+)$", "Preferred name: {value}"),
        (r"^i live in\s+(.+)$", "Location: {value}"),
        (r"^i work as\s+(.+)$", "Work: {value}"),
        (r"^i prefer\s+(.+)$", "Preference: {value}"),
        (r"^i like\s+(.+?)\s+in\s+food$", "Favorite food: {value}"),
        (r"^i love\s+(.+?)\s+in\s+food$", "Favorite food: {value}"),
        (r"^i like\s+(.+)$", "Likes: {value}"),
        (r"^i love\s+(.+)$", "Likes: {value}"),
    ]
    for pattern, template in patterns:
        match = re.match(pattern, clean, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .")
            if value:
                return template.format(value=value)

    return clean


def extract_durable_memories(user_text: str) -> Iterable[str]:
    text = user_text.strip()
    lowered = text.lower()

    remember_match = re.search(r"\bremember(?: that)?\s+(.+)", text, flags=re.IGNORECASE)
    if remember_match:
        normalized = normalize_memory_text(remember_match.group(1).strip(" ."))
        if normalized:
            yield normalized
        return

    durable_starts = (
        "my name is ",
        "i live in ",
        "i work as ",
        "i like ",
        "i love ",
        "i prefer ",
        "call me ",
    )
    if lowered.startswith(durable_starts):
        normalized = normalize_memory_text(text)
        if normalized:
            yield normalized
        return

    identity_starts = ("i am ", "i'm ")
    transient_states = {
        "good",
        "fine",
        "ok",
        "okay",
        "tired",
        "sad",
        "happy",
        "bored",
        "busy",
        "hungry",
    }
    for prefix in identity_starts:
        if lowered.startswith(prefix):
            remainder = lowered.removeprefix(prefix).strip(" .!")
            if remainder and remainder not in transient_states and len(remainder.split()) > 1:
                normalized = normalize_memory_text(text)
                if normalized:
                    yield normalized
            return
