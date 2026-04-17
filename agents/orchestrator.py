"""
Orchestrator for A.N.K.I.T.A multi-agent system.

Implements the Fan-Out / Fan-In parallel execution pattern:
  1. Supervisor routes request -> list of specialist agents
  2. Fan-Out: dispatch agents concurrently (ThreadPoolExecutor)
  3. Fan-In: collect results, synthesize a single cohesive response

Falls back to the base AgentRuntime if anything goes wrong.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm import LLMRuntime, call_chat_once
from llm.client import build_vision_runtime_from_env, call_chat_with_image
from llm.agent_router import get_agent_runtime, detect_task_complexity
from tools.engine import execute_tool_call, TOOL_SPECS, compact_messages, _estimate_tokens
from .content_contract import parse_content_payload, validate_content_payload, extract_body

_ORCHESTRATOR_TOKEN_LIMIT = 48_000   # same guardian threshold as agent_runtime


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

from .supervisor import SupervisorAgent
from .communication_protocol import AgentMessage, MessageType, MessagePriority, COMMUNICATION_HUB
from .specialists import SPECIALIST_MAP, SpecialistAgent

_MAX_TOOL_STEPS = 20
_MAX_HANDOFF_STEPS = 6
_CONTENT_PAYLOAD_STATS: Dict[str, int] = {
    "total": 0,
    "schema_valid_first_pass": 0,
    "schema_repaired": 0,
    "schema_fallback_legacy": 0,
}

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

# ─────────────────────────────────────────────────────────────────────────────
# VISION CACHE — remembers the last captured image for 60 seconds so
# follow-up messages like "describe it", "what do you see", "tell me more"
# don't require the user to trigger a new capture.
# Structure: {"b64": str, "mime": str, "ts": float, "source": str}
# source = "gui" | "chat" | "telegram" — only inject if same source channel
# ─────────────────────────────────────────────────────────────────────────────
_LAST_VISION_CACHE: Dict[str, Any] = {}
_VISION_CACHE_TTL_SEC = 60  # seconds before cache expires

_VISION_FOLLOWUP_KEYWORDS = {
    "describe", "what do you see", "tell me", "what's in", "what is in",
    "analyse", "analyze", "look at", "what did you", "explain what",
    "describe it", "describe the", "what are", "can you see", "do you see",
    "what's there", "what is there", "read it", "read the", "what text",
    "any text", "what does it show", "what does it say",
}

# Tools that can capture images — only these should trigger vision cache
_VISION_TOOL_NAMES = {"capture_webcam", "read_screen_context", "visual_click"}

# -----------------------------------------------------------------------------
# HYDRA PROTOCOL - Escalation Matrix 
# Maps (primary_agent) -> (backup_agent_name, context_note_for_backup)
# -----------------------------------------------------------------------------
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
                     "Quality matters more than length here — produce something complete and usable. "
                     "IMPORTANT: After writing, call write_file to save it to Desktop as a .md file. "
                     "Use a sensible filename based on the topic. "
                     "Then call launch_app to open it. "
                     "Do NOT just return text — save it."),
    "CodeAgent":    ("CodeAgent",
                     "Your previous attempt had an error. Re-read the error message carefully, "
                     "identify the root cause, and retry with a corrected approach. "
                     "Do NOT repeat the same mistake."),
    "MusicAgent":   ("TerminalAgent",
                     "MusicAgent failed. Try launching the music app or file directly via execute_shell: "
                     "Start-Process 'spotify:' or Start-Process 'wmplayer.exe'."),
    "PlannerAgent": ("GeneralAgent",
                     "PlannerAgent failed to produce a plan. "
                     "Handle this request directly as best you can, "
                     "completing all implied steps yourself."),
}


def _extract_artifacts(text: str) -> Dict[str, List[str]]:
    """
    'Baton Pass' - sniff an agent's reply for artifacts (file paths, URLs)
    so the Orchestrator can hand them explicitly to the next agent.

    Returns a dict like:
        {"files": ["C:\\Users\\Krish\\Desktop\\poem.txt"], "urls": ["https://..."]}
    """
    artifacts: Dict[str, List[str]] = {"files": [], "urls": [], "handoffs": []}
    explicit_files: List[str] = []

    # FILE_PATH: <path> pattern (our standard output marker)
    for m in re.finditer(r"FILE_PATH:\s*(.+?)(?:\n|$)", text):
        path = m.group(1).strip()
        if path and path not in artifacts["files"]:
            artifacts["files"].append(path)
            explicit_files.append(path)

    # Bare Windows/Unix absolute paths (e.g. C:\Users\...\file.txt or /home/.../file.txt)
    for m in re.finditer(
        r"(?<!\w)([A-Za-z]:\\[^\s\"'<>|*?\n]+|/(?:home|tmp|var|usr)/[^\s\"'<>|*?\n]+)",
        text,
    ):
        path = m.group(1).strip().rstrip(".,;)")
        if any(explicit == path or explicit.startswith(path + " ") for explicit in explicit_files):
            continue
        if path and path not in artifacts["files"]:
            artifacts["files"].append(path)

    # URLs
    for m in re.finditer(r"https?://[^\s\"'<>\n]+", text):
        url = m.group(0).strip().rstrip(".,;)")
        if url and url not in artifacts["urls"]:
            artifacts["urls"].append(url)
    
    # HANDOFF signals: SUGGEST_NEXT: AgentName → message OR HANDOFF: AgentName → message
    for m in re.finditer(r"(SUGGEST_NEXT|HANDOFF):\s*(\w+Agent)\s*→\s*(.+?)(?:\n|$)", text):
        label = m.group(1).strip()
        agent = m.group(2).strip()
        message = m.group(3).strip()
        if "FILE_PATH" in message and explicit_files:
            message = message.replace("FILE_PATH", explicit_files[-1])
        handoff = f"{label}: {agent} → {message}"
        if handoff not in artifacts["handoffs"]:
            artifacts["handoffs"].append(handoff)

    return artifacts


def _merge_artifacts(reply: str, extra: Optional[Dict[str, List[str]]] = None) -> Dict[str, List[str]]:
    artifacts = _extract_artifacts(reply or "")
    if not extra:
        return artifacts
    for key in ("files", "urls", "handoffs"):
        for item in extra.get(key, []):
            if item and item not in artifacts[key]:
                artifacts[key].append(item)
    return artifacts


def _slugify_filename(value: str, default: str = "content_output") -> str:
    s = (value or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:80] or default


def _build_prior_context_block(agent_name: str, reply: str, artifacts: Dict[str, List[str]]) -> str:
    """
    Build a clean context block for next agent handoff.
    For ContentAgent, prefer structured CONTENT_PAYLOAD_V1 and emit deterministic
    fields plus legacy CONTENT block for backward compatibility.
    """
    lines = ["--- PREVIOUS AGENT OUTPUT ---"]
    if agent_name == "ContentAgent":
        lines.append(f"[{agent_name}]: content generated")
    else:
        lines.append(f"[{agent_name}]: {reply.strip()}")

    file_already_opened = agent_name == "FileAgent" and ("opened" in reply.lower() or "launch_app" in reply.lower())

    if artifacts["files"]:
        if not file_already_opened:
            for f in artifacts["files"]:
                lines.append(f"FILE: {f}")
    if artifacts["urls"]:
        for u in artifacts["urls"]:
            lines.append(f"URL: {u}")
    if artifacts.get("handoffs"):
        for h in artifacts["handoffs"]:
            lines.append(h)

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
                lines.append("CONTENT_SCHEMA: CONTENT_PAYLOAD_V1")
                lines.append(f"TASK_TYPE: {task_type}")
                lines.append(f"TITLE: {title}")
                lines.append(f"FORMAT: {fmt}")
                lines.append(f"AUDIENCE: {audience}")
                lines.append(f"TONE: {tone}")
                lines.append(f"WORD_TARGET: {word_target}")
                lines.append(f"FILENAME_HINT: {_slugify_filename(title, default=task_type)}{ext}")
                if notes:
                    lines.append(f"CONTENT_NOTES: {notes}")
                lines.append(f"CONTENT:\n{body}\n:END_CONTENT")
            else:
                if errors:
                    lines.append(f"CONTENT_SCHEMA_ERRORS: {'; '.join(errors)}")
                lines.append(f"CONTENT:\n{reply.strip()}\n:END_CONTENT")

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


def _validate_or_repair_content_payload(
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

_SYNTHESIZER_PROMPT = (
    "You are A.N.K.I.T.A's Synthesizer. You receive outputs from specialist agents that executed tasks. "
    "Your ONLY job is to confirm what was done in ONE brief sentence.\n\n"
    "STRICT RULES:\n"
    "1. NEVER echo, repeat, or display the content that was written/generated "
    "(no paragraphs, scripts, songs, emails, or any generated text in your reply).\n"
    "2. NEVER apologize or say 'it seems there was an issue' if the agent outputs show tools succeeded.\n"
    "3. NEVER offer manual alternatives like 'you can copy this yourself' or 'open it manually'.\n"
    "4. If actions succeeded -> ONE confirmation sentence. "
    "Example: 'Done - written the paragraph, opened it in Notepad, and started your music.'\n"
    "5. If a genuine error occurred (explicitly marked as failed) -> ONE sentence stating what failed.\n"
    "6. You are a STATUS REPORTER, not a content displayer or a chatbot. Be terse."
)





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


def _extract_clean_history(messages: List[Dict[str, Any]], max_turns: int = 6) -> List[Dict[str, Any]]:
    """Extract the last N clean user/assistant turns from conversation history.
    
    Filters out:
    - System messages
    - Tool messages
    - Messages with base64 content
    - Multimodal content (lists)
    
    Args:
        messages: Full conversation history
        max_turns: Maximum number of turns to extract (default 6 = 3 exchanges)
    
    Returns:
        List of clean user/assistant message dicts
    """
    clean = []
    for msg in reversed(messages):
        role = msg.get("role")
        content = msg.get("content")
        
        # Skip system and tool messages
        if role in ("system", "tool"):
            continue
        
        # Skip multimodal content (lists with image_url blocks)
        if isinstance(content, list):
            continue
        
        # Skip messages with base64 data
        if isinstance(content, str) and ("base64" in content or len(content) > 10000):
            continue
        
        # Only keep user and assistant messages with clean text content
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            clean.append({"role": role, "content": content})
        
        # Stop when we have enough turns
        if len(clean) >= max_turns:
            break
    
    # Reverse back to chronological order
    return list(reversed(clean))


def _run_specialist(
    specialist: SpecialistAgent,
    task: str,
    runtime: LLMRuntime,
    workspace_root: Path,
    prior_context: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run a single specialist agent to completion and return its result.

    Args:
        prior_context: 'Telepathy' block from previous agent — injected directly
                       into the specialist's system prompt so it knows what happened
                       before it woke up. No hunting through text needed.
    """
    # UPGRADE 14: Smart model routing for CodeAgent based on task complexity
    # Detect complexity and use appropriate model tier (simple/medium/complex)
    if specialist.name == "CodeAgent":
        complexity = detect_task_complexity(task, agent_name="CodeAgent")
        specialist_runtime = get_agent_runtime("CodeAgent", runtime, complexity)
        if specialist_runtime.model != runtime.model:
            print(
                f"[ModelRouter] CodeAgent: {complexity.upper()} task → routing to {specialist_runtime.model}",
                flush=True,
            )
    else:
        specialist_runtime = runtime

    messages = specialist.make_messages(task, history=conversation_history)

    # ── SANITIZE MESSAGES: strip any image_url blocks that leaked from prior turns ──
    # Vision packets injected in a previous turn (e.g. from GUI) can persist in the
    # messages list passed to drones — causing "data too massive" on Telegram/follow-ups.
    def _strip_image_blocks(msgs: list) -> list:
        clean = []
        for m in msgs:
            content = m.get("content")
            if isinstance(content, list):
                # Filter out image_url blocks — keep only text blocks
                text_parts = [b for b in content if isinstance(b, dict) and b.get("type") != "image_url"]
                if not text_parts:
                    continue  # Skip messages that were ONLY images
                # If only one text block, flatten to string
                if len(text_parts) == 1 and text_parts[0].get("type") == "text":
                    clean.append({**m, "content": text_parts[0].get("text", ""), "_mime_type": None})
                else:
                    clean.append({**m, "content": text_parts})
            else:
                clean.append(m)
        return clean

    messages = _strip_image_blocks(messages)

    # PARALLEL CHUNK ENGINE: For ContentAgent in deep mode, boost the token budget
    # to 8192 so the LLM can write a full 10-page document without truncation.
    # For all other agents, use the runtime default.
    if specialist.name == "ContentAgent" and _is_deep_mode_task(task, prior_context):
        max_tokens = _DEEP_MODE_MAX_TOKENS
        print(f"[Orchestrator] ContentAgent DEEP MODE - max_tokens boosted to {max_tokens}", flush=True)
    else:
        max_tokens = specialist_runtime.max_tokens

    # ── VISION FOLLOW-UP CACHE ─────────────────────────────────────────────
    # If the user is asking a describe/analyse follow-up (no new tool needed)
    # AND we have a fresh cached image (<60s old), inject it directly so the
    # model can answer without needing to re-capture.
    import time as _time_fup
    _task_lower = task.lower()
    _cache_fresh = (
        _LAST_VISION_CACHE
        and (_time_fup.time() - _LAST_VISION_CACHE.get("ts", 0)) < _VISION_CACHE_TTL_SEC
    )
    _is_followup = any(kw in _task_lower for kw in _VISION_FOLLOWUP_KEYWORDS)
    if _cache_fresh and _is_followup:
        _cached_b64 = _LAST_VISION_CACHE["b64"]
        _cached_mime = _LAST_VISION_CACHE["mime"]
        print(
            f"[VisionCache] Using cached image ({_cached_mime}) for follow-up via call_chat_with_image: '{task[:60]}'",
            flush=True,
        )
        # Use call_chat_with_image() — isolated API call with ONLY image + prompt.
        # Never inject raw image into messages (causes "too massive" context overflow).
        try:
            _vision_rt = build_vision_runtime_from_env(specialist_runtime)
            _cache_desc = call_chat_with_image(
                _vision_rt,
                f"The user asks: {task}\nDescribe what you see in this image, focusing on the user's question.",
                _cached_b64,
                max_tokens=600,
                temperature=0.3,
                mime_type=_cached_mime,
            )
            messages.append({
                "role": "assistant",
                "content": "Looking at the image from earlier...",
            })
            messages.append({
                "role": "user",
                "content": f"[Vision Analysis — cached image]\n{_cache_desc}",
            })
            print(f"[VisionCache] Follow-up description ready ({len(_cache_desc)} chars)", flush=True)
        except Exception as _cache_vision_err:
            print(f"[VisionCache] call_chat_with_image failed: {_cache_vision_err}", flush=True)
            messages.append({
                "role": "user",
                "content": f"[Vision follow-up failed: {_cache_vision_err}]",
            })

    # TELEPATHY: inject prior context into the system message so the agent
    # starts with full awareness of what previous agents did/produced.
    if prior_context and messages and messages[0]["role"] == "system":
        messages[0] = {
            "role": "system",
            "content": messages[0]["content"] + "\n\n" + prior_context,
        }

    # ── CASCADING OVERFLOW RECOVERY (OpenClaw-inspired) ────────────────────
    # Tier 1: Proactive compact before LLM call (already exists)
    # Tier 2: On 400/context_overflow → trim tool results + retry
    # Tier 3: On second failure → LLM-summarize old messages + retry
    # Tier 4: On third failure → emergency compact (keep tail only)
    _overflow_attempts = 0
    _MAX_OVERFLOW_ATTEMPTS = 3
    _forced_tool_retry = False
    tool_artifacts: Dict[str, List[str]] = {"files": [], "urls": [], "handoffs": []}

    for _ in range(_MAX_TOOL_STEPS):
        # -- TOKEN LIMIT GUARDIAN: proactive trim before each specialist LLM call --
        estimated = _estimate_tokens(messages)
        if estimated > _ORCHESTRATOR_TOKEN_LIMIT:
            print(
                f"[TokenGuardian/{specialist.name}] [WARN]  ~{estimated:,} tokens - compacting...",
                flush=True,
            )
            trimmed = compact_messages(messages, runtime=specialist_runtime)
            messages = trimmed
            print(
                f"[TokenGuardian/{specialist.name}] [OK] Compacted to ~{_estimate_tokens(messages):,} tokens.",
                flush=True,
            )
        try:
            response = call_chat_once(specialist_runtime, messages, tools=specialist.tool_specs, max_tokens=max_tokens)
            _overflow_attempts = 0  # Reset on success
        except Exception as err:
            err_str = str(err).lower()
            is_payload_err = (
                "400" in err_str
                or "context_length_exceeded" in err_str
                or "bad request" in err_str
                or "too large" in err_str
                or "request too large" in err_str
                or "maximum context" in err_str
            )
            if not is_payload_err:
                if specialist.name == "SystemAgent" and prior_context:
                    task_lower = task.lower()
                    wants_open = any(token in task_lower for token in (" open ", " open it", " open the", " show ", " view ", " launch "))
                    if not wants_open and task_lower.startswith(("open ", "show ", "view ", "launch ")):
                        wants_open = True
                    if wants_open:
                        try:
                            from tools.engine import _call as _engine_call
                            prior_file = ""
                            for line in reversed(prior_context.splitlines()):
                                if line.startswith("FILE: ") or line.startswith("FILE_PATH: "):
                                    prior_file = line.split(":", 1)[1].strip()
                                    if prior_file:
                                        break
                            if prior_file:
                                open_result = _engine_call(
                                    "open_path",
                                    {"path": prior_file},
                                    workspace_root,
                                    agent_name=specialist.name,
                                )
                                if bool(open_result.get("ok", False)):
                                    return {
                                        "agent": specialist.name,
                                        "ok": True,
                                        "reply": f"Done - opened the file.\nFILE_PATH: {prior_file}",
                                        "artifacts": {
                                            "files": [prior_file],
                                            "urls": [],
                                            "handoffs": [],
                                        },
                                    }
                        except Exception as open_err:
                            print(f"[SystemAgentExceptionFallback] open_path failed: {open_err}", flush=True)
                return {"agent": specialist.name, "ok": False, "reply": f"[Error] {err}"}

            _overflow_attempts += 1
            print(
                f"[CascadeRecovery/{specialist.name}] Overflow attempt {_overflow_attempts}/{_MAX_OVERFLOW_ATTEMPTS}",
                flush=True,
            )

            if _overflow_attempts == 1:
                # Tier 2: Truncate ALL tool messages to slim placeholders
                _truncated_any = False
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "tool":
                        content = messages[i].get("content", "")
                        if isinstance(content, str) and len(content) > 500:
                            messages[i] = {
                                **messages[i],
                                "content": content[:500] + "\n[TRUNCATED — result too large]",
                            }
                            _truncated_any = True
                if _truncated_any:
                    print(f"[CascadeRecovery/{specialist.name}] Tier 2: Truncated tool messages", flush=True)
                    continue  # Retry the loop iteration

            if _overflow_attempts == 2:
                # Tier 3: LLM-powered summarization of old context
                messages = compact_messages(messages, runtime=specialist_runtime)
                print(f"[CascadeRecovery/{specialist.name}] Tier 3: LLM summarization applied", flush=True)
                continue

            if _overflow_attempts >= _MAX_OVERFLOW_ATTEMPTS:
                # Tier 4: Emergency — keep only system + last 6 messages
                system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
                tail = messages[-6:]
                messages = ([system_msg] if system_msg else []) + [{
                    "role": "system",
                    "content": "[EMERGENCY] Context overflow recovery — older context dropped.",
                }] + tail
                print(f"[CascadeRecovery/{specialist.name}] Tier 4: Emergency compact", flush=True)
                try:
                    response = call_chat_once(specialist_runtime, messages, tools=specialist.tool_specs, max_tokens=max_tokens)
                except Exception as final_err:
                    return {
                        "agent": specialist.name,
                        "ok": False,
                        "reply": (
                            "[WARN] Context overflow after 3 recovery attempts. "
                            "Please try a more specific request."
                        ),
                    }
            else:
                continue

        tool_calls = response.get("tool_calls") or []
        messages.append({
            "role": "assistant",
            "content": response.get("content") or "",
            **({"tool_calls": tool_calls} if tool_calls else {}),
        })

        if not tool_calls:
            reply = (response.get("content") or "").strip()
            if specialist.name == "SystemAgent":
                if not _forced_tool_retry:
                    _forced_tool_retry = True
                    messages.append({
                        "role": "system",
                        "content": (
                            "You are handling a real system action request. "
                            "You MUST call an appropriate tool before replying. "
                            "Do not answer with catchphrases, status lines, or prose until a tool has executed."
                        ),
                    })
                    messages.append({
                        "role": "user",
                        "content": f"Retry this same request now by calling a tool: {task}",
                    })
                    continue

                try:
                    from tools.engine import _call as _engine_call, _format_result as _engine_format_result, _parse_local_intent

                    task_lower = task.lower()
                    wants_open = any(token in task_lower for token in (" open ", " open it", " open the", " show ", " view ", " launch "))
                    if not wants_open and task_lower.startswith(("open ", "show ", "view ", "launch ")):
                        wants_open = True

                    if wants_open and prior_context:
                        prior_file = ""
                        for line in reversed(prior_context.splitlines()):
                            if line.startswith("FILE: ") or line.startswith("FILE_PATH: "):
                                prior_file = line.split(":", 1)[1].strip()
                                if prior_file:
                                    break
                        if prior_file:
                            open_result = _engine_call(
                                "open_path",
                                {"path": prior_file},
                                workspace_root,
                                agent_name=specialist.name,
                            )
                            if bool(open_result.get("ok", False)):
                                return {
                                    "agent": specialist.name,
                                    "ok": True,
                                    "reply": f"Done - opened the file.\nFILE_PATH: {prior_file}",
                                    "artifacts": {
                                        "files": [prior_file],
                                        "urls": [],
                                        "handoffs": [],
                                    },
                                }

                    parsed_intent = _parse_local_intent(task, workspace_root)
                    if parsed_intent:
                        tool_name, tool_args = parsed_intent
                        if not str(tool_name).startswith("__"):
                            fallback_result = _engine_call(
                                tool_name,
                                tool_args,
                                workspace_root,
                                agent_name=specialist.name,
                            )
                            fallback_reply = _engine_format_result(fallback_result)
                            fallback_ok = bool(fallback_result.get("ok", True))
                            artifact_path = ""
                            if isinstance(fallback_result, dict):
                                artifact_path = str(
                                    fallback_result.get("FILE_PATH")
                                    or fallback_result.get("absolute_path")
                                    or fallback_result.get("path")
                                    or ""
                                ).strip()
                            if fallback_ok and artifact_path and wants_open:
                                try:
                                    open_result = _engine_call(
                                        "open_path",
                                        {"path": artifact_path},
                                        workspace_root,
                                        agent_name=specialist.name,
                                    )
                                    if bool(open_result.get("ok", False)):
                                        fallback_reply = f"Done - took a screenshot and opened it.\nFILE_PATH: {artifact_path}"
                                    else:
                                        fallback_reply = (
                                            f"{fallback_reply}\n"
                                            f"FILE_PATH: {artifact_path}\n"
                                            "I saved it, but opening it failed."
                                        )
                                except Exception as open_err:
                                    fallback_reply = (
                                        f"{fallback_reply}\n"
                                        f"FILE_PATH: {artifact_path}\n"
                                        f"I saved it, but opening it failed: {open_err}"
                                    )
                            if tool_name == "system_control" and isinstance(fallback_result, dict):
                                action = str(fallback_result.get("action", "")).strip().lower()
                                stdout = str(fallback_result.get("stdout", "")).strip()
                                stderr = str(fallback_result.get("stderr", "")).strip()
                                if "brightness_unavailable" in stderr:
                                    fallback_reply = (
                                        "Software brightness control is not available on this display. "
                                        "This monitor appears to require its physical brightness buttons."
                                    )
                                    fallback_ok = True
                                elif action.startswith("brightness") and fallback_ok:
                                    fallback_reply = stdout or "Brightness adjusted."
                            return {
                                "agent": specialist.name,
                                "ok": fallback_ok,
                                "reply": fallback_reply,
                                "artifacts": tool_artifacts,
                            }
                except Exception as fallback_err:
                    print(f"[SystemAgentFallback] Local tool fallback failed: {fallback_err}", flush=True)

            if specialist.name == "ContentAgent":
                _CONTENT_PAYLOAD_STATS["total"] += 1
                checked = _validate_or_repair_content_payload(
                    specialist_runtime=specialist_runtime,
                    messages=messages,
                    reply=reply,
                    max_tokens=max_tokens,
                )
                if checked["content_payload_valid"] and checked["content_payload_repaired"]:
                    _CONTENT_PAYLOAD_STATS["schema_repaired"] += 1
                elif checked["content_payload_valid"]:
                    _CONTENT_PAYLOAD_STATS["schema_valid_first_pass"] += 1
                else:
                    _CONTENT_PAYLOAD_STATS["schema_fallback_legacy"] += 1

                print(
                    "[ContentPayload] total={total} first_pass={schema_valid_first_pass} "
                    "repaired={schema_repaired} fallback={schema_fallback_legacy}".format(
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

        # --- VISION INJECTION: collect image payloads from vision tools ---
        vision_packets: List[Dict[str, Any]] = []

        for tc in tool_calls:
            try:
                # Inject runtime so visual_click can call LLM vision API
                execute_tool_call._runtime = runtime  # type: ignore[attr-defined]
                result = execute_tool_call(tc, workspace_root=workspace_root, agent_name=specialist.name)
                if isinstance(result, dict):
                    for key in ("FILE_PATH", "absolute_path", "path"):
                        path_value = result.get(key)
                        if isinstance(path_value, str):
                            path_text = path_value.strip()
                            if path_text and Path(path_text).is_absolute() and path_text not in tool_artifacts["files"]:
                                tool_artifacts["files"].append(path_text)

                # Check if this tool returned image data (capture_screen / read_screen_context).
                # execute_tool_call wraps the inner result as {"ok": True, "result": {...}},
                # but sometimes the inner result is truncated to {"status":"truncated","data":"<json>"}
                # where the actual base64 is inside the JSON string in "data".
                _inner = result.get("result", {}) if isinstance(result, dict) else {}
                # Unwrap truncated data if needed
                if isinstance(_inner, dict) and _inner.get("status") == "truncated" and isinstance(_inner.get("data"), str):
                    try:
                        _inner = json.loads(_inner["data"])
                    except Exception:
                        pass
                _b64_source = None
                if isinstance(result, dict) and "base64" in result:
                    _b64_source = result
                elif isinstance(_inner, dict) and "base64" in _inner:
                    _b64_source = _inner

                if _b64_source is not None:
                    b64_data = _b64_source["base64"]

                    # Detect MIME type from the tool result:
                    # - capture_webcam() encodes as JPEG → "image/jpeg"
                    # - capture_screen() / read_screen_context() encodes as PNG → "image/png"
                    # Using the wrong MIME type causes the API to silently misparse the image.
                    _tool_name = tc.get("function", {}).get("name", "")
                    _img_mime = "image/jpeg" if _tool_name == "capture_webcam" else "image/png"

                    # ── VISION CACHE: store this capture so follow-up messages
                    # ("describe it", "what do you see") can re-use it without
                    # triggering a new capture. TTL = 60 seconds.
                    import time as _time
                    _LAST_VISION_CACHE.clear()
                    _LAST_VISION_CACHE.update({
                        "b64": b64_data,
                        "mime": _img_mime,
                        "ts": _time.time(),
                    })

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

                    # Apply size guard before building vision packet — compress if >200KB base64
                    _vp_b64 = b64_data
                    _vp_mime = _img_mime
                    _VP_MAX_B64 = 200_000
                    if len(_vp_b64) > _VP_MAX_B64:
                        try:
                            import base64 as _b64vp
                            from io import BytesIO as _BytesIOvp
                            from PIL import Image as _PILvp
                            _raw_vp = _b64vp.b64decode(_vp_b64)
                            _img_vp = _PILvp.open(_BytesIOvp(_raw_vp)).convert("RGB")
                            _w_vp, _h_vp = _img_vp.size
                            if _w_vp > 480:
                                _img_vp = _img_vp.resize((480, int(_h_vp * 480 / _w_vp)), _PILvp.LANCZOS)
                            _buf_vp = _BytesIOvp()
                            _img_vp.save(_buf_vp, format="JPEG", quality=50)
                            _vp_b64 = _b64vp.b64encode(_buf_vp.getvalue()).decode("utf-8")
                            _vp_mime = "image/jpeg"
                            print(
                                f"[VisionPacket] Packet re-compressed to 480px/q50 ({len(_vp_b64):,} chars)",
                                flush=True,
                            )
                        except Exception as _vp_err:
                            print(f"[VisionPacket] ⚠️  Re-compress failed: {_vp_err}", flush=True)

                    # Build a proper multimodal vision message for the LLM
                    vision_packets.append({
                        "role": "user",
                        "_mime_type": _vp_mime,  # metadata for _describe_vision_packets_as_text
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
                                    "url": f"data:{_vp_mime};base64,{_vp_b64}",
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
            # Determine if the current runtime/model can natively handle vision payloads.
            # Only GPT-4o (and variants) support image_url messages.
            # gpt-4, gpt-3.5-turbo, and LLaMA models will return 400 Bad Request.
            # Broaden model check: any gpt-4, gpt-4o, o1, claude, gemini variant supports vision.
            # Previously only exact substrings "gpt-4o" / "gpt-4-vision" matched, so
            # models like "gpt-4o-2024-05-13" silently fell through to the text-only path.
            _VISION_CAPABLE_MODELS = {
                "gpt-4o", "gpt-4-vision", "gpt-4-vision-preview",
                "gpt-4-turbo", "o1", "claude", "gemini",
            }
            # Copilot + any gpt-4 variant → always vision capable (Copilot only serves gpt-4 family)
            _model_lower = specialist_runtime.model.lower()
            _model_supports_vision = (
                (specialist_runtime.provider == "copilot" and (
                    any(vm in _model_lower for vm in _VISION_CAPABLE_MODELS)
                    or "gpt-4" in _model_lower
                ))
                or (specialist_runtime.provider == "nvidia" and (
                    "vision" in _model_lower or "-vl" in _model_lower or "llama-4" in _model_lower
                ))
            )

            # Helper: pre-describe each vision packet as plain text via a vision runtime.
            def _describe_vision_packets_as_text(vision_runtime: "LLMRuntime") -> None:
                for vp in vision_packets:
                    try:
                        b64 = None
                        # Retrieve the MIME type stored as metadata on the vision packet
                        vp_mime = vp.get("_mime_type", "image/jpeg")
                        # Tailor prompt by image source — screen vs webcam
                        _is_screen = vp_mime == "image/png" or "screen" in str(vp.get("_tool_name", ""))
                        if _is_screen:
                            text_prompt = (
                                "You are analysing a screenshot of a computer screen. "
                                "IMPORTANT: You MUST describe what you see. Do not refuse or say the image is too large. "
                                "Describe: (1) what application or website is open, "
                                "(2) what text, content, or UI elements are visible, "
                                "(3) any errors, notifications, or important information on screen. "
                                "Be specific. Start with 'I can see on the screen...'"
                            )
                        else:
                            text_prompt = (
                                "You are analysing a webcam photo. "
                                "IMPORTANT: You MUST describe what you see. Do not refuse or say the image is too large. "
                                "Describe: (1) the person — face, expression, hair, clothing, what they are doing, "
                                "(2) the background — room, objects, lighting, (3) anything else visible. "
                                "Be specific and detailed. Start with 'I can see...'"
                            )
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
                                temperature=0.2,
                                mime_type=vp_mime,
                            )
                            print(f"[VisionPipeline] Image described ({len(description)} chars)", flush=True)
                            # Store description on the vision_packets list so the caller can
                            # return it directly without giving GPT-4o another turn to refuse.
                            vp["_description"] = description
                        else:
                            vp["_description"] = "[Image was captured but could not be decoded for vision analysis]"
                    except Exception as vision_err:
                        print(f"[VisionPipeline] call_chat_with_image failed: {vision_err}", flush=True)
                        vp["_description"] = f"[Vision analysis failed: {vision_err}]"

            # ── UNIFIED VISION PATH ─────────────────────────────────────────────────
            # ALWAYS use call_chat_with_image() for vision — an isolated API call
            # with ONLY the image + prompt (no chat history, no tool specs).
            # 
            # Why: injecting raw image_url into the main messages list combines the
            # image tokens with conversation history + 53 tool specs, easily exceeding
            # Copilot's context window → "data is too massive to process".
            #
            # call_chat_with_image() sends a fresh, minimal request: just the image
            # and one text prompt. The text description is then injected into the
            # main messages so the chat model can reason about it.
            vision_runtime = build_vision_runtime_from_env(specialist_runtime)
            _vision_model_lower = vision_runtime.model.lower()
            _is_vision_capable = (
                (vision_runtime.provider == "copilot"
                 and (any(vm in _vision_model_lower for vm in _VISION_CAPABLE_MODELS) or "gpt-4" in _vision_model_lower))
                or (vision_runtime.provider == "nvidia"
                    and ("vision" in _vision_model_lower or "-vl" in _vision_model_lower or "llama-4" in _vision_model_lower))
            )
            if _is_vision_capable:
                _describe_vision_packets_as_text(vision_runtime)
                # Collect all descriptions and return directly — do NOT give GPT-4o
                # another turn to "interpret" the tool result, it generates a canned refusal.
                descriptions = [vp.get("_description", "") for vp in vision_packets if vp.get("_description")]
                if descriptions:
                    final_desc = "\n\n".join(descriptions)
                    return {"agent": specialist.name, "ok": True, "reply": final_desc}
            else:
                # No vision runtime available — tell user clearly
                provider_label = f"{specialist_runtime.provider}/{specialist_runtime.model}"
                return {
                    "agent": specialist.name,
                    "ok": True,
                    "reply": (
                        f"I captured the image but cannot analyse it because no vision-capable model "
                        f"is configured ({provider_label}). "
                        "Set VISION_PROVIDER=copilot and VISION_MODEL=gpt-4o in your .env to enable vision."
                    ),
                }

    return {"agent": specialist.name, "ok": True, "reply": "Task completed (max steps reached).", "artifacts": tool_artifacts}


def _evaluate_condition(condition: str, step_results: Dict[int, Dict], depends_on: List[int]) -> bool:
    """
    Evaluate a condition string against actual step results.
    
    Supported formats:
    - "only if step N exit_code == 0"
    - "only if step N succeeded"
    - "only if step N ok == true"
    - "only if step N failed"
    
    Args:
        condition: Condition string from plan
        step_results: Dict of step_id -> result data
        depends_on: List of dependency step IDs
        
    Returns:
        True if condition is met, False otherwise
    """
    import re
    
    condition_lower = condition.lower().strip()
    
    # Pattern: "only if step N <field> == <value>"
    match = re.search(r'step\s+(\d+)\s+(\w+)\s*==\s*(.+)', condition_lower)
    if match:
        step_id = int(match.group(1))
        field = match.group(2).strip()
        expected_value = match.group(3).strip().strip('"\'')
        
        if step_id not in step_results:
            return False
        
        result = step_results[step_id]
        actual_value = result.get(field)
        
        # Type conversion for comparison
        if expected_value.isdigit():
            expected_value = int(expected_value)
        elif expected_value in ('true', 'false'):
            expected_value = expected_value == 'true'
        
        return actual_value == expected_value
    
    # Pattern: "only if step N succeeded"
    match = re.search(r'step\s+(\d+)\s+succeeded', condition_lower)
    if match:
        step_id = int(match.group(1))
        if step_id not in step_results:
            return False
        return step_results[step_id].get("ok", False)
    
    # Pattern: "only if step N failed"
    match = re.search(r'step\s+(\d+)\s+failed', condition_lower)
    if match:
        step_id = int(match.group(1))
        if step_id not in step_results:
            return False
        return not step_results[step_id].get("ok", False)
    
    # Default: check if all dependencies succeeded
    for dep_id in depends_on:
        dep_result = step_results.get(dep_id, {})
        if not dep_result.get("ok", False):
            return False
    
    return True


# ─────────────────────────────────────────────────────────────────────────────
# PROACTIVE INTELLIGENCE HELPERS (Steps 6, 7a)
# ─────────────────────────────────────────────────────────────────────────────

def _classify_interaction(agent_names: List[str], user_text: str) -> str:
    """
    Classify an interaction type for behavioral fingerprint recording.

    Returns one of: "code", "write", "search", "system", "general"
    """
    import re as _re
    agent_set = set(agent_names)
    if "CodeAgent" in agent_set:
        return "code"
    if "ContentAgent" in agent_set:
        return "write"
    if "WebAgent" in agent_set:
        return "search"
    if agent_set & {"SystemAgent", "TerminalAgent", "FileAgent"}:
        return "system"
    # Heuristic on user text
    _text_lower = user_text.lower()
    if _re.search(r'\b(code|debug|fix|refactor|write.*function|class|def |import )\b', _text_lower):
        return "code"
    if _re.search(r'\b(write|draft|essay|poem|blog|script|content)\b', _text_lower):
        return "write"
    if _re.search(r'\b(search|find|look up|google|research|what is|who is)\b', _text_lower):
        return "search"
    if _re.search(r'\b(run|execute|install|open|launch|start|stop|kill|terminal)\b', _text_lower):
        return "system"
    return "general"


def _append_follow_up_hint(
    reply: str, user_text: str, workspace_root: Path
) -> str:
    """Append lightweight follow-up hints to a reply when useful."""
    try:
        tail = ""
        reply_lower = reply.lower()

        if tail:
            return reply + tail

        # 1. Deadline within 2 hours
        try:
            from datetime import datetime as _dt
            from tools.task_ops import task_op as _task_op  # type: ignore
            _r = _task_op(action="list")
            if _r.get("status") == "success":
                for _t in _r.get("tasks", []):
                    if _t.get("status") in ("pending", "in_progress") and _t.get("deadline"):
                        try:
                            _dl = _dt.strptime(_t["deadline"], "%Y-%m-%d %H:%M")
                            _mins_left = (_dl - _dt.now()).total_seconds() / 60
                            if 0 < _mins_left <= 120:
                                tail = (
                                    f"\n\n⏰ By the way, **{_t['title']}** is due in "
                                    f"{int(_mins_left)} minutes."
                                )
                                break
                        except Exception:
                            pass
        except Exception:
            pass

        if tail:
            return reply + tail

        # 3. Code fix/error heuristic
        _code_fixed = any(k in reply_lower for k in ("fixed", "bug fixed", "error resolved", "patched"))
        _code_error = any(k in reply_lower for k in ("error", "traceback", "exception"))
        if _code_fixed or _code_error:
            tail = "\n\nWant me to run the tests to verify?"

        if tail:
            return reply + tail

        # 4. Terminal install heuristic
        if any(k in reply_lower for k in ("installed", "successfully installed", "setup complete")):
            tail = "\n\nWant me to launch it now?"

    except Exception:
        pass

    return reply + tail if tail else reply


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
        # Attach runtime to MemoryManager so fact extraction + summarization work
        try:
            from memory import get_memory_manager
            get_memory_manager(workspace_root).attach_runtime(runtime)
        except Exception:
            pass

    def run(self, user_text: str, messages: List[Dict[str, Any]]) -> str:
        """
        Full orchestration pipeline:
          ContextAgent -> Supervisor -> [Fan-Out specialist(s)] -> Synthesizer -> reply
        """
        import time as _time
        _start_ts = _time.time()  # Step 7a: track interaction duration

        print(f"[Orchestrator.run] ENTRY: user_text='{user_text[:80]}'", flush=True)
        print(f"[Orchestrator] Starting Supervisor routing for: {user_text[:50]}...", flush=True)

        # ── MEMORY: Inject/refresh long-term context into messages ──────────
        try:
            from memory import get_memory_manager
            _mem = get_memory_manager(self.workspace_root)
            _mem.inject_into_messages(messages, user_query=user_text)
        except Exception:
            pass

        # 1. Supervisor routes the request
        # Generate an interaction ID for FeedbackEngine tracking
        _interaction_id: Optional[str] = None
        _fb_eng = None
        try:
            from tools.feedback_engine import get_instance as _get_fb
            _fb_eng = _get_fb()
            if _fb_eng is not None:
                _interaction_id = _fb_eng.new_interaction()
        except Exception:
            pass

        supervisor_history = _extract_clean_history(messages, max_turns=4)
        routing_text = user_text
        
        routing = self.supervisor.route(routing_text, history=supervisor_history)
        print(f"[Supervisor] Routed to: {routing.get('agents', [])} (parallel={routing.get('parallel', False)})", flush=True)
        agent_names: List[str] = routing["agents"]
        parallel: bool = routing["parallel"]
        reasoning: str = routing.get("reasoning", "")
        confidence: float = routing.get("confidence", 1.0)  # UPGRADE 13: Read confidence score
        
        # DUAL ROUTING PROTOCOL: If confidence < 0.65, run both primary and fallback
        if confidence < 0.65 and len(agent_names) == 1:
            primary = agent_names[0]
            fallback_map = {
                "FileAgent": "TerminalAgent",
                "WebAgent": "GeneralAgent",
                "SystemAgent": "TerminalAgent",
                "CodeAgent": "TerminalAgent",
                "MusicAgent": "GeneralAgent",
            }
            if primary in fallback_map:
                fallback_agent = fallback_map[primary]
                agent_names.append(fallback_agent)
                print(f"[DualRouting] Low confidence ({confidence:.2f}) - adding fallback: {fallback_agent}", flush=True)

        # Record routing decision in FeedbackEngine
        if _interaction_id:
            try:
                _fb_eng.record_routing(_interaction_id, agent_names, reasoning, user_text)
            except Exception:
                pass

        # Single GeneralAgent -> just use the full agent runtime (cheaper, faster)
        if agent_names == ["GeneralAgent"]:
            return self._run_general(routing_text, messages, routing_reason=reasoning)

        # PLANNER AGENT: intercept and execute planned tasks
        if agent_names == ["PlannerAgent"]:
            return self._run_planned_task(user_text, messages)

        # Override lazy GeneralAgent routing: if the Supervisor chose only GeneralAgent
        # but the user text clearly maps to a specialist, re-route to the right agent.

        specialists = [SPECIALIST_MAP[n] for n in agent_names if n in SPECIALIST_MAP]
        if not specialists:
            return self._run_general(routing_text, messages, routing_reason=reasoning)

        if len(specialists) == 1 and "capabilities" in reasoning.lower():
            reply = self._run_specialist_capability_query(specialists[0], user_text)
            self._append_to_messages(messages, user_text, reply)
            try:
                from memory import get_memory_manager
                get_memory_manager(self.workspace_root).save("assistant", reply, interface="orchestrator")
            except Exception:
                pass
            return reply

        # TIME LORD: Force sequential if a producer->consumer dependency is detected.
        # ASSEMBLY LINE: ContentAgent produces text -> FileAgent saves -> SystemAgent opens.
        # All three are in a strict dependency chain - always sequential.
        _EXTERNAL_PRODUCERS = {"ContentAgent", "FileAgent", "WebAgent"}
        _CONSUMERS = {"FileAgent", "SystemAgent", "CodeAgent"}
        agent_name_set = set(agent_names)
        if (_EXTERNAL_PRODUCERS & agent_name_set) and (_CONSUMERS & agent_name_set):
            parallel = False  # override Supervisor - baton must be passed sequentially

        # 2. Fan-Out: run specialists (parallel or sequential)
        results: List[Dict[str, Any]] = []
        if parallel and len(specialists) > 1:
            results = self._fan_out_parallel(specialists, user_text)
        else:
            # Store messages for history extraction
            self.messages = messages
            results = self._run_sequential_with_context(specialists, user_text)

        # 2b. Handoff chain: run any agent-suggested follow-ups sequentially
        extra_results = self._run_handoff_chain(
            results=results,
            conversation_history=_extract_clean_history(messages, max_turns=6),
        )
        if extra_results:
            results.extend(extra_results)

        # 3. Fan-In: if only one result, return it directly
        if len(results) == 1:
            reply = results[0].get("reply", "")
            self._append_to_messages(messages, user_text, reply)
            # Save assistant reply to memory
            try:
                from memory import get_memory_manager
                get_memory_manager(self.workspace_root).save("assistant", reply, interface="orchestrator")
            except Exception:
                pass
            # Step 7a: Record behavioral fingerprint
            try:
                import time as _time
                from tools.behavioral_pattern_learner import BehavioralPatternLearner  # type: ignore
                BehavioralPatternLearner(self.workspace_root).record_fingerprint(
                    interaction_type=_classify_interaction(agent_names, user_text),
                    duration_sec=int(_time.time() - _start_ts),
                    tools_used=agent_names,
                    context=user_text[:120],
                )
            except Exception:
                pass
            # Step 6: Append follow-up hint
            reply = _append_follow_up_hint(reply, user_text, self.workspace_root)
            return reply

        # 4. Synthesize multiple results
        reply = self._synthesize(user_text, results)
        self._append_to_messages(messages, user_text, reply)
        # Save synthesized reply to memory
        try:
            from memory import get_memory_manager
            get_memory_manager(self.workspace_root).save("assistant", reply, interface="orchestrator")
        except Exception:
            pass
        # Step 7a: Record behavioral fingerprint
        try:
            import time as _time2
            from tools.behavioral_pattern_learner import BehavioralPatternLearner  # type: ignore
            BehavioralPatternLearner(self.workspace_root).record_fingerprint(
                interaction_type=_classify_interaction(agent_names, user_text),
                duration_sec=int(_time2.time() - _start_ts),
                tools_used=agent_names,
                context=user_text[:120],
            )
        except Exception:
            pass
        # Step 6: Append follow-up hint
        reply = _append_follow_up_hint(reply, user_text, self.workspace_root)
        return reply

    def _run_sequential_with_context(
        self, specialists: List[SpecialistAgent], task: str
    ) -> List[Dict[str, Any]]:
        """Run specialists one by one, passing each result as context to the next.

        Implements the full sequential coordination protocol:
        - BATON PASS: Orchestrator sniffs artifacts (file paths, URLs) from each
          agent's reply and hands them explicitly to the next agent.
        - TELEPATHY: Prior context is injected directly into the next agent's
          system prompt - not just appended to the task. The agent *knows* what
          happened before it even reads the task.
        - TIME LORD: Sequential execution guarantees producers finish before
          consumers start. Files exist before they are opened.
        """
        results: List[Dict[str, Any]] = []
        prior_context_block: Optional[str] = None  # injected into system prompt of next agent

        # Extract clean conversation history for context continuity
        conversation_history = _extract_clean_history(self.messages, max_turns=6) if hasattr(self, "messages") else []

        queue: List[tuple[SpecialistAgent, Optional[str]]] = [(sp, None) for sp in specialists]
        seen_handoffs: set = set()
        idx = 0
        while idx < len(queue):
            sp, task_override = queue[idx]
            idx += 1
            current_task = task_override or task
            result = _run_specialist(
                sp, current_task, self.runtime, self.workspace_root,
                prior_context=prior_context_block,
                conversation_history=conversation_history,
            )

            # -- HYDRA PROTOCOL: Error Interceptor  -------------------------
            # If the agent failed, look up the Escalation Matrix and reroute
            # to a backup agent with a Post-Mortem Injection context prompt.
            # Capped at 1 retry per agent to prevent infinite loops.
            reply = result.get("reply", "")
            _reply_lower = reply.lower() if reply else ""
            agent_failed = (
                not result.get("ok", True)
                or reply.startswith("[Error]")
                or "Tool not found" in reply
                or "Permission denied" in reply
                or "timed out" in _reply_lower
                # ── Copout detection: LLM gave up instead of using tools ──
                or (len(reply.strip()) < 15 and not reply.strip().startswith("Done"))
                or "i can't" in _reply_lower
                or "i cannot" in _reply_lower
                or "i'm unable" in _reply_lower
                or "i am unable" in _reply_lower
                or "not possible for me" in _reply_lower
                or "beyond my capabilities" in _reply_lower
                or "outside my scope" in _reply_lower
                or "as an ai" in _reply_lower
                or "i don't have the ability" in _reply_lower
                or "i don't have access" in _reply_lower
            )
            if agent_failed and sp.name in _ESCALATION_MATRIX:
                backup_name, failure_note = _ESCALATION_MATRIX[sp.name]
                backup_sp = SPECIALIST_MAP.get(backup_name)
                if backup_sp and backup_sp.name != sp.name or (backup_sp and backup_sp.name == sp.name):
                    print(
                        f"[Hydra] [WARN] {sp.name} failed -> rerouting to {backup_name}",
                        flush=True,
                    )
                    post_mortem = (
                        f"SYSTEM ALERT - HYDRA REROUTE:\n"
                        f"Original request: {task}\n"
                        f"{sp.name} already tried and failed with: {reply[:300]}\n\n"
                        f"BACKUP MISSION: {failure_note}\n"
                        f"Achieve the SAME goal using YOUR tools. Do not repeat the failed approach."
                    )
                    backup_result = _run_specialist(
                        backup_sp, task, self.runtime, self.workspace_root,
                        prior_context=post_mortem,
                        conversation_history=conversation_history,
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
                artifacts = _merge_artifacts(reply, result.get("artifacts"))
                # Build the Telepathy block for the next agent
                prior_context_block = _build_prior_context_block(
                    result.get("agent", sp.name), reply, artifacts
                )
                # HANDOFF CHAIN: enqueue suggested next agents (sequential)
                for handoff in artifacts.get("handoffs", []):
                    parsed = self._parse_handoff(handoff)
                    if not parsed:
                        continue
                    agent_name, handoff_task = parsed
                    if not handoff_task:
                        continue
                    key = (agent_name, handoff_task.strip().lower())
                    if key in seen_handoffs:
                        continue
                    if len(seen_handoffs) >= _MAX_HANDOFF_STEPS:
                        break
                    next_sp = SPECIALIST_MAP.get(agent_name)
                    if not next_sp:
                        continue
                    seen_handoffs.add(key)
                    queue.append((next_sp, handoff_task))

            # AUDIT LOG: record agent name, tools used, and artifacts to .ankita/audit.jsonl
            self._write_audit(sp.name, result)

        return results

    def _run_handoff_chain(
        self,
        results: List[Dict[str, Any]],
        conversation_history: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Run agent-suggested handoffs after initial fan-out results."""
        extra: List[Dict[str, Any]] = []
        seen: set = set()
        for r in results:
            reply = r.get("reply", "") or ""
            if not reply:
                continue
            artifacts = _merge_artifacts(reply, r.get("artifacts"))
            if not artifacts.get("handoffs"):
                continue
            prior_context_block = _build_prior_context_block(r.get("agent", "Agent"), reply, artifacts)
            for handoff in artifacts.get("handoffs", []):
                parsed = self._parse_handoff(handoff)
                if not parsed:
                    continue
                agent_name, handoff_task = parsed
                if not handoff_task:
                    continue
                key = (agent_name, handoff_task.strip().lower())
                if key in seen:
                    continue
                if len(seen) >= _MAX_HANDOFF_STEPS:
                    return extra
                next_sp = SPECIALIST_MAP.get(agent_name)
                if not next_sp:
                    continue
                seen.add(key)
                extra.append(
                    _run_specialist(
                        next_sp,
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
        """Parse SUGGEST_NEXT/HANDOFF lines into (agent_name, task)."""
        m = re.search(r"(SUGGEST_NEXT|HANDOFF):\s*(\w+Agent)\s*→\s*(.+)$", handoff)
        if not m:
            return None
        agent_name = m.group(2).strip()
        task = m.group(3).strip()
        return (agent_name, task)

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
                "content_payload_valid": result.get("content_payload_valid"),
                "content_payload_errors": result.get("content_payload_errors", []),
                "content_payload_repaired": result.get("content_payload_repaired"),
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
        """
        Dispatch specialists concurrently and collect results.
        
        Each specialist has a 120s timeout to prevent hanging.
        """
        results = [None] * len(specialists)
        STEP_TIMEOUT = 120  # 2 minutes max per specialist
        
        with ThreadPoolExecutor(max_workers=min(len(specialists), 4)) as executor:
            future_to_idx = {
                executor.submit(_run_specialist, sp, task, self.runtime, self.workspace_root): i
                for i, sp in enumerate(specialists)
            }
            
            # Collect results with timeout
            for future in as_completed(future_to_idx, timeout=STEP_TIMEOUT * len(specialists)):
                idx = future_to_idx[future]
                try:
                    # Get result with per-future timeout
                    results[idx] = future.result(timeout=STEP_TIMEOUT)
                except TimeoutError:
                    results[idx] = {
                        "agent": specialists[idx].name,
                        "ok": False,
                        "reply": f"[Timeout] Agent exceeded {STEP_TIMEOUT}s limit"
                    }
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

    def _run_general(self, user_text: str, messages: List[Dict[str, Any]], routing_reason: str = "") -> str:
            """Fallback: use full AgentRuntime-style loop with all tools."""
            print(f"[Orchestrator._run_general] Starting with user_text: {user_text[:100]}...", flush=True)
            capability_mode = _is_capability_routing_reason(routing_reason)
            if capability_mode:
                return self._run_capability_inventory(
                    user_text=user_text,
                    tool_specs=TOOL_SPECS,
                    scope_label="A.N.K.I.T.A overall",
                )
            else:
                direct_messages = list(messages)
            direct_messages.append({"role": "user", "content": user_text})
            try:
                response = call_chat_once(self.runtime, direct_messages, tools=None, max_tokens=240)
                result = (response.get("content") or "").strip()
                if result:
                    try:
                        from memory import get_memory_manager
                        get_memory_manager(self.workspace_root).save("assistant", result, interface="orchestrator")
                    except Exception:
                        pass
                    print(f"[Orchestrator._run_general] Completed direct LLM reply", flush=True)
                    return result
            except Exception as err:
                print(f"[Orchestrator._run_general] Direct LLM path failed: {err}", flush=True)
            from agent_runtime import AgentRuntime
            agent = AgentRuntime(runtime=self.runtime, workspace_root=self.workspace_root)
            messages.append({"role": "user", "content": user_text})
            try:
                result = agent.run_turn(messages, tools=TOOL_SPECS)
                # Save assistant reply to memory
                try:
                    from memory import get_memory_manager
                    get_memory_manager(self.workspace_root).save("assistant", result, interface="orchestrator")
                except Exception:
                    pass
                print(f"[Orchestrator._run_general] Completed successfully", flush=True)
                return result
            except Exception as err:
                print(f"[Orchestrator._run_general] Error: {err}", flush=True)
                if messages and messages[-1].get("role") == "user":
                    messages.pop()
                return f"[Error] {err}"

    def _run_specialist_capability_query(self, specialist: SpecialistAgent, user_text: str) -> str:
            """Answer domain capability questions from actual tool specs, not stale action history."""
            return self._run_capability_inventory(
                user_text=user_text,
                tool_specs=specialist.tool_specs,
                scope_label=specialist.name,
            )

    def _run_capability_inventory(
        self,
        user_text: str,
        tool_specs: List[Dict[str, Any]],
        scope_label: str,
    ) -> str:
            payload = []
            for spec in tool_specs:
                fn = spec.get("function", {})
                payload.append(
                    {
                        "name": fn.get("name", ""),
                        "description": fn.get("description", ""),
                    }
                )
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
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "scope": scope_label,
                            "question": user_text,
                            "tools": payload,
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            try:
                response = call_chat_once(self.runtime, messages, tools=None, max_tokens=420)
                result = (response.get("content") or "").strip()
                if result:
                    return result
            except Exception as err:
                print(f"[Orchestrator._run_capability_inventory] Error: {err}", flush=True)
            names = ", ".join(sorted(item["name"] for item in payload if item.get("name")))
            return f"Available tools in {scope_label}: {names}"


    def _append_to_messages(
        self, messages: List[Dict[str, Any]], user_text: str, reply: str
    ) -> None:
        """Append the user/assistant turn to the shared message history."""
        # Only append if user message is not already there
        if not messages or messages[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": reply})

    def _run_planned_task(self, user_text: str, messages: List[Dict[str, Any]]) -> str:
        """
        Execute a planned multi-step task using PlannerAgent.
        
        Workflow:
        1. Call PlannerAgent to generate a structured JSON plan
        2. Parse the plan and validate it
        3. Execute steps sequentially, respecting dependencies
        4. Handle conditionals and parallel execution
        5. Synthesize final result
        """
        import time as _time
        
        # Step 1: Call PlannerAgent to generate the plan
        planner_specialist = SPECIALIST_MAP.get("PlannerAgent")
        if not planner_specialist:
            return "❌ PlannerAgent not available."
        
        # Extract clean conversation history for context
        conversation_history = _extract_clean_history(messages, max_turns=6)
        
        # Build messages for PlannerAgent
        planner_messages = planner_specialist.make_messages(user_text, history=conversation_history)
        
        try:
            planner_runtime = get_agent_runtime("PlannerAgent", self.runtime)
            response = call_chat_once(planner_runtime, planner_messages, tools=None, max_tokens=1500)
            plan_content = (response.get("content") or "").strip()
        except Exception as err:
            return f"❌ PlannerAgent failed: {err}"
        
        # Step 2: Parse the JSON plan
        try:
            # Extract JSON from markdown code fences if present
            import re as _re
            json_match = _re.search(r"```(?:json)?\s*([\s\S]*?)```", plan_content)
            if json_match:
                plan_json_str = json_match.group(1).strip()
            else:
                # Try to find the first {...} block
                brace_match = _re.search(r"\{[\s\S]*\}", plan_content)
                if brace_match:
                    plan_json_str = brace_match.group(0)
                else:
                    plan_json_str = plan_content
            
            plan = json.loads(plan_json_str)
            goal = plan.get("goal", "")
            steps = plan.get("steps", [])
            
            if not steps:
                return "❌ PlannerAgent produced an empty plan."
            
        except json.JSONDecodeError as err:
            return f"❌ Failed to parse plan JSON: {err}\n\nPlan output:\n{plan_content[:500]}"
        
        # Step 3: Log the plan to audit
        try:
            audit_path = self.workspace_root / ".ankita" / "audit.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            plan_entry = {
                "type": "plan",
                "ts": _time.time(),
                "user_request": user_text,
                "goal": goal,
                "plan": plan,
                "steps_count": len(steps),
            }
            with audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(plan_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # Audit failures must never crash the main flow
        
        # Step 4: Show the plan to the user (optional but great UX)
        plan_preview_lines = [f"📋 Plan: {len(steps)} steps"]
        for step in steps:
            step_id = step.get("id", "?")
            agent = step.get("agent", "?")
            task_preview = step.get("task", "")[:60]
            plan_preview_lines.append(f"  {step_id}. {agent} → {task_preview}...")
        plan_preview = "\n".join(plan_preview_lines)
        print(f"\n{plan_preview}\n", flush=True)
        
        # Step 5: Execute steps sequentially
        step_results: Dict[int, Dict[str, Any]] = {}
        steps_executed = 0
        steps_skipped = 0
        start_time = _time.time()
        
        for step in steps:
            step_id = step.get("id")
            agent_name = step.get("agent")
            task = step.get("task")
            depends_on = step.get("depends_on", [])
            condition = step.get("condition")
            
            # Check dependencies
            for dep_id in depends_on:
                if dep_id not in step_results:
                    return f"❌ Step {step_id} depends on step {dep_id} which hasn't completed yet."
                if not step_results[dep_id].get("ok", False):
                    return f"❌ Step {step_id} depends on step {dep_id} which failed."
            
            # Evaluate condition if present
            if condition:
                # Parse and evaluate condition against actual step results
                # Supported formats:
                # - "only if step N exit_code == 0"
                # - "only if step N succeeded"
                # - "only if step N ok == true"
                condition_met = _evaluate_condition(condition, step_results, depends_on)
                
                if not condition_met:
                    print(f"Step {step_id}/{len(steps)} — [CONDITION: {condition} ❌] — SKIPPED", flush=True)
                    steps_skipped += 1
                    continue
            
            # Execute the step
            print(f"Step {step_id}/{len(steps)} — {agent_name}: {task[:60]}...", flush=True)
            
            specialist = SPECIALIST_MAP.get(agent_name)
            if not specialist:
                return f"❌ Agent {agent_name} not found for step {step_id}."
            
            # Build prior context from previous steps
            prior_context_parts = []
            for dep_id in depends_on:
                dep_result = step_results.get(dep_id, {})
                dep_agent = dep_result.get("agent", "PreviousAgent")
                dep_reply = dep_result.get("reply", "")
                if dep_reply:
                    artifacts = _extract_artifacts(dep_reply)
                    context_block = _build_prior_context_block(dep_agent, dep_reply, artifacts)
                    prior_context_parts.append(context_block)
            
            prior_context = "\n\n".join(prior_context_parts) if prior_context_parts else None
            
            # Run the specialist
            result = _run_specialist(
                specialist, task, self.runtime, self.workspace_root,
                prior_context=prior_context,
                conversation_history=conversation_history,
            )
            
            step_results[step_id] = result
            steps_executed += 1
            
            # Show result preview
            reply_preview = (result.get("reply", "") or "")[:80]
            status = "✅" if result.get("ok", True) else "❌"
            print(f"  {status} {reply_preview}", flush=True)
            
            # If step failed and no HYDRA backup, stop execution
            if not result.get("ok", True):
                return f"❌ Step {step_id} failed: {result.get('reply', 'Unknown error')}"
        
        # Step 6: Synthesize final result
        total_time_ms = int((_time.time() - start_time) * 1000)
        
        # Update audit with execution results
        try:
            plan_entry["steps_executed"] = steps_executed
            plan_entry["steps_skipped"] = steps_skipped
            plan_entry["total_time_ms"] = total_time_ms
            with audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(plan_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        
        # Collect all step results for synthesis
        all_results = list(step_results.values())
        
        if len(all_results) == 1:
            # Single step - return directly
            reply = all_results[0].get("reply", "")
            self._append_to_messages(messages, user_text, reply)
            return reply
        
        # Multiple steps - synthesize
        reply = self._synthesize(user_text, all_results)
        self._append_to_messages(messages, user_text, reply)
        return reply


