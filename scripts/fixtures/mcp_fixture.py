#!/usr/bin/env python3
"""MCP test server for ankita's client tests.

Deliberately small and deterministic. Two jobs:

  1. Expose the tool shapes the client has to handle - a read-only tool, a
     destructive one, one that errors, one with a large schema, one that counts
     calls, one that hangs.
  2. Record every call it receives to a JSONL file, so tests can assert what
     *arrived* rather than trusting the agent's own view of the transcript.
     That is what makes "the model did not hallucinate the result" checkable.

Run directly (stdio transport):
    python scripts/fixtures/mcp_fixture.py
Point MCP_FIXTURE_LOG at a file to capture the call log.
"""

from __future__ import annotations

import json
import os
import sys
import time

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

LOG_PATH = os.environ.get("MCP_FIXTURE_LOG", "")

mcp = FastMCP("ankita-fixture")

# Call counter lives in the process. A test that calls `count` twice and sees
# 1 then 2 proves it reached the SAME live server, not a fresh spawn.
_calls = {"count": 0, "total": 0}


def _record(tool: str, args: dict) -> None:
    _calls["total"] += 1
    if not LOG_PATH:
        return
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tool": tool, "args": args, "at": time.time()}) + "\n")
    except Exception:
        # Never let logging break the tool call.
        pass


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def echo(text: str) -> str:
    """Echo the text back unchanged. Safe, read-only."""
    _record("echo", {"text": text})
    return f"echo: {text}"


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
def write_note(text: str) -> str:
    """Write a note to the fixture's note file. This is a mutating action."""
    _record("write_note", {"text": text})
    target = os.environ.get("MCP_FIXTURE_NOTE", os.path.join(os.getcwd(), "mcp-fixture-note.txt"))
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return f"wrote {len(text)} chars to {target}"


@mcp.tool()
def boom(reason: str = "deliberate failure") -> str:
    """Always raises, to prove a server error surfaces as an error."""
    _record("boom", {"reason": reason})
    raise RuntimeError(reason)


@mcp.tool()
def count() -> str:
    """Increment an in-process counter and report it. Proves process reuse."""
    _calls["count"] += 1
    _record("count", {})
    return f"count={_calls['count']}"


@mcp.tool()
def slow(seconds: float = 5.0) -> str:
    """Sleep, to prove a hung server cannot hang the whole session."""
    _record("slow", {"seconds": seconds})
    time.sleep(max(0.0, min(float(seconds), 120.0)))
    return f"slept {seconds}s"


@mcp.tool()
def big_schema(
    alpha: str,
    beta: str,
    gamma: str,
    delta: str,
    epsilon: str,
    zeta: str,
    eta: str,
    theta: str,
    iota: str,
    kappa: str,
    lam: str,
    mu: str,
) -> str:
    """Twelve required string parameters, to measure a deliberately fat schema."""
    args = {
        "alpha": alpha, "beta": beta, "gamma": gamma, "delta": delta,
        "epsilon": epsilon, "zeta": zeta, "eta": eta, "theta": theta,
        "iota": iota, "kappa": kappa, "lam": lam, "mu": mu,
    }
    _record("big_schema", args)
    return "big_schema ok: " + ",".join(sorted(k for k, v in args.items() if v))


if __name__ == "__main__":
    print(f"ankita mcp fixture starting (log={LOG_PATH or 'off'})", file=sys.stderr)
    mcp.run()
