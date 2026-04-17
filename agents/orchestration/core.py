"""Primary orchestrator implementation."""

from __future__ import annotations

import copy
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm import LLMRuntime, call_chat_once
from tools.engine import TOOL_SPECS

from ..specialists import SPECIALIST_MAP, SpecialistAgent
from ..supervisor import SupervisorAgent
from .completion import (
    MAX_COMPLETION_ATTEMPTS,
    build_retry_context,
    build_retry_user_text,
    collect_verification_signals,
    context_has_completed_open,
    reply_looks_like_failure,
    result_has_objective_open_success,
    review_completion_attempt,
    task_requests_open,
    verification_has_any_objective_success,
)
from .shared import (
    _ESCALATION_MATRIX,
    _MAX_HANDOFF_STEPS,
    _SYNTHESIZER_PROMPT,
    append_follow_up_hint,
    build_prior_context_block,
    classify_interaction,
    extract_artifacts,
    extract_clean_history,
    extract_file_path,
    merge_artifacts,
)
from .specialist_runner import run_specialist
from .workflows import (
    is_specialist_capability_query,
    run_capability_inventory,
    run_general,
    run_planned_task,
    run_specialist_capability_query,
)


def _display_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return Path(text).name or text
    except Exception:
        return text


def _join_brief(items: List[str], limit: int = 2) -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return ""
    picked = values[:limit]
    if len(values) <= limit:
        return ", ".join(picked)
    return f"{', '.join(picked)} +{len(values) - limit} more"


def _fallback_verified_completion_reply(verification: Dict[str, Any]) -> str:
    opened = [_display_name(path_text) for path_text in verification.get("opened_files", [])]
    launched = [_display_name(app_name) for app_name in verification.get("launched_apps", [])]
    existing = [_display_name(path_text) for path_text in verification.get("existing_files", [])]
    parts: List[str] = []
    if opened:
        parts.append(f"opened {_join_brief(opened)}")
    if launched:
        parts.append(f"launched {_join_brief(launched)}")
    if existing and not parts:
        parts.append(f"saved {_join_brief(existing)}")
    if not parts:
        return "Done."
    return f"Done - {' and '.join(parts)}."


def _reply_looks_like_raw_receipt(reply: str) -> bool:
    text = str(reply or "").strip()
    if not text:
        return False
    first_line = text.splitlines()[0].strip().lower()
    return first_line in {"[opened]", "[already_open]", "[launched]"} or first_line.startswith(
        ("file_path:", "opened_file:", "launched_app:")
    )


def _history_reply_with_artifacts(reply: str, verification: Dict[str, Any]) -> str:
    lines = [str(reply or "").strip()]
    seen: set[str] = set()

    for prefix, key in (
        ("FILE_PATH", "existing_files"),
        ("OPENED_FILE", "opened_files"),
        ("LAUNCHED_APP", "launched_apps"),
    ):
        for value in verification.get(key, [])[:4]:
            text = str(value or "").strip()
            if not text:
                continue
            line = f"{prefix}: {text}"
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
    return "\n".join(line for line in lines if line).strip()


def _reply_conflicts_with_verification(reply: str, verification: Dict[str, Any]) -> bool:
    text = str(reply or "").strip().lower()
    if not text:
        return False
    verified_names = {
        _display_name(item).strip().lower()
        for key in ("opened_files", "existing_files", "launched_apps")
        for item in verification.get(key, [])
        if _display_name(item).strip()
    }
    if not verified_names:
        return False
    mentioned_file_names = {
        match.group(0).strip().lower()
        for match in re.finditer(r"\b[\w.\-]+\.[A-Za-z0-9]{1,8}\b", text)
    }
    if mentioned_file_names and mentioned_file_names.isdisjoint(verified_names):
        return True
    return False


class Orchestrator:
    """Multi-agent orchestrator using Supervisor + specialists + synthesizer."""

    def __init__(self, runtime: LLMRuntime, workspace_root: Path) -> None:
        self.runtime = runtime
        self.workspace_root = workspace_root
        self.supervisor = SupervisorAgent(runtime)
        try:
            from memory import get_memory_manager

            get_memory_manager(workspace_root).attach_runtime(runtime)
        except Exception:
            pass

    def run(self, user_text: str, messages: List[Dict[str, Any]]) -> str:
        start_ts = time.time()
        print(f"[Orchestrator.run] ENTRY: user_text='{user_text[:80]}'", flush=True)
        final_attempt: Dict[str, Any] = {"reply": "", "agent_names": [], "results": []}
        prior_attempts: List[Dict[str, Any]] = []
        retry_context: Optional[str] = None
        effective_user_text = user_text
        final_review: Dict[str, Any] = {"status": "failed", "verification": {}}

        for attempt_index in range(1, MAX_COMPLETION_ATTEMPTS + 1):
            print(
                f"[CompletionLoop] attempt {attempt_index}/{MAX_COMPLETION_ATTEMPTS} for: {user_text[:60]}",
                flush=True,
            )
            scratch_messages = copy.deepcopy(messages)
            attempt = self._execute_once(
                effective_user_text,
                scratch_messages,
                original_user_text=user_text,
                loop_context=retry_context,
            )
            final_attempt = attempt
            review = review_completion_attempt(
                self.runtime,
                user_text,
                attempt.get("reply", ""),
                attempt.get("results", []),
                attempt_index,
                prior_attempts,
            )
            final_review = review
            prior_attempts.append(
                {
                    "attempt": attempt_index,
                    "reply": attempt.get("reply", ""),
                    "agent_names": attempt.get("agent_names", []),
                    "review": review,
                }
            )
            if review.get("status") == "complete" or attempt_index >= MAX_COMPLETION_ATTEMPTS:
                break
            retry_context = build_retry_context(
                user_text,
                attempt_index,
                attempt.get("reply", ""),
                review,
            )
            effective_user_text = build_retry_user_text(user_text, review)

        final_reply = str(final_attempt.get("reply", "") or "").strip()
        agent_names = list(final_attempt.get("agent_names", []) or [])
        final_verification = final_review.get("verification", {}) if isinstance(final_review, dict) else {}
        if (
            final_review.get("status") == "complete"
            and verification_has_any_objective_success(final_verification)
            and (reply_looks_like_failure(final_reply) or _reply_conflicts_with_verification(final_reply, final_verification))
        ):
            repaired = ""
            if final_attempt.get("results"):
                repaired = self._synthesize(user_text, list(final_attempt.get("results", []) or []))
            final_reply = (
                repaired
                if repaired
                and not reply_looks_like_failure(repaired)
                and not _reply_conflicts_with_verification(repaired, final_verification)
                else _fallback_verified_completion_reply(final_verification)
            )
        elif (
            final_review.get("status") == "complete"
            and verification_has_any_objective_success(final_verification)
            and _reply_looks_like_raw_receipt(final_reply)
        ):
            repaired = ""
            if final_attempt.get("results"):
                repaired = self._synthesize(user_text, list(final_attempt.get("results", []) or []))
            final_reply = (
                repaired
                if repaired
                and not _reply_looks_like_raw_receipt(repaired)
                and not reply_looks_like_failure(repaired)
                else _fallback_verified_completion_reply(final_verification)
            )
        final_reply = append_follow_up_hint(final_reply, user_text, self.workspace_root)
        history_reply = _history_reply_with_artifacts(final_reply, final_verification)
        self._append_to_messages(messages, user_text, history_reply)
        self._save_reply(final_reply)
        self._record_behavior(agent_names, user_text, start_ts)
        return final_reply

    def _execute_once(
        self,
        user_text: str,
        messages: List[Dict[str, Any]],
        original_user_text: Optional[str] = None,
        loop_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        visible_user_text = original_user_text or user_text
        print(f"[Orchestrator] Starting Supervisor routing for: {user_text[:50]}...", flush=True)
        try:
            from memory import get_memory_manager

            get_memory_manager(self.workspace_root).inject_into_messages(messages, user_query=visible_user_text)
        except Exception:
            pass
        interaction_id = None
        feedback_engine = None
        try:
            from tools.feedback_engine import get_instance as get_feedback_engine

            feedback_engine = get_feedback_engine()
            if feedback_engine is not None:
                interaction_id = feedback_engine.new_interaction()
        except Exception:
            pass

        supervisor_history = extract_clean_history(messages, max_turns=4)
        if loop_context:
            supervisor_history.append({"role": "assistant", "content": loop_context})
        routing = self.supervisor.route(user_text, history=supervisor_history)
        print(f"[Supervisor] Routed to: {routing.get('agents', [])} (parallel={routing.get('parallel', False)})", flush=True)
        agent_names: List[str] = routing["agents"]
        parallel: bool = routing["parallel"]
        reasoning: str = routing.get("reasoning", "")
        confidence: float = routing.get("confidence", 1.0)
        if confidence < 0.65 and len(agent_names) == 1:
            fallback_agent = {
                "FileAgent": "TerminalAgent",
                "WebAgent": "GeneralAgent",
                "SystemAgent": "TerminalAgent",
                "CodeAgent": "TerminalAgent",
                "MusicAgent": "GeneralAgent",
            }.get(agent_names[0])
            if fallback_agent:
                agent_names.append(fallback_agent)
                print(f"[DualRouting] Low confidence ({confidence:.2f}) - adding fallback: {fallback_agent}", flush=True)
        if interaction_id:
            try:
                feedback_engine.record_routing(interaction_id, agent_names, reasoning, visible_user_text)
            except Exception:
                pass

        if agent_names == ["GeneralAgent"]:
            reply = run_general(self.runtime, self.workspace_root, user_text, messages, routing_reason=reasoning)
            return {
                "reply": reply,
                "agent_names": agent_names,
                "results": [{"agent": "GeneralAgent", "ok": True, "reply": reply, "artifacts": merge_artifacts(reply)}],
                "reasoning": reasoning,
            }
        if agent_names == ["PlannerAgent"]:
            reply = run_planned_task(self.runtime, self.workspace_root, user_text, messages, self._append_to_messages, self._synthesize)
            return {
                "reply": reply,
                "agent_names": agent_names,
                "results": [{"agent": "PlannerAgent", "ok": True, "reply": reply, "artifacts": merge_artifacts(reply)}],
                "reasoning": reasoning,
            }

        specialists = [SPECIALIST_MAP[name] for name in agent_names if name in SPECIALIST_MAP]
        if not specialists:
            reply = run_general(self.runtime, self.workspace_root, user_text, messages, routing_reason=reasoning)
            return {
                "reply": reply,
                "agent_names": ["GeneralAgent"],
                "results": [{"agent": "GeneralAgent", "ok": True, "reply": reply, "artifacts": merge_artifacts(reply)}],
                "reasoning": reasoning,
            }
        if len(specialists) == 1 and (
            "capabilities" in reasoning.lower()
            or is_specialist_capability_query(self.runtime, specialists[0], user_text, supervisor_history, reasoning)
        ):
            reply = run_specialist_capability_query(self.runtime, specialists[0], user_text)
            return {
                "reply": reply,
                "agent_names": agent_names,
                "results": [{"agent": specialists[0].name, "ok": True, "reply": reply, "artifacts": merge_artifacts(reply)}],
                "reasoning": reasoning,
            }

        producers = {"ContentAgent", "FileAgent", "WebAgent"}
        consumers = {"FileAgent", "SystemAgent", "CodeAgent"}
        if (producers & set(agent_names)) and (consumers & set(agent_names)):
            parallel = False

        self.messages = messages
        results: List[Dict[str, Any]]
        used_parallel = parallel and len(specialists) > 1
        if used_parallel:
            results = self._fan_out_parallel(specialists, user_text, loop_context=loop_context)
        else:
            results = self._run_sequential_with_context(specialists, user_text, loop_context=loop_context)
        extra_results: List[Dict[str, Any]] = []
        if used_parallel:
            extra_results = self._run_handoff_chain(
                results,
                extract_clean_history(messages, max_turns=6),
                loop_context=loop_context,
            )
        if extra_results:
            results.extend(extra_results)

        reply = results[0].get("reply", "") if len(results) == 1 else self._synthesize(visible_user_text, results)
        verification = collect_verification_signals(results)
        if verification_has_any_objective_success(verification) and reply_looks_like_failure(reply):
            repaired = self._synthesize(visible_user_text, results)
            if repaired and not reply_looks_like_failure(repaired):
                reply = repaired
            else:
                reply = _fallback_verified_completion_reply(verification)
        return {
            "reply": reply,
            "agent_names": agent_names,
            "results": results,
            "reasoning": reasoning,
        }

    def _run_sequential_with_context(
        self,
        specialists: List[SpecialistAgent],
        task: str,
        loop_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        prior_context_block: Optional[str] = loop_context
        conversation_history = extract_clean_history(self.messages, max_turns=6) if hasattr(self, "messages") else []
        if loop_context:
            conversation_history.append({"role": "assistant", "content": loop_context})
        queue: List[tuple[SpecialistAgent, Optional[str]]] = [(specialist, None) for specialist in specialists]
        seen_handoffs: set[tuple[str, str]] = set()
        index = 0
        while index < len(queue):
            specialist, task_override = queue[index]
            index += 1
            if (
                specialist.name == "SystemAgent"
                and context_has_completed_open(prior_context_block)
                and task_requests_open(task_override or task)
            ):
                print("[CompletionLoop] Skipping generic SystemAgent open stage; already completed.", flush=True)
                continue
            result = run_specialist(
                specialist,
                task_override or task,
                self.runtime,
                self.workspace_root,
                prior_context=prior_context_block,
                conversation_history=conversation_history,
            )
            reply = result.get("reply", "")
            reply_lower = reply.lower() if reply else ""
            artifacts = merge_artifacts(reply, result.get("artifacts"))
            has_existing_file = any(
                Path(path_text).expanduser().exists()
                for path_text in artifacts.get("files", [])
                if str(path_text).strip()
            )
            has_objective_success = (
                result_has_objective_open_success(result)
                or (has_existing_file and not task_requests_open(task_override or task))
            )
            agent_failed = (
                not has_objective_success
                and (
                    not result.get("ok", True)
                    or reply.startswith("[Error]")
                    or "[FAILED]" in reply
                    or "server error" in reply_lower
                    or "Tool not found" in reply
                    or "Permission denied" in reply
                    or "timed out" in reply_lower
                    or (len(reply.strip()) < 15 and not reply.strip().startswith("Done"))
                    or "i can't" in reply_lower
                    or "i cannot" in reply_lower
                    or "i'm unable" in reply_lower
                    or "i am unable" in reply_lower
                    or "not possible for me" in reply_lower
                    or "beyond my capabilities" in reply_lower
                    or "outside my scope" in reply_lower
                    or "as an ai" in reply_lower
                    or "i don't have the ability" in reply_lower
                    or "i don't have access" in reply_lower
                )
            )
            if agent_failed and specialist.name in _ESCALATION_MATRIX:
                backup_name, failure_note = _ESCALATION_MATRIX[specialist.name]
                backup_specialist = SPECIALIST_MAP.get(backup_name)
                if backup_specialist:
                    print(f"[Hydra] [WARN] {specialist.name} failed -> rerouting to {backup_name}", flush=True)
                    post_mortem = (
                        "SYSTEM ALERT - HYDRA REROUTE:\n"
                        f"Original request: {task}\n"
                        f"{specialist.name} already tried and failed with: {reply[:300]}\n\n"
                        f"BACKUP MISSION: {failure_note}\n"
                        "Achieve the SAME goal using YOUR tools. Do not repeat the failed approach."
                    )
                    backup_result = run_specialist(
                        backup_specialist,
                        task,
                        self.runtime,
                        self.workspace_root,
                        prior_context=post_mortem,
                        conversation_history=conversation_history,
                    )
                    backup_artifacts = merge_artifacts(backup_result.get("reply", ""), backup_result.get("artifacts"))
                    merged_artifacts = {
                        "files": [],
                        "urls": [],
                        "handoffs": [],
                        "opened_files": [],
                        "launched_apps": [],
                    }
                    for source in (artifacts, backup_artifacts):
                        for key in merged_artifacts:
                            for item in source.get(key, []):
                                if item and item not in merged_artifacts[key]:
                                    merged_artifacts[key].append(item)
                    backup_result["artifacts"] = merged_artifacts
                    backup_result["rerouted_from"] = specialist.name
                    self._write_audit(specialist.name, {**result, "hydra_rerouted_to": backup_name})
                    self._write_audit(backup_name, {**backup_result, "hydra_backup": True})
                    result = backup_result
                    reply = result.get("reply", "")
            results.append(result)
            if reply:
                artifacts = merge_artifacts(reply, result.get("artifacts"))
                prior_context_block = build_prior_context_block(result.get("agent", specialist.name), reply, artifacts)
                if loop_context:
                    prior_context_block = f"{loop_context}\n\n{prior_context_block}"
                for handoff in artifacts.get("handoffs", []):
                    parsed = self._parse_handoff(handoff)
                    if not parsed:
                        continue
                    agent_name, handoff_task = parsed
                    key = (agent_name, handoff_task.strip().lower())
                    if not handoff_task or key in seen_handoffs or len(seen_handoffs) >= _MAX_HANDOFF_STEPS:
                        continue
                    next_specialist = SPECIALIST_MAP.get(agent_name)
                    if not next_specialist:
                        continue
                    replaced_existing = False
                    for queue_index in range(index, len(queue)):
                        queued_specialist, queued_task = queue[queue_index]
                        if queued_specialist.name == agent_name and queued_task is None:
                            queue[queue_index] = (queued_specialist, handoff_task)
                            replaced_existing = True
                            break
                    seen_handoffs.add(key)
                    if not replaced_existing:
                        queue.append((next_specialist, handoff_task))
            self._write_audit(specialist.name, result)
        return results

    def _run_handoff_chain(
        self,
        results: List[Dict[str, Any]],
        conversation_history: List[Dict[str, Any]],
        loop_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        extra: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for result in results:
            reply = result.get("reply", "") or ""
            if not reply:
                continue
            artifacts = merge_artifacts(reply, result.get("artifacts"))
            if not artifacts.get("handoffs"):
                continue
            prior_context_block = build_prior_context_block(result.get("agent", "Agent"), reply, artifacts)
            if loop_context:
                prior_context_block = f"{loop_context}\n\n{prior_context_block}"
            for handoff in artifacts.get("handoffs", []):
                parsed = self._parse_handoff(handoff)
                if not parsed:
                    continue
                agent_name, handoff_task = parsed
                key = (agent_name, handoff_task.strip().lower())
                if not handoff_task or key in seen or len(seen) >= _MAX_HANDOFF_STEPS:
                    continue
                next_specialist = SPECIALIST_MAP.get(agent_name)
                if not next_specialist:
                    continue
                seen.add(key)
                extra.append(
                    run_specialist(
                        next_specialist,
                        handoff_task,
                        self.runtime,
                        self.workspace_root,
                        prior_context=prior_context_block,
                        conversation_history=conversation_history,
                    )
                )
        return extra

    @staticmethod
    def _parse_handoff(handoff: str) -> Optional[tuple[str, str]]:
        match = re.search(r"(SUGGEST_NEXT|HANDOFF):\s*(\w+Agent)\s*→\s*(.+)$", handoff)
        if not match:
            return None
        return match.group(2).strip(), match.group(3).strip()

    def _write_audit(self, agent_name: str, result: Dict[str, Any]) -> None:
        try:
            audit_path = self.workspace_root / ".ankita" / "audit.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": time.time(),
                "agent": agent_name,
                "reply_preview": (result.get("reply", "") or "")[:120],
                "tools_used": result.get("tools_used", []),
                "artifacts": merge_artifacts(result.get("reply", "") or "", result.get("artifacts")),
                "content_payload_valid": result.get("content_payload_valid"),
                "content_payload_errors": result.get("content_payload_errors", []),
                "content_payload_repaired": result.get("content_payload_repaired"),
            }
            with audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _fan_out_parallel(
        self,
        specialists: List[SpecialistAgent],
        task: str,
        loop_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results: List[Optional[Dict[str, Any]]] = [None] * len(specialists)
        step_timeout = 120
        conversation_history = extract_clean_history(self.messages, max_turns=6) if hasattr(self, "messages") else []
        if loop_context:
            conversation_history.append({"role": "assistant", "content": loop_context})
        with ThreadPoolExecutor(max_workers=min(len(specialists), 4)) as executor:
            future_to_index = {
                executor.submit(
                    run_specialist,
                    specialist,
                    task,
                    self.runtime,
                    self.workspace_root,
                    prior_context=loop_context,
                    conversation_history=conversation_history,
                ): index
                for index, specialist in enumerate(specialists)
            }
            for future in as_completed(future_to_index, timeout=step_timeout * len(specialists)):
                index = future_to_index[future]
                try:
                    results[index] = future.result(timeout=step_timeout)
                except TimeoutError:
                    results[index] = {
                        "agent": specialists[index].name,
                        "ok": False,
                        "reply": f"[Timeout] Agent exceeded {step_timeout}s limit",
                    }
                except Exception as err:
                    results[index] = {"agent": specialists[index].name, "ok": False, "reply": f"[Error] {err}"}
        return [result for result in results if result is not None]

    def _synthesize(self, user_text: str, results: List[Dict[str, Any]]) -> str:
        parts = []
        for result in results:
            agent = result.get("agent", "Agent")
            reply = result.get("reply", "")
            if reply:
                parts.append(f"[{agent}]: {reply}")
        combined = "\n\n".join(parts)
        verification = collect_verification_signals(results)
        synth_messages = [
            {
                "role": "system",
                "content": (
                    _SYNTHESIZER_PROMPT
                    + "\n7. Trust objective verification signals over any individual agent prose."
                    + "\n8. If verification shows opened_files, launched_apps, or existing_files, do not describe the task as failed unless verification itself shows no success."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original request: {user_text}\n\n"
                    f"Verification signals:\n{json.dumps(verification, ensure_ascii=False)}\n\n"
                    f"Agent outputs:\n{combined}"
                ),
            },
        ]
        try:
            response = call_chat_once(self.runtime, synth_messages, tools=None, max_tokens=self.runtime.max_tokens)
            candidate = (response.get("content") or "").strip()
            if verification_has_any_objective_success(verification) and reply_looks_like_failure(candidate):
                return _fallback_verified_completion_reply(verification)
            return candidate or combined
        except Exception:
            if verification_has_any_objective_success(verification):
                return _fallback_verified_completion_reply(verification)
            return combined

    @staticmethod
    def _extract_file_path(text: str) -> Optional[str]:
        return extract_file_path(text)

    def _run_general(self, user_text: str, messages: List[Dict[str, Any]], routing_reason: str = "") -> str:
        return run_general(self.runtime, self.workspace_root, user_text, messages, routing_reason=routing_reason)

    def _run_specialist_capability_query(self, specialist: SpecialistAgent, user_text: str) -> str:
        return run_specialist_capability_query(self.runtime, specialist, user_text)

    def _run_capability_inventory(
        self,
        user_text: str,
        tool_specs: List[Dict[str, Any]],
        scope_label: str,
    ) -> str:
        return run_capability_inventory(self.runtime, user_text, tool_specs, scope_label)

    def _run_planned_task(self, user_text: str, messages: List[Dict[str, Any]]) -> str:
        return run_planned_task(
            self.runtime,
            self.workspace_root,
            user_text,
            messages,
            self._append_to_messages,
            self._synthesize,
        )

    def _append_to_messages(self, messages: List[Dict[str, Any]], user_text: str, reply: str) -> None:
        if not messages or messages[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": reply})

    def _save_reply(self, reply: str) -> None:
        try:
            from memory import get_memory_manager

            get_memory_manager(self.workspace_root).save("assistant", reply, interface="orchestrator")
        except Exception:
            pass

    def _record_behavior(self, agent_names: List[str], user_text: str, start_ts: float) -> None:
        try:
            from tools.behavioral_pattern_learner import BehavioralPatternLearner

            BehavioralPatternLearner(self.workspace_root).record_fingerprint(
                interaction_type=classify_interaction(agent_names, user_text),
                duration_sec=int(time.time() - start_ts),
                tools_used=agent_names,
                context=user_text[:120],
            )
        except Exception:
            pass
