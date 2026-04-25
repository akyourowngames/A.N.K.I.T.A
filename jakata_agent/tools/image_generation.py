from __future__ import annotations

import base64
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


class ImageGenerationTool(Tool):
    name = "image_generation"
    description = "Generate an image from a text prompt through NVIDIA OpenAI-compatible image generation."
    safety = "write"
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Detailed image prompt."},
            "size": {"type": "string", "description": "Image size such as 1024x1024."},
        },
        "required": ["prompt"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        output_dir: str | Path,
        default_size: str = "1024x1024",
        timeout_seconds: float = 60.0,
        client_factory: Callable[..., Any] = OpenAI,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.output_dir = Path(output_dir)
        self.default_size = default_size
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("size", self.default_size)
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        prompt = str(args.get("prompt", "")).strip()
        size = str(args.get("size", self.default_size)).strip() or self.default_size
        if not prompt:
            return ToolResult(ok=False, summary="Image prompt is required.", data={}, error="missing_prompt")
        if not self.api_key:
            return ToolResult(ok=False, summary="NVIDIA_API_KEY is missing.", data={}, error="missing_api_key")
        if not self.model:
            return ToolResult(ok=False, summary="NVIDIA_IMAGE_MODEL is missing.", data={}, error="missing_model")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = self.client_factory(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_seconds, max_retries=0)
            response = client.images.generate(
                model=self.model,
                prompt=prompt,
                size=size,
                response_format="b64_json",
            )
            image_data = self._extract_image_bytes(response)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Image generation failed: {exc}", data={}, error="image_generation_failed")

        filename = f"{int(time.time())}-{self._slug(prompt)[:80]}.png"
        path = self.output_dir / filename
        path.write_bytes(image_data)
        return ToolResult(
            ok=True,
            summary=f"Generated image: {path.name}",
            data={
                "path": str(path),
                "prompt": prompt,
                "model": self.model,
                "size": size,
                "mime_type": "image/png",
                "bytes": len(image_data),
            },
        )

    def render(self, data: dict[str, Any]) -> str:
        return f"Generated image: {data.get('path', '')}"

    @staticmethod
    def _extract_image_bytes(response: Any) -> bytes:
        data = getattr(response, "data", None)
        if not data and isinstance(response, dict):
            data = response.get("data")
        if not data:
            raise RuntimeError("image response did not include data")
        first = data[0]
        b64_json = getattr(first, "b64_json", None)
        if b64_json is None and isinstance(first, dict):
            b64_json = first.get("b64_json")
        if b64_json:
            return base64.b64decode(str(b64_json))
        url = getattr(first, "url", None)
        if url is None and isinstance(first, dict):
            url = first.get("url")
        if url:
            with urllib.request.urlopen(str(url), timeout=60) as response_handle:  # noqa: S310
                return response_handle.read()
        raise RuntimeError("image response did not include b64_json or url")

    @staticmethod
    def _slug(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
        return cleaned or "image"


def register_image_generation_tool(
    registry: ToolRegistry,
    *,
    api_key: str,
    base_url: str,
    model: str,
    output_dir: str | Path,
    default_size: str = "1024x1024",
    timeout_seconds: float = 60.0,
) -> None:
    registry.register(
        ImageGenerationTool(
            api_key=api_key,
            base_url=base_url,
            model=model,
            output_dir=output_dir,
            default_size=default_size,
            timeout_seconds=timeout_seconds,
        )
    )
