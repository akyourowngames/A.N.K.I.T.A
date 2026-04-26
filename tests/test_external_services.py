from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from jakata_agent.agent import JakataAgent
from jakata_agent.plan_validator import PlanValidator
from jakata_agent.router import IntentRouter
from jakata_agent.services.google_workspace import GoogleServiceStatus
from jakata_agent.services.sync_store import ExternalServiceStore, ServiceItem
from jakata_agent.tasks.store import TaskStore
from jakata_agent.tools.external_services import (
    CalendarUpcomingTool,
    ExternalServicesStatusTool,
    GmailCreateDraftTool,
    GmailSearchTool,
    GmailUnreadTool,
)
from jakata_agent.tools.registry import ToolRegistry


class RouterClient:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.router_calls = 0

    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
        del system_prompt, user_prompt, temperature
        self.router_calls += 1
        return "router-model", self.raw

    def complete(self, messages, temperature: float = 0.7):
        del messages, temperature
        return "chat-model", "chat fallback"

    def stream_complete(self, messages, temperature: float = 0.7):
        del messages, temperature
        yield "chat-model", "chat fallback"


class DummyMemory:
    def __init__(self) -> None:
        self.messages = []
        self.embedder = None
        self.knowledge_chunks = []
        self.store = SimpleNamespace(recent=lambda limit=10: [])

    def bootstrap_system_note(self):
        return "Memory empty."

    def persist_turn(self, messages):
        self.messages = list(messages)

    def learn_from_user_message(self, user_message: str):
        del user_message

    def retrieve(self, query: str):
        del query
        return SimpleNamespace(
            to_system_context=lambda: "",
            permanent_memories=[],
            knowledge_chunks=[],
            archived_chat_chunks=[],
        )

    def graph_search(self, query: str):
        del query
        return {"nodes": [], "edges": []}

    def remember_task_event(self, *args, **kwargs):
        del args, kwargs


class FakeGoogle:
    def __init__(self) -> None:
        self.created_drafts: list[dict] = []

    def status(self) -> GoogleServiceStatus:
        return GoogleServiceStatus(
            configured=True,
            authorized=True,
            credentials_path="credentials.json",
            token_path="token.json",
            message="Google Workspace token is available.",
        )

    def authorize(self, *, interactive: bool = False) -> GoogleServiceStatus:
        del interactive
        return self.status()

    def upcoming_range(self, *, days: int):
        start = datetime(2026, 4, 26, 9, 0, tzinfo=timezone.utc)
        return start, start + timedelta(days=days)

    def today_range(self):
        start = datetime(2026, 4, 26, 0, 0, tzinfo=timezone.utc)
        return start, start + timedelta(days=1)

    def list_calendar_events(self, *, time_min, time_max, max_results: int = 10, calendar_id: str = "primary"):
        del time_min, time_max, max_results, calendar_id
        return [
            ServiceItem(
                provider="google",
                item_type="calendar_event",
                external_id="evt-1",
                title="Math class",
                text="Chapter revision",
                start_at="2026-04-26T10:00:00+00:00",
                end_at="2026-04-26T11:00:00+00:00",
                url="https://calendar.google.com/event?eid=evt-1",
            )
        ]

    def search_gmail(self, *, query: str, max_results: int = 10):
        del max_results
        return [
            ServiceItem(
                provider="google",
                item_type="gmail_message",
                external_id="msg-1",
                title="Exam notes - teacher@example.com",
                text=f"Matched query: {query}",
                start_at="Sun, 26 Apr 2026 09:00:00 +0000",
                url="https://mail.google.com/mail/u/0/#all/msg-1",
                labels=["UNREAD"],
            )
        ]

    def unread_gmail(self, *, max_results: int = 10):
        del max_results
        return self.search_gmail(query="is:unread")

    def create_gmail_draft(self, *, to: str, subject: str, body: str, thread_id: str = ""):
        draft = {"id": "draft-1", "to": to, "subject": subject, "body": body, "thread_id": thread_id}
        self.created_drafts.append(draft)
        return draft


def build_agent(tmp_path: Path, client: RouterClient, tools: ToolRegistry) -> JakataAgent:
    settings = SimpleNamespace(
        session_id="test",
        workspace_dir=tmp_path,
        data_dir=tmp_path / "data",
        approval_policy="auto_safe",
        router_tool_limit=0,
        router_min_tool_score=0.0,
    )
    return JakataAgent(
        settings=settings,
        client=client,
        tools=tools,
        memory=DummyMemory(),
        router=IntentRouter(client),
        validator=PlanValidator(),
        task_store=TaskStore(tmp_path / "jakata.db"),
        task_engine=None,
    )


def service_tools(tmp_path: Path, google: FakeGoogle) -> tuple[ToolRegistry, ExternalServiceStore]:
    store = ExternalServiceStore(tmp_path / "external_services.db")
    tools = ToolRegistry()
    tools.register(ExternalServicesStatusTool(google=google, store=store))
    tools.register(CalendarUpcomingTool(google=google, store=store))
    tools.register(GmailUnreadTool(google=google, store=store))
    tools.register(GmailSearchTool(google=google, store=store))
    tools.register(GmailCreateDraftTool(google=google))
    return tools, store


def test_external_service_store_upserts_and_queries(tmp_path: Path):
    store = ExternalServiceStore(tmp_path / "services.db")

    count = store.upsert_many(
        [
            ServiceItem(
                provider="google",
                item_type="calendar_event",
                external_id="evt-1",
                title="Chemistry exam",
                text="Bring notes",
                start_at="2026-04-27T08:00:00+00:00",
            )
        ]
    )
    rows = store.query(provider="google", item_type="calendar_event", text_query="Chemistry")

    assert count == 1
    assert rows[0]["title"] == "Chemistry exam"
    assert store.counts() == {"google:calendar_event": 1}


def test_agent_reads_google_calendar_through_real_tool_path(tmp_path: Path):
    google = FakeGoogle()
    tools, store = service_tools(tmp_path, google)
    client = RouterClient('{"steps":[{"tool":"calendar_upcoming","args":{"days":3},"reason":"check calendar"}]}')
    agent = build_agent(tmp_path, client, tools)

    model, content = agent.reply("what is on my calendar soon")

    assert model == "local:tool"
    assert "Math class" in content
    assert store.counts() == {"google:calendar_event": 1}
    assert client.router_calls == 1


def test_agent_searches_gmail_through_real_tool_path(tmp_path: Path):
    google = FakeGoogle()
    tools, store = service_tools(tmp_path, google)
    client = RouterClient('{"steps":[{"tool":"gmail_search","args":{"query":"from:teacher"},"reason":"search mail"}]}')
    agent = build_agent(tmp_path, client, tools)

    model, content = agent.reply("find teacher emails")

    assert model == "local:tool"
    assert "Exam notes" in content
    assert store.counts() == {"google:gmail_message": 1}


def test_gmail_draft_requires_explicit_confirmation(tmp_path: Path):
    google = FakeGoogle()
    tools, _store = service_tools(tmp_path, google)
    result = tools.execute(
        "gmail_create_draft",
        {"to": "teacher@example.com", "subject": "Question", "body": "Can you explain this?"},
    )

    assert not result.ok
    assert result.error == "confirmation_required"
    assert google.created_drafts == []
