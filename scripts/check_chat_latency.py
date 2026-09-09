"""Measure local recall and optionally the configured provider; no chat is saved."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
parser = argparse.ArgumentParser()
parser.add_argument("--live-model", action="store_true")
args = parser.parse_args()

from memory.fast_recall import recall
for label in ("cold", "repeated"):
    start = time.perf_counter()
    context = recall("What do you remember about my projects?")
    print(json.dumps({"check": label + "_recall", "elapsed_ms": round((time.perf_counter() - start) * 1000), "context_characters": len(context)}), flush=True)
if args.live_model:
    from core.api_client import stream_agent_completion
    from core.config import get_default_model
    from core.models import Message
    model = get_default_model()
    print(json.dumps({"check": "configured_chat_model", "model": model}), flush=True)
    start = time.perf_counter()
    first = []
    def token(text):
        if not first:
            first.append(time.perf_counter())
            print(json.dumps({"check": "first_provider_token", "model": model, "elapsed_ms": round((first[0] - start) * 1000)}), flush=True)
    try:
        result = stream_agent_completion([Message("user", "Reply with one short greeting. Do not use tools.")],
            model, max_tokens=1200, timeout=45, on_token=token)
        print(json.dumps({"check": "provider_complete", "elapsed_ms": round((time.perf_counter() - start) * 1000), "characters": len(result.content)}), flush=True)
    except Exception as exc:
        print(json.dumps({"check": "provider_error", "elapsed_ms": round((time.perf_counter() - start) * 1000), "error": str(exc)[:300]}), flush=True)
