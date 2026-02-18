import os
from pathlib import Path

from dotenv import load_dotenv

from agent_runtime import AgentRuntime, new_session
from corn import CornRunner
from llm import build_runtime_from_env
WORKSPACE_ROOT = Path.cwd().resolve()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def main() -> None:
    load_dotenv()
    runtime = build_runtime_from_env()
    agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)
    runner: CornRunner | None = None
    if _env_bool("CORN_AUTO_RUN", True):
        runner = CornRunner(
            workspace_root=WORKSPACE_ROOT,
            poll_interval_sec=float(os.getenv("CORN_POLL_INTERVAL_SEC", "5")),
            max_jobs_per_tick=int(os.getenv("CORN_MAX_JOBS_PER_TICK", "5")),
        )
        runner.start()

    print("Chat CLI + File Tools")
    print(f"Provider: {runtime.provider}")
    print(f"Model: {runtime.model}")
    print(f"Max output tokens/request: {runtime.max_tokens}")
    print(f"Workspace: {WORKSPACE_ROOT}")
    print(f"Corn scheduler: {'ON' if runner is not None else 'OFF'}")
    print("Type '/exit' to quit, '/reset' to clear history.\\n")

    messages = new_session()

    while True:
        try:
            user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\\nBye.")
            break

        if not user_text:
            continue
        if user_text.lower() == "/exit":
            print("Bye.")
            break
        if user_text.lower() == "/reset":
            messages = new_session()
            print("Conversation reset.")
            continue

        try:
            assistant_text = agent.process_user_text(user_text=user_text, messages=messages)
        except Exception as err:
            print(f"Assistant [Error]: {err}")
            continue

        print(f"Assistant: {assistant_text}\\n")

    if runner is not None:
        runner.stop()


if __name__ == "__main__":
    main()
