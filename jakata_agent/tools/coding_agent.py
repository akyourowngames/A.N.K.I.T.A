from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jakata_agent.llm import TextCompletionClient
from jakata_agent.prompts import load_prompt
from jakata_agent.tasks.approval import ApprovalGate
from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


CODING_PLANNER_PROMPT = load_prompt("coding_agent/planner.md")
CODING_VERIFIER_PROMPT = load_prompt("coding_agent/verifier.md")


@dataclass(slots=True)
class CodingAction:
    tool: str
    args: dict[str, Any]
    reason: str = ""


class CodingController:
    DEFAULT_ALLOWED_TOOLS = [
        "shell",
        "read_file",
        "list_dir",
        "search_files",
        "write_file",
        "search_web",
        "browser",
        "system",
        "screen",
        "ocr",
        "datetime",
    ]

    def __init__(self, client: TextCompletionClient, tools: ToolRegistry) -> None:
        self.client = client
        self.tools = tools

    def run_goal(
        self,
        goal: str,
        *,
        context: str = "",
        success_criteria: list[str] | None = None,
        cwd: str = "",
        budget_minutes: int = 20,
        allowed_tools: list[str] | None = None,
        repair_limit: int = 3,
        action_limit: int = 30,
        event_logger: Callable[[str, dict[str, Any]], None] | None = None,
        approval_gate: ApprovalGate | None = None,
    ) -> ToolResult:
        workspace = Path(cwd or Path.cwd()).expanduser().resolve()
        allowed = allowed_tools or list(self.DEFAULT_ALLOWED_TOOLS)
        criteria = [str(item).strip() for item in (success_criteria or []) if str(item).strip()] or [
            "The requested code or project change is implemented.",
            "Relevant checks or a direct runtime proof completed successfully.",
        ]
        started = time.time()
        observations: list[str] = []
        executed: list[dict[str, Any]] = []
        last_reason = "not_started"

        for attempt in range(repair_limit + 1):
            state = self._collect_state(workspace, allowed, goal)
            if executed:
                verdict = self._verify(goal, context, criteria, state, observations, executed, last_reason)
                if event_logger:
                    event_logger("verification_passed" if verdict["ok"] else "verification_failed", verdict)
                if verdict["ok"]:
                    return ToolResult(
                        ok=True,
                        summary=verdict["summary"],
                        data={
                            "goal": goal,
                            "cwd": str(workspace),
                            "observations": [*observations, *state["observations"]][-20:],
                            "executed": executed,
                            "reason": "verified",
                            "success_criteria": criteria,
                        },
                    )
                last_reason = str(verdict["reason"])

            if time.time() - started > budget_minutes * 60:
                return ToolResult(
                    ok=False,
                    summary="Coding task timed out.",
                    data={"goal": goal, "cwd": str(workspace), "observations": observations, "executed": executed, "reason": "timeout"},
                    error="timeout",
                )

            actions = self._plan_actions(
                goal=goal,
                context=context,
                success_criteria=criteria,
                workspace=workspace,
                allowed_tools=allowed,
                state=state,
                previous_observations=observations[-10:],
                executed=executed[-10:],
                last_reason=last_reason,
            )
            if not actions:
                return ToolResult(
                    ok=False,
                    summary="Coding planner produced no actions.",
                    data={"goal": goal, "cwd": str(workspace), "observations": observations, "executed": executed, "reason": "empty_plan"},
                    error="empty_plan",
                )

            for action in actions:
                if len(executed) >= action_limit:
                    return ToolResult(
                        ok=False,
                        summary="Coding action limit reached.",
                        data={"goal": goal, "cwd": str(workspace), "observations": observations, "executed": executed, "reason": "action_limit"},
                        error="action_limit",
                    )
                if approval_gate is not None:
                    approval_gate.require(action.tool, action.args, action.reason)
                if event_logger:
                    event_logger("action_started", {"tool": action.tool, "args": action.args, "reason": action.reason})
                result = self.tools.execute(action.tool, action.args)
                rendered = result.summary
                tool = self.tools.get(action.tool)
                if tool is not None:
                    try:
                        rendered = tool.render(result.data).strip() or rendered
                    except Exception:
                        rendered = result.summary
                record = {
                    "tool": action.tool,
                    "args": action.args,
                    "ok": result.ok,
                    "summary": result.summary,
                    "rendered": rendered,
                    "error": result.error,
                    "data": result.data,
                }
                executed.append(record)
                observations.append(f"[{action.tool}] {rendered[:1200]}")
                if event_logger:
                    event_logger("action_finished", {"tool": action.tool, "ok": result.ok, "summary": result.summary})
                if not result.ok:
                    last_reason = "tool_failure"
                    break

        return ToolResult(
            ok=False,
            summary=f"Coding task not verified: {last_reason}",
            data={"goal": goal, "cwd": str(workspace), "observations": observations, "executed": executed, "reason": last_reason},
            error=last_reason,
        )

    def _plan_actions(
        self,
        *,
        goal: str,
        context: str,
        success_criteria: list[str],
        workspace: Path,
        allowed_tools: list[str],
        state: dict[str, Any],
        previous_observations: list[str],
        executed: list[dict[str, Any]],
        last_reason: str,
    ) -> list[CodingAction]:
        manifest = [
            tool
            for tool in self.tools.manifest(public_only=False)
            if tool["name"] in set(allowed_tools) and tool["name"] not in {"coding_agent", "os_agent"}
        ]
        payload = {
            "goal": goal,
            "context": context,
            "success_criteria": success_criteria,
            "workspace": str(workspace),
            "allowed_tools": manifest,
            "state": state,
            "previous_observations": previous_observations,
            "recent_actions": executed,
            "last_reason": last_reason,
        }
        try:
            _, raw = self.client.complete_text(CODING_PLANNER_PROMPT, json.dumps(payload, ensure_ascii=False, default=str), temperature=0.0)
            parsed = self._clean_json(raw)
            steps = parsed.get("steps", [])
        except Exception:
            steps = []

        actions = self._parse_actions(steps, manifest, workspace)
        if actions:
            return actions
        return self._fallback_actions(goal, workspace, executed)

    def _parse_actions(self, steps: Any, manifest: list[dict[str, Any]], workspace: Path) -> list[CodingAction]:
        if not isinstance(steps, list):
            return []
        allowed_names = {item["name"] for item in manifest}
        actions: list[CodingAction] = []
        for item in steps[:8]:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool", "")).strip()
            if tool_name not in allowed_names:
                continue
            args = item.get("args", {})
            if not isinstance(args, dict):
                args = {}
            args = self._with_workspace(tool_name, args, workspace)
            tool = self.tools.get(tool_name)
            if tool is None:
                continue
            normalized = tool.normalize_args(args)
            required = tool.input_schema.get("required", [])
            if any(normalized.get(key) in (None, "") for key in required):
                continue
            allowed_args = set(tool.input_schema.get("properties", {}).keys())
            normalized = {key: value for key, value in normalized.items() if key in allowed_args}
            actions.append(CodingAction(tool=tool_name, args=normalized, reason=str(item.get("reason", "")).strip()))
        return actions

    @staticmethod
    def _with_workspace(tool_name: str, args: dict[str, Any], workspace: Path) -> dict[str, Any]:
        patched = dict(args)
        if tool_name in {"shell", "read_file", "list_dir", "search_files", "write_file"}:
            patched.setdefault("cwd", str(workspace))
        if tool_name == "shell":
            patched.setdefault("timeout", 180)
        return patched

    @staticmethod
    def _fallback_actions(goal: str, workspace: Path, executed: list[dict[str, Any]]) -> list[CodingAction]:
        lowered = goal.lower()
        if not executed and any(token in lowered for token in ("test", "pytest", "verify", "run checks")):
            return [CodingAction("shell", {"command": "python -m pytest -q", "cwd": str(workspace), "timeout": 600}, "fallback: run test suite")]
        if not executed:
            return [CodingAction("list_dir", {"path": ".", "cwd": str(workspace)}, "fallback: inspect workspace")]
        return []

    def _collect_state(self, workspace: Path, allowed_tools: list[str], goal: str) -> dict[str, Any]:
        state: dict[str, Any] = {"workspace": str(workspace), "observations": []}
        observations: list[str] = []
        if "list_dir" in allowed_tools and self.tools.get("list_dir") is not None:
            listed = self.tools.execute("list_dir", {"path": ".", "cwd": str(workspace), "pattern": "*"})
            if listed.ok:
                entries = listed.data.get("entries", [])
                state["root_entries"] = entries[:80] if isinstance(entries, list) else []
                observations.append(f"[list_dir] {listed.summary}")
        if "shell" in allowed_tools and self.tools.get("shell") is not None:
            status = self.tools.execute("shell", {"command": "git status --short", "cwd": str(workspace), "timeout": 20})
            if status.ok:
                state["git_status"] = str(status.data.get("stdout", "")).strip()
                observations.append("[git] " + (state["git_status"] or "clean"))
        if "screen" in allowed_tools and self.tools.get("screen") is not None and self._goal_mentions_screen(goal):
            capture = self.tools.execute("screen", {"action": "capture"})
            if capture.ok:
                state["screenshot_path"] = capture.data.get("path", "")
                observations.append(f"[screen] {capture.summary}")
        state["observations"] = observations
        return state

    def _verify(
        self,
        goal: str,
        context: str,
        success_criteria: list[str],
        state: dict[str, Any],
        observations: list[str],
        executed: list[dict[str, Any]],
        last_reason: str,
    ) -> dict[str, Any]:
        payload = {
            "goal": goal,
            "context": context,
            "success_criteria": success_criteria,
            "state": state,
            "observations": [*observations[-12:], *state.get("observations", [])[-6:]],
            "executed": executed[-12:],
            "last_reason": last_reason,
        }
        try:
            _, raw = self.client.complete_text(CODING_VERIFIER_PROMPT, json.dumps(payload, ensure_ascii=False, default=str), temperature=0.0)
            parsed = self._clean_json(raw)
            ok = bool(parsed.get("ok"))
            summary = str(parsed.get("summary", "")).strip() or ("Coding task verified." if ok else "Coding task not verified.")
            reason = str(parsed.get("reason", "verified" if ok else "verifier_rejected")).strip()
            return {"ok": ok, "summary": summary, "reason": reason, "evidence": payload["observations"][-4:]}
        except Exception:
            return self._heuristic_verify(executed, observations)

    @staticmethod
    def _heuristic_verify(executed: list[dict[str, Any]], observations: list[str]) -> dict[str, Any]:
        if not executed:
            return {"ok": False, "summary": "No coding actions ran.", "reason": "unknown", "evidence": observations[-4:]}
        if any(not item.get("ok") for item in executed[-3:]):
            return {"ok": False, "summary": "A recent coding action failed.", "reason": "tool_failure", "evidence": observations[-4:]}
        combined = "\n".join(str(item.get("rendered") or item.get("summary") or "") for item in executed).lower()
        if " passed" in combined or "no tests ran" in combined or any(item.get("tool") == "write_file" for item in executed):
            return {"ok": True, "summary": "Coding task has direct tool evidence.", "reason": "verified", "evidence": observations[-4:]}
        return {"ok": False, "summary": "Coding completion is not proven yet.", "reason": "verifier_rejected", "evidence": observations[-4:]}

    @staticmethod
    def _goal_mentions_screen(goal: str) -> bool:
        lowered = goal.lower()
        return any(token in lowered for token in ("screen", "screenshot", "visible", "browser", "open result", "preview"))

    @staticmethod
    def _clean_json(raw: str) -> dict[str, Any]:
        cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
        brace = cleaned.find("{")
        if brace > 0:
            cleaned = cleaned[brace:]
        end_brace = cleaned.rfind("}")
        if end_brace >= 0:
            cleaned = cleaned[: end_brace + 1]
        return json.loads(cleaned)


class CodingAgentTool(Tool):
    name = "coding_agent"
    safety = "write"
    description = (
        "Goal-oriented coding agent for repo edits, terminal commands, tests, online lookup, screenshots, "
        "and opening results with verify-and-repair loops."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "Coding goal to accomplish."},
            "context": {"type": "string", "description": "Additional context."},
            "success_criteria": {"type": "array", "items": {"type": "string"}, "description": "Optional explicit success criteria."},
            "cwd": {"type": "string", "description": "Workspace directory. Defaults to current process cwd."},
            "budget_minutes": {"type": "integer", "description": "Execution budget in minutes. Default 20, max 60."},
            "allowed_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional allowed tool names. Defaults to shell/files/search/browser/system/screen/ocr/datetime.",
            },
        },
        "required": ["goal"],
        "additionalProperties": False,
    }

    def __init__(self, controller: CodingController) -> None:
        self.controller = controller

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("context", "")
        args.setdefault("success_criteria", [])
        args.setdefault("cwd", "")
        args.setdefault("budget_minutes", 20)
        args["budget_minutes"] = max(1, min(int(args.get("budget_minutes", 20)), 60))
        args.setdefault("allowed_tools", list(CodingController.DEFAULT_ALLOWED_TOOLS))
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        normalized = self.normalize_args(dict(args))
        return self.controller.run_goal(
            str(normalized["goal"]),
            context=str(normalized.get("context", "")),
            success_criteria=list(normalized.get("success_criteria", [])),
            cwd=str(normalized.get("cwd", "")),
            budget_minutes=int(normalized.get("budget_minutes", 20)),
            allowed_tools=list(normalized.get("allowed_tools", list(CodingController.DEFAULT_ALLOWED_TOOLS))),
        )

    def render(self, data: dict[str, Any]) -> str:
        observations = data.get("observations", [])
        if isinstance(observations, list) and observations:
            return "\n".join(str(item) for item in observations[-8:])
        return str(data.get("goal", "Coding task complete."))
