from __future__ import annotations

import math
from typing import Iterable

from openai import OpenAI


class SemanticEmbedder:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self._cache: dict[str, list[float]] = {}

    def embed(self, text: str) -> list[float]:
        key = " ".join(text.strip().split())
        if not key:
            return []
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        response = self.client.embeddings.create(model=self.model, input=[key])
        vector = list(response.data[0].embedding)
        self._cache[key] = vector
        return vector

    def similarity(self, a: str, b: str) -> float:
        va = self.embed(a)
        vb = self.embed(b)
        if not va or not vb:
            return 0.0
        return cosine_similarity(va, vb)


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
