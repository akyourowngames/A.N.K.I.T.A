from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SemanticManifestResult:
    tools: list[dict[str, Any]]
    best_score: float
    second_score: float
    used_semantic_ranking: bool


class SemanticToolManifest:
    def __init__(self, embedder: Any, *, limit: int, min_score: float) -> None:
        self.embedder = embedder
        self.limit = max(0, int(limit))
        self.min_score = max(0.0, float(min_score))

    def shortlist(self, user_message: str, tools: list[dict[str, Any]]) -> SemanticManifestResult:
        if not tools or self.limit <= 0 or self.embedder is None:
            return SemanticManifestResult(
                tools=tools,
                best_score=1.0 if tools else 0.0,
                second_score=0.0,
                used_semantic_ranking=False,
            )

        texts = [self._manifest_text(tool) for tool in tools]
        try:
            similarity_many = getattr(self.embedder, "similarity_many", None)
            if callable(similarity_many):
                scores = [float(score) for score in similarity_many(user_message, texts)]
            else:
                scores = [float(self.embedder.similarity(user_message, text)) for text in texts]
        except Exception:
            return SemanticManifestResult(tools=tools, best_score=1.0, second_score=0.0, used_semantic_ranking=False)

        ranked = sorted(zip(scores, tools, strict=False), key=lambda item: item[0], reverse=True)
        best_score = ranked[0][0] if ranked else 0.0
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        if best_score < self.min_score:
            return SemanticManifestResult(tools=[], best_score=best_score, second_score=second_score, used_semantic_ranking=True)
        selected = [tool for score, tool in ranked[: self.limit] if score >= self.min_score]
        return SemanticManifestResult(tools=selected, best_score=best_score, second_score=second_score, used_semantic_ranking=True)

    @staticmethod
    def _manifest_text(tool: dict[str, Any]) -> str:
        args = tool.get("args", {})
        arg_names = ", ".join(args.keys()) if isinstance(args, dict) else ""
        return "\n".join(
            [
                str(tool.get("name", "")),
                str(tool.get("description", "")),
                f"args: {arg_names}",
                f"safety: {tool.get('safety', '')}",
            ]
        )
