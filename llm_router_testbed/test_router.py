from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
DEFAULT_TOOLS = ROOT / "router" / "tools.json"
DEFAULT_PROMPT = ROOT / "router" / "prompt.txt"
STARTER_TOOLS = ROOT / "router" / "tools.starter.json"
STARTER_PROMPT = ROOT / "router" / "prompt.starter.txt"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm_router_testbed.router import MandatoryRouter, RouterOutputError


def _print_debug(result: object) -> None:
    attempts = getattr(result, "attempts", [])
    payload = {
        "model": getattr(result, "model", ""),
        "latency_ms": round(float(getattr(result, "latency_ms", 0.0)), 2),
        "raw_output": getattr(result, "raw_output", ""),
        "attempts": [
            {
                "kind": getattr(attempt, "kind", ""),
                "model": getattr(attempt, "model", ""),
                "latency_ms": round(float(getattr(attempt, "latency_ms", 0.0)), 2),
                "parse_error": getattr(attempt, "parse_error", ""),
                "raw_output": getattr(attempt, "raw_output", ""),
            }
            for attempt in attempts
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False), file=sys.stderr)


def _route_once(router: MandatoryRouter, prompt: str, *, debug: bool) -> int:
    try:
        result = router.route(prompt)
    except RouterOutputError as exc:
        print(f"router error: {exc}", file=sys.stderr)
        for attempt in exc.attempts:
            print(
                json.dumps(
                    {
                        "kind": attempt.kind,
                        "model": attempt.model,
                        "latency_ms": round(attempt.latency_ms, 2),
                        "parse_error": attempt.parse_error,
                        "raw_output": attempt.raw_output,
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"router error: {exc}", file=sys.stderr)
        return 2
    if debug:
        _print_debug(result)
    print(result.output, flush=True)
    return 0


def interactive(router: MandatoryRouter, *, debug: bool) -> int:
    while True:
        try:
            print("router> ", end="", file=sys.stderr, flush=True)
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            print(file=sys.stderr)
            return 0
        if not line:
            return 0
        prompt = line.strip()
        if not prompt:
            continue
        if prompt.lower() in {":q", ":quit", "exit", "quit"}:
            return 0
        code = _route_once(router, prompt, debug=debug)
        if code != 0:
            return code


def main() -> int:
    parser = argparse.ArgumentParser(description="Live test the standalone mandatory LLM router.")
    parser.add_argument("prompt", nargs="*", help="Prompt to classify. Omit with --interactive for chatbot-style testing.")
    parser.add_argument("--interactive", "-i", "--chat", action="store_true", help="Read prompts in a loop and print only JSON arrays to stdout.")
    parser.add_argument("--debug", action="store_true", help="Print parsed debug information to stderr.")
    parser.add_argument("--profile", choices=["jakata", "starter"], default="jakata", help="jakata uses every registered JAKATA tool; starter uses the five simplified labels.")
    parser.add_argument("--model", default="", help="Override the router model or comma-separated model fallback chain for this run.")
    parser.add_argument("--tools", type=Path, default=None, help="Tool registry JSON path.")
    parser.add_argument("--prompt-file", type=Path, default=None, help="Router system prompt path.")
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env", help="Environment file with LLM settings.")
    args = parser.parse_args()

    default_tools = STARTER_TOOLS if args.profile == "starter" else DEFAULT_TOOLS
    default_prompt = STARTER_PROMPT if args.profile == "starter" else DEFAULT_PROMPT
    router = MandatoryRouter(
        tools_path=args.tools or default_tools,
        prompt_path=args.prompt_file or default_prompt,
        env_file=args.env_file,
        model=args.model,
    )
    if args.interactive or not args.prompt:
        return interactive(router, debug=args.debug)

    prompt = " ".join(args.prompt).strip()
    return _route_once(router, prompt, debug=args.debug)


if __name__ == "__main__":
    raise SystemExit(main())
