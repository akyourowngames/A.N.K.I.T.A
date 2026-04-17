"""Dedicated code and UI artifact writer for ANKITA."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional

from llm import LLMRuntime, build_runtime_from_env, call_chat_once
from llm.client import DEFAULT_NVIDIA_CODE_MODEL, NVIDIA_BASE_URL

from .writer_common import normalize_absolute_path, resolve_output_dir, safe_filename

DEFAULT_NVIDIA_CODEWRITER_REASONING_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_NVIDIA_CODEWRITER_MODEL = "qwen/qwen3-coder-480b-a35b-instruct"

_WEB_ARTIFACT_TYPES = {"landing_page", "html_page", "website"}
_ARTIFACT_ALIASES = {
    "landing page": "landing_page",
    "homepage": "landing_page",
    "home page": "landing_page",
    "web page": "html_page",
    "html page": "html_page",
    "website": "website",
    "site": "website",
    "component": "component",
    "script": "script",
}


def _env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _build_nvidia_runtime(reference_runtime: LLMRuntime) -> LLMRuntime:
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        return reference_runtime
    model = os.getenv("NVIDIA_MODEL", "").strip() or reference_runtime.model
    base_url = os.getenv("NVIDIA_BASE_URL", NVIDIA_BASE_URL).strip() or NVIDIA_BASE_URL
    return LLMRuntime(
        provider="nvidia",
        model=model,
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        max_tokens=reference_runtime.max_tokens,
    )


def _reasoning_runtime(base_runtime: LLMRuntime) -> LLMRuntime:
    preferred = _build_nvidia_runtime(base_runtime)
    model = _env_first(
        "NVIDIA_CODEWRITER_REASONING_MODEL",
        "CODEWRITER_REASONING_MODEL",
    )
    if not model and preferred.provider == "nvidia":
        model = DEFAULT_NVIDIA_CODEWRITER_REASONING_MODEL
    if not model:
        model = _env_first("NVIDIA_REASONING_MODEL", "REASONING_MODEL")
    return replace(preferred, model=model) if model else preferred


def _coding_runtime(base_runtime: LLMRuntime) -> LLMRuntime:
    preferred = _build_nvidia_runtime(base_runtime)
    model = _env_first(
        "NVIDIA_CODEWRITER_MODEL",
        "CODEWRITER_MODEL",
    )
    if not model and preferred.provider == "nvidia":
        model = DEFAULT_NVIDIA_CODEWRITER_MODEL
    if not model:
        model = _env_first("NVIDIA_CODE_MODEL", "CODEAGENT_MODEL")
    return replace(preferred, model=model) if model else preferred


def _normalize_artifact_type(artifact_type: str, task: str, framework: str) -> str:
    raw = str(artifact_type or "").strip().lower()
    if raw in _ARTIFACT_ALIASES:
        return _ARTIFACT_ALIASES[raw]
    if raw:
        return raw.replace(" ", "_")

    combined = " ".join(part.strip().lower() for part in (task, framework) if part and part.strip())
    if any(term in combined for term in ("landing page", "homepage", "home page")):
        return "landing_page"
    if any(term in combined for term in ("website", "web page", "html page")):
        return "website" if "website" in combined else "html_page"
    if "component" in combined:
        return "component"
    if "script" in combined:
        return "script"
    return "code_file"


def _default_extension(kind: str, filename: str, framework: str) -> str:
    provided_suffix = Path(str(filename or "")).suffix.lower()
    if provided_suffix:
        return provided_suffix

    framework_lower = str(framework or "").strip().lower()
    if kind in _WEB_ARTIFACT_TYPES:
        return ".html"
    if kind == "component":
        if "react" in framework_lower or "tsx" in framework_lower or "typescript" in framework_lower:
            return ".tsx"
        return ".jsx"
    if kind == "script":
        if "javascript" in framework_lower or framework_lower in {"node", "nodejs"}:
            return ".js"
        if "typescript" in framework_lower:
            return ".ts"
        return ".py"
    if "typescript" in framework_lower:
        return ".ts"
    if "javascript" in framework_lower:
        return ".js"
    if "html" in framework_lower:
        return ".html"
    return ".py"


def _slug_from_plan(title: str, fallback: str) -> str:
    candidate = safe_filename(title or fallback, max_len=50)
    return candidate.lower()


def _strip_fences(text: str) -> str:
    body = str(text or "").strip()
    fenced = re.match(r"^```[a-zA-Z0-9_-]*\s*([\s\S]*?)\s*```$", body)
    if fenced:
        body = fenced.group(1).strip()
    return body


def _parse_plan_json(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _looks_like_model_selection_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return (
        "404" in text
        or "unsupported" in text
        or "not found" in text
        or "tool use has not been enabled" in text
    )


def _call_with_model_fallback(
    runtime: LLMRuntime,
    messages: list[dict[str, str]],
    max_tokens: int,
    fallback_models: list[str],
) -> tuple[Dict[str, Any], str]:
    tried: set[str] = set()
    last_err: Optional[Exception] = None
    candidates = [runtime.model, *fallback_models]
    for model in candidates:
        selected = str(model or "").strip()
        if not selected or selected in tried:
            continue
        tried.add(selected)
        candidate_runtime = replace(runtime, model=selected)
        try:
            return call_chat_once(candidate_runtime, messages, tools=None, max_tokens=max_tokens), selected
        except Exception as exc:
            last_err = exc
            if not _looks_like_model_selection_error(exc):
                raise
    if last_err is not None:
        raise last_err
    raise RuntimeError("No usable model candidates were available.")


def _plan_prompt(task: str, artifact_type: str, framework: str, filename: str, extra_context: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a senior software planner for a code-generation pipeline. "
                "Return only one JSON object. No markdown fences. No commentary.\n"
                "Required keys: title, artifact_type, extension, filename_stem, framework, language, "
                "implementation_notes, visual_goals, acceptance_checks.\n"
                "implementation_notes, visual_goals, acceptance_checks must be arrays of short strings.\n"
                "For landing pages or HTML pages, optimize for a polished, usable local artifact rather than marketing fluff."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": task,
                    "artifact_type": artifact_type,
                    "framework_hint": framework,
                    "filename_hint": filename,
                    "extra_context": extra_context,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _build_code_prompt(
    task: str,
    artifact_type: str,
    framework: str,
    extra_context: str,
    plan: Dict[str, Any],
    extension: str,
) -> list[dict[str, str]]:
    base_rules = [
        "Return only the file contents for a single file.",
        "Do not wrap the output in markdown fences.",
        "Do not add commentary, explanations, or filenames.",
        "Prefer a complete, runnable artifact over placeholders.",
    ]
    if artifact_type in _WEB_ARTIFACT_TYPES:
        base_rules.extend(
            [
                "Produce one complete self-contained HTML document with inline CSS and minimal inline JavaScript.",
                "Start with <!DOCTYPE html>.",
                "Make the page responsive, polished, and directly usable when opened locally.",
                "Use semantic HTML and real sections, not lorem ipsum filler.",
            ]
        )
    elif extension in {".py", ".js", ".ts", ".tsx", ".jsx"}:
        base_rules.append("Write production-quality code with concise comments only where they add real value.")

    return [
        {
            "role": "system",
            "content": (
                "You are ANKITA's dedicated code artifact generator. "
                + " ".join(base_rules)
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": task,
                    "artifact_type": artifact_type,
                    "framework_hint": framework,
                    "extra_context": extra_context,
                    "plan": plan,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _audit_write(path: str, status: str, byte_count: int) -> None:
    try:
        audit_dir = Path.home() / ".ankita"
        audit_dir.mkdir(parents=True, exist_ok=True)
        log_line = (
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
            f"Code artifact write: {path} | Status: {status} | Bytes: {byte_count}\n"
        )
        with open(audit_dir / "audit.log", "a", encoding="utf-8") as handle:
            handle.write(log_line)
    except Exception:
        pass


def write_code_artifact(
    workspace_root: Path,
    task: str,
    artifact_type: str = "",
    extra_context: str = "",
    output_dir: Optional[str] = None,
    filename: Optional[str] = None,
    framework: str = "",
) -> Dict[str, Any]:
    """Generate a saved code or UI artifact using reasoning + coding model passes."""
    del workspace_root  # reserved for future artifact-relative generation

    task_clean = str(task or "").strip()
    if not task_clean:
        return {"ok": False, "error": "task is required.", "spoken_reply": "I need a coding task first."}

    artifact_kind = _normalize_artifact_type(artifact_type, task_clean, framework)
    base_runtime = build_runtime_from_env()
    reasoning_runtime = _reasoning_runtime(base_runtime)
    coding_runtime = _coding_runtime(base_runtime)

    plan_messages = _plan_prompt(
        task=task_clean,
        artifact_type=artifact_kind,
        framework=framework,
        filename=str(filename or ""),
        extra_context=extra_context,
    )
    plan_response, reasoning_model_used = _call_with_model_fallback(
        reasoning_runtime,
        plan_messages,
        max_tokens=900,
        fallback_models=[
            DEFAULT_NVIDIA_CODEWRITER_REASONING_MODEL,
            base_runtime.model,
            os.getenv("NVIDIA_MODEL", "").strip(),
        ],
    )
    plan = _parse_plan_json(plan_response.get("content") or "")

    plan_title = str(plan.get("title", "")).strip() or task_clean
    plan_framework = str(plan.get("framework", "")).strip() or str(framework or "").strip()
    filename_hint = str(filename or "").strip()
    extension = str(plan.get("extension", "")).strip() or _default_extension(artifact_kind, filename_hint, plan_framework)
    filename_stem = (
        Path(filename_hint).stem
        if filename_hint
        else str(plan.get("filename_stem", "")).strip() or _slug_from_plan(plan_title, artifact_kind)
    )
    final_filename = Path(filename_hint).name if filename_hint else f"{filename_stem}{extension}"

    code_messages = _build_code_prompt(
        task=task_clean,
        artifact_type=artifact_kind,
        framework=plan_framework,
        extra_context=extra_context,
        plan=plan,
        extension=extension,
    )
    code_max_tokens = 8192 if artifact_kind in _WEB_ARTIFACT_TYPES else 6144
    code_response, coding_model_used = _call_with_model_fallback(
        coding_runtime,
        code_messages,
        max_tokens=code_max_tokens,
        fallback_models=[
            DEFAULT_NVIDIA_CODEWRITER_MODEL,
            os.getenv("NVIDIA_CODE_MODEL", "").strip(),
            os.getenv("CODEAGENT_MODEL", "").strip(),
            DEFAULT_NVIDIA_CODE_MODEL,
        ],
    )
    generated_text = _strip_fences(code_response.get("content") or "")
    if not generated_text:
        return {
            "ok": False,
            "error": "Coding model returned empty content.",
            "spoken_reply": "The code writer came back empty.",
        }

    dest_dir = resolve_output_dir(output_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    file_path = dest_dir / final_filename
    if file_path.exists():
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        file_path = dest_dir / f"{Path(final_filename).stem}_{timestamp}{extension}"

    absolute_path = normalize_absolute_path(file_path)
    _audit_write(absolute_path, "attempting", 0)
    try:
        file_path.write_text(generated_text, encoding="utf-8")
        byte_count = len(generated_text.encode("utf-8"))
        _audit_write(absolute_path, "success", byte_count)
    except Exception as err:
        _audit_write(absolute_path, f"FAILED: {err}", 0)
        return {
            "ok": False,
            "error": f"Failed to save code artifact: {err}",
            "spoken_reply": f"I built the artifact but couldn't save it: {err}",
        }

    return {
        "ok": True,
        "status": "success",
        "path": absolute_path,
        "absolute_path": absolute_path,
        "FILE_PATH": absolute_path,
        "already_saved": True,
        "bytes": byte_count,
        "filename": Path(absolute_path).name,
        "artifact_type": artifact_kind,
        "framework": plan_framework,
        "title": plan_title,
        "reasoning_model": reasoning_model_used,
        "coding_model": coding_model_used,
        "spoken_reply": (
            f"Done! Built the {artifact_kind.replace('_', ' ')} and saved it as {Path(absolute_path).name}."
        ),
    }
