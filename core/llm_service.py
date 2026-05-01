from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    temperature: float
    max_tokens: int
    timeout_seconds: int
    stream: bool

    @classmethod
    def from_env(cls, project_root: Path) -> "LLMConfig":
        load_dotenv(project_root / ".env")

        api_key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not api_key:
            raise ValueError("Missing NVIDIA_API_KEY. Add it to .env before chatting.")

        return cls(
            api_key=api_key,
            base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/"),
            model=os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct"),
            temperature=float(os.getenv("TEMPERATURE", "0.4")),
            max_tokens=int(os.getenv("MAX_TOKENS", "1024")),
            timeout_seconds=int(os.getenv("NVIDIA_TIMEOUT_SECONDS", "20")),
            stream=os.getenv("NVIDIA_STREAM", "true").strip().lower() in {"1", "true", "yes", "on"},
        )


class NvidiaLLMService:
    def __init__(self, config: LLMConfig):
        self.config = config

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int | None = None,
    ) -> str:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
        }

        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout or self.config.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            if error.code == 404 and "Function" in details and "Not found" in details:
                raise RuntimeError(
                    "NVIDIA could not find the configured model for this account. "
                    "Check NVIDIA_MODEL in .env and use the exact case-sensitive model id from build.nvidia.com."
                ) from error
            raise RuntimeError(f"NVIDIA API request failed: {error.code} {details}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not reach NVIDIA API: {error.reason}") from error

        return self._extract_text(body)

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int | None = None,
    ) -> Iterator[str]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "stream": True,
        }

        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout or self.config.timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    chunk = self._extract_stream_delta(json.loads(data))
                    if chunk:
                        yield chunk
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"NVIDIA streaming request failed: {error.code} {details}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not reach NVIDIA API: {error.reason}") from error

    @staticmethod
    def _extract_text(body: dict[str, Any]) -> str:
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError(f"Unexpected NVIDIA API response: {body}") from error

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            return "\n".join(part for part in parts if part).strip()

        return str(content).strip()

    @staticmethod
    def _extract_stream_delta(body: dict[str, Any]) -> str:
        try:
            delta = body["choices"][0].get("delta", {})
        except (KeyError, IndexError, TypeError):
            return ""

        content = delta.get("content", "")
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            return "".join(part.get("text", "") for part in content if isinstance(part, dict))

        return str(content) if content else ""
