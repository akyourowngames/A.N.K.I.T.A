from __future__ import annotations

import json
import base64
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jakata_agent.config import Settings
from jakata_agent.router import PlanDecision, PlanStep
from jakata_agent.web import SessionManager, create_app


class FakeTools:
    def execute(self, name: str, args: dict[str, object]):
        if name != "search_web":
            raise AssertionError(f"Unexpected tool call: {name}")
        query = str(args.get("query", "")).strip() or "default query"
        return SimpleNamespace(
            ok=True,
            summary=f"Search answer for {query}",
            data={
                "answer": f"Search answer for {query}",
                "results": [
                    {
                        "title": f"Source for {query}",
                        "url": "https://example.com/story",
                        "content": f"Fresh result for {query}",
                    }
                ],
            },
            error="",
        )


class FakeRuntime(SimpleNamespace):
    pass


class FakeAgent:
    def __init__(self, runtime: FakeRuntime) -> None:
        self.runtime = runtime
        self.history: list[str] = []

    def plan(self, user_message: str) -> PlanDecision:
        lowered = user_message.lower()
        if "direct answer" in lowered:
            return PlanDecision(
                steps=[PlanStep(tool="general_chat", args={}, reason="direct_answer")],
                direct_answer="direct response from router",
            )
        if "latest" in lowered or "news" in lowered or "who is" in lowered:
            return PlanDecision(
                steps=[
                    PlanStep(
                        tool="search_web",
                        args={"query": f"clean {user_message}", "topic": "general", "max_results": 3},
                        reason="Needs current web information.",
                    )
                ]
            )
        return PlanDecision(steps=[PlanStep(tool="general_chat", args={}, reason="Normal chat.")])

    def execute_steps(self, steps: list[PlanStep]) -> list[dict[str, object]]:
        del steps
        return []

    def stream_general_chat(self, user_message: str):
        self.history.append(user_message)
        if "long voice" in user_message.lower():
            yield "fake-model", (
                "This is a long spoken response with many details. "
                "It keeps going with setup steps, extra notes, verification details, and more explanation. "
                "This final sentence should stay on the screen instead of being fully read aloud."
            )
            return
        yield "fake-model", f"turn {len(self.history)}: {user_message}"

    def stream_tool_results_reply(self, user_message: str, tool_results: list[dict[str, object]]):
        self.history.append(user_message)
        summary = str(tool_results[0]["summary"])
        yield "fake-model", f"{summary} [turn {len(self.history)}]"

    def stream_direct_answer(self, user_message: str, content: str):
        self.history.append(user_message)
        yield "router:answer", content


def fake_runtime_factory(settings: Settings) -> FakeRuntime:
    return FakeRuntime(settings=settings, tools=FakeTools())


def fake_agent_builder(runtime: FakeRuntime) -> FakeAgent:
    return FakeAgent(runtime)


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        api_key="test-key",
        base_url="https://example.com/v1",
        primary_model="fake-model",
        fallback_models=["fallback-model"],
        vision_model="fake-vision",
        vision_fallback_models=[],
        embedding_model="fake-embed",
        session_id="default",
        data_dir=tmp_path,
        tavily_api_key="tavily-key",
        openweather_api_key="",
        chrome_path="",
        tesseract_cmd="",
        browser_backend="native",
        automation_backend="nvidia",
        automation_model="",
        browser_automation_model="",
        codex_cli_path="codex",
        workspace_dir=tmp_path,
        camera_device_index=0,
        camera_frame_width=640,
        camera_frame_height=480,
        telegram_bot_token="",
        telegram_admin_password="",
        telegram_admin_password_hash="",
        telegram_session_ttl_minutes=720,
        telegram_guest_daily_limit=50,
        telegram_max_upload_mb=45,
        telegram_safe_roots=[tmp_path],
        telegram_artifact_dir=tmp_path / "artifacts",
        telegram_upload_dir=tmp_path / "uploads",
        image_base_url="https://example.com/v1",
        image_model="fake-image-model",
        image_size="1024x1024",
        image_output_dir=tmp_path / "images",
        sarvam_api_key="sarvam-test-key",
        sarvam_tts_max_spoken_chars=95,
        sarvam_tts_long_response_phrases=["The rest of the chat is on screen, sir. You can check it out."],
    )


class FakeTTSClient:
    def stream(self, text: str):
        yield f"mp3:{text}".encode("utf-8")


def fake_tts_client_factory(settings: Settings) -> FakeTTSClient:
    assert settings.sarvam_api_key == "sarvam-test-key"
    return FakeTTSClient()


def build_client(tmp_path: Path) -> TestClient:
    settings = build_settings(tmp_path)
    session_manager = SessionManager(
        base_settings=settings,
        runtime_factory=fake_runtime_factory,
        agent_builder=fake_agent_builder,
    )
    app = create_app(
        base_settings=settings,
        session_manager=session_manager,
        tts_client_factory=fake_tts_client_factory,
    )
    return TestClient(app)


def parse_sse_payloads(body: str) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payloads.append(json.loads(line[6:]))
    return payloads


def test_frontend_assets_and_health(tmp_path: Path):
    client = build_client(tmp_path)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"

    index = client.get("/")
    assert index.status_code == 200
    assert "Ask Jarvis anything" in index.text
    assert 'rel="icon" href="data:,' in index.text

    style = client.get("/style.css")
    assert style.status_code == 200
    assert "--bg" in style.text

    script = client.get("/script.js")
    assert script.status_code == 200
    assert "/chat/jarvis/stream" in script.text

    orb = client.get("/orb.js")
    assert orb.status_code == 200
    assert "OrbRenderer" in orb.text

    audio = client.get("/app/audio/starter_1.mp3")
    assert audio.status_code == 404


def test_chat_stream_emits_session_and_done(tmp_path: Path):
    client = build_client(tmp_path)

    response = client.post("/chat/stream", json={"message": "hello there", "tts": False})
    assert response.status_code == 200

    payloads = parse_sse_payloads(response.text)
    assert payloads[0]["session_id"] == "default"
    assert payloads[0]["chunk"] == ""
    assert any(item.get("activity", {}).get("event") == "routing" for item in payloads if isinstance(item.get("activity"), dict))
    assert any(item.get("chunk") == "turn 1: hello there" for item in payloads)
    assert payloads[-1]["done"] is True


def test_chat_stream_emits_sarvam_audio_when_tts_enabled(tmp_path: Path):
    client = build_client(tmp_path)

    response = client.post("/chat/stream", json={"message": "hello there", "tts": True})
    assert response.status_code == 200

    payloads = parse_sse_payloads(response.text)
    audio_payload = next(item for item in payloads if "audio" in item)
    decoded = base64.b64decode(str(audio_payload["audio"]))
    assert decoded.startswith(b"mp3:turn 1: hello there")
    assert any(item.get("activity", {}).get("event") == "tts_ready" for item in payloads if isinstance(item.get("activity"), dict))


def test_long_tts_is_limited_and_points_to_screen(tmp_path: Path):
    client = build_client(tmp_path)

    response = client.post("/chat/stream", json={"message": "long voice please", "tts": True})
    assert response.status_code == 200

    payloads = parse_sse_payloads(response.text)
    decoded_audio = b" ".join(base64.b64decode(str(item["audio"])) for item in payloads if "audio" in item)
    assert b"The rest of the chat is on screen, sir" in decoded_audio
    assert b"final sentence should stay on the screen" not in decoded_audio
    assert any(item.get("activity", {}).get("event") == "tts_limited" for item in payloads if isinstance(item.get("activity"), dict))


def test_session_id_keeps_conversation_context(tmp_path: Path):
    client = build_client(tmp_path)

    first = parse_sse_payloads(client.post("/chat/stream", json={"message": "first turn"}).text)
    session_id = str(first[0]["session_id"])
    second = parse_sse_payloads(
        client.post("/chat/stream", json={"message": "second turn", "session_id": session_id}).text
    )

    assert any(item.get("chunk") == "turn 2: second turn" for item in second)


def test_web_stream_uses_router_direct_answer_without_second_chat(tmp_path: Path):
    client = build_client(tmp_path)

    payloads = parse_sse_payloads(client.post("/chat/stream", json={"message": "direct answer please"}).text)

    assert any(item.get("model") == "router:answer" and item.get("chunk") == "direct response from router" for item in payloads)


def test_realtime_and_jarvis_emit_search_results(tmp_path: Path):
    client = build_client(tmp_path)

    realtime = parse_sse_payloads(
        client.post("/chat/realtime/stream", json={"message": "latest nvidia news"}).text
    )
    assert any(item.get("activity", {}).get("event") == "searching_web" for item in realtime if isinstance(item.get("activity"), dict))
    realtime_search = next(item["search_results"] for item in realtime if "search_results" in item)
    assert realtime_search["query"] == "clean latest nvidia news"
    assert realtime[-1]["done"] is True

    jarvis = parse_sse_payloads(
        client.post("/chat/jarvis/stream", json={"message": "who is the CEO of Nvidia"}).text
    )
    decision = next(item["activity"] for item in jarvis if "activity" in item and item["activity"].get("event") == "decision")
    assert decision["query_type"] == "realtime"
    assert any("search_results" in item for item in jarvis)


if __name__ == "__main__":
    import tempfile

    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn(Path(tempfile.mkdtemp()))
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
