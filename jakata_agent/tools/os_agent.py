from __future__ import annotations

import json
import platform
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from jakata_agent.llm import TextCompletionClient
from jakata_agent.prompts import load_prompt
from jakata_agent.tasks.approval import ApprovalGate
from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


OS_PLANNER_PROMPT = load_prompt("os_agent/planner.md")
OS_SPEC_PROMPT = load_prompt("os_agent/spec_builder.md")
OS_VERIFIER_PROMPT = load_prompt("os_agent/verifier.md")
OS_MODAL_RECOVERY_PROMPT = load_prompt("os_agent/modal_recovery.md")


@dataclass(slots=True)
class OsAction:
    tool: str
    args: dict[str, Any]
    reason: str = ""


class OsController:
    DEFAULT_ALLOWED_SURFACES = [
        "browser",
        "shell",
        "files",
        "window",
        "keyboard",
        "clipboard",
        "mouse",
        "system",
        "screen",
        "ocr",
    ]
    KILL_SWITCH_NAME = "kill.switch"

    def __init__(
        self,
        client: TextCompletionClient,
        tools: ToolRegistry,
        kill_switch_path: str,
        browser_client: TextCompletionClient | None = None,
    ) -> None:
        self.client = client
        self.browser_client = browser_client or client
        self.tools = tools
        self.kill_switch_path = kill_switch_path

    def run_goal(
        self,
        goal: str,
        *,
        context: str = "",
        success_criteria: list[str] | None = None,
        budget_minutes: int = 20,
        allowed_surfaces: list[str] | None = None,
        cwd: str = "",
        event_logger: Callable[[str, dict[str, Any]], None] | None = None,
        approval_gate: ApprovalGate | None = None,
        repair_limit: int = 5,
        action_limit: int = 30,
    ) -> ToolResult:
        del cwd
        derived = self._derive_task_spec(goal, context, success_criteria or [])
        criteria = derived["success_criteria"]
        allowed = allowed_surfaces or list(self.DEFAULT_ALLOWED_SURFACES)
        started = time.time()
        observations: list[str] = []
        executed: list[dict[str, Any]] = []
        last_reason = "unknown"

        for attempt in range(repair_limit + 1):
            state_snapshot = self._collect_state_snapshot(allowed, goal=goal, success_criteria=criteria)
            precheck = self._verify(
                goal,
                context,
                criteria,
                state_snapshot["observations"][-12:],
                executed[-8:],
                system_state=state_snapshot["state"],
            )
            if precheck["ok"]:
                return ToolResult(
                    ok=True,
                    summary=precheck["summary"],
                    data={
                        "goal": goal,
                        "observations": state_snapshot["observations"],
                        "executed": executed,
                        "reason": precheck["reason"],
                        "success_criteria": criteria,
                        "completion_hint": derived["completion_hint"],
                    },
                )
            if self._kill_switch_active():
                return ToolResult(ok=False, summary="Kill switch is active.", data={"reason": "canceled"}, error="canceled")
            if time.time() - started > budget_minutes * 60:
                return ToolResult(
                    ok=False,
                    summary="OS task timed out.",
                    data={"reason": "timeout", "observations": observations, "executed": executed},
                    error="timeout",
                )

            actions = self._plan_actions(
                goal=goal,
                context=context,
                success_criteria=criteria,
                allowed_surfaces=allowed,
                previous_observations=[*state_snapshot["observations"][-4:], *observations[-8:]],
                executed=executed[-10:],
                last_reason=last_reason,
                system_state=state_snapshot["state"],
            )
            if not actions:
                return ToolResult(
                    ok=False,
                    summary="OS planner produced no actions.",
                    data={"reason": "unknown", "observations": observations, "executed": executed},
                    error="empty_plan",
                )

            batch_error: dict[str, Any] | None = None
            for action in actions:
                if len(executed) >= action_limit:
                    return ToolResult(
                        ok=False,
                        summary="OS action limit reached.",
                        data={"reason": "timeout", "observations": observations, "executed": executed},
                        error="action_limit",
                    )
                if action.tool in {"keyboard", "mouse"}:
                    guard = self._guard_active_surface(action.tool)
                    observations.extend(guard["observations"])
                    if not guard["ok"]:
                        last_reason = str(guard["reason"])
                        batch_error = {"ok": False, "summary": guard["summary"], "reason": last_reason, "evidence": guard["observations"]}
                        if event_logger:
                            event_logger("verification_failed", {"reason": last_reason, "summary": guard["summary"]})
                        break

                if event_logger:
                    event_logger("action_started", {"tool": action.tool, "args": action.args, "reason": action.reason})
                if approval_gate is not None:
                    approval_gate.require(action.tool, action.args, action.reason)
                result = self.tools.execute(action.tool, action.args)
                rendered = result.summary
                tool = self.tools.get(action.tool)
                if result.ok and tool is not None:
                    try:
                        rendered = tool.render(result.data).strip() or rendered
                    except Exception:
                        rendered = result.summary
                executed.append(
                    {
                        "tool": action.tool,
                        "args": action.args,
                        "ok": result.ok,
                        "summary": result.summary,
                        "rendered": rendered,
                    }
                )
                observations.append(f"[{action.tool}] {rendered}")
                if event_logger:
                    event_logger(
                        "action_finished",
                        {"tool": action.tool, "ok": result.ok, "summary": result.summary, "rendered": rendered},
                    )
                if not result.ok:
                    last_reason = "tool_failure"
                    batch_error = {"ok": False, "summary": result.summary, "reason": last_reason, "evidence": [rendered]}
                    break

                if action.tool in {"keyboard", "mouse"}:
                    post_guard = self._guard_active_surface(action.tool)
                    observations.extend(post_guard["observations"])
                    if not post_guard["ok"]:
                        last_reason = str(post_guard["reason"])
                        batch_error = {
                            "ok": False,
                            "summary": post_guard["summary"],
                            "reason": last_reason,
                            "evidence": post_guard["observations"],
                        }
                        break

            state_snapshot = self._collect_state_snapshot(allowed, goal=goal, success_criteria=criteria)
            verdict = batch_error or self._verify(
                goal,
                context,
                criteria,
                [*observations[-12:], *state_snapshot["observations"][-4:]],
                executed[-8:],
                system_state=state_snapshot["state"],
            )
            if event_logger:
                event_logger(
                    "verification_passed" if verdict["ok"] else "verification_failed",
                    {"reason": verdict["reason"], "summary": verdict["summary"], "evidence": verdict["evidence"]},
                )
            if verdict["ok"]:
                return ToolResult(
                    ok=True,
                    summary=verdict["summary"],
                    data={
                        "goal": goal,
                        "observations": observations,
                        "executed": executed,
                        "reason": verdict["reason"],
                        "success_criteria": criteria,
                        "completion_hint": derived["completion_hint"],
                    },
                )
            last_reason = str(verdict["reason"])
            observations.extend(verdict["evidence"])
            if event_logger:
                event_logger("repair_planned", {"attempt": attempt + 1, "reason": last_reason, "summary": verdict["summary"]})

        return ToolResult(
            ok=False,
            summary=f"OS task not verified: {last_reason}",
            data={"goal": goal, "observations": observations, "executed": executed, "reason": last_reason},
            error=last_reason,
        )

    def _derive_task_spec(self, goal: str, context: str, existing_criteria: list[str]) -> dict[str, Any]:
        cleaned_existing = [str(item).strip() for item in existing_criteria if str(item).strip()]
        if cleaned_existing:
            return {"success_criteria": cleaned_existing[:4], "completion_hint": "one_shot"}

        payload = {"goal": goal, "context": context}
        try:
            _, raw = self.client.complete_text(OS_SPEC_PROMPT, json.dumps(payload, ensure_ascii=False), temperature=0.0)
            parsed = self._clean_json(raw)
            criteria = [str(item).strip() for item in parsed.get("success_criteria", []) if str(item).strip()]
            hint = str(parsed.get("completion_hint", "one_shot")).strip().lower()
            if hint not in {"one_shot", "persistent"}:
                hint = "one_shot"
            if criteria:
                return {"success_criteria": criteria[:4], "completion_hint": hint}
        except Exception:
            pass
        return {
            "success_criteria": [
                f"The requested goal is visibly completed: {goal}",
                "The final screen or tool state matches the requested outcome.",
            ],
            "completion_hint": "one_shot",
        }

    def _plan_actions(
        self,
        *,
        goal: str,
        context: str,
        success_criteria: list[str],
        allowed_surfaces: list[str],
        previous_observations: list[str],
        executed: list[dict[str, Any]],
        last_reason: str,
        system_state: dict[str, Any],
    ) -> list[OsAction]:
        manifest = []
        for tool in self.tools.manifest(public_only=False):
            if tool["name"] == "os_agent":
                continue
            if not self._tool_allowed(tool["name"], allowed_surfaces):
                continue
            manifest.append(tool)
        blocker = self._detect_modal_blocker(system_state)
        if blocker is not None:
            recovery = self._plan_modal_recovery(
                goal=goal,
                context=context,
                blocker=blocker,
                previous_observations=previous_observations,
                manifest=manifest,
                system_state=system_state,
            )
            if recovery:
                return recovery
        browser_goal = self._classify_browser_goal(goal, success_criteria)
        browser_repair = self._plan_browser_recovery(
            goal_state=browser_goal,
            system_state=system_state,
            previous_observations=previous_observations,
            executed=executed,
        )
        if browser_repair:
            return browser_repair
        payload = {
            "goal": goal,
            "context": context,
            "success_criteria": success_criteria,
            "allowed_tools": manifest,
            "previous_observations": previous_observations,
            "recent_actions": executed,
            "last_reason": last_reason,
            "system_state": system_state,
            "platform": self._platform_context(),
            "detected_blocker": blocker,
            "browser_goal": browser_goal,
        }
        planner_client = self.browser_client if browser_goal.get("kind") != "none" else self.client
        try:
            _, raw = planner_client.complete_text(OS_PLANNER_PROMPT, json.dumps(payload, ensure_ascii=False), temperature=0.0)
            parsed = self._clean_json(raw)
            steps = parsed.get("steps", [])
        except Exception:
            return []
        actions: list[OsAction] = []
        allowed_tool_names = {item["name"] for item in manifest}
        for item in steps[:6]:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool", "")).strip()
            if tool_name not in allowed_tool_names:
                continue
            args = item.get("args", {})
            if not isinstance(args, dict):
                args = {}
            actions.append(OsAction(tool=tool_name, args=args, reason=str(item.get("reason", "")).strip()))
        return actions

    def _verify(
        self,
        goal: str,
        context: str,
        success_criteria: list[str],
        observations: list[str],
        executed: list[dict[str, Any]],
        system_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system_state = system_state or {}
        blocker = self._detect_modal_blocker(system_state)
        if blocker is not None:
            return {
                "ok": False,
                "summary": blocker["summary"],
                "reason": "blocked_by_modal",
                "evidence": blocker["evidence"],
            }
        browser_goal = self._classify_browser_goal(goal, success_criteria)
        browser_verdict = self._verify_browser_goal(browser_goal, system_state, observations)
        if browser_verdict is not None:
            return browser_verdict
        browser_state = system_state.get("browser", {}) if isinstance(system_state.get("browser", {}), dict) else {}
        if self._goal_requires_foreground_browser(goal, success_criteria):
            if browser_state.get("has_chrome_window") and not browser_state.get("is_browser_foreground"):
                return {
                    "ok": False,
                    "summary": "Chrome exists but is not the active foreground window yet.",
                    "reason": "unmet_precondition",
                    "evidence": observations[-3:],
                }
        failures = [step for step in executed if not step.get("ok")]
        if failures:
            return {
                "ok": False,
                "summary": failures[-1].get("summary", "tool failure"),
                "reason": "tool_failure",
                "evidence": [failures[-1].get("rendered", failures[-1].get("summary", ""))],
            }
        payload = {
            "goal": goal,
            "context": context,
            "success_criteria": success_criteria,
            "observations": observations,
            "executed": executed,
            "system_state": system_state,
            "platform": self._platform_context(),
        }
        try:
            _, raw = self.client.complete_text(OS_VERIFIER_PROMPT, json.dumps(payload, ensure_ascii=False), temperature=0.0)
            parsed = self._clean_json(raw)
            ok = bool(parsed.get("ok"))
            summary = str(parsed.get("summary", "")).strip() or ("Goal verified." if ok else "Goal not verified.")
            reason = str(parsed.get("reason", "verified" if ok else "verifier_rejected")).strip()
            if reason not in {
                "verified",
                "tool_failure",
                "unmet_precondition",
                "wrong_window",
                "ocr_uncertain",
                "verifier_rejected",
                "blocked_by_login",
                "blocked_by_modal",
                "timeout",
                "unknown",
            }:
                reason = "verified" if ok else "unknown"
            return {"ok": ok, "summary": summary, "reason": reason, "evidence": observations[-3:]}
        except Exception:
            return self._heuristic_verify(goal, success_criteria, observations, executed, system_state)

    def _guard_active_surface(self, surface: str) -> dict[str, Any]:
        observations: list[str] = []
        active = self.tools.execute("window", {"action": "active"})
        if not active.ok:
            return {"ok": False, "reason": "wrong_window", "summary": active.summary, "observations": observations}
        active_title = str(active.data.get("title", "")).strip()
        observations.append(f"[window] Active window: {active_title}")
        capture = self.tools.execute("screen", {"action": "capture"})
        if not capture.ok:
            return {"ok": False, "reason": "ocr_uncertain", "summary": capture.summary, "observations": observations}
        ocr = self.tools.execute("ocr", {"action": "extract_text", "path": capture.data.get("path", "")})
        if not ocr.ok:
            return {"ok": False, "reason": "ocr_uncertain", "summary": ocr.summary, "observations": observations}
        text = str(ocr.data.get("text", "")).strip()
        observations.append(f"[ocr] {text[:300]}")
        if not active_title and not text:
            return {
                "ok": False,
                "reason": "wrong_window",
                "summary": f"No active {surface} target context.",
                "observations": observations,
            }
        return {"ok": True, "reason": "verified", "summary": f"{surface.title()} target confirmed.", "observations": observations}

    def _collect_state_snapshot(
        self,
        allowed_surfaces: list[str],
        *,
        goal: str = "",
        success_criteria: list[str] | None = None,
    ) -> dict[str, Any]:
        state: dict[str, Any] = {"platform": self._platform_context()}
        observations: list[str] = []

        if "window" in allowed_surfaces:
            active = self.tools.execute("window", {"action": "active"})
            if active.ok:
                title = str(active.data.get("title", "")).strip()
                state["active_window"] = title
                state["active_window_bounds"] = {
                    key: int(active.data.get(key, 0))
                    for key in ("left", "top", "width", "height", "right", "bottom")
                    if key in active.data
                }
                if title:
                    observations.append(f"[window] Active window: {title}")
                if state["active_window_bounds"]:
                    observations.append(f"[window_bounds] {json.dumps(state['active_window_bounds'], ensure_ascii=False)}")
            listed = self.tools.execute("window", {"action": "list"})
            if listed.ok:
                windows = listed.data.get("windows", [])
                if isinstance(windows, list):
                    state["window_titles"] = [str(item) for item in windows[:20]]
                    if state["window_titles"]:
                        observations.append("[windows] " + " | ".join(state["window_titles"][:6]))

        if "browser" in allowed_surfaces and self.tools.get("browser") is not None:
            browser_goal = self._classify_browser_goal(goal, success_criteria or [])
            inspect_args: dict[str, Any] = {"action": "inspect"}
            if browser_goal.get("query"):
                inspect_args["query"] = browser_goal["query"]
            browser = self.tools.execute("browser", inspect_args)
            if browser.ok:
                state["browser"] = browser.data
                active_title = str(browser.data.get("active_browser_title", "")).strip()
                if active_title:
                    observations.append(f"[browser] Active browser title: {active_title}")
                chrome_titles = browser.data.get("chrome_titles", [])
                if isinstance(chrome_titles, list) and chrome_titles:
                    observations.append("[browser_windows] " + " | ".join(str(item) for item in chrome_titles[:4]))
                current_url = str(browser.data.get("current_url", "")).strip()
                if current_url:
                    observations.append(f"[browser_url] {current_url}")
                page_kind = str(browser.data.get("page_kind", "")).strip()
                if page_kind:
                    observations.append(f"[browser_page] {page_kind}")
                focus_context = str(browser.data.get("focus_context", "")).strip()
                if focus_context:
                    observations.append(f"[browser_focus] {focus_context}")
                playback = str(browser.data.get("playback_ui_state", "")).strip()
                if playback and playback != "unknown":
                    observations.append(f"[browser_playback] {playback}")

        if "system" in allowed_surfaces:
            system_status = self.tools.execute("system", {"action": "status"})
            if system_status.ok and isinstance(system_status.data, dict):
                state["system"] = system_status.data
                summary = str(system_status.summary).strip()
                if summary:
                    observations.append(f"[system] {summary}")
            processes = self.tools.execute("system", {"action": "list_processes", "max_results": 12})
            if processes.ok:
                proc_data = processes.data.get("processes", [])
                state["processes"] = proc_data
                names = [str(item.get("name", "")) for item in proc_data[:8] if str(item.get("name", ""))]
                if names:
                    observations.append("[processes] " + " | ".join(names))

        if "screen" in allowed_surfaces and "ocr" in allowed_surfaces:
            capture = self.tools.execute("screen", {"action": "capture"})
            if capture.ok:
                path = str(capture.data.get("path", "")).strip()
                state["screenshot_path"] = path
                ocr = self.tools.execute("ocr", {"action": "extract_text", "path": path})
                if ocr.ok:
                    text = str(ocr.data.get("text", "")).strip()
                    state["ocr_text"] = text[:2000]
                    if text:
                        observations.append(f"[ocr] {text[:500]}")
                else:
                    state["ocr_error"] = ocr.error or ocr.summary
                    observations.append(f"[ocr_error] {ocr.summary}")
            else:
                state["screen_error"] = capture.error or capture.summary
                observations.append(f"[screen_error] {capture.summary}")

        if "mouse" in allowed_surfaces:
            pointer = self.tools.execute("mouse", {"action": "position"})
            if pointer.ok:
                state["cursor"] = {"x": int(pointer.data.get("x", 0)), "y": int(pointer.data.get("y", 0))}
                observations.append(f"[cursor] ({state['cursor']['x']}, {state['cursor']['y']})")

        blocker = self._detect_modal_blocker(state)
        if blocker is not None:
            state["modal_dialog"] = blocker
            observations.append(f"[modal] {blocker['summary']}")

        return {"state": state, "observations": observations}

    def _plan_modal_recovery(
        self,
        *,
        goal: str,
        context: str,
        blocker: dict[str, Any],
        previous_observations: list[str],
        manifest: list[dict[str, Any]],
        system_state: dict[str, Any],
    ) -> list[OsAction]:
        payload = {
            "goal": goal,
            "context": context,
            "blocker": blocker,
            "previous_observations": previous_observations,
            "allowed_tools": [tool for tool in manifest if tool["name"] in {"keyboard", "mouse", "window", "system", "browser"}],
            "system_state": system_state,
            "platform": self._platform_context(),
        }
        try:
            _, raw = self.client.complete_text(OS_MODAL_RECOVERY_PROMPT, json.dumps(payload, ensure_ascii=False), temperature=0.0)
            parsed = self._clean_json(raw)
            steps = parsed.get("steps", [])
        except Exception:
            steps = []
        if not isinstance(steps, list):
            return []
        actions: list[OsAction] = []
        allowed_tool_names = {item["name"] for item in manifest}
        for item in steps[:3]:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool", "")).strip()
            if tool_name not in allowed_tool_names:
                continue
            args = item.get("args", {})
            if not isinstance(args, dict):
                args = {}
            actions.append(OsAction(tool=tool_name, args=args, reason=str(item.get("reason", "")).strip() or "modal_recovery"))
        return actions

    def _detect_modal_blocker(self, system_state: dict[str, Any]) -> dict[str, Any] | None:
        existing = system_state.get("modal_dialog")
        if isinstance(existing, dict) and existing.get("summary"):
            return existing

        active_title = str(system_state.get("active_window", "")).strip()
        ocr_text = str(system_state.get("ocr_text", "")).strip()
        if not active_title and not ocr_text:
            return None

        title_lower = active_title.lower()
        text_lower = ocr_text.lower()
        combined = f"{title_lower}\n{text_lower}".strip()
        if not combined:
            return None

        modal_markers = [
            "confirm save as",
            "save as",
            "do you want to replace it",
            "replace it?",
            "already exists",
            "save changes",
            "do you want to save",
            "are you sure",
            "permission",
            "allow access",
            "confirm",
            "warning",
            "error",
            "replace",
            "overwrite",
        ]
        decision_markers = [
            "yes",
            "no",
            "ok",
            "cancel",
            "replace",
            "skip",
            "save",
            "don't save",
            "allow",
            "deny",
        ]
        if not any(marker in combined for marker in modal_markers):
            if not (any(marker in title_lower for marker in ("confirm", "warning", "error", "permission")) and any(marker in text_lower for marker in decision_markers)):
                return None

        evidence: list[str] = []
        if active_title:
            evidence.append(f"[window] {active_title}")
        excerpt = ocr_text.replace("\r", " ").replace("\n", " ").strip()
        if excerpt:
            evidence.append(f"[ocr] {excerpt[:280]}")
        summary = active_title or excerpt[:120] or "Blocking popup detected."
        if excerpt:
            summary = f"Blocking popup detected: {excerpt[:120]}"
        return {
            "title": active_title,
            "text": excerpt[:1200],
            "summary": summary,
            "evidence": evidence,
            "window_bounds": system_state.get("active_window_bounds", {}),
            "cursor": system_state.get("cursor", {}),
        }

    def _heuristic_verify(
        self,
        goal: str,
        success_criteria: list[str],
        observations: list[str],
        executed: list[dict[str, Any]],
        system_state: dict[str, Any],
    ) -> dict[str, Any]:
        blocker = self._detect_modal_blocker(system_state)
        if blocker is not None:
            return {"ok": False, "summary": blocker["summary"], "reason": "blocked_by_modal", "evidence": blocker["evidence"]}
        if not executed:
            return {"ok": False, "summary": "No task actions were executed.", "reason": "unknown", "evidence": observations[-3:]}

        haystack_parts = [goal, *success_criteria, *observations]
        haystack_parts.append(str(system_state.get("active_window", "")))
        haystack_parts.append(str(system_state.get("ocr_text", "")))
        browser = system_state.get("browser", {})
        if isinstance(browser, dict):
            haystack_parts.extend(str(item) for item in browser.get("chrome_titles", []) if str(item).strip())
        haystack = "\n".join(part for part in haystack_parts if str(part).strip()).lower()

        criteria = [item for item in success_criteria if str(item).strip()] or [goal]
        matched = [self._criterion_matches(str(item), haystack) for item in criteria]
        strong_signal = any(signal in haystack for signal in ["saved", "replaced", "opened", "visible", "focused", "completed", "done"])
        if matched and all(matched) and strong_signal:
            return {
                "ok": True,
                "summary": "Heuristic verifier accepted the final screen state.",
                "reason": "verified",
                "evidence": observations[-4:],
            }
        return {
            "ok": False,
            "summary": "Verification was unavailable and the final machine state is not proven yet.",
            "reason": "verifier_rejected",
            "evidence": observations[-4:],
        }

    def _classify_browser_goal(self, goal: str, success_criteria: list[str]) -> dict[str, Any]:
        haystack_goal = goal.lower()
        haystack = " ".join([goal, *success_criteria]).lower()
        explicit_url = self._extract_explicit_url(goal) or self._extract_explicit_url(" ".join(success_criteria))
        if not any(
            token in haystack_goal
            for token in ("chrome", "browser", "site", "website", "homepage", "youtube", "google", "play", "watch", "listen", "search", "open")
        ) and not explicit_url:
            return {"kind": "none", "query": "", "url": "", "site": ""}

        kind = "open_page"
        site = "youtube" if "youtube" in haystack_goal or "youtu" in haystack_goal else "web"
        if any(token in haystack_goal for token in ("play ", "play the", "listen", "watch", "song", "music", "video")):
            kind = "media_playback"
            if site == "web":
                site = "youtube"
        elif any(token in haystack_goal for token in ("search", "look up", "find")):
            kind = "search_only"

        query = self._extract_browser_query(goal, kind=kind)
        if not query and explicit_url:
            query = explicit_url
        return {"kind": kind, "query": query, "url": explicit_url, "site": site}

    def _plan_browser_recovery(
        self,
        *,
        goal_state: dict[str, Any],
        system_state: dict[str, Any],
        previous_observations: list[str],
        executed: list[dict[str, Any]] | None = None,
    ) -> list[OsAction]:
        del previous_observations
        executed = executed or []
        if goal_state.get("kind") == "none":
            return []
        browser = system_state.get("browser", {})
        if not isinstance(browser, dict):
            browser = {}

        has_chrome = bool(browser.get("has_chrome_window"))
        foreground = bool(browser.get("is_browser_foreground"))
        current_url = str(browser.get("current_url", "")).strip()
        query = str(goal_state.get("query", "")).strip()
        site = str(goal_state.get("site", "web")).strip() or "web"
        kind = str(goal_state.get("kind", "open_page")).strip() or "open_page"
        address_bar_focused = bool(browser.get("address_bar_focused"))
        focus_context = str(browser.get("focus_context", "")).strip()
        page_kind = str(browser.get("page_kind", "")).strip()
        browser_loop = self._browser_action_loop(executed)

        if not has_chrome:
            if goal_state.get("url"):
                return [OsAction(tool="browser", args={"action": "open_url", "url": goal_state["url"]}, reason="open_target_url")]
            if query:
                return [OsAction(tool="browser", args={"action": "search", "query": query, "engine": site}, reason="open_browser_search")]
            return []
        if not foreground:
            return [OsAction(tool="browser", args={"action": "focus"}, reason="focus_browser")]
        if focus_context == "address_bar_query":
            return [OsAction(tool="browser", args={"action": "commit_address_bar", "query": query}, reason="commit_address_bar_query")]
        if address_bar_focused and (browser.get("is_search_results_page") or browser.get("target_match") or str(browser.get("page_kind", "")).strip() not in {"", "unknown"}):
            return [OsAction(tool="browser", args={"action": "dismiss_address_bar", "query": query}, reason="return_focus_to_page")]
        if browser_loop and browser.get("is_search_results_page") and kind != "search_only":
            return [OsAction(tool="browser", args={"action": "open_result", "result_index": 0}, reason="break_browser_search_loop")]

        if kind == "media_playback":
            if browser.get("is_search_results_page"):
                return [OsAction(tool="browser", args={"action": "open_result", "result_index": 0}, reason="open_first_media_result")]
            if not browser.get("is_target_media_page"):
                if query:
                    return [OsAction(tool="browser", args={"action": "search", "query": query, "engine": site}, reason="search_media_target")]
                return []
            if not browser.get("target_match") and query:
                return [OsAction(tool="browser", args={"action": "search", "query": query, "engine": site}, reason="recover_media_target")]
            if str(browser.get("playback_ui_state", "unknown")) != "playing":
                return [OsAction(tool="browser", args={"action": "play_pause", "query": query}, reason="start_media_playback")]
            return []

        if kind == "search_only":
            if query and current_url and not browser.get("target_match"):
                return [OsAction(tool="browser", args={"action": "search", "query": query, "engine": site}, reason="refresh_search_results")]
            return []

        if goal_state.get("url"):
            if current_url != goal_state["url"]:
                return [OsAction(tool="browser", args={"action": "open_url", "url": goal_state["url"]}, reason="open_target_page")]
            return []
        if query and browser.get("is_search_results_page"):
            return [OsAction(tool="browser", args={"action": "open_result", "result_index": 0}, reason="open_first_result")]
        if kind == "open_page" and site == "web" and self._is_wrong_web_target(browser):
            if query and self._same_browser_action_repeated(executed, "search", query=query, threshold=2):
                return []
            return [OsAction(tool="browser", args={"action": "search", "query": query, "engine": "web"}, reason="recover_web_target")]
        if query and not browser.get("target_match"):
            if self._same_browser_action_repeated(executed, "search", query=query, threshold=2):
                return []
            return [OsAction(tool="browser", args={"action": "search", "query": query, "engine": site}, reason="search_target_page")]
        return []

    @staticmethod
    def _browser_action_loop(executed: list[dict[str, Any]]) -> bool:
        recent = [
            str(step.get("args", {}).get("action", "")).strip()
            for step in executed[-6:]
            if step.get("tool") == "browser" and isinstance(step.get("args"), dict)
        ]
        if len(recent) < 4:
            return False
        if len(set(recent[-4:])) <= 2 and any(action in {"search", "open_url", "dismiss_address_bar", "commit_address_bar"} for action in recent[-4:]):
            return True
        return recent[-3:] == ["search", "search", "search"]

    @staticmethod
    def _same_browser_action_repeated(
        executed: list[dict[str, Any]],
        action: str,
        *,
        query: str = "",
        threshold: int = 2,
    ) -> bool:
        count = 0
        for step in reversed(executed):
            if step.get("tool") != "browser" or not isinstance(step.get("args"), dict):
                continue
            args = step["args"]
            if str(args.get("action", "")).strip() != action:
                continue
            if query and str(args.get("query", "")).strip().lower() != query.lower():
                continue
            count += 1
            if count >= threshold:
                return True
        return False

    def _verify_browser_goal(
        self,
        goal_state: dict[str, Any],
        system_state: dict[str, Any],
        observations: list[str],
    ) -> dict[str, Any] | None:
        if goal_state.get("kind") == "none":
            return None
        browser = system_state.get("browser", {})
        if not isinstance(browser, dict):
            return {
                "ok": False,
                "summary": "Browser state is unavailable.",
                "reason": "unmet_precondition",
                "evidence": observations[-3:],
            }
        if not browser.get("has_chrome_window"):
            return {
                "ok": False,
                "summary": "Chrome is not open yet.",
                "reason": "unmet_precondition",
                "evidence": observations[-3:],
            }
        if not browser.get("is_browser_foreground"):
            return {
                "ok": False,
                "summary": "Chrome exists but is not the active foreground window yet.",
                "reason": "unmet_precondition",
                "evidence": observations[-3:],
            }

        kind = str(goal_state.get("kind", "open_page")).strip()
        expected_site = str(goal_state.get("site", "web")).strip() or "web"
        target_match = bool(browser.get("target_match"))
        page_kind = str(browser.get("page_kind", "unknown")).strip()
        playback = str(browser.get("playback_ui_state", "unknown")).strip()
        focus_context = str(browser.get("focus_context", "")).strip()
        if focus_context == "address_bar_query":
            return {
                "ok": False,
                "summary": "Chrome focus is still in the address bar with pending input.",
                "reason": "unmet_precondition",
                "evidence": observations[-4:],
            }
        if kind == "search_only":
            if browser.get("is_search_results_page") and target_match:
                return {
                    "ok": True,
                    "summary": "Search results are visible in Chrome.",
                    "reason": "verified",
                    "evidence": observations[-4:],
                }
            return {
                "ok": False,
                "summary": "Expected a search results page, but the current browser state does not prove it yet.",
                "reason": "verifier_rejected",
                "evidence": observations[-4:],
            }

        if kind == "media_playback":
            if browser.get("is_search_results_page"):
                return {
                    "ok": False,
                    "summary": "Chrome is still on search results instead of the media page.",
                    "reason": "verifier_rejected",
                    "evidence": observations[-4:],
                }
            if page_kind != "youtube_watch":
                return {
                    "ok": False,
                    "summary": "The target media page is not open yet.",
                    "reason": "unmet_precondition",
                    "evidence": observations[-4:],
                }
            if not target_match:
                return {
                    "ok": False,
                    "summary": "A media page is open, but it does not yet match the requested song/video.",
                    "reason": "verifier_rejected",
                    "evidence": observations[-4:],
                }
            if playback != "playing":
                return {
                    "ok": False,
                    "summary": "The target media page is open, but playback is not proven active yet.",
                    "reason": "verifier_rejected",
                    "evidence": observations[-4:],
                }
            return {
                "ok": True,
                "summary": "The target media page is open and playback UI indicates it is playing.",
                "reason": "verified",
                "evidence": observations[-4:],
            }

        if browser.get("is_search_results_page"):
            return {
                "ok": False,
                "summary": "Chrome is still showing search results instead of the target page.",
                "reason": "verifier_rejected",
                "evidence": observations[-4:],
            }
        if kind == "open_page" and expected_site == "web" and self._is_wrong_web_target(browser):
            return {
                "ok": False,
                "summary": "A matching page is open, but it is not the requested normal website/homepage target.",
                "reason": "verifier_rejected",
                "evidence": observations[-4:],
            }
        if goal_state.get("url"):
            current_url = str(browser.get("current_url", "")).strip()
            if current_url and current_url.startswith(str(goal_state["url"])):
                return {
                    "ok": True,
                    "summary": "The target page is open in Chrome.",
                    "reason": "verified",
                    "evidence": observations[-4:],
                }
        if target_match:
            return {
                "ok": True,
                "summary": "The target page is open in Chrome.",
                "reason": "verified",
                "evidence": observations[-4:],
            }
        return {
            "ok": False,
            "summary": "The intended browser page is not proven yet.",
            "reason": "verifier_rejected",
            "evidence": observations[-4:],
        }

    @staticmethod
    def _is_wrong_web_target(browser: dict[str, Any]) -> bool:
        current_url = str(browser.get("current_url", "")).lower()
        page_kind = str(browser.get("page_kind", "")).lower()
        if page_kind in {"youtube_search_results", "youtube_watch", "google_search_results"}:
            return True
        wrong_hosts = ("youtube.com/", "youtu.be/", "google.com/search", "bing.com/search")
        return any(host in current_url for host in wrong_hosts)

    @staticmethod
    def _extract_explicit_url(text: str) -> str:
        found = re.search(r"https?://\S+", text, flags=re.IGNORECASE)
        return found.group(0).rstrip(").,]}>") if found else ""

    def _extract_browser_query(self, goal: str, *, kind: str) -> str:
        query = goal.strip()
        lowered = query.lower()
        replacements = [
            "on youtube",
            "in youtube",
            "from youtube",
            "on google",
            "in chrome",
            "in browser",
            "for me",
        ]
        for item in replacements:
            lowered = lowered.replace(item, " ")
        if kind == "media_playback":
            patterns = ["play ", "listen to ", "watch ", "open and play "]
        elif kind == "search_only":
            patterns = ["search for ", "search ", "look up ", "find "]
        else:
            patterns = ["open ", "go to ", "navigate to ", "visit "]
        candidate = lowered
        for prefix in patterns:
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix) :]
                break
        candidate = re.sub(r"\b(the|a|an|website|site|homepage|browser)\b", " ", candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip()
        return candidate or query

    @staticmethod
    def _criterion_matches(criterion: str, haystack: str) -> bool:
        normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in criterion)
        tokens = [token for token in normalized.split() if len(token) >= 4]
        if not tokens:
            return False
        if normalized.strip() and normalized.strip() in haystack:
            return True
        required = min(len(tokens), 2 if len(tokens) >= 2 else 1)
        return sum(1 for token in tokens if token in haystack) >= required

    def _platform_context(self) -> dict[str, str]:
        system = platform.system()
        if system == "Windows":
            rules = (
                "Use Windows-friendly commands only. Prefer native browser, system, mouse, keyboard, and window helpers "
                "before raw shell. Use powershell only when specialized tools are insufficient. Avoid Unix/macOS "
                "commands like 'which', 'open -a', and 'google-chrome'."
            )
        elif system == "Darwin":
            rules = "Use macOS-friendly commands like 'open -a' and AppleScript-aware flows."
        else:
            rules = "Use Linux-friendly commands like xdg-open and typical POSIX utilities."
        browser = self.tools.execute("browser", {"action": "status"})
        browser_path = ""
        if browser.ok and isinstance(browser.data, dict):
            browser_path = str(browser.data.get("chrome_path", "")).strip()
        return {
            "system": system,
            "shell": "subprocess(shell=True)",
            "rules": rules,
            "chrome_path": browser_path,
        }

    def _kill_switch_active(self) -> bool:
        from pathlib import Path

        return Path(self.kill_switch_path).exists()

    @staticmethod
    def _tool_allowed(tool_name: str, allowed_surfaces: list[str]) -> bool:
        if tool_name in {"read_file", "write_file", "search_files", "list_dir"}:
            return "files" in allowed_surfaces
        if tool_name == "browser":
            return "browser" in allowed_surfaces
        if tool_name == "system":
            return "system" in allowed_surfaces
        return tool_name in allowed_surfaces

    @staticmethod
    def _goal_requires_foreground_browser(goal: str, success_criteria: list[str]) -> bool:
        haystack = " ".join([goal, *success_criteria]).lower()
        return any(
            token in haystack
            for token in ["chrome", "browser", "search", "headline", "results", "news", "youtube", "play", "listen", "watch", "song", "video"]
        )

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


class OsAgentTool(Tool):
    name = "os_agent"
    description = (
        "Goal-oriented OS agent for multi-step desktop/browser workflows that need stateful execution, "
        "verification, retries, recovery, or proof of completion. Prefer this over direct browser/system "
        "tools when the user asks for a workflow to be completed and verified end-to-end."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "Goal the OS agent should accomplish."},
            "context": {"type": "string", "description": "Additional task context."},
            "budget_minutes": {"type": "integer", "description": "Execution budget in minutes. Default 20, max 30."},
            "success_criteria": {"type": "array", "items": {"type": "string"}, "description": "Optional explicit success criteria."},
            "cwd": {"type": "string", "description": "Optional working directory."},
            "allowed_surfaces": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Allowed OS surfaces. Default shell/files/window/keyboard/clipboard/mouse/system/screen/ocr.",
            },
        },
        "required": ["goal"],
        "additionalProperties": False,
    }

    def __init__(self, controller: OsController) -> None:
        self.controller = controller

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("budget_minutes", 20)
        args["budget_minutes"] = min(max(int(args.get("budget_minutes", 20)), 1), 30)
        args.setdefault("success_criteria", [])
        args.setdefault("allowed_surfaces", list(OsController.DEFAULT_ALLOWED_SURFACES))
        args.setdefault("context", "")
        args.setdefault("cwd", "")
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        return self.controller.run_goal(
            str(args["goal"]),
            context=str(args.get("context", "")),
            success_criteria=list(args.get("success_criteria", [])),
            budget_minutes=int(args.get("budget_minutes", 20)),
            allowed_surfaces=list(args.get("allowed_surfaces", list(OsController.DEFAULT_ALLOWED_SURFACES))),
            cwd=str(args.get("cwd", "")),
        )

    def render(self, data: dict[str, Any]) -> str:
        observations = data.get("observations", [])
        if not observations:
            return data.get("goal", "OS task complete.")
        return "\n".join(str(item) for item in observations[-6:])
