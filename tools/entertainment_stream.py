from __future__ import annotations

from typing import Any

from tools.entertainment_agent import entertainment_search, entertainment_stream_direct


def search(params: dict[str, Any]) -> dict[str, Any]:
    return entertainment_search(params)


def stream_direct(params: dict[str, Any]) -> dict[str, Any]:
    return entertainment_stream_direct(params)
