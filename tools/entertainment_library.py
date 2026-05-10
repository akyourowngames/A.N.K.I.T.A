from __future__ import annotations

from typing import Any

from tools.entertainment_agent import entertainment_library


def handle(params: dict[str, Any]) -> dict[str, Any]:
    return entertainment_library(params)
