from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .registry import ToolInputError, require_text


def jarvis_latency_probe(params: dict[str, Any]) -> dict[str, Any]:
    prompts = probe_prompts(params)
    timeout_seconds = bounded_int(params.get("timeout_seconds"), 45, 5, 180)
    results = [measure_prompt(prompt, timeout_seconds) for prompt in prompts]
    lines = ["Jarvis latency probe:"]
    for result in results:
        first = result.get("first_content_seconds")
        total = result.get("total_seconds")
        lines.append(f"- {result['prompt']}: first={first}s total={total}s")
    return {
        "count": len(results),
        "results": results,
        "summary": "\n".join(lines),
    }


def probe_prompts(params: dict[str, Any]) -> list[str]:
    raw = params.get("prompts")
    if isinstance(raw, list):
        prompts = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    else:
        prompts = [require_text(params, "prompt")]
    if not prompts:
        raise ToolInputError("prompt or prompts is required")
    return prompts[:5]


def measure_prompt(prompt: str, timeout_seconds: int) -> dict[str, Any]:
    env = os.environ.copy()
    env["MEMORY_EXTRACT_FROM_CHAT"] = "false"
    env["JARVIS_LATENCY_DEBUG"] = "true"
    process = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=str(Path.cwd()),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0,
        env=env,
    )
    output_queue: queue.Queue[tuple[float, str]] = queue.Queue()
    reader = threading.Thread(target=read_stdout, args=(process, output_queue), daemon=True)
    reader.start()
    started = time.perf_counter()
    if process.stdin is None:
        raise ToolInputError("Jarvis stdin was not available")
    process.stdin.write(prompt + "\nexit\n")
    process.stdin.flush()

    output = ""
    marker_seen: float | None = None
    first_content: float | None = None
    deadline = started + timeout_seconds
    while time.perf_counter() < deadline:
        try:
            timestamp, char = output_queue.get(timeout=0.05)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        output += char
        if marker_seen is None and "JARVIS:" in output:
            marker_seen = timestamp
        if marker_seen is not None and first_content is None and has_reply_content(output):
            first_content = timestamp
        if first_content is not None and output.count("Krish:") >= 2:
            break

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
    finished = time.perf_counter()
    return {
        "prompt": prompt,
        "first_content_seconds": round(first_content - started, 3) if first_content is not None else None,
        "total_seconds": round(finished - started, 3),
        "output": output[-1200:],
    }


def read_stdout(process: subprocess.Popen[str], output_queue: queue.Queue[tuple[float, str]]) -> None:
    if process.stdout is None:
        return
    while True:
        char = process.stdout.read(1)
        if char == "":
            break
        output_queue.put((time.perf_counter(), char))


def has_reply_content(output: str) -> bool:
    marker = "JARVIS:"
    if marker not in output:
        return False
    after = output.split(marker, 1)[1]
    for char in after:
        if char not in " \r\n":
            return True
    return False


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip():
        try:
            number = int(value.strip())
        except ValueError:
            number = fallback
    else:
        number = fallback
    return max(minimum, min(maximum, number))
