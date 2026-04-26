# JAKATA Routing Benchmark

This benchmark exercises the live JAKATA runtime and router against an editable set of prompt cases.
It does not execute planned tools; it measures whether the runtime chooses the right route.

Run:

```powershell
.\.venv\Scripts\python.exe .\benchmarks\routing_benchmark.py
```

Outputs are written to `data/logs/benchmarks/`, including `routing-benchmark-latest.json`.

The cases live in `benchmarks/routing_cases.json`. Add new tools or scenarios there instead of adding routing rules to application code.
