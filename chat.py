import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from agent_runtime import AgentRuntime, new_session
from agents import Orchestrator
from agents.hive import HiveMind
from corn import CornRunner
from llm import build_runtime_from_env
from memory import MemoryStore
from proactive import ProactiveEngine
from session_manager import SessionManager

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

    # Multi-agent orchestrator (uses Supervisor + Specialists + Synthesizer)
    use_multi_agent = _env_bool("ANKITA_MULTI_AGENT", True)
    orchestrator = Orchestrator(runtime=runtime, workspace_root=WORKSPACE_ROOT)
    agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)

    # Vector memory
    memory = MemoryStore(workspace_root=WORKSPACE_ROOT)

    # ── Session Manager (Black Box / Flight Recorder) ✈️ ──────────────────────
    session = SessionManager(workspace_root=WORKSPACE_ROOT, runtime=runtime)

    # Corn scheduler
    runner: CornRunner | None = None
    if _env_bool("CORN_AUTO_RUN", True):
        runner = CornRunner(
            workspace_root=WORKSPACE_ROOT,
            poll_interval_sec=float(os.getenv("CORN_POLL_INTERVAL_SEC", "5")),
            max_jobs_per_tick=int(os.getenv("CORN_MAX_JOBS_PER_TICK", "5")),
        )
        runner.start()

    # Proactive engine
    proactive = ProactiveEngine(workspace_root=WORKSPACE_ROOT)
    proactive.attach_runtime(runtime)
    proactive.start()

    # Hive Mind — async background task manager
    hive = HiveMind(orchestrator=orchestrator, agent_runtime=agent, use_multi_agent=use_multi_agent)

    # ── Resurrection Protocol 🧟 ───────────────────────────────────────────────
    # Build fresh system-prompt messages, then overlay any saved history on top.
    base_messages = new_session()
    restored_history = session.load()

    if restored_history:
        messages = session.build_restored_messages(base_messages)
    else:
        messages = base_messages

    session_id = "cli-session"
    session_label = f"RESTORED ({len(restored_history)} msgs)" if restored_history else "NEW"

    # Now that session_id is set, attach memory properly
    proactive.attach_memory(memory, session_id)

    print("\n╔══════════════════════════════════════╗")
    print("║   A.N.K.I.T.A  — SYSTEM ACTIVE       ║")
    print("╚══════════════════════════════════════╝")
    print(f"  Provider    : {runtime.provider}")
    print(f"  Model       : {runtime.model}")
    max_tokens_label = "AUTO" if runtime.max_tokens is None else str(runtime.max_tokens)
    print(f"  Max tokens  : {max_tokens_label}")
    print(f"  Workspace   : {WORKSPACE_ROOT}")
    print(f"  Multi-agent : {'ON' if use_multi_agent else 'OFF'}")
    print(f"  Memory      : {'ON (ChromaDB)' if memory.enabled else 'OFF (chromadb not installed)'}")
    print(f"  Proactive   : ON")
    print(f"  Scheduler   : {'ON' if runner is not None else 'OFF'}")
    print(f"  Hive Mind   : ON 🐝")
    print(f"  Session     : {session_label} ✈️")
    print("\n  Commands: /exit  /reset  /agents on|off  /memory  /hive  show <id>")
    print("─" * 42 + "\n")

    if session.restored:
        print("🧠 A.N.K.I.T.A: Session restored — I remember where we left off.\n")

    # Background thread: drains proactive events every 5 seconds even while
    # input("You: ") is blocking. This is how DreamState epiphanies get printed
    # without needing the user to press Enter first.
    _stop_event_watcher = threading.Event()

    def _event_watcher() -> None:
        while not _stop_event_watcher.is_set():
            events = proactive.get_pending_events()
            for event in events:
                if event.kind == "dream_epiphany":
                    epiphany_text = event.data.get("text", event.message)
                    if epiphany_text:
                        print(f"\n\n✨ [A.N.K.I.T.A — Dream] {epiphany_text}\n\nYou: ", end="", flush=True)
                        try:
                            memory.add(session_id, "assistant", epiphany_text)
                        except Exception:
                            pass
                elif event.kind == "content_request":
                    suggested_prompt = event.data.get("suggested_prompt", "")
                    if suggested_prompt:
                        print(f"\n\n[ANKITA] Processing content request in background...\n\nYou: ", end="", flush=True)
                        try:
                            if use_multi_agent:
                                content_reply = orchestrator.run(
                                    user_text=suggested_prompt,
                                    messages=new_session(),
                                )
                            else:
                                content_reply = agent.process_user_text(
                                    user_text=suggested_prompt,
                                    messages=new_session(),
                                )
                            print(f"\n[ANKITA] {content_reply}\n\nYou: ", end="", flush=True)
                            memory.add(session_id, "assistant", content_reply)
                        except Exception as _err:
                            print(f"\n[ANKITA] Content generation error: {_err}\n\nYou: ", end="", flush=True)
                else:
                    print(f"\n\n[ANKITA] {event.message}\n\nYou: ", end="", flush=True)
            # Drain Hive Mind drone completion notifications
            for note in hive.check_notifications():
                print(f"\n\n{note}\n\nYou: ", end="", flush=True)
            time.sleep(5)

    _watcher_thread = threading.Thread(target=_event_watcher, daemon=True, name="ProactiveEventWatcher")
    _watcher_thread.start()

    while True:
        try:
            user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_text:
            continue

        # Record interaction so idle/dream tracker resets
        proactive.set_last_interaction()

        if user_text.lower() == "/exit":
            print("Bye.")
            break

        if user_text.lower() == "/reset":
            messages = new_session()
            session.clear()
            print("Conversation reset.\n")
            continue

        if user_text.lower() in ("/agents on", "/agents off"):
            use_multi_agent = user_text.lower() == "/agents on"
            print(f"Multi-agent mode: {'ON' if use_multi_agent else 'OFF'}\n")
            continue

        if user_text.lower() == "/memory":
            # Show the persistent JSON vault (long-term memory)
            from tools.memory_ops import recall, format_memory_block
            block = format_memory_block()
            if block:
                print(f"\n{block}\n")
            else:
                print("\n[Memory vault is empty. Say 'remember that...' to add memories.]\n")
            # Also show recent ChromaDB vector memories
            hits = memory.search("recent", n=5)
            if hits:
                print("Recent session memories (ChromaDB):")
                for h in hits:
                    print(f"  [{h['meta'].get('role','?')}] {h['text'][:120]}")
            print()
            continue

        if user_text.lower() == "/hive":
            print(f"\n{hive.list_tasks()}\n")
            continue

        if user_text.lower().startswith("show "):
            task_id = user_text[5:].strip()
            print(f"\n{hive.get_result(task_id)}\n")
            continue

        # ── Save user turn to session vault ───────────────────────────────────
        session.add_message("user", user_text)

        # Inject relevant memories as context
        mem_context = memory.format_memory_context(user_text, n=4)
        if mem_context and messages:
            # Insert memory as a temporary system message before user turn
            messages.append({"role": "system", "content": mem_context})

        # send_fn: called from background drone thread when reply is ready
        def _print_reply(text: str, _session_id: str = session_id) -> None:
            if not text:
                return
            print(f"\nA.N.K.I.T.A: {text}\n\nYou: ", end="", flush=True)
            try:
                memory.add(_session_id, "assistant", text)
                proactive.set_last_interaction()
                # ── Save assistant reply to session vault ──────────────────
                session.add_message("assistant", text)
                # ── Compress if history is getting long (background thread) ─
                threading.Thread(
                    target=session.compress_if_needed,
                    daemon=True,
                    name="SessionCompressor",
                ).start()
            except Exception:
                pass

        try:
            ack = hive.delegate(user_text, messages, send_fn=_print_reply)
            if ack:
                # Heavy task — print the "Started 🐝" acknowledgement immediately
                print(f"\nA.N.K.I.T.A: {ack}\n\nYou: ", end="", flush=True)
            # For normal tasks: reply comes asynchronously via _print_reply
            # Input loop continues immediately — fully non-blocking ✅
        except Exception as err:
            print(f"Assistant [Error]: {err}\n")
        continue

        # Store turn in vector memory  (unreachable — kept for reference)
        memory.add(session_id, "user", user_text)
        memory.add(session_id, "assistant", "")

    _stop_event_watcher.set()
    proactive.stop()
    if runner is not None:
        runner.stop()


if __name__ == "__main__":
    main()
