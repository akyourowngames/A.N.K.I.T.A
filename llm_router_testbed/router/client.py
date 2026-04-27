from __future__ import annotations

import os
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv
from openai import OpenAI


class RouterClient(Protocol):
    def complete(self, *, system_prompt: str, user_prompt: str) -> "ModelResponse":
        ...


@dataclass(slots=True)
class ModelResponse:
    model: str
    raw_output: str
    latency_ms: float


@dataclass(slots=True)
class RouterModelConfig:
    api_key: str
    base_url: str
    model: str
    model_chain: list[str]
    timeout_seconds: float = 8.0
    max_retries: int = 1
    max_tokens: int = 96
    temperature: float = 0.0
    response_format: str = ""
    extra_body: dict[str, object] | None = None

    @classmethod
    def from_env(cls, env_file: Path | None = None, model_override: str = "") -> "RouterModelConfig":
        if env_file is not None:
            load_dotenv(env_file)
        else:
            load_dotenv()

        api_key = (
            os.getenv("LLM_ROUTER_API_KEY", "").strip()
            or os.getenv("NVIDIA_API_KEY", "").strip()
            or os.getenv("OPENAI_API_KEY", "").strip()
        )
        if not api_key:
            raise RuntimeError("Missing LLM_ROUTER_API_KEY, NVIDIA_API_KEY, or OPENAI_API_KEY.")

        base_url = (
            os.getenv("LLM_ROUTER_BASE_URL", "").strip()
            or os.getenv("NVIDIA_BASE_URL", "").strip()
            or os.getenv("OPENAI_BASE_URL", "").strip()
        )
        model_text = (
            model_override.strip()
            or os.getenv("LLM_ROUTER_MODELS", "").strip()
            or os.getenv("LLM_ROUTER_MODEL", "").strip()
            or "qwen/qwen3.5-122b-a10b,nvidia/nemotron-mini-4b-instruct"
        )
        model_chain = [item.strip() for item in model_text.split(",") if item.strip()]
        model = model_chain[0]
        response_format = os.getenv("LLM_ROUTER_RESPONSE_FORMAT", "").strip().lower()
        if not response_format and os.getenv("LLM_ROUTER_USE_RESPONSE_FORMAT", "").strip().lower() in {"1", "true", "yes", "on"}:
            response_format = "json_object"
        extra_body_raw = os.getenv("LLM_ROUTER_EXTRA_BODY", "").strip()
        extra_body: dict[str, object] | None = None
        if extra_body_raw:
            payload = json.loads(extra_body_raw)
            if not isinstance(payload, dict):
                raise RuntimeError("LLM_ROUTER_EXTRA_BODY must be a JSON object.")
            extra_body = payload
        elif model == "moonshotai/kimi-k2.5":
            extra_body = {"chat_template_kwargs": {"thinking": False}}
        timeout_seconds = (
            os.getenv("LLM_ROUTER_TIMEOUT_SECONDS", "").strip()
            or ("60" if model == "moonshotai/kimi-k2.5" else os.getenv("NVIDIA_TIMEOUT_SECONDS", "").strip() or "20")
        )
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            model_chain=model_chain,
            timeout_seconds=float(timeout_seconds),
            max_retries=int(os.getenv("LLM_ROUTER_MAX_RETRIES", "1").strip() or "1"),
            max_tokens=int(os.getenv("LLM_ROUTER_MAX_TOKENS", "96").strip() or "96"),
            temperature=float(os.getenv("LLM_ROUTER_TEMPERATURE", "0").strip() or "0"),
            response_format=response_format,
            extra_body=extra_body,
        )


class OpenAICompatibleRouterClient:
    def __init__(self, config: RouterModelConfig) -> None:
        client_kwargs = {
            "api_key": config.api_key,
            "timeout": config.timeout_seconds,
            "max_retries": 0,
        }
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        self.client = OpenAI(**client_kwargs)
        self.config = config

    def complete(self, *, system_prompt: str, user_prompt: str) -> ModelResponse:
        last_error: Exception | None = None
        started = time.perf_counter()
        for model in self.config.model_chain:
            for attempt in range(1, self.config.max_retries + 1):
                try:
                    request = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": self.config.temperature,
                        "max_tokens": self.config.max_tokens,
                    }
                    if self.config.response_format == "json_object":
                        request["response_format"] = {"type": "json_object"}
                    elif self.config.response_format == "json_schema":
                        request["response_format"] = {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "router_tool_array",
                                "schema": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 1,
                                },
                                "strict": True,
                            },
                        }
                    extra_body = self.config.extra_body
                    if extra_body is None and model == "moonshotai/kimi-k2.5":
                        extra_body = {"chat_template_kwargs": {"thinking": False}}
                    if extra_body:
                        request["extra_body"] = extra_body
                    response = self.client.chat.completions.create(**request)
                    raw = response.choices[0].message.content or ""
                    return ModelResponse(
                        model=model,
                        raw_output=raw,
                        latency_ms=(time.perf_counter() - started) * 1000,
                    )
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt < self.config.max_retries:
                        time.sleep(min(2 ** (attempt - 1), 4))
        raise RuntimeError(f"Router model call failed: {last_error}") from last_error
