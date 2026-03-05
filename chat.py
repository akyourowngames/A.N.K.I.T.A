import os
import threading
import time
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

from agent_runtime import AgentRuntime, new_session
from agents import Orchestrator
from agents.hive import HiveMind
from corn import CornRunner
from llm import build_runtime_from_env
from proactive import ProactiveEngine
from memory import get_memory_manager

WORKSPACE_ROOT = Path.cwd().resolve()

# Module-level reference so the WatchdogManager singleton is accessible globally
watchdog_mgr = None


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

    # Memory system — init singleton, anchor root, attach runtime
    memory = get_memory_manager(WORKSPACE_ROOT)
    memory.attach_runtime(runtime)
    try:
        from agent_runtime import set_memory_root
        set_memory_root(WORKSPACE_ROOT)
    except Exception:
        pass

    # Multi-agent orchestrator (uses Supervisor + Specialists + Synthesizer)
    use_multi_agent = _env_bool("ANKITA_MULTI_AGENT", True)
    orchestrator = Orchestrator(runtime=runtime, workspace_root=WORKSPACE_ROOT)
    agent = AgentRuntime(runtime=runtime, workspace_root=WORKSPACE_ROOT)

    # Self-improvement feedback engine
    from tools.feedback_engine import init_engine as _init_fb
    feedback_engine = _init_fb(workspace_root=WORKSPACE_ROOT, llm_runtime=runtime)

    # Session ID for CLI
    session_id = "cli-session"

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

    from tools.notification_router import NotificationRouter
    notification_router = NotificationRouter(WORKSPACE_ROOT)

    # Watchdog system — always-on 24/7 monitoring
    from watchdog_manager import WatchdogManager
    global watchdog_mgr  # expose as module global so orchestrator can reach it
    watchdog_mgr = WatchdogManager(workspace_root=WORKSPACE_ROOT, proactive=proactive)
    watchdog_mgr.load_config()
    watchdog_mgr.start_all()

    # Hive Mind — async background task manager
    hive = HiveMind(orchestrator=orchestrator, agent_runtime=agent, use_multi_agent=use_multi_agent)

    # Build fresh system-prompt messages
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
    print(f"  Proactive   : ON")
    print(f"  Scheduler   : {'ON' if runner is not None else 'OFF'}")
    print(f"  Hive Mind   : ON 🐝")
    print("\n  Commands: /exit  /reset  /agents on|off  /hive  /watchdogs  /reauth github  /github status  show <id>")
    print("─" * 42 + "\n")

    # Background thread: drains proactive events every 5 seconds even while
    # input("You: ") is blocking.
    _stop_event_watcher = threading.Event()

    def _event_watcher() -> None:
        while not _stop_event_watcher.is_set():
            events = proactive.get_pending_events()
            for event in events:
                result = notification_router.route_notification(event)
                if not result.get("delivered") or "cli" not in result.get("channels", []):
                    continue
                formatted = result.get("formatted_messages", {}).get("cli", event.message)
                if event.kind == "dream_epiphany":
                    epiphany_text = event.data.get("text", event.message)
                    if epiphany_text:
                        print(f"\n\n✨ [A.N.K.I.T.A — Dream] {epiphany_text}\n\nYou: ", end="", flush=True)
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
                        except Exception as _err:
                            print(f"\n[ANKITA] Content generation error: {_err}\n\nYou: ", end="", flush=True)
                else:
                    print(f"\n\n[ANKITA] {formatted}\n\nYou: ", end="", flush=True)
            # Drain Hive Mind drone completion notifications
            for note in hive.check_notifications():
                print(f"\n\n{note}\n\nYou: ", end="", flush=True)
            time.sleep(5)

    _watcher_thread = threading.Thread(target=_event_watcher, daemon=True, name="ProactiveEventWatcher")
    _watcher_thread.start()

    _last_iid: List[Optional[str]] = [None]  # mutable ref for nested _print_reply closure

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
            messages = new_session("")
            print("Conversation reset.\n")
            continue

        if user_text.lower() in ("/agents on", "/agents off"):
            use_multi_agent = user_text.lower() == "/agents on"
            print(f"Multi-agent mode: {'ON' if use_multi_agent else 'OFF'}\n")
            continue

        if user_text.lower() == "/hive":
            print(f"\n{hive.list_tasks()}\n")
            continue

        if user_text.lower() == "/watchdogs":
            status = watchdog_mgr.status() if watchdog_mgr else "⚠️ WatchdogManager not running."
            print(f"\n{status}\n")
            continue

        if user_text.lower() in ("/reauth github", "/reauth-github"):
            try:
                from tools.auth_manager import get_github_token, github_token_status
                print("\n🔐 Starting GitHub re-authorization via Device Flow...")
                get_github_token(force_reauth=True)
                print(f"\n{github_token_status()}\n")
            except Exception as _exc:
                print(f"\n❌ GitHub re-auth failed: {_exc}\n")
            continue

        if user_text.lower() == "/github status":
            from tools.auth_manager import github_token_status
            print(f"\n{github_token_status()}\n")
            continue

        if user_text.lower() == "/feedback stats":
            print(f"\n{feedback_engine.get_stats()}\n")
            continue

        if user_text.lower().startswith("show "):
            # Smart Fallback Protocol: only intercept if a real task ID exists.
            task_id = user_text[5:].strip()
            task_report = hive.get_result(task_id)
            if task_report and "No task found" not in task_report and "Error" not in task_report:
                print(f"\n{task_report}\n")
                continue
            # No real task found → fall through to agent

        # Detect implicit feedback ("good", "👍", etc.) before treating as new query
        _impl_fb = feedback_engine.detect_implicit_feedback(user_text, _last_iid[0])
        if _impl_fb is not None:
            _emoji = "👍" if _impl_fb == "positive" else "👎"
            print(f"\nA.N.K.I.T.A: Thanks for the feedback {_emoji}\n\nYou: ", end="", flush=True)
            continue

        # send_fn: called from background drone thread when reply is ready
        def _print_reply(text: str, _session_id: str = session_id, _iid_ref: List = _last_iid) -> None:
            if not text:
                return
            print(f"\nA.N.K.I.T.A: {text}\n\nYou: ", end="", flush=True)
            try:
                proactive.set_last_interaction()
                try:
                    from tools.feedback_engine import get_instance as _fb_get
                    _fb = _fb_get()
                    if _fb:
                        from tools.feedback_engine import _load_jsonl, _INSTANCE as _fb_inst
                        if _fb_inst is not None:
                            recent = _load_jsonl(_fb_inst._interactions_path, max_lines=1)
                            if recent:
                                _iid_ref[0] = recent[-1].get("id")
                            elif _iid_ref[0] is None:
                                _iid_ref[0] = _fb.new_interaction()
                                _fb.record_interaction(_iid_ref[0], "", text)
                except Exception:
                    pass
            except Exception:
                pass

        try:
            ack = hive.delegate(user_text, messages, send_fn=_print_reply)
            if ack:
                print(f"\nA.N.K.I.T.A: {ack}\n\nYou: ", end="", flush=True)
        except Exception as err:
            print(f"Assistant [Error]: {err}\n")
        continue

    _stop_event_watcher.set()
    proactive.stop()
    if runner is not None:
        runner.stop()


if __name__ == "__main__":
    main()
