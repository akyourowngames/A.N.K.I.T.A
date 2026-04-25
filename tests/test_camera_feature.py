from __future__ import annotations

import sys
import types
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

from jakata_agent.cli import handle_camera_command, should_force_camera_analysis
from jakata_agent.tools.camera import CameraTool


class StubCameraStatus:
    def __init__(self, *, active: bool, error: str = "", latest_frame_path: str = "", last_frame_time: float = 0.0):
        self.active = active
        self.error = error
        self.latest_frame_path = latest_frame_path
        self.last_frame_time = last_frame_time
        self.device_index = 0
        self.frame_width = 960
        self.frame_height = 540


class StubCameraSession:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.snapshots = 0
        self._active = False
        self.path = str(ROOT / "dummy.txt")

    def start(self):
        self.started += 1
        self._active = True
        return StubCameraStatus(active=True, latest_frame_path=self.path, last_frame_time=1.0)

    def stop(self):
        self.stopped += 1
        self._active = False
        return StubCameraStatus(active=False)

    @property
    def is_active(self) -> bool:
        return self._active

    def status(self):
        return StubCameraStatus(active=self._active, latest_frame_path=self.path, last_frame_time=1.0)

    def snapshot(self) -> str:
        self.snapshots += 1
        return self.path


class StubVisionClient:
    def describe_image(self, *, image_path: str, user_prompt: str, system_prompt: str = "", temperature: float = 0.0, max_tokens: int = 0):
        del system_prompt, temperature, max_tokens
        return "vision-fast", f"vision[{Path(image_path).name}] {user_prompt}"


def test_camera_tool_describe_uses_snapshot_and_vision_client():
    session = StubCameraSession()
    tool = CameraTool(session, StubVisionClient())
    result = tool.run({"action": "describe", "prompt": "what do you see"})
    assert result.ok
    assert session.snapshots == 1
    assert result.data["model"] == "vision-fast"
    assert "what do you see" in result.summary


def test_camera_command_turns_preview_on():
    session = StubCameraSession()
    runtime = SimpleNamespace(camera_session=session, tools=None)
    handled, message = handle_camera_command("/camera", runtime)
    assert handled is True
    assert session.started == 1
    assert "opened" in (message or "").lower()


def test_camera_command_forces_analysis_through_tool_registry():
    session = StubCameraSession()

    class Tools:
        def execute(self, name: str, args: dict):
            assert name == "camera"
            assert args["action"] == "describe"
            return SimpleNamespace(summary="detected laptop on desk")

    runtime = SimpleNamespace(camera_session=session, tools=Tools())
    handled, message = handle_camera_command("/camera ask what is on the desk", runtime)
    assert handled is True
    assert message == "detected laptop on desk"


def test_force_camera_analysis_requires_live_session_and_prompt_match():
    session = StubCameraSession()
    runtime = SimpleNamespace(camera_session=session)
    assert not should_force_camera_analysis("what do you see right now", runtime)
    session.start()
    assert should_force_camera_analysis("what do you see right now", runtime)
    assert not should_force_camera_analysis("tell me a joke", runtime)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
