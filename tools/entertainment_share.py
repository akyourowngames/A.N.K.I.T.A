from __future__ import annotations

from typing import Any

from tools.entertainment_agent import entertainment_share


def handle(params: dict[str, Any]) -> dict[str, Any]:
    return entertainment_share(params)
