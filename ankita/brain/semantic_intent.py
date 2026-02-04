import json
import os
from dataclasses import dataclass

import numpy as np

from brain.intent_registry import ALLOWED_INTENTS, validate_intent_result
from brain.text_normalizer import normalize_text


@dataclass(frozen=True)
class SemanticMatch:
    intent: str
    score: float


def _cosine_similarity_matrix(vec: np.ndarray, mat: np.ndarray) -> np.ndarray:
    """vec: [d], mat: [n, d]"""
    v = vec.reshape(1, -1)
    v_norm = np.linalg.norm(v, axis=1, keepdims=True) + 1e-12
    m_norm = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12
    v = v / v_norm
    m = mat / m_norm
    return (m @ v.T).reshape(-1)


class SemanticIntentMatcher:
    """Optional embedding-based intent classifier.

    Uses sentence-transformers when available. If not installed, matcher is disabled.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", threshold: float = 0.65):
        self.model_name = model_name
        self.threshold = float(threshold)
        self._enabled = False
        self._model = None
        self._intent_to_vectors: dict[str, np.ndarray] = {}

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(model_name)
            self._enabled = True
        except Exception:
            self._enabled = False

        self._load_examples()

    @property
    def enabled(self) -> bool:
        return bool(self._enabled)

    def _load_examples(self) -> None:
        intents_path = os.path.join(os.path.dirname(__file__), "intents.json")
        if not os.path.exists(intents_path):
            return

        try:
            with open(intents_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return

        # Only index intents that are whitelisted
        cleaned: dict[str, list[str]] = {}
        for intent, meta in (raw or {}).items():
            if intent not in ALLOWED_INTENTS:
                continue
            examples = meta.get("examples", []) if isinstance(meta, dict) else []
            if not isinstance(examples, list):
                continue
            ex = [normalize_text(x) for x in examples if isinstance(x, str) and x.strip()]
            if ex:
                cleaned[intent] = ex

        self._examples = cleaned

    def _ensure_index(self) -> None:
        if not self.enabled:
            return
        if self._intent_to_vectors:
            return

        # Build vectors once per process
        for intent, examples in self._examples.items():
            try:
                vecs = self._model.encode(examples, normalize_embeddings=True)
                self._intent_to_vectors[intent] = np.array(vecs, dtype=np.float32)
            except Exception:
                continue

    def match(self, text: str) -> SemanticMatch | None:
        if not self.enabled:
            return None

        self._ensure_index()
        if not self._intent_to_vectors:
            return None

        query = normalize_text(text)
        if not query:
            return None

        try:
            qv = self._model.encode([query], normalize_embeddings=True)
            qv = np.array(qv[0], dtype=np.float32)
        except Exception:
            return None

        best_intent: str | None = None
        best_score = 0.0

        for intent, mat in self._intent_to_vectors.items():
            if mat.size == 0:
                continue
            try:
                scores = _cosine_similarity_matrix(qv, mat)
                score = float(np.max(scores))
            except Exception:
                continue

            if score > best_score:
                best_score = score
                best_intent = intent

        if best_intent is None:
            return None

        if best_score < self.threshold:
            return None

        # Return intent only; entities are extracted deterministically later
        validated = validate_intent_result(best_intent, {})
        if validated["intent"] == "unknown":
            return None

        return SemanticMatch(intent=validated["intent"], score=best_score)


_matcher_singleton: SemanticIntentMatcher | None = None


def semantic_classify(text: str, threshold: float = 0.65) -> dict:
    """Convenience wrapper that returns the same shape as other classifiers."""
    global _matcher_singleton

    if _matcher_singleton is None or _matcher_singleton.threshold != float(threshold):
        _matcher_singleton = SemanticIntentMatcher(threshold=threshold)

    m = _matcher_singleton.match(text)
    if not m:
        return {"intent": "unknown", "entities": {}}

    print(f"[Semantic] Matched intent={m.intent} score={m.score:.3f}")
    return {"intent": m.intent, "entities": {}}


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]).strip() or "open chrome please"
    out = semantic_classify(q)
    print(out)
