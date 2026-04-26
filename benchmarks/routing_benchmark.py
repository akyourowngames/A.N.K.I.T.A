from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jakata_agent.config import load_settings
from jakata_agent.runtime import create_runtime
from jakata_agent.web import build_agent


DEFAULT_CASES = ROOT / "benchmarks" / "routing_cases.json"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "logs" / "benchmarks"


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a list of cases in {path}")
    return [case for case in payload if isinstance(case, dict)]


def _first_route(decision: Any) -> str:
    if getattr(decision, "direct_answer", ""):
        return "general_chat"
    steps = list(getattr(decision, "steps", []) or [])
    if not steps:
        return "none"
    return str(getattr(steps[0], "tool", "") or "none")


def _steps_payload(decision: Any) -> list[dict[str, Any]]:
    steps = []
    for step in list(getattr(decision, "steps", []) or []):
        steps.append(
            {
                "tool": getattr(step, "tool", ""),
                "args": getattr(step, "args", {}),
                "reason": getattr(step, "reason", ""),
            }
        )
    return steps


def run_benchmark(*, cases_path: Path, output_dir: Path, case_filter: str = "") -> dict[str, Any]:
    settings = load_settings()
    session_id = f"benchmark-{int(time.time())}"
    settings = replace(settings, session_id=session_id)
    runtime = create_runtime(settings)
    agent = build_agent(runtime)
    tool_manifest = runtime.tools.manifest(public_only=True)
    tool_names = {tool.get("name") for tool in tool_manifest}
    cases = _load_cases(cases_path)
    if case_filter:
        cases = [case for case in cases if case_filter.lower() in str(case.get("id", "")).lower()]

    results: list[dict[str, Any]] = []
    for case in cases:
        expected = [str(item) for item in case.get("expected_tools", [])]
        started = time.perf_counter()
        manifest_result = agent._planner_manifest(str(case.get("prompt", "")))
        after_manifest = time.perf_counter()
        decision = agent.plan(str(case.get("prompt", "")))
        finished = time.perf_counter()
        route = _first_route(decision)
        selected_tools = [str(tool.get("name", "")) for tool in manifest_result.tools]
        invalid_expected = [tool for tool in expected if tool != "general_chat" and tool not in tool_names]
        ok = route in expected and not invalid_expected
        results.append(
            {
                "id": case.get("id", ""),
                "category": case.get("category", ""),
                "execution": case.get("execution", "plan_only"),
                "prompt": case.get("prompt", ""),
                "expected_tools": expected,
                "actual_tool": route,
                "ok": ok,
                "invalid_expected_tools": invalid_expected,
                "semantic_best_score": round(float(manifest_result.best_score), 4),
                "semantic_used": bool(manifest_result.used_semantic_ranking),
                "semantic_shortlist": selected_tools,
                "manifest_ms": round((after_manifest - started) * 1000),
                "plan_ms": round((finished - after_manifest) * 1000),
                "total_ms": round((finished - started) * 1000),
                "steps": _steps_payload(decision),
                "direct_answer_preview": str(getattr(decision, "direct_answer", ""))[:300],
            }
        )

    passed = sum(1 for result in results if result["ok"])
    categories: dict[str, dict[str, int]] = {}
    expected_coverage: set[str] = set()
    actual_coverage: set[str] = set()
    for result in results:
        category = str(result["category"] or "uncategorized")
        bucket = categories.setdefault(category, {"passed": 0, "total": 0})
        bucket["total"] += 1
        if result["ok"]:
            bucket["passed"] += 1
        expected_coverage.update(result["expected_tools"])
        if result["actual_tool"] != "none":
            actual_coverage.add(result["actual_tool"])

    report = {
        "session_id": session_id,
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "score": round(passed / len(results), 4) if results else 0.0,
        "tool_catalog_count": len(tool_manifest),
        "tool_catalog": sorted(str(name) for name in tool_names if name),
        "expected_tool_coverage": sorted(expected_coverage),
        "actual_tool_coverage": sorted(actual_coverage),
        "missing_expected_catalog_tools": sorted((tool_names | {"general_chat"}) - expected_coverage),
        "category_scores": categories,
        "results": results,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    output_path = output_dir / f"routing-benchmark-{stamp}.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    latest_path = output_dir / "routing-benchmark-latest.json"
    latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["output_path"] = str(output_path)
    report["latest_path"] = str(latest_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run JAKATA live routing benchmark cases without executing planned tools.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--case", default="", help="Optional substring filter for case ids.")
    args = parser.parse_args()
    report = run_benchmark(cases_path=args.cases, output_dir=args.output_dir, case_filter=args.case)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2, ensure_ascii=False))
    for result in report["results"]:
        status = "PASS" if result["ok"] else "FAIL"
        print(
            f"{status}\t{result['id']}\texpected={result['expected_tools']}\t"
            f"actual={result['actual_tool']}\ttotal_ms={result['total_ms']}"
        )


if __name__ == "__main__":
    main()
