"""Experimental prompt-label MiniLM tool classifier.

This is intentionally isolated from production routing. It uses a small
sentence-transformer as a classifier over natural-language label descriptions.
There are no regex intent rules in this file; the only fixed data is the label
set and the prompt text that defines each label.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

try:
    from config import EMBEDDING_MODEL
except Exception:
    EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


PRIMARY_LABEL_PROMPTS: Dict[str, str] = {
    "general": (
        "Classify as general when the user is chatting, asking static knowledge, "
        "asking for advice, coding help, math, greetings, or anything that does "
        "not require live web data or an action tool."
    ),
    "realtime": (
        "Classify as realtime when the user asks for current, live, recent, "
        "changing, price, weather, score, news, review, person, company, or "
        "web-backed information."
    ),
    "camera": (
        "Classify as camera when the user wants the assistant to look through "
        "the camera or analyze an attached/visible object, image, paper, hand, "
        "screen, or scene."
    ),
    "task": (
        "Classify as task when the user wants an action tool: open a website or "
        "app, play media, search Google or YouTube, generate an image, write "
        "content, control webcam, inspect this PC, run terminal, change volume "
        "or brightness, lock screen, or perform an unsupported action such as "
        "taking a screenshot."
    ),
    "mixed": (
        "Classify as mixed only when the same message contains both a question "
        "or explanation request and a clear action tool request."
    ),
}


TOOL_LABEL_PROMPTS: Dict[str, str] = {
    "open": (
        "The user wants to open, visit, launch, or go to a website, web app, URL, "
        "domain, or known online service."
    ),
    "play": (
        "The user wants to play a song, video, music, artist, playlist, or media "
        "item, usually through YouTube."
    ),
    "open_app": (
        "The user commands Jarvis to start a desktop application installed on "
        "this Windows computer, such as Notepad, Calculator, Chrome, or VS Code. "
        "This label is only for launching an app, not listing running apps."
    ),
    "close_app": (
        "The user wants to close, quit, kill, terminate, or stop a desktop app "
        "or process on this computer."
    ),
    "open_webcam": (
        "The user wants to open, turn on, start, or show the webcam/camera feed."
    ),
    "close_webcam": (
        "The user wants to close, turn off, stop, or disable the webcam/camera feed."
    ),
    "generate_image": (
        "The user wants to generate, draw, create, or make an image, picture, "
        "logo, artwork, visual, or design."
    ),
    "content": (
        "The user wants written content such as an essay, application, poem, "
        "letter, email, code, draft, or composed text."
    ),
    "google_search": (
        "The user wants to search Google or the web for a topic, lookup, query, "
        "restaurant, review, product, or information."
    ),
    "youtube_search": (
        "The user wants to search YouTube or find videos on YouTube without "
        "directly asking to play a specific item."
    ),
    "inspect_pc": (
        "The user asks about this PC's current state: what apps are open, "
        "open windows, CPU, RAM, memory, disk, battery, ports, downloads, "
        "performance, or why the laptop is slow."
    ),
    "run_terminal": (
        "The user asks to run an explicit terminal, shell, command prompt, or "
        "PowerShell command on this computer."
    ),
    "set_volume": "The user wants to set the system volume to a specific level or percent.",
    "volume_up": "The user wants to increase or raise the system volume.",
    "volume_down": "The user wants to decrease or lower the system volume.",
    "mute_volume": "The user wants to mute, unmute, or toggle system audio mute.",
    "set_brightness": "The user wants to set screen brightness to a specific level or percent.",
    "brightness_up": "The user wants to increase screen brightness or make the screen brighter.",
    "brightness_down": "The user wants to decrease brightness, lower brightness, or dim the screen.",
    "lock_screen": "The user wants to lock the Windows screen or session.",
    "unsupported_needs_tool": (
        "The user wants an action that Jarvis does not currently have an executor "
        "for, especially taking a screenshot, screen capture, sending messages, "
        "making calls, booking, buying, or controlling unsupported external apps. "
        "Short forms such as 'ss' can mean screenshot."
    ),
}


@dataclass(frozen=True)
class Classification:
    label: str
    confidence: float
    backend: str
    elapsed_ms: int
    matched_example: str = ""


def normalize_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


class ExperimentalToolClassifier:
    """MiniLM semantic classifier over prompt-style label definitions."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        primary_threshold: float = 0.18,
        tool_threshold: float = 0.16,
    ):
        self.model_name = model_name
        self.primary_threshold = primary_threshold
        self.tool_threshold = tool_threshold
        self._model = None
        self._model_error = ""
        self._primary_labels = tuple(PRIMARY_LABEL_PROMPTS.keys())
        self._tool_labels = tuple(TOOL_LABEL_PROMPTS.keys())
        self._primary_embeddings = None
        self._tool_embeddings = None

    def classify_primary(self, text: str) -> Classification:
        return self._classify(text, self._primary_labels, PRIMARY_LABEL_PROMPTS, "primary")

    def classify_tool(self, text: str) -> Classification:
        return self._classify(text, self._tool_labels, TOOL_LABEL_PROMPTS, "tool")

    def classify_route(self, text: str) -> Tuple[Classification, Optional[Classification]]:
        primary = self.classify_primary(text)
        if primary.label in ("task", "mixed"):
            return primary, self.classify_tool(text)
        return primary, None

    def _classify(
        self,
        text: str,
        labels: Sequence[str],
        prompts: Dict[str, str],
        group: str,
    ) -> Classification:
        start = time.perf_counter()
        normalized = normalize_text(text)
        if not normalized:
            return Classification("general", 0.0, "empty", 0)

        if not self._ensure_model():
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            fallback = "general" if group == "primary" else "unsupported_needs_tool"
            return Classification(fallback, 0.0, f"model-unavailable:{self._model_error}", elapsed_ms)

        label, score, prompt = self._semantic_match(normalized, labels, prompts, group)
        threshold = self.primary_threshold if group == "primary" else self.tool_threshold
        if score < threshold:
            label = "general" if group == "primary" else "unsupported_needs_tool"

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return Classification(label, score, "minilm-prompt", elapsed_ms, prompt)

    def _ensure_model(self) -> bool:
        if self._model is not None:
            return True
        if self._model_error:
            return False
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            return True
        except Exception as exc:
            self._model_error = exc.__class__.__name__
            return False

    def _semantic_match(
        self,
        text: str,
        labels: Sequence[str],
        prompts: Dict[str, str],
        group: str,
    ) -> Tuple[str, float, str]:
        import numpy as np

        if group == "primary":
            if self._primary_embeddings is None:
                self._primary_embeddings = self._encode([self._label_prompt(label, prompts[label]) for label in labels])
            embeddings = self._primary_embeddings
        else:
            if self._tool_embeddings is None:
                self._tool_embeddings = self._encode([self._label_prompt(label, prompts[label]) for label in labels])
            embeddings = self._tool_embeddings

        query = self._encode([f"User message: {text}"])[0]
        scores = embeddings @ query
        best_idx = int(np.argmax(scores))
        label = labels[best_idx]
        return label, float(scores[best_idx]), prompts[label]

    def _encode(self, texts: Sequence[str]):
        return self._model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    @staticmethod
    def _label_prompt(label: str, description: str) -> str:
        return f"Intent label: {label}. Meaning: {description}"
