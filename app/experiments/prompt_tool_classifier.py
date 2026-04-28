"""Experimental LLM prompt classifier for Jarvis routing.

This file is also isolated from production. It uses the existing NVIDIA chat
client to classify routing and tool labels through a structured prompt.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from app.experiments.tool_classifier_bert import (
    PRIMARY_LABEL_PROMPTS,
    TOOL_LABEL_PROMPTS,
    Classification,
)
from app.services.nvidia_client import NvidiaClient
from config import GROQ_API_KEYS, NVIDIA_BASE_URL, NVIDIA_FAST_MODEL


@dataclass(frozen=True)
class PromptRoute:
    primary: Classification
    tool: Optional[Classification]
    raw: str


class PromptToolClassifier:
    def __init__(
        self,
        model: str = NVIDIA_FAST_MODEL,
        api_key: Optional[str] = None,
        base_url: str = NVIDIA_BASE_URL,
        timeout: int = 20,
    ):
        key = api_key or (GROQ_API_KEYS[0] if GROQ_API_KEYS else "")
        if not key:
            raise ValueError("No NVIDIA/GROQ-compatible API key is configured.")
        self.model = model
        self.client = NvidiaClient(key, base_url, timeout=timeout)

    def classify_route(self, text: str) -> Tuple[Classification, Optional[Classification]]:
        route = self.classify(text)
        return route.primary, route.tool

    def classify(self, text: str) -> PromptRoute:
        started = time.perf_counter()
        raw = self.client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": f"User message: {text}"},
            ],
            temperature=0.0,
            max_tokens=120,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        data = self._parse_json(raw)

        primary = self._clean_label(data.get("primary"), PRIMARY_LABEL_PROMPTS, "general")
        tool = self._clean_label(data.get("tool"), TOOL_LABEL_PROMPTS, "")
        confidence = self._clean_confidence(data.get("confidence"))
        reasoning = str(data.get("reason", "")).strip()

        if tool and primary not in ("task", "mixed"):
            primary = "task"
        if primary not in ("task", "mixed"):
            tool = ""

        primary_result = Classification(primary, confidence, "llm-prompt", elapsed_ms, reasoning)
        tool_result = None
        if primary in ("task", "mixed"):
            tool_result = Classification(tool or "unsupported_needs_tool", confidence, "llm-prompt", elapsed_ms, reasoning)
        return PromptRoute(primary_result, tool_result, raw)

    def _system_prompt(self) -> str:
        primary_labels = "\n".join(f"- {label}: {desc}" for label, desc in PRIMARY_LABEL_PROMPTS.items())
        tool_labels = "\n".join(f"- {label}: {desc}" for label, desc in TOOL_LABEL_PROMPTS.items())
        return (
            "You are a strict Jarvis routing classifier. Classify the user's message; do not execute it.\n"
            "Return exactly one JSON object with keys primary, tool, confidence, reason.\n"
            "primary must be one of the primary labels. tool must be one of the tool labels when primary is task or mixed; otherwise tool is null.\n"
            "Core priority: if the user asks Jarvis to DO something, primary is task, not general and not realtime.\n"
            "Open, play, search, write, generate, inspect PC, camera on/off, volume, brightness, lock, terminal, screenshot, and unsupported actions are all task.\n"
            "Generate, draw, create image, make picture, and logo requests are task with tool generate_image.\n"
            "Realtime is only for answering current information questions, not for explicit Google or YouTube search commands.\n"
            "Questions like latest score, weather today, current price, and news are realtime when the user did not ask to search/open a page.\n"
            "Camera is only for visual analysis, such as 'what am I holding' or 'look at this', not for opening or closing the webcam.\n"
            "Inspect_pc is for asking what is open/running or why the PC is slow; open_app is only for commands to launch an app.\n"
            "'what apps are open' must be inspect_pc, not open_app.\n"
            "Never choose open_app for a question about already-open apps or windows.\n"
            "Brightness_up/down are for direction changes; set_brightness is only for a specific level or percent.\n"
            "If the user asks for an action Jarvis cannot currently execute, choose tool unsupported_needs_tool instead of guessing open.\n"
            "Treat typo-heavy short messages by meaning, not spelling. Example: 'can yu take ss' means the user likely wants a screenshot.\n\n"
            f"Primary labels:\n{primary_labels}\n\n"
            f"Tool labels:\n{tool_labels}\n\n"
            "Examples:\n"
            '{"primary":"task","tool":"unsupported_needs_tool","confidence":0.92,"reason":"screenshot request, no screenshot executor yet"} for can yu take ss\n'
            '{"primary":"task","tool":"open","confidence":0.95,"reason":"open website command"} for open youtube\n'
            '{"primary":"task","tool":"youtube_search","confidence":0.95,"reason":"explicit YouTube search command"} for search youtube for python decorators\n'
            '{"primary":"task","tool":"generate_image","confidence":0.95,"reason":"image generation command"} for generate image of a blue sports car\n'
            '{"primary":"task","tool":"inspect_pc","confidence":0.95,"reason":"asks for current PC state"} for what apps are open\n'
            '{"primary":"task","tool":"inspect_pc","confidence":0.95,"reason":"asks which apps are already open"} for what apps are open right now\n'
            '{"primary":"task","tool":"open_app","confidence":0.95,"reason":"launches a desktop app"} for open notepad app\n'
            '{"primary":"task","tool":"brightness_up","confidence":0.95,"reason":"directional brightness increase"} for increase brightness\n'
            '{"primary":"realtime","tool":null,"confidence":0.95,"reason":"asks for current score, not a search command"} for latest cricket score today\n'
            '{"primary":"camera","tool":null,"confidence":0.9,"reason":"asks visual analysis through camera"} for what am I holding\n'
            '{"primary":"mixed","tool":"open","confidence":0.85,"reason":"asks an explanation and an open action"} for tell me about python and open youtube\n'
        )

    @staticmethod
    def _parse_json(raw: str) -> dict:
        text = (raw or "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return {}
            return {}

    @staticmethod
    def _clean_label(value, allowed: dict, default: str) -> str:
        label = str(value or "").strip().lower()
        return label if label in allowed else default

    @staticmethod
    def _clean_confidence(value) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, confidence))
