from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from jakata_agent.companion import CompanionStore, ProactiveCompanionEngine
from jakata_agent.config import Settings
from jakata_agent.web import SessionManager, create_app


class FakeStarterClient:
    def __init__(self, text: str | None = None) -> None:
        self.text = text or (
            '{"text":"Quick one, bud. Omnitrix or Iron Man suit if you had to build your future around one?",'
            '"category":"fun_power_choice","reason":"fun companion opener","score":0.91}'
        )
        self.calls = 0

    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.7):
        assert "Return only valid JSON" in system_prompt
        assert "Recent companion feedback" in user_prompt
        self.calls += 1
        return "fake-companion-model", self.text


class FakeMemory:
    def __init__(self) -> None:
        self.persisted = []

    def persist_turn(self, messages):
        self.persisted.append(list(messages))


class FakeAgent:
    def __init__(self) -> None:
        self.messages = []
        self.memory = FakeMemory()

    def _conversation_context(self, max_messages: int = 8, max_chars: int = 2400):
        del max_messages, max_chars
        return "user: I like anime powers and big questions."

    def _retrieve_memory_context(self, query: str, max_chars: int = 2500):
        del query, max_chars
        return "Krish likes supportive, fun, thoughtful companion talk."


class FakeRuntime(SimpleNamespace):
    pass


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        api_key="test-key",
        base_url="https://example.com/v1",
        primary_model="fake-model",
        fallback_models=[],
        vision_model="fake-vision",
        vision_fallback_models=[],
        embedding_model="fake-embed",
        session_id="default",
        data_dir=tmp_path,
        tavily_api_key="",
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
    )


def test_companion_engine_records_message_and_feedback(tmp_path: Path):
    store = CompanionStore(tmp_path / "companion.db")
    client = FakeStarterClient()
    engine = ProactiveCompanionEngine(client=client, store=store, min_interval_seconds=300)

    decision = engine.next_message(
        session_id="default",
        conversation_context="user likes impossible choices",
        memory_context="",
        force=True,
    )
    feedback = store.record_feedback(
        session_id="default",
        message_id=decision.message_id,
        signal="more_like_this",
        user_reply="Omnitrix obviously",
    )

    assert decision.should_speak
    assert "Omnitrix" in decision.text
    assert feedback["signal"] == "more_like_this"
    assert "more_like_this" in store.feedback_summary("default")


def test_companion_frequency_and_stop_feedback(tmp_path: Path):
    store = CompanionStore(tmp_path / "companion.db")
    engine = ProactiveCompanionEngine(client=FakeStarterClient(), store=store, min_interval_seconds=300)

    first = engine.next_message(session_id="default", conversation_context="", force=False)
    second = engine.next_message(session_id="default", conversation_context="", force=False)
    store.record_feedback(session_id="default", message_id=first.message_id, signal="stop")
    third = engine.next_message(session_id="default", conversation_context="", force=False)

    assert first.should_speak
    assert not second.should_speak
    assert second.skipped_reason == "too_soon"
    assert not third.should_speak
    assert third.skipped_reason == "disabled"


def test_web_companion_endpoint_uses_runtime_and_persists_feedback(tmp_path: Path):
    settings = build_settings(tmp_path)
    store = CompanionStore(tmp_path / "companion.db")
    engine = ProactiveCompanionEngine(client=FakeStarterClient(), store=store)
    fake_agent = FakeAgent()

    def runtime_factory(session_settings: Settings):
        return FakeRuntime(settings=session_settings, companion_store=store, companion_engine=engine)

    def agent_builder(runtime):
        del runtime
        return fake_agent

    manager = SessionManager(
        base_settings=settings,
        runtime_factory=runtime_factory,
        agent_builder=agent_builder,
    )
    app = create_app(base_settings=settings, session_manager=manager)
    client = TestClient(app)

    response = client.post(
        "/companion/next",
        json={"session_id": "browser", "force": True, "idle_seconds": 99, "page_visible": True},
    )
    payload = response.json()
    feedback = client.post(
        "/companion/feedback",
        json={"session_id": "browser", "message_id": payload["message_id"], "signal": "reply", "user_reply": "Omnitrix"},
    )

    assert response.status_code == 200
    assert payload["should_speak"] is True
    assert "Omnitrix" in payload["text"]
    assert feedback.status_code == 200
    assert feedback.json()["signal"] == "reply"
    assert fake_agent.memory.persisted
