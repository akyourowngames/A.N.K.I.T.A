"""Specialist execution loop for orchestration."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm import LLMRuntime, call_chat_once
from llm.agent_router import detect_task_complexity, get_agent_runtime
from llm.client import build_vision_runtime_from_env, call_chat_with_image
from tools.engine import _estimate_tokens, compact_messages, execute_tool_call

from ..content_contract import extract_body, parse_content_payload, validate_content_payload
from ..specialists import SpecialistAgent
from .shared import (
    _CONTENT_PAYLOAD_STATS,
    _DEEP_MODE_MAX_TOKENS,
    _LAST_VISION_CACHE,
    _MAX_TOOL_STEPS,
    _ORCHESTRATOR_TOKEN_LIMIT,
    _VISION_CACHE_TTL_SEC,
    _VISION_FOLLOWUP_KEYWORDS,
    is_deep_mode_task,
    slugify_filename,
    validate_or_repair_content_payload,
)
from .vision import finalize_vision_packets, handle_vision_result


def _strip_image_blocks(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            clean.append(message)
            continue
        text_parts = [block for block in content if isinstance(block, dict) and block.get("type") != "image_url"]
        if not text_parts:
            continue
        if len(text_parts) == 1 and text_parts[0].get("type") == "text":
            clean.append({**message, "content": text_parts[0].get("text", ""), "_mime_type": None})
        else:
            clean.append({**message, "content": text_parts})
    return clean


def _build_messages(
    specialist: SpecialistAgent,
    task: str,
    conversation_history: Optional[List[Dict[str, Any]]],
    prior_context: Optional[str],
) -> List[Dict[str, Any]]:
    messages = specialist.make_messages(task, history=conversation_history)
    messages = _strip_image_blocks(messages)
    if prior_context and messages and messages[0]["role"] == "system":
        messages[0] = {"role": "system", "content": messages[0]["content"] + "\n\n" + prior_context}
    return messages


def _filter_tool_specs(specs: List[Dict[str, Any]], allowed_names: set[str]) -> List[Dict[str, Any]]:
    return [spec for spec in specs if str(spec.get("function", {}).get("name", "")).strip() in allowed_names]


def _get_runtime_for_specialist(specialist: SpecialistAgent, task: str, runtime: LLMRuntime) -> LLMRuntime:
    if specialist.name not in {"CodeAgent", "CodeWriterAgent"}:
        return runtime
    complexity = detect_task_complexity(task, agent_name=specialist.name)
    specialist_runtime = get_agent_runtime(specialist.name, runtime, complexity)
    if specialist_runtime.model != runtime.model:
        print(
            f"[ModelRouter] {specialist.name}: {complexity.upper()} task -> routing to {specialist_runtime.model}",
            flush=True,
        )
    return specialist_runtime


def _effective_tool_specs(specialist: SpecialistAgent, task: str) -> List[Dict[str, Any]]:
    if specialist.name == "TerminalAgent" and _task_needs_local_discovery(task):
        filtered = _filter_tool_specs(
            specialist.tool_specs,
            {
                "remember",
                "recall",
                "forget",
                "get_system_context",
                "fast_file_search",
                "list_files",
                "read_file",
                "search_text",
                "execute_shell",
                "run_command",
                "open_path",
                "launch_app",
            },
        )
        if filtered:
            return filtered
    if specialist.name == "SystemAgent" and _wants_open(task):
        filtered = _filter_tool_specs(
            specialist.tool_specs,
            {
                "remember",
                "recall",
                "forget",
                "system_control",
                "open_path",
                "launch_app",
                "read_file",
                "search_text",
                "execute_shell",
                "run_command",
                "get_system_context",
            },
        )
        if filtered:
            return filtered
    return specialist.tool_specs


def _extract_prior_file(prior_context: Optional[str]) -> str:
    if not prior_context:
        return ""
    for line in reversed(prior_context.splitlines()):
        if line.startswith("FILE: ") or line.startswith("FILE_PATH: "):
            path = line.split(":", 1)[1].strip()
            if path:
                return path
    return ""


def _extract_context_value(prior_context: Optional[str], prefix: str) -> str:
    if not prior_context:
        return ""
    for line in prior_context.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _extract_legacy_content(prior_context: Optional[str]) -> str:
    if not prior_context:
        return ""
    match = re.search(r"CONTENT:\s*(.*?)\s*:END_CONTENT", prior_context, re.DOTALL)
    return match.group(1).strip() if match else ""


def _requested_app_for_task(task: str) -> str:
    try:
        from tools.terminal_ops import APP_ALIASES
    except Exception:
        return ""
    task_lower = task.lower()
    for alias in sorted(APP_ALIASES.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", task_lower):
            values = APP_ALIASES.get(alias) or []
            return str(values[0]).strip() if values else alias
    return ""


def _prior_context_says_already_open(prior_context: Optional[str]) -> bool:
    text = (prior_context or "").lower()
    return bool(text) and (
        "opened_file:" in text
        or "launched_app:" in text
        or
        "opened it" in text
        or "opened in notepad" in text
        or "opened the file" in text
        or "launch_app" in text
        or "already open" in text
    )


def _wants_open(task: str) -> bool:
    task_lower = task.lower()
    wants_open = any(token in task_lower for token in (" open ", " open it", " open the", " show ", " view ", " launch "))
    if not wants_open and task_lower.startswith(("open ", "show ", "view ", "launch ")):
        wants_open = True
    return wants_open


def _has_explicit_local_path(task: str) -> bool:
    return bool(re.search(r"(?i)(?:[A-Z]:\\|/|\\)", str(task or "")))


def _task_needs_local_discovery(task: str) -> bool:
    text = str(task or "").strip().lower()
    if not text or _has_explicit_local_path(text):
        return False
    if re.search(r"\b(take|capture|generate|create|make)\b", text) and re.search(r"\b(screenshot|snapshot|image|photo|picture|selfie)\b", text):
        return False
    has_target = re.search(r"\b(file|folder|path|directory|report|document|pdf|txt|log|desktop|downloads|documents|project|repo|image|photo|picture)\b", text)
    has_action = re.search(r"\b(find|locate|where|search|look for|show|open|view|launch|list)\b", text)
    return bool(has_target and has_action)


def _task_prefers_workspace_scope(task: str) -> bool:
    text = str(task or "").lower()
    return any(token in text for token in ("this project", "project", "workspace", "repo", "repository", "codebase", "here"))


def _new_artifacts() -> Dict[str, List[str]]:
    return {
        "files": [],
        "urls": [],
        "handoffs": [],
        "opened_files": [],
        "launched_apps": [],
    }


def _try_open_prior_file(
    specialist: SpecialistAgent,
    task: str,
    workspace_root: Path,
    prior_context: Optional[str],
) -> Optional[Dict[str, Any]]:
    if specialist.name != "SystemAgent" or not _wants_open(task):
        return None
    prior_file = _extract_prior_file(prior_context)
    if not prior_file:
        return None
    if _prior_context_says_already_open(prior_context):
        prior_result = {
            "ok": True,
            "opened": False,
            "already_opened": True,
            "path": prior_file,
            "absolute_path": prior_file,
            "FILE_PATH": prior_file,
            "launcher": "prior-context",
        }
        return {
            "agent": specialist.name,
            "ok": True,
            "reply": _render_tool_completion(prior_result),
            "artifacts": {
                "files": [prior_file],
                "urls": [],
                "handoffs": [],
                "opened_files": [prior_file],
                "launched_apps": [],
            },
        }
    try:
        from tools.engine import _call as _engine_call

        open_result = _engine_call("open_path", {"path": prior_file}, workspace_root, agent_name=specialist.name)
        if bool(open_result.get("ok", False)):
            return {
                "agent": specialist.name,
                "ok": True,
                "reply": _render_tool_completion(open_result),
                "artifacts": {
                    "files": [prior_file],
                    "urls": [],
                    "handoffs": [],
                    "opened_files": [prior_file],
                    "launched_apps": [],
                },
            }
    except Exception as open_err:
        print(f"[SystemAgentOpenFallback] open_path failed: {open_err}", flush=True)
    return None


def _build_content_fallback_target(
    workspace_root: Path,
    task_type: str,
    title: str,
    fmt: str,
    save_to: str,
    filename_hint: str,
) -> Path:
    if filename_hint:
        file_name = filename_hint
    else:
        ext = ".md" if fmt == "markdown" or task_type in {"report", "article"} else ".txt"
        if task_type == "email":
            file_name = f"email_{slugify_filename(title, default='email')}.txt"
        elif task_type in {"poem", "script"}:
            file_name = f"{task_type}_{slugify_filename(title, default=task_type)}.txt"
        else:
            file_name = f"{slugify_filename(title, default=task_type or 'content_output')}{ext}"
    target_dir = Path(save_to).expanduser() if save_to else (Path.home() / "Desktop")
    if not target_dir.is_absolute():
        target_dir = (workspace_root / target_dir).resolve()
    return target_dir / file_name


def _handle_file_agent_local_fallback(
    specialist: SpecialistAgent,
    task: str,
    workspace_root: Path,
    prior_context: Optional[str],
) -> Optional[Dict[str, Any]]:
    if specialist.name != "FileAgent" or not prior_context:
        return None
    payload = parse_content_payload(prior_context)
    payload_ok, _ = validate_content_payload(payload)
    if payload_ok and payload is not None:
        body = extract_body(payload)
        task_type = str(payload.get("task_type", "other")).strip().lower() or "other"
        title = str(payload.get("title", "untitled")).strip() or "untitled"
        fmt = str(payload.get("format", "plain_text")).strip().lower() or "plain_text"
    else:
        body = _extract_legacy_content(prior_context)
        if not body:
            return None
        task_type = _extract_context_value(prior_context, "TASK_TYPE:").strip().lower() or "other"
        title = _extract_context_value(prior_context, "TITLE:").strip() or "untitled"
        fmt = _extract_context_value(prior_context, "FORMAT:").strip().lower() or "plain_text"

    save_to = _extract_context_value(prior_context, "SAVE_TO:")
    filename_hint = _extract_context_value(prior_context, "FILENAME_HINT:")
    target_path = _build_content_fallback_target(workspace_root, task_type, title, fmt, save_to, filename_hint)

    try:
        from tools.engine import _call as _engine_call

        write_result = _engine_call(
            "write_file",
            {"path": str(target_path), "content": body, "overwrite": True},
            workspace_root,
            agent_name=specialist.name,
        )
        absolute_path = str(
            write_result.get("FILE_PATH")
            or write_result.get("absolute_path")
            or write_result.get("path")
            or target_path
        ).strip()
        artifacts = _new_artifacts()
        artifacts["files"].append(absolute_path)
        reply_parts = [_render_tool_completion(write_result)]

        if _wants_open(task):
            requested_app = _requested_app_for_task(task)
            if requested_app:
                try:
                    open_result = _engine_call(
                        "launch_app",
                        {"app": requested_app, "args": [absolute_path]},
                        workspace_root,
                        agent_name=specialist.name,
                    )
                    if bool(open_result.get("ok", False)):
                        reply_parts.append(_render_tool_completion(open_result))
                        artifacts["launched_apps"].append(requested_app)
                        artifacts["opened_files"].append(absolute_path)
                    else:
                        artifacts["handoffs"].append(f"HANDOFF: SystemAgent → open {absolute_path}")
                except Exception:
                    artifacts["handoffs"].append(f"HANDOFF: SystemAgent → open {absolute_path}")
            else:
                artifacts["handoffs"].append(f"HANDOFF: SystemAgent → open {absolute_path}")

        reply_text = "\n".join(part for part in reply_parts if part).strip()
        if artifacts["handoffs"]:
            reply_text = "\n".join(
                part for part in [reply_text, *artifacts["handoffs"]] if part
            ).strip()
        return {
            "agent": specialist.name,
            "ok": True,
            "reply": reply_text,
            "artifacts": artifacts,
        }
    except Exception as fallback_err:
        print(f"[FileAgentFallback] Local save fallback failed: {fallback_err}", flush=True)
        return None


def _tool_signature(tool_call: Dict[str, Any]) -> str:
    fn = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    name = str(fn.get("name", "")).strip()
    raw_args = fn.get("arguments", "{}")
    try:
        parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
    except Exception:
        parsed_args = raw_args
    if isinstance(parsed_args, dict):
        rendered_args = json.dumps(parsed_args, ensure_ascii=False, sort_keys=True)
    else:
        rendered_args = str(parsed_args)
    return f"{name}:{rendered_args}"


def _align_tool_call_with_artifacts(
    tool_call: Dict[str, Any],
    tool_artifacts: Dict[str, List[str]],
) -> Dict[str, Any]:
    fn = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    tool_name = str(fn.get("name", "")).strip()
    raw_args = fn.get("arguments", "{}")
    try:
        parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
    except Exception:
        return tool_call
    if not isinstance(parsed_args, dict):
        return tool_call
    last_artifact = next(
        (
            path_text
            for path_text in reversed(tool_artifacts.get("files", []))
            if path_text and Path(path_text).exists()
        ),
        "",
    )
    if not last_artifact:
        return tool_call

    changed = False
    if tool_name == "open_path":
        requested_path = str(parsed_args.get("path", "")).strip()
        if requested_path and requested_path != last_artifact and not Path(requested_path).exists():
            parsed_args["path"] = last_artifact
            changed = True
    elif tool_name == "launch_app":
        launch_args = parsed_args.get("args")
        if isinstance(launch_args, list) and launch_args:
            first_arg = str(launch_args[0]).strip()
            if (
                first_arg
                and first_arg != last_artifact
                and "://" not in first_arg
                and (("\\" in first_arg) or ("/" in first_arg) or Path(first_arg).suffix)
                and not Path(first_arg).exists()
            ):
                parsed_args["args"] = [last_artifact, *launch_args[1:]]
                changed = True
    if not changed:
        return tool_call

    patched_fn = dict(fn)
    patched_fn["arguments"] = json.dumps(parsed_args, ensure_ascii=False)
    patched_call = dict(tool_call)
    patched_call["function"] = patched_fn
    return patched_call


def _tool_call_succeeded(result: Any) -> bool:
    if not isinstance(result, dict):
        return True
    if result.get("ok") is False:
        return False
    inner = result.get("result")
    if isinstance(inner, dict):
        if inner.get("ok") is False:
            return False
        status = str(inner.get("status", "")).strip().lower()
        if status in {"error", "failed", "failure"}:
            return False
    return True


def _tool_artifact_path(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    inner = result.get("result") if isinstance(result.get("result"), dict) else {}
    return str(
        inner.get("FILE_PATH")
        or inner.get("absolute_path")
        or inner.get("path")
        or result.get("FILE_PATH")
        or result.get("absolute_path")
        or result.get("path")
        or ""
    ).strip()


def _tool_call_requested_local_target(tool_call: Dict[str, Any]) -> str:
    fn = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    tool_name = str(fn.get("name", "")).strip()
    raw_args = fn.get("arguments", "{}")
    try:
        parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
    except Exception:
        return ""
    if not isinstance(parsed_args, dict):
        return ""
    if tool_name == "open_path":
        return str(parsed_args.get("path", "")).strip()
    if tool_name == "launch_app":
        launch_args = parsed_args.get("args")
        if isinstance(launch_args, list) and launch_args:
            candidate = str(launch_args[0]).strip()
            if "://" not in candidate and (("\\" in candidate) or ("/" in candidate) or Path(candidate).suffix):
                return candidate
    return ""


def _should_block_unverified_open_guess(
    task: str,
    tool_call: Dict[str, Any],
    tool_artifacts: Dict[str, List[str]],
) -> bool:
    fn = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    tool_name = str(fn.get("name", "")).strip()
    if tool_name not in {"open_path", "launch_app"}:
        return False
    if _has_verified_local_artifact(tool_artifacts):
        return False
    if not _task_needs_local_discovery(task):
        return False
    requested_target = _tool_call_requested_local_target(tool_call)
    if not requested_target:
        return False
    try:
        return not Path(requested_target).expanduser().exists()
    except Exception:
        return True


def _discovery_search_roots(task: str, workspace_root: Path) -> List[Path]:
    task_lower = str(task or "").lower()
    roots: List[Path] = []
    if any(token in task_lower for token in ("project", "workspace", "repo", "repository", "codebase", "here")):
        roots.append(workspace_root)
    else:
        roots.append(workspace_root)
        try:
            roots.append(Path.home())
        except Exception:
            pass
    unique: List[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _guess_local_target_name(task: str, requested_target: str) -> str:
    candidate = str(requested_target or "").strip().strip("\"'")
    if candidate:
        try:
            name = Path(candidate).name.strip()
        except Exception:
            name = candidate
        if name:
            return name
    match = re.search(r"\b[\w.\-]+\.[A-Za-z0-9]{1,8}\b", str(task or ""))
    if match:
        return match.group(0).strip()
    return ""


def _recover_unverified_local_target(
    specialist: SpecialistAgent,
    task: str,
    workspace_root: Path,
    tool_artifacts: Dict[str, List[str]],
    requested_target: str,
) -> Optional[Dict[str, Any]]:
    target_name = _guess_local_target_name(task, requested_target)
    if not target_name:
        return None
    try:
        from tools.engine import _call as _engine_call
    except Exception:
        return None

    escaped_pattern = re.escape(target_name)
    suffix = Path(target_name).suffix
    for search_root in _discovery_search_roots(task, workspace_root):
        search_result = _engine_call(
            "fast_file_search",
            {
                "pattern": escaped_pattern,
                "path": str(search_root),
                "glob": f"*{suffix}" if suffix else None,
                "max_results": 20,
            },
            workspace_root,
            agent_name=specialist.name,
        )
        inner = search_result.get("result", {}) if isinstance(search_result, dict) else {}
        candidates = inner.get("results", []) if isinstance(inner, dict) else []
        if not isinstance(candidates, list) or not candidates:
            continue
        found_path = next(
            (
                str(path_text).strip()
                for path_text in candidates
                if str(path_text).strip() and Path(str(path_text)).name.lower() == target_name.lower()
            ),
            str(candidates[0]).strip(),
        )
        if not found_path:
            continue
        if found_path not in tool_artifacts["files"]:
            tool_artifacts["files"].append(found_path)
        if not _wants_open(task):
            return {
                "agent": specialist.name,
                "ok": True,
                "reply": f"FILE_PATH: {found_path}",
                "artifacts": tool_artifacts,
            }
        open_result = _engine_call(
            "open_path",
            {"path": found_path},
            workspace_root,
            agent_name=specialist.name,
        )
        if bool(open_result.get("ok", False)):
            _record_tool_artifacts(tool_artifacts, open_result)
            return {
                "agent": specialist.name,
                "ok": True,
                "reply": "\n".join(
                    part
                    for part in (
                        f"FILE_PATH: {found_path}",
                        _render_tool_completion(open_result),
                    )
                    if part
                ).strip(),
                "artifacts": tool_artifacts,
            }
    return None


def _record_tool_artifacts(tool_artifacts: Dict[str, List[str]], tool_result: Any) -> None:
    artifact_path = _tool_artifact_path(tool_result)
    if artifact_path and artifact_path not in tool_artifacts["files"]:
        tool_artifacts["files"].append(artifact_path)
    if not isinstance(tool_result, dict):
        return
    tool_name = str(tool_result.get("tool", "")).strip().lower()
    inner = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else {}
    if tool_name == "open_path" and artifact_path and artifact_path not in tool_artifacts["opened_files"]:
        tool_artifacts["opened_files"].append(artifact_path)
    if tool_name == "launch_app":
        app_name = str(inner.get("requested") or inner.get("app") or tool_result.get("requested") or tool_result.get("app") or "").strip()
        if app_name and app_name not in tool_artifacts["launched_apps"]:
            tool_artifacts["launched_apps"].append(app_name)
        if artifact_path and artifact_path not in tool_artifacts["opened_files"]:
            tool_artifacts["opened_files"].append(artifact_path)


def _reply_looks_like_failure(reply: str) -> bool:
    text = str(reply or "").strip().lower()
    if not text:
        return True
    failure_markers = (
        "[failed]",
        "[error]",
        "failed",
        "error",
        "didn't work",
        "did not work",
        "unable",
        "can't",
        "cannot",
        "couldn't",
        "could not",
        "not found",
        "server error",
        "timed out",
        "max steps reached",
    )
    return any(marker in text for marker in failure_markers)


def _reply_claims_objective_success(reply: str) -> bool:
    text = f" {str(reply or '').strip().lower()} "
    if not text.strip():
        return False
    success_markers = (
        " opened ",
        " opened.",
        " opened it",
        " launched ",
        " launched.",
        " saved ",
        " saved.",
        " written ",
        " wrote ",
        " generated ",
        " generated.",
        " created ",
        " created.",
        " downloaded ",
        " found ",
        " found.",
        " took a screenshot",
        " done -",
    )
    return any(marker in text for marker in success_markers)


def _has_verified_local_artifact(tool_artifacts: Dict[str, List[str]]) -> bool:
    if tool_artifacts.get("opened_files") or tool_artifacts.get("launched_apps"):
        return True
    for path_text in tool_artifacts.get("files", []):
        try:
            if path_text and Path(path_text).exists():
                return True
        except Exception:
            continue
    return False


def _should_force_tool_grounding_retry(
    specialist: SpecialistAgent,
    task: str,
    reply: str,
    tool_state: Dict[str, Any],
    tool_artifacts: Dict[str, List[str]],
) -> bool:
    if specialist.name not in {"SystemAgent", "TerminalAgent", "FileAgent", "ImageAgent"}:
        return False
    if int(tool_state.get("executed_count", 0)) > 0:
        return False
    if _has_verified_local_artifact(tool_artifacts):
        return False
    task_lower = str(task or "").lower()
    if _wants_open(task):
        return True
    if _reply_claims_objective_success(reply):
        return True
    return any(
        token in task_lower
        for token in ("find ", "locate ", "where ", "search ", "list ", "show ", "view ", "file", "folder", "path")
    )


def _render_tool_completion(tool_result: Any, extra_handoffs: Optional[List[str]] = None) -> str:
    if tool_result is None:
        return ""
    render_target = tool_result.get("result") if isinstance(tool_result, dict) and isinstance(tool_result.get("result"), dict) else tool_result
    try:
        from tools.engine import _format_result as _engine_format_result

        rendered = _engine_format_result(render_target).strip()
    except Exception:
        rendered = json.dumps(render_target, ensure_ascii=False, indent=2) if isinstance(render_target, dict) else str(render_target)

    lines = [rendered] if rendered else []
    artifact_path = _tool_artifact_path(tool_result)
    if artifact_path and "FILE_PATH:" not in rendered and artifact_path not in rendered:
        lines.append(f"FILE_PATH: {artifact_path}")
    for handoff in extra_handoffs or []:
        handoff_text = str(handoff or "").strip()
        if handoff_text and handoff_text not in lines:
            lines.append(handoff_text)
    return "\n".join(lines).strip()


def _recover_from_successful_tool_after_error(
    specialist: SpecialistAgent,
    task: str,
    workspace_root: Path,
    tool_state: Dict[str, Any],
    tool_artifacts: Dict[str, List[str]],
) -> Optional[Dict[str, Any]]:
    last_result = tool_state.get("last_result")
    if int(tool_state.get("executed_count", 0)) <= 0 or not _tool_call_succeeded(last_result):
        return None
    if not isinstance(last_result, dict):
        return None
    tool_name = str(last_result.get("tool", "")).strip()
    artifact_path = _tool_artifact_path(last_result)
    _record_tool_artifacts(tool_artifacts, last_result)

    if artifact_path and _wants_open(task) and tool_name not in {"open_path", "launch_app"}:
        try:
            from tools.engine import _call as _engine_call

            requested_app = _requested_app_for_task(task)
            if requested_app:
                open_result = _engine_call(
                    "launch_app",
                    {"app": requested_app, "args": [artifact_path]},
                    workspace_root,
                    agent_name=specialist.name,
                )
            else:
                open_result = _engine_call(
                    "open_path",
                    {"path": artifact_path},
                    workspace_root,
                    agent_name=specialist.name,
                )
            if bool(open_result.get("ok", False)):
                _record_tool_artifacts(tool_artifacts, open_result)
                return {
                    "agent": specialist.name,
                    "ok": True,
                    "reply": "\n".join(
                        part
                        for part in (
                            _render_tool_completion(last_result),
                            _render_tool_completion(open_result),
                        )
                        if part
                    ).strip(),
                    "artifacts": tool_artifacts,
                }
        except Exception as recovery_err:
            print(f"[{specialist.name}Recovery] Tool-success completion fallback failed: {recovery_err}", flush=True)

    return {
        "agent": specialist.name,
        "ok": True,
        "reply": _render_tool_completion(last_result),
        "artifacts": tool_artifacts,
    }


def _handle_non_payload_error(
    specialist: SpecialistAgent,
    task: str,
    workspace_root: Path,
    prior_context: Optional[str],
    err: Exception,
    tool_artifacts: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    opened = _try_open_prior_file(specialist, task, workspace_root, prior_context)
    if opened:
        return opened
    if specialist.name == "SystemAgent":
        system_fallback = _handle_system_agent_local_fallback(
            specialist,
            task,
            workspace_root,
            prior_context,
            tool_artifacts or _new_artifacts(),
        )
        if system_fallback:
            return system_fallback
    file_fallback = _handle_file_agent_local_fallback(specialist, task, workspace_root, prior_context)
    if file_fallback:
        return file_fallback
    return {"agent": specialist.name, "ok": False, "reply": f"[Error] {err}"}


def _handle_payload_overflow(
    specialist: SpecialistAgent,
    messages: List[Dict[str, Any]],
    specialist_runtime: LLMRuntime,
    overflow_attempts: int,
) -> tuple[List[Dict[str, Any]], bool]:
    print(
        f"[CascadeRecovery/{specialist.name}] Overflow attempt {overflow_attempts}/3",
        flush=True,
    )
    if overflow_attempts == 1:
        truncated_any = False
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "tool":
                content = messages[index].get("content", "")
                if isinstance(content, str) and len(content) > 500:
                    messages[index] = {**messages[index], "content": content[:500] + "\n[TRUNCATED — result too large]"}
                    truncated_any = True
        if truncated_any:
            print(f"[CascadeRecovery/{specialist.name}] Tier 2: Truncated tool messages", flush=True)
            return messages, True
    if overflow_attempts == 2:
        print(f"[CascadeRecovery/{specialist.name}] Tier 3: LLM summarization applied", flush=True)
        return compact_messages(messages, runtime=specialist_runtime), True
    return messages, False


def _apply_emergency_compact(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    system_message = messages[0] if messages and messages[0].get("role") == "system" else None
    tail = messages[-6:]
    compacted = ([system_message] if system_message else []) + [
        {"role": "system", "content": "[EMERGENCY] Context overflow recovery — older context dropped."}
    ]
    compacted.extend(tail)
    return compacted


def _maybe_inject_vision_followup(messages: List[Dict[str, Any]], task: str, specialist_runtime: LLMRuntime) -> None:
    cache_fresh = _LAST_VISION_CACHE and (time.time() - _LAST_VISION_CACHE.get("ts", 0)) < _VISION_CACHE_TTL_SEC
    is_followup = any(keyword in task.lower() for keyword in _VISION_FOLLOWUP_KEYWORDS)
    if not (cache_fresh and is_followup):
        return
    cached_b64 = _LAST_VISION_CACHE["b64"]
    cached_mime = _LAST_VISION_CACHE["mime"]
    print(
        f"[VisionCache] Using cached image ({cached_mime}) for follow-up via call_chat_with_image: '{task[:60]}'",
        flush=True,
    )
    try:
        vision_runtime = build_vision_runtime_from_env(specialist_runtime)
        cache_desc = call_chat_with_image(
            vision_runtime,
            f"The user asks: {task}\nDescribe what you see in this image, focusing on the user's question.",
            cached_b64,
            max_tokens=600,
            temperature=0.3,
            mime_type=cached_mime,
        )
        messages.extend(
            [
                {"role": "assistant", "content": "Looking at the image from earlier..."},
                {"role": "user", "content": f"[Vision Analysis — cached image]\n{cache_desc}"},
            ]
        )
        print(f"[VisionCache] Follow-up description ready ({len(cache_desc)} chars)", flush=True)
    except Exception as vision_err:
        print(f"[VisionCache] call_chat_with_image failed: {vision_err}", flush=True)
        messages.append({"role": "user", "content": f"[Vision follow-up failed: {vision_err}]"})


def _handle_system_agent_local_fallback(
    specialist: SpecialistAgent,
    task: str,
    workspace_root: Path,
    prior_context: Optional[str],
    tool_artifacts: Dict[str, List[str]],
) -> Optional[Dict[str, Any]]:
    if specialist.name != "SystemAgent":
        return None
    opened = _try_open_prior_file(specialist, task, workspace_root, prior_context)
    if opened:
        return opened
    try:
        from tools.engine import _call as _engine_call, _parse_local_intent

        parsed_intent = _parse_local_intent(task, workspace_root)
        if not parsed_intent:
            return None
        tool_name, tool_args = parsed_intent
        if str(tool_name).startswith("__"):
            return None
        fallback_result = _engine_call(tool_name, tool_args, workspace_root, agent_name=specialist.name)
        fallback_reply = _render_tool_completion(fallback_result)
        fallback_ok = bool(fallback_result.get("ok", True))
        artifact_path = _tool_artifact_path(fallback_result)
        _record_tool_artifacts(tool_artifacts, fallback_result)
        if fallback_ok and artifact_path and _wants_open(task):
            try:
                open_result = _engine_call("open_path", {"path": artifact_path}, workspace_root, agent_name=specialist.name)
                if bool(open_result.get("ok", False)):
                    _record_tool_artifacts(tool_artifacts, open_result)
                    fallback_reply = "\n".join(
                        part
                        for part in (fallback_reply, _render_tool_completion(open_result))
                        if part
                    ).strip()
            except Exception as fallback_err:
                print(f"[SystemAgentFallback] open_path after local fallback failed: {fallback_err}", flush=True)
        return {
            "agent": specialist.name,
            "ok": fallback_ok,
            "reply": fallback_reply,
            "artifacts": tool_artifacts,
        }
    except Exception as fallback_err:
        print(f"[SystemAgentFallback] Local tool fallback failed: {fallback_err}", flush=True)
        return None


def _process_tool_calls(
    specialist: SpecialistAgent,
    task: str,
    runtime: LLMRuntime,
    specialist_runtime: LLMRuntime,
    workspace_root: Path,
    tool_calls: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    tool_artifacts: Dict[str, List[str]],
    tool_replay_guard: Dict[str, Dict[str, Any]],
    tool_state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    vision_packets: List[Dict[str, Any]] = []
    for tool_call in tool_calls:
        tool_call = _align_tool_call_with_artifacts(tool_call, tool_artifacts)
        signature = _tool_signature(tool_call)
        prior = tool_replay_guard.get(signature)
        if prior is not None:
            content_str = json.dumps(
                {
                    "ok": prior.get("success", False),
                    "suppressed": True,
                    "reason": (
                        "Exact same tool call was already executed earlier in this agent run. "
                        "Use the prior result instead of repeating it."
                    ),
                    "prior_result": prior.get("result"),
                },
                ensure_ascii=False,
            )
            messages.append({"role": "tool", "tool_call_id": tool_call.get("id", ""), "content": content_str})
            continue
        if _should_block_unverified_open_guess(task, tool_call, tool_artifacts):
            guessed_target = _tool_call_requested_local_target(tool_call)
            recovered = _recover_unverified_local_target(
                specialist,
                task,
                workspace_root,
                tool_artifacts,
                guessed_target,
            )
            if recovered:
                return recovered
            blocked_result = {
                "ok": False,
                "suppressed": True,
                "reason": (
                    "Open/launch was blocked because the requested local target is not verified yet. "
                    "Discover the real existing path first with fast_file_search, list_files, search_text, or execute_shell, then open that path."
                ),
                "requested_path": guessed_target,
            }
            tool_replay_guard[signature] = {"success": False, "result": blocked_result}
            messages.append({"role": "tool", "tool_call_id": tool_call.get("id", ""), "content": json.dumps(blocked_result, ensure_ascii=False)})
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "The prior open/launch attempt used an unverified local path. "
                        "Do not guess. Discover the real path first, then open it."
                    ),
                }
            )
            continue
        try:
            execute_tool_call._runtime = runtime  # type: ignore[attr-defined]
            result = execute_tool_call(tool_call, workspace_root=workspace_root, agent_name=specialist.name)
            tool_replay_guard[signature] = {"success": _tool_call_succeeded(result), "result": result}
            tool_state["executed_count"] = int(tool_state.get("executed_count", 0)) + 1
            tool_state["last_result"] = result
            _record_tool_artifacts(tool_artifacts, result)
            inner = result.get("result", {}) if isinstance(result, dict) else {}
            if isinstance(inner, dict) and inner.get("status") == "truncated" and isinstance(inner.get("data"), str):
                try:
                    inner = json.loads(inner["data"])
                except Exception:
                    pass
            b64_source = None
            if isinstance(result, dict) and "base64" in result:
                b64_source = result
            elif isinstance(inner, dict) and "base64" in inner:
                b64_source = inner
            if b64_source is not None:
                content_str = handle_vision_result(tool_call, result, inner, b64_source, vision_packets)
            else:
                content_str = json.dumps(result, ensure_ascii=False)
        except Exception as err:
            content_str = json.dumps({"ok": False, "error": str(err)})
        messages.append({"role": "tool", "tool_call_id": tool_call.get("id", ""), "content": content_str})
    if not vision_packets:
        return None
    return finalize_vision_packets(specialist_runtime, specialist.name, vision_packets)


def run_specialist(
    specialist: SpecialistAgent,
    task: str,
    runtime: LLMRuntime,
    workspace_root: Path,
    prior_context: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    specialist_runtime = _get_runtime_for_specialist(specialist, task, runtime)
    active_tool_specs = _effective_tool_specs(specialist, task)
    messages = _build_messages(specialist, task, conversation_history, prior_context)
    if specialist.name == "TerminalAgent" and _task_needs_local_discovery(task) and _task_prefers_workspace_scope(task):
        scope_note = (
            "WORKSPACE DISCOVERY SCOPE:\n"
            f"Search inside this workspace first: {workspace_root}\n"
            "If the user said 'this project', 'workspace', 'repo', or 'here', do not search Downloads, Desktop, or the whole PC unless the workspace search fails."
        )
        if messages and messages[0].get("role") == "system":
            messages[0] = {"role": "system", "content": str(messages[0].get("content", "")) + "\n\n" + scope_note}
    max_tokens = _DEEP_MODE_MAX_TOKENS if specialist.name == "ContentAgent" and is_deep_mode_task(task, prior_context) else specialist_runtime.max_tokens
    if max_tokens == _DEEP_MODE_MAX_TOKENS:
        print(f"[Orchestrator] ContentAgent DEEP MODE - max_tokens boosted to {max_tokens}", flush=True)
    _maybe_inject_vision_followup(messages, task, specialist_runtime)
    opened = _try_open_prior_file(specialist, task, workspace_root, prior_context)
    if opened:
        return opened

    overflow_attempts = 0
    forced_tool_retry = False
    tool_artifacts: Dict[str, List[str]] = _new_artifacts()
    tool_replay_guard: Dict[str, Dict[str, Any]] = {}
    tool_state: Dict[str, Any] = {"executed_count": 0, "last_result": None}
    for _ in range(_MAX_TOOL_STEPS):
        estimated = _estimate_tokens(messages)
        if estimated > _ORCHESTRATOR_TOKEN_LIMIT:
            print(f"[TokenGuardian/{specialist.name}] [WARN]  ~{estimated:,} tokens - compacting...", flush=True)
            messages = compact_messages(messages, runtime=specialist_runtime)
            print(f"[TokenGuardian/{specialist.name}] [OK] Compacted to ~{_estimate_tokens(messages):,} tokens.", flush=True)
        try:
            response = call_chat_once(specialist_runtime, messages, tools=active_tool_specs, max_tokens=max_tokens)
            overflow_attempts = 0
        except Exception as err:
            err_str = str(err).lower()
            is_payload_err = any(token in err_str for token in ("400", "context_length_exceeded", "bad request", "too large", "request too large", "maximum context"))
            if not is_payload_err:
                recovered = _recover_from_successful_tool_after_error(
                    specialist,
                    task,
                    workspace_root,
                    tool_state,
                    tool_artifacts,
                )
                if recovered:
                    return recovered
                return _handle_non_payload_error(
                    specialist,
                    task,
                    workspace_root,
                    prior_context,
                    err,
                    tool_artifacts=tool_artifacts,
                )
            overflow_attempts += 1
            messages, should_retry = _handle_payload_overflow(specialist, messages, specialist_runtime, overflow_attempts)
            if should_retry:
                continue
            if overflow_attempts >= 3:
                print(f"[CascadeRecovery/{specialist.name}] Tier 4: Emergency compact", flush=True)
                messages = _apply_emergency_compact(messages)
                try:
                    response = call_chat_once(specialist_runtime, messages, tools=active_tool_specs, max_tokens=max_tokens)
                except Exception:
                    return {
                        "agent": specialist.name,
                        "ok": False,
                        "reply": "[WARN] Context overflow after 3 recovery attempts. Please try a more specific request.",
                    }
            else:
                continue

        tool_calls = response.get("tool_calls") or []
        messages.append({"role": "assistant", "content": response.get("content") or "", **({"tool_calls": tool_calls} if tool_calls else {})})
        if not tool_calls:
            reply = (response.get("content") or "").strip()
            last_result = tool_state.get("last_result")
            if _should_force_tool_grounding_retry(specialist, task, reply, tool_state, tool_artifacts) and not forced_tool_retry:
                forced_tool_retry = True
                messages.extend(
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are handling a real local action or discovery request. "
                                "You MUST inspect or act with tools before giving a completion message. "
                                "Do not claim found/opened/saved/generated/launched unless the tool receipt proves it."
                            ),
                        },
                        {"role": "user", "content": f"Retry this same request now by using the appropriate tools first: {task}"},
                    ]
                )
                continue
            if int(tool_state.get("executed_count", 0)) > 0 and _tool_call_succeeded(last_result):
                if (
                    not reply
                    or reply.startswith("{")
                    or reply.startswith("[")
                    or _reply_looks_like_failure(reply)
                    or (
                        specialist.name in {"SystemAgent", "TerminalAgent", "FileAgent", "ImageAgent"}
                        and _reply_claims_objective_success(reply)
                        and not _has_verified_local_artifact(tool_artifacts)
                    )
                ):
                    reply = _render_tool_completion(last_result)
            if specialist.name == "SystemAgent":
                if int(tool_state.get("executed_count", 0)) == 0 and not forced_tool_retry:
                    forced_tool_retry = True
                    messages.extend(
                        [
                            {
                                "role": "system",
                                "content": (
                                    "You are handling a real system action request. "
                                    "You MUST call an appropriate tool before replying. "
                                    "Do not answer with catchphrases, status lines, or prose until a tool has executed."
                                ),
                            },
                            {"role": "user", "content": f"Retry this same request now by calling a tool: {task}"},
                        ]
                    )
                    continue
                if int(tool_state.get("executed_count", 0)) == 0:
                    fallback = _handle_system_agent_local_fallback(specialist, task, workspace_root, prior_context, tool_artifacts)
                    if fallback:
                        return fallback
                if (
                    not reply
                    or reply.startswith("{")
                    or reply.startswith("[")
                    or (isinstance(last_result, dict) and not _tool_call_succeeded(last_result))
                ):
                    reply = _render_tool_completion(last_result)
            if specialist.name == "ContentAgent":
                _CONTENT_PAYLOAD_STATS["total"] += 1
                checked = validate_or_repair_content_payload(specialist_runtime, messages, reply, max_tokens)
                if checked["content_payload_valid"] and checked["content_payload_repaired"]:
                    _CONTENT_PAYLOAD_STATS["schema_repaired"] += 1
                elif checked["content_payload_valid"]:
                    _CONTENT_PAYLOAD_STATS["schema_valid_first_pass"] += 1
                else:
                    _CONTENT_PAYLOAD_STATS["schema_fallback_legacy"] += 1
                print(
                    "[ContentPayload] total={total} first_pass={schema_valid_first_pass} repaired={schema_repaired} fallback={schema_fallback_legacy}".format(
                        **_CONTENT_PAYLOAD_STATS
                    ),
                    flush=True,
                )
                return {
                    "agent": specialist.name,
                    "ok": True,
                    "reply": checked["reply"],
                    "artifacts": tool_artifacts,
                    "content_payload_valid": checked["content_payload_valid"],
                    "content_payload_errors": checked["content_payload_errors"],
                    "content_payload_repaired": checked["content_payload_repaired"],
                }
            return {"agent": specialist.name, "ok": True, "reply": reply, "artifacts": tool_artifacts}
        vision_result = _process_tool_calls(
            specialist,
            task,
            runtime,
            specialist_runtime,
            workspace_root,
            tool_calls,
            messages,
            tool_artifacts,
            tool_replay_guard,
            tool_state,
        )
        if vision_result:
            return vision_result
    last_result = tool_state.get("last_result")
    if int(tool_state.get("executed_count", 0)) > 0 and _tool_call_succeeded(last_result):
        return {
            "agent": specialist.name,
            "ok": True,
            "reply": _render_tool_completion(last_result),
            "artifacts": tool_artifacts,
        }
    return {"agent": specialist.name, "ok": True, "reply": "Task completed (max steps reached).", "artifacts": tool_artifacts}


def _run_specialist(
    specialist: SpecialistAgent,
    task: str,
    runtime: LLMRuntime,
    workspace_root: Path,
    prior_context: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return run_specialist(
        specialist,
        task,
        runtime,
        workspace_root,
        prior_context=prior_context,
        conversation_history=conversation_history,
    )
