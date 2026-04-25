from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from jakata_agent.router import PlanStep
from jakata_agent.tasks.orchestrator import TaskOrchestrator
from jakata_agent.tasks.store import TaskStore
from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.coding_agent import CodingController
from jakata_agent.tools.opening import OpenTargetResult
from jakata_agent.tools.registry import ToolRegistry
from jakata_agent.tools.system_control import SystemTool
import jakata_agent.tools.terminal as terminal_module
import jakata_agent.tools.opening as opening_module
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


def test_terminal_shell_has_no_command_blacklist(tmp_path: Path):
    registry = ToolRegistry()
    register_terminal_tools(registry, tmp_path)
    shell = registry.get("shell")
    assert shell is not None

    result = shell.run({"command": "Write-Output 'rm -rf /'", "cwd": str(tmp_path), "timeout": 30})

    assert result.ok
    assert "rm -rf /" in result.data["stdout"]


def test_terminal_tools_discover_and_verify_pc_paths(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JAKATA_PATH_SEARCH_ROOTS", f"{tmp_path / 'OneDrive'}{os.pathsep}{tmp_path}")
    monkeypatch.setenv("JAKATA_PATH_DISCOVERY_MAX_DEPTH", "4")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    desktop = tmp_path / "OneDrive" / "Desktop"
    desktop.mkdir(parents=True)
    (desktop / "notes.txt").write_text("desktop-ok", encoding="utf-8")
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "archive.zip").write_text("zip", encoding="utf-8")

    registry = ToolRegistry()
    register_terminal_tools(registry, workspace)
    list_dir = registry.get("list_dir")
    read_file = registry.get("read_file")
    write_file = registry.get("write_file")
    open_path = registry.get("open_path")
    search_files = registry.get("search_files")
    assert list_dir is not None
    assert read_file is not None
    assert write_file is not None
    assert open_path is not None
    assert search_files is not None

    listed_desktop = list_dir.run({"path": "Desktop"})
    assert listed_desktop.ok
    assert Path(listed_desktop.data["path"]) == desktop.resolve()
    assert listed_desktop.data["discovered"] is True
    assert any(entry["name"] == "notes.txt" for entry in listed_desktop.data["entries"])

    listed_downloads = list_dir.run({"path": "downloand"})
    assert listed_downloads.ok
    assert Path(listed_downloads.data["path"]) == downloads.resolve()

    read = read_file.run({"path": "notes.txt"})
    assert read.ok
    assert read.data["content"] == "desktop-ok"

    written = write_file.run({"path": "Desktop/new.txt", "content": "write-ok", "mode": "overwrite"})
    assert written.ok
    assert (desktop / "new.txt").read_text(encoding="utf-8") == "write-ok"

    found = search_files.run({"path": "Desktop", "file_pattern": "*.txt", "max_results": 10})
    assert found.ok
    assert any(item["file"] == "new.txt" for item in found.data["results"])


def test_open_path_tool_resolves_and_reports_open_verification(tmp_path: Path, monkeypatch):
    opened: list[tuple[str, float]] = []

    def fake_open_target(target, *, wait_seconds=1.5):
        opened.append((str(target), wait_seconds))
        return OpenTargetResult(
            ok=True,
            target=str(target),
            kind="path",
            method="fake-opener",
            opened=True,
            verified=True,
            process={"id": 123, "process_name": "viewer"},
        )

    monkeypatch.setattr(terminal_module, "open_target", fake_open_target)
    monkeypatch.setenv("JAKATA_PATH_SEARCH_ROOTS", f"{tmp_path / 'OneDrive'}{os.pathsep}{tmp_path}")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    desktop = tmp_path / "OneDrive" / "Desktop"
    desktop.mkdir(parents=True)
    note = desktop / "notes.txt"
    note.write_text("desktop-ok", encoding="utf-8")

    registry = ToolRegistry()
    register_terminal_tools(registry, workspace)
    open_path = registry.get("open_path")
    assert open_path is not None

    result = open_path.run({"target": "Desktop/notes.txt", "wait_seconds": 2})

    assert result.ok
    assert result.data["opened"] is True
    assert result.data["verified"] is True
    assert Path(result.data["target"]) == note.resolve()
    assert opened == [(str(note.resolve()), 2.0)]


def test_search_files_returns_partial_results_when_scan_is_capped(tmp_path: Path):
    for index in range(20):
        (tmp_path / f"file_{index}.txt").write_text(f"needle {index}", encoding="utf-8")
    registry = ToolRegistry()
    register_terminal_tools(registry, tmp_path)
    search_files = registry.get("search_files")
    assert search_files is not None

    result = search_files.run({"path": ".", "query": "needle", "file_pattern": "*.txt", "max_results": 50, "max_files": 5, "max_seconds": 5})

    assert result.ok
    assert result.data["scanned_files"] == 5
    assert result.data["capped"] is True
    assert len(result.data["results"]) == 5


def test_windows_open_target_uses_image_fallback_when_default_app_is_unverified(tmp_path: Path, monkeypatch):
    image = tmp_path / "picture.png"
    image.write_bytes(b"fake-png")
    popen_calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = '{"ok":true,"error":"","process":null,"matching_windows":[]}'
        stderr = ""

    class Proc:
        pid = 456

        def poll(self):
            return None

    def fake_run(*args, **kwargs):
        del args, kwargs
        return Completed()

    def fake_popen(command, **kwargs):
        del kwargs
        popen_calls.append(list(command))
        return Proc()

    monkeypatch.setattr(opening_module, "PLATFORM", "Windows")
    monkeypatch.setattr(opening_module.subprocess, "run", fake_run)
    monkeypatch.setattr(opening_module.subprocess, "Popen", fake_popen)

    result = opening_module.open_target(image, wait_seconds=0.1)

    assert result.ok
    assert result.opened is True
    assert result.verified is True
    assert "image fallback" in result.method
    assert popen_calls == [["mspaint.exe", str(image)]]


def test_windows_open_target_uses_explorer_fallback_for_unverified_folder(tmp_path: Path, monkeypatch):
    folder = tmp_path / "images"
    folder.mkdir()
    popen_calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = '{"ok":true,"error":"","process":null,"matching_windows":[]}'
        stderr = ""

    class Proc:
        pid = 789

        def poll(self):
            return 0

    def fake_run(*args, **kwargs):
        del args, kwargs
        return Completed()

    def fake_popen(command, **kwargs):
        del kwargs
        popen_calls.append(list(command))
        return Proc()

    monkeypatch.setattr(opening_module, "PLATFORM", "Windows")
    monkeypatch.setattr(opening_module.subprocess, "run", fake_run)
    monkeypatch.setattr(opening_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(opening_module, "_windows_matching_windows", lambda token: [{"ProcessName": "explorer", "MainWindowTitle": token}])

    result = opening_module.open_target(folder, wait_seconds=0.1)

    assert result.ok
    assert result.opened is True
    assert result.verified is True
    assert "folder fallback" in result.method
    assert popen_calls == [["explorer.exe", str(folder)]]


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
