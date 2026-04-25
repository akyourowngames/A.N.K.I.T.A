from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ToolResult:
    ok: bool
    summary: str
    data: dict[str, Any]
    error: str | None = None


class Tool(ABC):
    name: str
    description: str
    input_schema: dict[str, Any]
    safety: str = "read_only"
    public: bool = True

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        return args

    def render(self, data: dict[str, Any]) -> str:
        return data.get("summary", "") if isinstance(data, dict) else str(data)

    @abstractmethod
    def run(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

