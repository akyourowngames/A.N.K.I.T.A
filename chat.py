import os
import time
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

from agent_runtime import AgentRuntime, new_session
from agents import Orchestrator
from llm import build_runtime_from_env
from memory import get_memory_manager

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

    memory = get_memory_manager(WORKSPACE_ROOT)
    memory.attach_runtime(runtime)
    try:
        from agent_runtime import set_memory_root

        set_memory_root(WORKSPACE_ROOT)
    except Exception:
        pass

    use_multi_agent = _env_bool("ANKITA_MULTI_AGENT", True)
    orchestrator = Orchestrator(runtime=runtime, workspace_root=WORKSPACE_ROOT)
    agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)

    from tools.feedback_engine import init_engine as _init_fb

    feedback_engine = _init_fb(workspace_root=WORKSPACE_ROOT, llm_runtime=runtime)
    session_id = "cli-session"
    messages = new_session()

    print("\n╔══════════════════════════════════════╗")
    print("║   A.N.K.I.T.A  — SYSTEM ACTIVE       ║")
    print("╚══════════════════════════════════════╝")
    print(f"  Provider    : {runtime.provider}")
    print(f"  Model       : {runtime.model}")
    max_tokens_label = "AUTO" if runtime.max_tokens is None else str(runtime.max_tokens)
    print(f"  Max tokens  : {max_tokens_label}")
    print(f"  Workspace   : {WORKSPACE_ROOT}")
    print(f"  Multi-agent : {'ON' if use_multi_agent else 'OFF'}")
    print("\n  Commands: /exit  /reset  /mood  /agents on|off  /reauth github  /github status")
    print("─" * 42 + "\n")

    _last_iid: List[Optional[str]] = [None]

    while True:
        try:
            user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_text:
            continue

        if user_text.lower() == "/exit":
            print("Bye.")
            break

        if user_text.lower() == "/reset":
            messages = new_session("")
            print("Conversation reset.\n")
            continue

        if user_text.lower() in ("/agents on", "/agents off"):
            use_multi_agent = user_text.lower() == "/agents on"
            print(f"Multi-agent mode: {'ON' if use_multi_agent else 'OFF'}\n")
            continue

        if user_text.lower() in ("/reauth github", "/reauth-github"):
            try:
                from tools.auth_manager import get_github_token, github_token_status

                print("\n🔐 Starting GitHub re-authorization via Device Flow...")
                get_github_token(force_reauth=True)
                print(f"\n{github_token_status()}\n")
            except Exception as exc:
                print(f"\n❌ GitHub re-auth failed: {exc}\n")
            continue

        if user_text.lower() == "/github status":
            from tools.auth_manager import github_token_status

            print(f"\n{github_token_status()}\n")
            continue

        if user_text.lower() == "/feedback stats":
            print(f"\n{feedback_engine.get_stats()}\n")
            continue

        implicit_feedback = feedback_engine.detect_implicit_feedback(user_text, _last_iid[0])
        if implicit_feedback is not None:
            emoji = "👍" if implicit_feedback == "positive" else "👎"
            print(f"\nA.N.K.I.T.A: Thanks for the feedback {emoji}\n\nYou: ", end="", flush=True)
            continue

        try:
            if use_multi_agent:
                reply = orchestrator.run(user_text, messages)
            else:
                reply = agent.process_user_text(user_text, messages)
            print(f"\nA.N.K.I.T.A: {reply}\n")
        except Exception as err:
            print(f"Assistant [Error]: {err}\n")
        time.sleep(0)


if __name__ == "__main__":
    main()
