from __future__ import annotations

import json
import time

from prompt_toolkit import prompt
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich import box
from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from jakata_agent.agent import JakataAgent
from jakata_agent.runtime import JakataRuntime, create_runtime


console = Console(soft_wrap=True, highlight=False)
bindings = KeyBindings()
prompt_style = Style.from_dict(
    {
        "prompt.user": "bold #9ec5a2",
        "prompt.sep": "#8b949e",
        "toolbar": "bg:#1f2328 #d0d7de",
        "toolbar.key": "bg:#30363d #f0f6fc bold",
        "continuation": "#8b949e",
    }
)
STREAM_FRAME_SECONDS = 1 / 24
TASK_STATUS_STYLES = {
    "queued": "yellow",
    "running": "cyan",
    "awaiting_approval": "yellow",
    "completed": "green",
    "failed": "red",
    "denied": "red",
    "canceled": "magenta",
    "cancelled": "magenta",
}


@bindings.add("enter")
def _(event) -> None:
    event.current_buffer.validate_and_handle()


@bindings.add("escape", "enter")
def _(event) -> None:
    event.current_buffer.insert_text("\n")


def build_agent() -> tuple[JakataAgent, JakataRuntime]:
    runtime = create_runtime()
    return (
        JakataAgent(
            settings=runtime.settings,
            client=runtime.client,
            tools=runtime.tools,
            memory=runtime.memory,
            router=runtime.router,
        validator=runtime.validator,
        task_store=runtime.task_store,
        task_engine=runtime.task_engine,
        ),
        runtime,
    )


def _fit_value(value: object) -> str:
    text = str(value).strip()
    return text or "-"


def _build_detail_table(rows: list[tuple[str, object]]) -> Table:
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(style="bold #9ec5a2", no_wrap=True, width=12)
    table.add_column(style="white", ratio=1, overflow="fold")
    for label, value in rows:
        table.add_row(label, _fit_value(value))
    return table


def print_welcome(agent: JakataAgent) -> None:
    intro = Group(
        Text("JAKATA CLI", style="bold #9ec5a2"),
        Text("Simple operator shell for foreground chat and tools.", style="#8b949e"),
    )
    session = _build_detail_table(
        [
            ("Session", agent.settings.session_id),
            ("Data", agent.settings.data_dir),
            ("Input", "Enter sends, Esc+Enter adds a newline"),
        ]
    )
    commands = Table.grid(expand=True, padding=(0, 1))
    commands.add_column(style="bold #9ec5a2", no_wrap=True, width=12)
    commands.add_column(style="white", ratio=1, overflow="fold")
    for command, description in [
        ("/help", "show commands"),
        ("/clear", "reset chat history"),
        ("/models", "show model order"),
        ("/camera", "open live camera preview"),
        ("/memory", "show memory paths"),
        ("/tasks", "list recent tasks"),
        ("/task <id>", "inspect one task"),
        ("/approve <id>", "approve a waiting action"),
        ("/deny <id>", "deny a waiting action"),
        ("/cancel <id>", "cancel a task"),
        ("/agents <id>", "inspect agent runs"),
        ("/graph <query>", "search the memory graph"),
        ("/exit", "leave the shell"),
    ]:
        commands.add_row(command, description)

    toolkit = Text(agent.tools.describe(public_only=True) or "No public tools registered.", overflow="fold", no_wrap=False)

    console.print(Panel(intro, border_style="#4b5563", box=box.SQUARE, padding=(0, 1)))
    console.print(
        Columns(
            [
                Panel(session, title="Session", border_style="#4b5563", box=box.SQUARE, padding=(0, 1)),
                Panel(toolkit, title="Toolkit", border_style="#4b5563", box=box.SQUARE, padding=(0, 1)),
            ],
            expand=True,
            equal=True,
        )
    )
    console.print(Panel(commands, title="Commands", border_style="#4b5563", box=box.SQUARE, padding=(0, 1)))
    console.print()


def print_help() -> None:
    table = Table(box=box.SIMPLE, expand=True, header_style="bold #9ec5a2")
    table.add_column("Command", style="bold #9ec5a2", no_wrap=True)
    table.add_column("Action", overflow="fold")
    for command, description in [
        ("/help", "show commands"),
        ("/clear", "reset chat history"),
        ("/models", "show configured model fallback order"),
        ("/camera", "toggle the live camera preview on"),
        ("/camera off", "close the live camera preview"),
        ("/camera status", "show live camera state"),
        ("/camera ask <prompt>", "force live camera analysis now"),
        ("/memory", "show memory storage location"),
        ("/tasks", "list recent tasks"),
        ("/task <id>", "inspect one task and recent events"),
        ("/approve <id>", "approve a waiting action"),
        ("/deny <id>", "deny a waiting action"),
        ("/cancel <id>", "cancel a task"),
        ("/agents <id>", "inspect agent runs for a task"),
        ("/graph <query>", "inspect the live memory graph"),
        ("Enter", "send message"),
        ("Esc+Enter", "insert newline for long prompts"),
        ("/exit", "quit"),
    ]:
        table.add_row(command, description)
    console.print(Panel(table, title="Help", border_style="#4b5563", box=box.SQUARE, padding=(0, 1)))


def read_user_input() -> str:
    with patch_stdout(raw=True):
        return prompt(
            [("class:prompt.user", "you"), ("class:prompt.sep", " > ")],
            multiline=True,
            key_bindings=bindings,
            mouse_support=False,
            style=prompt_style,
            prompt_continuation=lambda width, line_number, wrap_count: [("class:continuation", "... ")],
            bottom_toolbar=[
                ("class:toolbar.key", " Enter "),
                ("class:toolbar", " send "),
                ("class:toolbar.key", " Esc+Enter "),
                ("class:toolbar", " newline "),
                ("class:toolbar.key", " /help "),
                ("class:toolbar", " commands "),
            ],
        ).strip()


def preview_user_input(user_input: str, limit: int = 140) -> str:
    flattened = " ".join(user_input.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 3].rstrip() + "..."


def render_task_summary(task) -> str:
    table = _build_detail_table(
        [
            ("ID", task.id),
            ("Status", task.status),
            ("Goal", task.goal),
            ("Repairs", f"{task.repair_count}/{task.repair_limit}"),
            ("Actions", f"{task.action_count}/{task.action_limit}"),
            ("Result", task.result_summary),
            ("Error", task.last_error),
            ("Approval", task.pending_approval.get("id", "") if getattr(task, "pending_approval", {}) else ""),
        ]
    )
    with console.capture() as capture:
        console.print(table)
    return capture.get().rstrip()


def render_task_panel(task, *, title: str | None = None, body: str | None = None) -> Panel:
    status_style = TASK_STATUS_STYLES.get(task.status, "yellow")
    return Panel(
        body or render_task_summary(task),
        title=title or f"Task {task.status}",
        border_style=status_style,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _camera_status_body(runtime: JakataRuntime) -> str:
    status = runtime.camera_session.status()
    lines = [
        f"active: {status.active}",
        f"device: {status.device_index}",
        f"resolution: {status.frame_width}x{status.frame_height}",
        f"last frame: {status.latest_frame_path or '-'}",
        f"vision model: {runtime.settings.vision_model_chain[0] if runtime.settings.vision_model_chain else '-'}",
    ]
    if status.last_frame_time:
        lines.append(f"updated: {time.strftime('%H:%M:%S', time.localtime(status.last_frame_time))}")
    if status.error:
        lines.append(f"error: {status.error}")
    return "\n".join(lines)


def _camera_panel(runtime: JakataRuntime, title: str = "Camera", border_style: str = "#4b5563") -> Panel:
    return Panel(_camera_status_body(runtime), title=title, border_style=border_style, box=box.SQUARE, padding=(0, 1))


def handle_camera_command(user_input: str, runtime: JakataRuntime) -> tuple[bool, str | None]:
    stripped = user_input.strip()
    if not stripped.lower().startswith("/camera"):
        return False, None

    parts = stripped.split(maxsplit=2)
    subcommand = parts[1].lower() if len(parts) >= 2 else "on"
    prompt = parts[2].strip() if len(parts) >= 3 else ""

    if subcommand in {"on", "start"}:
        status = runtime.camera_session.start()
        if status.active:
            return True, "Live camera preview opened. Ask what JAKATA sees or use /camera ask <prompt>."
        return True, f"Camera failed to start: {status.error or 'unknown camera error'}"
    if subcommand in {"off", "stop"}:
        runtime.camera_session.stop()
        return True, "Live camera preview closed."
    if subcommand == "status":
        return True, None
    if subcommand in {"ask", "analyze", "analyse", "describe"}:
        if not prompt:
            return True, "Usage: /camera ask <prompt>"
        result = runtime.tools.execute("camera", {"action": "describe", "prompt": prompt})
        return True, result.summary
    if subcommand == "capture":
        result = runtime.tools.execute("camera", {"action": "capture"})
        return True, result.summary
    return True, "Camera commands: /camera, /camera off, /camera status, /camera ask <prompt>"


def _should_refresh_stream(last_render: float, now: float, chunk: str) -> bool:
    if last_render == 0.0:
        return True
    elapsed = now - last_render
    if elapsed >= STREAM_FRAME_SECONDS:
        return True
    return chunk.endswith(("\n", ".", "!", "?", ":", ";")) and elapsed >= 0.05


def _render_response_panel(content: str, *, model: str, streaming: bool, elapsed: float) -> Panel:
    title = Text.assemble(
        ("JAKATA", "bold #9ec5a2"),
        (" streaming" if streaming else " reply", "white"),
    )
    subtitle = Text()
    subtitle.append("streaming" if streaming else "complete", style="#8b949e")
    if model:
        subtitle.append(f"  {model}", style="#8b949e")
    subtitle.append(f"  {elapsed:.1f}s", style="#8b949e")
    body = Text(content or "thinking...", style="white" if content else "#8b949e", overflow="fold", no_wrap=False)
    return Panel(body, title=title, subtitle=subtitle, border_style="#4b5563", box=box.SQUARE, padding=(0, 1))


def stream_assistant_reply(agent: JakataAgent, user_input: str) -> str:
    chunks: list[str] = []
    current_model = ""
    last_render = 0.0
    started = time.perf_counter()

    with Live(
        _render_response_panel("", model="", streaming=True, elapsed=0.0),
        console=console,
        refresh_per_second=24,
        transient=False,
        vertical_overflow="visible",
    ) as live:
        for model, chunk in agent.stream_reply(user_input):
            current_model = model
            chunks.append(chunk)
            now = time.perf_counter()
            if _should_refresh_stream(last_render, now, chunk):
                live.update(
                    _render_response_panel("".join(chunks), model=current_model, streaming=True, elapsed=now - started),
                    refresh=True,
                )
                last_render = now

        live.update(
            _render_response_panel(
                "".join(chunks),
                model=current_model,
                streaming=False,
                elapsed=time.perf_counter() - started,
            ),
            refresh=True,
        )
    console.print()
    return current_model


def main() -> None:
    agent, runtime = build_agent()
    settings = runtime.settings

    print_welcome(agent)

    try:
        while True:
            try:
                user_input = read_user_input()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]bye[/dim]")
                break

            if not user_input:
                continue

            if "\n" in user_input or len(user_input) > 160:
                console.print(
                    Panel.fit(
                        Text(preview_user_input(user_input), style="white"),
                        title="You",
                        subtitle="preview",
                        border_style="#4b5563",
                        box=box.SQUARE,
                    )
                )

            lowered = user_input.lower()
            if lowered in {"exit", "quit", "/exit"}:
                console.print("[dim]bye[/dim]")
                break
            if lowered == "/help":
                print_help()
                continue
            handled, camera_message = handle_camera_command(user_input, runtime)
            if handled:
                if lowered == "/camera status" or camera_message is None:
                    console.print(_camera_panel(runtime))
                else:
                    console.print(
                        Panel.fit(
                            Text(camera_message, style="white"),
                            title="Camera",
                            border_style="red" if "failed" in camera_message.lower() else "#4b5563",
                            box=box.SQUARE,
                        )
                    )
                continue
            if lowered == "/clear":
                agent.reset()
                console.print(Panel.fit("Chat history cleared.", border_style="#4b5563", box=box.SQUARE))
                continue
            if lowered == "/models":
                console.print(
                    Panel(
                        "chat:\n"
                        + "\n".join(settings.model_chain)
                        + "\n\nvision:\n"
                        + "\n".join(settings.vision_model_chain),
                        title="Model Order",
                        border_style="#4b5563",
                        box=box.SQUARE,
                        padding=(0, 1),
                    )
                )
                continue
            if lowered == "/memory":
                console.print(
                    Panel(
                        (
                            f"session: {settings.session_id}\n"
                            f"data: {settings.data_dir}\n"
                            f"chat archive: {settings.data_dir / 'chats'}\n"
                            f"knowledge: {settings.data_dir / 'knowledge'}\n"
                            f"memory db: {settings.data_dir / 'memory' / 'jakata.db'}"
                        ),
                        title="Memory",
                        border_style="#4b5563",
                        box=box.SQUARE,
                        padding=(0, 1),
                    )
                )
                continue
            if lowered == "/tasks":
                tasks = runtime.task_store.list_tasks(limit=15)
                if not tasks:
                    console.print(Panel.fit("No tasks yet.", border_style="#4b5563", box=box.SQUARE))
                    continue
                for task in tasks:
                    console.print(render_task_panel(task))
                console.print()
                continue
            if lowered.startswith("/task "):
                task_id = user_input.split(maxsplit=1)[1].strip()
                task = runtime.task_store.get_task(task_id)
                if task is None:
                    console.print(Panel.fit(f"Task not found: {task_id}", border_style="red", box=box.SQUARE))
                    continue
                events = runtime.task_store.list_events(task_id, limit=20)
                body = render_task_summary(task)
                if events:
                    body += "\n\n[bold]Recent events:[/bold]\n" + "\n".join(
                        f"- {event.event_type}: {json.dumps(event.payload, ensure_ascii=False)[:180]}" for event in events[-10:]
                    )
                console.print(render_task_panel(task, title="Task Detail", body=body))
                console.print()
                continue
            if lowered.startswith("/approve "):
                token = user_input.split(maxsplit=1)[1].strip()
                result = runtime.task_engine.approve_and_resume(token, actor="cli")
                if result is None:
                    console.print(Panel.fit(f"Approval not found: {token}", border_style="red", box=box.SQUARE))
                else:
                    console.print(render_task_panel(result.task, title="Task Result", body=result.report))
                console.print()
                continue
            if lowered.startswith("/deny "):
                token = user_input.split(maxsplit=1)[1].strip()
                result = runtime.task_engine.deny(token, actor="cli")
                if result is None:
                    console.print(Panel.fit(f"Approval not found: {token}", border_style="red", box=box.SQUARE))
                else:
                    console.print(render_task_panel(result.task, title="Task Denied", body=result.report))
                console.print()
                continue
            if lowered.startswith("/cancel "):
                task_id = user_input.split(maxsplit=1)[1].strip()
                task = runtime.task_store.cancel_task(task_id)
                if task is None:
                    console.print(Panel.fit(f"Task not found: {task_id}", border_style="red", box=box.SQUARE))
                else:
                    console.print(Panel.fit(f"Task status: {task.status}", border_style="#4b5563", box=box.SQUARE))
                continue
            if lowered.startswith("/agents "):
                task_id = user_input.split(maxsplit=1)[1].strip()
                runs = runtime.task_store.list_agent_runs(task_id)
                if not runs:
                    console.print(Panel.fit("No agent runs found for that task.", border_style="#4b5563", box=box.SQUARE))
                    continue
                body = "\n".join(
                    f"- #{run.id} {run.role}: {run.status} {json.dumps(run.details, ensure_ascii=False)}" for run in runs
                )
                console.print(Panel(body, title="Agent Runs", border_style="#4b5563", box=box.SQUARE, padding=(0, 1)))
                console.print()
                continue
            if lowered.startswith("/graph "):
                query = user_input.split(maxsplit=1)[1].strip()
                found = runtime.memory.graph_search(query)
                body = json.dumps(found, ensure_ascii=False, indent=2)
                console.print(Panel(body, title="Graph", border_style="#4b5563", box=box.SQUARE, padding=(0, 1)))
                console.print()
                continue
            try:
                console.print()
                stream_assistant_reply(agent, user_input)
            except Exception as exc:  # noqa: BLE001
                console.print(
                    Panel.fit(
                        Text(str(exc), style="white"),
                        title="JAKATA error",
                        border_style="red",
                        box=box.SQUARE,
                    )
                )
    finally:
        runtime.camera_session.stop()
