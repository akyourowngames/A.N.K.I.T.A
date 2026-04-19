from __future__ import annotations

import time
from typing import Any, Iterator

from openai import OpenAI

from jakata_agent.config import Settings


class NvidiaChatClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            max_retries=0,
        )

    def complete(self, messages: list[dict[str, Any]]) -> tuple[str, str]:
        last_error: Exception | None = None

        for model in self.settings.model_chain:
            for attempt in range(1, self.settings.max_retries + 1):
                try:
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0.7,
                    )
                    content = response.choices[0].message.content or ""
                    if not content.strip():
                        raise RuntimeError("Model returned an empty response.")
                    return model, content
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt < self.settings.max_retries:
                        time.sleep(min(2 ** (attempt - 1), 4))

        raise RuntimeError(f"All NVIDIA model attempts failed: {last_error}") from last_error

    def stream_complete(self, messages: list[dict[str, Any]]) -> Iterator[tuple[str, str]]:
        last_error: Exception | None = None

        for model in self.settings.model_chain:
            for attempt in range(1, self.settings.max_retries + 1):
                chunks: list[str] = []
                try:
                    stream = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0.7,
                        stream=True,
                    )
                    for event in stream:
                        delta = event.choices[0].delta.content or ""
                        if delta:
                            chunks.append(delta)
                            yield model, delta
                    if not chunks:
                        raise RuntimeError("Model returned an empty streamed response.")
                    return
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt < self.settings.max_retries:
                        time.sleep(min(2 ** (attempt - 1), 4))

        raise RuntimeError(f"All NVIDIA model attempts failed: {last_error}") from last_error

    def complete_text(self, system_prompt: str, user_prompt: str) -> tuple[str, str]:
        return self.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
