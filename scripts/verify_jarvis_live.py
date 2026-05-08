from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis_nim import load_dotenv
from tools.terminal import run_terminal


def main() -> int:
    workspace = Path.cwd()
    load_dotenv(workspace / ".env")
    listing_dir = workspace / "tmp_live_listing_check"
    listing_dir.mkdir(exist_ok=True)
    (listing_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
    (listing_dir / "beta.txt").write_text("beta", encoding="utf-8")
    checks = [
        {
            "name": "pc_status_grounded_summary",
            "expected": ["OS:", "Architecture:", "Workspace:"],
            "prompt": "whats my pc status",
            "forbidden": ['"path"', "[{", "tool", "running"],
        },
        {
            "name": "directory_listing_clean_summary",
            "expected": ["alpha.txt", "beta.txt"],
            "prompt": f"list all files in {listing_dir}",
            "forbidden": ['"path"', "[{", "tool", "running"],
        },
        {
            "name": "jarvis_runtime_python_grounding",
            "expected": sys.version.split()[0],
            "prompt": "what Python version are you running under",
        },
        {
            "name": "python_version_grounding",
            "command": "python --version",
            "prompt": "check my current python version installed on this system",
        },
        {
            "name": "node_version_grounding",
            "command": "node -v",
            "prompt": "whats current node js version on this system",
        },
        {
            "name": "npm_and_node_version_grounding",
            "commands": ["npm -v", "node -v"],
            "prompt": "whats current npm version and node js version",
        },
        {
            "name": "python_node_npm_multi_fact_grounding",
            "commands": ["python --version", "node -v", "npm -v"],
            "prompt": "check my python version, node version, and npm version on this system",
            "forbidden": ["tool", "running", "schema"],
        },
        {
            "name": "date_time_direct_answer",
            "expected": "Current date and time:",
            "prompt": "whats the current date and time",
            "forbidden": ["tool", "running", "schema"],
        },
        {
            "name": "calculator_direct_answer",
            "expected": "4",
            "prompt": "calculate 2 + 2",
            "forbidden": ["tool", "running", "schema"],
        },
        {
            "name": "weather_direct_answer",
            "expected": "Delhi",
            "prompt": "whats the weather in Delhi",
            "forbidden": ["can't", "cannot", "not available", "tool is running", "schema"],
        },
        {
            "name": "date_and_weather_multi_tool_answer",
            "expected": [str(datetime.now().date()), "Delhi"],
            "prompt": "whats the current date and time, then tell me the weather in Delhi, and answer only with the useful results",
            "forbidden": ["tool", "running", "schema"],
        },
        {
            "name": "date_weather_name_mixed_answer",
            "expected": [str(datetime.now().date()), "Delhi", "Krish"],
            "prompt": "whats the date, weather in delhi and my name",
            "forbidden": ["OS:", "Architecture:", "CPU cores:", "tool", "running", "schema"],
        },
        {
            "name": "fetch_url_summary_no_raw_html",
            "expected": ["Example Domain", "This domain"],
            "prompt": "fetch https://example.com and summarize what the page says in one sentence",
            "forbidden": ["<!doctype", "<html", "viewport", "tool is running", "schema"],
        },
        {
            "name": "web_search_extension_direct_answer",
            "expected": ["Example Domain", "example.com"],
            "prompt": "search the web for Example Domain and give me the best title and URL only",
            "forbidden": ["<!doctype", "<html", "tool", "running", "schema"],
        },
        {
            "name": "document_extract_extension_direct_answer",
            "expected": "Jarvis NIM Python Assistant",
            "prompt": "extract README.md and tell me the project name only",
            "forbidden": ["tool", "running", "schema"],
        },
        {
            "name": "vector_memory_reindex_and_search",
            "expected": ["Vector memory", "Krish", "15"],
            "prompt": "reindex vector memory, then search vector memory for Krish age and name",
            "forbidden": ["running", "schema"],
        },
        {
            "name": "vector_memory_existing_index_search",
            "expected": ["Krish", "15"],
            "prompt": "search deep vector memory for my age and name",
            "forbidden": ["running", "schema"],
        },
        {
            "name": "extension_complex_multi_tool_answer",
            "expected": [str(datetime.now().date()), "Delhi", "Jarvis NIM Python Assistant", "Example Domain"],
            "prompt": "what is the current date and time, weather in Delhi, extract README.md and tell me the project name, and search the web for Example Domain; answer only useful results",
            "forbidden": ["tool", "running", "schema", "<html"],
        },
        {
            "name": "hash_tool_direct_answer",
            "expected": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            "prompt": "hash abc with sha256",
            "forbidden": ["tool", "running", "schema"],
        },
        {
            "name": "text_stats_direct_answer",
            "expected": "2",
            "prompt": "use text_stats to count words in this text: hello world",
            "forbidden": ["tool", "running", "schema"],
        },
    ]

    failures = []
    for check in checks:
        expected_values = expected_outputs(check)
        if not expected_values:
            print(f"{check['name']} skipped: no command output")
            continue
        reply = jarvis_reply(check["prompt"])
        forbidden_values = [value for value in check.get("forbidden", []) if isinstance(value, str)]
        ok = all(output_is_in_reply(expected, reply) for expected in expected_values)
        ok = ok and not any(value.lower() in reply.lower() for value in forbidden_values)
        print(f"{check['name']}: expected={expected_values!r}")
        print(f"{check['name']}: reply={reply!r}")
        print(f"{check['name']}: {'ok' if ok else 'failed'}")
        if not ok:
            failures.append(check["name"])
        time.sleep(0.5)

    interactive_failure = interactive_python_recheck()
    if interactive_failure:
        failures.append(interactive_failure)
    notepad_failure = interactive_date_and_open_notepad()
    if notepad_failure:
        failures.append(notepad_failure)

    try:
        if failures:
            print("failed live checks: " + ", ".join(failures))
            return 1
        print("live jarvis checks ok")
        return 0
    finally:
        cleanup_listing_dir(listing_dir)


def expected_outputs(check: dict[str, object]) -> list[str]:
    expected = check.get("expected")
    if isinstance(expected, str) and expected:
        return [expected]
    if isinstance(expected, list):
        return [value for value in expected if isinstance(value, str) and value]
    commands = check.get("commands")
    if isinstance(commands, list):
        values = []
        for command in commands:
            if isinstance(command, str):
                output = expected_output(command)
                if output:
                    values.append(output)
        return values
    command = check.get("command")
    if isinstance(command, str):
        output = expected_output(command)
        return [output] if output else []
    return []


def expected_output(command: str) -> str:
    result = run_terminal({"command": command, "timeout_seconds": 10, "max_output_chars": 1000})
    stdout = str(result.get("stdout", "")).strip()
    stderr = str(result.get("stderr", "")).strip()
    if stdout:
        return stdout
    return stderr


def output_is_in_reply(expected: str, reply: str) -> bool:
    if expected in reply:
        return True
    prefix = "Python "
    if expected.startswith(prefix) and expected[len(prefix) :] in reply:
        return True
    return False


def jarvis_reply(prompt: str) -> str:
    env = os.environ.copy()
    env["MEMORY_EXTRACT_FROM_CHAT"] = "false"
    completed = subprocess.run(
        [sys.executable, "main.py", prompt],
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    output = completed.stdout.strip()
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        return f"PROCESS_FAILED[{completed.returncode}]: {stderr}"
    marker = "JARVIS:"
    if marker in output:
        return output.split(marker, 1)[1].strip()
    return output


def interactive_python_recheck() -> str:
    expected = expected_output("python --version")
    env = os.environ.copy()
    env["MEMORY_EXTRACT_FROM_CHAT"] = "false"
    completed = subprocess.run(
        [sys.executable, "main.py"],
        cwd=str(Path.cwd()),
        input="check my current python version installed on this system\nare you sure\nexit\n",
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    output = completed.stdout
    expected_token = expected[len("Python ") :] if expected.startswith("Python ") else expected
    ok = output.count(expected_token) >= 2 and "Can I run" not in output and "cannot verify" not in output
    print(f"interactive_python_recheck: expected={expected!r}")
    print(f"interactive_python_recheck: {'ok' if ok else 'failed'}")
    if not ok:
        print(output)
        return "interactive_python_recheck"
    return ""


def cleanup_listing_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_file():
            child.unlink()
    path.rmdir()


def interactive_date_and_open_notepad() -> str:
    if os.name != "nt":
        print("interactive_date_and_open_notepad: skipped on non-Windows")
        return ""
    before = notepad_pids()
    new_pids: set[int] = set()
    env = os.environ.copy()
    env["MEMORY_EXTRACT_FROM_CHAT"] = "false"
    try:
        completed = subprocess.run(
            [sys.executable, "main.py"],
            cwd=str(Path.cwd()),
            input="cool whats the date today and open me notepad\nexit\n",
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
        time.sleep(1)
        after = notepad_pids()
        new_pids = after - before
        output = completed.stdout
        reply = output.split("Krish: JARVIS:", 1)[1] if "Krish: JARVIS:" in output else output
        ok = (
            completed.returncode == 0
            and date_is_in_reply(reply)
            and new_pids
            and "tool" not in reply.lower()
            and "running" not in reply.lower()
            and "schema" not in reply.lower()
        )
        print("interactive_date_and_open_notepad: " + ("ok" if ok else "failed"))
        if not ok:
            print(output)
            print(completed.stderr)
            print("new_notepad_pids=" + ",".join(str(pid) for pid in sorted(new_pids)))
            return "interactive_date_and_open_notepad"
        return ""
    finally:
        for pid in new_pids:
            stop_process(pid)


def notepad_pids() -> set[int]:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Process notepad -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    result: set[int] = set()
    for line in completed.stdout.splitlines():
        text = line.strip()
        if text.isdigit():
            result.add(int(text))
    return result


def stop_process(pid: int) -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"],
        capture_output=True,
        text=True,
        timeout=20,
    )


def date_is_in_reply(reply: str) -> bool:
    today = datetime.now()
    if str(today.date()) in reply:
        return True
    return today.strftime("%B") in reply and str(today.day) in reply and str(today.year) in reply


if __name__ == "__main__":
    raise SystemExit(main())
