"""Higher-level orchestration workflows."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

from llm import LLMRuntime, call_chat_once
from llm.agent_router import get_agent_runtime
from tools.engine import TOOL_SPECS

from ..specialists import SPECIALIST_MAP, SpecialistAgent
from .shared import (
    build_prior_context_block,
    evaluate_condition,
    extract_artifacts,
    extract_clean_history,
)
from .specialist_runner import run_specialist


_CAPABILITY_REASON_RE = re.compile(
    r"(?i)\b("
    r"capabilit(?:y|ies)"
    r"|available\s+tools"
    r"|overall\s+(?:abilities|capabilities)"
    r"|what\s+else\s+can\s+you\s+do"
    r"|what\s+tools\s+do(?:es)?\s+(?:you|ankita)\s+have"
    r")\b"
)


def _is_capability_routing_reason(reasoning: str) -> bool:
    return bool(_CAPABILITY_REASON_RE.search(str(reasoning or "").strip()))


def run_capability_inventory(
    runtime: LLMRuntime,
    user_text: str,
    tool_specs: List[Dict[str, Any]],
    scope_label: str,
) -> str:
    payload = []
    for spec in tool_specs:
        fn = spec.get("function", {})
        payload.append({"name": fn.get("name", ""), "description": fn.get("description", "")})
    messages = [
        {
            "role": "system",
            "content": (
                "You are summarizing capabilities from a real tool registry. "
                "Use ONLY the provided tools and descriptions. "
                "Do not invent abilities that are not supported by those tools. "
                "Group related capabilities together, keep it concise, and avoid slang. "
                "Mention representative tool names where useful."
            ),
        },
        {"role": "user", "content": json.dumps({"scope": scope_label, "question": user_text, "tools": payload}, ensure_ascii=False)},
    ]
    try:
        response = call_chat_once(runtime, messages, tools=None, max_tokens=420)
        result = (response.get("content") or "").strip()
        if result:
            return result
    except Exception as err:
        print(f"[Orchestrator.run_capability_inventory] Error: {err}", flush=True)
    names = ", ".join(sorted(item["name"] for item in payload if item.get("name")))
    return f"Available tools in {scope_label}: {names}"


_SPECIALIST_CAPABILITY_PROMPT = """You classify whether the user is asking about a specialist's capabilities.

Return JSON only:
{"capability_query": true|false, "reasoning":"..."}

Interpretation rules:
- True ONLY when the latest user message explicitly asks what the specialist/domain can do, what else it can do in that domain, or asks for its available tools/capabilities/options.
- False when the user is asking the specialist to perform an action right now.
- Prioritize the latest user message over recent history.
- If the latest user message is an imperative command or direct action request, classify false even if recent history discussed capabilities.
- If the user names a concrete subject, target, topic, file, app, website, product, comparison pair, or search target, that strongly suggests a real task, not a capability question.
- If the latest message does NOT contain explicit meta-language such as abilities, tools, capabilities, options, or \"what else can you do\", classify false.
- Be careful with domain-scoped questions like:
  - "what can you do with music"
  - "what else can you do in figma"
  - "what can you do with files"
  These are capability queries, not execution requests.
- Negative examples (classify false):
  - "take a screenshot and open it"
  - "generate an image of a red circle and open it"
  - "open calculator"
  - "what is my battery status"
  - "compare Python vs JavaScript"
  - "search the web for python official docs"
  - "find reddit opinions about React"
  - "fact check this claim"
  - "get me the latest AI news"
- Positive examples (classify true):
  - "what can you do with music"
  - "what else can you do with files"
  - "show me your figma capabilities"
  - "what tools does WebAgent have"
- If unsure, prefer true only when the request is clearly asking about abilities, options, or available actions.
"""


_GLOBAL_CAPABILITY_PROMPT = """You classify whether the user is asking about ANKITA's overall capabilities.

Return JSON only:
{"global_capability_query": true|false, "reasoning":"..."}

Rules:
- True when the user is asking what ANKITA can do overall, what else it can do, what tools it has, or asking for available capabilities/options.
- Use recent history when the latest message is short or vague.
- Messages like "what else", "anything else", "more", and "what can you do" are often capability queries when they follow a discussion about features or actions.
- False when the user is asking ANKITA to perform a task right now instead of describing capabilities.
- Prioritize the latest user message over recent history.
- Negative examples (classify false):
  - "take a screenshot and open it"
  - "generate an image of a red circle and open it"
  - "open calculator"
  - "what is my battery status"
- Positive examples (classify true):
  - "what can you do"
  - "what else"
  - "show your capabilities"
"""


_GENERAL_DIRECT_REPLY_PROMPT = """You decide whether ANKITA can answer directly without using tools.

Return JSON only:
{"direct_reply_ok": true|false, "reasoning":"..."}

Rules:
- True only for pure conversation, explanation, opinion, brainstorming, or general discussion.
- False for requests that ask ANKITA to do something in the world: save, open, create files, run commands, search live web, take screenshots, generate images, control the system, or perform multi-step execution.
- False when the reply would otherwise pretend that an action was completed without tool use.
- If unsure, prefer false.
"""


def is_global_capability_query(
    runtime: LLMRuntime,
    user_text: str,
    history: List[Dict[str, Any]],
) -> bool:
    payload = {
        "latest_user_message": user_text,
        "recent_history": history[-4:],
    }
    try:
        response = call_chat_once(
            runtime,
            [
                {"role": "system", "content": _GLOBAL_CAPABILITY_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            tools=None,
            max_tokens=120,
        )
        content = (response.get("content") or "").strip()
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            content = match.group(0)
        parsed = json.loads(content)
        return bool(parsed.get("global_capability_query", False))
    except Exception as err:
        print(f"[Orchestrator.is_global_capability_query] Error: {err}", flush=True)
        return False


def can_answer_directly(
    runtime: LLMRuntime,
    user_text: str,
    history: List[Dict[str, Any]],
) -> bool:
    payload = {
        "latest_user_message": user_text,
        "recent_history": history[-4:],
    }
    try:
        response = call_chat_once(
            runtime,
            [
                {"role": "system", "content": _GENERAL_DIRECT_REPLY_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            tools=None,
            max_tokens=120,
        )
        content = (response.get("content") or "").strip()
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            content = match.group(0)
        parsed = json.loads(content)
        return bool(parsed.get("direct_reply_ok", False))
    except Exception as err:
        print(f"[Orchestrator.can_answer_directly] Error: {err}", flush=True)
        return False


def is_specialist_capability_query(
    runtime: LLMRuntime,
    specialist: SpecialistAgent,
    user_text: str,
    history: List[Dict[str, Any]],
    routing_reason: str = "",
) -> bool:
    meta_language = re.search(
        r"\b(what can you do|what else can you do|capabilit(?:y|ies)|what tools|tools do you have|available actions|available options|abilities)\b",
        user_text.lower(),
    )
    if not meta_language:
        return False
    payload = {
        "specialist": specialist.name,
        "routing_reason": routing_reason,
        "latest_user_message": user_text,
        "recent_history": history[-4:],
    }
    try:
        response = call_chat_once(
            runtime,
            [
                {"role": "system", "content": _SPECIALIST_CAPABILITY_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            tools=None,
            max_tokens=120,
        )
        content = (response.get("content") or "").strip()
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            content = match.group(0)
        parsed = json.loads(content)
        return bool(parsed.get("capability_query", False))
    except Exception as err:
        print(f"[Orchestrator.is_specialist_capability_query] Error: {err}", flush=True)
        return False


def run_specialist_capability_query(runtime: LLMRuntime, specialist: SpecialistAgent, user_text: str) -> str:
    return run_capability_inventory(runtime, user_text, specialist.tool_specs, specialist.name)


def run_general(
    runtime: LLMRuntime,
    workspace_root: Path,
    user_text: str,
    messages: List[Dict[str, Any]],
    routing_reason: str = "",
) -> str:
    print(f"[Orchestrator.run_general] Starting with user_text: {user_text[:100]}...", flush=True)
    history = [msg for msg in messages if msg.get("role") in {"user", "assistant"}]
    capability_mode = (
        _is_capability_routing_reason(routing_reason)
        or is_global_capability_query(runtime, user_text, history)
    )
    if capability_mode:
        return run_capability_inventory(runtime, user_text, TOOL_SPECS, "A.N.K.I.T.A overall")
    if can_answer_directly(runtime, user_text, history):
        direct_messages = list(messages)
        direct_messages.append({"role": "user", "content": user_text})
        try:
            response = call_chat_once(runtime, direct_messages, tools=None, max_tokens=240)
            result = (response.get("content") or "").strip()
            if result:
                try:
                    from memory import get_memory_manager

                    get_memory_manager(workspace_root).save("assistant", result, interface="orchestrator")
                except Exception:
                    pass
                print("[Orchestrator.run_general] Completed direct LLM reply", flush=True)
                return result
        except Exception as err:
            print(f"[Orchestrator.run_general] Direct LLM path failed: {err}", flush=True)
    from agent_runtime import AgentRuntime

    agent = AgentRuntime(runtime=runtime, workspace_root=workspace_root)
    messages.append({"role": "user", "content": user_text})
    try:
        result = agent.run_turn(messages, tools=TOOL_SPECS)
        try:
            from memory import get_memory_manager

            get_memory_manager(workspace_root).save("assistant", result, interface="orchestrator")
        except Exception:
            pass
        print("[Orchestrator.run_general] Completed successfully", flush=True)
        return result
    except Exception as err:
        print(f"[Orchestrator.run_general] Error: {err}", flush=True)
        if messages and messages[-1].get("role") == "user":
            messages.pop()
        return f"[Error] {err}"


def run_planned_task(
    runtime: LLMRuntime,
    workspace_root: Path,
    user_text: str,
    messages: List[Dict[str, Any]],
    append_to_messages: Callable[[List[Dict[str, Any]], str, str], None],
    synthesize: Callable[[str, List[Dict[str, Any]]], str],
) -> str:
    planner_specialist = SPECIALIST_MAP.get("PlannerAgent")
    if not planner_specialist:
        return "❌ PlannerAgent not available."
    conversation_history = extract_clean_history(messages, max_turns=6)
    planner_messages = planner_specialist.make_messages(user_text, history=conversation_history)
    try:
        planner_runtime = get_agent_runtime("PlannerAgent", runtime)
        response = call_chat_once(planner_runtime, planner_messages, tools=None, max_tokens=1500)
        plan_content = (response.get("content") or "").strip()
    except Exception as err:
        return f"❌ PlannerAgent failed: {err}"
    try:
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", plan_content)
        if json_match:
            plan_json_str = json_match.group(1).strip()
        else:
            brace_match = re.search(r"\{[\s\S]*\}", plan_content)
            plan_json_str = brace_match.group(0) if brace_match else plan_content
        plan = json.loads(plan_json_str)
        goal = plan.get("goal", "")
        steps = plan.get("steps", [])
        if not steps:
            return "❌ PlannerAgent produced an empty plan."
    except json.JSONDecodeError as err:
        return f"❌ Failed to parse plan JSON: {err}\n\nPlan output:\n{plan_content[:500]}"
    audit_path = workspace_root / ".ankita" / "audit.jsonl"
    plan_entry = {
        "type": "plan",
        "ts": time.time(),
        "user_request": user_text,
        "goal": goal,
        "plan": plan,
        "steps_count": len(steps),
    }
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(plan_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
    preview_lines = [f"📋 Plan: {len(steps)} steps"]
    for step in steps:
        preview_lines.append(f"  {step.get('id', '?')}. {step.get('agent', '?')} → {step.get('task', '')[:60]}...")
    preview_text = "\n".join(preview_lines)
    print(f"\n{preview_text}\n", flush=True)

    step_results: Dict[int, Dict[str, Any]] = {}
    steps_executed = 0
    steps_skipped = 0
    start_time = time.time()
    for step in steps:
        step_id = step.get("id")
        agent_name = step.get("agent")
        task = step.get("task")
        depends_on = step.get("depends_on", [])
        condition = step.get("condition")
        for dep_id in depends_on:
            if dep_id not in step_results:
                return f"❌ Step {step_id} depends on step {dep_id} which hasn't completed yet."
            if not step_results[dep_id].get("ok", False):
                return f"❌ Step {step_id} depends on step {dep_id} which failed."
        if condition and not evaluate_condition(condition, step_results, depends_on):
            print(f"Step {step_id}/{len(steps)} — [CONDITION: {condition} ❌] — SKIPPED", flush=True)
            steps_skipped += 1
            continue
        print(f"Step {step_id}/{len(steps)} — {agent_name}: {str(task)[:60]}...", flush=True)
        specialist = SPECIALIST_MAP.get(agent_name)
        if not specialist:
            return f"❌ Agent {agent_name} not found for step {step_id}."
        prior_context_parts = []
        for dep_id in depends_on:
            dep_result = step_results.get(dep_id, {})
            dep_reply = dep_result.get("reply", "")
            if dep_reply:
                prior_context_parts.append(
                    build_prior_context_block(dep_result.get("agent", "PreviousAgent"), dep_reply, extract_artifacts(dep_reply))
                )
        prior_context = "\n\n".join(prior_context_parts) if prior_context_parts else None
        result = run_specialist(
            specialist,
            task,
            runtime,
            workspace_root,
            prior_context=prior_context,
            conversation_history=conversation_history,
        )
        step_results[step_id] = result
        steps_executed += 1
        preview = (result.get("reply", "") or "")[:80]
        print(f"  {'✅' if result.get('ok', True) else '❌'} {preview}", flush=True)
        if not result.get("ok", True):
            return f"❌ Step {step_id} failed: {result.get('reply', 'Unknown error')}"

    try:
        plan_entry["steps_executed"] = steps_executed
        plan_entry["steps_skipped"] = steps_skipped
        plan_entry["total_time_ms"] = int((time.time() - start_time) * 1000)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(plan_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
    all_results = list(step_results.values())
    if len(all_results) == 1:
        reply = all_results[0].get("reply", "")
        append_to_messages(messages, user_text, reply)
        return reply
    reply = synthesize(user_text, all_results)
    append_to_messages(messages, user_text, reply)
    return reply
