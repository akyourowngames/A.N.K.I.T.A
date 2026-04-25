from __future__ import annotations

import asyncio
import base64
import sys
import types
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

openai = types.ModuleType("openai")


class OpenAI:
    def __init__(self, *args, **kwargs):
        pass


openai.OpenAI = OpenAI
sys.modules.setdefault("openai", openai)

dotenv = types.ModuleType("dotenv")


def load_dotenv(*args, **kwargs):
    return None


dotenv.load_dotenv = load_dotenv
sys.modules.setdefault("dotenv", dotenv)

from jakata_agent.agent import JakataAgent
from jakata_agent.llm import FallbackTextClient, NvidiaChatClient
from jakata_agent.memory.graph_store import GraphStore
from jakata_agent.router import IntentRouter
from jakata_agent.tasks.approval import ApprovalGate, ApprovalRequired
from jakata_agent.tasks.engine import TaskCompletionEngine
from jakata_agent.tasks.notifications import BackgroundTaskNotifier
from jakata_agent.tasks.orchestrator import TaskOrchestrator
from jakata_agent.tasks.store import TaskStore
from jakata_agent.telegram_artifacts import TelegramArtifactService
from jakata_agent.telegram_bot import TelegramAuthManager, TelegramBotController
from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.browser import BrowserTool, detect_chrome_path
from jakata_agent.tools.image_generation import ImageGenerationTool
from jakata_agent.tools.os_agent import OsController
from jakata_agent.tools.registry import ToolRegistry
import jakata_agent.tools.system_control as system_control
from jakata_agent.tools.system_control import SystemTool


class FakeClient:
    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
        del temperature
        if "multi-agent orchestrator" in system_prompt:
            return "fake-model", '{"roles":["planner","researcher","executor","verifier"],"summary":"broad task"}'
        if "task verifier" in system_prompt:
            return "fake-model", '{"ok": true, "summary": "task verified", "reason": "verified"}'
        if "internal JAKATA OS action planner" in system_prompt:
            return "fake-model", '{"steps":[{"tool":"keyboard","args":{"action":"press","keys":"enter"},"reason":"confirm"}]}'
        if "modal recovery planner" in system_prompt:
            return "fake-model", '{"steps":[{"tool":"keyboard","args":{"action":"press","keys":"left"},"reason":"move to confirm"},{"tool":"keyboard","args":{"action":"press","keys":"enter"},"reason":"confirm overwrite"}]}'
        if "OS task spec builder" in system_prompt:
            return "fake-model", '{"success_criteria":["Chrome is open","AI news is visible"],"completion_hint":"one_shot"}'
        if "JAKATA OS verifier" in system_prompt:
            payload = json.loads(user_prompt)
            observations = " ".join(payload.get("observations", []))
            system_state = payload.get("system_state", {})
            if isinstance(system_state, dict) and system_state.get("modal_dialog"):
                return "fake-model", '{"ok": false, "summary": "popup still open", "reason": "blocked_by_modal"}'
            if "ocr_error" in observations or "screen_error" in observations:
                return "fake-model", '{"ok": false, "summary": "ocr uncertain", "reason": "ocr_uncertain"}'
            if "poem.txt saved" in observations:
                return "fake-model", '{"ok": true, "summary": "verified", "reason": "verified"}'
            if "AI news" in observations or "Chrome" in observations:
                return "fake-model", '{"ok": true, "summary": "verified", "reason": "verified"}'
            return "fake-model", '{"ok": false, "summary": "not verified", "reason": "unmet_precondition"}'
        return "fake-model", '{"execution_mode":"background","background_reason":"long task","steps":[{"tool":"os_agent","args":{"goal":"open app"},"reason":"needs os flow"}]}'

    def complete(self, messages, temperature: float = 0.7):
        del messages, temperature
        return "fake-model", "ok"

    def stream_complete(self, messages, temperature: float = 0.7):
        del messages, temperature
        yield "fake-model", "o"
        yield "fake-model", "k"


class StubOsAgentTool(Tool):
    name = "os_agent"
    description = "OS agent"
    input_schema = {
        "type": "object",
        "properties": {"goal": {"type": "string"}},
        "required": ["goal"],
        "additionalProperties": False,
    }

    def run(self, args):
        return ToolResult(ok=True, summary=f"done {args['goal']}", data={"goal": args["goal"]})


class StubVerifiedOsAgentTool(Tool):
    name = "os_agent"
    description = "OS agent"
    input_schema = {
        "type": "object",
        "properties": {"goal": {"type": "string"}},
        "required": ["goal"],
        "additionalProperties": False,
    }

    def run(self, args):
        return ToolResult(
            ok=True,
            summary=f"verified {args['goal']}",
            data={"goal": args["goal"], "reason": "verified", "observations": ["[window] Chrome", "[ocr] AI news headlines"]},
        )


class StubWindowTool(Tool):
    name = "window"
    public = False
    description = "window"
    input_schema = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}

    def run(self, args):
        action = args.get("action")
        if action == "list":
            return ToolResult(ok=True, summary="2 windows", data={"windows": ["Demo App - Google Chrome", "Visual Studio Code"]})
        if action == "focus":
            return ToolResult(ok=True, summary="Focused Chrome", data={"title": "Demo App - Google Chrome", "action": "focus"})
        return ToolResult(ok=True, summary="active window", data={"title": "Demo App - Google Chrome"})


class BackgroundChromeWindowTool(Tool):
    name = "window"
    public = False
    description = "window"
    input_schema = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}

    def run(self, args):
        action = args.get("action")
        if action == "list":
            return ToolResult(ok=True, summary="2 windows", data={"windows": ["AI news - Google Search - Google Chrome", ".env - JAKATA - Visual Studio Code"]})
        if action == "focus":
            return ToolResult(ok=True, summary="Focus request", data={"title": "AI news - Google Search - Google Chrome", "action": "focus"})
        return ToolResult(ok=True, summary="active window", data={"title": ".env - JAKATA - Visual Studio Code"})


class PopupWindowTool(Tool):
    name = "window"
    public = False
    description = "window"
    input_schema = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}

    def __init__(self) -> None:
        self.calls = 0

    def run(self, args):
        action = args.get("action")
        if action == "list":
            return ToolResult(ok=True, summary="2 windows", data={"windows": ["Confirm Save As", "Untitled - Notepad"]})
        if action == "focus":
            return ToolResult(ok=True, summary="Focused dialog", data={"title": "Confirm Save As", "action": "focus", "left": 100, "top": 100, "width": 420, "height": 220})
        self.calls += 1
        if self.calls <= 2:
            return ToolResult(ok=True, summary="active window", data={"title": "Confirm Save As", "left": 100, "top": 100, "width": 420, "height": 220})
        return ToolResult(ok=True, summary="active window", data={"title": "Untitled - Notepad", "left": 50, "top": 50, "width": 900, "height": 700})


class StubScreenTool(Tool):
    name = "screen"
    public = False
    description = "screen"
    input_schema = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}

    def run(self, args):
        return ToolResult(ok=True, summary="captured", data={"path": "fake.png"})


class StubOCRTool(Tool):
    name = "ocr"
    public = False
    description = "ocr"
    input_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}, "path": {"type": "string"}},
        "required": ["action"],
    }

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    def run(self, args):
        if not self.ok:
            return ToolResult(ok=False, summary="ocr missing", data={}, error="missing_dep")
        return ToolResult(ok=True, summary="ocr", data={"text": "Demo App Ready"})


class PopupOCRTool(Tool):
    name = "ocr"
    public = False
    description = "ocr"
    input_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}, "path": {"type": "string"}},
        "required": ["action"],
    }

    def __init__(self) -> None:
        self.calls = 0

    def run(self, args):
        del args
        self.calls += 1
        if self.calls <= 2:
            return ToolResult(
                ok=True,
                summary="popup",
                data={"text": "Confirm Save As poem.txt already exists. Do you want to replace it? Yes No"},
            )
        return ToolResult(ok=True, summary="saved", data={"text": "poem.txt saved"})


class StubKeyboardTool(Tool):
    name = "keyboard"
    public = False
    description = "keyboard"
    input_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}, "keys": {"type": "string"}},
        "required": ["action"],
    }

    def run(self, args):
        return ToolResult(ok=True, summary=f"pressed {args.get('keys', '')}", data={"action": args.get("action", "")})


class TrackingKeyboardTool(Tool):
    name = "keyboard"
    public = False
    description = "keyboard"
    input_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}, "keys": {"type": "string"}},
        "required": ["action"],
    }

    def __init__(self) -> None:
        self.presses: list[str] = []

    def run(self, args):
        keys = str(args.get("keys", ""))
        self.presses.append(keys)
        return ToolResult(ok=True, summary=f"pressed {keys}", data={"action": args.get("action", ""), "keys": keys})


class StubMouseTool(Tool):
    name = "mouse"
    public = False
    description = "mouse"
    input_schema = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}

    def run(self, args):
        action = str(args.get("action", ""))
        if action == "position":
            return ToolResult(ok=True, summary="cursor", data={"action": "position", "x": 640, "y": 480})
        return ToolResult(ok=True, summary=action, data={"action": action})


class StubClipboardTool(Tool):
    name = "clipboard"
    public = False
    description = "clipboard"
    input_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}, "text": {"type": "string"}},
        "required": ["action"],
    }

    def __init__(self) -> None:
        self.text = ""

    def run(self, args):
        action = args.get("action")
        if action == "write":
            self.text = str(args.get("text", ""))
            return ToolResult(ok=True, summary="clipboard written", data={"text": self.text})
        return ToolResult(ok=True, summary=self.text, data={"text": self.text})


class StubShellTool(Tool):
    name = "shell"
    public = False
    description = "shell"
    input_schema = {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}

    def __init__(self) -> None:
        self.commands: list[str] = []

    def run(self, args):
        command = str(args.get("command", ""))
        self.commands.append(command)
        return ToolResult(ok=True, summary="Done.", data={"command": command})


class BrowserMediaWindowTool(Tool):
    name = "window"
    public = False
    description = "window"
    input_schema = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}

    def run(self, args):
        action = args.get("action")
        if action == "list":
            return ToolResult(ok=True, summary="1 window", data={"windows": ["Pal Pal - YouTube - Google Chrome"]})
        if action == "focus":
            return ToolResult(
                ok=True,
                summary="Focused Chrome",
                data={"title": "Pal Pal - YouTube - Google Chrome", "action": "focus", "left": 10, "top": 10, "width": 1280, "height": 720},
            )
        return ToolResult(
            ok=True,
            summary="active window",
            data={"title": "Pal Pal - YouTube - Google Chrome", "left": 10, "top": 10, "width": 1280, "height": 720, "right": 1290, "bottom": 730},
        )


class SequencedBrowserTool(Tool):
    name = "browser"
    public = False
    description = "browser"
    input_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}},
        "required": ["action"],
    }

    def __init__(self) -> None:
        self.stage = "results"
        self.calls: list[tuple[str, dict]] = []

    def run(self, args):
        action = str(args.get("action", ""))
        self.calls.append((action, dict(args)))
        if action == "inspect":
            return ToolResult(ok=True, summary=self.stage, data=self._state())
        if action == "status":
            state = self._state()
            return ToolResult(ok=True, summary=self.stage, data=state)
        if action == "focus":
            state = self._state()
            return ToolResult(ok=True, summary="Focused Chrome", data={"title": state["active_title"], "left": 10, "top": 10, "width": 1280, "height": 720})
        if action == "search":
            self.stage = "results"
            return ToolResult(ok=True, summary="searched", data=self._state())
        if action == "open_result":
            self.stage = "watch_paused"
            return ToolResult(ok=True, summary="opened result", data=self._state())
        if action == "play_pause":
            self.stage = "watch_playing"
            return ToolResult(ok=True, summary="playback active", data=self._state())
        return ToolResult(ok=False, summary=f"unknown browser action {action}", data={}, error="unknown_action")

    def _state(self) -> dict:
        base = {
            "has_chrome_window": True,
            "chrome_titles": ["Pal Pal - YouTube - Google Chrome"],
            "active_title": "Pal Pal - YouTube - Google Chrome",
            "active_browser_title": "Pal Pal - YouTube - Google Chrome",
            "is_browser_foreground": True,
            "chrome_path": "chrome.exe",
            "left": 10,
            "top": 10,
            "width": 1280,
            "height": 720,
            "right": 1290,
            "bottom": 730,
            "query": "pal pal",
            "target_tokens": ["pal"],
            "site": "youtube",
            "target_match": True,
        }
        if self.stage == "results":
            return {
                **base,
                "current_url": "https://www.youtube.com/results?search_query=pal+pal",
                "page_kind": "youtube_search_results",
                "is_search_results_page": True,
                "is_target_media_page": False,
                "playback_ui_state": "unknown",
                "ocr_text": "Pal Pal results Filters video song",
            }
        if self.stage == "watch_paused":
            return {
                **base,
                "current_url": "https://www.youtube.com/watch?v=abc123",
                "page_kind": "youtube_watch",
                "is_search_results_page": False,
                "is_target_media_page": True,
                "playback_ui_state": "paused",
                "ocr_text": "Pal Pal YouTube Play (k)",
            }
        return {
            **base,
            "current_url": "https://www.youtube.com/watch?v=abc123",
            "page_kind": "youtube_watch",
            "is_search_results_page": False,
            "is_target_media_page": True,
            "playback_ui_state": "playing",
            "ocr_text": "Pal Pal YouTube Pause (k)",
        }


class GenericBrowserTool(Tool):
    name = "browser"
    public = False
    description = "browser"
    input_schema = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}

    def __init__(self) -> None:
        self.stage = "search"
        self.calls: list[tuple[str, dict]] = []

    def run(self, args):
        action = str(args.get("action", ""))
        self.calls.append((action, dict(args)))
        if action == "inspect":
            return ToolResult(ok=True, summary=self.stage, data=self._state())
        if action == "status":
            return ToolResult(ok=True, summary=self.stage, data=self._state())
        if action == "focus":
            return ToolResult(ok=True, summary="Focused Chrome", data=self._state())
        if action == "search":
            self.stage = "search"
            return ToolResult(ok=True, summary="search", data=self._state())
        if action == "open_result":
            self.stage = "target"
            return ToolResult(ok=True, summary="target", data=self._state())
        return ToolResult(ok=False, summary=f"unknown browser action {action}", data={}, error="unknown_action")

    def _state(self) -> dict:
        base = {
            "has_chrome_window": True,
            "chrome_titles": ["NVIDIA - Google Chrome"],
            "active_title": "NVIDIA - Google Chrome",
            "active_browser_title": "NVIDIA - Google Chrome",
            "is_browser_foreground": True,
            "chrome_path": "chrome.exe",
            "left": 10,
            "top": 10,
            "width": 1280,
            "height": 720,
            "right": 1290,
            "bottom": 730,
            "query": "nvidia homepage",
            "target_tokens": ["nvidia", "homepage"],
        }
        if self.stage == "search":
            return {
                **base,
                "current_url": "https://www.google.com/search?q=nvidia+homepage",
                "page_kind": "google_search_results",
                "is_search_results_page": True,
                "is_target_media_page": False,
                "playback_ui_state": "unknown",
                "target_match": True,
                "ocr_text": "NVIDIA homepage Google Search results",
                "site": "google",
            }
        return {
            **base,
            "current_url": "https://www.nvidia.com/",
            "page_kind": "generic_page",
            "is_search_results_page": False,
            "is_target_media_page": False,
            "playback_ui_state": "unknown",
            "target_match": True,
            "ocr_text": "NVIDIA AI and accelerated computing",
            "site": "other",
        }


class AddressBarLoopBrowserTool(Tool):
    name = "browser"
    public = False
    description = "browser"
    input_schema = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}

    def __init__(self) -> None:
        self.stage = "pending_query"
        self.calls: list[tuple[str, dict]] = []

    def run(self, args):
        action = str(args.get("action", ""))
        self.calls.append((action, dict(args)))
        if action == "inspect":
            return ToolResult(ok=True, summary=self.stage, data=self._state())
        if action == "status":
            return ToolResult(ok=True, summary=self.stage, data=self._state())
        if action == "focus":
            return ToolResult(ok=True, summary="Focused Chrome", data=self._state())
        if action == "commit_address_bar":
            self.stage = "results"
            state = self._state()
            return ToolResult(ok=True, summary="Committed the address bar input.", data={**state, "action": "commit_address_bar"})
        if action == "dismiss_address_bar":
            state = self._state()
            state["address_bar_focused"] = False
            state["address_bar_input"] = ""
            state["focus_context"] = "page"
            return ToolResult(ok=True, summary="Returned browser focus to the page.", data={**state, "action": "dismiss_address_bar"})
        if action == "open_result":
            self.stage = "target"
            return ToolResult(ok=True, summary="target", data=self._state())
        if action == "search":
            self.stage = "results"
            return ToolResult(ok=True, summary="search", data=self._state())
        return ToolResult(ok=False, summary=f"unknown browser action {action}", data={}, error="unknown_action")

    def _state(self) -> dict:
        base = {
            "has_chrome_window": True,
            "chrome_titles": ["NVIDIA - Google Chrome"],
            "active_title": "NVIDIA - Google Chrome",
            "active_browser_title": "NVIDIA - Google Chrome",
            "is_browser_foreground": True,
            "chrome_path": "chrome.exe",
            "left": 10,
            "top": 10,
            "width": 1280,
            "height": 720,
            "right": 1290,
            "bottom": 730,
            "query": "nvidia homepage",
            "target_tokens": ["nvidia", "homepage"],
        }
        if self.stage == "pending_query":
            return {
                **base,
                "current_url": "nvidia homepage",
                "page_kind": "unknown",
                "is_search_results_page": False,
                "is_target_media_page": False,
                "playback_ui_state": "unknown",
                "target_match": False,
                "address_bar_focused": True,
                "address_bar_input": "nvidia homepage",
                "focus_context": "address_bar_query",
                "ocr_text": "nvidia homepage",
                "site": "google",
            }
        if self.stage == "results":
            return {
                **base,
                "current_url": "https://www.google.com/search?q=nvidia+homepage",
                "page_kind": "google_search_results",
                "is_search_results_page": True,
                "is_target_media_page": False,
                "playback_ui_state": "unknown",
                "target_match": True,
                "address_bar_focused": False,
                "address_bar_input": "",
                "focus_context": "page",
                "ocr_text": "NVIDIA homepage Google Search results",
                "site": "google",
            }
        return {
            **base,
            "current_url": "https://www.nvidia.com/",
            "page_kind": "generic_page",
            "is_search_results_page": False,
            "is_target_media_page": False,
            "playback_ui_state": "unknown",
            "target_match": True,
            "address_bar_focused": False,
            "address_bar_input": "",
            "focus_context": "page",
            "ocr_text": "NVIDIA AI and accelerated computing",
            "site": "other",
        }


class AddressBarLoopKeyboardTool(Tool):
    name = "keyboard"
    public = False
    description = "keyboard"
    input_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}, "keys": {"type": "string"}},
        "required": ["action"],
    }

    def __init__(self, browser: AddressBarLoopBrowserTool) -> None:
        self.browser = browser
        self.presses: list[str] = []

    def run(self, args):
        keys = str(args.get("keys", ""))
        self.presses.append(keys)
        if keys == "enter" and self.browser.stage == "pending_query":
            self.browser.stage = "results"
        return ToolResult(ok=True, summary=f"pressed {keys}", data={"action": args.get("action", ""), "keys": keys})


@dataclass
class FakeRetrieved:
    def to_system_context(self) -> str:
        return "Known project context"

    permanent_memories: list = None
    knowledge_chunks: list = None
    archived_chat_chunks: list = None
    graph_chunks: list = None


class FakeMemory:
    def retrieve(self, query: str):
        del query
        return FakeRetrieved([], [], [], [])

    def remember_task_event(self, task_id: str, goal: str, event_type: str, payload: dict):
        del task_id, goal, event_type, payload

    def learn_from_user_message(self, user_message: str):
        del user_message

    def load_session_messages(self):
        return []

    def persist_turn(self, messages):
        del messages

    def bootstrap_system_note(self):
        return "memory bootstrapped"

    @property
    def store(self):
        class StubStore:
            def recent(self, limit: int = 10):
                del limit
                return []

        return StubStore()

    @property
    def knowledge_chunks(self):
        return []

    def graph_search(self, query: str):
        del query
        return {"nodes": [], "edges": []}


class FakeValidator:
    def validate(self, steps, registry):
        del registry

        class Result:
            def __init__(self, steps):
                self.steps = steps

        return Result(steps)


class FakeDaemon:
    def __init__(self):
        self.started = 0

    def ensure_running(self):
        self.started += 1


def test_router_parses_background_execution_mode():
    router = IntentRouter(FakeClient())
    manifest = [{"name": "os_agent", "description": "OS agent", "args": {}, "required": [], "safety": "write"}]
    decision = router.plan("Open app and keep trying", manifest)
    assert decision.execution_mode == "foreground"
    assert decision.background_reason == ""
    assert decision.steps[0].tool == "os_agent"


def test_task_store_lifecycle(tmp_path: Path):
    store = TaskStore(tmp_path / "jakata.db")
    task = store.create_task(goal="demo", session_id="s1", success_criteria=["done"])
    assert task.status == "queued"
    claimed = store.claim_next_task("worker-1")
    assert claimed is not None
    assert claimed.status == "planning"
    store.append_event(task.id, "planned", {"hello": "world"})
    store.update_task(task.id, status="completed", result_summary="done")
    loaded = store.get_task(task.id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert store.list_events(task.id)[0].event_type == "planned"


def test_task_store_approval_lifecycle(tmp_path: Path):
    store = TaskStore(tmp_path / "jakata.db")
    task = store.create_task(goal="press enter", session_id="s1")
    gate = ApprovalGate(task_store=store, task=task)
    try:
        gate.require("keyboard", {"action": "press", "keys": "enter"}, "confirm")
    except ApprovalRequired as exc:
        approval_id = exc.request.id
    else:
        raise AssertionError("approval should be required")

    waiting = store.get_task(task.id)
    assert waiting is not None
    assert waiting.status == "awaiting_approval"
    assert waiting.pending_approval["id"] == approval_id

    approved = store.approve_pending(approval_id, actor="test")
    assert approved is not None
    assert approved.status == "queued"
    ApprovalGate(task_store=store, task=approved).require("keyboard", {"action": "press", "keys": "enter"}, "confirm")
    consumed = store.get_task(task.id)
    assert consumed is not None
    assert consumed.pending_approval == {}


def test_approval_gate_auto_safe_skips_safe_system_status(tmp_path: Path):
    store = TaskStore(tmp_path / "jakata.db")
    task = store.create_task(goal="show pc status", session_id="s1")
    gate = ApprovalGate(
        task_store=store,
        task=task,
        approval_policy="auto_safe",
        workspace_dir=tmp_path,
        data_dir=tmp_path / "data",
    )
    gate.require("system", {"action": "status"}, "snapshot")
    loaded = store.get_task(task.id)
    assert loaded is not None
    assert loaded.pending_approval == {}
    assert loaded.status == "queued"


def test_approval_gate_auto_safe_still_requires_shell(tmp_path: Path):
    store = TaskStore(tmp_path / "jakata.db")
    task = store.create_task(goal="run git status", session_id="s1")
    gate = ApprovalGate(task_store=store, task=task, approval_policy="auto_safe", workspace_dir=tmp_path)
    try:
        gate.require("shell", {"command": "git status"}, "inspect repo")
    except ApprovalRequired:
        waiting = store.get_task(task.id)
        assert waiting is not None
        assert waiting.status == "awaiting_approval"
    else:
        raise AssertionError("shell should still require approval in auto_safe mode")


def test_graph_store_search(tmp_path: Path):
    graph = GraphStore(tmp_path / "jakata.db")
    user_id = graph.upsert_node("person", "user")
    project_id = graph.upsert_node("project", "JAKATA")
    graph.upsert_edge(user_id, project_id, "works_on")
    found = graph.search("jakata")
    assert found["nodes"]
    assert any(item["label"] == "JAKATA" for item in found["nodes"])
    assert found["edges"]


def test_os_controller_rejects_keyboard_when_ocr_missing(tmp_path: Path):
    registry = ToolRegistry()
    registry.register(StubWindowTool())
    registry.register(StubScreenTool())
    registry.register(StubOCRTool(ok=False))
    registry.register(StubKeyboardTool())
    controller = OsController(FakeClient(), registry, str(tmp_path / "kill.switch"))
    result = controller.run_goal("Press enter in the app", repair_limit=0)
    assert not result.ok
    assert result.error == "ocr_uncertain"


def test_task_orchestrator_processes_background_task(tmp_path: Path):
    store = TaskStore(tmp_path / "jakata.db")
    tools = ToolRegistry()
    tools.register(StubOsAgentTool())
    router = IntentRouter(FakeClient())
    task = store.create_task(goal="Open demo app", session_id="s1", execution_mode="background")
    orchestrator = TaskOrchestrator(
        client=FakeClient(),
        router=router,
        tools=tools,
        validator=FakeValidator(),
        memory=FakeMemory(),
        task_store=store,
    )
    final_task = orchestrator.process_task(task)
    assert final_task.status == "completed"
    runs = store.list_agent_runs(task.id)
    roles = [run.role for run in runs]
    assert "researcher" in roles
    assert "executor" in roles
    assert "verifier" in roles


def test_task_orchestrator_accepts_self_verified_os_agent_result(tmp_path: Path):
    store = TaskStore(tmp_path / "jakata.db")
    tools = ToolRegistry()
    tools.register(StubVerifiedOsAgentTool())
    router = IntentRouter(FakeClient())
    task = store.create_task(goal="Open chrome and AI news", session_id="s1", execution_mode="background")
    orchestrator = TaskOrchestrator(
        client=FakeClient(),
        router=router,
        tools=tools,
        validator=FakeValidator(),
        memory=FakeMemory(),
        task_store=store,
    )
    final_task = orchestrator.process_task(task)
    assert final_task.status == "completed"
    assert "verified" in final_task.result_summary.lower()
    assert "Goal:" in final_task.final_report
    assert "Verified evidence:" in final_task.final_report
    events = store.list_events(task.id)
    assert any(event.event_type == "task_completed" for event in events)
    assert not any(event.event_type == "repair_planned" for event in events)


def test_task_completion_engine_runs_tool_task_with_report(tmp_path: Path):
    store = TaskStore(tmp_path / "jakata.db")
    tools = ToolRegistry()
    tools.register(StubVerifiedOsAgentTool())
    engine = TaskCompletionEngine(
        client=FakeClient(),
        router=IntentRouter(FakeClient()),
        tools=tools,
        validator=FakeValidator(),
        memory=FakeMemory(),
        task_store=store,
    )
    result = engine.run_foreground_task(goal="Open chrome and AI news", session_id="s1")
    assert result.task.status == "completed"
    assert "Goal: Open chrome and AI news" in result.report
    assert store.list_tasks(session_id="s1")[0].execution_mode == "foreground"


def test_telegram_auth_manager_unlocks_temporarily_and_rate_limits():
    auth = TelegramAuthManager(password="secret", session_ttl_minutes=1, guest_daily_limit=1)
    assert not auth.is_admin(7)
    assert auth.unlock(7, "secret")
    assert auth.is_admin(7)
    auth.lock(7)
    assert not auth.is_admin(7)
    assert auth.can_guest_chat(8)
    assert not auth.can_guest_chat(8)


def _artifact_settings(tmp_path: Path):
    workspace = tmp_path / "workspace"
    data = tmp_path / "data"
    workspace.mkdir(parents=True)
    data.mkdir(parents=True)
    return SimpleNamespace(
        workspace_dir=workspace.resolve(),
        data_dir=data.resolve(),
        telegram_safe_roots=[workspace.resolve(), data.resolve()],
        telegram_artifact_dir=(data / "telegram" / "artifacts").resolve(),
        telegram_upload_dir=(data / "telegram" / "uploads").resolve(),
        telegram_max_upload_mb=1,
        image_output_dir=(data / "generated" / "images").resolve(),
        image_size="1024x1024",
        telegram_admin_password="",
        telegram_admin_password_hash="",
        telegram_session_ttl_minutes=720,
        telegram_guest_daily_limit=50,
    )


class FakeTelegramMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.replies: list[str] = []
        self.documents: list[dict] = []
        self.photos: list[dict] = []

    async def reply_text(self, text: str):
        self.replies.append(text)

    async def reply_document(self, **kwargs):
        self.documents.append(kwargs)

    async def reply_photo(self, **kwargs):
        self.photos.append(kwargs)


def _fake_update(user_id: int = 1, text: str = ""):
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id), message=FakeTelegramMessage(text))


def test_telegram_start_admin_and_plain_help_onboard_users(tmp_path: Path):
    settings = _artifact_settings(tmp_path)
    store = TaskStore(tmp_path / "jakata.db")
    runtime = SimpleNamespace(settings=settings, task_store=store)
    auth = TelegramAuthManager(password="secret", guest_daily_limit=1)
    controller = TelegramBotController(runtime, auth=auth)

    update = _fake_update(1, "what can i type")
    asyncio.run(controller.start(update, SimpleNamespace(args=[])))
    assert "Guest mode" in update.message.replies[-1]
    assert "/admin" in update.message.replies[-1]

    asyncio.run(controller.admin(update, SimpleNamespace(args=[])))
    assert "/unlock <password>" in update.message.replies[-1]

    asyncio.run(controller.message(update, SimpleNamespace(args=[])))
    assert "Guest mode" in update.message.replies[-1]
    assert auth._guest_counts == {}

    asyncio.run(controller.unlock(update, SimpleNamespace(args=["secret"])))
    assert "Admin mode unlocked" in update.message.replies[-1]
    assert "/sendfile <path>" in update.message.replies[-1]

    asyncio.run(controller.help(update, SimpleNamespace(args=[])))
    assert "JAKATA admin commands" in update.message.replies[-1]


def test_telegram_artifact_service_exports_reports_and_logs(tmp_path: Path):
    settings = _artifact_settings(tmp_path)
    store = TaskStore(tmp_path / "jakata.db")
    task = store.create_task(goal="demo report", session_id="s1")
    store.update_task(task.id, status="completed", result_summary="done", final_report="Goal: demo\nStatus: completed")
    store.append_event(task.id, "task_completed", {"token": "should-redact", "NVIDIA_API_KEY": "secret"})
    run = store.create_agent_run(task.id, "verifier", "completed")
    store.add_agent_message(run.id or 0, "verifier", "output", "ok")

    service = TelegramArtifactService(settings, store)
    md = service.export_task(task.id, "md")
    logs = service.export_task(task.id, "json")
    archive = service.export_task(task.id, "zip")

    assert Path(md.path).exists()
    assert Path(logs.path).exists()
    assert Path(archive.path).exists()
    assert "[REDACTED]" in Path(logs.path).read_text(encoding="utf-8")
    assert service.get_artifact(md.id) is not None


def test_telegram_artifact_service_safe_roots_and_oversize_manifest(tmp_path: Path):
    settings = _artifact_settings(tmp_path)
    service = TelegramArtifactService(settings)
    safe_file = settings.workspace_dir / "small.txt"
    safe_file.write_text("ok", encoding="utf-8")
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("outside", encoding="utf-8")
    big_file = settings.workspace_dir / "big.bin"
    big_file.write_bytes(b"x" * (settings.telegram_max_upload_mb * 1024 * 1024 + 1))

    assert service.is_safe_path(safe_file)
    assert not service.is_safe_path(outside_file)
    manifest = service.sendable_or_manifest(service.register_file(big_file, kind="pc_file"))
    assert manifest.kind == "manifest"
    assert "larger than the Telegram upload limit" in Path(manifest.path).read_text(encoding="utf-8")


def test_image_generation_tool_saves_png_from_b64(tmp_path: Path):
    png = b"\x89PNG\r\n\x1a\nfake"

    class FakeImages:
        def generate(self, **kwargs):
            assert kwargs["model"] == "fake-image-model"
            payload = base64.b64encode(png).decode("ascii")
            return SimpleNamespace(data=[SimpleNamespace(b64_json=payload)])

    class FakeImageClient:
        def __init__(self, **kwargs):
            del kwargs
            self.images = FakeImages()

    tool = ImageGenerationTool(
        api_key="key",
        base_url="https://example.com/v1",
        model="fake-image-model",
        output_dir=tmp_path,
        client_factory=FakeImageClient,
    )
    result = tool.run({"prompt": "blue cyber city"})
    assert result.ok
    assert Path(result.data["path"]).read_bytes() == png


def test_telegram_sendfile_outside_safe_root_requires_approval_then_sends(tmp_path: Path):
    settings = _artifact_settings(tmp_path)
    store = TaskStore(tmp_path / "jakata.db")
    runtime = SimpleNamespace(settings=settings, task_store=store, task_engine=None, tools=ToolRegistry())
    auth = TelegramAuthManager(password="secret")
    assert auth.unlock(1, "secret")
    controller = TelegramBotController(runtime, auth=auth)

    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("send me", encoding="utf-8")
    update = _fake_update(1)
    asyncio.run(controller.sendfile(update, SimpleNamespace(args=[str(outside_file)])))

    pending = store.list_pending_approvals()
    assert len(pending) == 1
    approval_id = pending[0].pending_approval["id"]
    assert "Approval required" in update.message.replies[-1]

    asyncio.run(controller.approve(update, SimpleNamespace(args=[approval_id])))
    assert update.message.documents
    completed = store.get_task(pending[0].id)
    assert completed is not None
    assert completed.status == "completed"


def test_telegram_img_command_sends_generated_photo(tmp_path: Path):
    settings = _artifact_settings(tmp_path)
    store = TaskStore(tmp_path / "jakata.db")
    image_path = settings.image_output_dir / "demo.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    class FakeImageTools:
        def execute(self, name, args):
            assert name == "image_generation"
            assert "prompt" in args
            return ToolResult(ok=True, summary="generated", data={"path": str(image_path), "model": "fake", "size": "1024x1024"})

    runtime = SimpleNamespace(settings=settings, task_store=store, task_engine=None, tools=FakeImageTools())
    auth = TelegramAuthManager(password="secret")
    assert auth.unlock(1, "secret")
    controller = TelegramBotController(runtime, auth=auth)
    update = _fake_update(1)

    asyncio.run(controller.img(update, SimpleNamespace(args=["blue", "city"])))
    assert update.message.photos


def test_background_task_notifier_reports_completion_once(tmp_path: Path):
    store = TaskStore(tmp_path / "jakata.db")
    task = store.create_task(goal="demo", session_id="s1")
    store.update_task(task.id, status="completed", result_summary="done")
    notifier = BackgroundTaskNotifier(session_id="s1")
    first = notifier.collect(store)
    second = notifier.collect(store)
    assert len(first) == 1
    assert "completed" in first[0]
    assert second == []


def test_real_agent_runs_foreground_until_bg_is_explicit(tmp_path: Path):
    store = TaskStore(tmp_path / "jakata.db")
    daemon = FakeDaemon()
    tools = ToolRegistry()
    tools.register(StubOsAgentTool())
    agent = JakataAgent(
        settings=SimpleNamespace(session_id="s1"),
        client=FakeClient(),
        tools=tools,
        memory=FakeMemory(),
        router=IntentRouter(FakeClient()),
        validator=FakeValidator(),
        task_store=store,
        daemon=daemon,
    )
    model, content = agent.reply("open chrome and ai news")
    assert model == "fake-model"
    assert content == "ok"
    assert daemon.started == 0
    assert store.list_tasks(session_id="s1") == []


def test_submit_background_task_queues_daemon_work(tmp_path: Path):
    store = TaskStore(tmp_path / "jakata.db")
    daemon = FakeDaemon()
    tools = ToolRegistry()
    tools.register(StubOsAgentTool())
    agent = JakataAgent(
        settings=SimpleNamespace(session_id="s1"),
        client=FakeClient(),
        tools=tools,
        memory=FakeMemory(),
        router=IntentRouter(FakeClient()),
        validator=FakeValidator(),
        task_store=store,
        daemon=daemon,
    )
    task_id = agent.submit_background_task("open chrome and ai news")
    assert task_id
    assert daemon.started == 1
    tasks = store.list_tasks(session_id="s1")
    assert len(tasks) == 1
    assert tasks[0].status == "queued"


def test_agent_stream_reply_uses_streaming_chunks(tmp_path: Path):
    store = TaskStore(tmp_path / "jakata.db")
    daemon = FakeDaemon()
    tools = ToolRegistry()
    agent = JakataAgent(
        settings=SimpleNamespace(session_id="s1"),
        client=FakeClient(),
        tools=tools,
        memory=FakeMemory(),
        router=IntentRouter(FakeClient()),
        validator=FakeValidator(),
        task_store=store,
        daemon=daemon,
    )
    chunks = list(agent.stream_reply("hey"))
    assert chunks == [("fake-model", "o"), ("fake-model", "k")]


def test_nvidia_stream_stops_after_partial_output_on_error():
    settings = SimpleNamespace(
        api_key="key",
        base_url="https://example.com/v1",
        timeout_seconds=1.0,
        max_retries=3,
        model_chain=["fake-model"],
    )
    client = NvidiaChatClient(settings)
    calls = {"count": 0}

    def create(**kwargs):
        del kwargs
        calls["count"] += 1

        def stream():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hey bud"))])
            raise RuntimeError("stream dropped")

        return stream()

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    chunks = list(client.stream_complete([{"role": "user", "content": "hi"}]))
    assert chunks == [("fake-model", "hey bud")]
    assert calls["count"] == 1


def test_nvidia_stream_retries_if_no_output_was_emitted():
    settings = SimpleNamespace(
        api_key="key",
        base_url="https://example.com/v1",
        timeout_seconds=1.0,
        max_retries=3,
        model_chain=["fake-model"],
    )
    client = NvidiaChatClient(settings)
    calls = {"count": 0}

    def create(**kwargs):
        del kwargs
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary failure")

        def stream():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="all good"))])

        return stream()

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    chunks = list(client.stream_complete([{"role": "user", "content": "hi"}]))
    assert chunks == [("fake-model", "all good")]
    assert calls["count"] == 2


def test_browser_tool_reuses_existing_chrome_window():
    registry = ToolRegistry()
    registry.register(StubWindowTool())
    registry.register(StubKeyboardTool())
    registry.register(StubClipboardTool())
    shell = StubShellTool()
    registry.register(shell)
    tool = BrowserTool(registry, chrome_path="")
    status = tool.run({"action": "status"})
    assert status.ok
    result = tool.run({"action": "search", "query": "AI news"})
    assert result.ok
    assert result.data["used_existing_window"] is True
    assert shell.commands == []
    assert "AI news" in result.data["query"]


def test_browser_tool_uses_playwright_backend_before_native_shell():
    registry = ToolRegistry()
    registry.register(StubWindowTool())
    registry.register(StubKeyboardTool())
    registry.register(StubClipboardTool())
    shell = StubShellTool()
    registry.register(shell)
    tool = BrowserTool(registry, chrome_path="", backend="playwright")
    calls: list[str] = []

    def fake_pw_goto(url: str, *, query: str = ""):
        calls.append(f"{url}|{query}")
        return ToolResult(
            ok=True,
            summary="playwright",
            data={
                "automation_backend": "playwright",
                "page_kind": "google_search_results",
                "current_url": url,
                "target_match": True,
            },
        )

    tool._pw_goto = fake_pw_goto  # type: ignore[method-assign]
    result = tool.run({"action": "search", "query": "AI news"})
    assert result.ok
    assert result.data["automation_backend"] == "playwright"
    assert calls == ["https://www.google.com/search?q=AI+news|AI news"]
    assert shell.commands == []


def test_browser_tool_inspect_classifies_youtube_results():
    registry = ToolRegistry()
    registry.register(BrowserMediaWindowTool())
    registry.register(StubKeyboardTool())
    registry.register(StubClipboardTool())
    tool = BrowserTool(registry, chrome_path="")
    tool._read_current_url = lambda: "https://www.youtube.com/results?search_query=pal+pal"  # type: ignore[method-assign]
    tool._read_browser_ocr = lambda: "Pal Pal results Filters videos"  # type: ignore[method-assign]
    result = tool.run({"action": "inspect", "query": "pal pal"})
    assert result.ok
    assert result.data["page_kind"] == "youtube_search_results"
    assert result.data["is_search_results_page"] is True
    assert result.data["target_match"] is True


def test_browser_tool_inspect_detects_pending_address_bar_query():
    registry = ToolRegistry()
    registry.register(BrowserMediaWindowTool())
    registry.register(StubKeyboardTool())
    registry.register(StubClipboardTool())
    tool = BrowserTool(registry, chrome_path="")
    tool._read_current_url = lambda: "pal pal song"  # type: ignore[method-assign]
    tool._read_browser_ocr = lambda: "pal pal song\nSearch Google or type a URL"  # type: ignore[method-assign]
    result = tool.run({"action": "inspect", "query": "pal pal"})
    assert result.ok
    assert result.data["address_bar_focused"] is True
    assert result.data["focus_context"] == "address_bar_query"
    assert result.data["target_match"] is False


def test_browser_tool_does_not_treat_visible_url_as_focused_address_bar():
    registry = ToolRegistry()
    registry.register(StubWindowTool())
    registry.register(StubKeyboardTool())
    registry.register(StubClipboardTool())
    tool = BrowserTool(registry, chrome_path="")
    tool._read_current_url = lambda: "https://www.nvidia.com/"  # type: ignore[method-assign]
    tool._read_browser_ocr = lambda: "https://www.nvidia.com/\nNVIDIA AI and accelerated computing"  # type: ignore[method-assign]
    result = tool.run({"action": "inspect", "query": "nvidia"})
    assert result.ok
    assert result.data["page_kind"] == "generic_page"
    assert result.data["address_bar_focused"] is False
    assert result.data["focus_context"] == "page"


def test_browser_tool_does_not_classify_normal_page_text_as_google_results():
    registry = ToolRegistry()
    registry.register(StubWindowTool())
    registry.register(StubKeyboardTool())
    registry.register(StubClipboardTool())
    tool = BrowserTool(registry, chrome_path="")
    tool._read_current_url = lambda: "https://www.nvidia.com/en-in/"  # type: ignore[method-assign]
    tool._read_browser_ocr = lambda: "NVIDIA AI Enterprise Google Search integrations and accelerated computing"  # type: ignore[method-assign]
    result = tool.run({"action": "inspect", "query": "nvidia"})
    assert result.ok
    assert result.data["page_kind"] == "generic_page"
    assert result.data["target_match"] is True


def test_browser_tool_classifies_youtube_watch_when_clipboard_url_is_stale():
    registry = ToolRegistry()
    registry.register(BrowserMediaWindowTool())
    registry.register(StubKeyboardTool())
    registry.register(StubClipboardTool())
    tool = BrowserTool(registry, chrome_path="")
    tool._read_current_url = lambda: "kernalagent.vercel.app"  # type: ignore[method-assign]
    tool._read_browser_ocr = lambda: "YouTube To Text\n0:00 / 3:28\nPal Pal with Talwiinder"  # type: ignore[method-assign]
    result = tool.run({"action": "inspect", "query": "pal pal"})
    assert result.ok
    assert result.data["page_kind"] == "youtube_watch"
    assert result.data["media_position_seconds"] == 0
    assert result.data["target_match"] is True


def test_browser_tool_play_pause_reports_playing_state():
    registry = ToolRegistry()
    keyboard = TrackingKeyboardTool()
    mouse = StubMouseTool()
    registry.register(BrowserMediaWindowTool())
    registry.register(keyboard)
    registry.register(mouse)
    registry.register(StubClipboardTool())
    tool = BrowserTool(registry, chrome_path="")
    states = [
        ToolResult(
            ok=True,
            summary="paused",
            data={
                "active_title": "Pal Pal - YouTube - Google Chrome",
                "page_kind": "youtube_watch",
                "playback_ui_state": "paused",
                "is_target_media_page": True,
                "target_match": True,
                "left": 10,
                "top": 10,
                "width": 1280,
                "height": 720,
            },
        ),
        ToolResult(
            ok=True,
            summary="playing",
            data={
                "active_title": "Pal Pal - YouTube - Google Chrome",
                "page_kind": "youtube_watch",
                "playback_ui_state": "playing",
                "is_target_media_page": True,
                "target_match": True,
                "left": 10,
                "top": 10,
                "width": 1280,
                "height": 720,
            },
        ),
    ]

    def fake_inspect(query: str = ""):
        del query
        return states.pop(0)

    tool._inspect = fake_inspect  # type: ignore[method-assign]
    result = tool.run({"action": "play_pause", "query": "pal pal"})
    assert result.ok
    assert result.summary == "Playback appears active."
    assert keyboard.presses[0] == "k"


def test_browser_tool_refresh_uses_native_shortcut():
    registry = ToolRegistry()
    keyboard = TrackingKeyboardTool()
    registry.register(BrowserMediaWindowTool())
    registry.register(keyboard)
    registry.register(StubClipboardTool())
    tool = BrowserTool(registry, chrome_path="")
    tool._inspect = lambda query="": ToolResult(  # type: ignore[method-assign]
        ok=True,
        summary="page",
        data={"active_title": "Pal Pal - YouTube - Google Chrome", "current_url": "https://www.youtube.com/watch?v=abc123"},
    )
    result = tool.run({"action": "refresh"})
    assert result.ok
    assert result.summary == "Refreshed Chrome."
    assert keyboard.presses[-1] == "f5"


def test_browser_tool_wait_for_text_uses_inspection_loop():
    registry = ToolRegistry()
    registry.register(BrowserMediaWindowTool())
    registry.register(StubKeyboardTool())
    registry.register(StubClipboardTool())
    tool = BrowserTool(registry, chrome_path="")
    states = [
        ToolResult(ok=True, summary="loading", data={"active_title": "Chrome", "current_url": "https://example.com", "ocr_text": "loading"}),
        ToolResult(ok=True, summary="ready", data={"active_title": "Chrome", "current_url": "https://example.com", "ocr_text": "dashboard ready"}),
    ]

    def fake_inspect(query: str = ""):
        del query
        return states.pop(0)

    tool._inspect = fake_inspect  # type: ignore[method-assign]
    result = tool.run({"action": "wait_for_text", "text": "dashboard ready", "timeout_seconds": 2})
    assert result.ok
    assert result.summary == "Observed browser text: dashboard ready"


def test_os_controller_browser_media_goal_reaches_playing_state(tmp_path: Path):
    registry = ToolRegistry()
    browser = SequencedBrowserTool()
    registry.register(browser)
    controller = OsController(FakeClient(), registry, str(tmp_path / "kill.switch"))
    result = controller.run_goal(
        "play pal pal on youtube",
        success_criteria=[
            "The Pal Pal YouTube video page is open",
            "Playback is active rather than search results",
        ],
        repair_limit=3,
    )
    assert result.ok
    actions = [name for name, _ in browser.calls]
    assert "open_result" in actions
    assert "play_pause" in actions
    assert result.data["reason"] == "verified"


def test_os_controller_generic_browser_goal_does_not_stop_at_results(tmp_path: Path):
    registry = ToolRegistry()
    browser = GenericBrowserTool()
    registry.register(browser)
    controller = OsController(FakeClient(), registry, str(tmp_path / "kill.switch"))
    result = controller.run_goal(
        "open the NVIDIA homepage in chrome",
        success_criteria=["The NVIDIA homepage is open", "Chrome is not left on search results"],
        repair_limit=2,
    )
    assert result.ok
    actions = [name for name, _ in browser.calls]
    assert "open_result" in actions
    assert result.data["reason"] == "verified"


def test_os_controller_browser_goal_ignores_negative_youtube_criteria(tmp_path: Path):
    controller = OsController(FakeClient(), ToolRegistry(), str(tmp_path / "kill.switch"))
    goal_state = controller._classify_browser_goal(  # type: ignore[attr-defined]
        "open the NVIDIA homepage in chrome",
        ["Chrome is not left on Google or YouTube search results"],
    )
    assert goal_state["site"] == "web"
    verdict = controller._verify_browser_goal(  # type: ignore[attr-defined]
        goal_state,
        {
            "browser": {
                "has_chrome_window": True,
                "is_browser_foreground": True,
                "current_url": "https://www.youtube.com/@NVIDIA",
                "page_kind": "generic_page",
                "is_search_results_page": False,
                "target_match": True,
                "focus_context": "page",
                "playback_ui_state": "unknown",
            }
        },
        ["[browser] NVIDIA - YouTube"],
    )
    assert verdict is not None
    assert verdict["ok"] is False
    assert verdict["reason"] == "verifier_rejected"


def test_os_controller_commits_pending_address_bar_query_before_search_retry(tmp_path: Path):
    registry = ToolRegistry()
    browser = AddressBarLoopBrowserTool()
    registry.register(browser)
    controller = OsController(FakeClient(), registry, str(tmp_path / "kill.switch"))
    result = controller.run_goal(
        "open the NVIDIA homepage in chrome",
        success_criteria=["The NVIDIA homepage is open", "Chrome is not left on search results"],
        repair_limit=3,
    )
    assert result.ok
    actions = [name for name, _ in browser.calls]
    assert "search" not in actions
    assert "commit_address_bar" in actions
    assert "open_result" in actions
    assert result.data["reason"] == "verified"


def test_os_controller_breaks_repeated_browser_search_with_result_open(tmp_path: Path):
    controller = OsController(FakeClient(), ToolRegistry(), str(tmp_path / "kill.switch"))
    actions = controller._plan_browser_recovery(  # type: ignore[attr-defined]
        goal_state={"kind": "open_page", "query": "nvidia", "url": "", "site": "web"},
        system_state={
            "browser": {
                "has_chrome_window": True,
                "is_browser_foreground": True,
                "current_url": "https://www.google.com/search?q=nvidia",
                "page_kind": "google_search_results",
                "is_search_results_page": True,
                "target_match": True,
                "focus_context": "page",
            }
        },
        previous_observations=[],
        executed=[
            {"tool": "browser", "args": {"action": "search", "query": "nvidia"}, "ok": True},
            {"tool": "browser", "args": {"action": "dismiss_address_bar", "query": "nvidia"}, "ok": True},
            {"tool": "browser", "args": {"action": "search", "query": "nvidia"}, "ok": True},
            {"tool": "browser", "args": {"action": "dismiss_address_bar", "query": "nvidia"}, "ok": True},
        ],
    )
    assert actions
    assert actions[0].tool == "browser"
    assert actions[0].args["action"] == "open_result"


def test_detect_chrome_path_prefers_existing_configured_path(tmp_path: Path):
    fake = tmp_path / "chrome.exe"
    fake.write_text("x", encoding="utf-8")
    assert detect_chrome_path(str(fake)) == str(fake)


def test_os_controller_does_not_preverify_when_chrome_is_background(tmp_path: Path):
    registry = ToolRegistry()
    registry.register(BackgroundChromeWindowTool())
    registry.register(StubScreenTool())
    registry.register(StubOCRTool(ok=True))
    registry.register(StubKeyboardTool())
    registry.register(StubClipboardTool())
    registry.register(StubShellTool())
    registry.register(BrowserTool(registry, chrome_path=""))
    controller = OsController(FakeClient(), registry, str(tmp_path / "kill.switch"))
    result = controller.run_goal("open chrome and ai news", repair_limit=0)
    assert not result.ok
    assert result.error == "unmet_precondition"


def test_os_controller_treats_modal_popup_as_blocker_and_recovers(tmp_path: Path):
    registry = ToolRegistry()
    keyboard = TrackingKeyboardTool()
    registry.register(PopupWindowTool())
    registry.register(StubScreenTool())
    registry.register(PopupOCRTool())
    registry.register(keyboard)
    registry.register(StubMouseTool())
    controller = OsController(FakeClient(), registry, str(tmp_path / "kill.switch"))
    result = controller.run_goal(
        "Save the poem to poem.txt and overwrite the existing file if asked",
        success_criteria=["poem.txt is saved", "no confirmation dialog is left open"],
        repair_limit=2,
    )
    assert result.ok
    assert keyboard.presses[:2] == ["left", "enter"]
    assert result.data["reason"] == "verified"


def test_system_tool_wait_and_list_processes():
    tool = SystemTool()
    waited = tool.run({"action": "wait", "seconds": 0})
    assert waited.ok
    listed = tool.run({"action": "list_processes", "max_results": 3})
    assert listed.ok
    assert listed.data["count"] <= 3


def test_system_tool_status_aggregates_machine_signals():
    tool = SystemTool()
    tool._machine_status = lambda: ToolResult(  # type: ignore[method-assign]
        ok=True,
        summary="machine",
        data={"action": "status", "platform": "Windows", "battery_present": True, "battery_percent": 92, "on_ac_power": True, "process_count": 187, "uptime_minutes": 55},
    )
    tool._volume = lambda operation, args: ToolResult(ok=True, summary="volume", data={"action": "volume", "level": 38, "muted": False})  # type: ignore[method-assign]
    tool._brightness = lambda operation, args: ToolResult(ok=True, summary="brightness", data={"action": "brightness", "level": 61})  # type: ignore[method-assign]
    tool._bluetooth = lambda operation: ToolResult(ok=True, summary="bluetooth", data={"action": "bluetooth", "state": "On", "name": "Intel"})  # type: ignore[method-assign]
    result = tool.run({"action": "status"})
    assert result.ok
    assert "battery 92% (AC)" in result.summary
    assert result.data["volume_level"] == 38
    assert result.data["brightness_level"] == 61
    assert result.data["bluetooth_state"] == "On"


def test_system_tool_find_process_filters_matches():
    tool = SystemTool()
    tool._list_processes = lambda max_results: ToolResult(  # type: ignore[method-assign]
        ok=True,
        summary="listed",
        data={
            "action": "list_processes",
            "processes": [
                {"name": "chrome", "pid": 101, "window": "AI news - Google Chrome"},
                {"name": "code", "pid": 202, "window": "Visual Studio Code"},
            ],
        },
    )
    result = tool.run({"action": "find_process", "target": "chrome"})
    assert result.ok
    assert result.data["running"] is True
    assert result.data["count"] == 1
    assert result.data["matches"][0]["pid"] == 101


def test_system_tool_is_public_for_router_manifest():
    tool = SystemTool()
    assert tool.public is True


def test_system_tool_routes_volume_action_without_retrying_shell():
    original_platform = system_control.PLATFORM
    system_control.PLATFORM = "Windows"
    try:
        tool = SystemTool()
        seen: list[tuple[str, str]] = []

        def fake_run_windows_json(script: str, action: str, operation: str) -> ToolResult:
            seen.append((action, operation))
            assert "[Audio.AudioManager]" in script
            return ToolResult(ok=True, summary="Volume 42% (muted=False).", data={"action": "volume", "level": 42, "muted": False})

        tool._run_windows_json = fake_run_windows_json  # type: ignore[method-assign]
        result = tool.run({"action": "volume", "operation": "up", "step": 5})
        assert result.ok
        assert seen == [("volume", "up")]
        assert result.data["level"] == 42
    finally:
        system_control.PLATFORM = original_platform


def test_system_tool_routes_bluetooth_action():
    original_platform = system_control.PLATFORM
    system_control.PLATFORM = "Windows"
    try:
        tool = SystemTool()
        seen: list[tuple[str, str]] = []

        def fake_run_windows_json(script: str, action: str, operation: str) -> ToolResult:
            seen.append((action, operation))
            assert "Radio" in script
            return ToolResult(ok=True, summary="Bluetooth is on.", data={"action": "bluetooth", "state": "On", "name": "Intel Wireless Bluetooth"})

        tool._run_windows_json = fake_run_windows_json  # type: ignore[method-assign]
        result = tool.run({"action": "bluetooth", "operation": "on"})
        assert result.ok
        assert seen == [("bluetooth", "on")]
        assert result.data["state"] == "On"
    finally:
        system_control.PLATFORM = original_platform


def test_system_tool_volume_summary_uses_before_and_after():
    summary = SystemTool._summary_from_payload(  # type: ignore[attr-defined]
        {
            "action": "volume",
            "operation": "down",
            "before": 78,
            "level": 58,
            "before_muted": False,
            "muted": False,
        }
    )
    assert summary == "Volume decreased from 78% to 58%."


def test_system_tool_brightness_summary_uses_before_and_after():
    summary = SystemTool._summary_from_payload(  # type: ignore[attr-defined]
        {
            "action": "brightness",
            "operation": "up",
            "before": 40,
            "level": 50,
        }
    )
    assert summary == "Brightness increased from 40% to 50%."


def test_agent_direct_tool_reply_prefers_system_summary():
    reply = JakataAgent._direct_tool_reply(  # type: ignore[attr-defined]
        [
            {
                "tool": "system",
                "ok": True,
                "summary": "Volume decreased from 78% to 58%.",
                "rendered": "Volume: 58%",
                "error": None,
            }
        ]
    )
    assert reply == "Volume decreased from 78% to 58%."


def test_fallback_text_client_uses_secondary_backend():
    class FailingClient:
        def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
            del system_prompt, user_prompt, temperature
            raise RuntimeError("boom")

    class WorkingClient:
        def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
            del system_prompt, user_prompt, temperature
            return "fallback-model", '{"ok": true}'

    client = FallbackTextClient(FailingClient(), WorkingClient())
    model, content = client.complete_text("sys", "user")
    assert model == "fallback-model"
    assert content == '{"ok": true}'


if __name__ == "__main__":
    import tempfile

    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            if "tmp_path" in fn.__code__.co_varnames:
                fn(Path(tempfile.mkdtemp()))
            else:
                fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
