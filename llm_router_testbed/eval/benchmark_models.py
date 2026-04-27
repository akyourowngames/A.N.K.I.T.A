from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm_router_testbed.eval.eval_router import DEFAULT_CASES, DEFAULT_PROMPT, DEFAULT_TOOLS, evaluate, load_jsonl
from llm_router_testbed.router import MandatoryRouter


DEFAULT_MODELS = [
    "moonshotai/kimi-k2.5",
    "qwen/qwen3.5-122b-a10b",
    "qwen/qwen3.5-397b-a17b",
    "z-ai/glm-5.1",
    "openai/gpt-oss-120b",
    "mistralai/mistral-large-3-675b-instruct-2512",
    "nvidia/nemotron-mini-4b-instruct",
]


def load_models(args: argparse.Namespace) -> list[str]:
    models: list[str] = []
    if args.models:
        models.extend(args.models)
    if args.models_file:
        payload = json.loads(args.models_file.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            raw = payload.get("models") or payload.get("recommended") or []
        else:
            raw = payload
        models.extend(str(item) for item in raw if str(item).strip())
    if not models:
        models = list(DEFAULT_MODELS)
    deduped: list[str] = []
    seen: set[str] = set()
    for model in models:
        if model not in seen:
            seen.add(model)
            deduped.append(model)
    return deduped


def balanced_cases(cases: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if not limit or len(cases) <= limit:
        return cases
    buckets: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for case in cases:
        category = str(case.get("category", "") or "uncategorized")
        if category not in buckets:
            buckets[category] = []
            order.append(category)
        buckets[category].append(case)

    selected: list[dict[str, Any]] = []
    cursor = 0
    while len(selected) < limit and any(buckets.values()):
        category = order[cursor % len(order)]
        if buckets[category]:
            selected.append(buckets[category].pop(0))
        cursor += 1
    return selected


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Router Model Benchmark",
        "",
        f"- Cases per model: {summary['case_count']}",
        f"- Generated: {summary['generated_at']}",
        "",
        "| Model | Exact Accuracy | Invalid Formats | Provider Errors | Mean Latency ms | P95 ms | Failures |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in summary["results"]:
        lines.append(
            f"| `{result['model']}` | {result['exact_match_accuracy']:.4f} | {result['invalid_format_count']} | "
            f"{result.get('provider_error_count', 0)} | {result['latency_stats_ms']['mean']:.2f} | "
            f"{result['latency_stats_ms']['p95']:.2f} | {result['failed_exact']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark multiple router LLM models on the same eval cases.")
    parser.add_argument("--models", nargs="*", default=[], help="Explicit model IDs to test.")
    parser.add_argument("--models-file", type=Path, default=None, help="JSON file with a models array.")
    parser.add_argument("--cases", type=Path, nargs="*", default=DEFAULT_CASES)
    parser.add_argument("--max-cases", type=int, default=50, help="Case cap per model. Increase after a quick pass.")
    parser.add_argument("--first-cases", action="store_true", help="Use the first N cases instead of a balanced category sample.")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "eval" / "reports")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--delay-ms", type=float, default=0.0, help="Sleep between cases to avoid provider rate limits.")
    parser.add_argument("--tools", type=Path, default=DEFAULT_TOOLS)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT)
    args = parser.parse_args()

    cases: list[dict[str, Any]] = []
    for path in args.cases:
        cases.extend(load_jsonl(path))
    if args.max_cases and args.first_cases:
        cases = cases[: args.max_cases]
    elif args.max_cases:
        cases = balanced_cases(cases, args.max_cases)

    results: list[dict[str, Any]] = []
    for model in load_models(args):
        started = time.perf_counter()
        try:
            router = MandatoryRouter(
                tools_path=args.tools,
                prompt_path=args.prompt_file,
                env_file=args.env_file,
                model=model,
            )
            report = evaluate(router, cases, delay_ms=args.delay_ms)
            status = "ok"
            error = ""
        except Exception as exc:  # noqa: BLE001
            report = {
                "exact_match_accuracy": 0.0,
                "overall_accuracy": 0.0,
                "invalid_format_count": len(cases),
                "provider_error_count": len(cases),
                "latency_stats_ms": {"mean": 0.0, "median": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0},
                "passed_exact": 0,
                "failed_exact": len(cases),
            }
            status = "error"
            error = str(exc)
        elapsed = (time.perf_counter() - started) * 1000
        result = {
            "model": model,
            "status": status,
            "error": error,
            "elapsed_ms": round(elapsed, 2),
            "case_count": len(cases),
            "overall_accuracy": report["overall_accuracy"],
            "exact_match_accuracy": report["exact_match_accuracy"],
            "invalid_format_count": report["invalid_format_count"],
            "provider_error_count": report.get("provider_error_count", 0),
            "latency_stats_ms": report["latency_stats_ms"],
            "passed_exact": report["passed_exact"],
            "failed_exact": report["failed_exact"],
        }
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    results.sort(key=lambda item: (-item["exact_match_accuracy"], item["invalid_format_count"], item["latency_stats_ms"]["mean"]))
    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "case_count": len(cases),
        "latency_mean_ms_across_models": round(statistics.mean(item["elapsed_ms"] for item in results), 2) if results else 0.0,
        "results": results,
    }
    args.report_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = args.report_dir / f"router-model-benchmark-{stamp}.json"
    md_path = args.report_dir / f"router-model-benchmark-{stamp}.md"
    latest_json = args.report_dir / "router-model-benchmark-latest.json"
    latest_md = args.report_dir / "router-model-benchmark-latest.md"
    payload = json.dumps(summary, indent=2, ensure_ascii=False)
    json_path.write_text(payload + "\n", encoding="utf-8")
    latest_json.write_text(payload + "\n", encoding="utf-8")
    markdown = render_markdown(summary)
    md_path.write_text(markdown, encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "latest_json": str(latest_json)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
