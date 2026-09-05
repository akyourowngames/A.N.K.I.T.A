import asyncio
import json
from types import SimpleNamespace

import pytest

from mcpclient.manager import MCPManager
from mcpclient.agent import run_agent_loop
from models import ChatResult, ChatUsage


class FakeTool:
    def __init__(self, name, description="d", schema=None):
        self.name = name
        self.description = description
        self.inputSchema = schema or {"type": "object", "properties": {}}


class FakeSession:
    def __init__(self, tools):
        self.tools = tools

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def initialize(self):
        pass

    async def list_tools(self):
        return SimpleNamespace(tools=[FakeTool(t) for t in self.tools])

    async def call_tool(self, name, arguments=None):
        return SimpleNamespace(
            content=[SimpleNamespace(text=f"ran {name} with {json.dumps(arguments or {})}")],
            isError=False,
        )


@pytest.fixture
def connected_manager(monkeypatch):
    async def fake_connect(self, st):
        st.session = FakeSession(["alpha", "beta"])
        st.tools = [FakeTool("alpha"), FakeTool("beta")]
        st.status = "online"
        st.connected_at = 0.0

    monkeypatch.setattr(MCPManager, "_connect", fake_connect)
    return MCPManager(config={"srv": {"command": "x"}})


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_start_connects_and_collects_tools(connected_manager):
    async def main():
        mgr = connected_manager
        await mgr.start()
        tools = mgr.all_tools()
        assert [t["function"]["name"] for t in tools if not t["function"]["name"].startswith("zumba__")] == ["srv__alpha", "srv__beta"]
        assert mgr.online_count() == 1
        await mgr.stop()

    _run(main())


def test_call_tool_routes_by_namespace(connected_manager):
    async def main():
        mgr = connected_manager
        await mgr.start()
        out = await mgr.call_tool("srv__alpha", {"x": 1})
        assert "ran alpha" in out
        out = await mgr.call_tool("nope__alpha", {})
        assert out.startswith("ERROR")
        await mgr.stop()

    _run(main())


def test_disabled_server_never_connects():
    async def main():
        mgr = MCPManager(config={"off": {"command": "x", "enabled": False}})
        await mgr.start()
        assert mgr.servers["off"].status == "disabled"
        assert [t for t in mgr.all_tools() if not t["function"]["name"].startswith("zumba__")] == []
        out = await mgr.call_tool("off__alpha", {})
        assert "disabled" in out
        await mgr.stop()

    _run(main())


def test_offline_server_degrades_gracefully():
    async def main():
        mgr = MCPManager(config={"bad": {"command": "definitely-missing-binary-xyz"}})
        await mgr.start()  # must not raise
        assert mgr.servers["bad"].status == "offline"
        assert mgr.online_count() == 0
        out = await mgr.call_tool("bad__alpha", {})
        assert out.startswith("ERROR")
        await mgr.stop()

    _run(main())


# ---- agent loop with a scripted model --------------------------------------
def _tool_call(name, args, cid="call1"):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _final(content="final answer"):
    return ChatResult(content=content, model="m", usage=ChatUsage(),
                      raw={"choices": [{"message": {"content": content, "tool_calls": []}}]})


def test_agent_loop_executes_tools_and_finishes():
    calls = {"n": 0}

    def scripted_model(convo, model, tools=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raw = {"choices": [{"message": {"content": "", "tool_calls": [_tool_call("srv__alpha", {"q": "hi"})]}}]}
            return ChatResult(content="", model=model, usage=ChatUsage(), raw=raw)
        return _final()

    executed = []
    result = run_agent_loop(
        [], "m", scripted_model,
        execute_tool=lambda n, a: (executed.append((n, a)) or "tool-out"),
        tools=[{"type": "function", "function": {"name": "srv__alpha"}}],
    )
    assert result.content == "final answer"
    assert executed == [("srv__alpha", {"q": "hi"})]
    assert calls["n"] == 2


def test_agent_loop_max_iterations():
    def always_tools(convo, model, tools=None, **kw):
        raw = {"choices": [{"message": {"content": "", "tool_calls": [_tool_call("s__t", {})]}}]}
        return ChatResult(content="", model=model, usage=ChatUsage(), raw=raw)

    result = run_agent_loop([], "m", always_tools, execute_tool=lambda n, a: "ok",
                            tools=[], max_iterations=3)
    assert result is not None  # stops without hanging


def test_agent_loop_malformed_args():
    raw = {"choices": [{"message": {"content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "s__t", "arguments": "{not json"}}]}}]}
    state = {"first": True}

    def model(convo, m, tools=None, **kw):
        if state["first"]:
            state["first"] = False
            return ChatResult(content="", model=m, usage=ChatUsage(), raw=raw)
        tool_msgs = [x for x in convo if x.role == "tool"]
        assert tool_msgs and tool_msgs[0].content.startswith("ERROR")
        return _final()

    result = run_agent_loop([], "m", model, execute_tool=lambda n, a: "never", tools=[])
    assert result.content == "final answer"


def test_agent_loop_tool_messages_shape():
    raw = {"choices": [{"message": {"content": "", "tool_calls": [_tool_call("s__t", {"a": 1})]}}]}
    seen = {}

    def model(convo, m, tools=None, **kw):
        if not convo:
            return ChatResult(content="", model=m, usage=ChatUsage(), raw=raw)
        seen["convo"] = convo
        return _final()

    run_agent_loop([], "m", model, execute_tool=lambda n, a: "res", tools=[])
    asst, tool = seen["convo"][0], seen["convo"][1]
    assert asst.role == "assistant" and asst.tool_calls
    assert tool.role == "tool" and tool.tool_call_id == "call1" and tool.content == "res"
    assert tool.to_dict()["tool_call_id"] == "call1"
