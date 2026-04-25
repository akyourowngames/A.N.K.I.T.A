from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.opening import OpenTargetResult, open_target
from jakata_agent.tools.registry import ToolRegistry


_NVIDIA_MIN_DIMENSION = 512
_NVIDIA_MAX_DIMENSION = 1568
_NVIDIA_DIMENSION_STEP = 16


def _open_file(path: Path) -> OpenTargetResult:
    return open_target(path, wait_seconds=2.0)


class ImageGenerationTool(Tool):
    name = "image_generation"
    description = (
        "Generate an image from a text prompt. Supports local OpenAI-compatible image endpoints and NVIDIA hosted GenAI "
        "visual endpoints. This tool saves the image and returns its file path; use open_path separately when the current user message asks to open it."
    )
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
        infer_url: str = "",
        model_namespace: str = "black-forest-labs",
        timeout_seconds: float = 60.0,
        client_factory: Callable[..., Any] = OpenAI,
        opener: Callable[[Path], None] = _open_file,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.output_dir = Path(output_dir)
        self.default_size = default_size
        self.infer_url = infer_url
        self.model_namespace = model_namespace
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory
        self.opener = opener

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("size", self.default_size)
        args.setdefault("open_after", False)
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        prompt = str(args.get("prompt", "")).strip()
        size = str(args.get("size", self.default_size)).strip() or self.default_size
        open_after = bool(args.get("open_after", False))
        if not prompt:
            return ToolResult(ok=False, summary="Image prompt is required.", data={}, error="missing_prompt")
        if not self.api_key:
            return ToolResult(ok=False, summary="NVIDIA_API_KEY is missing.", data={}, error="missing_api_key")
        if not self.model:
            return ToolResult(ok=False, summary="NVIDIA_IMAGE_MODEL is missing.", data={}, error="missing_model")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            image_data, provider = self._generate_image_bytes(prompt=prompt, size=size)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Image generation failed: {exc}", data={}, error="image_generation_failed")

        filename = f"{int(time.time())}-{self._slug(prompt)[:80]}.png"
        path = self.output_dir / filename
        path.write_bytes(image_data)
        opened = False
        open_verified = False
        open_method = ""
        open_details: dict[str, Any] = {}
        open_error = ""
        if open_after:
            try:
                opener_result = self.opener(path)
                if isinstance(opener_result, OpenTargetResult):
                    opened = opener_result.ok
                    open_verified = opener_result.verified
                    open_method = opener_result.method
                    open_error = opener_result.error
                    open_details = opener_result.as_dict()
                else:
                    opened = True
            except Exception as exc:  # noqa: BLE001
                open_error = str(exc)
        if open_after and not opened:
            summary = f"Generated image but could not open it: {path.name}"
        elif opened:
            summary = f"Generated and opened image: {path.name}" if open_verified else f"Generated image and sent open request: {path.name}"
        else:
            summary = f"Generated image: {path.name}"
        return ToolResult(
            ok=True,
            summary=summary,
            data={
                "path": str(path),
                "prompt": prompt,
                "model": self.model,
                "size": size,
                "mime_type": "image/png",
                "bytes": len(image_data),
                "provider": provider,
                "opened": opened,
                "open_verified": open_verified,
                "open_method": open_method,
                "open_error": open_error,
                "open_details": open_details,
            },
        )

    def render(self, data: dict[str, Any]) -> str:
        path = data.get("path", "")
        if data.get("opened"):
            if data.get("open_verified"):
                return f"Generated and opened image: {path}"
            return f"Generated image and sent open request: {path}"
        error = str(data.get("open_error", "")).strip()
        if error:
            return f"Generated image but could not open it: {path}\nopen error: {error}"
        return f"Generated image: {path}"

    def _generate_image_bytes(self, *, prompt: str, size: str) -> tuple[bytes, str]:
        if self._prefer_nvidia_hosted():
            return self._generate_with_nvidia_hosted(prompt=prompt, size=size), "nvidia_genai"
        try:
            return self._generate_with_openai_compatible(prompt=prompt, size=size), "openai_compatible"
        except Exception as exc:
            if not self._should_fallback_to_nvidia(exc):
                raise
            return self._generate_with_nvidia_hosted(prompt=prompt, size=size), "nvidia_genai"

    def _generate_with_openai_compatible(self, *, prompt: str, size: str) -> bytes:
        client = self.client_factory(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_seconds, max_retries=0)
        response = client.images.generate(
            model=self.model,
            prompt=prompt,
            size=size,
            response_format="b64_json",
        )
        return self._extract_image_bytes(response)

    def _generate_with_nvidia_hosted(self, *, prompt: str, size: str) -> bytes:
        width, height = self._parse_size(size)
        url = self._nvidia_infer_url()
        payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "samples": 1,
            "seed": 0,
            "steps": 4,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response_handle:  # noqa: S310
                response = json.loads(response_handle.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{exc.code} {exc.reason}: {detail[:500]}") from exc
        return self._extract_image_bytes(response)

    def _nvidia_infer_url(self) -> str:
        if self.infer_url.strip():
            return self.infer_url.strip()
        model_path = self._nvidia_model_path()
        return f"https://ai.api.nvidia.com/v1/genai/{model_path}"

    def _nvidia_model_path(self) -> str:
        model = self.model.strip().strip("/")
        if "/" in model:
            return model
        namespace = self.model_namespace.strip().strip("/") or "black-forest-labs"
        return f"{namespace}/{model}"

    def _prefer_nvidia_hosted(self) -> bool:
        parsed = urllib.parse.urlparse(self.base_url)
        host = parsed.netloc.lower()
        return host.endswith("api.nvidia.com")

    @staticmethod
    def _should_fallback_to_nvidia(exc: Exception) -> bool:
        text = str(exc).lower()
        return "404" in text or "not found" in text or "unsupported" in text

    @staticmethod
    def _parse_size(size: str) -> tuple[int, int]:
        match = re.match(r"^\s*(\d+)\s*x\s*(\d+)\s*$", size)
        if not match:
            return 1024, 1024
        return ImageGenerationTool._snap_nvidia_dimension(int(match.group(1))), ImageGenerationTool._snap_nvidia_dimension(int(match.group(2)))

    @staticmethod
    def _snap_nvidia_dimension(value: int) -> int:
        clamped = max(_NVIDIA_MIN_DIMENSION, min(value, _NVIDIA_MAX_DIMENSION))
        steps = round((clamped - _NVIDIA_MIN_DIMENSION) / _NVIDIA_DIMENSION_STEP)
        return _NVIDIA_MIN_DIMENSION + steps * _NVIDIA_DIMENSION_STEP

    @staticmethod
    def _extract_image_bytes(response: Any) -> bytes:
        data = getattr(response, "data", None)
        if not data and isinstance(response, dict):
            data = response.get("data")
        if not data:
            artifacts = getattr(response, "artifacts", None)
            if artifacts is None and isinstance(response, dict):
                artifacts = response.get("artifacts")
            if artifacts:
                first_artifact = artifacts[0]
                b64_artifact = getattr(first_artifact, "base64", None)
                if b64_artifact is None and isinstance(first_artifact, dict):
                    b64_artifact = first_artifact.get("base64")
                if b64_artifact:
                    return base64.b64decode(str(b64_artifact))
            raise RuntimeError("image response did not include data or artifacts")
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
        raise RuntimeError("image response did not include b64_json, url, or artifacts")

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
    infer_url: str = "",
    model_namespace: str = "black-forest-labs",
    timeout_seconds: float = 60.0,
) -> None:
    registry.register(
        ImageGenerationTool(
            api_key=api_key,
            base_url=base_url,
            model=model,
            output_dir=output_dir,
            default_size=default_size,
            infer_url=infer_url,
            model_namespace=model_namespace,
            timeout_seconds=timeout_seconds,
        )
    )
