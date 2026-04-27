from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jakata_agent.config import load_settings
from jakata_agent.runtime import create_runtime


def export_tools(output: Path, *, public_only: bool) -> dict[str, object]:
    settings = load_settings()
    runtime = create_runtime(settings)
    manifest = runtime.tools.manifest(public_only=public_only)
    def clean(value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value))
        return text.encode("ascii", "ignore").decode("ascii")

    tools = [
        {
            "label": clean(tool["name"]),
            "description": clean(tool.get("description", "")),
            "safety": clean(tool.get("safety", "")),
        }
        for tool in manifest
    ]
    payload = {
        "version": 1,
        "source": "jakata_agent.runtime.create_runtime().tools.manifest",
        "public_only": public_only,
        "tools": tools,
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the live JAKATA tool manifest into router/tools.json.")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "tools.json")
    parser.add_argument("--public-only", action="store_true", help="Export only public tools instead of every registered tool.")
    args = parser.parse_args()
    payload = export_tools(args.output, public_only=args.public_only)
    print(json.dumps({"output": str(args.output), "tool_count": len(payload["tools"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
