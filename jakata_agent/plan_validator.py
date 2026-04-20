from __future__ import annotations

from dataclasses import dataclass

from jakata_agent.router import PlanStep
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
    - fallback_to is validated — nulled out if the fallback tool is not registered.
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

            # Unwrap LLM artifacts like {"value": "Delhi"} -> "Delhi"
            args: dict = {}
            for key, val in step.args.items():
                if isinstance(val, dict) and list(val.keys()) == ["value"]:
                    args[key] = val["value"]
                elif isinstance(val, dict):
                    errors.append(f"bad_arg_shape:{step.tool}:{key}")
                else:
                    args[key] = val

            # Let the tool fill its own defaults
            args = tool.normalize_args(args)

            # Check required fields
            required = tool.input_schema.get("required", [])
            missing = [k for k in required if args.get(k) in (None, "")]
            if missing:
                errors.append(f"missing_required:{step.tool}:{','.join(missing)}")
                continue

            # Strip keys the tool doesn't declare
            allowed = set(tool.input_schema.get("properties", {}).keys())
            args = {k: v for k, v in args.items() if k in allowed}

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

            validated.append(PlanStep(tool=step.tool, args=args, reason=step.reason, fallback_to=fallback))

        if not validated:
            validated = [PlanStep(tool="general_chat", args={}, reason="validator_empty_fallback")]

        return ValidationResult(steps=validated, errors=errors)