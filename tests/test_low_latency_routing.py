from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from jakata_agent.agent import JakataAgent
from jakata_agent.plan_validator import PlanValidator
from jakata_agent.router import IntentRouter
from jakata_agent.tasks.store import TaskStore
from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.datetime_tool import DateTimeTool
from jakata_agent.tools.image_generation import ImageGenerationTool
from jakata_agent.tools.registry import ToolRegistry


class RouterAnswerClient:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.router_calls = 0
        self.chat_calls = 0
        self.last_user_prompt = ""
        self.last_chat_messages = []

    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
        del system_prompt, temperature
        self.last_user_prompt = user_prompt
        self.router_calls += 1
        return "router-model", self.raw

    def complete(self, messages, temperature: float = 0.7):
        del temperature
        self.last_chat_messages = list(messages)
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


class ProducePathTool(Tool):
    name = "produce_path"
    description = "produce a path"
    input_schema = {"type": "object", "properties": {}, "required": []}

    def run(self, args):
        del args
        return ToolResult(ok=True, summary="produced path", data={"path": "C:/tmp/generated.png"})

    def render(self, data):
        return f"path={data['path']}"


class ConsumePathTool(Tool):
    name = "consume_path"
    description = "consume a path"
    input_schema = {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}

    def __init__(self) -> None:
        self.targets: list[str] = []

    def run(self, args):
        target = str(args.get("target", ""))
        self.targets.append(target)
        return ToolResult(ok=True, summary=f"consumed {target}", data={"target": target})


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


def test_router_receives_recent_conversation_context_for_followups(tmp_path: Path):
    client = RouterAnswerClient('{"answer":"ok"}')
    agent = build_agent(tmp_path, client, ToolRegistry())
    agent.messages.extend(
        [
            {"role": "user", "content": "what about gpt 5.5 model"},
            {"role": "assistant", "content": "older answer"},
        ]
    )

    agent.plan("are yu sure search about it")

    assert "Recent conversation context" in client.last_user_prompt
    assert "what about gpt 5.5 model" in client.last_user_prompt


def test_router_context_only_uses_immediate_prior_exchange(tmp_path: Path):
    client = RouterAnswerClient('{"answer":"ok"}')
    agent = build_agent(tmp_path, client, ToolRegistry())
    agent.messages.extend(
        [
            {"role": "user", "content": "gen a img of dog"},
            {"role": "assistant", "content": "Generated image: dog.png"},
            {"role": "user", "content": "convert 1 day to sec in si unit"},
            {"role": "assistant", "content": "1 day = 86400 seconds."},
        ]
    )

    agent.plan("how is it")

    assert "1 day = 86400 seconds" in client.last_user_prompt
    assert "gen a img of dog" not in client.last_user_prompt
    assert "dog.png" not in client.last_user_prompt


def test_general_chat_prompt_uses_short_context_not_full_session(tmp_path: Path):
    client = RouterAnswerClient('{"steps":[{"tool":"general_chat","args":{},"reason":"chat"}]}')
    agent = build_agent(tmp_path, client, ToolRegistry())
    agent.messages.extend(
        [
            {"role": "user", "content": "old dog image topic"},
            {"role": "assistant", "content": "old dog answer"},
            {"role": "user", "content": "convert 1 day to seconds"},
            {"role": "assistant", "content": "1 day = 86400 seconds."},
        ]
    )

    agent.reply("how is it")

    assert client.chat_calls == 1
    assert any("1 day = 86400 seconds" in item.get("content", "") for item in client.last_chat_messages)
    assert not any("old dog image topic" in item.get("content", "") for item in client.last_chat_messages)


def test_image_generation_schema_does_not_expose_open_after_to_planner(tmp_path: Path):
    tool = ImageGenerationTool(api_key="key", base_url="https://example.com/v1", model="fake", output_dir=tmp_path)

    assert "open_after" not in tool.input_schema["properties"]


def test_agent_resolves_tool_output_placeholders_between_steps(tmp_path: Path):
    client = RouterAnswerClient(
        '{"steps":['
        '{"tool":"produce_path","args":{},"reason":"make file"},'
        '{"tool":"consume_path","args":{"target":"{{produce_path.path}}"},"reason":"open file"}'
        "]}"
    )
    tools = ToolRegistry()
    producer = ProducePathTool()
    consumer = ConsumePathTool()
    tools.register(producer)
    tools.register(consumer)
    agent = build_agent(tmp_path, client, tools)

    model, content = agent.reply("generate image and open it")

    assert model == "local:tool"
    assert consumer.targets == ["C:/tmp/generated.png"]
    assert "consume_path: consumed C:/tmp/generated.png" in content
