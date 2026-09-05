import json

import pytest

from mcpclient.manager import MCPManager
from mcpclient import builtin
from mcpclient import defaults
from mcpclient import registry
from models import ChatResult, ChatUsage

META = defaults.META_SERVER
S = defaults.SEP


class FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = "d"
        self.inputSchema = {"type": "object", "properties": {}}


@pytest.fixture
def manager_factory(monkeypatch):
    def make(config):
        async def fake_connect(self, st):
            st.session = object()
            st.tools = [FakeTool("ping")]
            st.status = "online"

        monkeypatch.setattr(MCPManager, "_connect", fake_connect)
        return MCPManager(config=config)
    return make


def _run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_reload_adds_server_live(manager_factory):
    async def main():
        mgr = manager_factory({"a": {"command": "x"}})
        await mgr.start()
        assert mgr.online_count() == 1
        summary = await mgr.reload({"a": {"command": "x"}, "b": {"command": "y"}})
        assert summary["added"] == ["b"]
        assert mgr.online_count() == 2
        await mgr.stop()

    _run(main())


def test_reload_removes_server_live(manager_factory):
    async def main():
        mgr = manager_factory({"a": {"command": "x"}, "b": {"command": "y"}})
        await mgr.start()
        summary = await mgr.reload({"a": {"command": "x"}})
        assert summary["removed"] == ["b"]
        assert "b" not in mgr.servers
        assert mgr.online_count() == 1
        await mgr.stop()

    _run(main())


def test_reload_updates_changed_server(manager_factory, monkeypatch):
    calls = {"n": 0}

    async def counting_connect(self, st):
        calls["n"] += 1
        st.status = "online"
        st.tools = [FakeTool("ping")]

    import mcpclient.manager as mm
    orig = mm.MCPManager._connect

    async def main(monkeypatch):
        monkeypatch.setattr(mm.MCPManager, "_connect", counting_connect)
        mgr = mm.MCPManager(config={"a": {"command": "x"}})
        await mgr.start()
        assert calls["n"] == 1
        summary = await mgr.reload({"a": {"command": "x", "args": ["new"]}})
        assert summary["updated"] == ["a"]
        assert calls["n"] == 2  # reconnected
        await mgr.stop()

    _run(main(monkeypatch))


def test_reload_noop_when_unchanged(manager_factory):
    async def main():
        mgr = manager_factory({"a": {"command": "x"}})
        mgr._loaded_mtime = mgr._files_mtime()  # pretend fresh
        await mgr.start()
        summary = await mgr.reload({"a": {"command": "x"}})
        assert summary["unchanged"] == 1
        await mgr.stop()

    _run(main())


def test_builtin_tools_exposed(manager_factory):
    async def main():
        mgr = manager_factory({"a": {"command": "x"}})
        await mgr.start()
        names = [t["function"]["name"] for t in mgr.all_tools()]
        assert f"{META}{S}mcp_search" in names
        assert f"{META}{S}mcp_add" in names
        assert f"{META}{S}mcp_remove" in names
        assert f"{META}{S}mcp_list" in names
        await mgr.stop()

    _run(main())


def test_builtin_call_routes_to_handler(manager_factory):
    async def main():
        mgr = manager_factory({"a": {"command": "x"}})
        await mgr.start()
        out = await mgr.call_tool(f"{META}{S}mcp_list", {})
        assert "a: online" in out
        await mgr.stop()

    _run(main())


def test_builtin_add_and_remove_live(manager_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "search", lambda q, limit=5, timeout=20: [
        {"name": "gh", "full_name": "io.x/gh", "description": "GitHub tools",
         "version": "1.0", "install": {"command": "npx", "args": ["-y", "gh-mcp"]}},
    ])

    async def main(monkeypatch):
        from mcpclient import config as cfg
        monkeypatch.setattr(cfg, "home_config_path", lambda: tmp_path / "mcp.json")
        monkeypatch.setattr(cfg, "project_config_path", lambda: tmp_path / "none.json")
        mgr = manager_factory({})
        await mgr.start()
        # search
        out = await mgr.call_tool(f"{META}{S}mcp_search", {"query": "github"})
        assert "[1] gh" in out
        # install by index -> live connection
        out = await mgr.call_tool(f"{META}{S}mcp_add", {"install_index": 1})
        assert "'gh'" in out and "online" in out
        assert mgr.online_count() == 1
        tools = [t["function"]["name"] for t in mgr.all_tools()]
        assert "gh__ping" in tools
        # persisted to disk
        data = json.loads((tmp_path / "mcp.json").read_text(encoding="utf-8"))
        assert "gh" in data["mcpServers"]
        # remove live
        out = await mgr.call_tool(f"{META}{S}mcp_remove", {"name": "gh"})
        assert "Removed" in out
        assert mgr.online_count() == 0
        await mgr.stop()

    _run(main(monkeypatch))


def test_registry_search_parses(monkeypatch):
    class R:
        status_code = 200
        def json(self):
            return {"servers": [{
                "server": {
                    "name": "io.gh/github-mcp",
                    "description": "GitHub tools",
                    "version": "2.0",
                    "packages": [{"registry_type": "npm", "identifier": "@x/gh-mcp"}],
                }
            }]}

    import mcpclient.registry as reg
    monkeypatch.setattr(reg.requests, "get", lambda *a, **kw: R())
    results = reg.search("github")
    assert results[0]["name"] == "github-mcp"
    assert results[0]["install"] == {"command": "npx", "args": ["-y", "@x/gh-mcp"]}


def test_registry_search_never_raises(monkeypatch):
    import mcpclient.registry as reg

    def boom(*a, **kw):
        raise OSError("network down")

    monkeypatch.setattr(reg.requests, "get", boom)
    assert reg.search("x") == []
