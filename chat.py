from pathlib import Path

from dotenv import load_dotenv

from agent_runtime import AgentRuntime, new_session
from llm import build_runtime_from_env
WORKSPACE_ROOT = Path.cwd().resolve()


def main() -> None:
    load_dotenv()
    runtime = build_runtime_from_env()
    agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)

    print("Chat CLI + File Tools")
    print(f"Provider: {runtime.provider}")
    print(f"Model: {runtime.model}")
    print(f"Max output tokens/request: {runtime.max_tokens}")
    print(f"Workspace: {WORKSPACE_ROOT}")
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


if __name__ == "__main__":
    main()
