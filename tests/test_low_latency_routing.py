from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from jakata_agent.agent import JakataAgent
from jakata_agent.plan_validator import PlanValidator
from jakata_agent.router import IntentRouter
from jakata_agent.tasks.store import TaskStore
from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.capabilities import register_capabilities_tool
from jakata_agent.tools.coding_agent import CodingAgentTool
from jakata_agent.tools.datetime_tool import DateTimeTool
from jakata_agent.tools.image_generation import ImageGenerationTool
from jakata_agent.tools.registry import ToolRegistry
from jakata_agent.tools.terminal import register_terminal_tools


class RouterAnswerClient:
    def __init__(self, raw: str | list[str]) -> None:
        self.raws = list(raw) if isinstance(raw, list) else [raw]
        self.raw = self.raws[-1]
        self.router_calls = 0
        self.chat_calls = 0
        self.last_user_prompt = ""
        self.last_chat_messages = []

    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
        del system_prompt, temperature
        self.last_user_prompt = user_prompt
        raw = self.raws[min(self.router_calls, len(self.raws) - 1)]
        self.router_calls += 1
        return "router-model", raw

    def complete(self, messages, temperature: float = 0.7):
        del temperature
        self.last_chat_messages = list(messages)
        self.chat_calls += 1
        return "chat-model", "chat fallback"

    def stream_complete(self, messages, temperature: float = 0.7):
        del messages, temperature
        yield "chat-model", "chat fallback"


class FakeSemanticEmbedder:
    def similarity_many(self, query: str, texts: list[str]) -> list[float]:
        query_l = query.lower()
        scores: list[float] = []
        for text in texts:
            text_l = text.lower()
            if "what can you do" in query_l and "connected tools" in text_l and "tool catalog" in text_l:
                scores.append(0.44)
            elif "time" in query_l and "datetime" in text_l:
                scores.append(0.91)
            elif "time" in query_l:
                scores.append(0.02)
            elif "path" in query_l and "produce_path" in text_l:
                scores.append(0.91)
            elif "path" in query_l:
                scores.append(0.02)
            else:
                scores.append(0.0)
        return scores


class DummyMemory:
    def __init__(self, context: str = "", embedder=None) -> None:
        self.messages = []
        self.context = context
        self.embedder = embedder
        self.knowledge_chunks = []
        self.store = SimpleNamespace(recent=lambda limit=10: [])
        self.retrieve_calls = 0

    def load_session_messages(self):
        return []

    def bootstrap_system_note(self):
        return "Memory empty."

    def persist_turn(self, messages):
        self.messages = list(messages)

    def learn_from_user_message(self, user_message: str):
        del user_message

    def retrieve(self, query: str):
        self.retrieve_calls += 1
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


class SkipMemoryTool(Tool):
    name = "skip_memory_tool"
    description = "semantic tool that does not need planning memory"
    skip_planning_memory = True
    input_schema = {"type": "object", "properties": {}, "required": []}

    def run(self, args):
        del args
        return ToolResult(ok=True, summary="skip memory complete", data={})


class SkipMemoryEmbedder:
    def similarity_many(self, query: str, texts: list[str]) -> list[float]:
        del query
        return [0.91 if "skip_memory_tool" in text else 0.01 for text in texts]


class ReadFileEmbedder:
    def similarity_many(self, query: str, texts: list[str]) -> list[float]:
        del query
        return [0.91 if "read_file" in text else 0.01 for text in texts]


class GeneralChatEmbedder:
    def similarity_many(self, query: str, texts: list[str]) -> list[float]:
        del query
        scores: list[float] = []
        for text in texts:
            text_l = text.lower()
            if "general_chat" in text_l and "no tool needed" in text_l:
                scores.append(0.46)
            elif "coding_agent" in text_l or "document" in text_l:
                scores.append(0.18)
            else:
                scores.append(0.03)
        return scores


class GeneralChatRunnerUpEmbedder:
    def similarity_many(self, query: str, texts: list[str]) -> list[float]:
        del query
        scores: list[float] = []
        for text in texts:
            text_l = text.lower()
            if "produce_path" in text_l:
                scores.append(0.24)
            elif "general_chat" in text_l and "no tool needed" in text_l:
                scores.append(0.21)
            else:
                scores.append(0.02)
        return scores


class ToolWithChatEscapeEmbedder:
    def similarity_many(self, query: str, texts: list[str]) -> list[float]:
        del query
        scores: list[float] = []
        for text in texts:
            text_l = text.lower()
            if "produce_path" in text_l:
                scores.append(0.24)
            elif "general_chat" in text_l and "no tool needed" in text_l:
                scores.append(0.10)
            else:
                scores.append(0.02)
        return scores


class CapturingCodingController:
    def __init__(self) -> None:
        self.cwd = ""

    def run_goal(self, goal: str, **kwargs):
        del goal
        self.cwd = str(kwargs.get("cwd", ""))
        return ToolResult(ok=True, summary="coding complete", data={"reason": "verified", "observations": ["done"]})


def build_agent(
    tmp_path: Path,
    client: RouterAnswerClient,
    tools: ToolRegistry,
    memory_context: str = "",
    *,
    embedder=None,
    router_tool_limit: int = 0,
    router_min_tool_score: float = 0.0,
    fast_client=None,
) -> JakataAgent:
    settings = SimpleNamespace(
        session_id="test",
        workspace_dir=tmp_path,
        data_dir=tmp_path / "data",
        approval_policy="auto_safe",
        router_tool_limit=router_tool_limit,
        router_min_tool_score=router_min_tool_score,
    )
    return JakataAgent(
        settings=settings,
        client=client,
        tools=tools,
        memory=DummyMemory(memory_context, embedder=embedder),
        router=IntentRouter(client),
        validator=PlanValidator(),
        task_store=TaskStore(tmp_path / "jakata.db"),
        fast_client=fast_client,
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


def test_router_retries_once_after_invalid_json(tmp_path: Path):
    client = RouterAnswerClient(["not json", '{"answer":"normal chat answered after retry"}'])
    agent = build_agent(tmp_path, client, ToolRegistry())

    model, content = agent.reply("normal message")

    assert model == "router:answer"
    assert content == "normal chat answered after retry"
    assert client.router_calls == 2
    assert "previous planner response was not valid JSON" in client.last_user_prompt
    assert client.chat_calls == 0


def test_router_receives_semantic_shortlisted_manifest(tmp_path: Path):
    client = RouterAnswerClient('{"steps":[{"tool":"produce_path","args":{},"reason":"path requested"}]}')
    tools = ToolRegistry()
    tools.register(DateTimeTool())
    tools.register(ProducePathTool())
    agent = build_agent(
        tmp_path,
        client,
        tools,
        embedder=FakeSemanticEmbedder(),
        router_tool_limit=1,
        router_min_tool_score=0.09,
    )

    model, content = agent.reply("make a path")

    assert model == "local:tool"
    assert content == "produced path"
    assert '"name":"produce_path"' in client.last_user_prompt
    assert '"name":"datetime"' not in client.last_user_prompt


def test_semantic_no_match_skips_router_and_uses_streamable_chat_path(tmp_path: Path):
    client = RouterAnswerClient('{"answer":"normal chat"}')
    tools = ToolRegistry()
    tools.register(DateTimeTool())
    agent = build_agent(
        tmp_path,
        client,
        tools,
        embedder=FakeSemanticEmbedder(),
        router_tool_limit=1,
        router_min_tool_score=0.09,
    )

    model, content = agent.reply("casual message")

    assert model == "chat-model"
    assert content == "chat fallback"
    assert client.router_calls == 0
    assert client.chat_calls == 1
    assert agent.memory.retrieve_calls == 0


def test_semantic_general_chat_candidate_skips_planner_for_chat_only_work(tmp_path: Path):
    client = RouterAnswerClient('{"steps":[{"tool":"coding_agent","args":{},"reason":"wrong"}]}')
    tools = ToolRegistry()
    tools.register(CodingAgentTool(CapturingCodingController()))  # type: ignore[arg-type]
    agent = build_agent(
        tmp_path,
        client,
        tools,
        embedder=GeneralChatEmbedder(),
        router_tool_limit=3,
        router_min_tool_score=0.09,
    )

    decision = agent.plan("Create a detailed landing page plan here without editing files.")

    assert decision.steps[0].tool == "general_chat"
    assert decision.steps[0].reason == "semantic_general_chat"
    assert client.router_calls == 0
    assert agent.memory.retrieve_calls == 0


def test_semantic_general_chat_runner_up_beats_ambiguous_tool_without_router(tmp_path: Path):
    client = RouterAnswerClient('{"steps":[{"tool":"produce_path","args":{},"reason":"wrong"}]}')
    tools = ToolRegistry()
    tools.register(ProducePathTool())
    agent = build_agent(
        tmp_path,
        client,
        tools,
        embedder=GeneralChatRunnerUpEmbedder(),
        router_tool_limit=2,
        router_min_tool_score=0.09,
    )

    decision = agent.plan("Draft the plan here in chat without taking local action.")

    assert decision.steps[0].tool == "general_chat"
    assert decision.steps[0].reason == "semantic_general_chat_competitive"
    assert client.router_calls == 0
    assert agent.memory.retrieve_calls == 0


def test_router_answer_uses_chat_voice_when_tool_manifest_is_ambiguous(tmp_path: Path):
    client = RouterAnswerClient('{"answer":"raw router wording"}')
    tools = ToolRegistry()
    tools.register(ProducePathTool())
    agent = build_agent(
        tmp_path,
        client,
        tools,
        embedder=ToolWithChatEscapeEmbedder(),
        router_tool_limit=1,
        router_min_tool_score=0.09,
    )

    model, content = agent.reply("ambiguous support request")

    assert model == "chat-model"
    assert content == "chat fallback"
    assert client.router_calls == 1
    assert client.chat_calls == 1
    assert '"name":"produce_path"' in client.last_user_prompt
    assert '"name":"general_chat"' in client.last_user_prompt


def test_semantic_no_match_can_use_fast_chat_client(tmp_path: Path):
    client = RouterAnswerClient('{"answer":"router should not be called"}')
    fast_client = RouterAnswerClient('{"answer":"unused"}')
    tools = ToolRegistry()
    tools.register(DateTimeTool())
    agent = build_agent(
        tmp_path,
        client,
        tools,
        embedder=FakeSemanticEmbedder(),
        router_tool_limit=1,
        router_min_tool_score=0.09,
        fast_client=fast_client,
    )

    model, content = agent.reply("casual message")

    assert model == "chat-model"
    assert content == "chat fallback"
    assert client.router_calls == 0
    assert client.chat_calls == 0
    assert fast_client.chat_calls == 1


def test_specific_semantic_direct_tool_answers_without_router(tmp_path: Path):
    client = RouterAnswerClient('{"answer":"router should not be called"}')
    tools = ToolRegistry()
    tools.register(DateTimeTool())
    agent = build_agent(
        tmp_path,
        client,
        tools,
        embedder=FakeSemanticEmbedder(),
        router_tool_limit=2,
        router_min_tool_score=0.09,
    )

    model, content = agent.reply("what time is it")

    assert model == "local:tool"
    assert "Local time is" in content
    assert client.router_calls == 0
    assert client.chat_calls == 0


def test_capabilities_catalog_uses_semantic_direct_tool(tmp_path: Path):
    client = RouterAnswerClient('{"answer":"router should not be called"}')
    tools = ToolRegistry()
    register_capabilities_tool(tools)
    agent = build_agent(
        tmp_path,
        client,
        tools,
        embedder=FakeSemanticEmbedder(),
        router_tool_limit=2,
        router_min_tool_score=0.09,
    )

    model, content = agent.reply("what can you do and which tools are connected")

    assert model == "local:tool"
    assert "connected tools" in content
    assert client.router_calls == 0
    assert client.chat_calls == 0


def test_semantic_tool_can_skip_planning_memory_context(tmp_path: Path):
    client = RouterAnswerClient('{"steps":[{"tool":"skip_memory_tool","args":{},"reason":"use selected tool"}]}')
    tools = ToolRegistry()
    tools.register(SkipMemoryTool())
    agent = build_agent(
        tmp_path,
        client,
        tools,
        memory_context="poisoned old coffee shop context",
        embedder=SkipMemoryEmbedder(),
        router_tool_limit=1,
        router_min_tool_score=0.09,
    )

    model, content = agent.reply("use the selected semantic tool")

    assert model == "local:tool"
    assert content == "skip memory complete"
    assert "poisoned old coffee shop context" not in client.last_user_prompt


def test_read_file_semantic_direct_extracts_named_file_path(tmp_path: Path):
    (tmp_path / "README.md").write_text("Setup\nInstall dependencies.\n", encoding="utf-8")
    client = RouterAnswerClient('{"answer":"router should not be called"}')
    tools = ToolRegistry()
    register_terminal_tools(tools, tmp_path)
    agent = build_agent(
        tmp_path,
        client,
        tools,
        embedder=ReadFileEmbedder(),
        router_tool_limit=1,
        router_min_tool_score=0.09,
    )

    decision = agent.plan("Read README.md and summarize the setup section.")

    assert decision.steps[0].tool == "read_file"
    assert decision.steps[0].args["path"] == "README.md"
    assert client.router_calls == 0


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


def test_stream_reply_returns_direct_tool_result_without_chat_synthesis(tmp_path: Path):
    client = RouterAnswerClient('{"steps":[{"tool":"datetime","args":{"include_utc":false},"reason":"live time"}]}')
    tools = ToolRegistry()
    tools.register(DateTimeTool())
    agent = build_agent(tmp_path, client, tools)

    chunks = list(agent.stream_reply("time please"))

    assert chunks
    assert chunks[0][0] == "local:tool"
    assert "Local time is" in chunks[0][1]
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


def test_blank_coding_cwd_uses_generated_projects_area(tmp_path: Path):
    client = RouterAnswerClient('{"steps":[{"tool":"coding_agent","args":{"goal":"build a landing page"},"reason":"build artifact"}]}')
    tools = ToolRegistry()
    controller = CapturingCodingController()
    tools.register(CodingAgentTool(controller))  # type: ignore[arg-type]
    agent = build_agent(tmp_path, client, tools)

    model, content = agent.reply("build me a landing page")

    assert model == "local:tool"
    assert content == "coding complete"
    assert controller.cwd == str(tmp_path / "data" / "generated" / "projects")
