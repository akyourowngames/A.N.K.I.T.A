import logging
from typing import List

from app.services.nvidia_client import NvidiaClient
from config import (
    NVIDIA_API_KEY,
    NVIDIA_BASE_URL,
    NVIDIA_EMBEDDING_BATCH_SIZE,
    NVIDIA_EMBEDDING_DIMENSIONS,
    NVIDIA_EMBEDDING_MODEL,
    NVIDIA_EMBEDDING_TYPE,
)

logger = logging.getLogger("J.A.R.V.I.S")


class NvidiaEmbeddings:
    def __init__(self):
        if not NVIDIA_API_KEY:
            raise ValueError("No NVIDIA_API_KEY configured. Set NVIDIA_API_KEY in .env")

        self.model = NVIDIA_EMBEDDING_MODEL
        self.batch_size = NVIDIA_EMBEDDING_BATCH_SIZE
        self.client = NvidiaClient(NVIDIA_API_KEY, NVIDIA_BASE_URL, timeout=60)
        logger.info("[VECTOR] NVIDIA embeddings initialized (%s)", self.model)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        vectors: List[List[float]] = []

        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            vectors.extend(self._embed(batch, input_type="passage"))

        return vectors

    def embed_query(self, text: str) -> List[float]:
        vectors = self._embed([text], input_type="query")
        return vectors[0] if vectors else []

    def _embed(self, texts: List[str], input_type: str) -> List[List[float]]:
        return self.client.embeddings(
            model=self.model,
            inputs=texts,
            input_type=input_type,
            embedding_type=NVIDIA_EMBEDDING_TYPE,
            dimensions=NVIDIA_EMBEDDING_DIMENSIONS,
        )
