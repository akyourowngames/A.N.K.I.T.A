"""Compare the current router fallback with experimental model classifiers.

Usage:
    python -m app.experiments.evaluate_routing_classifier --backend minilm
    python -m app.experiments.evaluate_routing_classifier --backend llm

The production app does not import this file.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import List, Optional

import app.services.brain_service as brain_module
from app.experiments.prompt_tool_classifier import PromptToolClassifier
from app.experiments.tool_classifier_bert import ExperimentalToolClassifier
from app.services.brain_service import BrainService


@dataclass(frozen=True)
class Case:
    text: str
    primary: str
    tool: Optional[str] = None
    note: str = ""


CASES: List[Case] = [
    Case("can yu take ss", "task", "unsupported_needs_tool", "screenshot typo from UI failure"),
    Case("take screenshot", "task", "unsupported_needs_tool", "no screenshot executor exists yet"),
    Case("capture my screen", "task", "unsupported_needs_tool"),
    Case("open youtube", "task", "open"),
    Case("can you open ss.com", "task", "open", "real domain should still open"),
    Case("open the web cam", "task", "open_webcam"),
    Case("turn off camera", "task", "close_webcam"),
    Case("play nanna re na re", "task", "play"),
    Case("search youtube for python decorators", "task", "youtube_search"),
    Case("google best gpu under 30000", "task", "google_search"),
    Case("write a leave application", "task", "content"),
    Case("generate image of a blue sports car", "task", "generate_image"),
    Case("what apps are open", "task", "inspect_pc"),
    Case("why is my laptop slow", "task", "inspect_pc"),
    Case("set volume to 20", "task", "set_volume"),
    Case("increase brightness", "task", "brightness_up"),
    Case("lock my screen", "task", "lock_screen"),
    Case("run terminal command Get-Process python", "task", "run_terminal"),
    Case("hello jarvis", "general"),
    Case("what is recursion", "general"),
    Case("latest cricket score today", "realtime"),
    Case("what is the weather today", "realtime"),
    Case("what am i holding", "camera"),
    Case("look at this and tell me what it is", "camera"),
    Case("tell me about python and open youtube", "mixed", "open"),
]


def _current_prediction(brain: BrainService, text: str):
    primary, primary_method, primary_ms = brain.classify_primary(text)
    task_types = []
    task_method = ""
    task_ms = 0
    if primary in ("task", "mixed"):
        task_types, task_method, task_ms = brain.classify_task(text)
    forced_task_types, forced_task_method, forced_task_ms = brain.classify_task(text)
    return {
        "primary": primary,
        "primary_method": primary_method,
        "primary_ms": primary_ms,
        "tool": task_types[0] if task_types else None,
        "tool_method": task_method,
        "tool_ms": task_ms,
        "forced_tool": forced_task_types[0] if forced_task_types else None,
        "forced_tool_method": forced_task_method,
        "forced_tool_ms": forced_task_ms,
    }


def _is_match(expected: Optional[str], actual: Optional[str]) -> bool:
    return expected == actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        choices=("minilm", "llm"),
        default="minilm",
        help="minilm uses local sentence-transformer label prompts; llm uses a live structured prompt classifier",
    )
    parser.add_argument(
        "--live-current",
        action="store_true",
        help="allow the current BrainService comparator to call configured LLM APIs",
    )
    args = parser.parse_args()

    if args.backend == "llm":
        classifier = PromptToolClassifier()
    else:
        classifier = ExperimentalToolClassifier()

    if not args.live_current:
        brain_module.GROQ_API_KEYS = []

    brain = BrainService(groq_service=None)

    current_primary_ok = 0
    current_tool_ok = 0
    experiment_primary_ok = 0
    experiment_tool_ok = 0
    rows = []

    for case in CASES:
        current = _current_prediction(brain, case.text)
        exp_primary, exp_tool = classifier.classify_route(case.text)
        exp_tool_label = exp_tool.label if exp_tool else None

        cur_primary_match = _is_match(case.primary, current["primary"])
        cur_tool_match = case.tool is None or _is_match(case.tool, current["tool"])
        exp_primary_match = _is_match(case.primary, exp_primary.label)
        exp_tool_match = case.tool is None or _is_match(case.tool, exp_tool_label)

        current_primary_ok += int(cur_primary_match)
        current_tool_ok += int(cur_tool_match)
        experiment_primary_ok += int(exp_primary_match)
        experiment_tool_ok += int(exp_tool_match)

        rows.append(
            {
                "text": case.text,
                "expected": f"{case.primary}/{case.tool or '-'}",
                "current": f"{current['primary']}/{current['tool'] or '-'}",
                "current_forced_tool": current["forced_tool"] or "-",
                "experiment": f"{exp_primary.label}/{exp_tool_label or '-'}",
                "experiment_backend": exp_tool.backend if exp_tool else exp_primary.backend,
                "experiment_match": exp_tool.matched_example if exp_tool else exp_primary.matched_example,
                "note": case.note,
                "ok": exp_primary_match and exp_tool_match,
            }
        )

    total = len(CASES)
    tool_cases = sum(1 for case in CASES if case.tool is not None)

    print("Routing classifier experiment")
    print("=" * 80)
    print(f"Cases: {total} total, {tool_cases} with tool labels")
    print(f"Current primary accuracy:    {current_primary_ok}/{total}")
    print(f"Current routed-tool accuracy:{current_tool_ok}/{total}")
    print(f"Experiment primary accuracy: {experiment_primary_ok}/{total}")
    print(f"Experiment tool accuracy:    {experiment_tool_ok}/{total}")
    print()
    print("Important comparison: current_forced_tool shows what happens if the")
    print("existing primary stage sends a message into task classification.")
    print()

    for row in rows:
        status = "OK" if row["ok"] else "MISS"
        print(f"[{status}] {row['text']}")
        print(f"  expected:   {row['expected']}")
        print(f"  current:    {row['current']} (forced tool: {row['current_forced_tool']})")
        print(f"  experiment: {row['experiment']} via {row['experiment_backend']}")
        print(f"  matched:    {row['experiment_match']}")
        if row["note"]:
            print(f"  note:       {row['note']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
