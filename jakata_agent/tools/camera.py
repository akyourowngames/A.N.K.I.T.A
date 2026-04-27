from __future__ import annotations

from typing import Any

from jakata_agent.camera import CameraSession
from jakata_agent.llm import NvidiaChatClient
from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


class CameraTool(Tool):
    name = "camera"
    description = (
        "Use the local webcam for detailed real-world visual understanding: capture frames, describe scenes, "
        "read visible text, inspect objects, troubleshoot what is in view, inventory items, and create grounded "
        "observations that pair well with memory, document, search_web, and weather."
    )
    public = True
    categories = ("vision", "grounding", "daily_life")
    aliases = ("webcam", "see this", "look around", "describe camera", "visual inspection")
    use_with = ("memory", "document", "search_web", "weather", "screen", "ocr")
    daily_uses = (
        "Describe a room, desk, object, outfit, food, package, appliance, label, or handwritten note in practical detail.",
        "Extract visible text from the camera view and explain what it likely means.",
        "Troubleshoot physical setup issues by listing visible evidence and uncertainty.",
        "Turn observations into notes, checklists, inventories, or document-ready descriptions.",
    )
    grounding = "Captures a fresh local webcam frame before analysis and returns the image path, model, prompt, and analysis."
    output_capabilities = ("image_path", "scene_description", "visible_text", "object_inventory", "uncertainty_notes")
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
            "mode": {
                "type": "string",
                "enum": ["general", "ocr", "inventory", "troubleshoot", "safety", "accessibility", "document"],
                "description": "Analysis lens for describe. general is balanced; ocr prioritizes visible text; document returns document-ready notes.",
            },
            "detail_level": {
                "type": "string",
                "enum": ["quick", "normal", "deep"],
                "description": "How much detail to request from the vision model. deep asks for exhaustive grounded detail.",
            },
            "focus": {
                "type": "string",
                "description": "Optional visual target to prioritize, such as 'the label', 'the desk', or 'anything unsafe'.",
            },
            "output_format": {
                "type": "string",
                "enum": ["prose", "bullets", "json"],
                "description": "Preferred response format for describe.",
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
            prompt = self._analysis_prompt(args)
            detail_level = self._detail_level(args.get("detail_level"))
            try:
                path = self.camera_session.snapshot()
                model, analysis = self.client.describe_image(
                    image_path=path,
                    user_prompt=prompt,
                    temperature=0.1,
                    max_tokens=self._max_tokens(detail_level),
                )
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, summary=f"Camera analysis failed: {exc}", data={}, error=str(exc))
            return ToolResult(
                ok=True,
                summary=analysis.strip(),
                data={
                    "action": "describe",
                    "path": path,
                    "prompt": prompt,
                    "mode": self._mode(args.get("mode")),
                    "detail_level": detail_level,
                    "focus": str(args.get("focus", "")).strip(),
                    "output_format": self._output_format(args.get("output_format")),
                    "analysis": analysis.strip(),
                    "model": model,
                    "active": self.camera_session.is_active,
                },
            )
        return ToolResult(ok=False, summary=f"Unknown camera action: {action}", data={}, error="unknown_action")

    @staticmethod
    def _mode(value: Any) -> str:
        mode = str(value or "general").strip().lower()
        return mode if mode in {"general", "ocr", "inventory", "troubleshoot", "safety", "accessibility", "document"} else "general"

    @staticmethod
    def _detail_level(value: Any) -> str:
        detail_level = str(value or "deep").strip().lower()
        return detail_level if detail_level in {"quick", "normal", "deep"} else "deep"

    @staticmethod
    def _output_format(value: Any) -> str:
        output_format = str(value or "bullets").strip().lower()
        return output_format if output_format in {"prose", "bullets", "json"} else "bullets"

    @staticmethod
    def _max_tokens(detail_level: str) -> int:
        return {"quick": 350, "normal": 750, "deep": 1300}.get(detail_level, 1300)

    def _analysis_prompt(self, args: dict[str, Any]) -> str:
        user_prompt = str(args.get("prompt", "")).strip()
        mode = self._mode(args.get("mode"))
        detail_level = self._detail_level(args.get("detail_level"))
        focus = str(args.get("focus", "")).strip()
        output_format = self._output_format(args.get("output_format"))
        mode_guidance = {
            "general": "Give a richly grounded scene description.",
            "ocr": "Prioritize every readable word, number, label, button, sign, screen, package, and handwritten mark.",
            "inventory": "List visible objects, their approximate locations, condition, grouping, and likely use.",
            "troubleshoot": "Identify visible evidence, likely causes, quick checks, and what cannot be confirmed from the image.",
            "safety": "Look for hazards, damage, blocked paths, risky placement, spills, heat/electrical risks, and urgency.",
            "accessibility": "Describe the scene for someone who cannot see it, including spatial layout and usable actions.",
            "document": "Return clean notes suitable for saving into a document, checklist, report, or inventory.",
        }[mode]
        detail_guidance = {
            "quick": "Be concise but specific.",
            "normal": "Be detailed enough for practical use.",
            "deep": "Be exhaustive: cover foreground, background, spatial layout, materials, colors, text, counts, state, relationships, uncertainty, and next useful actions.",
        }[detail_level]
        format_guidance = {
            "prose": "Use compact paragraphs.",
            "bullets": "Use short sectioned bullets.",
            "json": "Return valid JSON with keys: overview, visible_text, objects, spatial_layout, notable_details, uncertainty, suggested_next_steps.",
        }[output_format]
        parts = [
            mode_guidance,
            detail_guidance,
            format_guidance,
            "Do not invent hidden details. Mark uncertain observations as uncertain.",
            "Mention if the image is blurry, underexposed, cropped, mirrored, or too low resolution for a claim.",
        ]
        if focus:
            parts.append(f"Primary focus: {focus}.")
        if user_prompt:
            parts.append(f"User request: {user_prompt}")
        else:
            parts.append("User request: Describe what the camera sees right now in useful daily-life detail.")
        return "\n".join(parts)

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
