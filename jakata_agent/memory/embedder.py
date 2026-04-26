from __future__ import annotations

import math
from typing import Iterable

from openai import OpenAI


class SemanticEmbedder:
    def __init__(self, api_key: str, base_url: str, model: str, timeout_seconds: float = 8.0) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds, max_retries=0)
        self._cache: dict[str, list[float]] = {}

    def embed(self, text: str, input_type: str = "passage") -> list[float]:
        key = " ".join(text.strip().split())
        if not key:
            return []
        cache_key = f"{input_type}:{key}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        response = self.client.embeddings.create(model=self.model, input=[key], extra_body={"input_type": input_type})
        vector = list(response.data[0].embedding)
        self._cache[cache_key] = vector
        return vector

    def embed_many(self, texts: list[str], input_type: str = "passage") -> list[list[float]]:
        normalized = [" ".join(text.strip().split()) for text in texts]
        vectors: list[list[float]] = [[] for _ in normalized]
        missing: list[str] = []
        missing_indexes: list[int] = []
        for index, key in enumerate(normalized):
            if not key:
                continue
            cache_key = f"{input_type}:{key}"
            cached = self._cache.get(cache_key)
            if cached is not None:
                vectors[index] = cached
                continue
            missing.append(key)
            missing_indexes.append(index)

        if missing:
            response = self.client.embeddings.create(model=self.model, input=missing, extra_body={"input_type": input_type})
            for index, item in zip(missing_indexes, response.data, strict=False):
                vector = list(item.embedding)
                vectors[index] = vector
                self._cache[f"{input_type}:{normalized[index]}"] = vector
        return vectors

    def similarity(self, a: str, b: str) -> float:
        va = self.embed(a, input_type="query")
        vb = self.embed(b, input_type="passage")
        if not va or not vb:
            return 0.0
        return cosine_similarity(va, vb)

    def similarity_many(self, query: str, texts: list[str]) -> list[float]:
        query_vector = self.embed(query, input_type="query")
        text_vectors = self.embed_many(texts, input_type="passage")
        if not query_vector:
            return [0.0 for _ in texts]
        return [cosine_similarity(query_vector, vector) if vector else 0.0 for vector in text_vectors]


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    a_list = list(a)
    b_list = list(b)
    if not a_list or not b_list or len(a_list) != len(b_list):
        return 0.0
    dot = sum(x * y for x, y in zip(a_list, b_list))
    norm_a = math.sqrt(sum(x * x for x in a_list))
    norm_b = math.sqrt(sum(y * y for y in b_list))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
