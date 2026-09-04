import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from output import APP_VERSION, app_header, assistant_panel, emoji_supported, error_panel, info_panel, make_console, meta_line, remove_emoji_only, safe_text, section_rule, setup_windows_console, strip_emoji, styled_table, table_box, terminal_report

setup_windows_console()

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from api_client import KiloError, chat_completion, list_models, list_providers, stream_chat_completion
from chat import Conversation
from config import (
    CACHE_DIR,
    MODELS_CACHE_FILE,
    MODELS_CACHE_TTL,
    get_api_key,
    get_base_url,
    get_default_model,
    get_sessions_dir,
    set_default_model,
)
from store import add_message as db_add_message
from store import config_all as db_config_all
from store import config_get as db_config_get
from store import config_set as db_config_set
from store import create_session as db_create_session
from store import delete_session as db_delete_session
from store import get_session as db_get_session
from store import last_session_id as db_last_session
from store import list_sessions as db_list_sessions
from store import migrate_legacy_dir as db_migrate_legacy
from store import new_session_id as db_new_session_id
from store import set_last_session as db_set_last
from store import set_session_model as db_set_session_model
from models import Message, ModelInfo

app = typer.Typer(add_completion=False, rich_markup_mode="rich")


def _allow_emoji(explicit_no_emoji: bool = False) -> bool:
    if explicit_no_emoji:
        return False
    if os.getenv("ZUMBA_NO_EMOJI", "") == "1":
        return False
    if os.getenv("ZUMBA_FORCE_EMOJI", "") == "1":
        return True
    return emoji_supported()


console: Console = make_console(_allow_emoji())

BANNER = "[bold white]ZUMBA[/]  [dim]v1.1.0  ·  Personal AI Assistant  ·  Kilo Gateway[/]"


def _header() -> Panel:
    return app_header(_allow_emoji())


def _plain_system(system: str, allow_emoji: bool) -> str:
    if allow_emoji or not system:
        return system
    return system.rstrip() + " Respond in plain text only. Do not use emojis or special symbols."


def _box(allow_emoji: bool):
    return table_box(allow_emoji)


def _fail(message: str, hint: str = "") -> None:
    console.print(error_panel(message, hint, _allow_emoji()))
    raise typer.Exit(code=1)


def _read_cache() -> Optional[list]:
    try:
        if not MODELS_CACHE_FILE.exists():
            return None
        age = time.time() - MODELS_CACHE_FILE.stat().st_mtime
        if age > MODELS_CACHE_TTL:
            return None
        return json.loads(MODELS_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(data: list) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        MODELS_CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def _fetch_models(refresh: bool = False) -> list[ModelInfo]:
    if not refresh:
        cached = _read_cache()
        if cached:
            try:
                return [ModelInfo.from_dict(m) for m in cached if isinstance(m, dict)]
            except Exception:
                pass
    with console.status("Fetching models from Kilo gateway...", spinner="dots"):
        try:
            models = list_models()
        except KiloError as exc:
            _fail(str(exc))
    _write_cache([m.to_dict() for m in models])
    return models


def _models_table(models: list[ModelInfo], allow_emoji: bool = True) -> Table:
    table = styled_table("AVAILABLE MODELS", allow_emoji)
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("MODEL ID", style="cyan", no_wrap=False)
    table.add_column("NAME", style="white")
    table.add_column("CONTEXT", style="dim", justify="right")
    table.add_column("COST", justify="center")
    for i, m in enumerate(models, 1):
        cost = "[bold green]FREE[/]" if m.is_free else "[dim]PAID[/]"
        ctx = f"{m.context_length // 1000}K" if m.context_length else "-"
        table.add_row(str(i), m.id, m.name[:52], ctx, cost)
    return table


def _print_assistant(text: str, model: str = "", allow_emoji: bool = True, tokens: str = "") -> None:
    shown = text if allow_emoji else strip_emoji(text)
    if not shown.strip():
        console.print(info_panel("(empty response)", title="ASSISTANT", allow_emoji=allow_emoji))
        return
    console.print(assistant_panel(shown, model, allow_emoji, tokens))


def _stream_into_console(messages: list[Message], model: str, max_tokens: Optional[int], temperature: Optional[float], allow_emoji: bool = True) -> str:
    from rich.live import Live
    from rich.markdown import Markdown as RichMarkdown
    from rich.text import Text
    full = ""
    title = f"[bold white]ASSISTANT[/][dim]{'  ·  ' + model if model else ''}[/]"
    box_style = table_box(allow_emoji)
    live_panel = Panel(Text("", no_wrap=False), title=title, title_align="left", border_style="cyan", box=box_style, padding=(1, 2), expand=True)
    try:
        gen = stream_chat_completion(messages, model, max_tokens=max_tokens, temperature=temperature)
        with Live(live_panel, console=console, refresh_per_second=12, transient=False) as live:
            for chunk in gen:
                full += chunk
                shown = full if allow_emoji else remove_emoji_only(full)
                live.update(Panel(Text(shown, no_wrap=False), title=title, title_align="left", border_style="cyan", box=box_style, padding=(1, 2), expand=True))
            final = full if allow_emoji else strip_emoji(full)
            try:
                live.update(assistant_panel(final, model, allow_emoji))
            except Exception:
                pass
        return full if allow_emoji else strip_emoji(full)
    except KiloError:
        raise


@app.command("models")
def models_cmd(
    free_only: bool = typer.Option(True, "--free/--all", help="Show only free models or all models."),
    search: str = typer.Option("", "--search", "-s", help="Filter by id or name substring."),
    limit: int = typer.Option(30, "--limit", "-n", help="Max rows to display."),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON."),
    refresh: bool = typer.Option(False, "--refresh", help="Ignore cache and refetch."),
    no_emoji: bool = typer.Option(False, "--no-emoji", help="Strip emojis for legacy cmd."),
    set_default: str = typer.Option("", "--set-default", help="Persist a model id as the default for new sessions."),
) -> None:
    allow_emoji = _allow_emoji(no_emoji)
    if set_default:
        set_default_model(set_default.strip())
        console.print(_header())
        console.print(section_rule(f"DEFAULT MODEL  ·  {get_default_model()}"))
        return
    models = _fetch_models(refresh=refresh)
    if free_only:
        models = [m for m in models if m.is_free]
    if search:
        q = search.lower()
        models = [m for m in models if q in m.id.lower() or q in m.name.lower()]
    if as_json:
        console.print_json(json.dumps([m.to_dict() for m in models[:limit]]))
        return
    if not models:
        console.print(info_panel("No models matched. Try: zumba models --all", title="MODELS", allow_emoji=allow_emoji))
        return
    free_n = sum(1 for m in models if m.is_free)
    console.print(_header())
    console.print(_models_table([m for m in models[:limit]], allow_emoji))
    console.print(section_rule(f"{len(models[:limit])} SHOWN  ·  {free_n} FREE IN FILTER  ·  DEFAULT {get_default_model()}"))


@app.command("providers")
def providers_cmd(
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON."),
    refresh: bool = typer.Option(False, "--refresh", help="Reserved flag for symmetry."),
) -> None:
    del refresh
    with console.status("Fetching providers...", spinner="dots"):
        try:
            data = list_providers()
        except KiloError as exc:
            _fail(str(exc))
    if as_json:
        console.print_json(json.dumps(data))
        return
    allow_emoji = _allow_emoji()
    console.print(_header())
    items = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        console.print_json(json.dumps(data))
        return
    table = styled_table("PROVIDERS", allow_emoji)
    table.add_column("ID / NAME", style="cyan")
    table.add_column("DETAILS", style="dim")
    for p in items[:40]:
        if isinstance(p, dict):
            name = str(p.get("id", p.get("name", "?")))
            info = str(p.get("description", p.get("status", "")) or "")[:72]
            table.add_row(name, info)
        else:
            table.add_row(str(p), "")
    console.print(table)
    console.print(section_rule(f"{min(len(items), 40)} SHOWN"))


@app.command("ask")
def ask_cmd(
    prompt: str = typer.Argument(..., help="Single question to ask."),
    model: str = typer.Option("", "--model", "-m", help="Model id. Defaults to ZUMBA_MODEL or kilo-auto/free."),
    system: str = typer.Option("You are Zumba, a concise helpful personal assistant.", "--system", "-s"),
    no_stream: bool = typer.Option(False, "--no-stream", help="Disable streaming."),
    max_tokens: Optional[int] = typer.Option(None, "--max-tokens"),
    temperature: Optional[float] = typer.Option(None, "--temperature", "--temp"),
    no_emoji: bool = typer.Option(False, "--no-emoji", help="Strip emojis for legacy cmd."),
) -> None:
    allow_emoji = _allow_emoji(no_emoji)
    chosen = (model or get_default_model()).strip()
    try:
        key = get_api_key(require=True)
    except RuntimeError as exc:
        _fail(str(exc), "Free models still need a Kilo key. Sign up at https://kilo.ai — it is free.")
        return
    base = get_base_url()
    eff_system = _plain_system(system, allow_emoji)
    msgs = [Message(role="system", content=eff_system), Message(role="user", content=prompt)] if eff_system else [Message(role="user", content=prompt)]
    console.print(_header())
    console.print(section_rule("REQUEST"))
    console.print(f"{meta_line('Model', chosen)}   {meta_line('Endpoint', base)}")
    console.print(section_rule("RESPONSE"))
    try:
        if no_stream:
            with console.status("[cyan]Generating response...[/]", spinner="dots"):
                result = chat_completion(msgs, chosen, api_key=key, max_tokens=max_tokens, temperature=temperature)
            tokens = f"{result.usage.prompt_tokens} IN / {result.usage.completion_tokens} OUT" if result.usage.total_tokens else ""
            _print_assistant(result.content, result.model or chosen, allow_emoji, tokens)
        else:
            _stream_into_console(msgs, chosen, max_tokens, temperature, allow_emoji)
    except KiloError as exc:
        _fail(str(exc))
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/]")


@app.command("sessions")
def sessions_cmd(
    search: str = typer.Option("", "--search", "-s", help="Full-text search across titles and messages."),
    limit: int = typer.Option(20, "--limit", "-n"),
    delete: str = typer.Option("", "--delete", help="Delete a session by id."),
    show: str = typer.Option("", "--show", help="Show a session transcript by id."),
) -> None:
    allow_emoji = _allow_emoji()
    migrated = db_migrate_legacy(get_sessions_dir())
    console.print(_header())
    if delete:
        found = _resolve_session_id(delete)
        if not found:
            _fail(f"Session not found: {delete}")
            return
        db_delete_session(found)
        console.print(section_rule(f"DELETED  ·  {found}"))
        return
    if show:
        found = _resolve_session_id(show)
        if not found:
            _fail(f"Session not found: {show}")
            return
        data = db_get_session(found)
        if not data:
            _fail(f"Session not found: {show}")
            return
        console.print(section_rule(f"{data.get('title', '')}  ·  {data.get('id', '')}  ·  {data.get('model', '')}"))
        for m in data.get("messages", []):
            role = str(m.get("role", "")).upper()
            body = str(m.get("content", ""))
            if role == "USER":
                console.print(f"[bold cyan]{role} ›[/] {safe_text(body[:2000], allow_emoji)}")
            elif role == "ASSISTANT":
                _print_assistant(body, str(data.get("model", "")), allow_emoji)
        return
    rows = db_list_sessions(limit=limit, search=search)
    if migrated:
        console.print(f"[dim]Imported {migrated} legacy file session(s) into the database.[/]")
    if not rows:
        console.print(info_panel("No saved sessions yet. Run: zumba chat", title="SESSIONS", allow_emoji=allow_emoji))
        return
    table = styled_table("SAVED SESSIONS", allow_emoji)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("TITLE", style="white")
    table.add_column("MODEL", style="dim")
    table.add_column("MSGS", justify="right", style="dim")
    table.add_column("UPDATED", style="dim")
    import datetime
    for r in rows:
        try:
            mtime = datetime.datetime.fromtimestamp(float(r.get("updated_at", 0))).strftime("%m-%d %H:%M")
        except Exception:
            mtime = "-"
        table.add_row(str(r.get("id", ""))[:12], str(r.get("title", ""))[:42], str(r.get("model", ""))[:28], str(r.get("message_count", 0)), mtime)
    console.print(table)
    console.print(section_rule("RESUME WITH: zumba chat --resume <id>  ·  SEARCH WITH: zumba sessions --search <text>"))


def _resolve_session_id(prefix: str) -> str:
    prefix = (prefix or "").strip()
    if not prefix:
        return ""
    direct = db_get_session(prefix)
    if direct:
        return str(direct.get("id", ""))
    rows = db_list_sessions(limit=50)
    for r in rows:
        if str(r.get("id", "")).startswith(prefix):
            return str(r.get("id", ""))
    return ""


@app.command("config")
def config_cmd(
    set_model: str = typer.Option("", "--set-model", help="Persist default model for new sessions."),
    set_system: str = typer.Option("", "--set-system", help="Persist default system prompt."),
    set_streaming: str = typer.Option("", "--set-streaming", help="on/off default for chat streaming."),
    clear: bool = typer.Option(False, "--clear", help="Clear saved preferences."),
) -> None:
    allow_emoji = _allow_emoji()
    console.print(_header())
    if clear:
        for k in ("default_model", "default_system", "streaming", "last_session"):
            try:
                db_config_set(k, "")
            except Exception:
                pass
        console.print(section_rule("PREFERENCES CLEARED"))
        return
    if set_model:
        set_default_model(set_model.strip())
    if set_system:
        db_config_set("default_system", set_system.strip())
    if set_streaming:
        db_config_set("streaming", "off" if set_streaming.strip().lower() in ("off", "0", "false", "no") else "on")
    if set_model or set_system or set_streaming:
        console.print(section_rule("PREFERENCES SAVED"))
    table = styled_table("PREFERENCES", allow_emoji)
    table.add_column("KEY", style="cyan", no_wrap=True)
    table.add_column("VALUE", style="white")
    prefs = db_config_all()
    table.add_row("default_model", prefs.get("default_model", "") or get_default_model())
    table.add_row("default_system", (prefs.get("default_system", "") or "-")[:60])
    table.add_row("streaming", prefs.get("streaming", "") or "on")
    table.add_row("last_session", prefs.get("last_session", "") or "-")
    table.add_row("ZUMBA_MODEL env", __import__("os").getenv("ZUMBA_MODEL", "") or "-")
    console.print(table)
    console.print(section_rule("ENV ZUMBA_MODEL OVERRIDES SAVED default_model"))


@app.command("chat")
def chat_cmd(
    model: str = typer.Option("", "--model", "-m", help="Model id. Defaults to ZUMBA_MODEL or kilo-auto/free."),
    system: str = typer.Option("You are Zumba, a concise helpful personal assistant.", "--system", "-s"),
    resume: str = typer.Option("", "--resume", help="Resume a saved session by id, file path, or filename."),
    last: bool = typer.Option(False, "--last", help="Resume the most recent session."),
    no_stream: bool = typer.Option(False, "--no-stream", help="Disable streaming."),
    max_tokens: Optional[int] = typer.Option(None, "--max-tokens"),
    temperature: Optional[float] = typer.Option(None, "--temperature", "--temp"),
    no_emoji: bool = typer.Option(False, "--no-emoji", help="Strip emojis for legacy cmd."),
) -> None:
    allow_emoji = _allow_emoji(no_emoji)
    db_migrate_legacy(get_sessions_dir())
    saved_system = db_config_get("default_system", "")
    if not system or system == "You are Zumba, a concise helpful personal assistant.":
        system = saved_system or system
    chosen = (model or get_default_model()).strip()
    system = _plain_system(system, allow_emoji)
    try:
        key = get_api_key(require=True)
    except RuntimeError as exc:
        _fail(str(exc), "Free models still need a Kilo key. Sign up at https://kilo.ai — it is free.")
        return
    saved_streaming = db_config_get("streaming", "on")

    conv: Conversation
    session_id = ""
    if last and not resume:
        resume = db_last_session()
        if not resume:
            _fail("No previous session found.", "Start one with: zumba chat")
            return
    if resume:
        data = db_get_session(resume) or (db_get_session(_resolve_session_id(resume)) if _resolve_session_id(resume) else None)
        if data:
            session_id = str(data.get("id", ""))
            chosen = (str(data.get("model", "")) or chosen)
            system = str(data.get("system", "") or system)
            conv = Conversation(model=chosen, system="")
            conv.messages = []
            for m in data.get("messages", []):
                role = str(m.get("role", "user"))
                content = str(m.get("content", ""))
                if role == "system":
                    continue
                conv.messages.append(Message(role=role, content=content))
            if system:
                conv.messages.insert(0, Message(role="system", content=system))
            conv.model = chosen
            conv.system = system
        else:
            candidate = Path(resume)
            if not candidate.exists():
                candidate = get_sessions_dir() / resume
            if not candidate.exists():
                _fail(f"Session not found: {resume}", "Check with: zumba sessions")
                return
            try:
                conv = Conversation.load(candidate)
                chosen = conv.model or chosen
            except Exception as exc:
                _fail(f"Could not load session: {exc}")
                return
            session_id = db_new_session_id()
            db_create_session(session_id, chosen, system, title="Imported file")
            for m in conv.messages:
                if m.role == "system":
                    continue
                db_add_message(session_id, m.role, m.content)
    else:
        conv = Conversation(model=chosen, system=system)
        session_id = db_new_session_id()
        db_create_session(session_id, chosen, system)
    conv.model = chosen
    db_set_last(session_id)

    if no_stream:
        streaming = False
    elif saved_streaming == "off":
        streaming = False
    else:
        streaming = True

    you_label = "YOU"
    zumba_label = "ZUMBA"
    console.print(_header())
    console.print(section_rule("SESSION"))
    console.print(
        f"{meta_line('Model', chosen)}   {meta_line('Streaming', 'ON' if streaming else 'OFF')}   "
        f"{meta_line('Emoji', 'ON' if allow_emoji else 'OFF')}   {meta_line('Session', session_id[:12])}"
    )
    console.print("[dim]Commands: /help  ·  /models  ·  /model <id> (saved)  ·  /sessions  ·  /load <id>  ·  /new  ·  /exit[/]")
    if not allow_emoji:
        console.print("[dim]Legacy console: emoji stripped. For full rendering use VS Code terminal or Windows Terminal. See: zumba doctor[/]")
    console.print(section_rule("CHAT"))

    def show_help() -> None:
        table = styled_table("COMMANDS", allow_emoji)
        table.add_column("COMMAND", style="cyan", no_wrap=True)
        table.add_column("DESCRIPTION", style="white")
        table.add_row("/help", "Show this help")
        table.add_row("/models", "List free models")
        table.add_row("/model <id>", "Switch model (saved as default)")
        table.add_row("/system <text>", "Set system prompt")
        table.add_row("/clear", "Clear history")
        table.add_row("/sessions", "List saved sessions")
        table.add_row("/load <id>", "Load a saved session")
        table.add_row("/new", "Start a fresh session")
        table.add_row("/stream", "Toggle streaming")
        table.add_row("/emoji", "Toggle emoji stripping")
        table.add_row("/tokens", "Show token estimate")
        table.add_row("/exit, /quit", "Save and exit")
        console.print(table)

    while True:
        try:
            user_text = console.input("[bold cyan]YOU  › [/]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Saving and exiting...[/]")
            break
        if not user_text:
            continue
        if user_text.startswith("/ "):
            user_text = "/" + user_text[2:].lstrip()
        if user_text in ("/exit", "/quit"):
            break
        if user_text == "/help":
            show_help()
            continue
        if user_text == "/clear":
            conv.clear(keep_system=True)
            console.print(section_rule("HISTORY CLEARED"))
            continue
        if user_text == "/save":
            try:
                db_set_last(session_id)
                console.print(section_rule(f"SAVED  ·  SESSION {session_id[:12]}"))
            except Exception as exc:
                console.print(error_panel(f"Save failed: {exc}", allow_emoji=allow_emoji))
            continue
        if user_text == "/sessions":
            rows = db_list_sessions(limit=10)
            if not rows:
                console.print(info_panel("No saved sessions yet.", title="SESSIONS", allow_emoji=allow_emoji))
            else:
                table = styled_table("SAVED SESSIONS", allow_emoji)
                table.add_column("ID", style="cyan", no_wrap=True)
                table.add_column("TITLE", style="white")
                table.add_column("MODEL", style="dim")
                for r in rows:
                    table.add_row(str(r.get("id", ""))[:12], str(r.get("title", ""))[:40], str(r.get("model", ""))[:26])
                console.print(table)
            continue
        if user_text.startswith("/load "):
            target = user_text[6:].strip()
            found = _resolve_session_id(target)
            data = db_get_session(found) if found else None
            if not data:
                console.print(error_panel(f"Session not found: {target}", allow_emoji=allow_emoji))
                continue
            session_id = str(data.get("id", ""))
            chosen = str(data.get("model", "")) or chosen
            system = str(data.get("system", "") or system)
            conv = Conversation(model=chosen, system="")
            conv.messages = []
            for m in data.get("messages", []):
                role = str(m.get("role", "user"))
                if role == "system":
                    continue
                conv.messages.append(Message(role=role, content=str(m.get("content", ""))))
            if system:
                conv.messages.insert(0, Message(role="system", content=system))
            conv.model = chosen
            conv.system = system
            db_set_last(session_id)
            console.print(section_rule(f"LOADED  ·  {session_id[:12]}  ·  {chosen}"))
            continue
        if user_text == "/new":
            session_id = db_new_session_id()
            db_create_session(session_id, chosen, system)
            conv = Conversation(model=chosen, system=system)
            db_set_last(session_id)
            console.print(section_rule(f"NEW SESSION  ·  {session_id[:12]}"))
            continue
        if user_text == "/stream":
            streaming = not streaming
            console.print(section_rule(f"STREAMING {'ON' if streaming else 'OFF'}"))
            continue
        if user_text == "/emoji":
            allow_emoji = not allow_emoji
            system_eff = _plain_system(system, allow_emoji)
            conv.set_system(system_eff)
            console.print(section_rule(f"EMOJI {'ON' if allow_emoji else 'OFF'}"))
            continue
        if user_text == "/tokens":
            console.print(f"[dim]Tokens ~{conv.estimate_tokens()}  ·  {len(conv.messages)} messages[/]")
            continue
        if user_text == "/models":
            try:
                free = [m for m in _fetch_models() if m.is_free][:15]
                console.print(_models_table(free, allow_emoji))
            except Exception as exc:
                console.print(error_panel(str(exc), allow_emoji=allow_emoji))
            continue
        if user_text.startswith("/model "):
            new_model = user_text[7:].strip()
            if new_model:
                chosen = new_model
                conv.model = chosen
                set_default_model(chosen)
                db_set_session_model(session_id, chosen)
                console.print(section_rule(f"MODEL  ·  {chosen}  ·  SAVED AS DEFAULT"))
            continue
        if user_text.startswith("/system "):
            new_sys = user_text[8:].strip()
            conv.set_system(new_sys)
            console.print(section_rule("SYSTEM PROMPT UPDATED"))
            continue
        if user_text.startswith("/"):
            console.print(info_panel("Unknown command. Type /help", title="COMMANDS", allow_emoji=allow_emoji))
            continue

        conv.add_user(user_text)
        db_add_message(session_id, "user", user_text)
        try:
            if streaming:
                console.print(section_rule(f"{zumba_label}  ·  {chosen}"))
                full = _stream_into_console(conv.history(), chosen, max_tokens, temperature, allow_emoji)
                conv.add_assistant(full)
                db_add_message(session_id, "assistant", full)
            else:
                with console.status("[cyan]Generating response...[/]", spinner="dots"):
                    result = chat_completion(conv.history(), chosen, api_key=key, max_tokens=max_tokens, temperature=temperature)
                text = result.content if allow_emoji else strip_emoji(result.content)
                conv.add_assistant(text)
                tokens_n = int(result.usage.total_tokens or 0)
                db_add_message(session_id, "assistant", text, tokens_n)
                tokens = f"{result.usage.prompt_tokens} IN / {result.usage.completion_tokens} OUT" if result.usage.total_tokens else ""
                _print_assistant(result.content, result.model or chosen, allow_emoji, tokens)
        except KiloError as exc:
            try:
                conv.messages.pop()
            except Exception:
                pass
            console.print(error_panel(str(exc), allow_emoji=allow_emoji))
            continue
        except KeyboardInterrupt:
            console.print("\n[dim]Response interrupted.[/]")
            continue

    try:
        db_set_last(session_id)
        console.print(section_rule(f"SAVED  ·  SESSION {session_id[:12]}  ·  RESUME WITH: zumba chat --resume {session_id[:12]}"))
    except Exception as exc:
        console.print(error_panel(f"Could not save session: {exc}", allow_emoji=allow_emoji))


@app.command("doctor")
def doctor_cmd() -> None:
    info = terminal_report()
    allow_emoji = _allow_emoji()
    console.print(_header())
    table = styled_table("TERMINAL DIAGNOSTICS", allow_emoji)
    table.add_column("CHECK", style="cyan", no_wrap=True)
    table.add_column("VALUE", style="white")
    table.add_row("Emoji mode", "ON  ·  full unicode" if allow_emoji else "OFF  ·  legacy safe, stripped")
    table.add_row("Modern terminal", str(info.get("modern")))
    table.add_row("Windows Terminal", str(info.get("wt_session")))
    table.add_row("VS Code terminal", str(info.get("vscode")))
    table.add_row("TERM_PROGRAM", str(info.get("term_program") or "-"))
    table.add_row("Console codepage", str(info.get("output_cp")))
    table.add_row("stdout encoding", str(info.get("stdout_encoding")))
    console.print(table)
    console.print(info_panel(
        "If emojis show as boxes in cmd:\n"
        "1. Prefer Windows Terminal or VS Code terminal (full emoji + UTF-8).\n"
        "2. In legacy cmd: Cascadia Mono / Consolas font + chcp 65001.\n"
        "3. Zumba auto-strips emojis in legacy cmd. Override:\n"
        "   setx ZUMBA_FORCE_EMOJI 1  ·  force on\n"
        "   setx ZUMBA_NO_EMOJI 1     ·  force off",
        title="RENDERING FIX",
        allow_emoji=allow_emoji,
    ))


@app.command("version")
def version_cmd() -> None:
    console.print(_header())
    console.print(section_rule(f"VERSION  ·  {APP_VERSION}"))


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        allow_emoji = _allow_emoji()
        console.print(_header())
        table = styled_table("COMMANDS", allow_emoji)
        table.add_column("COMMAND", style="cyan", no_wrap=True)
        table.add_column("DESCRIPTION", style="white")
        table.add_row("zumba models", "List free models (no key needed)")
        table.add_row('zumba ask "..."', "One-shot question")
        table.add_row("zumba chat", "Interactive session (auto-saved, --last to resume)")
        table.add_row("zumba sessions", "List / search / show saved chats")
        table.add_row("zumba config", "Show or set default model + preferences")
        table.add_row("zumba doctor", "Terminal + rendering diagnostics")
        table.add_row("zumba version", "Show version")
        console.print(table)
        console.print(section_rule("SET KILO_API_KEY TO CHAT  ·  DEFAULT kilo-auto/free"))


if __name__ == "__main__":
    app()
