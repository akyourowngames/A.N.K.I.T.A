from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .client import ModelResponse, OpenAICompatibleRouterClient, RouterClient, RouterModelConfig
from .parser import RouterFormatError, format_tool_array, parse_tool_array


ROUTER_ROOT = Path(__file__).resolve().parent


@dataclass(slots=True)
class RouterAttempt:
    kind: str
    model: str
    raw_output: str
    latency_ms: float
    parse_error: str = ""


@dataclass(slots=True)
class RouterResult:
    tools: list[str]
    output: str
    raw_output: str
    model: str
    latency_ms: float
    attempts: list[RouterAttempt] = field(default_factory=list)


class RouterOutputError(RuntimeError):
    def __init__(self, message: str, attempts: list[RouterAttempt]) -> None:
        super().__init__(message)
        self.attempts = attempts


class ToolRegistry:
    def __init__(self, path: Path | None = None, *, payload: dict[str, Any] | None = None) -> None:
        if payload is None and path is None:
            raise ValueError("Tool registry requires either path or payload.")
        self.path = path
        if payload is None:
            assert path is not None
            payload = json.loads(path.read_text(encoding="utf-8"))
        self._load(payload, source=str(path or "inline payload"))

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ToolRegistry":
        return cls(payload=payload)

    def _load(self, payload: dict[str, Any], *, source: str) -> None:
        tools = payload.get("tools", [])
        if not isinstance(tools, list) or not tools:
            raise ValueError(f"Tool registry must contain a non-empty tools list: {source}")

        self.tools: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in tools:
            if not isinstance(item, dict):
                raise ValueError(f"Invalid tool registry item in {source}: {item!r}")
            label = str(item.get("label", "")).strip()
            description = str(item.get("description", "")).strip()
            if not label:
                raise ValueError(f"Tool registry item is missing a label in {source}")
            if label in seen:
                raise ValueError(f"Duplicate tool label in registry: {label}")
            seen.add(label)
            self.tools.append({"label": label, "description": description})

    @property
    def labels(self) -> list[str]:
        return [tool["label"] for tool in self.tools]

    def prompt_registry(self) -> str:
        return json.dumps(self.tools, ensure_ascii=False, separators=(",", ":"))


class MandatoryRouter:
    """Mandatory LLM-first router entrypoint for this standalone testbed."""

    def __init__(
        self,
        *,
        tools_path: Path | None = None,
        tools_payload: dict[str, Any] | None = None,
        prompt_path: Path | None = None,
        client: RouterClient | None = None,
        env_file: Path | None = None,
        model: str = "",
    ) -> None:
        self.registry = ToolRegistry(tools_path or ROUTER_ROOT / "tools.json", payload=tools_payload)
        self.system_prompt = (prompt_path or ROUTER_ROOT / "prompt.txt").read_text(encoding="utf-8").strip()
        self.client = client or OpenAICompatibleRouterClient(
            RouterModelConfig.from_env(env_file=env_file, model_override=model)
        )

    def route(self, user_prompt: str) -> RouterResult:
        prompt = user_prompt.strip()
        if not prompt:
            raise ValueError("User prompt is empty.")

        attempts: list[RouterAttempt] = []
        started = time.perf_counter()

        first_response = self.client.complete(
            system_prompt=self.system_prompt,
            user_prompt=self._classification_payload(prompt),
        )
        first_error = self._try_parse(first_response, attempts, kind="classify")
        if first_error is None:
            return self._result_from_response(first_response, attempts, started)

        repair_response = self.client.complete(
            system_prompt=self._repair_system_prompt(),
            user_prompt=self._repair_payload(prompt, first_response.raw_output, first_error.reason),
        )
        repair_error = self._try_parse(repair_response, attempts, kind="repair")
        if repair_error is None:
            return self._result_from_response(repair_response, attempts, started)

        raise RouterOutputError(f"Router returned invalid output after repair: {repair_error.reason}", attempts)

    def route_text(self, user_prompt: str) -> str:
        return self.route(user_prompt).output

    def _classification_payload(self, user_prompt: str) -> str:
        return (
            "Registered tool registry JSON:\n"
            f"{self.registry.prompt_registry()}\n\n"
            "User prompt:\n"
            f"{user_prompt}"
        )

    def _repair_system_prompt(self) -> str:
        labels = format_tool_array(self.registry.labels)
        return (
            "You repair invalid router output. Return exactly one valid JSON array of strings and nothing else. "
            f"Allowed labels are exactly: {labels}. "
            "Use the original user prompt and the invalid output only to produce the corrected tool array. "
            "No prose, no markdown, no code fence, no prefix, no suffix."
        )

    def _repair_payload(self, user_prompt: str, raw_output: str, reason: str) -> str:
        return (
            f"Original user prompt:\n{user_prompt}\n\n"
            f"Invalid model output:\n{raw_output}\n\n"
            f"Parser error:\n{reason}\n\n"
            "Return the corrected router output now."
        )

    def _try_parse(self, response: ModelResponse, attempts: list[RouterAttempt], *, kind: str) -> RouterFormatError | None:
        try:
            parse_tool_array(response.raw_output, self.registry.labels)
        except RouterFormatError as exc:
            attempts.append(
                RouterAttempt(
                    kind=kind,
                    model=response.model,
                    raw_output=response.raw_output,
                    latency_ms=response.latency_ms,
                    parse_error=exc.reason,
                )
            )
            return exc
        attempts.append(
            RouterAttempt(
                kind=kind,
                model=response.model,
                raw_output=response.raw_output,
                latency_ms=response.latency_ms,
            )
        )
        return None

    def _result_from_response(
        self,
        response: ModelResponse,
        attempts: list[RouterAttempt],
        started: float,
    ) -> RouterResult:
        tools = parse_tool_array(response.raw_output, self.registry.labels)
        return RouterResult(
            tools=tools,
            output=format_tool_array(tools),
            raw_output=response.raw_output,
            model=response.model,
            latency_ms=(time.perf_counter() - started) * 1000,
            attempts=list(attempts),
        )


def route_prompt(user_prompt: str) -> str:
    return MandatoryRouter().route_text(user_prompt)
