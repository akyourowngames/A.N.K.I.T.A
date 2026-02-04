import argparse
import json
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from brain.semantic_intent import SemanticIntentMatcher


def _iter_queries(args: argparse.Namespace):
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            for line in f:
                q = line.strip()
                if q:
                    yield q
        return

    if args.queries:
        for q in args.queries:
            if q and q.strip():
                yield q.strip()
        return

    for line in sys.stdin:
        q = line.strip()
        if q:
            yield q


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("queries", nargs="*", help="Queries to evaluate")
    p.add_argument("--file", help="Text file with one query per line")
    p.add_argument("--model", default="all-MiniLM-L6-v2")
    p.add_argument("--threshold", type=float, default=0.65)
    p.add_argument("--json", action="store_true", help="Emit JSON lines")
    args = p.parse_args()

    matcher = SemanticIntentMatcher(model_name=args.model, threshold=0.0)
    if not matcher.enabled:
        print("Semantic matcher disabled (sentence-transformers not installed)")
        return 2

    out = []
    for q in _iter_queries(args):
        m = matcher.match(q)
        if m is None:
            intent = "unknown"
            score = 0.0
        else:
            intent = m.intent
            score = float(m.score)

        row = {
            "query": q,
            "intent": intent,
            "score": score,
            "above_threshold": score >= float(args.threshold),
        }
        out.append(row)

        if args.json:
            print(json.dumps(row, ensure_ascii=False))
        else:
            flag = "OK" if row["above_threshold"] and intent != "unknown" else "LOW"
            print(f"{flag}  score={score:.3f}  intent={intent}  | {q}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
