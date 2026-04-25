from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from jakata_agent.agent import JakataAgent
from jakata_agent.plan_validator import PlanValidator
from jakata_agent.router import IntentRouter
from jakata_agent.tasks.store import TaskStore
from jakata_agent.tools.datetime_tool import DateTimeTool
from jakata_agent.tools.registry import ToolRegistry


class RouterAnswerClient:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.router_calls = 0
        self.chat_calls = 0
        self.last_user_prompt = ""

    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
        del system_prompt, temperature
        self.last_user_prompt = user_prompt
        self.router_calls += 1
        return "router-model", self.raw

    def complete(self, messages, temperature: float = 0.7):
        del messages, temperature
        self.chat_calls += 1
        return "chat-model", "chat fallback"

    def stream_complete(self, messages, temperature: float = 0.7):
        del messages, temperature
        yield "chat-model", "chat fallback"


class DummyMemory:
    def __init__(self, context: str = "") -> None:
        self.messages = []
        self.context = context
        self.knowledge_chunks = []
        self.store = SimpleNamespace(recent=lambda limit=10: [])

    def load_session_messages(self):
        return []

    def bootstrap_system_note(self):
        return "Memory empty."

    def persist_turn(self, messages):
        self.messages = list(messages)

    def learn_from_user_message(self, user_message: str):
        del user_message

    def retrieve(self, query: str):
        del query
        return SimpleNamespace(
            to_system_context=lambda: self.context,
            permanent_memories=[],
            knowledge_chunks=[],
            archived_chat_chunks=[],
        )

    def graph_search(self, query: str):
        del query
        return {"nodes": [], "edges": []}

    def remember_task_event(self, *args, **kwargs):
        return None


def build_agent(tmp_path: Path, client: RouterAnswerClient, tools: ToolRegistry, memory_context: str = "") -> JakataAgent:
    settings = SimpleNamespace(
        session_id="test",
        workspace_dir=tmp_path,
        data_dir=tmp_path / "data",
        approval_policy="auto_safe",
    )
    return JakataAgent(
        settings=settings,
        client=client,
        tools=tools,
        memory=DummyMemory(memory_context),
        router=IntentRouter(client),
        validator=PlanValidator(),
        task_store=TaskStore(tmp_path / "jakata.db"),
        daemon=SimpleNamespace(ensure_running=lambda: None),
        task_engine=None,
    )


def test_router_direct_answer_returns_without_second_chat_call(tmp_path: Path):
    client = RouterAnswerClient('{"answer":"normal chat answered by router"}')
    agent = build_agent(tmp_path, client, ToolRegistry())

    model, content = agent.reply("normal message")

    assert model == "router:answer"
    assert content == "normal chat answered by router"
    assert client.router_calls == 1
    assert client.chat_calls == 0


def test_router_direct_answer_receives_memory_context(tmp_path: Path):
    client = RouterAnswerClient('{"answer":"Your name is krish."}')
    agent = build_agent(tmp_path, client, ToolRegistry(), memory_context="Knowledge files:\n- user name is krish")

    model, content = agent.reply("whats my name")

    assert model == "router:answer"
    assert content == "Your name is krish."
    assert "user name is krish" in client.last_user_prompt
    assert client.chat_calls == 0


def test_simple_tool_plan_executes_directly_without_chat_synthesis(tmp_path: Path):
    client = RouterAnswerClient('{"steps":[{"tool":"datetime","args":{"include_utc":false},"reason":"live time"}]}')
    tools = ToolRegistry()
    tools.register(DateTimeTool())
    agent = build_agent(tmp_path, client, tools)

    model, content = agent.reply("time please")

    assert model == "local:tool"
    assert "Local time is" in content
    assert client.router_calls == 1
    assert client.chat_calls == 0
