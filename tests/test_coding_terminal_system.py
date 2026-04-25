from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from jakata_agent.router import PlanStep
from jakata_agent.tasks.orchestrator import TaskOrchestrator
from jakata_agent.tasks.store import TaskStore
from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.coding_agent import CodingController
from jakata_agent.tools.registry import ToolRegistry
from jakata_agent.tools.system_control import SystemTool
import jakata_agent.tools.terminal as terminal_module
from jakata_agent.tools.terminal import register_terminal_tools


class FakeCodingClient:
    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
        del temperature
        if "coding action planner" in system_prompt:
            if terminal_module.PLATFORM == "Windows":
                read_command = f'& "{sys.executable}" -c "from pathlib import Path; print(Path(\'agent_demo.txt\').read_text())"'
            else:
                read_command = f'"{sys.executable}" -c "from pathlib import Path; print(Path(\'agent_demo.txt\').read_text())"'
            return "fake-model", json.dumps(
                {
                    "steps": [
                        {
                            "tool": "write_file",
                            "args": {"path": "agent_demo.txt", "content": "coding-agent-ok\n", "mode": "overwrite"},
                            "reason": "write requested file",
                        },
                        {
                            "tool": "shell",
                            "args": {"command": read_command, "timeout": 60},
                            "reason": "prove the file can be read through the terminal",
                        },
                    ]
                }
            )
        if "coding task verifier" in system_prompt:
            payload = json.loads(user_prompt)
            rendered = "\n".join(str(item.get("rendered", "")) for item in payload.get("executed", []))
            ok = "coding-agent-ok" in rendered
            return "fake-model", json.dumps({"ok": ok, "summary": "verified" if ok else "not verified", "reason": "verified" if ok else "verifier_rejected"})
        return "fake-model", "{}"


class DummyMemory:
    def remember_task_event(self, *args, **kwargs):
        return None

    def retrieve(self, query: str):
        del query
        return SimpleNamespace(to_system_context=lambda: "", permanent_memories=[])


class FailingSystemTool(Tool):
    name = "system"
    description = "failing system"
    input_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}, "target": {"type": "string"}},
        "required": ["action"],
    }

    def run(self, args):
        return ToolResult(ok=False, summary="system failed", data={}, error="system_failed")


class BrowserOpenUrlTool(Tool):
    name = "browser"
    description = "browser"
    input_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}, "url": {"type": "string"}},
        "required": ["action"],
    }

    def run(self, args):
        if args.get("action") == "open_url":
            return ToolResult(ok=True, summary=f"opened {args.get('url')}", data={"action": "open_url", "url": args.get("url", "")})
        return ToolResult(ok=False, summary="bad action", data={}, error="bad_action")


def test_terminal_shell_is_public_and_runs_in_requested_cwd(tmp_path: Path):
    registry = ToolRegistry()
    register_terminal_tools(registry, tmp_path)
    shell = registry.get("shell")
    assert shell is not None
    assert shell.public is True

    if terminal_module.PLATFORM == "Windows":
        command = f'& "{sys.executable}" -c "import os; print(os.getcwd())"'
    else:
        command = f'"{sys.executable}" -c "import os; print(os.getcwd())"'
    result = shell.run({"command": command, "cwd": str(tmp_path), "timeout": 30})
    assert result.ok
    assert str(tmp_path) in result.data["stdout"]


def test_system_tool_adds_disk_network_environment_and_executable_lookup(tmp_path: Path):
    tool = SystemTool()
    disk = tool.run({"action": "disk_usage", "target": str(tmp_path)})
    assert disk.ok
    assert disk.data["disks"]

    resolved = tool.run({"action": "resolve_executable", "target": sys.executable})
    assert resolved.ok
    assert resolved.data["found"] is True

    env = tool.run({"action": "environment", "target": "PATH"})
    assert env.ok
    assert env.data["set"] is True


def test_task_orchestrator_runs_derived_fallback_when_primary_tool_fails(tmp_path: Path):
    registry = ToolRegistry()
    registry.register(FailingSystemTool())
    registry.register(BrowserOpenUrlTool())
    store = TaskStore(tmp_path / "jakata.db")
    task = store.create_task(goal="open example", session_id="test")
    orchestrator = TaskOrchestrator(
        client=FakeCodingClient(),
        router=None,
        tools=registry,
        validator=None,
        memory=DummyMemory(),
        task_store=store,
        approval_policy="auto_safe",
        workspace_dir=tmp_path,
        data_dir=tmp_path,
    )

    results = orchestrator._execute(
        task,
        [PlanStep(tool="system", args={"action": "open_url", "target": "https://example.com"}, reason="open with system")],
    )

    assert [item["tool"] for item in results] == ["system", "browser"]
    assert results[0]["ok"] is False
    assert results[1]["ok"] is True
    assert results[1]["fallback_for"] == "system"


def test_coding_agent_writes_code_and_verifies_with_terminal(tmp_path: Path):
    registry = ToolRegistry()
    register_terminal_tools(registry, tmp_path)
    controller = CodingController(FakeCodingClient(), registry)

    result = controller.run_goal("create a demo file and verify it", cwd=str(tmp_path), repair_limit=1)

    assert result.ok
    assert (tmp_path / "agent_demo.txt").read_text(encoding="utf-8") == "coding-agent-ok\n"
    assert [item["tool"] for item in result.data["executed"]] == ["write_file", "shell"]
