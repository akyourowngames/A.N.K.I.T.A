"""AI image generation via NVIDIA NIM."""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any, Dict
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json


_ROOT = Path.cwd()
_SCREENSHOTS_DIR = _ROOT / "screenshots"
_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_IMAGE_MODEL = (
    os.getenv("NVIDIA_IMAGE_MODEL", "stabilityai/stable-diffusion-3-medium").strip()
    or "stabilityai/stable-diffusion-3-medium"
)
DEFAULT_NEGATIVE_PROMPT = os.getenv(
    "NVIDIA_IMAGE_NEGATIVE_PROMPT",
    "blurry, low quality, distorted, ugly",
).strip()

_STYLE_SUFFIXES = {
    "realistic": "photorealistic, 8k, highly detailed",
    "anime": "anime style, vibrant colors, detailed illustration",
    "digital-art": "digital art, concept art, detailed illustration",
    "sketch": "pencil sketch, hand-drawn, detailed linework",
    "cinematic": "cinematic lighting, movie still, dramatic",
}

_LEGACY_MODEL_TO_STYLE = {
    "flux": "digital-art",
    "turbo": "digital-art",
    "gptimage": "realistic",
    "kontext": "digital-art",
    "seedream": "digital-art",
    "nanobanana": "digital-art",
    "nanobanana-pro": "digital-art",
    "flux-realism": "realistic",
    "flux-anime": "anime",
    "flux-3d": "cinematic",
    "dreamshaper": "digital-art",
}


def _nvidia_image_url(model: str) -> str:
    explicit = os.getenv("NVIDIA_IMAGE_ENDPOINT", "").strip()
    if explicit:
        return explicit
    clean_model = model.strip().strip("/")
    return f"https://ai.api.nvidia.com/v1/genai/{clean_model}"


def _resolve_style(model: str | None = None, style: str | None = None) -> str:
    candidate = (style or "").strip().lower()
    if candidate in _STYLE_SUFFIXES:
        return candidate
    candidate = (model or "").strip().lower()
    return _LEGACY_MODEL_TO_STYLE.get(candidate, "digital-art")


def _resolve_model_name(model: str | None) -> str:
    env_model = os.getenv("NVIDIA_IMAGE_MODEL", "").strip()
    if env_model:
        return env_model
    candidate = (model or "").strip()
    if not candidate:
        return DEFAULT_IMAGE_MODEL
    if candidate.lower() in _LEGACY_MODEL_TO_STYLE:
        return DEFAULT_IMAGE_MODEL
    return candidate


def _build_prompt(prompt: str, style: str) -> str:
    suffix = _STYLE_SUFFIXES.get(style, "")
    if not suffix:
        return prompt
    return f"{prompt}, {suffix}"


def _default_output_path(output_path: str | None) -> Path:
    if output_path:
        return Path(output_path).expanduser().resolve()
    return _SCREENSHOTS_DIR / f"generated_{int(time.time())}.png"


def _aspect_ratio(width: int, height: int) -> str:
    candidates = [
        ("1:1", 1.0),
        ("16:9", 16 / 9),
        ("9:16", 9 / 16),
        ("4:3", 4 / 3),
        ("3:4", 3 / 4),
    ]
    ratio = (float(width) / float(height)) if height else 1.0
    return min(candidates, key=lambda item: abs(item[1] - ratio))[0]


def generate_image(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    model: str = DEFAULT_IMAGE_MODEL,
    output_path: str | None = None,
    style: str | None = None,
) -> Dict[str, Any]:
    """Generate an image with NVIDIA image generation API and save it locally."""
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"status": "error", "message": "prompt is required."}

    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        return {"status": "error", "message": "NVIDIA_API_KEY is not set."}

    style_name = _resolve_style(model=model, style=style)
    full_prompt = _build_prompt(prompt, style_name)
    save_path = _default_output_path(output_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    model_name = _resolve_model_name(model)
    payload = {
        "prompt": full_prompt,
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
        "aspect_ratio": _aspect_ratio(int(width), int(height)),
        "steps": int(os.getenv("NVIDIA_IMAGE_STEPS", "30")),
        "cfg_scale": float(os.getenv("NVIDIA_IMAGE_CFG_SCALE", "5")),
        "seed": int(os.getenv("NVIDIA_IMAGE_SEED", "0")),
    }

    request = Request(
        url=_nvidia_image_url(model_name),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ANKITA/1.0",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return {"status": "error", "message": f"HTTP {exc.code}: {body[:400]}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    if data.get("image"):
        image_bytes = base64.b64decode(data["image"])
        save_path.write_bytes(image_bytes)
    else:
        return {"status": "error", "message": "No image data in response."}

    return {
        "status": "success",
        "path": str(save_path),
        "absolute_path": str(save_path.resolve()),
        "FILE_PATH": str(save_path.resolve()),
        "prompt": prompt,
        "style": style_name,
        "model": model_name,
        "size": f"{width}x{height}",
        "bytes": save_path.stat().st_size,
        "provider": "nvidia",
        "finish_reason": data.get("finish_reason"),
        "seed": data.get("seed"),
    }


def list_image_models() -> Dict[str, Any]:
    """Return the active NVIDIA image model and local style presets."""
    return {
        "status": "success",
        "provider": "nvidia",
        "default_model": DEFAULT_IMAGE_MODEL,
        "endpoint": _nvidia_image_url(DEFAULT_IMAGE_MODEL),
        "styles": sorted(_STYLE_SUFFIXES.keys()),
        "legacy_model_aliases": sorted(_LEGACY_MODEL_TO_STYLE.keys()),
    }
