from __future__ import annotations

import sys
from pathlib import Path

from core.brain import Brain


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    project_root = Path(__file__).resolve().parent
    brain = Brain.create(project_root)

    print(f"{brain.ai_name} is ready. Type 'exit' to stop.")
    while True:
        user_text = input(f"{brain.user_name}> ").strip()
        if user_text.lower() in {"exit", "quit"}:
            print(f"{brain.ai_name}> Bye.")
            break
        if not user_text:
            continue

        try:
            reply = brain.answer(user_text)
        except Exception as error:
            reply = f"Error: {error}"

        print(f"{brain.ai_name}> {reply}")


if __name__ == "__main__":
    main()
