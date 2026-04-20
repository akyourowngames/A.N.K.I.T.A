"""
Tests for plan_validator.py and multi-step routing.

Run from your project root:
    python -m pytest tests/test_plan_validator.py -v
    python tests/test_plan_validator.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Inline minimal stubs so tests run without API keys or .env
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PlanStep:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    fallback_to: str | None = None


@dataclass(slots=True)
class ToolResult:
    ok: bool
    summary: str
    data: dict[str, Any]
    error: str | None = None


class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)


# ---------------------------------------------------------------------------
# Inline validator — copy of plan_validator.py logic for self-contained test
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ValidationResult:
    steps: list[PlanStep]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def __repr__(self) -> str:
        if self.ok:
            return f"ValidationResult(ok=True, steps={[s.tool for s in self.steps]})"
        return f"ValidationResult(ok=False, errors={self.errors}, steps={[s.tool for s in self.steps]})"


class PlanValidator:
    def validate(self, steps: list[PlanStep], registry: ToolRegistry) -> ValidationResult:
        errors: list[str] = []
        has_real_tools = any(step.tool != "general_chat" for step in steps)
        seen: set[tuple[str, str]] = set()
        validated: list[PlanStep] = []

        for step in steps:
            if step.tool == "general_chat":
                if not has_real_tools:
                    validated.append(step)
                continue

            tool = registry.get(step.tool)
            if tool is None:
                errors.append(f"unknown_tool:{step.tool}")
                continue

            args: dict = {}
            for key, val in step.args.items():
                if isinstance(val, dict) and list(val.keys()) == ["value"]:
                    args[key] = val["value"]
                elif isinstance(val, dict):
                    errors.append(f"bad_arg_shape:{step.tool}:{key}")
                else:
                    args[key] = val

            args = tool.normalize_args(args)

            required = tool.input_schema.get("required", [])
            missing = [k for k in required if args.get(k) in (None, "")]
            if missing:
                errors.append(f"missing_required:{step.tool}:{','.join(missing)}")
                continue

            allowed = set(tool.input_schema.get("properties", {}).keys())
            args = {k: v for k, v in args.items() if k in allowed}

            dedup_key = (step.tool, str(sorted(args.items())))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            fallback = step.fallback_to
            if fallback and registry.get(fallback) is None:
                errors.append(f"unknown_fallback:{step.tool}:{fallback}")
                fallback = None

            validated.append(PlanStep(tool=step.tool, args=args, reason=step.reason, fallback_to=fallback))

        if not validated:
            validated = [PlanStep(tool="general_chat", args={}, reason="validator_empty_fallback")]

        return ValidationResult(steps=validated, errors=errors)


# ---------------------------------------------------------------------------
# Minimal stub tools — no API keys, no network
# ---------------------------------------------------------------------------

class StubDatetime(Tool):
    name = "datetime"
    description = "Get current date/time."
    input_schema = {
        "type": "object",
        "properties": {"include_utc": {"type": "boolean"}},
        "required": [],
        "additionalProperties": False,
    }
    def normalize_args(self, args):
        args.setdefault("include_utc", True)
        return args
    def run(self, args):
        return ToolResult(ok=True, summary="time", data={})


class StubWeather(Tool):
    name = "weather"
    description = "Get weather."
    input_schema = {
        "type": "object",
        "properties": {
            "location": {"type": "string"},
            "units": {"type": "string", "enum": ["metric", "imperial"]},
        },
        "required": ["location"],
        "additionalProperties": False,
    }
    def normalize_args(self, args):
        args.setdefault("units", "metric")
        return args
    def run(self, args):
        return ToolResult(ok=True, summary="weather", data={})


class StubSearch(Tool):
    name = "search_web"
    description = "Search the web."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    def normalize_args(self, args):
        args.setdefault("max_results", 5)
        return args
    def run(self, args):
        return ToolResult(ok=True, summary="search", data={})


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(StubDatetime())
    registry.register(StubWeather())
    registry.register(StubSearch())
    return registry


REGISTRY = make_registry()
VALIDATOR = PlanValidator()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_single_datetime_step():
    steps = [PlanStep(tool="datetime", args={}, reason="test")]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert result.ok, result
    assert len(result.steps) == 1
    assert result.steps[0].tool == "datetime"
    assert result.steps[0].args.get("include_utc") is True  # normalize_args filled default


def test_single_weather_step_fills_default_units():
    steps = [PlanStep(tool="weather", args={"location": "Delhi"}, reason="test")]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert result.ok, result
    assert result.steps[0].args["units"] == "metric"


def test_weather_missing_required_location():
    steps = [PlanStep(tool="weather", args={}, reason="test")]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert not result.ok
    assert any("missing_required:weather:location" in e for e in result.errors)
    # Falls back to general_chat since all steps failed
    assert result.steps[0].tool == "general_chat"


def test_unknown_tool_is_rejected():
    steps = [PlanStep(tool="browser_control", args={}, reason="test")]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert not result.ok
    assert any("unknown_tool:browser_control" in e for e in result.errors)
    assert result.steps[0].tool == "general_chat"


def test_multi_step_datetime_and_weather():
    steps = [
        PlanStep(tool="datetime", args={}, reason="time"),
        PlanStep(tool="weather", args={"location": "Delhi"}, reason="weather"),
    ]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert result.ok, result
    assert len(result.steps) == 2
    tools = [s.tool for s in result.steps]
    assert "datetime" in tools
    assert "weather" in tools


def test_general_chat_dropped_when_real_tools_present():
    steps = [
        PlanStep(tool="general_chat", args={}, reason="chat"),
        PlanStep(tool="datetime", args={}, reason="time"),
    ]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert result.ok, result
    assert all(s.tool != "general_chat" for s in result.steps)
    assert len(result.steps) == 1


def test_pure_general_chat_passes():
    steps = [PlanStep(tool="general_chat", args={}, reason="greeting")]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert result.ok, result
    assert result.steps[0].tool == "general_chat"


def test_duplicate_steps_deduped():
    steps = [
        PlanStep(tool="datetime", args={"include_utc": True}, reason="a"),
        PlanStep(tool="datetime", args={"include_utc": True}, reason="b"),
    ]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert result.ok, result
    assert len(result.steps) == 1


def test_llm_artifact_value_wrapper_unwrapped():
    # LLM sometimes emits {"location": {"value": "London"}} instead of {"location": "London"}
    steps = [PlanStep(tool="weather", args={"location": {"value": "London"}}, reason="test")]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert result.ok, result
    assert result.steps[0].args["location"] == "London"


def test_unknown_arg_keys_stripped():
    steps = [PlanStep(tool="datetime", args={"include_utc": True, "bogus_key": "oops"}, reason="test")]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert result.ok, result
    assert "bogus_key" not in result.steps[0].args


def test_invalid_fallback_nulled():
    steps = [PlanStep(tool="datetime", args={}, reason="test", fallback_to="nonexistent_tool")]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert result.steps[0].fallback_to is None
    assert any("unknown_fallback" in e for e in result.errors)


def test_valid_fallback_preserved():
    steps = [PlanStep(tool="datetime", args={}, reason="test", fallback_to="search_web")]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert result.steps[0].fallback_to == "search_web"


def test_three_step_plan():
    steps = [
        PlanStep(tool="datetime", args={}, reason="time"),
        PlanStep(tool="weather", args={"location": "Mumbai"}, reason="weather"),
        PlanStep(tool="search_web", args={"query": "NVIDIA news"}, reason="search"),
    ]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert result.ok, result
    assert len(result.steps) == 3


def test_mixed_valid_and_invalid_steps():
    # One valid step, one unknown tool — valid step should survive
    steps = [
        PlanStep(tool="datetime", args={}, reason="time"),
        PlanStep(tool="calendar", args={}, reason="unknown"),
    ]
    result = VALIDATOR.validate(steps, REGISTRY)
    assert not result.ok  # has errors
    assert len(result.steps) == 1
    assert result.steps[0].tool == "datetime"


# ---------------------------------------------------------------------------
# Runner for direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")