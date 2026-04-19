from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from jakata_agent.agent import JakataAgent
from jakata_agent.config import load_settings
from jakata_agent.llm import NvidiaChatClient
from jakata_agent.memory.manager import MemoryManager
from jakata_agent.router import IntentRouter
from jakata_agent.tools.datetime_tool import DateTimeTool
from jakata_agent.tools.registry import ToolRegistry
from jakata_agent.tools.search_web import TavilySearchTool
from jakata_agent.tools.weather import OpenWeatherTool


console = Console()


def build_agent() -> JakataAgent:
    settings = load_settings()
    client = NvidiaChatClient(settings)
    tools = ToolRegistry()
    tools.register(DateTimeTool())
    tools.register(TavilySearchTool(settings.tavily_api_key))
    tools.register(OpenWeatherTool(settings.openweather_api_key))
    return JakataAgent(
        settings=settings,
        client=client,
        tools=tools,
        memory=MemoryManager(settings.data_dir, settings.session_id),
        router=IntentRouter(client),
    )


def print_welcome(agent: JakataAgent) -> None:
    console.print(
        Panel.fit(
            "[bold cyan]JAKATA[/bold cyan]\n"
            "Personal AI assistant starter with streaming chat, retries, and model fallback.",
            border_style="cyan",
        )
    )
    console.print("[bold]Commands:[/bold] [cyan]/help[/cyan] [cyan]/clear[/cyan] [cyan]/models[/cyan] [cyan]/exit[/cyan]")
    console.print("[bold]Connected tools:[/bold]")
    console.print(agent.tools.describe())
    console.print(f"[bold]Session:[/bold] {agent.settings.session_id}")
    console.print(f"[bold]Data dir:[/bold] {agent.settings.data_dir}")
    console.print()


def print_help() -> None:
    console.print(
        Panel.fit(
            "/help  show commands\n"
            "/clear reset chat history\n"
            "/models show configured model fallback order\n"
            "/memory show memory storage location\n"
            "/exit  quit",
            title="Help",
            border_style="green",
        )
    )


def main() -> None:
    agent = build_agent()
    settings = load_settings()

    print_welcome(agent)

    while True:
        try:
            user_input = console.input("[bold yellow]you> [/bold yellow]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit", "/exit"}:
            console.print("[dim]bye[/dim]")
            break
        if user_input.lower() == "/help":
            print_help()
            continue
        if user_input.lower() == "/clear":
            agent.reset()
            console.print("[green]Chat history cleared.[/green]\n")
            continue
        if user_input.lower() == "/models":
            console.print(Panel.fit("\n".join(settings.model_chain), title="Model Order", border_style="blue"))
            continue
        if user_input.lower() == "/memory":
            console.print(
                Panel.fit(
                    f"session: {settings.session_id}\n"
                    f"data: {settings.data_dir}\n"
                    f"chat archive: {settings.data_dir / 'chats'}\n"
                    f"knowledge: {settings.data_dir / 'knowledge'}\n"
                    f"memory db: {settings.data_dir / 'memory' / 'jakata.db'}",
                    title="Memory",
                    border_style="magenta",
                )
            )
            continue

        try:
            console.print("[bold cyan]jakata>[/bold cyan] ", end="")
            current_model = ""
            output = Text()
            for model, chunk in agent.stream_reply(user_input):
                current_model = model
                output.append(chunk)
                console.print(chunk, end="", soft_wrap=True)
            console.print()
            if current_model:
                console.print(f"[dim]model: {current_model}[/dim]\n")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[bold red]jakata[error]>[/bold red] {exc}\n")
