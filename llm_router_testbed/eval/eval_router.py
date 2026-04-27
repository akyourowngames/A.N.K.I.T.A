from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
DEFAULT_TOOLS = ROOT / "router" / "tools.json"
DEFAULT_PROMPT = ROOT / "router" / "prompt.txt"
STARTER_TOOLS = ROOT / "router" / "tools.starter.json"
STARTER_PROMPT = ROOT / "router" / "prompt.starter.txt"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm_router_testbed.router import MandatoryRouter, RouterOutputError


DEFAULT_CASES = [ROOT / "eval" / "real_cases.jsonl", ROOT / "eval" / "hard_cases.jsonl"]
DEFAULT_REPORT_DIR = ROOT / "eval" / "reports"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            payload.setdefault("source_file", str(path))
            payload.setdefault("source_line", line_number)
            cases.append(payload)
    return cases


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def signature(tools: list[str]) -> str:
    return json.dumps(tools, ensure_ascii=False, separators=(",", ":"))


def evaluate(router: MandatoryRouter, cases: list[dict[str, Any]], *, delay_ms: float = 0.0) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    invalid_format_count = 0
    provider_error_count = 0
    expected_by_tool: Counter[str] = Counter()
    predicted_by_tool: Counter[str] = Counter()
    true_positive_by_tool: Counter[str] = Counter()
    confusion: Counter[tuple[str, str]] = Counter()

    for index, case in enumerate(cases, start=1):
        prompt = str(case.get("prompt", ""))
        expected = [str(item) for item in case.get("expected_tools", [])]
        started = time.perf_counter()
        predicted: list[str] = []
        output = ""
        raw_output = ""
        attempts: list[dict[str, Any]] = []
        failure_reason = ""
        model = ""
        invalid_format = False

        try:
            result = router.route(prompt)
            predicted = result.tools
            output = result.output
            raw_output = result.raw_output
            model = result.model
            attempts = [
                {
                    "kind": attempt.kind,
                    "model": attempt.model,
                    "raw_output": attempt.raw_output,
                    "latency_ms": round(attempt.latency_ms, 2),
                    "parse_error": attempt.parse_error,
                }
                for attempt in result.attempts
            ]
        except RouterOutputError as exc:
            invalid_format = True
            invalid_format_count += 1
            failure_reason = str(exc)
            attempts = [
                {
                    "kind": attempt.kind,
                    "model": attempt.model,
                    "raw_output": attempt.raw_output,
                    "latency_ms": round(attempt.latency_ms, 2),
                    "parse_error": attempt.parse_error,
                }
                for attempt in exc.attempts
            ]
            if attempts:
                raw_output = attempts[-1]["raw_output"]
                model = attempts[-1]["model"]
        except Exception as exc:  # noqa: BLE001
            provider_error_count += 1
            failure_reason = f"router exception: {exc}"

        latency_ms = (time.perf_counter() - started) * 1000
        exact_match = predicted == expected
        set_match = set(predicted) == set(expected) and len(predicted) == len(set(predicted))
        if not exact_match and not failure_reason:
            failure_reason = "exact mismatch" if set_match else "tool mismatch"
        expected_set = set(expected)
        predicted_set = set(predicted)
        for tool in expected_set:
            expected_by_tool[tool] += 1
        for tool in predicted_set:
            predicted_by_tool[tool] += 1
        for tool in expected_set & predicted_set:
            true_positive_by_tool[tool] += 1
        if not exact_match:
            confusion[(signature(expected), signature(predicted))] += 1

        results.append(
            {
                "index": index,
                "prompt": prompt,
                "expected": expected,
                "predicted": predicted,
                "output": output,
                "raw_model_output": raw_output,
                "model": model,
                "exact_match": exact_match,
                "set_match": set_match,
                "invalid_format": invalid_format,
                "failure_reason": failure_reason if not exact_match or invalid_format else "",
                "latency_ms": round(latency_ms, 2),
                "difficulty": case.get("difficulty", ""),
                "category": case.get("category", ""),
                "notes": case.get("notes", ""),
                "source_file": case.get("source_file", ""),
                "source_line": case.get("source_line", 0),
                "attempts": attempts,
            }
        )
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)

    total = len(results)
    exact_matches = sum(1 for item in results if item["exact_match"])
    set_matches = sum(1 for item in results if item["set_match"])
    latencies = [float(item["latency_ms"]) for item in results]
    all_tools = sorted(set(expected_by_tool) | set(predicted_by_tool))
    per_tool = {}
    for tool in all_tools:
        tp = true_positive_by_tool[tool]
        predicted_count = predicted_by_tool[tool]
        expected_count = expected_by_tool[tool]
        per_tool[tool] = {
            "precision": round(tp / predicted_count, 4) if predicted_count else 0.0,
            "recall": round(tp / expected_count, 4) if expected_count else 0.0,
            "true_positive": tp,
            "predicted": predicted_count,
            "expected": expected_count,
        }

    failures = [item for item in results if not item["exact_match"] or item["invalid_format"]]
    return {
        "case_count": total,
        "overall_accuracy": round(set_matches / total, 4) if total else 0.0,
        "exact_match_accuracy": round(exact_matches / total, 4) if total else 0.0,
        "passed_exact": exact_matches,
        "failed_exact": total - exact_matches,
        "invalid_format_count": invalid_format_count,
        "provider_error_count": provider_error_count,
        "latency_stats_ms": {
            "mean": round(statistics.mean(latencies), 2) if latencies else 0.0,
            "median": round(statistics.median(latencies), 2) if latencies else 0.0,
            "p90": round(percentile(latencies, 0.90), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "max": round(max(latencies), 2) if latencies else 0.0,
        },
        "per_tool": per_tool,
        "confusion_summary": [
            {"expected": expected, "predicted": predicted, "count": count}
            for (expected, predicted), count in confusion.most_common(30)
        ],
        "failures": failures,
        "results": results,
    }


def write_reports(report: dict[str, Any], report_dir: Path) -> dict[str, str]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = report_dir / f"router-eval-{stamp}.json"
    md_path = report_dir / f"router-eval-{stamp}.md"
    failures_path = report_dir / f"router-failures-{stamp}.jsonl"
    latest_json = report_dir / "router-eval-latest.json"
    latest_md = report_dir / "router-eval-latest.md"
    latest_failures = report_dir / "router-failures-latest.jsonl"

    json_payload = json.dumps(report, indent=2, ensure_ascii=False)
    json_path.write_text(json_payload, encoding="utf-8")
    latest_json.write_text(json_payload, encoding="utf-8")

    failure_lines = [json.dumps(item, ensure_ascii=False) for item in report["failures"]]
    failures_payload = "\n".join(failure_lines) + ("\n" if failure_lines else "")
    failures_path.write_text(failures_payload, encoding="utf-8")
    latest_failures.write_text(failures_payload, encoding="utf-8")

    md = render_markdown_report(report)
    md_path.write_text(md, encoding="utf-8")
    latest_md.write_text(md, encoding="utf-8")
    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "failures": str(failures_path),
        "latest_json": str(latest_json),
        "latest_markdown": str(latest_md),
        "latest_failures": str(latest_failures),
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# LLM Router Eval Report",
        "",
        f"- Cases: {report['case_count']}",
        f"- Overall accuracy, order-insensitive: {report['overall_accuracy']:.4f}",
        f"- Exact match accuracy: {report['exact_match_accuracy']:.4f}",
        f"- Invalid-format count: {report['invalid_format_count']}",
        f"- Provider-error count: {report.get('provider_error_count', 0)}",
        f"- Mean latency: {report['latency_stats_ms']['mean']:.2f} ms",
        f"- P95 latency: {report['latency_stats_ms']['p95']:.2f} ms",
        "",
        "## Per-Tool Metrics",
        "",
        "| Tool | Precision | Recall | TP | Predicted | Expected |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for tool, metrics in report["per_tool"].items():
        lines.append(
            f"| {tool} | {metrics['precision']:.4f} | {metrics['recall']:.4f} | "
            f"{metrics['true_positive']} | {metrics['predicted']} | {metrics['expected']} |"
        )
    lines.extend(["", "## Confusion Summary", ""])
    if report["confusion_summary"]:
        for item in report["confusion_summary"][:20]:
            lines.append(f"- {item['count']}x expected `{item['expected']}` predicted `{item['predicted']}`")
    else:
        lines.append("- No confusions.")

    lines.extend(["", "## Failures", ""])
    if report["failures"]:
        for failure in report["failures"][:50]:
            lines.append(
                f"- `{failure['category']}` {failure['difficulty']}: expected "
                f"`{signature(failure['expected'])}` predicted `{signature(failure['predicted'])}` "
                f"reason `{failure['failure_reason']}` prompt: {failure['prompt']}"
            )
    else:
        lines.append("- No failures.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the standalone mandatory LLM router.")
    parser.add_argument("--cases", type=Path, nargs="*", default=DEFAULT_CASES, help="JSONL case files to evaluate.")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR, help="Directory for eval reports.")
    parser.add_argument("--max-cases", type=int, default=0, help="Optional cap for quick smoke tests.")
    parser.add_argument("--debug-progress", action="store_true", help="Print progress to stderr.")
    parser.add_argument("--no-fail-code", action="store_true", help="Always exit 0 after writing reports.")
    parser.add_argument("--profile", choices=["jakata", "starter"], default="jakata", help="jakata uses every registered JAKATA tool; starter uses the five simplified labels.")
    parser.add_argument("--model", default="", help="Override the router model or comma-separated model fallback chain for this eval run.")
    parser.add_argument("--delay-ms", type=float, default=0.0, help="Sleep between cases to avoid provider rate limits.")
    parser.add_argument("--tools", type=Path, default=None, help="Tool registry JSON path.")
    parser.add_argument("--prompt-file", type=Path, default=None, help="Router system prompt path.")
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env", help="Environment file with LLM settings.")
    args = parser.parse_args()

    cases: list[dict[str, Any]] = []
    for path in args.cases:
        cases.extend(load_jsonl(path))
    if args.max_cases:
        cases = cases[: args.max_cases]

    default_tools = STARTER_TOOLS if args.profile == "starter" else DEFAULT_TOOLS
    default_prompt = STARTER_PROMPT if args.profile == "starter" else DEFAULT_PROMPT
    router = MandatoryRouter(
        tools_path=args.tools or default_tools,
        prompt_path=args.prompt_file or default_prompt,
        env_file=args.env_file,
        model=args.model,
    )
    if args.debug_progress:
        print(f"Evaluating {len(cases)} router cases...", file=sys.stderr)
    report = evaluate(router, cases, delay_ms=args.delay_ms)
    paths = write_reports(report, args.report_dir)
    summary = {key: value for key, value in report.items() if key not in {"results", "failures"}}
    summary["report_paths"] = paths
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.no_fail_code:
        return 0
    if report["invalid_format_count"]:
        return 2
    return 0 if report["failed_exact"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
