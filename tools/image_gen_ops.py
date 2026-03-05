"""image_gen_ops.py — AI image generation via Pollinations.ai

Pollinations.ai unified API (gen.pollinations.ai) — requires a free API key.
Get your key at: https://enter.pollinations.ai/ (free daily Pollen credits).
Set POLLINATIONS_API_KEY in your .env file.

Endpoint: GET https://gen.pollinations.ai/image/{encoded_prompt}?...
Returns: image bytes saved to Desktop.
"""

from __future__ import annotations

import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict

_DESKTOP = Path(os.path.expanduser("~")) / "Desktop"

AVAILABLE_MODELS = [
    "flux",
    "turbo",
    "gptimage",
    "kontext",
    "seedream",
    "nanobanana",
    "nanobanana-pro",
]


def generate_image(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    model: str = "flux",
    output_path: str | None = None,
) -> Dict[str, Any]:
    """Generate an image using the Pollinations.ai unified API (gen.pollinations.ai).

    Requires POLLINATIONS_API_KEY env var — get a free key at https://enter.pollinations.ai/

    Args:
        prompt:      Text description of the desired image.
        width:       Output width in pixels (default 1024). Recommended: 512, 768, 1024.
        height:      Output height in pixels (default 1024).
        model:       Model to use. One of: flux, turbo, gptimage, kontext, seedream, nanobanana, nanobanana-pro.
        output_path: Optional absolute path to save the image. Defaults to Desktop.

    Returns:
        {"status": "success", "path": "...", "url": "...", "prompt": "...", "model": "...", "size": "...", "bytes": N}
        {"status": "error", "message": "..."}
    """
    if not prompt or not prompt.strip():
        return {"status": "error", "message": "prompt is required."}

    api_key = os.getenv("POLLINATIONS_API_KEY", "")
    if not api_key:
        return {
            "status": "error",
            "message": (
                "POLLINATIONS_API_KEY is not set. "
                "Get a free key at https://enter.pollinations.ai/ and add it to your .env file."
            ),
        }

    prompt = prompt.strip()
    safe_model = model if model in AVAILABLE_MODELS else "flux"

    # Build new unified API URL
    encoded_prompt = urllib.parse.quote(prompt, safe="")
    seed = int(time.time()) % 1_000_000
    encoded_key = urllib.parse.quote(api_key, safe="")
    url = (
        f"https://gen.pollinations.ai/image/{encoded_prompt}"
        f"?model={safe_model}&width={int(width)}&height={int(height)}"
        f"&seed={seed}&key={encoded_key}"
    )

    # Determine output path
    if output_path:
        save_path = Path(output_path)
    else:
        _DESKTOP.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        save_path = _DESKTOP / f"ankita_img_{timestamp}.png"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ANKITA/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status != 200:
                return {"status": "error", "message": f"Pollinations.ai returned HTTP {resp.status}."}
            content_type = resp.headers.get("Content-Type", "")
            if "image" not in content_type and "video" not in content_type:
                return {
                    "status": "error",
                    "message": f"Unexpected content type from API: {content_type}. Try rephrasing your prompt.",
                }
            image_bytes = resp.read()

        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(image_bytes)

        return {
            "status": "success",
            "path": str(save_path),
            "url": url.split("&key=")[0],  # strip key from logged URL
            "prompt": prompt,
            "model": safe_model,
            "size": f"{width}x{height}",
            "bytes": len(image_bytes),
        }

    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def list_image_models() -> Dict[str, Any]:
    """Return the list of available image generation models with descriptions."""
    return {
        "status": "success",
        "models": AVAILABLE_MODELS,
        "descriptions": {
            "flux": "High quality general purpose model (recommended default)",
            "turbo": "Faster generation, slightly lower quality",
            "gptimage": "OpenAI GPT Image — photorealistic, high detail",
            "kontext": "Kontext — great for creative/stylized images",
            "seedream": "Seedream 5.0 — lightweight, fast generation",
            "nanobanana": "Nano banana (Gemini Flash) — high-speed generation",
            "nanobanana-pro": "Nano banana Pro — higher quality variant",
        },
        "default": "flux",
    }
