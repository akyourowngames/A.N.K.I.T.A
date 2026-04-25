from __future__ import annotations

from dataclasses import dataclass

from jakata_agent.router import PlanFallback, PlanStep
from jakata_agent.tools.registry import ToolRegistry


@dataclass(slots=True)
class ValidationResult:
    steps: list[PlanStep]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def __repr__(self) -> str:  # makes test output readable
        if self.ok:
            return f"ValidationResult(ok=True, steps={[s.tool for s in self.steps]})"
        return f"ValidationResult(ok=False, errors={self.errors}, steps={[s.tool for s in self.steps]})"


class PlanValidator:
    """
    Validates a list of PlanSteps against the live ToolRegistry.

    Rules enforced:
    - Unknown tools are rejected (logged as errors).
    - general_chat is dropped when real tool steps exist.
    - Each tool's normalize_args() is called to fill defaults.
    - Required args are checked after normalization.
    - Unknown arg keys are stripped (tool schema is the contract).
    - Duplicate (tool, args) pairs are deduplicated.
    - fallback_to/fallbacks are validated and normalized when alternate tool attempts are available.
    - If all steps are rejected, falls back to a single general_chat step.
    """

    def validate(self, steps: list[PlanStep], registry: ToolRegistry) -> ValidationResult:
        errors: list[str] = []
        has_real_tools = any(step.tool != "general_chat" for step in steps)
        seen: set[tuple[str, str]] = set()
        validated: list[PlanStep] = []

        for step in steps:
            # Drop general_chat when real tool steps exist
            if step.tool == "general_chat":
                if not has_real_tools:
                    validated.append(step)
                continue

            tool = registry.get(step.tool)
            if tool is None:
                errors.append(f"unknown_tool:{step.tool}")
                continue

            args = self._normalize_tool_args(step.tool, step.args, tool, errors)
            if args is None:
                continue

            # Deduplicate
            dedup_key = (step.tool, str(sorted(args.items())))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Validate fallback
            fallback = step.fallback_to
            if fallback and registry.get(fallback) is None:
                errors.append(f"unknown_fallback:{step.tool}:{fallback}")
                fallback = None
            validated_fallbacks: list[PlanFallback] = []
            fallback_candidates = list(step.fallbacks)
            if fallback:
                fallback_candidates.append(PlanFallback(tool=fallback, args=args, reason="legacy fallback"))
            for candidate in fallback_candidates:
                fallback_tool = registry.get(candidate.tool)
                if fallback_tool is None:
                    errors.append(f"unknown_fallback:{step.tool}:{candidate.tool}")
                    continue
                fallback_args = self._normalize_tool_args(candidate.tool, candidate.args, fallback_tool, errors)
                if fallback_args is None:
                    continue
                if candidate.tool == step.tool and fallback_args == args:
                    continue
                validated_fallbacks.append(PlanFallback(tool=candidate.tool, args=fallback_args, reason=candidate.reason))

            validated.append(PlanStep(tool=step.tool, args=args, reason=step.reason, fallback_to=fallback, fallbacks=validated_fallbacks[:3]))

        if not validated:
            validated = [PlanStep(tool="general_chat", args={}, reason="validator_empty_fallback")]

        return ValidationResult(steps=validated, errors=errors)

    @staticmethod
    def _normalize_tool_args(tool_name: str, raw_args: dict, tool, errors: list[str]) -> dict | None:
        args: dict = {}
        for key, val in raw_args.items():
            if isinstance(val, dict) and list(val.keys()) == ["value"]:
                args[key] = val["value"]
            elif isinstance(val, dict):
                errors.append(f"bad_arg_shape:{tool_name}:{key}")
            else:
                args[key] = val

        args = tool.normalize_args(args)

        required = tool.input_schema.get("required", [])
        missing = [k for k in required if args.get(k) in (None, "")]
        if missing:
            errors.append(f"missing_required:{tool_name}:{','.join(missing)}")
            return None

        allowed = set(tool.input_schema.get("properties", {}).keys())
        return {k: v for k, v in args.items() if k in allowed}
