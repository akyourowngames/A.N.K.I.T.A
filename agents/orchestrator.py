"""
Orchestrator for A.N.K.I.T.A multi-agent system.

Implements the Fan-Out / Fan-In parallel execution pattern:
  1. Supervisor routes request → list of specialist agents
  2. Fan-Out: dispatch agents concurrently (ThreadPoolExecutor)
  3. Fan-In: collect results, synthesize a single cohesive response

Falls back to the base AgentRuntime if anything goes wrong.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm import LLMRuntime, call_chat_once
from llm.client import build_vision_runtime_from_env, call_chat_with_image
from tools.engine import execute_tool_call, TOOL_SPECS, compact_messages
from tools.memory_ops import format_memory_block

from .supervisor import SupervisorAgent
from .specialists import SPECIALIST_MAP, SpecialistAgent

_MAX_TOOL_STEPS = 20

# ─────────────────────────────────────────────────────────────────────────────
# HYDRA PROTOCOL — Escalation Matrix 🐉
# Maps (primary_agent) → (backup_agent_name, context_note_for_backup)
# ─────────────────────────────────────────────────────────────────────────────
_ESCALATION_MATRIX: Dict[str, tuple] = {
    "SystemAgent":  ("TerminalAgent",
                     "SystemAgent tried and FAILED. Use raw PowerShell/CMD via execute_shell to achieve the same goal. "
                     "Do NOT repeat what SystemAgent did. Use terminal commands directly."),
    "WebAgent":     ("GeneralAgent",
                     "WebAgent tried and FAILED (search API down or blocked). "
                     "Use your internal LLM knowledge to answer as accurately as possible. "
                     "State clearly that you are using knowledge cutoff data, not live web results."),
    "FileAgent":    ("TerminalAgent",
                     "FileAgent tried and FAILED (likely permission error). "
                     "Use execute_shell to force-write the file via PowerShell: "
                     "New-Item -Path '<path>' -ItemType File -Force; Set-Content -Path '<path>' -Value '<content>'"),
    "ContentAgent": ("GeneralAgent",
                     "ContentAgent timed out or failed. Write a shorter, concise version of the requested content. "
                     "Quality matters more than length here — produce something complete and usable."),
    "CodeAgent":    ("CodeAgent",
                     "Your previous attempt had an error. Re-read the error message carefully, "
                     "identify the root cause, and retry with a corrected approach. "
                     "Do NOT repeat the same mistake."),
    "MusicAgent":   ("TerminalAgent",
                     "MusicAgent failed. Try launching the music app or file directly via execute_shell: "
                     "Start-Process 'spotify:' or Start-Process 'wmplayer.exe'."),
}


def _extract_artifacts(text: str) -> Dict[str, List[str]]:
    """
    'Baton Pass' — sniff an agent's reply for artifacts (file paths, URLs)
    so the Orchestrator can hand them explicitly to the next agent.

    Returns a dict like:
        {"files": ["C:\\Users\\Krish\\Desktop\\poem.txt"], "urls": ["https://..."]}
    """
    artifacts: Dict[str, List[str]] = {"files": [], "urls": []}

    # FILE_PATH: <path> pattern (our standard output marker)
    for m in re.finditer(r"FILE_PATH:\s*(.+?)(?:\n|$)", text):
        path = m.group(1).strip()
        if path and path not in artifacts["files"]:
            artifacts["files"].append(path)

    # Bare Windows/Unix absolute paths (e.g. C:\Users\...\file.txt or /home/.../file.txt)
    for m in re.finditer(
        r"(?<!\w)([A-Za-z]:\\[^\s\"'<>|*?\n]+|/(?:home|tmp|var|usr)/[^\s\"'<>|*?\n]+)",
        text,
    ):
        path = m.group(1).strip().rstrip(".,;)")
        if path and path not in artifacts["files"]:
            artifacts["files"].append(path)

    # URLs
    for m in re.finditer(r"https?://[^\s\"'<>\n]+", text):
        url = m.group(0).strip().rstrip(".,;)")
        if url and url not in artifacts["urls"]:
            artifacts["urls"].append(url)

    return artifacts


def _build_prior_context_block(agent_name: str, reply: str, artifacts: Dict[str, List[str]]) -> str:
    """
    'Telepathy' — build a clean, labeled context block to inject into the
    next agent's brain so it knows exactly what the previous agent did.

    ASSEMBLY LINE UPGRADE: If ContentAgent produced text but no file artifacts,
    include the full CONTENT: block so FileAgent can extract and save it.

    NEWSROOM UPGRADE: If WebAgent produced a RESEARCH_CONTEXT_BLOCK (from deep_research),
    inject it as a [RESEARCH_CONTEXT] block into ContentAgent so it enters Journalist Mode.
    """
    lines = [
        "--- PREVIOUS AGENT OUTPUT ---",
        f"[{agent_name}]: {reply.strip()}",
    ]
    if artifacts["files"]:
        for f in artifacts["files"]:
            lines.append(f"FILE: {f}")
    if artifacts["urls"]:
        for u in artifacts["urls"]:
            lines.append(f"URL: {u}")
    # ASSEMBLY LINE: If ContentAgent has no file/url artifacts, embed the raw content
    # so FileAgent can read it from context and save it to disk.
    if agent_name == "ContentAgent" and not artifacts["files"] and reply.strip():
        import os as _os
        desktop = str(_os.path.join(_os.path.expanduser("~"), "Desktop"))
        lines.append(f"SAVE_TO: {desktop}")   # GPS Lock hint — FileAgent reads this
        lines.append(f"CONTENT:\n{reply.strip()}\n:END_CONTENT")
    # NEWSROOM: If WebAgent's reply contains a RESEARCH_CONTEXT_BLOCK, extract it
    # and inject as a [RESEARCH_CONTEXT] block so ContentAgent enters Journalist Mode.
    if agent_name == "WebAgent":
        import re as _re
        rcb_match = _re.search(
            r"RESEARCH_CONTEXT_BLOCK:(.*?)END_RESEARCH_CONTEXT",
            reply,
            _re.DOTALL,
        )
        if rcb_match:
            research_block = rcb_match.group(0).strip()
            lines.append(f"\n[RESEARCH_CONTEXT]\n{research_block}\n[/RESEARCH_CONTEXT]")
    lines.append("--- END CONTEXT ---")
    return "\n".join(lines)

_SYNTHESIZER_PROMPT = (
    "You are A.N.K.I.T.A's Synthesizer. You receive outputs from specialist agents that executed tasks. "
    "Your ONLY job is to confirm what was done in ONE brief sentence.\n\n"
    "STRICT RULES:\n"
    "1. NEVER echo, repeat, or display the content that was written/generated "
    "(no paragraphs, scripts, songs, emails, or any generated text in your reply).\n"
    "2. NEVER apologize or say 'it seems there was an issue' if the agent outputs show tools succeeded.\n"
    "3. NEVER offer manual alternatives like 'you can copy this yourself' or 'open it manually'.\n"
    "4. If actions succeeded → ONE confirmation sentence. "
    "Example: 'Done — written the paragraph, opened it in Notepad, and started your music.'\n"
    "5. If a genuine error occurred (explicitly marked as failed) → ONE sentence stating what failed.\n"
    "6. You are a STATUS REPORTER, not a content displayer or a chatbot. Be terse."
)


def _inject_memory(messages: List[Dict[str, Any]]) -> None:
    """
    Hippocampus Injection — prepend the long-term memory block to the system prompt.

    This runs before EVERY specialist agent so they all share the same persistent
    context without needing to explicitly call recall().

    Only injects if .ankita/memory.json is non-empty (avoids useless padding).
    """
    memory_block = format_memory_block()
    if not memory_block:
        return  # vault is empty — nothing to inject

    if messages and messages[0].get("role") == "system":
        original = messages[0].get("content", "")
        messages[0]["content"] = f"{original}\n\n{memory_block}"
    else:
        # No system message yet — insert one at the front
        messages.insert(0, {"role": "system", "content": memory_block})


_DEEP_MODE_TASK_KEYWORDS = {
    "deep", "comprehensive", "detailed", "in-depth", "in depth", "full",
    "10 page", "10-page", "massive", "extensive", "thorough", "research",
    "investigation", "complete", "full investigation", "deep report",
    "deep dive", "deep-dive", "long form", "longform",
}
_DEEP_MODE_MAX_TOKENS = 8192


def _is_deep_mode_task(task: str, prior_context: Optional[str] = None) -> bool:
    """Return True if the task signals deep/long-form content generation."""
    combined = f"{task} {prior_context or ''}".lower()
    return any(kw in combined for kw in _DEEP_MODE_TASK_KEYWORDS)


def _run_specialist(
    specialist: SpecialistAgent,
    task: str,
    runtime: LLMRuntime,
    workspace_root: Path,
    prior_context: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a single specialist agent to completion and return its result.

    Args:
        prior_context: 'Telepathy' block from previous agent — injected directly
                       into the specialist's system prompt so it knows what happened
                       before it woke up. No hunting through text needed.
    """
    messages = specialist.make_messages(task)

    # PARALLEL CHUNK ENGINE: For ContentAgent in deep mode, boost the token budget
    # to 8192 so the LLM can write a full 10-page document without truncation.
    # For all other agents, use the runtime default.
    if specialist.name == "ContentAgent" and _is_deep_mode_task(task, prior_context):
        max_tokens = _DEEP_MODE_MAX_TOKENS
        print(f"[Orchestrator] 🔥 ContentAgent DEEP MODE — max_tokens boosted to {max_tokens}", flush=True)
    else:
        max_tokens = runtime.max_tokens

    # 🧠 HIPPOCAMPUS INJECTION — every agent sees long-term memory before speaking
    _inject_memory(messages)

    # TELEPATHY: inject prior context into the system message so the agent
    # starts with full awareness of what previous agents did/produced.
    if prior_context and messages and messages[0]["role"] == "system":
        messages[0] = {
            "role": "system",
            "content": messages[0]["content"] + "\n\n" + prior_context,
        }

    for _ in range(_MAX_TOOL_STEPS):
        try:
            response = call_chat_once(runtime, messages, tools=specialist.tool_specs, max_tokens=max_tokens)
        except Exception as err:
            return {"agent": specialist.name, "ok": False, "reply": f"[Error] {err}"}

        tool_calls = response.get("tool_calls") or []
        messages.append({
            "role": "assistant",
            "content": response.get("content") or "",
            **({"tool_calls": tool_calls} if tool_calls else {}),
        })

        if not tool_calls:
            return {"agent": specialist.name, "ok": True, "reply": (response.get("content") or "").strip()}

        # --- VISION INJECTION: collect image payloads from vision tools ---
        vision_packets: List[Dict[str, Any]] = []

        for tc in tool_calls:
            try:
                # Inject runtime so visual_click can call LLM vision API
                execute_tool_call._runtime = runtime  # type: ignore[attr-defined]
                result = execute_tool_call(tc, workspace_root=workspace_root)

                # Check if this tool returned image data (capture_screen / read_screen_context).
                # execute_tool_call wraps the inner result as {"ok": True, "result": {...}},
                # so we must look BOTH at the top level AND inside result["result"].
                _inner = result.get("result", {}) if isinstance(result, dict) else {}
                _b64_source = None
                if isinstance(result, dict) and "base64" in result:
                    _b64_source = result
                elif isinstance(_inner, dict) and "base64" in _inner:
                    _b64_source = _inner

                if _b64_source is not None:
                    b64_data = _b64_source["base64"]

                    # Strip the raw base64 blob from the text history — the LLM
                    # cannot read it as text and it wastes thousands of tokens.
                    # Rebuild the full wrapper without any base64 data.
                    clean_inner = {k: v for k, v in _b64_source.items() if k != "base64"}
                    clean_inner["base64"] = "<IMAGE_DATA_INJECTED_AS_VISION_MESSAGE>"
                    if _b64_source is _inner:
                        # base64 was inside result["result"] — rebuild the outer wrapper
                        safe_result = {**result, "result": clean_inner}
                    else:
                        # base64 was at the top level
                        safe_result = clean_inner

                    # Build a proper multimodal vision message for the LLM
                    vision_packets.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "System: Here is the screen capture you requested. "
                                    "Analyse it carefully and describe exactly what you see."
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64_data}",
                                    "detail": "low",  # "low" = faster + cheaper; avoids payload size 400s
                                },
                            },
                        ],
                    })
                    content_str = json.dumps(safe_result, ensure_ascii=False)
                else:
                    content_str = json.dumps(result, ensure_ascii=False)

            except Exception as err:
                content_str = json.dumps({"ok": False, "error": str(err)})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": content_str,
            })

        # Inject vision messages AFTER all tool outputs.
        # IMPORTANT: The OpenAI message format requires that after tool messages
        # we send an assistant turn, not a user turn. So we append a thin
        # assistant "pass-through" message to bridge the tool results, then
        # inject the image as a user message so the model sees the pixels.
        if vision_packets:
            # --- GROQ BLIND FIX: Groq/LLaMA cannot process image_url messages.
            # Instead: use a vision-capable runtime (Copilot/GPT-4o) to pre-describe
            # the image as plain text, then inject that description for Groq to read.
            if runtime.provider == "groq":
                vision_runtime = build_vision_runtime_from_env(runtime)
                if vision_runtime.provider != "groq":
                    # We have a vision-capable runtime — pre-describe each image
                    for vp in vision_packets:
                        try:
                            # Extract the base64 from the image_url content block
                            b64 = None
                            text_prompt = "Describe everything you can see in this image in detail. Include what the person is holding, wearing, or doing. Be specific."
                            for block in vp.get("content", []):
                                if block.get("type") == "image_url":
                                    url_str = block["image_url"].get("url", "")
                                    if "base64," in url_str:
                                        b64 = url_str.split("base64,")[1]
                                    elif len(url_str) > 100:
                                        b64 = url_str
                                elif block.get("type") == "text":
                                    text_prompt = block.get("text", text_prompt)

                            if b64:
                                description = call_chat_with_image(
                                    vision_runtime,
                                    text_prompt,
                                    b64,
                                    max_tokens=600,
                                    temperature=0.3,
                                )
                                # Inject as plain text — Groq can read this!
                                messages.append({
                                    "role": "assistant",
                                    "content": "I captured the image. Let me describe what I see.",
                                })
                                messages.append({
                                    "role": "user",
                                    "content": f"[Vision Analysis by GPT-4o]\n{description}",
                                })
                            else:
                                messages.append({
                                    "role": "user",
                                    "content": "[Image was captured but could not be decoded for vision analysis]",
                                })
                        except Exception as vision_err:
                            messages.append({
                                "role": "user",
                                "content": f"[Vision analysis failed: {vision_err}]",
                            })
                else:
                    # No vision runtime available — tell user clearly
                    messages.append({
                        "role": "assistant",
                        "content": "I captured the image.",
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            "[Vision Analysis Unavailable]\n"
                            "I captured the image but cannot analyse it because the current LLM (Groq/LLaMA) "
                            "does not support vision. To enable real image analysis, add COPILOT_GITHUB_TOKEN "
                            "to your .env file. I'll use that as the vision engine while keeping Groq for text."
                        ),
                    })
            else:
                # Vision-capable runtime (Copilot/GPT-4o) — inject images normally
                messages.append({
                    "role": "assistant",
                    "content": "I have the screen capture. Let me analyse it now.",
                })
                messages.extend(vision_packets)

    return {"agent": specialist.name, "ok": True, "reply": "Task completed (max steps reached)."}


class Orchestrator:
    """
    Multi-agent orchestrator using Supervisor + parallel Specialists + Synthesizer.

    Usage:
        orch = Orchestrator(runtime, workspace_root)
        reply = orch.run(user_text, messages)
    """

    def __init__(self, runtime: LLMRuntime, workspace_root: Path) -> None:
        self.runtime = runtime
        self.workspace_root = workspace_root
        self.supervisor = SupervisorAgent(runtime)

    def run(self, user_text: str, messages: List[Dict[str, Any]]) -> str:
        """
        Full orchestration pipeline:
          Supervisor → [Fan-Out specialist(s)] → Synthesizer → reply
        """
        # 1. Supervisor routes the request
        routing = self.supervisor.route(user_text)
        agent_names: List[str] = routing["agents"]
        parallel: bool = routing["parallel"]
        reasoning: str = routing.get("reasoning", "")

        # Single GeneralAgent → just use the full agent runtime (cheaper, faster)
        if agent_names == ["GeneralAgent"]:
            return self._run_general(user_text, messages)

        # Override lazy GeneralAgent routing: if the Supervisor chose only GeneralAgent
        # but the user text clearly maps to a specialist, re-route to the right agent.
        _ACTION_OVERRIDES = {
            "play_music": ({"play", "song", "music", "listen", "lofi", "lo-fi"}, ["MusicAgent"]),
            "stop_music": ({"stop music", "pause music"}, ["MusicAgent"]),
            "screenshot": ({"screenshot", "screen capture", "take a screenshot"}, ["SystemAgent"]),
            "launch_app": ({"open notepad", "launch", "open app", "start app"}, ["SystemAgent"]),
            # ASSEMBLY LINE: write tasks → ContentAgent (writes) + FileAgent (saves)
            "write_and_save_content": ({"write a", "draft a", "generate a", "create a report",
                               "write an essay", "write a poem", "write a script",
                               "write a song", "write a paragraph", "write an email",
                               "write a letter", "write a story", "write a summary"}, ["ContentAgent", "FileAgent"]),
            "search_web": ({"search for", "google", "look up", "find info"}, ["WebAgent"]),
            "execute_shell": ({"ping ", "ipconfig", "netstat", "tasklist", "whoami",
                               "git status", "git log", "git pull", "git push",
                               "run git", "run script", "terminal command",
                               "shell command", "what is my ip", "my ip address",
                               "show processes", "running processes"}, ["TerminalAgent"]),
            "capture_screen": ({"what's on my screen", "what is on my screen",
                                 "what does my screen show", "read the error on screen",
                                 "read my screen", "look at my screen", "see my screen",
                                 "what's on screen", "screen show", "screen says",
                                 "click the", "click on the", "visual click",
                                 "click button", "click submit", "click deploy",
                                 "read error on screen", "what error", "error on screen"}, ["ScreenAgent"]),
        }
        text_lower = user_text.lower()
        if agent_names == ["GeneralAgent"]:
            for _tool, (keywords, reroute_agents) in _ACTION_OVERRIDES.items():
                if any(kw in text_lower for kw in keywords):
                    agent_names = reroute_agents
                    parallel = False
                    break

        specialists = [SPECIALIST_MAP[n] for n in agent_names if n in SPECIALIST_MAP]
        if not specialists:
            return self._run_general(user_text, messages)

        # TIME LORD: Force sequential if a producer→consumer dependency is detected.
        # ASSEMBLY LINE: ContentAgent produces text → FileAgent saves → SystemAgent opens.
        # All three are in a strict dependency chain — always sequential.
        _EXTERNAL_PRODUCERS = {"ContentAgent", "FileAgent", "WebAgent"}
        _CONSUMERS = {"FileAgent", "SystemAgent", "CodeAgent"}
        agent_name_set = set(agent_names)
        if (_EXTERNAL_PRODUCERS & agent_name_set) and (_CONSUMERS & agent_name_set):
            parallel = False  # override Supervisor — baton must be passed sequentially

        # 2. Fan-Out: run specialists (parallel or sequential)
        results: List[Dict[str, Any]] = []
        if parallel and len(specialists) > 1:
            results = self._fan_out_parallel(specialists, user_text)
        else:
            results = self._run_sequential_with_context(specialists, user_text)

        # 3. Fan-In: if only one result, return it directly
        if len(results) == 1:
            reply = results[0].get("reply", "")
            self._append_to_messages(messages, user_text, reply)
            return reply

        # 4. Synthesize multiple results
        reply = self._synthesize(user_text, results)
        self._append_to_messages(messages, user_text, reply)
        return reply

    def _run_sequential_with_context(
        self, specialists: List[SpecialistAgent], task: str
    ) -> List[Dict[str, Any]]:
        """Run specialists one by one, passing each result as context to the next.

        Implements the full Hive Mind Protocol:
        - BATON PASS: Orchestrator sniffs artifacts (file paths, URLs) from each
          agent's reply and hands them explicitly to the next agent.
        - TELEPATHY: Prior context is injected directly into the next agent's
          system prompt — not just appended to the task. The agent *knows* what
          happened before it even reads the task.
        - TIME LORD: Sequential execution guarantees producers finish before
          consumers start. Files exist before they are opened.
        """
        results: List[Dict[str, Any]] = []
        prior_context_block: Optional[str] = None  # injected into system prompt of next agent

        for sp in specialists:
            result = _run_specialist(
                sp, task, self.runtime, self.workspace_root,
                prior_context=prior_context_block,
            )

            # ── HYDRA PROTOCOL: Error Interceptor 🐉 ─────────────────────────
            # If the agent failed, look up the Escalation Matrix and reroute
            # to a backup agent with a Post-Mortem Injection context prompt.
            # Capped at 1 retry per agent to prevent infinite loops.
            reply = result.get("reply", "")
            agent_failed = (
                not result.get("ok", True)
                or reply.startswith("[Error]")
                or "Tool not found" in reply
                or "Permission denied" in reply
                or "timed out" in reply.lower()
            )
            if agent_failed and sp.name in _ESCALATION_MATRIX:
                backup_name, failure_note = _ESCALATION_MATRIX[sp.name]
                backup_sp = SPECIALIST_MAP.get(backup_name)
                if backup_sp and backup_sp.name != sp.name or (backup_sp and backup_sp.name == sp.name):
                    print(
                        f"[Hydra] ⚡ {sp.name} failed → rerouting to {backup_name}",
                        flush=True,
                    )
                    post_mortem = (
                        f"SYSTEM ALERT — HYDRA REROUTE:\n"
                        f"Original request: {task}\n"
                        f"{sp.name} already tried and failed with: {reply[:300]}\n\n"
                        f"BACKUP MISSION: {failure_note}\n"
                        f"Achieve the SAME goal using YOUR tools. Do not repeat the failed approach."
                    )
                    backup_result = _run_specialist(
                        backup_sp, task, self.runtime, self.workspace_root,
                        prior_context=post_mortem,
                    )
                    backup_result["rerouted_from"] = sp.name
                    # Log both the failure and the reroute
                    self._write_audit(sp.name, {**result, "hydra_rerouted_to": backup_name})
                    self._write_audit(backup_name, {**backup_result, "hydra_backup": True})
                    result = backup_result
                    reply = result.get("reply", "")

            results.append(result)

            # BATON PASS: sniff this agent's reply for artifacts
            if reply:
                artifacts = _extract_artifacts(reply)
                # Build the Telepathy block for the next agent
                prior_context_block = _build_prior_context_block(
                    result.get("agent", sp.name), reply, artifacts
                )

            # AUDIT LOG: record agent name, tools used, and artifacts to .ankita/audit.jsonl
            self._write_audit(sp.name, result)

        return results

    def _write_audit(self, agent_name: str, result: Dict[str, Any]) -> None:
        """Write a structured audit entry to .ankita/audit.jsonl for traceability."""
        import time as _time
        try:
            audit_path = self.workspace_root / ".ankita" / "audit.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": _time.time(),
                "agent": agent_name,
                "reply_preview": (result.get("reply", "") or "")[:120],
                "tools_used": result.get("tools_used", []),
                "artifacts": _extract_artifacts(result.get("reply", "") or ""),
            }
            with audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # Audit log failures must never crash the main flow

    @staticmethod
    def _extract_file_path(text: str) -> Optional[str]:
        """Extract FILE_PATH: <path> from an agent reply."""
        import re
        match = re.search(r"FILE_PATH:\s*(.+?)(?:\n|$)", text)
        if match:
            return match.group(1).strip()
        return None

    def _fan_out_parallel(
        self, specialists: List[SpecialistAgent], task: str
    ) -> List[Dict[str, Any]]:
        """Dispatch specialists concurrently and collect results."""
        results = [None] * len(specialists)
        with ThreadPoolExecutor(max_workers=min(len(specialists), 4)) as executor:
            future_to_idx = {
                executor.submit(_run_specialist, sp, task, self.runtime, self.workspace_root): i
                for i, sp in enumerate(specialists)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as err:
                    results[idx] = {"agent": specialists[idx].name, "ok": False, "reply": f"[Error] {err}"}
        return results

    def _synthesize(self, user_text: str, results: List[Dict[str, Any]]) -> str:
        """Merge multiple specialist outputs into a single cohesive response."""
        parts = []
        for r in results:
            agent = r.get("agent", "Agent")
            reply = r.get("reply", "")
            if reply:
                parts.append(f"[{agent}]: {reply}")

        combined = "\n\n".join(parts)
        synth_messages = [
            {"role": "system", "content": _SYNTHESIZER_PROMPT},
            {"role": "user", "content": f"Original request: {user_text}\n\nAgent outputs:\n{combined}"},
        ]
        try:
            response = call_chat_once(self.runtime, synth_messages, tools=None, max_tokens=self.runtime.max_tokens)
            return (response.get("content") or combined).strip()
        except Exception:
            return combined

    def _run_general(self, user_text: str, messages: List[Dict[str, Any]]) -> str:
        """Fallback: use full AgentRuntime-style loop with all tools."""
        from agent_runtime import AgentRuntime
        # Reuse the same runtime; create a temp AgentRuntime
        agent = AgentRuntime(runtime=self.runtime, workspace_root=self.workspace_root)
        messages.append({"role": "user", "content": user_text})
        try:
            return agent.run_turn(messages, tools=TOOL_SPECS)
        except Exception as err:
            if messages and messages[-1].get("role") == "user":
                messages.pop()
            return f"[Error] {err}"

    def _append_to_messages(
        self, messages: List[Dict[str, Any]], user_text: str, reply: str
    ) -> None:
        """Append the user/assistant turn to the shared message history."""
        # Only append if user message is not already there
        if not messages or messages[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": reply})
