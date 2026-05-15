from __future__ import annotations

import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


TraceSink = Callable[[dict[str, Any]], None]
_CURRENT_TRACE: ContextVar["LatencyTrace | None"] = ContextVar("jarvis_latency_trace", default=None)


@dataclass
class LatencyTrace:
    enabled: bool = True
    sink: TraceSink | None = None
    started: float = field(default_factory=time.perf_counter)
    events: list[dict[str, Any]] = field(default_factory=list)
    model_calls: int = 0
    route_mode: str = ""
    selected_tools: list[str] = field(default_factory=list)

    def mark(self, stage: str, **metadata: Any) -> None:
        if not self.enabled:
            return
        elapsed_ms = round((time.perf_counter() - self.started) * 1000, 3)
        event: dict[str, Any] = {"stage": stage, "elapsed_ms": elapsed_ms}
        for key, value in metadata.items():
            if safe_trace_value(value):
                event[key] = value
        self.events.append(event)
        if self.sink is not None:
            self.sink(dict(event))

    def mark_once(self, stage: str, **metadata: Any) -> None:
        if any(event.get("stage") == stage for event in self.events):
            return
        self.mark(stage, **metadata)

    def increment_model_call(self) -> None:
        self.model_calls += 1

    def set_route(self, mode: str, selected_tools: list[str]) -> None:
        self.route_mode = mode
        self.selected_tools = list(selected_tools)

    def finish(self) -> dict[str, Any]:
        self.mark_once("response_done")
        total_ms = round((time.perf_counter() - self.started) * 1000, 3)
        return {
            "total_ms": total_ms,
            "model_calls": self.model_calls,
            "route_mode": self.route_mode,
            "selected_tools": list(self.selected_tools),
            "events": list(self.events),
            "stage_ms": self.stage_durations(),
            "first_token_ms": self.first_stage_ms("first_model_token"),
        }

    def first_stage_ms(self, stage: str) -> float | None:
        for event in self.events:
            if event.get("stage") == stage:
                value = event.get("elapsed_ms")
                return value if isinstance(value, float) else None
        return None

    def stage_durations(self) -> dict[str, float]:
        pairs = {
            "selector_ms": ("selector_started", "selector_done"),
            "planner_ms": ("planner_started", "planner_done"),
            "tool_ms": ("tool_execution_started", "tool_execution_done"),
            "final_model_ms": ("final_model_started", "response_done"),
            "memory_ms": ("memory_started", "memory_done"),
            "local_router_ms": ("local_router_started", "local_router_done"),
        }
        return {name: self.elapsed_between(start, end) for name, (start, end) in pairs.items()}

    def elapsed_between(self, start_stage: str, end_stage: str) -> float:
        start = self.first_stage_ms(start_stage)
        end = self.first_stage_ms(end_stage)
        if start is None or end is None or end < start:
            return 0.0
        return round(end - start, 3)


def safe_trace_value(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or (
        isinstance(value, list) and all(isinstance(item, str) for item in value)
    )


def current_trace() -> LatencyTrace | None:
    return _CURRENT_TRACE.get()


@contextmanager
def use_latency_trace(trace: LatencyTrace | None) -> Iterator[None]:
    token = _CURRENT_TRACE.set(trace)
    try:
        yield
    finally:
        _CURRENT_TRACE.reset(token)


def trace_mark(stage: str, **metadata: Any) -> None:
    trace = current_trace()
    if trace is not None:
        trace.mark(stage, **metadata)


def trace_mark_once(stage: str, **metadata: Any) -> None:
    trace = current_trace()
    if trace is not None:
        trace.mark_once(stage, **metadata)


def trace_model_call() -> None:
    trace = current_trace()
    if trace is not None:
        trace.increment_model_call()


def latency_debug_enabled() -> bool:
    value = os.environ.get("JARVIS_LATENCY_DEBUG", "").strip().lower()
    return value in {"1", "true", "yes", "on"}
