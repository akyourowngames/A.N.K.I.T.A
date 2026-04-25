from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


def _import_pyautogui():
    try:
        import pyautogui

        pyautogui.FAILSAFE = True
        return pyautogui, None
    except ImportError:
        return None, "pyautogui not installed. Run: pip install pyautogui"


def _import_pytesseract():
    try:
        import pytesseract

        return pytesseract, None
    except ImportError:
        return None, "pytesseract not installed. Run: pip install pytesseract"


def _capture_with_imagegrab():
    try:
        from PIL import ImageGrab

        return ImageGrab.grab(), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


class ScreenTool(Tool):
    name = "screen"
    description = "Capture the current screen or a specific region for observation."
    public = False
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["capture", "capture_region"],
                "description": "capture: take a screenshot of the current desktop. capture_region: take a screenshot of a screen region.",
            },
            "x": {"type": "integer", "description": "Region left coordinate for action=capture_region."},
            "y": {"type": "integer", "description": "Region top coordinate for action=capture_region."},
            "width": {"type": "integer", "description": "Region width for action=capture_region."},
            "height": {"type": "integer", "description": "Region height for action=capture_region."},
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "capture")).strip()
        if action not in {"capture", "capture_region"}:
            return ToolResult(ok=False, summary=f"Unknown screen action: {action}", data={}, error="unknown_action")
        pyautogui, err = _import_pyautogui()
        image = None
        errors: list[str] = []
        try:
            if pyautogui is not None:
                image = pyautogui.screenshot()
            elif err:
                errors.append(err)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

        if image is None:
            image, grab_err = _capture_with_imagegrab()
            if grab_err:
                errors.append(grab_err)

        if image is None:
            detail = " | ".join(item for item in errors if item) or "unknown screen capture error"
            return ToolResult(ok=False, summary=f"Screenshot failed: {detail}", data={}, error=detail)

        if action == "capture_region":
            x = args.get("x")
            y = args.get("y")
            width = args.get("width")
            height = args.get("height")
            if x in (None, "") or y in (None, "") or width in (None, "") or height in (None, ""):
                return ToolResult(ok=False, summary="capture_region requires x, y, width, and height.", data={}, error="missing_region")
            left = int(x)
            top = int(y)
            region_width = max(1, int(width))
            region_height = max(1, int(height))
            image = image.crop((left, top, left + region_width, top + region_height))
            region = {"x": left, "y": top, "width": region_width, "height": region_height}
        else:
            region = {}

        path = Path(tempfile.gettempdir()) / f"jakata_screen_{next(tempfile._get_candidate_names())}.png"
        image.save(path)
        return ToolResult(
            ok=True,
            summary=f"Captured screenshot: {path}",
            data={"path": str(path), "action": action, "region": region},
        )


class OCRTool(Tool):
    name = "ocr"
    description = "Extract UI text from a screenshot, the current screen, or a specific region."
    public = False
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["extract_text", "extract_region_text"],
                "description": "extract_text: OCR a screenshot path or the active screen. extract_region_text: capture and OCR a screen region.",
            },
            "path": {
                "type": "string",
                "description": "Optional screenshot path. If omitted, captures a fresh screenshot first.",
            },
            "x": {"type": "integer", "description": "Region left coordinate for action=extract_region_text."},
            "y": {"type": "integer", "description": "Region top coordinate for action=extract_region_text."},
            "width": {"type": "integer", "description": "Region width for action=extract_region_text."},
            "height": {"type": "integer", "description": "Region height for action=extract_region_text."},
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(self, tesseract_cmd: str = "") -> None:
        self.tesseract_cmd = tesseract_cmd.strip()

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "extract_text")).strip()
        if action not in {"extract_text", "extract_region_text"}:
            return ToolResult(ok=False, summary=f"Unknown OCR action: {action}", data={}, error="unknown_action")
        pytesseract, err = _import_pytesseract()
        if err:
            return ToolResult(ok=False, summary=err, data={}, error="missing_dep")
        path = str(args.get("path", "")).strip()
        if not path:
            capture_args = {"action": "capture"}
            if action == "extract_region_text":
                capture_args = {
                    "action": "capture_region",
                    "x": args.get("x"),
                    "y": args.get("y"),
                    "width": args.get("width"),
                    "height": args.get("height"),
                }
            screen = ScreenTool().run(capture_args)
            if not screen.ok:
                return screen
            path = str(screen.data.get("path", ""))
        try:
            from PIL import Image

            if self.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
            text = pytesseract.image_to_string(Image.open(path))
            return ToolResult(
                ok=True,
                summary=f"OCR extracted {len(text)} chars.",
                data={
                    "action": action,
                    "path": path,
                    "text": text,
                    "tesseract_cmd": self.tesseract_cmd,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"OCR failed: {exc}", data={}, error=str(exc))


def register_screen_tools(registry: ToolRegistry, tesseract_cmd: str = "") -> None:
    registry.register(ScreenTool())
    registry.register(OCRTool(tesseract_cmd=tesseract_cmd))
