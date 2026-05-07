from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis_nim import chat_url, load_dotenv, stream_token


def main() -> int:
    workspace = Path.cwd()
    load_dotenv(workspace / ".env")
    args = build_parser().parse_args()

    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    base_url = os.environ.get("NVIDIA_BASE_URL", "").strip()
    if not api_key or not base_url:
        print("NVIDIA_API_KEY and NVIDIA_BASE_URL are required.")
        return 1

    endpoint = chat_url(base_url)
    profiles = load_profiles(args, base_url, api_key)
    if not profiles:
        print("No model profiles found.")
        return 1

    modes = benchmark_modes(args.mode)
    results = run_benchmarks(
        endpoint=endpoint,
        api_key=api_key,
        profiles=profiles,
        modes=modes,
        timeout_seconds=args.timeout,
        workers=args.workers,
        prompt=args.prompt,
        max_tokens=args.max_tokens,
    )
    report = build_report(args, profiles, results)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_summary(report, output_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark NVIDIA NIM model latency from live API responses.")
    parser.add_argument("--discover", action="store_true", help="Fetch models from the NVIDIA /models endpoint.")
    parser.add_argument("--catalog", default=os.environ.get("JARVIS_MODEL_CATALOG", "config/nim_models.json"))
    parser.add_argument("--output", default=os.environ.get("NIM_BENCHMARK_OUTPUT", "config/nim_benchmark_results.json"))
    parser.add_argument("--limit", type=int, default=env_int("NIM_BENCHMARK_LIMIT", 0))
    parser.add_argument("--workers", type=int, default=env_int("NIM_BENCHMARK_WORKERS", 8))
    parser.add_argument("--timeout", type=float, default=env_float("NIM_BENCHMARK_TIMEOUT_SECONDS", 10.0))
    parser.add_argument("--mode", choices=["stream", "json", "both"], default=os.environ.get("NIM_BENCHMARK_MODE", "stream"))
    parser.add_argument("--prompt", default=os.environ.get("NIM_BENCHMARK_PROMPT", "Reply with OK only."))
    parser.add_argument("--max-tokens", type=int, default=env_int("NIM_BENCHMARK_MAX_TOKENS", 8))
    return parser


def env_int(name: str, fallback: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def env_float(name: str, fallback: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return float(value)
    except ValueError:
        return fallback


def benchmark_modes(mode: str) -> list[str]:
    if mode == "both":
        return ["stream", "json"]
    return [mode]


def load_profiles(args: argparse.Namespace, base_url: str, api_key: str) -> list[dict[str, Any]]:
    if args.discover:
        models = discover_models(models_url(base_url), api_key, args.timeout)
        profiles = profiles_from_models(models)
    else:
        catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
        values = catalog.get("profiles", [])
        profiles = [profile for profile in values if isinstance(profile, dict)] if isinstance(values, list) else []

    if args.limit > 0:
        return profiles[: args.limit]
    return profiles


def models_url(base_url: str) -> str:
    clean = base_url.rstrip("/")
    suffix = "/chat/completions"
    if clean.endswith(suffix):
        clean = clean[: -len(suffix)]
    return clean + "/models"


def discover_models(url: str, api_key: str, timeout_seconds: float) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    values = data.get("data", []) if isinstance(data, dict) else []
    return [value for value in values if isinstance(value, dict)]


def profiles_from_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for model in models:
        model_id = model.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        profiles.append(
            {
                "name": model_id,
                "model": model_id,
                "owned_by": model.get("owned_by"),
                "source": "NVIDIA /models endpoint",
            }
        )
    return profiles


def run_benchmarks(
    endpoint: str,
    api_key: str,
    profiles: list[dict[str, Any]],
    modes: list[str],
    timeout_seconds: float,
    workers: int,
    prompt: str,
    max_tokens: int,
) -> list[dict[str, Any]]:
    tasks: list[tuple[dict[str, Any], str]] = []
    for profile in profiles:
        model = profile.get("model")
        if not isinstance(model, str) or not model.strip():
            continue
        for mode in modes:
            tasks.append((profile, mode))

    results: list[dict[str, Any]] = []
    max_workers = max(1, workers)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(run_probe, endpoint, api_key, profile, mode, timeout_seconds, prompt, max_tokens): (
                profile,
                mode,
            )
            for profile, mode in tasks
        }
        for future in concurrent.futures.as_completed(future_map):
            try:
                results.append(future.result())
            except Exception as error:
                profile, mode = future_map[future]
                results.append(
                    {
                        "name": profile.get("name"),
                        "model": profile.get("model"),
                        "mode": mode,
                        "ok": False,
                        "useful": False,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
    return sorted(results, key=result_sort_key)


def result_sort_key(result: dict[str, Any]) -> tuple[int, float, str]:
    useful = 0 if result.get("useful") else 1
    seconds = result.get("first_token_seconds")
    if not isinstance(seconds, (int, float)):
        seconds = result.get("seconds")
    if not isinstance(seconds, (int, float)):
        seconds = 999999.0
    model = result.get("model")
    return useful, float(seconds), model if isinstance(model, str) else ""


def run_probe(
    endpoint: str,
    api_key: str,
    profile: dict[str, Any],
    mode: str,
    timeout_seconds: float,
    prompt: str,
    max_tokens: int,
) -> dict[str, Any]:
    if mode == "stream":
        return run_stream_probe(endpoint, api_key, profile, timeout_seconds, prompt, max_tokens)
    return run_json_probe(endpoint, api_key, profile, timeout_seconds, prompt, max_tokens)


def run_json_probe(
    endpoint: str,
    api_key: str,
    profile: dict[str, Any],
    timeout_seconds: float,
    prompt: str,
    max_tokens: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        data = post_completion(endpoint, api_key, profile["model"], prompt, max_tokens, False, "application/json", timeout_seconds)
        elapsed = time.perf_counter() - started
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "") if isinstance(data, dict) else ""
        reply = normalize_reply(content)
        return base_result(profile, "json", True, elapsed, reply)
    except Exception as error:
        elapsed = time.perf_counter() - started
        return error_result(profile, "json", elapsed, error)


def run_stream_probe(
    endpoint: str,
    api_key: str,
    profile: dict[str, Any],
    timeout_seconds: float,
    prompt: str,
    max_tokens: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    first_token_seconds = None
    full_text = ""
    try:
        request = completion_request(endpoint, api_key, profile["model"], prompt, max_tokens, True, "text/event-stream")
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data_line = line[len("data:") :].strip()
                if data_line == "[DONE]":
                    break
                data = json.loads(data_line)
                token = stream_token(data)
                if token:
                    if first_token_seconds is None:
                        first_token_seconds = time.perf_counter() - started
                    full_text += token
        elapsed = time.perf_counter() - started
        result = base_result(profile, "stream", True, elapsed, full_text)
        result["first_token_seconds"] = round(first_token_seconds, 3) if first_token_seconds is not None else None
        return result
    except Exception as error:
        elapsed = time.perf_counter() - started
        return error_result(profile, "stream", elapsed, error)


def post_completion(
    endpoint: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
    stream: bool,
    accept: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    request = completion_request(endpoint, api_key, model, prompt, max_tokens, stream, accept)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def completion_request(
    endpoint: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
    stream: bool,
    accept: str,
) -> urllib.request.Request:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    return urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": accept,
        },
        method="POST",
    )


def base_result(profile: dict[str, Any], mode: str, ok: bool, elapsed: float, reply: str) -> dict[str, Any]:
    clean_reply = normalize_reply(reply)
    return {
        "name": profile.get("name"),
        "model": profile.get("model"),
        "owned_by": profile.get("owned_by"),
        "mode": mode,
        "ok": ok,
        "useful": bool(clean_reply.strip()),
        "seconds": round(elapsed, 3),
        "reply": clean_reply,
    }


def error_result(profile: dict[str, Any], mode: str, elapsed: float, error: Exception) -> dict[str, Any]:
    return {
        "name": profile.get("name"),
        "model": profile.get("model"),
        "owned_by": profile.get("owned_by"),
        "mode": mode,
        "ok": False,
        "useful": False,
        "seconds": round(elapsed, 3),
        "error": error_text(error),
    }


def error_text(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        detail = error.read().decode("utf-8", errors="replace")
        return clip_text(f"{error.code} {error.reason}: {detail}", 600)
    if isinstance(error, TimeoutError):
        return "TimeoutError: read timed out"
    return clip_text(f"{type(error).__name__}: {error}", 600)


def normalize_reply(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def clip_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def build_report(args: argparse.Namespace, profiles: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    stream_results = [result for result in results if result.get("mode") == "stream" and result.get("useful")]
    json_results = [result for result in results if result.get("mode") == "json" and result.get("useful")]
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "discovered": bool(args.discover),
        "profile_count": len(profiles),
        "result_count": len(results),
        "useful_count": len([result for result in results if result.get("useful")]),
        "prompt": args.prompt,
        "timeout_seconds": args.timeout,
        "workers": args.workers,
        "recommended_stream": stream_results[0] if stream_results else None,
        "recommended_json": json_results[0] if json_results else None,
        "top_stream": stream_results[:10],
        "top_json": json_results[:10],
        "results": results,
    }


def print_summary(report: dict[str, Any], output_path: Path) -> None:
    print(f"Saved benchmark report -> {output_path}")
    print(f"Profiles tested -> {report.get('profile_count')}")
    print(f"Useful replies -> {report.get('useful_count')}")
    stream = report.get("recommended_stream")
    if isinstance(stream, dict):
        print(
            "Fastest stream -> "
            + f"{stream.get('model')} first_token={stream.get('first_token_seconds')}s total={stream.get('seconds')}s"
        )
    json_result = report.get("recommended_json")
    if isinstance(json_result, dict):
        print("Fastest json -> " + f"{json_result.get('model')} total={json_result.get('seconds')}s")
    print("Top stream:")
    for result in report.get("top_stream", []):
        print(
            "  "
            + f"{result.get('model')} first_token={result.get('first_token_seconds')}s total={result.get('seconds')}s"
        )


if __name__ == "__main__":
    raise SystemExit(main())
