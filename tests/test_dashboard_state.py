from __future__ import annotations

from api_server import compact_dashboard_state


def test_dashboard_uses_health_state_without_agent_specific_claims() -> None:
    dashboard = compact_dashboard_state(
        {"ok": True, "assistant": "JARVIS", "model": "nim-model", "streaming": True, "tools": 12}
    )

    assert dashboard["ok"] is True
    assert dashboard["assistant"]["name"] == "JARVIS"
    assert dashboard["assistant"]["model"] == "nim-model"
    assert dashboard["assistant"]["streaming"] is True
    assert dashboard["assistant"]["tools"] == 12
