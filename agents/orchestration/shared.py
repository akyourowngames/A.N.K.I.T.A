"""Shared orchestration helpers and constants."""

from __future__ import annotations

import ctypes
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm import LLMRuntime, call_chat_once

from ..content_contract import extract_body, parse_content_payload, validate_content_payload

_ORCHESTRATOR_TOKEN_LIMIT = 48_000
_MAX_TOOL_STEPS = 20
_MAX_HANDOFF_STEPS = 6

_CONTENT_PAYLOAD_STATS: Dict[str, int] = {
    "total": 0,
    "schema_valid_first_pass": 0,
    "schema_repaired": 0,
    "schema_fallback_legacy": 0,
}

_LAST_VISION_CACHE: Dict[str, Any] = {}
_VISION_CACHE_TTL_SEC = 60

_VISION_FOLLOWUP_KEYWORDS = {
    "describe",
    "what do you see",
    "tell me",
    "what's in",
    "what is in",
    "analyse",
    "analyze",
    "look at",
    "what did you",
    "explain what",
    "describe it",
    "describe the",
    "what are",
    "can you see",
    "do you see",
    "what's there",
    "what is there",
    "read it",
    "read the",
    "what text",
    "any text",
    "what does it show",
    "what does it say",
}


def _known_folder(csidl: int, fallback: str) -> str:
    if os.name != "nt":
        return fallback
    try:
        buf = ctypes.create_unicode_buffer(260)
        result = ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
        if result == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return fallback

_VISION_TOOL_NAMES = {"capture_webcam", "read_screen_context", "visual_click"}

_ESCALATION_MATRIX: Dict[str, tuple[str, str]] = {
    "SystemAgent": (
        "TerminalAgent",
        "SystemAgent tried and FAILED. Use raw PowerShell/CMD via execute_shell to achieve the same goal. "
        "Do NOT repeat what SystemAgent did. Use terminal commands directly.",
    ),
    "WebAgent": (
        "GeneralAgent",
        "WebAgent tried and FAILED (search API down or blocked). "
        "Use your internal LLM knowledge to answer as accurately as possible. "
        "State clearly that you are using knowledge cutoff data, not live web results.",
    ),
    "FileAgent": (
        "TerminalAgent",
        "FileAgent tried and FAILED (likely permission error). "
        "Use execute_shell to force-write the file via PowerShell: "
        "New-Item -Path '<path>' -ItemType File -Force; Set-Content -Path '<path>' -Value '<content>'",
    ),
    "ContentAgent": (
        "GeneralAgent",
        "ContentAgent timed out or failed. Write a shorter, concise version of the requested content. "
        "Quality matters more than length here — produce something complete and usable. "
        "IMPORTANT: After writing, call write_file to save it to Desktop as a .md file. "
        "Use a sensible filename based on the topic. "
        "Then call launch_app to open it. "
        "Do NOT just return text — save it.",
    ),
    "CodeAgent": (
        "CodeAgent",
        "Your previous attempt had an error. Re-read the error message carefully, "
        "identify the root cause, and retry with a corrected approach. "
        "Do NOT repeat the same mistake.",
    ),
    "MusicAgent": (
        "TerminalAgent",
        "MusicAgent failed. Try launching the music app or file directly via execute_shell: "
        "Start-Process 'spotify:' or Start-Process 'wmplayer.exe'.",
    ),
    "PlannerAgent": (
        "GeneralAgent",
        "PlannerAgent failed to produce a plan. "
        "Handle this request directly as best you can, "
        "completing all implied steps yourself.",
    ),
}

_SYNTHESIZER_PROMPT = (
    "You are A.N.K.I.T.A's Synthesizer. You receive outputs from specialist agents that executed tasks. "
    "Your ONLY job is to confirm what was done in ONE brief sentence.\n\n"
    "STRICT RULES:\n"
    "1. NEVER echo, repeat, or display the content that was written/generated "
    "(no paragraphs, scripts, songs, emails, or any generated text in your reply).\n"
    "2. NEVER apologize or say 'it seems there was an issue' if the agent outputs show tools succeeded.\n"
    "3. NEVER offer manual alternatives like 'you can copy this yourself' or 'open it manually'.\n"
    "4. If actions succeeded -> ONE confirmation sentence. "
    "Examples: 'Done - wrote the report and opened it in Notepad.' "
    "'Done - drafted the letter and opened it in Notepad.' "
    "'Done - built the landing page and opened it in Chrome.'\n"
    "5. Preserve the actual artifact type from the request and agent outputs. "
    "Never downgrade a report, essay, letter, email, or landing page into a generic 'paragraph' or 'content'.\n"
    "6. If agent outputs contain CONTENT_PAYLOAD_V1, TASK_TYPE, FORMAT, format_type, or artifact_type, use that evidence in your wording.\n"
    "7. If a genuine error occurred (explicitly marked as failed) -> ONE sentence stating what failed.\n"
    "8. You are a STATUS REPORTER, not a content displayer or a chatbot. Be terse."
)

_DEEP_MODE_TASK_KEYWORDS = {
    "deep",
    "comprehensive",
    "detailed",
    "in-depth",
    "in depth",
    "full",
    "10 page",
    "10-page",
    "massive",
    "extensive",
    "thorough",
    "research",
    "investigation",
    "complete",
    "full investigation",
    "deep report",
    "deep dive",
    "deep-dive",
    "long form",
    "longform",
}
_DEEP_MODE_MAX_TOKENS = 8192


def extract_artifacts(text: str) -> Dict[str, List[str]]:
    artifacts: Dict[str, List[str]] = {
        "files": [],
        "urls": [],
        "handoffs": [],
        "opened_files": [],
        "launched_apps": [],
    }
    explicit_files: List[str] = []
    for match in re.finditer(r"FILE_PATH:\s*(.+?)(?:\n|$)", text):
        path = match.group(1).strip()
        if path and path not in artifacts["files"]:
            artifacts["files"].append(path)
            explicit_files.append(path)
    for match in re.finditer(r"OPENED_FILE:\s*(.+?)(?:\n|$)", text):
        path = match.group(1).strip()
        if path and path not in artifacts["opened_files"]:
            artifacts["opened_files"].append(path)
    for match in re.finditer(r"LAUNCHED_APP:\s*(.+?)(?:\n|$)", text):
        app = match.group(1).strip()
        if app and app not in artifacts["launched_apps"]:
            artifacts["launched_apps"].append(app)
    for match in re.finditer(
        r"(?<!\w)([A-Za-z]:\\[^\n\"'<>|*?]+|/(?:home|tmp|var|usr)/[^\s\"'<>|*?\n]+)",
        text,
    ):
        path = match.group(1).strip().rstrip(".,;)")
        if any(explicit == path or explicit.startswith(path + " ") for explicit in explicit_files):
            continue
        if path and path not in artifacts["files"]:
            artifacts["files"].append(path)
    for match in re.finditer(r"https?://[^\s\"'<>\n]+", text):
        url = match.group(0).strip().rstrip(".,;)")
        if url and url not in artifacts["urls"]:
            artifacts["urls"].append(url)
    for match in re.finditer(r"(SUGGEST_NEXT|HANDOFF):\s*(\w+Agent)\s*→\s*(.+?)(?:\n|$)", text):
        label = match.group(1).strip()
        agent = match.group(2).strip()
        message = match.group(3).strip()
        if "FILE_PATH" in message and explicit_files:
            message = message.replace("FILE_PATH", explicit_files[-1])
        handoff = f"{label}: {agent} → {message}"
        if handoff not in artifacts["handoffs"]:
            artifacts["handoffs"].append(handoff)
    if explicit_files and ("[OPENED]" in text or "[ALREADY_OPEN]" in text):
        for path in explicit_files:
            if path not in artifacts["opened_files"]:
                artifacts["opened_files"].append(path)
    for match in re.finditer(r"\[LAUNCHED\]\s*(.+?)(?:\n|$)", text):
        app_line = match.group(1).strip()
        if not app_line:
            continue
        app_name = app_line.split()[0].strip()
        if app_name and app_name not in artifacts["launched_apps"]:
            artifacts["launched_apps"].append(app_name)
    return artifacts


def merge_artifacts(reply: str, extra: Optional[Dict[str, List[str]]] = None) -> Dict[str, List[str]]:
    artifacts = extract_artifacts(reply or "")
    if not extra:
        return artifacts
    for key in ("files", "urls", "handoffs", "opened_files", "launched_apps"):
        for item in extra.get(key, []):
            if item and item not in artifacts[key]:
                artifacts[key].append(item)
    return artifacts


def slugify_filename(value: str, default: str = "content_output") -> str:
    slug = (value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug[:80] or default


def build_prior_context_block(agent_name: str, reply: str, artifacts: Dict[str, List[str]]) -> str:
    lines = ["--- PREVIOUS AGENT OUTPUT ---"]
    if agent_name == "ContentAgent":
        lines.append(f"[{agent_name}]: content generated")
    else:
        lines.append(f"[{agent_name}]: {reply.strip()}")

    if artifacts["files"]:
        for item in artifacts["files"]:
            lines.append(f"FILE: {item}")
    if artifacts.get("opened_files"):
        for item in artifacts["opened_files"]:
            lines.append(f"OPENED_FILE: {item}")
    if artifacts.get("launched_apps"):
        for item in artifacts["launched_apps"]:
            lines.append(f"LAUNCHED_APP: {item}")
    if artifacts["urls"]:
        for item in artifacts["urls"]:
            lines.append(f"URL: {item}")
    if artifacts.get("handoffs"):
        for item in artifacts["handoffs"]:
            lines.append(item)

    if agent_name == "ContentAgent" and not artifacts["files"] and reply.strip():
        if "already_saved" not in reply.lower():
            desktop = _known_folder(0x10, str(Path.home() / "Desktop"))
            lines.append(f"SAVE_TO: {desktop}")
            payload = parse_content_payload(reply)
            ok, errors = validate_content_payload(payload)
            if ok and payload is not None:
                task_type = str(payload.get("task_type", "other")).strip().lower() or "other"
                title = str(payload.get("title", "untitled")).strip() or "untitled"
                fmt = str(payload.get("format", "plain_text")).strip().lower() or "plain_text"
                tone = str(payload.get("tone", "")).strip()
                audience = str(payload.get("audience", "")).strip()
                word_target = str(payload.get("word_target", "")).strip()
                notes = str(payload.get("notes", "")).strip()
                body = extract_body(payload)
                ext = ".md" if fmt == "markdown" or task_type in {"report", "article"} else ".txt"
                lines.extend(
                    [
                        "CONTENT_SCHEMA: CONTENT_PAYLOAD_V1",
                        f"TASK_TYPE: {task_type}",
                        f"TITLE: {title}",
                        f"FORMAT: {fmt}",
                        f"AUDIENCE: {audience}",
                        f"TONE: {tone}",
                        f"WORD_TARGET: {word_target}",
                        f"FILENAME_HINT: {slugify_filename(title, default=task_type)}{ext}",
                    ]
                )
                if notes:
                    lines.append(f"CONTENT_NOTES: {notes}")
                lines.append(f"CONTENT:\n{body}\n:END_CONTENT")
            else:
                if errors:
                    lines.append(f"CONTENT_SCHEMA_ERRORS: {'; '.join(errors)}")
                lines.append(f"CONTENT:\n{reply.strip()}\n:END_CONTENT")

    if agent_name == "WebAgent":
        match = re.search(r"RESEARCH_CONTEXT_BLOCK:(.*?)END_RESEARCH_CONTEXT", reply, re.DOTALL)
        if match:
            lines.append(f"\n[RESEARCH_CONTEXT]\n{match.group(0).strip()}\n[/RESEARCH_CONTEXT]")
    lines.append("--- END CONTEXT ---")
    return "\n".join(lines)


def validate_or_repair_content_payload(
    specialist_runtime: LLMRuntime,
    messages: List[Dict[str, Any]],
    reply: str,
    max_tokens: int,
) -> Dict[str, Any]:
    payload = parse_content_payload(reply)
    ok, errors = validate_content_payload(payload)
    if ok:
        return {
            "reply": reply,
            "content_payload_valid": True,
            "content_payload_errors": [],
            "content_payload_repaired": False,
        }

    repair_prompt = (
        "Your previous output did not match CONTENT_PAYLOAD_V1. "
        "Return ONLY one valid CONTENT_PAYLOAD_V1 envelope and nothing else.\n"
        f"Validation errors: {errors}\n"
        "Preserve user intent and keep content quality."
    )
    fix_messages = list(messages) + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": repair_prompt},
    ]
    try:
        fixed = call_chat_once(specialist_runtime, fix_messages, tools=None, max_tokens=max_tokens)
        repaired_reply = (fixed.get("content") or "").strip()
        repaired_payload = parse_content_payload(repaired_reply)
        repaired_ok, repaired_errors = validate_content_payload(repaired_payload)
        if repaired_ok:
            return {
                "reply": repaired_reply,
                "content_payload_valid": True,
                "content_payload_errors": [],
                "content_payload_repaired": True,
            }
        return {
            "reply": reply,
            "content_payload_valid": False,
            "content_payload_errors": repaired_errors,
            "content_payload_repaired": False,
        }
    except Exception as repair_err:
        return {
            "reply": reply,
            "content_payload_valid": False,
            "content_payload_errors": [*errors, f"repair_failed: {repair_err}"],
            "content_payload_repaired": False,
        }


def is_deep_mode_task(task: str, prior_context: Optional[str] = None) -> bool:
    combined = f"{task} {prior_context or ''}".lower()
    return any(keyword in combined for keyword in _DEEP_MODE_TASK_KEYWORDS)


def extract_clean_history(messages: List[Dict[str, Any]], max_turns: int = 6) -> List[Dict[str, Any]]:
    def _strip_receipt_lines(text: str) -> str:
        kept_lines = [
            line
            for line in str(text or "").splitlines()
            if not line.startswith(("FILE_PATH:", "OPENED_FILE:", "LAUNCHED_APP:"))
        ]
        return "\n".join(kept_lines).strip()

    clean: List[Dict[str, Any]] = []
    for message in reversed(messages):
        role = message.get("role")
        content = message.get("content")
        if role in ("system", "tool"):
            continue
        if isinstance(content, list):
            continue
        if isinstance(content, str) and ("base64" in content or len(content) > 10000):
            continue
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            sanitized = _strip_receipt_lines(content)
            if sanitized:
                clean.append({"role": role, "content": sanitized})
        if len(clean) >= max_turns:
            break
    return list(reversed(clean))


def evaluate_condition(condition: str, step_results: Dict[int, Dict], depends_on: List[int]) -> bool:
    condition_lower = condition.lower().strip()
    match = re.search(r"step\s+(\d+)\s+(\w+)\s*==\s*(.+)", condition_lower)
    if match:
        step_id = int(match.group(1))
        field = match.group(2).strip()
        expected_value: Any = match.group(3).strip().strip("\"'")
        if step_id not in step_results:
            return False
        result = step_results[step_id]
        actual_value = result.get(field)
        if isinstance(expected_value, str) and expected_value.isdigit():
            expected_value = int(expected_value)
        elif expected_value in ("true", "false"):
            expected_value = expected_value == "true"
        return actual_value == expected_value
    match = re.search(r"step\s+(\d+)\s+succeeded", condition_lower)
    if match:
        step_id = int(match.group(1))
        return bool(step_results.get(step_id, {}).get("ok", False))
    match = re.search(r"step\s+(\d+)\s+failed", condition_lower)
    if match:
        step_id = int(match.group(1))
        return not bool(step_results.get(step_id, {}).get("ok", False))
    for dep_id in depends_on:
        if not step_results.get(dep_id, {}).get("ok", False):
            return False
    return True


def classify_interaction(agent_names: List[str], user_text: str) -> str:
    agent_set = set(agent_names)
    if "CodeAgent" in agent_set:
        return "code"
    if "ContentAgent" in agent_set:
        return "write"
    if "WebAgent" in agent_set:
        return "search"
    if agent_set & {"SystemAgent", "TerminalAgent", "FileAgent"}:
        return "system"
    text_lower = user_text.lower()
    if re.search(r"\b(code|debug|fix|refactor|write.*function|class|def |import )\b", text_lower):
        return "code"
    if re.search(r"\b(write|draft|essay|poem|blog|script|content)\b", text_lower):
        return "write"
    if re.search(r"\b(search|find|look up|google|research|what is|who is)\b", text_lower):
        return "search"
    if re.search(r"\b(run|execute|install|open|launch|start|stop|kill|terminal)\b", text_lower):
        return "system"
    return "general"


def append_follow_up_hint(reply: str, user_text: str, workspace_root: Path) -> str:
    try:
        tail = ""
        reply_lower = reply.lower()
        if tail:
            return reply + tail
        try:
            from datetime import datetime as _dt
            from tools.task_ops import task_op as _task_op

            result = _task_op(action="list")
            if result.get("status") == "success":
                for task in result.get("tasks", []):
                    if task.get("status") in ("pending", "in_progress") and task.get("deadline"):
                        try:
                            deadline = _dt.strptime(task["deadline"], "%Y-%m-%d %H:%M")
                            mins_left = (deadline - _dt.now()).total_seconds() / 60
                            if 0 < mins_left <= 120:
                                tail = (
                                    f"\n\n⏰ By the way, **{task['title']}** is due in {int(mins_left)} minutes."
                                )
                                break
                        except Exception:
                            pass
        except Exception:
            pass
        if tail:
            return reply + tail
    except Exception:
        pass
    return reply + tail if tail else reply


def extract_file_path(text: str) -> Optional[str]:
    match = re.search(r"FILE_PATH:\s*(.+?)(?:\n|$)", text)
    if match:
        return match.group(1).strip()
    return None


def _extract_artifacts(text: str) -> Dict[str, List[str]]:
    return extract_artifacts(text)


def _merge_artifacts(reply: str, extra: Optional[Dict[str, List[str]]] = None) -> Dict[str, List[str]]:
    return merge_artifacts(reply, extra)


def _slugify_filename(value: str, default: str = "content_output") -> str:
    return slugify_filename(value, default=default)


def _build_prior_context_block(agent_name: str, reply: str, artifacts: Dict[str, List[str]]) -> str:
    return build_prior_context_block(agent_name, reply, artifacts)


def _validate_or_repair_content_payload(
    specialist_runtime: LLMRuntime,
    messages: List[Dict[str, Any]],
    reply: str,
    max_tokens: int,
) -> Dict[str, Any]:
    return validate_or_repair_content_payload(specialist_runtime, messages, reply, max_tokens)


def _is_deep_mode_task(task: str, prior_context: Optional[str] = None) -> bool:
    return is_deep_mode_task(task, prior_context)


def _extract_clean_history(messages: List[Dict[str, Any]], max_turns: int = 6) -> List[Dict[str, Any]]:
    return extract_clean_history(messages, max_turns=max_turns)


def _evaluate_condition(condition: str, step_results: Dict[int, Dict], depends_on: List[int]) -> bool:
    return evaluate_condition(condition, step_results, depends_on)


def _classify_interaction(agent_names: List[str], user_text: str) -> str:
    return classify_interaction(agent_names, user_text)


def _append_follow_up_hint(reply: str, user_text: str, workspace_root: Path) -> str:
    return append_follow_up_hint(reply, user_text, workspace_root)


def _extract_file_path(text: str) -> Optional[str]:
    return extract_file_path(text)
