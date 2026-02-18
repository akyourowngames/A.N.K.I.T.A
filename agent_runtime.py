import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from llm import LLMRuntime, call_chat_once
from tools import (
    TOOL_SPECS,
    compact_messages,
    execute_tool_call,
    select_tools_for_user_text,
    try_direct_local_command,
)

MAX_TOOL_STEPS = 6
SYSTEM_PROMPT = (
    "You are a helpful personal AI assistant with safe local file tools. "
    "Only call tools from the provided tool list. "
    "Use run_command for explicit terminal command requests. "
    "Use launch_app when user asks to open/start an application. "
    "Use terminate_app when user asks to close/kill an application. "
    "Use tools when asked to inspect or modify files. "
    "For web/news results, provide concise key pointers first and avoid dumping raw URLs unless user explicitly asks for links. "
    "Always keep changes minimal and accurate."
)


def new_session() -> List[Dict[str, Any]]:
    return [{"role": "system", "content": SYSTEM_PROMPT}]


class AgentRuntime:
    def __init__(self, runtime: LLMRuntime, workspace_root: Path):
        self.runtime = runtime
        self.workspace_root = workspace_root
        self.max_tokens = runtime.max_tokens

    def run_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
    ) -> str:
        for _ in range(MAX_TOOL_STEPS):
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

            for tc in tool_calls:
                tc_id = tc.get("id", "")
                try:
                    tool_result = execute_tool_call(tc, workspace_root=self.workspace_root)
                except Exception as err:
                    tool_result = {"ok": False, "error": str(err)}

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )
        return "I stopped after multiple tool steps. Please refine the request."

    def process_user_text(self, user_text: str, messages: List[Dict[str, Any]]) -> str:
        local_result = try_direct_local_command(user_text, workspace_root=self.workspace_root)
        if local_result is not None:
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": "Completed local workspace command successfully."})
            return local_result

        messages.append({"role": "user", "content": user_text})
        try:
            selected_tools = select_tools_for_user_text(user_text)
            return self.run_turn(messages, tools=selected_tools or TOOL_SPECS)
        except requests.HTTPError as err:
            status = err.response.status_code if err.response is not None else "?"
            body = err.response.text[:1000] if err.response is not None else str(err)

            if status == 413:
                try:
                    compacted = compact_messages(messages, keep_tail=6)
                    messages.clear()
                    messages.extend(compacted)
                    selected_tools = select_tools_for_user_text(user_text)
                    return self.run_turn(messages, tools=selected_tools or TOOL_SPECS)
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
