"""Global completion-loop helpers for orchestration.

UPGRADED:
- Tiered retry system (quick → deep → escalation → decompose)
- Tool-aware failure recovery using PlannerAgent introspection
- Circuit breaker pattern for repeat failures
- Adaptive retry with exponential backoff + jitter
- Per-step granular retry with smart strategy selection
- Rich verification with multi-signal fusion
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llm import LLMRuntime, call_chat_once
from llm.client import build_vision_runtime_from_env, call_chat_with_image
from tools import desktop_ops

from .shared import merge_artifacts

MAX_COMPLETION_ATTEMPTS = 5  # Upgraded from 4

# ---------------------------------------------------------------------------
# Circuit Breaker — prevent infinite retry loops
# ---------------------------------------------------------------------------

class _CircuitBreaker:
    """
    Tracks consecutive failures per agent. After N consecutive failures,
    the circuit "opens" and that agent is bypassed for a cooldown period.
    """

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 60.0):
        self._failures: Dict[str, int] = {}
        self._open_until: Dict[str, float] = {}
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds

    def record_success(self, agent_name: str) -> None:
        self._failures[agent_name] = 0
        self._open_until.pop(agent_name, None)

    def record_failure(self, agent_name: str) -> None:
        count = self._failures.get(agent_name, 0) + 1
        self._failures[agent_name] = count
        if count >= self._threshold:
            self._open_until[agent_name] = time.time() + self._cooldown
            print(
                f"[CircuitBreaker] ⚡ {agent_name} circuit OPEN after {count} consecutive failures. "
                f"Cooldown: {self._cooldown}s",
                flush=True,
            )

    def is_open(self, agent_name: str) -> bool:
        deadline = self._open_until.get(agent_name)
        if deadline is None:
            return False
        if time.time() >= deadline:
            # Cooldown expired — half-open (allow one attempt)
            self._open_until.pop(agent_name, None)
            self._failures[agent_name] = self._threshold - 1  # One more failure re-opens
            return False
        return True

    def get_failure_count(self, agent_name: str) -> int:
        return self._failures.get(agent_name, 0)

    def reset(self) -> None:
        self._failures.clear()
        self._open_until.clear()


# Global circuit breaker instance
_circuit_breaker = _CircuitBreaker()


# ---------------------------------------------------------------------------
# Retry Strategy Engine
# ---------------------------------------------------------------------------

class RetryStrategy:
    """Determines HOW to retry a failed step based on error classification."""

    STRATEGIES = {
        "none": {"max_retries": 0, "backoff_base": 0},
        "transient": {"max_retries": 3, "backoff_base": 1.5},
        "permission": {"max_retries": 2, "backoff_base": 0.5},
        "alternative": {"max_retries": 1, "backoff_base": 0},
        "decompose": {"max_retries": 2, "backoff_base": 1.0},
    }

    @staticmethod
    def get_config(strategy_name: str) -> Dict[str, Any]:
        return RetryStrategy.STRATEGIES.get(
            strategy_name,
            RetryStrategy.STRATEGIES["transient"],
        )

    @staticmethod
    def compute_backoff(attempt: int, strategy_name: str) -> float:
        """Compute backoff delay with jitter (exponential backoff)."""
        config = RetryStrategy.get_config(strategy_name)
        base = config["backoff_base"]
        if base <= 0:
            return 0.0
        delay = min(base * (2 ** attempt) + random.uniform(0, 1), 30.0)
        return delay

    @staticmethod
    def should_retry(
        attempt: int,
        strategy_name: str,
        error_text: str = "",
        agent_name: str = "",
    ) -> Tuple[bool, str]:
        """
        Decide whether to retry, and return (should_retry, reason).
        
        Also checks the circuit breaker.
        """
        if _circuit_breaker.is_open(agent_name):
            return False, f"Circuit breaker open for {agent_name}"

        config = RetryStrategy.get_config(strategy_name)
        if attempt >= config["max_retries"]:
            return False, f"Max retries ({config['max_retries']}) exhausted for strategy '{strategy_name}'"

        # Classify the error to decide
        error_lower = error_text.lower()

        # Non-retryable errors (hard failures)
        hard_failures = ("invalid api key", "billing", "subscription", "payment", "quota exceeded")
        if any(hf in error_lower for hf in hard_failures):
            return False, "Hard failure (auth/billing) — not retryable"

        # Strategy-specific logic
        if strategy_name == "transient":
            transient_markers = ("timeout", "rate limit", "429", "connection", "network", "dns", "socket")
            if any(marker in error_lower for marker in transient_markers):
                return True, f"Transient error detected, retry with backoff"
            return True, "Retrying (transient strategy allows general retry)"

        if strategy_name == "permission":
            if "permission" in error_lower or "denied" in error_lower or "access" in error_lower:
                return True, "Permission error — will try elevated"
            return False, "Not a permission error"

        if strategy_name == "alternative":
            return True, "Trying fallback agent"

        if strategy_name == "decompose":
            return True, "Decomposing step into sub-steps"

        return False, f"Unknown strategy: {strategy_name}"

    @staticmethod
    def classify_error(error_text: str) -> str:
        """Classify an error into a retry strategy suggestion."""
        e = error_text.lower()
        if any(k in e for k in ("timeout", "rate limit", "429", "connection", "network")):
            return "transient"
        if any(k in e for k in ("permission", "denied", "access", "forbidden")):
            return "permission"
        if any(k in e for k in ("not found", "no such file", "does not exist")):
            return "alternative"
        if any(k in e for k in ("context_length", "too large", "maximum context")):
            return "decompose"
        return "transient"  # Default to transient (most forgiving)


# ---------------------------------------------------------------------------
# Tool-Aware Recovery — uses PlannerAgent's introspection API
# ---------------------------------------------------------------------------

def _get_fallback_agent(failed_agent: str, error_text: str = "") -> Optional[str]:
    """
    Use the capability manifest to find a fallback agent that can handle
    the same capabilities as the failed agent.
    """
    try:
        from agents.planner import get_capability_manifest
        manifest = get_capability_manifest()
    except Exception:
        return None

    failed_info = manifest.get("agents", {}).get(failed_agent)
    if not failed_info:
        return None

    failed_caps = set(failed_info.get("capabilities", []))
    if not failed_caps:
        return None

    # Known escalation paths (from HYDRA protocol)
    escalation = {
        "SystemAgent": "TerminalAgent",
        "WebAgent": "GeneralAgent",
        "FileAgent": "TerminalAgent",
        "ContentAgent": "GeneralAgent",
        "CodeAgent": "CodeAgent",  # Self-retry with different approach
        "MusicAgent": "TerminalAgent",
    }

    # Try known escalation first
    if failed_agent in escalation:
        return escalation[failed_agent]

    # Dynamic fallback: find an agent with overlapping capabilities
    best_match = None
    best_overlap = 0

    for agent_name, info in manifest.get("agents", {}).items():
        if agent_name == failed_agent:
            continue
        agent_caps = set(info.get("capabilities", []))
        overlap = len(failed_caps & agent_caps)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = agent_name

    return best_match


# ---------------------------------------------------------------------------
# Completion Review Prompts (Upgraded)
# ---------------------------------------------------------------------------

_COMPLETION_REVIEW_PROMPT = """You are the completion verifier for A.N.K.I.T.A.

Decide whether the original user request is actually complete.

Return ONLY JSON:
{"status":"complete|retry|failed","reason":"...","retry_instruction":"...","verification_summary":"...","retry_strategy":"transient|permission|alternative|decompose|none","suggested_agent":"AgentName|null"}

Rules:
- Use the original request, specialist outputs, and objective verification signals.
- Mark "complete" only when the request is satisfied or there is objective evidence that the required actions already happened.
- Check artifact-task fit, not just whether something was opened or launched.
- If the request asked for a specific artifact type or outcome (for example a landing page, report, image, screenshot, code file, or app), make sure the evidence matches that outcome.
- If something opened successfully but it is clearly the wrong file, wrong format, wrong app, or wrong artifact for the request, return "retry".
- If there is partial progress plus a recoverable failure, return "retry" with a specific retry_strategy:
    - "transient" for network/timeout/rate-limit issues
    - "permission" for access denied errors
    - "alternative" to try a different agent
    - "decompose" to break the step into smaller pieces
- Include "suggested_agent" if a different agent should handle the retry.
- Preserve completed work. Never ask the next attempt to repeat confirmed-complete open/save/build steps unless strictly necessary.
- If the outputs show a launched/opened target already succeeded, treat that step as complete.
- If there is a hard blocker with no reasonable next attempt, return "failed".
- Be concise and operational.
"""

_SCREENSHOT_VERIFY_DECIDER_PROMPT = """You decide whether screenshot verification is worth doing for an ambiguous desktop/system task.

Return ONLY JSON:
{"use_screenshot_verification":true|false,"reason":"...","focus":"..."}

Rules:
- Choose true only if a fresh screenshot of the current screen could materially clarify whether the request succeeded.
- Prefer false for pure text/chat tasks, background tasks, web research, and anything already proven by objective artifacts.
- Prefer true for GUI/app/window/open/show/click/view tasks when current evidence is ambiguous or conflicting.
- `focus` should say what to visually check on screen if verification is useful.
"""

_SCREENSHOT_VERIFY_PROMPT = """You are verifying whether a user request succeeded by looking at a CURRENT screenshot of the screen.

Return ONLY JSON:
{"status":"complete|unclear|retry","reason":"...","visible_evidence":"..."}

Rules:
- Mark `complete` only if the screenshot clearly shows the requested outcome on screen.
- Mark `retry` if the screenshot clearly shows the task did not succeed yet.
- Mark `unclear` if the screenshot does not provide enough evidence either way.
- Be literal. Do not infer hidden state that is not visible.
"""


# ---------------------------------------------------------------------------
# Result Analysis Helpers
# ---------------------------------------------------------------------------

def result_has_objective_open_success(result: Dict[str, Any]) -> bool:
    artifacts = merge_artifacts(result.get("reply", "") or "", result.get("artifacts"))
    return bool(artifacts.get("opened_files") or artifacts.get("launched_apps"))


def reply_looks_like_failure(reply: str) -> bool:
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
        "permission denied",
        "access denied",
        "connection refused",
        "module not found",
        "import error",
    )
    return any(marker in text for marker in failure_markers)


def verification_has_any_objective_success(verification: Dict[str, Any]) -> bool:
    return bool(
        verification.get("existing_files")
        or verification.get("opened_files")
        or verification.get("launched_apps")
    )


def _request_might_be_visually_verifiable(original_request: str, results: List[Dict[str, Any]]) -> bool:
    text = str(original_request or "").strip().lower()
    if not text:
        return False
    visual_markers = (
        "open ",
        "launch ",
        "show ",
        "view ",
        "click ",
        "window",
        "screen",
        "desktop",
        "app",
        "browser",
        "notepad",
        "calculator",
        "paint",
        "explorer",
    )
    if any(marker in text for marker in visual_markers):
        return True
    agent_names = {str(result.get("agent", "")).strip() for result in results}
    return bool(agent_names & {"SystemAgent", "ScreenAgent", "TerminalAgent"})


def _clean_screen_verification_signal(signal: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(signal, dict):
        return None
    return {
        "status": str(signal.get("status", "")).strip(),
        "reason": str(signal.get("reason", "")).strip(),
        "focus": str(signal.get("focus", "")).strip(),
        "visible_evidence": str(signal.get("visible_evidence", "")).strip(),
        "path": str(signal.get("path", "")).strip(),
        "provider": str(signal.get("provider", "")).strip(),
        "model": str(signal.get("model", "")).strip(),
    }


# ---------------------------------------------------------------------------
# Screenshot Verification
# ---------------------------------------------------------------------------

def _should_try_screenshot_verification(
    runtime: LLMRuntime,
    original_request: str,
    latest_reply: str,
    results: List[Dict[str, Any]],
    verification: Dict[str, Any],
    attempt_index: int,
) -> Optional[Dict[str, Any]]:
    if os.getenv("ANKITA_SCREENSHOT_VERIFY_ENABLE", "true").strip().lower() in {"0", "false", "no", "off"}:
        return None
    if verification_has_any_objective_success(verification):
        return None
    if not _request_might_be_visually_verifiable(original_request, results):
        return None
    if not (verification.get("failures") or reply_looks_like_failure(latest_reply) or attempt_index > 1):
        return None
    payload = {
        "original_request": original_request,
        "attempt": attempt_index,
        "latest_reply": latest_reply[:300],
        "specialist_results": [_summarize_result(result) for result in results],
        "verification": verification,
    }
    try:
        response = call_chat_once(
            runtime,
            [
                {"role": "system", "content": _SCREENSHOT_VERIFY_DECIDER_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            tools=None,
            max_tokens=140,
        )
        content = (response.get("content") or "").strip()
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            content = match.group(0)
        parsed = json.loads(content)
        if not bool(parsed.get("use_screenshot_verification", False)):
            return None
        return {
            "status": "requested",
            "reason": str(parsed.get("reason", "")).strip(),
            "focus": str(parsed.get("focus", "")).strip(),
        }
    except Exception:
        return None


def _run_screenshot_verification(
    runtime: LLMRuntime,
    original_request: str,
    results: List[Dict[str, Any]],
    verification: Dict[str, Any],
    decision: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    try:
        capture = desktop_ops.capture_screen(monitor=1)
    except Exception as err:
        return {"status": "unavailable", "reason": str(err), "focus": str(decision.get("focus", "")).strip()}
    if not capture.get("ok"):
        return {
            "status": "unavailable",
            "reason": str(capture.get("error", "screen capture failed")).strip(),
            "focus": str(decision.get("focus", "")).strip(),
            "path": str(capture.get("FILE_PATH") or capture.get("path") or "").strip(),
        }
    image_b64 = str(capture.get("base64", "")).strip()
    if not image_b64:
        return {
            "status": "unavailable",
            "reason": "screen capture returned no image payload",
            "focus": str(decision.get("focus", "")).strip(),
            "path": str(capture.get("FILE_PATH") or capture.get("path") or "").strip(),
        }
    vision_runtime = build_vision_runtime_from_env(runtime)
    verify_payload = {
        "original_request": original_request,
        "focus": str(decision.get("focus", "")).strip(),
        "specialist_results": [_summarize_result(result) for result in results],
        "verification": verification,
    }
    try:
        content = call_chat_with_image(
            vision_runtime,
            _SCREENSHOT_VERIFY_PROMPT + "\n\n" + json.dumps(verify_payload, ensure_ascii=False),
            image_b64,
            max_tokens=260,
            temperature=0.0,
            mime_type=str(capture.get("base64_mime", "image/jpeg")).strip() or "image/jpeg",
        )
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            content = match.group(0)
        parsed = json.loads(content)
        status = str(parsed.get("status", "")).strip().lower()
        if status not in {"complete", "unclear", "retry"}:
            status = "unclear"
        return {
            "status": status,
            "reason": str(parsed.get("reason", "")).strip(),
            "focus": str(decision.get("focus", "")).strip(),
            "visible_evidence": str(parsed.get("visible_evidence", "")).strip(),
            "path": str(capture.get("FILE_PATH") or capture.get("path") or "").strip(),
            "provider": vision_runtime.provider,
            "model": vision_runtime.model,
        }
    except Exception as err:
        return {
            "status": "unavailable",
            "reason": str(err),
            "focus": str(decision.get("focus", "")).strip(),
            "path": str(capture.get("FILE_PATH") or capture.get("path") or "").strip(),
            "provider": vision_runtime.provider,
            "model": vision_runtime.model,
        }


# ---------------------------------------------------------------------------
# Result Failure Detection
# ---------------------------------------------------------------------------

def _result_failed(result: Dict[str, Any]) -> bool:
    if result_has_objective_open_success(result):
        return False
    reply = str(result.get("reply", "") or "")
    return bool(
        not result.get("ok", True)
        or reply.startswith("[Error]")
        or "[FAILED]" in reply
        or "error_class:" in reply.lower()
        or reply_looks_like_failure(reply)
    )


def _safe_path_exists(path_text: str) -> bool:
    try:
        return Path(path_text).expanduser().exists()
    except Exception:
        return False


def _summarize_result(result: Dict[str, Any]) -> Dict[str, Any]:
    artifacts = merge_artifacts(result.get("reply", "") or "", result.get("artifacts"))
    return {
        "agent": result.get("agent", "Agent"),
        "ok": bool(result.get("ok", True)),
        "rerouted_from": result.get("rerouted_from"),
        "reply_preview": str(result.get("reply", "") or "")[:800],
        "artifacts": artifacts,
    }


# ---------------------------------------------------------------------------
# Verification Signal Collection (Upgraded)
# ---------------------------------------------------------------------------

def collect_verification_signals(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    existing_files: List[str] = []
    missing_files: List[str] = []
    opened_files: List[str] = []
    launched_apps: List[str] = []
    failures: List[Dict[str, str]] = []
    tool_errors: List[Dict[str, str]] = []

    for result in results:
        summary = _summarize_result(result)
        artifacts = summary["artifacts"]
        for path_text in artifacts.get("files", []):
            target_bucket = existing_files if _safe_path_exists(path_text) else missing_files
            if path_text not in target_bucket:
                target_bucket.append(path_text)
        for path_text in artifacts.get("opened_files", []):
            if path_text and path_text not in opened_files:
                opened_files.append(path_text)
        for app_name in artifacts.get("launched_apps", []):
            if app_name and app_name not in launched_apps:
                launched_apps.append(app_name)
        if _result_failed(result):
            agent_name = str(summary["agent"])
            reply_preview = str(summary["reply_preview"])
            failures.append(
                {
                    "agent": agent_name,
                    "reply_preview": reply_preview,
                }
            )
            # Record failure in circuit breaker
            _circuit_breaker.record_failure(agent_name)

            # Extract tool-level error info
            error_strategy = RetryStrategy.classify_error(reply_preview)
            tool_errors.append({
                "agent": agent_name,
                "classified_strategy": error_strategy,
                "fallback_agent": _get_fallback_agent(agent_name, reply_preview) or "",
            })
        else:
            # Record success in circuit breaker
            agent_name = str(summary["agent"])
            _circuit_breaker.record_success(agent_name)

    return {
        "existing_files": existing_files,
        "missing_files": missing_files,
        "opened_files": opened_files,
        "launched_apps": launched_apps,
        "failures": failures,
        "tool_errors": tool_errors,
    }


def _has_strong_completion_signal(results: List[Dict[str, Any]], verification: Dict[str, Any]) -> bool:
    successful_agents = {
        str(result.get("agent", ""))
        for result in results
        if not _result_failed(result)
    }
    failed_agents = {str(item.get("agent", "")) for item in verification.get("failures", [])}
    has_open_signal = bool(verification.get("opened_files") or verification.get("launched_apps"))
    has_file_signal = bool(verification.get("existing_files"))
    if (
        has_open_signal
        and has_file_signal
        and successful_agents & {"ContentAgent", "FileAgent", "CodeAgent", "WebAgent", "ImageAgent"}
        and failed_agents
        and failed_agents.issubset({"SystemAgent", "TerminalAgent"})
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Completion Review (Upgraded with retry strategy awareness)
# ---------------------------------------------------------------------------

def review_completion_attempt(
    runtime: LLMRuntime,
    original_request: str,
    reply: str,
    results: List[Dict[str, Any]],
    attempt_index: int,
    prior_attempts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    verification = collect_verification_signals(results)

    # Fast-path: GeneralAgent conversation-only
    if (
        len(results) == 1
        and str(results[0].get("agent", "")) == "GeneralAgent"
        and not verification["failures"]
    ):
        return {
            "status": "complete",
            "reason": "General conversational reply completed without tool failure.",
            "retry_instruction": "",
            "verification_summary": "conversation_only",
            "verification": verification,
            "retry_strategy": "none",
            "suggested_agent": None,
        }

    # Fast-path: strong objective signal
    if _has_strong_completion_signal(results, verification):
        return {
            "status": "complete",
            "reason": "Objective open/save evidence is already present despite redundant downstream failure.",
            "retry_instruction": "",
            "verification_summary": "artifact_verified",
            "verification": verification,
            "retry_strategy": "none",
            "suggested_agent": None,
        }

    # Circuit breaker check — if ALL failed agents have open circuits, don't retry
    if verification["failures"]:
        all_open = all(
            _circuit_breaker.is_open(f.get("agent", ""))
            for f in verification["failures"]
        )
        if all_open and attempt_index > 1:
            return {
                "status": "failed",
                "reason": "All failed agents have tripped their circuit breakers. Stopping retry loop.",
                "retry_instruction": "",
                "verification_summary": "circuit_breaker_halt",
                "verification": verification,
                "retry_strategy": "none",
                "suggested_agent": None,
            }

    # Screenshot verification
    screenshot_decision = _should_try_screenshot_verification(
        runtime,
        original_request,
        reply,
        results,
        verification,
        attempt_index,
    )
    screenshot_signal = _run_screenshot_verification(
        runtime,
        original_request,
        results,
        verification,
        screenshot_decision,
    ) if screenshot_decision else None
    cleaned_screen_signal = _clean_screen_verification_signal(screenshot_signal)
    if cleaned_screen_signal:
        verification["screenshot_verification"] = cleaned_screen_signal
        if cleaned_screen_signal.get("status") == "complete":
            return {
                "status": "complete",
                "reason": cleaned_screen_signal.get("reason") or "Current screenshot visually confirms the task is complete.",
                "retry_instruction": "",
                "verification_summary": "screenshot_verified",
                "verification": verification,
                "retry_strategy": "none",
                "suggested_agent": None,
            }

    # Inject tool-aware context into the review payload
    tool_awareness = {}
    try:
        from agents.planner import get_capability_manifest
        manifest = get_capability_manifest()
        tool_awareness = {
            "total_agents": manifest["total_agents"],
            "total_tools": manifest["total_tools"],
            "failed_agent_fallbacks": {
                err["agent"]: err.get("fallback_agent", "")
                for err in verification.get("tool_errors", [])
            },
        }
    except Exception:
        pass

    payload = {
        "original_request": original_request,
        "attempt": attempt_index,
        "max_attempts": MAX_COMPLETION_ATTEMPTS,
        "latest_reply": reply,
        "specialist_results": [_summarize_result(result) for result in results],
        "verification": verification,
        "prior_attempts": prior_attempts[-2:],
        "tool_awareness": tool_awareness,
    }

    try:
        response = call_chat_once(
            runtime,
            [
                {"role": "system", "content": _COMPLETION_REVIEW_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            tools=None,
            max_tokens=300,
        )
        content = (response.get("content") or "").strip()
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            content = match.group(0)
        parsed = json.loads(content)
        status = str(parsed.get("status", "")).strip().lower()
        if status not in {"complete", "retry", "failed"}:
            raise ValueError(f"invalid completion status: {status}")
        if status != "complete" and _has_strong_completion_signal(results, verification):
            status = "complete"
        return {
            "status": status,
            "reason": str(parsed.get("reason", "")).strip(),
            "retry_instruction": str(parsed.get("retry_instruction", "")).strip(),
            "verification_summary": str(parsed.get("verification_summary", "")).strip(),
            "verification": verification,
            "retry_strategy": str(parsed.get("retry_strategy", "transient")).strip(),
            "suggested_agent": parsed.get("suggested_agent"),
        }
    except Exception:
        return _fallback_completion_review(original_request, reply, results, verification, attempt_index)


def _fallback_completion_review(
    original_request: str,
    reply: str,
    results: List[Dict[str, Any]],
    verification: Dict[str, Any],
    attempt_index: int,
) -> Dict[str, Any]:
    failures = verification.get("failures", [])
    missing_files = verification.get("missing_files", [])
    tool_errors = verification.get("tool_errors", [])
    screenshot_signal = _clean_screen_verification_signal(verification.get("screenshot_verification"))

    if screenshot_signal and screenshot_signal.get("status") == "complete":
        return {
            "status": "complete",
            "reason": screenshot_signal.get("reason") or "Current screenshot visually confirms the task is complete.",
            "retry_instruction": "",
            "verification_summary": "screenshot_verified",
            "verification": verification,
            "retry_strategy": "none",
            "suggested_agent": None,
        }

    if not failures and not missing_files:
        status = "complete"
        reason = "No explicit specialist failure and all referenced local artifacts exist."
        retry_strategy = "none"
        suggested_agent = None
    elif attempt_index < MAX_COMPLETION_ATTEMPTS:
        status = "retry"
        reason = "Recoverable failure or missing artifact detected."

        # Smart strategy selection from tool errors
        if tool_errors:
            primary_error = tool_errors[0]
            retry_strategy = primary_error.get("classified_strategy", "transient")
            suggested_agent = primary_error.get("fallback_agent") or None
        else:
            retry_strategy = "transient"
            suggested_agent = None
    else:
        status = "failed"
        reason = "Retry budget exhausted with unresolved failure."
        retry_strategy = "none"
        suggested_agent = None

    retry_instruction = (
        "Continue the original request from the last attempt. "
        "Keep confirmed-complete work, do not reopen or relaunch already opened targets, "
        "and only fix the missing or failed step."
    )
    return {
        "status": status,
        "reason": reason,
        "retry_instruction": retry_instruction,
        "verification_summary": reply[:160],
        "verification": verification,
        "retry_strategy": retry_strategy,
        "suggested_agent": suggested_agent,
    }


# ---------------------------------------------------------------------------
# Retry Context Builder (Upgraded)
# ---------------------------------------------------------------------------

def build_retry_context(
    original_request: str,
    attempt_index: int,
    latest_reply: str,
    review: Dict[str, Any],
) -> str:
    verification = review.get("verification", {})
    retry_strategy = review.get("retry_strategy", "transient")
    suggested_agent = review.get("suggested_agent")

    lines = [
        "--- GLOBAL COMPLETION LOOP ---",
        f"ORIGINAL_REQUEST: {original_request}",
        f"ATTEMPT: {attempt_index}/{MAX_COMPLETION_ATTEMPTS}",
        f"VERDICT: {review.get('status', 'retry')}",
        f"REASON: {review.get('reason', '')}",
        f"RETRY_STRATEGY: {retry_strategy}",
    ]

    if suggested_agent:
        lines.append(f"SUGGESTED_AGENT: {suggested_agent}")

    if review.get("retry_instruction"):
        lines.append(f"RETRY_INSTRUCTION: {review['retry_instruction']}")

    # Inject backoff delay info
    backoff = RetryStrategy.compute_backoff(attempt_index, retry_strategy)
    if backoff > 0:
        lines.append(f"BACKOFF_DELAY: {backoff:.1f}s (applied before this attempt)")

    for path_text in verification.get("existing_files", [])[:6]:
        lines.append(f"CONFIRMED_FILE: {path_text}")
    for path_text in verification.get("opened_files", [])[:6]:
        lines.append(f"OPENED_FILE: {path_text}")
    for app_name in verification.get("launched_apps", [])[:6]:
        lines.append(f"LAUNCHED_APP: {app_name}")

    for failure in verification.get("failures", [])[:4]:
        agent = failure.get("agent", "")
        lines.append(f"FAILED_AGENT: {agent}")
        preview = str(failure.get("reply_preview", "")).strip()
        if preview:
            lines.append(f"FAILED_REPLY: {preview[:240]}")
        # Show circuit breaker status
        if _circuit_breaker.is_open(agent):
            lines.append(f"CIRCUIT_BREAKER: {agent} is OPEN (temporarily bypassed)")
        failure_count = _circuit_breaker.get_failure_count(agent)
        if failure_count > 0:
            lines.append(f"CONSECUTIVE_FAILURES: {agent} = {failure_count}")

    # Tool error analysis
    for err in verification.get("tool_errors", [])[:4]:
        agent = err.get("agent", "")
        strategy = err.get("classified_strategy", "")
        fallback = err.get("fallback_agent", "")
        if strategy:
            lines.append(f"ERROR_STRATEGY[{agent}]: {strategy}")
        if fallback:
            lines.append(f"FALLBACK_AGENT[{agent}]: {fallback}")

    screenshot_signal = _clean_screen_verification_signal(verification.get("screenshot_verification"))
    if screenshot_signal:
        if screenshot_signal.get("status"):
            lines.append(f"SCREENSHOT_VERIFY_STATUS: {screenshot_signal['status']}")
        if screenshot_signal.get("reason"):
            lines.append(f"SCREENSHOT_VERIFY_REASON: {screenshot_signal['reason']}")
        if screenshot_signal.get("visible_evidence"):
            lines.append(f"SCREENSHOT_VERIFY_EVIDENCE: {screenshot_signal['visible_evidence'][:240]}")
        if screenshot_signal.get("path"):
            lines.append(f"SCREENSHOT_VERIFY_PATH: {screenshot_signal['path']}")

    if latest_reply:
        lines.append(f"LATEST_REPLY: {latest_reply[:400]}")

    lines.append("Do not repeat confirmed-complete steps. Finish only what is still missing.")
    return "\n".join(lines)


def build_retry_user_text(original_request: str, review: Dict[str, Any]) -> str:
    instruction = str(review.get("retry_instruction", "")).strip()
    retry_strategy = review.get("retry_strategy", "transient")
    suggested_agent = review.get("suggested_agent")

    if not instruction:
        instruction = (
            "Continue the same request, preserve completed work, and finish the missing part."
        )

    strategy_hint = ""
    if retry_strategy == "permission":
        strategy_hint = "\n[HINT: Try with elevated permissions or use TerminalAgent for direct shell access.]"
    elif retry_strategy == "alternative":
        agent_hint = f" using {suggested_agent}" if suggested_agent else ""
        strategy_hint = f"\n[HINT: Try a different approach{agent_hint}.]"
    elif retry_strategy == "decompose":
        strategy_hint = "\n[HINT: Break this into smaller sub-steps.]"

    return f"{original_request}\n\n[GLOBAL COMPLETION LOOP RETRY]{strategy_hint}\n{instruction}"


def apply_retry_backoff(attempt_index: int, review: Dict[str, Any]) -> None:
    """Apply adaptive backoff delay before retrying. Call this before the retry attempt."""
    retry_strategy = review.get("retry_strategy", "transient")
    delay = RetryStrategy.compute_backoff(attempt_index, retry_strategy)
    if delay > 0:
        print(f"[RetryBackoff] Waiting {delay:.1f}s before attempt {attempt_index + 1}...", flush=True)
        time.sleep(delay)


# ---------------------------------------------------------------------------
# Utility predicates
# ---------------------------------------------------------------------------

def context_has_completed_open(prior_context: Optional[str]) -> bool:
    if not prior_context:
        return False
    return any(
        line.startswith(("OPENED_FILE:", "LAUNCHED_APP:"))
        for line in prior_context.splitlines()
    )


def task_requests_open(task: Optional[str]) -> bool:
    text = str(task or "").strip().lower()
    if not text:
        return False
    return bool(
        text.startswith(("open ", "show ", "view ", "launch "))
        or any(token in text for token in (" open ", " open it", " open the", " show ", " view ", " launch "))
    )


def reset_circuit_breakers() -> None:
    """Reset all circuit breakers — useful at the start of a new conversation."""
    _circuit_breaker.reset()
