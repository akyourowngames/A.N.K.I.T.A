from __future__ import annotations

from typing import Any

from jakata_agent.camera import CameraSession
from jakata_agent.llm import NvidiaChatClient
from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


class CameraTool(Tool):
    name = "camera"
    description = "Use the local webcam to capture or describe what the camera currently sees."
    public = True
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "capture", "describe"],
                "description": "status: camera state. capture: save a frame. describe: analyze the current frame.",
            },
            "prompt": {
                "type": "string",
                "description": "Optional analysis instruction for describe. Example: 'What objects are visible?'",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(self, camera_session: CameraSession, client: NvidiaChatClient) -> None:
        self.camera_session = camera_session
        self.client = client

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "")).strip().lower()
        if action == "status":
            status = self.camera_session.status()
            summary = "Camera preview is live." if status.active else "Camera preview is off."
            if status.error:
                summary = f"{summary} Error: {status.error}"
            return ToolResult(
                ok=True,
                summary=summary,
                data={
                    "action": "status",
                    "active": status.active,
                    "device_index": status.device_index,
                    "latest_frame_path": status.latest_frame_path,
                    "last_frame_time": status.last_frame_time,
                    "error": status.error,
                },
            )
        if action == "capture":
            try:
                path = self.camera_session.snapshot()
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, summary=f"Camera capture failed: {exc}", data={}, error=str(exc))
            return ToolResult(
                ok=True,
                summary=f"Captured camera frame: {path}",
                data={"action": "capture", "path": path, "active": self.camera_session.is_active},
            )
        if action == "describe":
            prompt = str(args.get("prompt", "")).strip() or "Describe what the camera sees right now."
            try:
                path = self.camera_session.snapshot()
                model, analysis = self.client.describe_image(image_path=path, user_prompt=prompt)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, summary=f"Camera analysis failed: {exc}", data={}, error=str(exc))
            return ToolResult(
                ok=True,
                summary=analysis.strip(),
                data={
                    "action": "describe",
                    "path": path,
                    "prompt": prompt,
                    "analysis": analysis.strip(),
                    "model": model,
                    "active": self.camera_session.is_active,
                },
            )
        return ToolResult(ok=False, summary=f"Unknown camera action: {action}", data={}, error="unknown_action")

    def render(self, data: dict[str, Any]) -> str:
        action = str(data.get("action", "")).strip()
        if action == "status":
            return "Camera preview is live." if data.get("active") else "Camera preview is off."
        if action == "capture":
            return f"Captured frame: {data.get('path', '')}".strip()
        if action == "describe":
            model = str(data.get("model", "")).strip()
            analysis = str(data.get("analysis", "")).strip()
            return f"{analysis}\n(model: {model})".strip()
        return data.get("summary", "Camera action complete.")


def register_camera_tools(registry: ToolRegistry, camera_session: CameraSession, client: NvidiaChatClient) -> None:
    registry.register(CameraTool(camera_session, client))
