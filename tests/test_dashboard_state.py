from __future__ import annotations

from api_server import compact_dashboard_state


def test_dashboard_uses_real_music_state_without_false_playing_claim() -> None:
    dashboard = compact_dashboard_state(
        {"ok": True, "assistant": "JARVIS", "model": "nim-model", "streaming": True, "tools": 12},
        {
            "library": {"total_tracks": 4},
            "queue_length": 1,
            "player_running": False,
            "current_track": {
                "title": "HASEEN",
                "artist": "Talwiinder",
                "source": "local",
                "duration_seconds": 175,
            },
            "player": {
                "summary": "Player playing. Current: HASEEN. Backend: vlc.",
                "player_running": False,
                "backend": "vlc",
                "volume": 70,
                "state": {
                    "playback_status": "playing",
                    "backend": "vlc",
                    "volume": 70,
                    "queue": ["track-1"],
                    "started_at": 1778656514,
                },
            },
        },
    )

    assert dashboard["assistant"]["model"] == "nim-model"
    assert dashboard["music"]["title"] == "HASEEN"
    assert dashboard["music"]["artist"] == "Talwiinder"
    assert dashboard["music"]["status"] == "Last played"
    assert dashboard["music"]["running"] is False
    assert dashboard["music"]["volume"] == 70
    assert dashboard["music"]["queue_length"] == 1


def test_dashboard_marks_active_track_when_player_is_running() -> None:
    dashboard = compact_dashboard_state(
        {"ok": True, "assistant": "JARVIS", "model": "nim-model", "streaming": False, "tools": 3},
        {
            "library": {"total_tracks": 8},
            "queue_length": 2,
            "player_running": True,
            "current_track": {"title": "Live Track", "artist": "Artist", "duration_seconds": 200},
            "player": {
                "player_running": True,
                "volume": 64,
                "state": {
                    "playback_status": "playing",
                    "backend": "vlc",
                    "started_at": 0,
                },
            },
        },
    )

    assert dashboard["music"]["status"] == "Playing"
    assert dashboard["music"]["running"] is True
    assert dashboard["music"]["progress_percent"] == 100
