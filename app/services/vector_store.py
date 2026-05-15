import json
import logging
import math
import os
import time
from dataclasses import dataclass
from typing import List, Optional

from app.services.nvidia_embeddings import NvidiaEmbeddings
from app.services.latency_optimizer import latency_optimizer
from config import (
    CHATS_DATA_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    LEARNING_DATA_DIR,
    VECTOR_INDEX_CHAT_HISTORY,
    VECTOR_STORE_DIR,
    VECTOR_STORE_CACHE_ENABLED,
)

logger = logging.getLogger("J.A.R.V.I.S")

VECTOR_STORE_CACHE_PATH = VECTOR_STORE_DIR / "vector_cache.json"
VECTOR_STORE_METADATA_PATH = VECTOR_STORE_DIR / "vector_metadata.json"


@dataclass
class Document:
    page_content: str
    metadata: dict


class SimpleRetriever:
    def __init__(self, store: "SimpleVectorStore", k: int):
        self.store = store
        self.k = k

    def invoke(self, query: str) -> List[Document]:
        return self.store.search(query, self.k)


class SimpleVectorStore:
    def __init__(self, embeddings: NvidiaEmbeddings):
        self.embeddings = embeddings
        self.documents: List[Document] = []
        self.vectors: List[List[float]] = []

    def build(self, documents: List[Document]):
        self.documents = documents
        if not documents:
            self.vectors = []
            return

        vectors = self.embeddings.embed_documents([doc.page_content for doc in documents])
        self.vectors = [self._normalize(vector) for vector in vectors]

    def as_retriever(self, search_kwargs: Optional[dict] = None) -> SimpleRetriever:
        k = int((search_kwargs or {}).get("k", 10))
        return SimpleRetriever(self, k)

    def search(self, query: str, k: int) -> List[Document]:
        if not self.documents or not self.vectors:
            return []

        query_vector = self._normalize(self.embeddings.embed_query(query))
        if not query_vector:
            return []

        scored = []
        for index, vector in enumerate(self.vectors):
            scored.append((self._dot(query_vector, vector), index))
        scored.sort(reverse=True)
        return [self.documents[index] for _, index in scored[:k]]

    def _normalize(self, vector: List[float]) -> List[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        if not norm:
            return []
        return [value / norm for value in vector]

    def _dot(self, left: List[float], right: List[float]) -> float:
        return sum(a * b for a, b in zip(left, right))


class VectorStoreService:
    def __init__(self):
        self.embeddings = NvidiaEmbeddings()
        self.vector_store = SimpleVectorStore(self.embeddings)
        self._has_context_documents = False
        self._retriever_cache: dict = {}
        self._query_cache: dict = {}
        self._max_query_cache = 200
        self._last_build_time = 0.0
        self._source_file_hashes: dict = {}

    def _compute_source_hash(self) -> str:
        """Compute a hash of all source files to detect changes."""
        import hashlib
        hasher = hashlib.md5()

        for file_path in sorted(LEARNING_DATA_DIR.glob("*.txt")):
            try:
                content = file_path.read_bytes()
                hasher.update(content)
                hasher.update(str(file_path.stat().st_mtime).encode())
            except Exception:
                pass

        if VECTOR_INDEX_CHAT_HISTORY:
            for file_path in sorted(CHATS_DATA_DIR.glob("*.json")):
                try:
                    content = file_path.read_bytes()
                    hasher.update(content)
                    hasher.update(str(file_path.stat().st_mtime).encode())
                except Exception:
                    pass

        return hasher.hexdigest()

    def _load_cache_if_valid(self) -> bool:
        """Load vector store from cache if source files haven't changed."""
        if not VECTOR_STORE_CACHE_ENABLED:
            return False

        if not VECTOR_STORE_CACHE_PATH.exists() or not VECTOR_STORE_METADATA_PATH.exists():
            return False

        try:
            with open(VECTOR_STORE_METADATA_PATH, "r") as f:
                metadata = json.load(f)

            current_hash = self._compute_source_hash()
            if metadata.get("source_hash") != current_hash:
                logger.info("[VECTOR] Source files changed, cache invalid")
                return False

            with open(VECTOR_STORE_CACHE_PATH, "r") as f:
                cache_data = json.load(f)

            documents = []
            vectors = []

            for item in cache_data.get("entries", []):
                doc = Document(
                    page_content=item["page_content"],
                    metadata=item["metadata"]
                )
                documents.append(doc)
                vectors.append(item["vector"])

            self.vector_store.documents = documents
            self.vector_store.vectors = vectors
            self._has_context_documents = bool(documents)
            self._last_build_time = time.time()

            logger.info("[VECTOR] Loaded %d vectors from cache", len(documents))
            return True

        except Exception as e:
            logger.warning("[VECTOR] Cache load failed: %s", e)
            return False

    def _save_cache(self):
        """Save vector store to disk for faster subsequent loads."""
        if not VECTOR_STORE_CACHE_ENABLED:
            return

        try:
            entries = []
            for doc, vec in zip(self.vector_store.documents, self.vector_store.vectors):
                entries.append({
                    "page_content": doc.page_content,
                    "metadata": doc.metadata,
                    "vector": vec,
                })

            cache_data = {"entries": entries}
            with open(VECTOR_STORE_CACHE_PATH, "w") as f:
                json.dump(cache_data, f)

            metadata = {
                "source_hash": self._compute_source_hash(),
                "num_documents": len(entries),
                "timestamp": time.time(),
            }
            with open(VECTOR_STORE_METADATA_PATH, "w") as f:
                json.dump(metadata, f)

            logger.info("[VECTOR] Saved %d vectors to cache", len(entries))

        except Exception as e:
            logger.warning("[VECTOR] Cache save failed: %s", e)

    def load_learning_data(self) -> List[Document]:
        documents = []

        for file_path in sorted(LEARNING_DATA_DIR.glob("*.txt")):
            try:
                content = file_path.read_text(encoding="utf-8").strip()
                if content:
                    documents.append(Document(page_content=content, metadata={"source": str(file_path.name)}))
                    logger.info("[VECTOR] Loaded learning data: %s (%d chars)", file_path.name, len(content))
            except Exception as e:
                logger.warning("Could not load learning data file %s: %s", file_path, e)

        logger.info("[VECTOR] Total learning data files loaded: %d", len(documents))
        return documents

    def load_chat_history(self) -> List[Document]:
        documents = []

        for file_path in sorted(CHATS_DATA_DIR.glob("*.json")):
            try:
                chat_data = json.loads(file_path.read_text(encoding="utf-8"))
                messages = chat_data.get("messages", [])
                if not isinstance(messages, list):
                    continue

                lines = []
                for msg in messages:
                    if not isinstance(msg, dict):
                        continue

                    role = msg.get("role") or "assistant"
                    content = msg.get("content") or ""
                    prefix = "User: " if role == "user" else "Assistant: "
                    lines.append(prefix + content)

                chat_content = "\n".join(lines)
                if chat_content.strip():
                    documents.append(Document(page_content=chat_content, metadata={"source": f"chat_{file_path.stem}"}))
                    logger.info("[VECTOR] Loaded chat history: %s (%d messages)", file_path.name, len(messages))
            except Exception as e:
                logger.warning("Could not load chat history file %s: %s", file_path, e)

        logger.info("[VECTOR] Total chat history files loaded: %d", len(documents))
        return documents

    def create_vector_store(self) -> SimpleVectorStore:
        if self._load_cache_if_valid():
            return self.vector_store

        t0 = time.perf_counter()
        learning_docs = self.load_learning_data()
        chat_docs = self.load_chat_history() if VECTOR_INDEX_CHAT_HISTORY else []
        all_documents = learning_docs + chat_docs
        self._has_context_documents = bool(all_documents)
        logger.info(
            "[VECTOR] Total documents to index: %d (learning: %d, chat: %d)",
            len(all_documents),
            len(learning_docs),
            len(chat_docs),
        )

        chunks = self._split_documents(all_documents)
        if chunks:
            logger.info("[VECTOR] Split into %d chunks (chunk_size=%d, overlap=%d)", len(chunks), CHUNK_SIZE, CHUNK_OVERLAP)
        else:
            logger.info("[VECTOR] No documents found, using empty in-memory index")

        self.vector_store.build(chunks)
        self._retriever_cache.clear()
        self._last_build_time = time.time()

        build_time = time.perf_counter() - t0
        latency_optimizer.record("vector_store_build", build_time * 1000)
        logger.info("[VECTOR] Simple NVIDIA embedding index ready with %d vectors (%.2fs)", len(self.vector_store.vectors), build_time)

        self._save_cache()
        return self.vector_store

    def load_or_create_vector_store(self) -> SimpleVectorStore:
        return self.create_vector_store()

    def has_context_documents(self) -> bool:
        return self._has_context_documents

    def save_vector_store(self):
        self._save_cache()

    def get_retriever(self, k: int = 10):
        if not self.vector_store:
            raise RuntimeError("Vector store not initialized. This should not happen.")

        if k not in self._retriever_cache:
            self._retriever_cache[k] = self.vector_store.as_retriever(search_kwargs={"k": k})
        return self._retriever_cache[k]

    def search_cached(self, query: str, k: int = 5) -> List[Document]:
        """Search with query caching for repeated queries."""
        cache_key = f"{query.lower().strip()}|{k}"

        if cache_key in self._query_cache:
            logger.debug("[VECTOR] Cache hit for query: %.50s", query[:50])
            return self._query_cache[cache_key]

        retriever = self.get_retriever(k=k)
        results = retriever.invoke(query)

        if len(self._query_cache) >= self._max_query_cache:
            oldest_key = next(iter(self._query_cache))
            del self._query_cache[oldest_key]

        self._query_cache[cache_key] = results
        return results

    def _split_documents(self, documents: List[Document]) -> List[Document]:
        chunks = []
        step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)

        for document in documents:
            text = document.page_content
            if len(text) <= CHUNK_SIZE:
                chunks.append(document)
                continue

            start = 0
            chunk_index = 0
            while start < len(text):
                chunk_text = text[start:start + CHUNK_SIZE].strip()
                if chunk_text:
                    metadata = dict(document.metadata)
                    metadata["chunk"] = chunk_index
                    chunks.append(Document(page_content=chunk_text, metadata=metadata))
                    chunk_index += 1
                start += step

        return chunks
