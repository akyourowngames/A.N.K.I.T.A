from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm_router_testbed.router.client import RouterModelConfig


def list_models(*, env_file: Path | None = None) -> list[str]:
    config = RouterModelConfig.from_env(env_file=env_file)
    client_kwargs = {"api_key": config.api_key, "timeout": config.timeout_seconds, "max_retries": 0}
    if config.base_url:
        client_kwargs["base_url"] = config.base_url
    client = OpenAI(**client_kwargs)
    response = client.models.list()
    return sorted({item.id for item in response.data})


def main() -> int:
    parser = argparse.ArgumentParser(description="List models available on the configured OpenAI-compatible router endpoint.")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument("--contains", default="", help="Optional substring filter.")
    args = parser.parse_args()

    if args.env_file:
        load_dotenv(args.env_file)
    models = list_models(env_file=args.env_file)
    if args.contains:
        needle = args.contains.lower()
        models = [model for model in models if needle in model.lower()]

    payload = {"count": len(models), "models": models}
    if args.output:
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
