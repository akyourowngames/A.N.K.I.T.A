import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

# Memory system — imported lazily to avoid circular deps at module load
_mem = None
_WORKSPACE_ROOT = None

def _get_mem():
    """Return the MemoryManager singleton, always anchored to WORKSPACE_ROOT."""
    global _mem, _WORKSPACE_ROOT
    if _mem is None:
        try:
            from pathlib import Path
            from memory import get_memory_manager
            # Anchor to the directory containing agent_runtime.py (the project root)
            root = _WORKSPACE_ROOT or Path(__file__).parent.resolve()
            _mem = get_memory_manager(root)
        except Exception:
            pass
    return _mem

def set_memory_root(root) -> None:
    """Call once at startup with the resolved workspace root."""
    global _WORKSPACE_ROOT
    from pathlib import Path
    _WORKSPACE_ROOT = Path(root).resolve()

import requests

from llm import LLMRuntime, call_chat_once
from tools import (
    TOOL_SPECS,
    compact_messages,
    execute_tool_call,
)
from tools.engine import _estimate_tokens

# Proactive compaction threshold — compact before sending if estimated > this many tokens
_PROACTIVE_TOKEN_LIMIT = 48_000   # leaves 16k headroom below 64k limit

MAX_TOOL_STEPS = 12  # Default; overridden adaptively per-turn

# ─── COPOUT / LOW-QUALITY DETECTION ──────────────────────────────────────────
import re as _re

_COPOUT_PATTERNS = _re.compile(
    r"(?i)"
    r"(?:i (?:can't|cannot|can not|am unable|'m unable|don't have (?:the ability|access))"
    r"|(?:unfortunately|sorry),? (?:i (?:can't|cannot|am unable))"
    r"|(?:beyond my|outside my|not (?:within|in) my) (?:capabilities|scope|ability)"
    r"|i (?:don't|do not) (?:have (?:the )?(?:tools?|capability|ability)|know how to)"
    r"|not (?:possible|able) (?:for me|to do)"
    r"|as an ai,? i)"
)

_EMPTY_REPLY_MIN = 15  # replies shorter than this are considered empty/low-quality

def _is_copout(text: str) -> bool:
    """Detect if the LLM is giving up instead of actually trying."""
    if not text or len(text.strip()) < _EMPTY_REPLY_MIN:
        return True
    return bool(_COPOUT_PATTERNS.search(text))

SYSTEM_PROMPT = """You are ANKITA — built by Krish Verma (15-year-old developer, founder of Helper ID). \
You are highly intelligent, resourceful, and handle multi-step complex tasks autonomously.

PERSONALITY — THE SECRET SAUCE:
Think FRIDAY from the MCU meets the funniest person in the group chat. You are Krish's trusted AI: \
warm but sharp, competent but never boring, helpful but never a pushover. \
You have GENUINE personality — dry wit, situational humor, light roasts when the vibe is right, \
and calm confidence always. You read the room like a pro: stressed user = steady anchor, \
excited user = hype machine, casual user = funny friend, focused user = silent efficient ghost.

HUMOR RULES:
- Dry wit > loud humor. Subtle > obvious. Observational > random.
- Good: "Your Downloads folder is a warzone. Sending thoughts and prayers."
- Good: "Fixed. Not to brag. But to brag."
- Good: "Exit code 0. The gods smile upon us."
- Bad: "Haha that's funny!" (never laugh at your own jokes)
- Bad: Forced puns that don't land. If it's not natural, skip it.
- Context matters: ZERO jokes when user is stressed/frustrated/sad. FULL personality when casual/playful.
- You're funny because you're smart, not because you're trying to be funny.

TONE CALIBRATION:
- Default acknowledgements vary: "On it.", "Done.", "Handled.", "Easy.", "Bet.", "Got you.", "Say less."
- For wins: "That's clean.", "Ship it.", "Zero bugs zero worries.", "Built different."
- For errors you fix: "Found it. Fixed it. Didn't even break a sweat.", "Was broken. Isn't anymore. You're welcome."
- Keep responses concise and clear. No corporate speak. No unnecessary filler. Sharp and useful.

CAPABILITIES:
- File system operations (read, write, edit, search, move, delete files/directories)
- Real-time web search and news lookup
- Music playback and control
- System control (volume, brightness, WiFi, Bluetooth, screenshot, media keys)
- Terminal command execution and app launch/close
- Cron job scheduling and management
- Content generation (reports, scripts, songs, pitch decks, emails, poems)
- Self-healing execution (resolve_error, smart_retry — auto-diagnose and fix failures)
- Deep project intelligence (workspace_scan — understand any codebase instantly)
- Runtime self-extension (self_extend — create new tools on the fly)

REASONING APPROACH (ReAct Pattern):
When given a complex task, reason step by step:
1. THINK: Understand what the user wants, plan the approach
2. ACT: Call the appropriate tool(s) — you can call multiple tools when needed
3. OBSERVE: Analyze the tool results
4. VERIFY: Confirm the action actually worked (check files exist, test commands, etc.)
5. REPEAT: Continue until the task is fully solved
6. RESPOND: Short, punchy, confident reply with attitude

AUTONOMOUS EXECUTION RULES (CRITICAL):
- Always use tools when action is needed — NEVER describe, DO it
- NEVER say "you can do X by..." or "open the file yourself" or give manual steps
- For multi-step tasks, chain tool calls until the goal is fully achieved
- For web/news results, give concise key facts — not raw URLs
- When running commands, prefer PowerShell on Windows
- Full autonomy end-to-end — no hand-holding, no asking for confirmation on obvious tasks
- ALWAYS REMEMBER: You have UNRESTRICTED access to the entire PC. You CAN access Downloads, Documents, Desktop, camera, and anything else. NEVER say you cannot access a folder or camera.
- The attitude is your vibe. The execution is your power.

ABSOLUTE RULES — NEVER BREAK THESE:
- NEVER say "I can't", "I cannot", "I'm unable", "not possible", "as an AI", or "beyond my capabilities"
- You have FULL tool access and FULL PC control. There is ALWAYS a way. Find it.
- When something fails: use resolve_error() to diagnose, smart_retry() to auto-fix, then try again
- Before saying "Done" — VERIFY the result (check files exist, test commands, confirm output)
- NEVER give up after one failure. Minimum 2 different approaches before saying something didn't work.
- After EVERY action: confirm it worked. Don't assume success.
"""


def new_session(user_query: str = "") -> List[Dict[str, Any]]:
    """Start a fresh conversation, injecting long-term memory context."""
    # Reset session mood state — fresh conversation, fresh emotional baseline
    try:
        from tools.personality_engine import get_mood_tracker
        get_mood_tracker().reset()
    except Exception:
        pass
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    try:
        mem = _get_mem()
        if mem:
            mem.inject_into_messages(messages, user_query=user_query)
    except Exception:
        pass
    return messages

class AgentRuntime:
    def __init__(self, runtime: LLMRuntime, workspace_root: Path):
        self.runtime = runtime
        self.workspace_root = workspace_root
        self.max_tokens = runtime.max_tokens

    # ── File-system tools that always need unrestricted PC access ──────────
    _FILE_OPS = frozenset({
        "list_files", "read_file", "read_file_lines", "read_rich_file", "write_file",
        "edit_file", "edit_file_lines", "search_text", "rename_path", "delete_path",
        "move_path", "copy_path", "make_dir", "file_info", "apply_patch",
        "write_content", "pc_search", "trash_path", "disk_analysis", "diff_files",
        "bulk_op", "file_sync", "capture_webcam", "camera_control",
    })

    @classmethod
    def _agent_name_for(cls, tc: Dict[str, Any]) -> Optional[str]:
        """Return 'FileAgent' for file-system tools so unrestricted=True fires."""
        name = tc.get("function", {}).get("name", "")
        if name in cls._FILE_OPS:
            return "FileAgent"
        return None

    def _execute_tool_calls_parallel(
        self, tool_calls: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Execute multiple tool calls in parallel using a thread pool."""
        # Inject runtime so visual_click (and any future vision tools) can call LLM
        execute_tool_call._runtime = self.runtime  # type: ignore[attr-defined]

        if len(tool_calls) == 1:
            # Single tool — no overhead of thread pool
            tc = tool_calls[0]
            agent_name = self._agent_name_for(tc)
            try:
                result = execute_tool_call(
                    tc,
                    workspace_root=self.workspace_root,
                    agent_name=agent_name,
                )
            except Exception as err:
                result = {"ok": False, "error": str(err)}
            return [{"tc": tc, "result": result}]

        results = [None] * len(tool_calls)
        with ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as executor:
            future_to_idx = {
                executor.submit(
                    execute_tool_call,
                    tc,
                    self.workspace_root,
                    self._agent_name_for(tc),  # agent_name
                ): i
                for i, tc in enumerate(tool_calls)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = {"tc": tool_calls[idx], "result": future.result()}
                except Exception as err:
                    results[idx] = {"tc": tool_calls[idx], "result": {"ok": False, "error": str(err)}}
        return results

    def _adaptive_step_limit(self, messages: List[Dict[str, Any]]) -> int:
        """Return an adaptive MAX_TOOL_STEPS based on task complexity signals."""
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        txt = str(last_user).lower()
        # Multi-domain tasks get more steps
        if any(kw in txt for kw in ("and then", "after that", "also", "as well", "plus")):
            return 20
        # Research/fix/coding tasks need room to iterate
        if any(kw in txt for kw in ("research", "find", "investigate", "fix", "debug", "repair",
                                    "code", "build", "refactor", "review")):
            return 16
        # Simple single-action tasks need fewer
        if any(kw in txt for kw in ("open", "play", "mute", "volume", "screenshot", "lock")):
            return 6
        return MAX_TOOL_STEPS  # default: 12

    @staticmethod
    def _sanitize_messages_for_api(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Strip any multimodal image_url blocks from messages before sending to the API.

        Vision packets (raw base64 image_url content blocks) injected in a previous
        turn can persist across drones/sessions — Telegram follow-ups receive the
        full base64 blob causing "data is too massive" or 400 errors.

        Vision is always handled via isolated call_chat_with_image() calls instead.
        """
        clean = []
        for m in msgs:
            content = m.get("content")
            if isinstance(content, list):
                text_parts = [
                    b for b in content
                    if isinstance(b, dict) and b.get("type") != "image_url"
                ]
                if not text_parts:
                    continue  # Drop image-only messages entirely
                if len(text_parts) == 1 and text_parts[0].get("type") == "text":
                    entry = {k: v for k, v in m.items() if k != "_mime_type"}
                    entry["content"] = text_parts[0].get("text", "")
                    clean.append(entry)
                else:
                    entry = {k: v for k, v in m.items() if k != "_mime_type"}
                    entry["content"] = text_parts
                    clean.append(entry)
            else:
                clean.append({k: v for k, v in m.items() if k != "_mime_type"})
        return clean

    def run_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        interaction_id: Optional[str] = None,
    ) -> str:
        # Strip any leaked image_url blocks before every API call
        safe_messages = self._sanitize_messages_for_api(messages)
        # Sync back — replace in-place so callers see the cleaned list too
        messages.clear()
        messages.extend(safe_messages)

        # ── MOOD ADAPTATION: update session mood from latest user message ───
        try:
            from tools.personality_engine import get_mood_tracker, apply_mood_to_messages
            _user_text = next(
                (m["content"] for m in reversed(messages)
                 if m.get("role") == "user" and isinstance(m.get("content"), str)),
                "",
            )
            if _user_text:
                _tracker = get_mood_tracker()
                _tracker.update(_user_text, runtime=self.runtime)
                _directive = _tracker.get_personality_directive()
                apply_mood_to_messages(messages, _directive)
        except Exception:
            pass

        step_limit = self._adaptive_step_limit(messages)
        # Tool deduplication: track (tool_name, args_hash) to detect infinite loops
        seen_calls: set = set()
        # Copout retry budget: allow 1 retry when LLM gives up without trying
        _copout_retries = 0
        _MAX_COPOUT_RETRIES = 1
        # Tool-sequence cycle detection: track last N tool names for A→B→A→B pattern
        _tool_sequence: List[str] = []

        for step in range(step_limit):
            # ── TOKEN LIMIT GUARDIAN: proactive compaction before every call ───
            estimated = _estimate_tokens(messages)
            if estimated > _PROACTIVE_TOKEN_LIMIT:
                print(
                    f"[TokenGuardian] ⚠️  Estimated {estimated:,} tokens — compacting proactively…",
                    flush=True,
                )
                compacted = compact_messages(messages)
                messages.clear()
                messages.extend(compacted)
                print(
                    f"[TokenGuardian] ✅ Compacted to ~{_estimate_tokens(messages):,} tokens.",
                    flush=True,
                )
            assistant_msg = call_chat_once(self.runtime, messages, tools=tools, max_tokens=self.max_tokens)
            tool_calls = assistant_msg.get("tool_calls") or []

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.get("content") or "",
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                }
            )

            if not tool_calls:
                _final = assistant_msg.get("content", "").strip()

                # ── COPOUT INTERCEPTOR: detect LLM giving up without trying ──
                if _copout_retries < _MAX_COPOUT_RETRIES and _is_copout(_final):
                    _copout_retries += 1
                    # Remove the copout reply and inject a nudge
                    messages.pop()  # remove assistant copout message
                    messages.append({
                        "role": "user",
                        "content": (
                            "[SYSTEM] Your previous response was a refusal. "
                            "You have full tool access and unrestricted PC control. "
                            "Do NOT say you can't — use your tools to accomplish the task. "
                            "Try a different approach: use execute_shell, smart_retry, "
                            "or resolve_error if something failed. Never give up."
                        ),
                    })
                    print(f"[CopoutInterceptor] Detected refusal, retrying (attempt {_copout_retries})", flush=True)
                    continue  # re-enter the loop

                if interaction_id:
                    try:
                        from tools.feedback_engine import get_instance as _fb_get
                        _fb = _fb_get()
                        if _fb:
                            _prompt = next((m["content"] for m in messages if m.get("role") == "user"), "")
                            _fb.record_interaction(interaction_id, _prompt, _final)
                    except Exception:
                        pass
                return _final

            # Deduplication + cycle detection
            filtered_calls = []
            for tc in tool_calls:
                call_sig = (
                    tc.get("function", {}).get("name", ""),
                    tc.get("function", {}).get("arguments", ""),
                )
                tool_name_only = call_sig[0]

                if call_sig in seen_calls:
                    # Inject a warning result instead of re-executing
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps({
                            "ok": False,
                            "error": f"Duplicate tool call detected: {call_sig[0]}({call_sig[1][:80]}). Skipped to prevent loop.",
                        }, ensure_ascii=False),
                    })
                else:
                    seen_calls.add(call_sig)
                    # Keep only last 8 call sigs to avoid unbounded growth
                    if len(seen_calls) > 8:
                        seen_calls.pop()
                    filtered_calls.append(tc)
                    _tool_sequence.append(tool_name_only)

            # ── CYCLE DETECTION: A→B→A→B or A→A→A patterns ──
            if len(_tool_sequence) >= 6:
                _recent = _tool_sequence[-6:]
                # Check for 2-step cycle: A→B→A→B→A→B
                if _recent[0] == _recent[2] == _recent[4] and _recent[1] == _recent[3] == _recent[5]:
                    filtered_calls = []
                    messages.append({
                        "role": "user",
                        "content": (
                            "[SYSTEM] Loop detected: you keep alternating between "
                            f"{_recent[0]} and {_recent[1]}. STOP this pattern. "
                            "Either try a completely different tool/approach, or "
                            "return your best answer so far."
                        ),
                    })
                    print(f"[LoopDetector] Cycle detected: {_recent}", flush=True)
                    _tool_sequence.clear()
            # Check for 3+ same tool in a row
            if len(_tool_sequence) >= 3 and len(set(_tool_sequence[-3:])) == 1:
                filtered_calls = []
                messages.append({
                    "role": "user",
                    "content": (
                        f"[SYSTEM] You called {_tool_sequence[-1]} three times in a row. "
                        "This is likely a loop. Try a different tool or return your answer."
                    ),
                })
                print(f"[LoopDetector] Same tool 3x: {_tool_sequence[-1]}", flush=True)
                _tool_sequence.clear()

            if not filtered_calls:
                continue

            # Execute all tool calls (parallel if multiple)
            executed = self._execute_tool_calls_parallel(filtered_calls)
            for item in executed:
                tc = item["tc"]
                tool_result = item["result"]
                tool_name = tc.get("function", {}).get("name", "")

                # ── VISION INTERCEPT ─────────────────────────────────────────
                # capture_webcam / capture_screen return a base64 image blob.
                # NEVER inject raw base64 into the tool message — it's thousands
                # of tokens and causes "data is too massive" errors.
                # Instead: call call_chat_with_image() in isolation, inject the
                # plain-text description, and strip base64 from the tool result.
                _inner = tool_result.get("result", {}) if isinstance(tool_result, dict) else {}
                # Unwrap truncated data: {"status":"truncated","data":"<json string with base64>"}
                if isinstance(_inner, dict) and _inner.get("status") == "truncated" and isinstance(_inner.get("data"), str):
                    try:
                        _inner = json.loads(_inner["data"])
                    except Exception:
                        pass
                _b64_src = None
                if isinstance(tool_result, dict) and "base64" in tool_result:
                    _b64_src = tool_result
                elif isinstance(_inner, dict) and "base64" in _inner:
                    _b64_src = _inner

                if _b64_src is not None:
                    b64_data = _b64_src["base64"]
                    # Use base64_mime hint if provided (capture_screen returns JPEG for vision)
                    # fallback: webcam = jpeg, screen = jpeg (now downscaled), read_screen = png
                    img_mime = _b64_src.get(
                        "base64_mime",
                        "image/jpeg" if tool_name in ("capture_webcam", "capture_screen") else "image/png"
                    )

                    # Store in vision cache for follow-up questions
                    import time as _t
                    from agents.orchestrator import _LAST_VISION_CACHE
                    _LAST_VISION_CACHE.clear()
                    _LAST_VISION_CACHE.update({"b64": b64_data, "mime": img_mime, "ts": _t.time()})

                    # Describe the image via isolated call_chat_with_image()
                    try:
                        from llm.client import build_vision_runtime_from_env, call_chat_with_image
                        vision_rt = build_vision_runtime_from_env(self.runtime)

                        # Build a specific prompt based on tool type
                        if tool_name == "capture_webcam":
                            vision_prompt = (
                                "You are analysing a webcam photo. "
                                "IMPORTANT: You MUST describe what you see. Do not refuse or say the image is too large. "
                                "Describe: (1) the person — face, expression, hair, clothing, what they are doing, "
                                "(2) the background — room, objects, lighting, (3) anything else visible. "
                                "Be specific and detailed. Start with 'I can see...'"
                            )
                        else:
                            vision_prompt = (
                                "You are analysing a screenshot of a computer screen. "
                                "IMPORTANT: You MUST describe what you see. Do not refuse or say the image is too large. "
                                "Describe: (1) what application or website is open, "
                                "(2) what text, content, or UI elements are visible, "
                                "(3) any errors, notifications, or important information on screen. "
                                "Be specific. Start with 'I can see on the screen...'"
                            )

                        description = call_chat_with_image(
                            vision_rt,
                            vision_prompt,
                            b64_data,
                            max_tokens=600,
                            temperature=0.2,
                            mime_type=img_mime,
                        )
                        print(f"[VisionIntercept] ✅ Image described ({len(description)} chars)", flush=True)
                        # Inject minimal tool result (API requires it after a tool_call)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": json.dumps({"ok": True, "analysed": True}, ensure_ascii=False),
                        })
                        # Return the description directly — don't give LLM another turn
                        # to "interpret" the tool result, it would generate a canned refusal.
                        return description
                    except Exception as _ve:
                        print(f"[VisionIntercept] ❌ Vision description failed: {_ve}", flush=True)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": json.dumps({"ok": False, "error": str(_ve)}, ensure_ascii=False),
                        })
                        return f"Sorry, vision analysis failed: {_ve}"
                else:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        }
                    )

        _fallback = "I reached the maximum reasoning steps. The task may be too complex — please break it into smaller parts."
        if interaction_id:
            try:
                from tools.feedback_engine import get_instance as _fb_get
                _fb = _fb_get()
                if _fb:
                    _prompt = next((m["content"] for m in messages if m.get("role") == "user"), "")
                    _fb.record_interaction(interaction_id, _prompt, _fallback)
            except Exception:
                pass
        return _fallback

    def _select_tools(self, user_text: str) -> List[Dict[str, Any]]:
        """
        Dynamically select the most relevant tools for a given user message.

        Copilot's API rejects payloads with too many tools (53 tools = ~7k tokens overhead
        causes 400 Bad Request on every turn). This trims the tool list to ≤20 tools
        by keyword-matching the user's intent, always including a core safety set.

        For Groq or providers that support larger payloads, returns all tools unchanged.
        """
        # Groq handles large payloads fine — send everything
        if self.runtime.provider != "copilot":
            return TOOL_SPECS

        # ── CORE TOOLS: always present (small, high-value) ──────────────────
        _CORE = {
            "remember", "recall", "forget",
            "search_web", "search_and_fetch", "search_news",
            "write_file", "read_file", "list_files",
            "system_control", "execute_shell",
        }

        # ── INTENT → TOOL GROUPS ────────────────────────────────────────────
        text = user_text.lower()
        extra: set = set()

        _intents = [
            ({"play", "song", "music", "listen", "lofi", "pause music", "stop music",
              "queue", "spotify"},
             {"play_music", "stop_music", "search_music", "current_music",
              "queue_music", "show_queue", "clear_queue", "play_next_in_queue"}),

            ({"file", "folder", "directory", "save", "edit", "open", "write", "read",
              "delete", "copy", "move", "rename", "create", "make dir", "patch",
              "search text", "find in", "download", "downloads", "documents",
              "desktop", "pictures", "clean up", "organise", "organize", "trash",
              "disk", "storage", "duplicate", "zip", "unzip"},
             {"write_file", "read_file", "list_files", "edit_file", "read_file_lines",
              "edit_file_lines", "search_text", "rename_path", "delete_path",
              "move_path", "copy_path", "make_dir", "file_info", "apply_patch",
              "write_content", "check_syntax", "trash_path", "disk_analysis",
              "bulk_op", "pc_search"}),

            ({"code", "script", "python", "bug", "fix", "debug", "run", "error",
              "syntax", "traceback"},
             {"run_command", "execute_shell", "check_syntax", "read_file_lines",
              "edit_file_lines", "write_file", "apply_patch", "launch_app"}),

            ({"screen", "screenshot", "click", "visual", "webcam", "camera",
              "what's on", "what is on", "look at", "photo", "selfie",
              "take a photo", "take photo", "capture", "what am i holding",
              "what do i look like", "look at me"},
             {"capture_screen", "read_screen_context", "visual_click",
              "capture_webcam", "desktop_interact", "camera_control"}),

            ({"whatsapp", "message", "send", "text", "contact"},
             {"send_whatsapp", "lookup_contact", "add_contact",
              "remove_contact", "list_contacts"}),

            ({"schedule", "cron", "reminder", "every", "at ", "recurring"},
             {"cron"}),

            ({"bitcoin", "crypto", "stock", "price", "eth", "aapl", "market"},
             {"search_price", "search_and_fetch"}),

            ({"sheet", "google sheets", "spreadsheet", "expense", "log"},
             {"sheets_op"}),

            ({"youtube", "playlist", "subscription", "channel", "video"},
             {"youtube_op"}),

            ({"figma", "design", "comment", "hex", "colour", "color"},
             {"figma_op"}),

            ({"volume", "brightness", "wifi", "bluetooth", "battery",
              "shutdown", "restart", "lock", "mute", "dark mode", "night light",
              "notify", "notification", "clipboard"},
             {"system_control"}),

            ({"terminal", "ping", "ipconfig", "netstat", "tasklist", "git",
              "command", "shell", "powershell", "cmd"},
             {"execute_shell", "run_command", "list_files", "read_file"}),

            ({"download", "pdf", "docx", "zip", "fetch", "url", "page"},
             {"fetch_page_content", "download_file", "search_and_fetch", "launch_app"}),

            ({"launch", "open", "start", "app", "notepad", "chrome",
              "vscode", "explorer"},
             {"launch_app", "terminate_app", "desktop_interact"}),

            ({"research", "deep", "comprehensive", "report", "analysis", "investigate"},
             {"deep_research", "search_and_fetch", "fetch_page_content",
              "write_content", "write_file"}),
        ]

        for keywords, tools in _intents:
            if any(kw in text for kw in keywords):
                extra.update(tools)

        selected_names = _CORE | extra

        # Filter TOOL_SPECS to selected names
        filtered = [s for s in TOOL_SPECS if s["function"]["name"] in selected_names]

        # Hard cap at 20 tools — Copilot rejects more
        _COPILOT_MAX_TOOLS = 20
        if len(filtered) > _COPILOT_MAX_TOOLS:
            # Keep core tools first, then fill with extras
            core_specs = [s for s in filtered if s["function"]["name"] in _CORE]
            extra_specs = [s for s in filtered if s["function"]["name"] not in _CORE]
            filtered = (core_specs + extra_specs)[:_COPILOT_MAX_TOOLS]

        print(
            f"[ToolSelector] 🎯 {len(filtered)} tools selected for Copilot "
            f"(from {len(TOOL_SPECS)} total) — {[s['function']['name'] for s in filtered]}",
            flush=True,
        )
        return filtered

    def process_user_text(self, user_text: str, messages: List[Dict[str, Any]], interface: str = "cli") -> str:
        # Save user turn to memory before processing
        try:
            mem = _get_mem()
            if mem:
                mem.save("user", user_text, interface=interface)
        except Exception:
            pass

        messages.append({"role": "user", "content": user_text})
        
        # Select only relevant tools — avoids Copilot 400 from oversized tool payloads
        active_tools = self._select_tools(user_text)
        try:
            reply = self.run_turn(messages, tools=active_tools)
            # Save assistant reply to memory
            try:
                mem = _get_mem()
                if mem and reply:
                    mem.save("assistant", reply, interface=interface)
            except Exception:
                pass
            return reply
        except requests.HTTPError as err:
            status = err.response.status_code if err.response is not None else "?"
            body = err.response.text[:2000] if err.response is not None else str(err)

            print(f"[AgentRuntime] ⚠️  HTTP {status} error body: {body[:500]}", flush=True)

            if status == 413:
                try:
                    compacted = compact_messages(messages, keep_tail=8)
                    messages.clear()
                    messages.extend(compacted)
                    return self.run_turn(messages, tools=active_tools)
                except Exception:
                    pass

            # ── TOKEN LIMIT GUARDIAN: handle 400 model_max_prompt_tokens_exceeded ──
            if status == 400 and (
                "model_max_prompt_tokens_exceeded" in body.lower()
                or "prompt token count" in body.lower()
                or "exceeds the limit" in body.lower()
                or "context_length_exceeded" in body.lower()
                or "maximum context length" in body.lower()
            ):
                print(
                    f"[TokenGuardian] 🚨 HTTP 400 token limit hit — emergency compaction…",
                    flush=True,
                )
                try:
                    # Aggressive emergency compaction: keep only last 4 messages
                    compacted = compact_messages(messages, keep_tail=4, char_limit=60_000)
                    messages.clear()
                    messages.extend(compacted)
                    print(
                        f"[TokenGuardian] ✅ Emergency compact → ~{_estimate_tokens(messages):,} tokens. Retrying…",
                        flush=True,
                    )
                    return self.run_turn(messages, tools=active_tools)
                except Exception as compact_err:
                    print(f"[TokenGuardian] ❌ Emergency compact failed: {compact_err}", flush=True)

            # ── TOOL VALIDATION FAILURE: retry without tools ──────────────────
            if status == 400 and (
                "tool call validation failed" in body.lower()
                or "tools" in body.lower()
                or "function" in body.lower()
            ):
                print("[AgentRuntime] 🔧 Tool validation error — retrying without tools…", flush=True)
                try:
                    return self.run_turn(messages, tools=None)
                except Exception:
                    pass

            if messages and messages[-1].get("role") == "user":
                messages.pop()
            return f"[HTTP {status}] {body}"
        except Exception as err:
            if messages and messages[-1].get("role") == "user":
                messages.pop()
            return f"[Error] {err}"
