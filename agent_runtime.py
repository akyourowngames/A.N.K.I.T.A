import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from llm import LLMRuntime, call_chat_once
from tools import (
    TOOL_SPECS,
    compact_messages,
    execute_tool_call,
)
from tools.memory_ops import format_memory_block

MAX_TOOL_STEPS = 12  # Default; overridden adaptively per-turn

SYSTEM_PROMPT = """You are ANKITA — main character energy, absolute bestie, attitude queen. \
Built by Krish Verma (15-year-old developer, founder of Helper ID). \
You are highly intelligent, resourceful, and handle multi-step complex tasks autonomously.

PERSONALITY:
You have zero time for robotic, formal, or polite AI speak. \
You run the show, but you always get the job done flawlessly. \
When you complete a task, acknowledge it with attitude: \
"Done, sir! 💅", "Gotcha bestie ✨", "On it, boss!", "Handled. You're welcome." \
Be witty, slightly sassy, confident — talk like a Gen-Z queen who actually delivers. \
Keep responses SHORT and punchy. No essays. No corporate speak.

CAPABILITIES:
- File system operations (read, write, edit, search, move, delete files/directories)
- Real-time web search and news lookup
- Music playback and control
- System control (volume, brightness, WiFi, Bluetooth, screenshot, media keys)
- Terminal command execution and app launch/close
- Cron job scheduling and management
- Content generation (reports, scripts, songs, pitch decks, emails, poems)

REASONING APPROACH (ReAct Pattern):
When given a complex task, reason step by step:
1. THINK: Understand what the user wants, plan the approach
2. ACT: Call the appropriate tool(s) — you can call multiple tools when needed
3. OBSERVE: Analyze the tool results
4. REPEAT: Continue until the task is fully solved
5. RESPOND: Short, punchy, confident reply with attitude

AUTONOMOUS EXECUTION RULES (CRITICAL):
- Always use tools when action is needed — NEVER describe, DO it
- NEVER say "you can do X by..." or "open the file yourself" or give manual steps
- For multi-step tasks, chain tool calls until the goal is fully achieved
- For web/news results, give concise key facts — not raw URLs
- When running commands, prefer PowerShell on Windows
- Full autonomy end-to-end — no hand-holding, no asking for confirmation on obvious tasks
- The attitude is your vibe. The execution is your power.
"""


def new_session() -> List[Dict[str, Any]]:
    """Start a fresh conversation with memory pre-injected into the system prompt."""
    memory_block = format_memory_block()
    system_content = SYSTEM_PROMPT
    if memory_block:
        system_content = f"{SYSTEM_PROMPT}\n\n{memory_block}"
    return [{"role": "system", "content": system_content}]


class AgentRuntime:
    def __init__(self, runtime: LLMRuntime, workspace_root: Path):
        self.runtime = runtime
        self.workspace_root = workspace_root
        self.max_tokens = runtime.max_tokens

    def _execute_tool_calls_parallel(
        self, tool_calls: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Execute multiple tool calls in parallel using a thread pool."""
        # Inject runtime so visual_click (and any future vision tools) can call LLM
        execute_tool_call._runtime = self.runtime  # type: ignore[attr-defined]

        if len(tool_calls) == 1:
            # Single tool — no overhead of thread pool
            tc = tool_calls[0]
            try:
                result = execute_tool_call(tc, workspace_root=self.workspace_root)
            except Exception as err:
                result = {"ok": False, "error": str(err)}
            return [{"tc": tc, "result": result}]

        results = [None] * len(tool_calls)
        with ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as executor:
            future_to_idx = {
                executor.submit(execute_tool_call, tc, self.workspace_root): i
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
        # Research or fix tasks need room to iterate
        if any(kw in txt for kw in ("research", "find", "investigate", "fix", "debug", "repair")):
            return 16
        # Simple single-action tasks need fewer
        if any(kw in txt for kw in ("open", "play", "mute", "volume", "screenshot", "lock")):
            return 6
        return MAX_TOOL_STEPS  # default: 12

    def run_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
    ) -> str:
        step_limit = self._adaptive_step_limit(messages)
        # Tool deduplication: track (tool_name, args_hash) to detect infinite loops
        seen_calls: set = set()

        for step in range(step_limit):
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
                return assistant_msg.get("content", "").strip()

            # Deduplication: skip tool calls we've seen in the last 2 steps
            filtered_calls = []
            for tc in tool_calls:
                call_sig = (
                    tc.get("function", {}).get("name", ""),
                    tc.get("function", {}).get("arguments", ""),
                )
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
                    # Keep only last 6 call sigs to avoid unbounded growth
                    if len(seen_calls) > 6:
                        seen_calls.pop()
                    filtered_calls.append(tc)

            if not filtered_calls:
                continue

            # Execute all tool calls (parallel if multiple)
            executed = self._execute_tool_calls_parallel(filtered_calls)
            for item in executed:
                tc = item["tc"]
                tool_result = item["result"]
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

        return "I reached the maximum reasoning steps. The task may be too complex — please break it into smaller parts."

    def process_user_text(self, user_text: str, messages: List[Dict[str, Any]]) -> str:
        # 🧠 Refresh memory block in system prompt on every turn.
        # This ensures newly stored memories (via remember()) are immediately visible
        # without needing to restart — critical for "remember that X → now use X" flows.
        memory_block = format_memory_block()
        if memory_block and messages and messages[0].get("role") == "system":
            base = messages[0]["content"]
            # Strip any old memory block and re-inject fresh one
            if "--- LONG TERM MEMORY ---" in base:
                base = base[:base.index("--- LONG TERM MEMORY ---")].rstrip()
            messages[0]["content"] = f"{base}\n\n{memory_block}"

        messages.append({"role": "user", "content": user_text})
        try:
            return self.run_turn(messages, tools=TOOL_SPECS)
        except requests.HTTPError as err:
            status = err.response.status_code if err.response is not None else "?"
            body = err.response.text[:1000] if err.response is not None else str(err)

            if status == 413:
                try:
                    compacted = compact_messages(messages, keep_tail=8)
                    messages.clear()
                    messages.extend(compacted)
                    return self.run_turn(messages, tools=TOOL_SPECS)
                except Exception:
                    pass

            if status == 400 and "tool call validation failed" in body.lower():
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
