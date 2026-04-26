from __future__ import annotations

import base64
import mimetypes
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator, Protocol

from openai import OpenAI

from jakata_agent.config import Settings
from jakata_agent.prompts import load_prompt


class TextCompletionClient(Protocol):
    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> tuple[str, str]:
        ...


VISION_SYSTEM_PROMPT = load_prompt("camera/vision.md")


class NvidiaChatClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            max_retries=0,
        )

    def complete(self, messages: list[dict[str, Any]], temperature: float = 0.7) -> tuple[str, str]:
        last_error: Exception | None = None

        for model in self.settings.model_chain:
            for attempt in range(1, self.settings.max_retries + 1):
                try:
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
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

    def stream_complete(self, messages: list[dict[str, Any]], temperature: float = 0.7) -> Iterator[tuple[str, str]]:
        last_error: Exception | None = None

        for model in self.settings.model_chain:
            for attempt in range(1, self.settings.max_retries + 1):
                chunks: list[str] = []
                try:
                    stream = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        stream=True,
                    )
                    for event in stream:
                        if not event.choices:
                            continue
                        delta = event.choices[0].delta.content or ""
                        if delta:
                            chunks.append(delta)
                            yield model, delta
                    if not chunks:
                        raise RuntimeError("Model returned an empty streamed response.")
                    return
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if chunks:
                        # Once text has already been shown to the user, retrying the stream
                        # creates a second visible answer glued onto the first one.
                        return
                    if attempt < self.settings.max_retries:
                        time.sleep(min(2 ** (attempt - 1), 4))

        raise RuntimeError(f"All NVIDIA model attempts failed: {last_error}") from last_error

    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> tuple[str, str]:
        return self.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )

    def describe_image(
        self,
        *,
        image_path: str | Path,
        user_prompt: str,
        system_prompt: str = VISION_SYSTEM_PROMPT,
        temperature: float = 0.2,
        max_tokens: int = 300,
    ) -> tuple[str, str]:
        image_file = Path(image_path)
        if not image_file.exists():
            raise RuntimeError(f"Image not found: {image_file}")

        mime_type = mimetypes.guess_type(image_file.name)[0] or "image/jpeg"
        encoded = base64.b64encode(image_file.read_bytes()).decode("utf-8")
        content: list[dict[str, Any]] = [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
        ]

        last_error: Exception | None = None
        for model in self.settings.vision_model_chain:
            for attempt in range(1, self.settings.max_retries + 1):
                try:
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": content},
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    output = response.choices[0].message.content or ""
                    if not output.strip():
                        raise RuntimeError("Vision model returned an empty response.")
                    return model, output
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt < self.settings.max_retries:
                        time.sleep(min(2 ** (attempt - 1), 4))

        raise RuntimeError(f"All NVIDIA vision model attempts failed: {last_error}") from last_error


class NvidiaTextClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_chain: list[str],
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        max_tokens: int | None = None,
    ) -> None:
        self.model_chain = [item for item in model_chain if item]
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=self.timeout_seconds,
            max_retries=0,
        )

    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> tuple[str, str]:
        last_error: Exception | None = None
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        for model in self.model_chain:
            for attempt in range(1, self.max_retries + 1):
                try:
                    request: dict[str, Any] = {
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                    }
                    if self.max_tokens is not None:
                        request["max_tokens"] = self.max_tokens
                    response = self.client.chat.completions.create(**request)
                    content = response.choices[0].message.content or ""
                    if not content.strip():
                        raise RuntimeError("Model returned an empty response.")
                    return model, content
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt < self.max_retries:
                        time.sleep(min(2 ** (attempt - 1), 4))
        raise RuntimeError(f"All NVIDIA automation model attempts failed: {last_error}") from last_error


class CodexCliTextClient:
    def __init__(
        self,
        *,
        codex_command: str = "codex",
        model: str = "gpt-5.4",
        workdir: Path,
        timeout_seconds: float = 180.0,
    ) -> None:
        self.codex_command = codex_command
        self.model = model
        self.workdir = Path(workdir)
        self.timeout_seconds = timeout_seconds

    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> tuple[str, str]:
        del temperature
        prompt = (
            f"{system_prompt.strip()}\n\n"
            "Return only the final answer requested by the system prompt.\n\n"
            f"{user_prompt.strip()}\n"
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as handle:
            output_path = Path(handle.name)
        command = [
            self.codex_command,
            "exec",
            "--skip-git-repo-check",
            "--cd",
            str(self.workdir),
            "--model",
            self.model,
            "--output-last-message",
            str(output_path),
            "--color",
            "never",
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                cwd=self.workdir,
                timeout=self.timeout_seconds,
                check=False,
            )
            content = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
            if completed.returncode != 0 and not content:
                stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown codex error"
                raise RuntimeError(stderr[:500])
            if not content:
                raise RuntimeError("Codex CLI returned an empty response.")
            return f"codex:{self.model}", content
        finally:
            output_path.unlink(missing_ok=True)


class FallbackTextClient:
    def __init__(self, primary: TextCompletionClient, fallback: TextCompletionClient) -> None:
        self.primary = primary
        self.fallback = fallback

    def complete_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> tuple[str, str]:
        try:
            return self.primary.complete_text(system_prompt, user_prompt, temperature=temperature)
        except Exception:
            return self.fallback.complete_text(system_prompt, user_prompt, temperature=temperature)


def build_automation_client(settings: Settings, fallback: NvidiaChatClient) -> TextCompletionClient:
    backend = settings.automation_backend.lower()
    nvidia_automation = None
    if settings.automation_model:
        nvidia_automation = NvidiaTextClient(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model_chain=[settings.automation_model, *settings.fallback_models],
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
        )
    codex_client = CodexCliTextClient(
        codex_command=settings.codex_cli_path,
        model=settings.automation_model or "gpt-5.4",
        workdir=settings.workspace_dir,
        timeout_seconds=settings.automation_timeout_seconds,
    )
    if backend == "nvidia":
        return nvidia_automation or fallback
    if backend == "codex":
        return FallbackTextClient(codex_client, nvidia_automation or fallback)
    if backend == "auto":
        return FallbackTextClient(codex_client, nvidia_automation or fallback)
    return nvidia_automation or fallback


def build_router_client(settings: Settings, fallback: NvidiaChatClient) -> TextCompletionClient:
    seen: set[str] = set()
    model_chain: list[str] = []
    for model in [settings.router_model, settings.primary_model, *settings.fallback_models]:
        if model and model not in seen:
            seen.add(model)
            model_chain.append(model)
    if not model_chain:
        return fallback
    return FallbackTextClient(
        NvidiaTextClient(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model_chain=model_chain,
            timeout_seconds=settings.router_timeout_seconds,
            max_retries=settings.router_max_retries,
            max_tokens=settings.router_max_tokens,
        ),
        fallback,
    )


def build_browser_automation_client(settings: Settings, fallback: TextCompletionClient) -> TextCompletionClient:
    if not settings.browser_automation_model:
        return fallback
    return FallbackTextClient(
        NvidiaTextClient(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model_chain=[settings.browser_automation_model, settings.automation_model, *settings.fallback_models],
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
        ),
        fallback,
    )
