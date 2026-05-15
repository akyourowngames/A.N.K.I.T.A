import argparse
import logging
import sys
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from config import ASSISTANT_NAME, BASE_DIR, GROQ_API_KEYS
from app.services.latency_optimizer import decision_cache, latency_optimizer
from app.services.model_registry import model_selector

console = Console()
logger = logging.getLogger("J.A.R.V.I.S")

TYPING_ANIMATIONS = [
    "[dots] Thinking...",
    "[dots] Processing...",
    "[dots] Analyzing...",
    "[dots] Working on it...",
]


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_chat_service(rebuild_index: bool = False, background_tasks: bool = False):
    if not GROQ_API_KEYS:
        raise RuntimeError("No NVIDIA_API_KEY configured. Add it to .env before starting the CLI.")

    from app.services.brain_service import BrainService
    from app.services.chat_service import ChatService
    from app.services.groq_service import GroqService
    from app.services.prompt_router_service import PromptRouterService
    from app.services.realtime_service import RealtimeGroqService
    from app.services.task_executor import TaskExecutor
    from app.services.task_manager import TaskManager
    from app.services.vector_store import VectorStoreService
    from app.services.vision_service import VisionService

    vector_store_service = VectorStoreService()
    if rebuild_index:
        vector_store_service.create_vector_store()
    else:
        vector_store_service.load_or_create_vector_store()

    groq_service = GroqService(vector_store_service)
    realtime_service = RealtimeGroqService(vector_store_service)
    brain_service = BrainService(groq_service)
    prompt_router_service = PromptRouterService()
    task_executor = TaskExecutor(groq_service=groq_service)
    task_manager = TaskManager(task_executor=task_executor) if background_tasks else None
    vision_service = VisionService()

    return ChatService(
        groq_service,
        realtime_service,
        brain_service,
        task_executor=task_executor,
        vision_service=vision_service,
        task_manager=task_manager,
        prompt_router=prompt_router_service,
    )


def print_header(session_id: str) -> None:
    console.print()
    title = Text()
    title.append(f" {ASSISTANT_NAME} ", style="bold cyan on black")
    console.print(title)
    console.print("Streaming text | Multi-model | Decision caching | Optimized latency", style="dim")
    console.print(f"Session: {session_id}", style="dim")
    console.print()
    console.print("Commands:", style="bold")
    console.print("  /new       Start a fresh chat session", style="dim")
    console.print("  /session   Show the active session id", style="dim")
    console.print("  /stats     Show latency & cache stats", style="dim")
    console.print("  /models    List available NVIDIA models", style="dim")
    console.print("  /help      Show this help", style="dim")
    console.print("  /exit      Quit the CLI", style="dim")
    console.print()


def print_help() -> None:
    console.print("\n[bold]Commands[/bold]")
    console.print("/new       Start a fresh chat session")
    console.print("/session   Show the active session id")
    console.print("/stats     Show latency & cache statistics")
    console.print("/models    List available NVIDIA models")
    console.print("/help      Show this help")
    console.print("/exit      Quit the CLI")


def print_stats() -> None:
    console.print("\n[bold]Performance Statistics[/bold]")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="dim")
    table.add_column("Value", style="green")

    cache_stats = decision_cache.stats()
    table.add_row("Decision Cache Size", str(cache_stats["size"]))
    table.add_row("Cache Hit Rate", cache_stats["hit_rate"])
    table.add_row("Cache Hits", str(cache_stats["hits"]))
    table.add_row("Cache Misses", str(cache_stats["misses"]))

    latency_report = latency_optimizer.get_report()
    for op, stats in latency_report.items():
        if isinstance(stats, dict):
            table.add_row(f"Latency: {op}", f"{stats['avg_ms']:.0f}ms (avg)")

    console.print(table)
    console.print()


def print_models() -> None:
    console.print("\n[bold]Available NVIDIA Models[/bold]")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Model", style="green")
    table.add_column("Tier", style="yellow")
    table.add_column("Avg Latency", style="dim")
    table.add_row("meta/llama-3.1-8b-instruct", "fast", "~200ms")
    table.add_row("google/gemma-2-9b-it", "fast", "~200ms")
    table.add_row("microsoft/phi-3-mini-128k-instruct", "fast", "~150ms")
    table.add_row("meta/llama-3.1-70b-instruct", "balanced", "~500ms")
    table.add_row("nvidia/nemotron-3-nano-30b-a3b", "balanced", "~400ms")
    table.add_row("mistralai/mixtral-8x22b-instruct-v0.1", "balanced", "~400ms")
    table.add_row("meta/llama-3.1-405b-instruct", "powerful", "~1500ms")
    table.add_row("mistralai/mistral-large-2", "powerful", "~800ms")
    table.add_row("qwen/qwen2.5-coder-32b-instruct", "balanced", "~500ms")
    table.add_row("nvidia/llama-3.1-nemotron-nano-vl-8b-v1", "vision", "~300ms")

    console.print(table)
    console.print("\n[dim]Models are auto-selected based on task type. Fast models for routing, balanced for chat, powerful for complex tasks.[/dim]")
    console.print()


def save_image_action(item: Any) -> Optional[Path]:
    if not isinstance(item, (list, tuple)) or len(item) < 2:
        return None

    image_bytes = item[1]
    if not isinstance(image_bytes, bytes):
        return None

    export_dir = BASE_DIR / "database" / "cli_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    output_path = export_dir / f"image_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
    output_path.write_bytes(image_bytes)
    return output_path


def handle_actions(actions: Dict[str, Any], open_actions: bool) -> None:
    link_groups = (
        actions.get("wopens") or [],
        actions.get("plays") or [],
        actions.get("googlesearches") or [],
        actions.get("youtubesearches") or [],
    )
    links = [url for group in link_groups for url in group if isinstance(url, str) and url.startswith(("http://", "https://"))]

    for url in links:
        if open_actions:
            webbrowser.open(url)
            console.print(f"\n[dim]Opened: {url}[/dim]")
        else:
            console.print(f"\n[dim]Action link: {url}[/dim]")

    for image in actions.get("images") or []:
        image_path = save_image_action(image)
        if image_path:
            console.print(f"\n[dim]Saved image: {image_path}[/dim]")
        elif isinstance(image, str):
            console.print(f"\n[dim]Image: {image}[/dim]")

    for content in actions.get("contents") or []:
        if content:
            console.print()
            console.print(content, markup=False)

    cam = actions.get("cam")
    if cam:
        console.print("\n[dim]Camera actions need the web UI because this CLI does not capture webcam frames.[/dim]")


def render_stream_with_typing(
    chunks: Iterable[Any],
    open_actions: bool,
    show_activity: bool,
) -> None:
    wrote_text = False
    response_text = ""
    activity_events = []
    first_chunk_received = False
    start_time = time.perf_counter()

    with Live(
        Spinner("dots", text=" Thinking...", style="cyan"),
        console=console,
        transient=True,
        refresh_per_second=10,
    ) as live:
        for chunk in chunks:
            if isinstance(chunk, dict):
                activity = chunk.get("_activity")
                if activity:
                    event = activity.get("event", "activity")
                    if event == "first_chunk" and not first_chunk_received:
                        first_chunk_received = True
                        elapsed = activity.get("elapsed_ms", 0)
                        live.update(Text(f" First token: {elapsed}ms", style="green"))
                    elif show_activity:
                        detail = activity.get("message") or activity.get("route") or activity.get("query_type") or ""
                        activity_events.append(f"{event}: {detail}")
                    continue

                actions = chunk.get("_actions")
                if actions:
                    handle_actions(actions, open_actions=open_actions)
                    continue

                background_tasks = chunk.get("_background_tasks")
                if background_tasks:
                    console.print(f"\n[dim]Background tasks: {background_tasks}[/dim]")
                    continue

                search_results = chunk.get("_search_results")
                if search_results and show_activity:
                    console.print(f"\n[dim]Search results received.[/dim]")
                    continue

                continue

            text = str(chunk)
            if text:
                if not first_chunk_received:
                    first_chunk_received = True
                    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                    live.update(Text(f" First token: {elapsed_ms}ms", style="green"))

                response_text += text
                live.update(Text(response_text, style="white"))
                wrote_text = True

    if wrote_text:
        console.print()

    total_time = time.perf_counter() - start_time
    console.print(f"[dim]Response generated in {total_time*1000:.0f}ms[/dim]")


def chat_once(
    chat_service: Any,
    session_id: str,
    message: str,
    open_actions: bool,
    show_activity: bool,
) -> None:
    active_session = chat_service.get_or_create_session(session_id)
    chunks = chat_service.process_jarvis_message_stream(active_session, message)
    render_stream_with_typing(chunks, open_actions=open_actions, show_activity=show_activity)


def run_interactive(args: argparse.Namespace) -> int:
    from app.services.groq_service import AllGroqApisFailedError

    chat_service = build_chat_service(
        rebuild_index=args.rebuild_index,
        background_tasks=args.background_tasks,
    )
    session_id = args.session
    chat_service.get_or_create_session(session_id)

    print_header(session_id)

    while True:
        try:
            message = Prompt.ask("\n[bold green]You[/bold green]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nExiting.")
            break

        if not message:
            continue

        command = message.lower()
        if command in ("/exit", "/quit"):
            break
        if command == "/help":
            print_help()
            continue
        if command == "/session":
            console.print(session_id)
            continue
        if command == "/stats":
            print_stats()
            continue
        if command == "/models":
            print_models()
            continue
        if command == "/new":
            session_id = f"cli-{uuid.uuid4().hex[:12]}"
            chat_service.get_or_create_session(session_id)
            console.print(f"New session: {session_id}", style="dim")
            continue

        try:
            chat_once(
                chat_service,
                session_id,
                message,
                open_actions=not args.no_open_actions,
                show_activity=args.activity,
            )
        except AllGroqApisFailedError as e:
            console.print(f"\n{e}", style="red")
        except Exception as e:
            logger.exception("CLI chat failed")
            console.print(f"\nError: {e}", style="red")

    if chat_service.task_manager:
        chat_service.task_manager.shutdown()
    return 0


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Terminal chat client for J.A.R.V.I.S.")
    parser.add_argument("--session", default="cli", help="Session id to load or create.")
    parser.add_argument("--once", help="Send one message, stream the response, then exit.")
    parser.add_argument("--no-open-actions", action="store_true", help="Print action links instead of opening them.")
    parser.add_argument("--activity", action="store_true", help="Show routing/activity events while streaming.")
    parser.add_argument("--rebuild-index", action="store_true", help="Rebuild the vector index before chat.")
    parser.add_argument("--background-tasks", action="store_true", help="Use background task manager like the web server.")
    parser.add_argument("--verbose", action="store_true", help="Show service logs.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    if not args.once:
        return run_interactive(args)

    try:
        chat_service = build_chat_service(
            rebuild_index=args.rebuild_index,
            background_tasks=args.background_tasks,
        )

        chat_once(
            chat_service,
            args.session,
            args.once,
            open_actions=not args.no_open_actions,
            show_activity=args.activity,
        )
        if chat_service.task_manager:
            chat_service.task_manager.shutdown()
        return 0

    except Exception as e:
        console.print(f"Startup failed: {e}", style="red")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
