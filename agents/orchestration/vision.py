"""Vision packet handling for orchestration."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from llm import LLMRuntime
from llm.client import build_vision_runtime_from_env, call_chat_with_image

from .shared import _LAST_VISION_CACHE


def describe_vision_packets_as_text(vision_packets: List[Dict[str, Any]], vision_runtime: LLMRuntime) -> None:
    for packet in vision_packets:
        try:
            b64 = None
            packet_mime = packet.get("_mime_type", "image/jpeg")
            is_screen = packet_mime == "image/png" or "screen" in str(packet.get("_tool_name", ""))
            if is_screen:
                text_prompt = (
                    "You are analysing a screenshot of a computer screen. "
                    "IMPORTANT: You MUST describe what you see. Do not refuse or say the image is too large. "
                    "Describe: (1) what application or website is open, (2) what text, content, or UI elements are visible, "
                    "(3) any errors, notifications, or important information on screen. "
                    "Be specific. Start with 'I can see on the screen...'"
                )
            else:
                text_prompt = (
                    "You are analysing a webcam photo. "
                    "IMPORTANT: You MUST describe what you see. Do not refuse or say the image is too large. "
                    "Describe: (1) the person — face, expression, hair, clothing, what they are doing, "
                    "(2) the background — room, objects, lighting, (3) anything else visible. "
                    "Be specific and detailed. Start with 'I can see...'"
                )
            for block in packet.get("content", []):
                if block.get("type") == "image_url":
                    url_str = block["image_url"].get("url", "")
                    if "base64," in url_str:
                        b64 = url_str.split("base64,")[1]
                    elif len(url_str) > 100:
                        b64 = url_str
                elif block.get("type") == "text":
                    text_prompt = block.get("text", text_prompt)
            if b64:
                description = call_chat_with_image(
                    vision_runtime,
                    text_prompt,
                    b64,
                    max_tokens=600,
                    temperature=0.2,
                    mime_type=packet_mime,
                )
                print(f"[VisionPipeline] Image described ({len(description)} chars)", flush=True)
                packet["_description"] = description
            else:
                packet["_description"] = "[Image was captured but could not be decoded for vision analysis]"
        except Exception as vision_err:
            print(f"[VisionPipeline] call_chat_with_image failed: {vision_err}", flush=True)
            packet["_description"] = f"[Vision analysis failed: {vision_err}]"


def handle_vision_result(
    tool_call: Dict[str, Any],
    result: Any,
    inner: Any,
    b64_source: Dict[str, Any],
    vision_packets: List[Dict[str, Any]],
) -> str:
    b64_data = b64_source["base64"]
    tool_name = tool_call.get("function", {}).get("name", "")
    image_mime = "image/jpeg" if tool_name == "capture_webcam" else "image/png"
    _LAST_VISION_CACHE.clear()
    _LAST_VISION_CACHE.update({"b64": b64_data, "mime": image_mime, "ts": time.time()})
    clean_inner = {key: value for key, value in b64_source.items() if key != "base64"}
    clean_inner["base64"] = "<IMAGE_DATA_INJECTED_AS_VISION_MESSAGE>"
    safe_result = {**result, "result": clean_inner} if b64_source is inner else clean_inner
    packet_b64 = b64_data
    packet_mime = image_mime
    if len(packet_b64) > 200_000:
        try:
            import base64
            from io import BytesIO

            from PIL import Image

            raw = base64.b64decode(packet_b64)
            image = Image.open(BytesIO(raw)).convert("RGB")
            width, height = image.size
            if width > 480:
                image = image.resize((480, int(height * 480 / width)), Image.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=50)
            packet_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            packet_mime = "image/jpeg"
            print(f"[VisionPacket] Packet re-compressed to 480px/q50 ({len(packet_b64):,} chars)", flush=True)
        except Exception as packet_err:
            print(f"[VisionPacket] ⚠️  Re-compress failed: {packet_err}", flush=True)
    vision_packets.append(
        {
            "role": "user",
            "_mime_type": packet_mime,
            "content": [
                {
                    "type": "text",
                    "text": "System: Here is the screen capture you requested. Analyse it carefully and describe exactly what you see.",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{packet_mime};base64,{packet_b64}", "detail": "low"},
                },
            ],
        }
    )
    return json.dumps(safe_result, ensure_ascii=False)


def finalize_vision_packets(
    specialist_runtime: LLMRuntime,
    specialist_name: str,
    vision_packets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    vision_runtime = build_vision_runtime_from_env(specialist_runtime)
    model_lower = vision_runtime.model.lower()
    is_vision_capable = (
        (vision_runtime.provider == "copilot" and ("gpt-4" in model_lower or any(token in model_lower for token in {"gpt-4o", "gpt-4-vision", "gpt-4-turbo", "o1", "claude", "gemini"})))
        or (vision_runtime.provider == "nvidia" and ("vision" in model_lower or "-vl" in model_lower or "llama-4" in model_lower))
    )
    if not is_vision_capable:
        provider_label = f"{specialist_runtime.provider}/{specialist_runtime.model}"
        return {
            "agent": specialist_name,
            "ok": True,
            "reply": (
                f"I captured the image but cannot analyse it because no vision-capable model is configured ({provider_label}). "
                "Set VISION_PROVIDER=gemini, nvidia, or copilot in your .env to enable vision."
            ),
        }
    describe_vision_packets_as_text(vision_packets, vision_runtime)
    descriptions = [packet.get("_description", "") for packet in vision_packets if packet.get("_description")]
    return {"agent": specialist_name, "ok": True, "reply": "\n\n".join(descriptions)}
