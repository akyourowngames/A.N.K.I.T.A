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

    @abstractmethod
    def run(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

