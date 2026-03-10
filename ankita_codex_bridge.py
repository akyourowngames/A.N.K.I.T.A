#!/usr/bin/env python3
"""
Bridge script so the Codex CLI provider can invoke ANKITA's local Python tools.
"""

import json
import sys

from chatbot import CopilotChatbot


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: python ankita_codex_bridge.py <tool_name> '<json arguments>'",
            file=sys.stderr,
        )
        return 2

    tool_name = sys.argv[1].strip()
    raw_arguments = sys.argv[2] if len(sys.argv) > 2 else "{}"

    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as err:
        print(f"Error: Invalid JSON arguments: {err}", file=sys.stderr)
        return 2

    if not isinstance(arguments, dict):
        print("Error: Tool arguments must decode to a JSON object", file=sys.stderr)
        return 2

    chatbot = CopilotChatbot()
    result = chatbot.execute_tool(tool_name, arguments)

    stream = sys.stdout
    exit_code = 0
    if result.startswith("Error:") or result.startswith("Tool execution failed"):
        stream = sys.stderr
        exit_code = 1

    print(result, file=stream)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
