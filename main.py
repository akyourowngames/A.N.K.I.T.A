import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from output import APP_VERSION, app_header, assistant_panel, emoji_supported, error_panel, info_panel, make_console, meta_line, normalize_text, remove_emoji_only, safe_text, section_rule, setup_windows_console, strip_emoji, styled_table, table_box, terminal_report

setup_windows_console()

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from api_client import KiloError, chat_completion, list_models, list_providers, stream_chat_completion
from mcpclient.config import add_server as mcp_add_server
from mcpclient.config import remove_server as mcp_remove_server
from mcpclient.config import get_server as mcp_get_server
from mcpclient.config import list_servers as mcp_list_servers
from mcpclient.manager import manager as mcp_manager, run_tool as mcp_run_tool
from mcpclient.manager import reload_sync as mcp_reload_sync, reload_if_stale_sync as mcp_reload_if_stale
import mcpclient.tools as mcp_tools_mod
from mcpclient import defaults as mcp_defaults
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

_WINDOW_CACHE: dict[str, dict] = {}
_WHY_LAST: dict[str, dict] = {}
_WHY_ON: dict[str, bool] = {}


def _why_store(session_id: str, query: str, text: str, hits: list) -> None:
    _WHY_LAST[session_id] = {"query": query, "text": text or "", "hits": hits or []}


def _why_render(session_id: str) -> str:
    data = _WHY_LAST.get(session_id) or {}
    if not data.get("text") and not data.get("hits"):
        return "No memory was injected on the last turn (nothing recalled)."
    lines = [f"query: {data.get('query', '')}"]
    hits = data.get("hits") or []
    if not hits:
        lines.append("(recall block came from core profile blocks, not scored hits)")
    for i, h in enumerate(hits, 1):
        meta = h.get("meta") or {}
        ref = f" id={meta.get('id')}" if meta.get("id") is not None else ""
        lines.append(f"{i}. [{h.get('kind')}] score={h.get('score')}{ref} :: {h.get('snippet', '')[:160]}")
    return "\n".join(lines)


def _window_cache_for(msgs: list[Message]) -> dict:
    """Per-session rolling-summary cache, keyed by the session anchor (first
    user message). Lets build_window reuse summaries across turns."""
    import hashlib

    anchor = next((m.content for m in msgs if m.role == "user"), "")
    key = hashlib.sha256(anchor.encode("utf-8", errors="replace")).hexdigest()[:16]
    return _WINDOW_CACHE.setdefault(key, {})


def _fit_window(msgs: list[Message]) -> list[Message]:
    try:
        from context_budget import build_window, get_context_limit

        return build_window(msgs, model_limit=get_context_limit(), cache=_window_cache_for(msgs))
    except Exception:
        return msgs

_MEM = None
_MCP_DISABLE = os.getenv("ZUMBA_NO_MCP", "") == "1"


def _mcp():
    """Lazily-initialized MCP manager; None if disabled. Never crashes chat.
    Set ZUMBA_NO_MCP=1 to disable entirely."""
    if _MCP_DISABLE:
        return None
    try:
        return mcp_manager()
    except Exception:
        return None


def _mcp_preamble(msgs: list[Message], tools: list) -> list[Message]:
    """Inject a tool description preamble as a system message before the last
    user turn (like memory recall) for models without native function calling.
    The behavioral note is generated from defaults and can be overridden via
    the ZUMBA_MCP_SYSTEM_NOTE env var or the `mcp_system_note` config pref."""
    preamble = mcp_tools_mod.system_preamble(tools)
    if not preamble or not msgs:
        return msgs
    note = db_config_get("mcp_system_note", "") or mcp_defaults.SYSTEM_NOTE
    sys_msg = Message(role="system", content=(
        "Connected MCP tools (call them via the function/tool-call mechanism; "
        "names are prefixed by their server):\n" + preamble +
        "\n" + note.replace("{meta}", mcp_defaults.META_SERVER) +
        "\nShell: zumba__shell_run executes UNRESTRICTED Windows PowerShell in one persistent "
        "session (cwd/env persist) — chain state instead of re-stating it. "
        "ALWAYS use PowerShell syntax: Get-ChildItem (never `ls -la`), Get-Content (never `cat`), "
        "Get-Location (never `pwd`), Select-String (never `grep`). Bash flags like -la/-rf do not exist. "
        "Soul files live at ~/.zumba/soul.md and ~/.zumba/user.md — read them with "
        "Get-Content when the user asks what was drafted, never guess; never run `ls -la`."
    ))
    return msgs[:-1] + [sys_msg, msgs[-1]]


def _mcp_agent_turn(msgs: list[Message], model: str, key: str, max_tokens, temperature, allow_emoji: bool) -> tuple:
    """Run the MCP agent loop for one chat turn. Returns (reply, tools used, transcript)."""
    from mcpclient.agent import run_agent_loop
    mgr = mcp_manager()
    tools = mgr.all_tools()
    convo = _mcp_preamble(list(msgs), tools) if tools else list(msgs)
    convo = _fit_window(convo)
    used = {"n": 0}
    transcript: list = []

    def on_tool(name, args, result):
        used["n"] += 1
        shown = result[:400] + ("..." if len(result) > 400 else "")
        args_s = json.dumps(args, ensure_ascii=False)[:200]
        console.print(f"[dim]  tool › [cyan]{safe_text(name, allow_emoji)}[/]({safe_text(args_s, allow_emoji)})[/]")
        console.print(Panel(safe_text(shown, allow_emoji), title=f"TOOL  ·  {safe_text(name, allow_emoji)}",
                            title_align="left", border_style="magenta", box=table_box(allow_emoji), padding=(0, 2)))

    result = run_agent_loop(
        convo, model,
        call_model=lambda ms, m, tools, **kw: chat_completion(
            ms, m, api_key=key, tools=tools, max_tokens=max_tokens, temperature=temperature),
        execute_tool=lambda name, args: mcp_run_tool(name, args),
        tools=tools,
        on_tool=on_tool,
        transcript_out=transcript,
        max_iterations=mcp_defaults.MAX_ITERATIONS,
    )
    reply = result.content or ""
    if not reply.strip() and used["n"]:
        reply = result.content = "Did %d tool step(s) but the model gave no summary. Say 'continue' and I will carry on from the last tool result." % used["n"]
    usage = getattr(result, "usage", None)
    tokens = f"{usage.prompt_tokens} IN / {usage.completion_tokens} OUT" if usage and usage.total_tokens else ""
    _print_assistant(reply, getattr(result, "model", "") or model, allow_emoji, tokens)
    return normalize_text(reply, allow_emoji), used["n"], transcript


def _remember_tool_transcript(conv, transcript: list, keep: int = 10) -> None:
    """Persist tool exchanges into conversation history so follow-up turns see
    prior tool results. Caps retained tool context to the latest `keep` entries."""
    try:
        for m in transcript or []:
            conv.messages.append(m)
        related = [m for m in conv.messages if m.role == "tool" or (m.role == "assistant" and m.tool_calls)]
        while len(related) > keep:
            conv.messages.remove(related.pop(0))
    except Exception:
        pass


def _save_tool_transcript(session_id: str, transcript: list) -> None:
    """Persist tool exchanges to the session DB so `continue` and `--resume`
    keep tool context. Orphan-safe: resume folds these into a system digest
    (see _fold_saved_tool_context) instead of sending bare tool messages."""
    try:
        for m in transcript or []:
            content = (m.content or "").strip()
            if m.role == "assistant" and not content:
                content = "(tool call — see following tool result)"
            db_add_message(session_id, m.role, content)
    except Exception:
        pass


def _fold_saved_tool_context(messages: list[Message]) -> list[Message]:
    """Fold saved tool exchanges into one system digest.

    Bare `role=tool` messages (and their content-less assistant parents,
    whose tool_calls don't survive the DB) would fail API validation if
    replayed, so replace them with a system note carrying the results."""
    try:
        tools = [m for m in messages if m.role == "tool"]
        if not tools:
            return messages
        lines = []
        for m in tools[-8:]:
            name = getattr(m, "name", "") or "tool"
            lines.append(f"{name}: {(m.content or '').strip()[:300]}")
        digest = Message(role="system", content=(
            "Prior tool context from saved session (these tools already ran — "
            "use these results instead of re-running blindly):\n" + "\n".join(lines)))
        kept = [m for m in messages
                if m.role != "tool" and not (m.role == "assistant" and not (m.content or "").strip())]
        idx = 0
        while idx < len(kept) and kept[idx].role == "system":
            idx += 1
        kept.insert(idx, digest)
        return kept
    except Exception:
        return messages


def _memory():
    """Lazily-initialized memory service; None if disabled or unavailable.

    Memory must never crash chat: every failure mode degrades to no memory.
    Set ZUMBA_NO_MEMORY=1 to disable entirely.
    """
    global _MEM
    if os.getenv("ZUMBA_NO_MEMORY", "") == "1":
        return None
    if _MEM is None:
        try:
            from memory import get_memory

            _MEM = get_memory()
        except Exception:
            _MEM = False
    return _MEM or None


def _mem_capture(mem, session_id: str, user_text: str, reply: str, kind: str = "chat") -> None:
    """Queue the exchange for background ingestion (serialized worker thread),
    then opportunistically consolidate (decay, note links, contradictions,
    communities, core blocks). Never blocks or crashes the chat loop."""
    try:
        mem.capture_async(user_text, reply, session_id=session_id, kind=kind)
    except Exception:
        pass


def _soul_onboarding(allow_emoji: bool) -> None:
    try:
        import soul as _soul
        if not _soul.needs_bootstrap():
            return
        console.print(info_panel(
            "First run — let's give Zumba a soul (30s, skippable).\n"
            f"1. {_soul.BOOTSTRAP_QUESTIONS[0]}\n"
            f"2. {_soul.BOOTSTRAP_QUESTIONS[1]}\n"
            f"3. {_soul.BOOTSTRAP_QUESTIONS[2]}\n"
            "Answer with: /soul init <how I should sound> | <keep in mind> | <off-limits>\n"
            "Or: /soul wingit (I'll draft it from our first exchanges)",
            title="SOUL", allow_emoji=allow_emoji))
    except Exception:
        pass


def _soul_chat_cmd(arg: str, allow_emoji: bool) -> bool:
    import soul as _soul
    cmd = (arg or "").strip()
    if cmd in ("", "show"):
        text = _soul.load() or "(no soul.md yet — /soul wingit to draft one)"
        console.print(Panel(safe_text(text[:6000], allow_emoji), title="SOUL",
                            title_align="left", border_style="cyan", box=_box(allow_emoji), padding=(0, 2)))
        return True
    if cmd == "wingit":
        r = _soul.bootstrap_flow({"sound": "just wing it"})
        console.print(section_rule(f"SOUL DRAFTED  ·  {r.get('soul', '')}"))
        return True
    if cmd.startswith("init"):
        rest = cmd[4:].strip()
        parts = [p.strip() for p in rest.split("|")]
        answers = {"sound": parts[0] if len(parts) > 0 else "", "keep": parts[1] if len(parts) > 1 else "",
                   "off_limits": parts[2] if len(parts) > 2 else ""}
        if not any(answers.values()):
            console.print(info_panel("Usage: /soul init <sound> | <keep in mind> | <off-limits>\nOr: /soul wingit",
                                     title="SOUL", allow_emoji=allow_emoji))
            return True
        r = _soul.bootstrap_flow(answers)
        console.print(section_rule(f"SOUL WRITTEN  ·  {r.get('soul', '')}"))
        return True
    if cmd == "diff":
        console.print(Panel(safe_text(_soul.diff_proposed(), allow_emoji), title="SOUL DIFF",
                            title_align="left", border_style="cyan", box=_box(allow_emoji), padding=(0, 2)))
        return True
    if cmd == "accept":
        ok = _soul.apply_proposal()
        console.print(section_rule("SOUL UPDATED" if ok else "NO PROPOSAL"))
        return True
    if cmd == "reject":
        _soul.reject_proposal()
        console.print(section_rule("SOUL PROPOSAL REJECTED"))
        return True
    if cmd.startswith("edit"):
        import subprocess
        editor = os.getenv("EDITOR", "notepad" if os.name == "nt" else "vi")
        try:
            subprocess.run([editor, str(_soul.soul_path())])
        except Exception as exc:
            console.print(error_panel(f"soul edit: {exc}", allow_emoji=allow_emoji))
        return True
    return False


def _soul_show_intent(text: str) -> bool:
    low = f" {(text or '').lower()} "
    if "/" in (text or "")[:1]:
        return False
    if "soul" not in low and "drafted" not in low:
        return False
    return any(k in low for k in ("show", "list", "what", "display", "read", "draft", "soul"))


def _session_reflect(mem, session_id: str) -> None:
    try:
        if mem is None:
            return
        mem.flush(timeout=60.0)
        try:
            from memory import db as _mdb
            _mdb.ensure_tier2(mem._con if getattr(mem, "_con", None) is not None else _mdb.connect())
        except Exception:
            pass
        exchanges: list = []
        try:
            con = mem._open()
            try:
                rows = con.execute(
                    "SELECT id, user_text, assistant_text FROM episodes WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
                exchanges = [{"user": r["user_text"], "assistant": r["assistant_text"], "episode_id": r["id"]} for r in rows]
            finally:
                if getattr(mem, "_own", True):
                    try:
                        con.close()
                    except Exception:
                        pass
        except Exception:
            exchanges = []
        if not exchanges:
            return
        def _bg():
            try:
                mem.reflect_on_session(exchanges, session_id=session_id, use_llm=True)
            except Exception:
                pass
        threading.Thread(target=_bg, daemon=True).start()
    except Exception:
        pass


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
    shown = normalize_text(text, allow_emoji)
    if not shown.strip():
        console.print(info_panel("(empty response)", title="ASSISTANT", allow_emoji=allow_emoji))
        return
    console.print(assistant_panel(shown, model, allow_emoji, tokens))


def _stream_into_console(messages: list[Message], model: str, max_tokens: Optional[int], temperature: Optional[float], allow_emoji: bool = True) -> str:
    from output import is_modern_terminal
    full = ""
    title = f"[bold white]ASSISTANT[/][dim]{'  ·  ' + model if model else ''}[/]"
    box_style = table_box(allow_emoji)
    try:
        gen = stream_chat_completion(messages, model, max_tokens=max_tokens, temperature=temperature)
        if allow_emoji and is_modern_terminal():
            from rich.live import Live
            from rich.text import Text
            live_panel = Panel(Text("", no_wrap=False), title=title, title_align="left", border_style="cyan", box=box_style, padding=(1, 2), expand=True)
            with Live(live_panel, console=console, refresh_per_second=12, transient=False) as live:
                for chunk in gen:
                    full += chunk
                    live.update(Panel(Text(full, no_wrap=False), title=title, title_align="left", border_style="cyan", box=box_style, padding=(1, 2), expand=True))
                try:
                    live.update(assistant_panel(full, model, allow_emoji))
                except Exception:
                    pass
            return full
        for chunk in gen:
            full += chunk
            try:
                sys.stdout.write(normalize_text(chunk, allow_emoji))
                sys.stdout.flush()
            except Exception:
                pass
        try:
            sys.stdout.write("\n")
            sys.stdout.flush()
        except Exception:
            pass
        final = normalize_text(full, allow_emoji)
        try:
            console.print(assistant_panel(final, model, allow_emoji))
        except Exception:
            pass
        return final
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
    mem = _memory()
    console.print(_header())
    console.print(section_rule("REQUEST"))
    console.print(f"{meta_line('Model', chosen)}   {meta_line('Endpoint', base)}")
    console.print(section_rule("RESPONSE"))
    full_text = ""
    try:
        if no_stream:
            with console.status("[cyan]Generating response...[/]", spinner="dots"):
                result = chat_completion(msgs, chosen, api_key=key, max_tokens=max_tokens, temperature=temperature)
            tokens = f"{result.usage.prompt_tokens} IN / {result.usage.completion_tokens} OUT" if result.usage.total_tokens else ""
            full_text = result.content
            _print_assistant(result.content, result.model or chosen, allow_emoji, tokens)
        else:
            full_text = _stream_into_console(msgs, chosen, max_tokens, temperature, allow_emoji)
        if mem is not None and full_text:
            _mem_capture(mem, "", prompt, full_text)
            mem.flush(timeout=60.0)
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
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("TITLE", style="white")
    table.add_column("MODEL", style="dim")
    table.add_column("MSGS", justify="right", style="dim")
    table.add_column("UPDATED", style="dim")
    import datetime
    for i, r in enumerate(rows, 1):
        try:
            mtime = datetime.datetime.fromtimestamp(float(r.get("updated_at", 0))).strftime("%m-%d %H:%M")
        except Exception:
            mtime = "-"
        table.add_row(str(i), str(r.get("title", ""))[:42], str(r.get("model", ""))[:28], str(r.get("message_count", 0)), mtime)
    console.print(table)
    console.print(section_rule("RESUME WITH: zumba chat --resume <#>  ·  SEARCH WITH: zumba sessions --search <text>"))


def _recent_sessions(limit: int = 50) -> list[dict]:
    try:
        return db_list_sessions(limit=limit)
    except Exception:
        return []


def _resolve_session_id(prefix: str) -> str:
    prefix = (prefix or "").strip()
    if not prefix:
        return ""
    if prefix.isdigit():
        rows = _recent_sessions()
        idx = int(prefix) - 1
        if 0 <= idx < len(rows):
            return str(rows[idx].get("id", ""))
        return ""
    direct = db_get_session(prefix)
    if direct:
        return str(direct.get("id", ""))
    rows = _recent_sessions()
    for r in rows:
        if str(r.get("id", "")).startswith(prefix):
            return str(r.get("id", ""))
    lowered = prefix.lower()
    for r in rows:
        if lowered in str(r.get("title", "")).lower():
            return str(r.get("id", ""))
    return ""


def _render_history(conv: Conversation, chosen: str, allow_emoji: bool, header: str = "PREVIOUS MESSAGES") -> None:
    past = [m for m in conv.messages if m.role in ("user", "assistant")]
    if not past:
        return
    console.print(section_rule(f"{header}  ·  {len(past)}"))
    for m in past[-30:]:
        body = normalize_text(m.content, allow_emoji)
        if m.role == "user":
            console.print(f"[bold cyan]YOU ›[/] {body[:1500]}")
        else:
            _print_assistant(body, chosen, allow_emoji)
    console.print(section_rule("CONTINUING"))


def _pick_session_interactive(allow_emoji: bool) -> str:
    rows = _recent_sessions(limit=15)
    if not rows:
        console.print(info_panel("No saved sessions yet.", title="SESSIONS", allow_emoji=allow_emoji))
        return ""
    table = styled_table("SAVED SESSIONS", allow_emoji)
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("TITLE", style="white")
    table.add_column("MODEL", style="dim")
    table.add_column("MSGS", justify="right", style="dim")
    for i, r in enumerate(rows, 1):
        table.add_row(str(i), str(r.get("title", ""))[:44], str(r.get("model", ""))[:28], str(r.get("message_count", 0)))
    console.print(table)
    try:
        choice = console.input("[bold cyan]Load # (number, Enter to stay) › [/]").strip()
    except (KeyboardInterrupt, EOFError):
        console.print()
        return ""
    if not choice:
        return ""
    found = _resolve_session_id(choice)
    if not found:
        console.print(error_panel(f"No session #{choice}.", allow_emoji=allow_emoji))
        return ""
    return found


@app.command("config")
def config_cmd(
    set_model: str = typer.Option("", "--set-model", help="Persist default model for new sessions."),
    set_system: str = typer.Option("", "--set-system", help="Persist default system prompt."),
    set_style: str = typer.Option("", "--set-style", help="Persist persona style prefs (tone)."),
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
    if set_style:
        db_config_set("style", set_style.strip())
    if set_streaming:
        db_config_set("streaming", "off" if set_streaming.strip().lower() in ("off", "0", "false", "no") else "on")
    if set_model or set_system or set_style or set_streaming:
        console.print(section_rule("PREFERENCES SAVED"))
    table = styled_table("PREFERENCES", allow_emoji)
    table.add_column("KEY", style="cyan", no_wrap=True)
    table.add_column("VALUE", style="white")
    prefs = db_config_all()
    table.add_row("default_model", prefs.get("default_model", "") or get_default_model())
    table.add_row("default_system", (prefs.get("default_system", "") or "-")[:60])
    table.add_row("style", (prefs.get("style", "") or "-")[:60])
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
    from persona import resolve_chat_system

    system = resolve_chat_system(system, saved_system)
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
    resumed_history = False
    if resume:
        if resume.strip().isdigit() or db_get_session(resume) is None:
            resolved = _resolve_session_id(resume)
            if resolved:
                resume = resolved
        data = db_get_session(resume)
        if data:
            resumed_history = True
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
            conv.messages = _fold_saved_tool_context(conv.messages)
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
    mem = _memory()
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
    mcp_header = _mcp()
    mcp_note = f"   {meta_line('MCP', f'{mcp_header.online_count()} online')}" if mcp_header is not None and mcp_header.servers else ""
    console.print(
        f"{meta_line('Model', chosen)}   {meta_line('Streaming', 'ON' if streaming else 'OFF')}   "
        f"{meta_line('Emoji', 'ON' if allow_emoji else 'OFF')}   {meta_line('Session', session_id[:12])}{mcp_note}"
    )
    console.print("[dim]Commands: /help  ·  /models  ·  /model <id> (saved)  ·  /sessions  ·  /load <#>  ·  /new  ·  /exit[/]")
    if not allow_emoji:
        console.print("[dim]Legacy console: emoji stripped. For full rendering use VS Code terminal or Windows Terminal. See: zumba doctor[/]")
    if resumed_history:
        _render_history(conv, chosen, allow_emoji)
    else:
        console.print(section_rule("CHAT"))
    _soul_onboarding(allow_emoji)

    def show_help() -> None:
        table = styled_table("COMMANDS", allow_emoji)
        table.add_column("COMMAND", style="cyan", no_wrap=True)
        table.add_column("DESCRIPTION", style="white")
        table.add_row("/help", "Show this help")
        table.add_row("/models", "List free models")
        table.add_row("/model <id>", "Switch model (saved as default)")
        table.add_row("/system <text>", "Set system prompt")
        table.add_row("/clear", "Clear history")
        table.add_row("/sessions", "Pick a saved session by number")
        table.add_row("/load <#>", "Load a saved session by number")
        table.add_row("/new", "Start a fresh session")
        table.add_row("/stream", "Toggle streaming")
        table.add_row("/emoji", "Toggle emoji stripping")
        table.add_row("/remember <text>", "Store a fact in long-term memory")
        table.add_row("/memory <query>", "Search long-term memory")
        table.add_row("/why", "Explain the last turn's memory recall")
        table.add_row("/forget <name>", "Invalidate facts about an entity")
        table.add_row("/soul show|diff|accept|reject|edit|init|wingit", "Identity file (self-authored)")
        table.add_row("/me", "Show your user profile (user.md)")
        table.add_row("/brief", "Daily briefing from memory")
        table.add_row("/mcp", "Show connected MCP servers + status")
        table.add_row("/tools", "List all tools from connected MCP servers")
        table.add_row("/shell <cmd>", "Run a shell command directly (god-mode, persistent)")
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
            found = _pick_session_interactive(allow_emoji)
            if not found:
                continue
            user_text = f"/load {found}"
        if user_text == "/load":
            found = _pick_session_interactive(allow_emoji)
            if not found:
                continue
            user_text = f"/load {found}"
        if user_text.startswith("/load "):
            target = user_text[6:].strip()
            found = _resolve_session_id(target)
            data = db_get_session(found) if found else None
            if not data:
                console.print(error_panel(f"Session not found: {target or '?'}", allow_emoji=allow_emoji))
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
            conv.messages = _fold_saved_tool_context(conv.messages)
            if system:
                conv.messages.insert(0, Message(role="system", content=system))
            conv.model = chosen
            conv.system = system
            db_set_last(session_id)
            console.print(section_rule(f"LOADED  ·  {str(data.get('title', ''))[:40]}  ·  {chosen}"))
            _render_history(conv, chosen, allow_emoji)
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
        if user_text == "/mcp":
            _mcp_status_table(allow_emoji)
            continue
        if user_text == "/mcp reload":
            summary = mcp_reload_sync()
            console.print(section_rule(f"MCP RELOADED LIVE  ·  {json.dumps(summary)}"))
            _mcp_status_table(allow_emoji)
            continue
        if user_text.startswith("/mcp add ") or user_text.startswith("/mcp remove "):
            _mcp_chat_manage(user_text[6:], allow_emoji)
            _mcp_status_table(allow_emoji)
            continue
        if user_text == "/tools" or user_text.startswith("/tools "):
            _mcp_tools_table(allow_emoji)
            continue
        if user_text == "/shell" or user_text.startswith("/shell "):
            _shell_chat_run(user_text[6:].strip(), allow_emoji)
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
        if user_text.startswith("/remember ") and len(user_text) > 10:
            fact = user_text[10:].strip()
            if mem is None:
                mem = _memory()
            if mem is not None and fact:
                threading.Thread(target=_mem_capture, args=(mem, session_id, fact, ""), daemon=True).start()
                console.print(section_rule("WILL REMEMBER"))
            continue
        if user_text == "/memory" or user_text.startswith("/memory "):
            q = user_text[8:].strip() if len(user_text) > 8 else ""
            if q and mem is not None:
                try:
                    hits = mem.recall(q, top_k=8, max_bytes=4500)
                    console.print(Panel(hits or "(nothing recalled)", title="MEMORY", border_style="cyan", box=_box(allow_emoji)))
                except Exception as exc:
                    console.print(error_panel(f"memory: {exc}", allow_emoji=allow_emoji))
            continue
        if user_text == "/why" or user_text.startswith("/why "):
            arg = user_text[4:].strip().lower()
            if arg == "off":
                _WHY_ON[session_id] = False
                console.print(section_rule("WHY CAPTURE OFF"))
                continue
            if arg == "on":
                _WHY_ON[session_id] = True
                console.print(section_rule("WHY CAPTURE ON"))
                continue
            console.print(Panel(safe_text(_why_render(session_id), allow_emoji), title="WHY  ·  last recall",
                                title_align="left", border_style="cyan", box=_box(allow_emoji), padding=(0, 2)))
            continue
        if user_text.startswith("/forget ") and len(user_text) > 8:
            target = user_text[8:].strip()
            if mem is not None and target:
                try:
                    r = mem.forget(target)
                    console.print(section_rule("FORGOT" if r.get("forgot") else "NOT FOUND"))
                except Exception as exc:
                    console.print(error_panel(f"memory: {exc}", allow_emoji=allow_emoji))
            continue
        if user_text == "/soul" or user_text.startswith("/soul "):
            try:
                if not _soul_chat_cmd(user_text[5:].strip(), allow_emoji):
                    console.print(info_panel("Usage: /soul show|diff|accept|reject|edit|init|wingit", title="SOUL", allow_emoji=allow_emoji))
            except Exception as exc:
                console.print(error_panel(f"soul: {exc}", allow_emoji=allow_emoji))
            continue
        if user_text == "/me":
            try:
                import userprofile as _up
                prof = _up.profile_block() or "(no user.md yet — chat a little, then consolidation writes it)"
                console.print(Panel(safe_text(prof[:6000], allow_emoji), title="ME  ·  user.md",
                                    title_align="left", border_style="cyan", box=_box(allow_emoji), padding=(0, 2)))
            except Exception as exc:
                console.print(error_panel(f"me: {exc}", allow_emoji=allow_emoji))
            continue
        if user_text == "/brief":
            try:
                mem2 = mem if mem is not None else _memory()
                if mem2 is None:
                    console.print(info_panel("(memory disabled)", title="BRIEF", allow_emoji=allow_emoji))
                else:
                    from memory import briefing as _br
                    from memory import db as _mdb
                    con = mem2._open()
                    try:
                        text = _br.compose_daily(con, use_llm=True)
                    finally:
                        if getattr(mem2, "_own", True):
                            con.close()
                    console.print(Panel(safe_text(text[:6000], allow_emoji), title="BRIEF  ·  daily",
                                        title_align="left", border_style="cyan", box=_box(allow_emoji), padding=(0, 2)))
            except Exception as exc:
                console.print(error_panel(f"brief: {exc}", allow_emoji=allow_emoji))
            continue
        if user_text.startswith("/"):
            import difflib as _dl
            _known = ["/help", "/models", "/model", "/system", "/clear", "/sessions", "/load", "/new",
                      "/stream", "/emoji", "/tokens", "/mcp", "/tools", "/shell", "/remember", "/memory",
                      "/why", "/forget", "/soul", "/me", "/brief", "/save", "/exit", "/quit"]
            _word = user_text.split()[0].lower()
            _hit = _dl.get_close_matches(_word, _known, n=1, cutoff=0.6)
            _hint = f" Did you mean {_hit[0]}?" if _hit else ""
            console.print(info_panel(f"Unknown command.{_hint} Type /help", title="COMMANDS", allow_emoji=allow_emoji))
            continue
        try:
            if _soul_show_intent(user_text):
                _soul_chat_cmd("show", allow_emoji)
                continue
        except Exception:
            pass

        recall_text = ""
        recall_hits: list = []
        mem = _memory()
        if mem is not None:
            try:
                if _WHY_ON.get(session_id, True):
                    recall_text, recall_hits = mem.recall_with_hits(user_text, top_k=5, max_bytes=3500)
                else:
                    recall_text = mem.recall(user_text, top_k=5, max_bytes=3500)
            except Exception:
                recall_text, recall_hits = "", []
        _why_store(session_id, user_text, recall_text, recall_hits)

        conv.add_user(user_text)
        db_add_message(session_id, "user", user_text)
        # Inject recalled memory as a system message just before the user turn
        # (kept out of conv so it never pollutes saved history).
        msgs = conv.history()
        if recall_text:
            msgs = msgs[:-1] + [Message(role="system", content=(
                "Relevant long-term memory about the user:\n" + recall_text +
                "\n(These facts were distilled from past sessions. They may be outdated — the user's most recent statements in this conversation always override them.)"
            )), msgs[-1]]
            console.print(f"[dim]memory: {recall_text.count(chr(10)) + 1} recall line(s) injected[/]")
        try:
            reply_text = ""
            reply_kind = "chat"
            mcp_mgr = _mcp()
            if mcp_mgr is not None:
                reloaded = mcp_reload_if_stale(mcp_mgr)  # pick up mcp.json edits live
                if reloaded is not None:
                    console.print("[dim]mcp: config changed on disk — reloaded live[/]")
            mcp_active = mcp_mgr is not None  # built-in meta-tools always available
            if mcp_active:
                console.print(section_rule(f"{zumba_label}  ·  {chosen}  ·  MCP ({mcp_mgr.online_count()} server(s) online)"))
                full, tools_used, tool_transcript = _mcp_agent_turn(msgs, chosen, key, max_tokens, temperature, allow_emoji)
                _remember_tool_transcript(conv, tool_transcript)
                _save_tool_transcript(session_id, tool_transcript)
                conv.add_assistant(full)
                db_add_message(session_id, "assistant", full)
                reply_text = full
                reply_kind = "tool" if tools_used else "chat"
            elif streaming:
                console.print(section_rule(f"{zumba_label}  ·  {chosen}"))
                full = _stream_into_console(_fit_window(msgs), chosen, max_tokens, temperature, allow_emoji)
                conv.add_assistant(full)
                db_add_message(session_id, "assistant", full)
                reply_text = full
            else:
                with console.status("[cyan]Generating response...[/]", spinner="dots"):
                    result = chat_completion(_fit_window(msgs), chosen, api_key=key, max_tokens=max_tokens, temperature=temperature)
                text = normalize_text(result.content, allow_emoji)
                conv.add_assistant(text)
                tokens_n = int(result.usage.total_tokens or 0)
                db_add_message(session_id, "assistant", text, tokens_n)
                tokens = f"{result.usage.prompt_tokens} IN / {result.usage.completion_tokens} OUT" if result.usage.total_tokens else ""
                _print_assistant(result.content, result.model or chosen, allow_emoji, tokens)
                reply_text = text
            if mem is not None and reply_text:
                threading.Thread(target=_mem_capture, args=(mem, session_id, user_text, reply_text, reply_kind), daemon=True).start()
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
        if mem is not None:
            with console.status("[cyan]Saving memories...[/]", spinner="dots"):
                mem.flush(timeout=60.0)
            with console.status("[cyan]Reflecting on session (one LLM pass)...[/]", spinner="dots"):
                _session_reflect(mem, session_id)
        db_set_last(session_id)
        from mcpclient.manager import shutdown as mcp_shutdown
        try:
            mcp_shutdown()
        except BaseException:
            pass
        console.print(section_rule(f"SAVED  ·  SESSION {session_id[:12]}  ·  RESUME WITH: zumba chat --resume {session_id[:12]}"))
    except (Exception, KeyboardInterrupt) as exc:
        console.print(error_panel(f"Could not save session: {exc}", allow_emoji=allow_emoji))


def _mcp_chat_manage(args: str, allow_emoji: bool) -> None:
    """Handle '/mcp add ...' and '/mcp remove ...' live, in-session."""
    args = args.strip()
    try:
        if args.startswith("add "):
            rest = args[4:].strip()
            if "--url " in rest:
                name, url = rest.split("--url", 1)
                mcp_add_server(name.strip(), {"transport": "http", "url": url.strip()})
            elif "--" in rest:
                name, cmd = rest.split("--", 1)
                parts = cmd.strip().split()
                if not parts:
                    raise ValueError("empty command")
                mcp_add_server(name.strip(), {"command": parts[0], "args": parts[1:]})
            else:
                raise ValueError("use: /mcp add <name> -- <command...>  or  /mcp add <name> --url <url>")
        elif args.startswith("remove "):
            if not mcp_remove_server(args[7:].strip()):
                raise ValueError("server not found in home registry")
        else:
            raise ValueError("unsupported")
        summary = mcp_reload_sync()
        console.print(section_rule(f"MCP UPDATED LIVE  ·  {json.dumps(summary)}  ·  no restart needed"))
    except (ValueError, KeyError) as exc:
        console.print(error_panel(f"mcp: {exc}", allow_emoji=allow_emoji))


def _mcp_status_table(allow_emoji: bool) -> None:
    mgr = _mcp()
    rows = mgr.status_rows() if mgr is not None else []
    if not rows:
        console.print(info_panel(
            "No MCP servers configured.\nAdd servers to ~/.zumba/mcp.json (Claude-Desktop format) or:\n"
            "  zumba mcp add <name> -- <command> [args...]\n"
            "  zumba mcp add <name> --url https://mcp.example.com/mcp",
            title="MCP", allow_emoji=allow_emoji))
        return
    dot = {"online": "[green]●", "offline": "[red]●", "disabled": "[dim]○", "pending": "[yellow]●"}
    table = styled_table("MCP SERVERS", allow_emoji)
    table.add_column("", width=2)
    table.add_column("SERVER", style="cyan", no_wrap=True)
    table.add_column("TRANSPORT", style="dim")
    table.add_column("TOOLS", justify="right")
    table.add_column("STATUS")
    for r in rows:
        status = f"{dot.get(r['status'], '[red]●')} {r['status']}[/]" + (f"  [dim]{safe_text(r['error'], allow_emoji)[:60]}[/]" if r["error"] else "")
        table.add_row("", r["name"], r["transport"], str(r["tool_count"]), status)
    console.print(table)


def _shell_chat_run(cmd: str, allow_emoji: bool) -> None:
    """Handle '/shell <cmd>' live, in-session (bypasses the model)."""
    import shelltool

    if not cmd:
        console.print(info_panel("Usage: /shell <powershell command>", title="SHELL", allow_emoji=allow_emoji))
        return
    if not shelltool.enabled():
        console.print(error_panel("shell tool is disabled (ZUMBA_NO_SHELL=1).", allow_emoji=allow_emoji))
        return
    with console.status("[cyan]Running shell...[/]", spinner="dots"):
        res = shelltool.run(cmd)
    text = shelltool.format_result(res, cwd=shelltool.get_session().cwd)
    border = "red" if text.startswith("ERROR") else "green"
    console.print(Panel(safe_text(text, allow_emoji), title="SHELL",
                        title_align="left", border_style=border, box=_box(allow_emoji), padding=(0, 2)))


def _mcp_tools_table(allow_emoji: bool) -> None:
    mgr = _mcp()
    if mgr is None:
        console.print(info_panel("MCP disabled (ZUMBA_NO_MCP=1).", title="MCP TOOLS", allow_emoji=allow_emoji))
        return
    tools = mgr.all_tools()
    if not tools:
        console.print(info_panel("No tools available (no online servers or no tools).", title="MCP TOOLS", allow_emoji=allow_emoji))
        return
    table = styled_table(f"MCP TOOLS  ·  {len(tools)}", allow_emoji)
    table.add_column("QUALIFIED NAME", style="cyan", no_wrap=False)
    table.add_column("DESCRIPTION", style="dim")
    for t in tools:
        fn = t.get("function", {})
        desc = " ".join(str(fn.get("description", "")).split())[:90]
        table.add_row(fn.get("name", "?"), safe_text(desc, allow_emoji))
    console.print(table)


mcp_app = typer.Typer(help="MCP servers: list / add / remove / tools / call.")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("list")
def mcp_list_cmd() -> None:
    allow_emoji = _allow_emoji()
    console.print(_header())
    _mcp_status_table(allow_emoji)
    home = mcp_list_servers()
    proj_file = Path(__file__).resolve().parent / ".mcp.json"
    console.print(f"[dim]Home registry: {Path.home() / '.zumba' / 'mcp.json'}  ·  Project overrides: {proj_file}[/]") if not home else None


@mcp_app.command("add")
def mcp_add_cmd(
    name: str = typer.Argument(..., help="Server name (used as tool prefix, e.g. fs)."),
    command: list[str] = typer.Argument(None, help="Stdio command + args after --"),
    url: str = typer.Option("", "--url", help="Remote server URL (transport http)."),
    transport: str = typer.Option("", "--transport", help="http, sse or stdio (default auto)."),
    enabled: bool = typer.Option(True, "--disabled/--enabled"),
) -> None:
    try:
        if url:
            mcp_add_server(name, {"transport": transport or "http", "url": url, "enabled": enabled})
        elif command:
            mcp_add_server(name, {"command": command[0], "args": list(command[1:]), "enabled": enabled})
        else:
            _fail("Provide a command after -- or --url for a remote server.")
            return
    except ValueError as exc:
        _fail(str(exc))
        return
    console.print(section_rule(f"MCP SERVER ADDED  ·  {name}"))
    console.print(f"[dim]Restart zumba (or use /mcp in chat) to connect. Registry: {Path.home() / '.zumba' / 'mcp.json'}[/]")


@mcp_app.command("remove")
def mcp_remove_cmd(name: str = typer.Argument(...)) -> None:
    if mcp_remove_server(name):
        console.print(section_rule(f"MCP SERVER REMOVED  ·  {name}"))
    else:
        _fail(f"Server '{name}' not found in home registry.")


@mcp_app.command("tools")
def mcp_tools_cmd() -> None:
    allow_emoji = _allow_emoji()
    console.print(_header())
    _mcp_tools_table(allow_emoji)


@mcp_app.command("reload")
def mcp_reload_cmd() -> None:
    """Hot-reload servers from mcp.json without restarting."""
    allow_emoji = _allow_emoji()
    console.print(_header())
    summary = mcp_reload_sync()
    console.print(Panel(json.dumps(summary, indent=2), title="MCP RELOADED LIVE",
                        title_align="left", border_style="green", box=table_box(allow_emoji), padding=(0, 2)))
    _mcp_status_table(allow_emoji)


@mcp_app.command("call")
def mcp_call_cmd(
    tool: str = typer.Argument(..., help="Qualified tool name: server__tool."),
    args: str = typer.Option("{}", "--args", "-a", help="JSON object of arguments."),
    timeout: Optional[float] = typer.Option(None, "--timeout", help="Seconds (default from ZUMBA_MCP_TOOL_TIMEOUT or 60)."),
) -> None:
    try:
        arguments = json.loads(args) if args.strip() else {}
        if not isinstance(arguments, dict):
            raise ValueError("--args must be a JSON object")
    except ValueError as exc:
        _fail(f"Invalid --args: {exc}")
        return
    with console.status(f"[cyan]Calling {tool}...[/]", spinner="dots"):
        result = mcp_run_tool(tool, arguments, timeout=timeout)
    allow_emoji = _allow_emoji()
    border = "red" if result.startswith("ERROR") else "green"
    console.print(Panel(safe_text(result, allow_emoji), title=f"RESULT  ·  {tool}",
                        title_align="left", border_style=border, box=table_box(allow_emoji), padding=(1, 2)))


@app.command("shell")
def shell_cmd(
    cmd: str = typer.Argument(..., help="PowerShell command to run (persistent god-mode session)."),
    timeout: Optional[float] = typer.Option(None, "--timeout", help="Seconds (default from ZUMBA_SHELL_TIMEOUT or 60)."),
    no_emoji: bool = typer.Option(False, "--no-emoji", help="Strip emojis for legacy cmd."),
) -> None:
    import shelltool

    allow_emoji = _allow_emoji(no_emoji)
    if not shelltool.enabled():
        _fail("shell tool is disabled (ZUMBA_NO_SHELL=1).")
        return
    res = shelltool.run(cmd, timeout_s=timeout or 0)
    text = shelltool.format_result(res, cwd=shelltool.get_session().cwd)
    border = "red" if text.startswith("ERROR") else "green"
    console.print(Panel(safe_text(text, allow_emoji), title="SHELL",
                        title_align="left", border_style=border, box=_box(allow_emoji), padding=(0, 2)))
    if (res.get("exit_code") or 0) != 0:
        raise typer.Exit(code=int(res.get("exit_code") or 1))


memory_app = typer.Typer(help="Long-term memory (hippocampus): stats, search, add, forget, consolidate.")
app.add_typer(memory_app, name="memory")


@memory_app.command("stats")
def memory_stats_cmd() -> None:
    allow_emoji = _allow_emoji()
    mem = _memory()
    if mem is None:
        _fail("Memory is disabled (ZUMBA_NO_MEMORY=1 or import failed).")
        return
    s = mem.stats()
    table = styled_table("MEMORY STATS", allow_emoji)
    table.add_column("KEY", style="cyan", no_wrap=True)
    table.add_column("VALUE", style="white")
    for k in ("episodes", "entities", "relations", "active_relations", "notes", "communities", "core_blocks",
              "user_facts", "follow_ups_open", "moods", "eval_pairs", "eval_runs", "database"):
        table.add_row(k, str(s.get(k, "-")))
    console.print(table)


@memory_app.command("search")
def memory_search_cmd(
    query: str = typer.Argument(..., help="What to recall."),
    top_k: int = typer.Option(8, "--top", "-k"),
) -> None:
    allow_emoji = _allow_emoji()
    mem = _memory()
    if mem is None:
        _fail("Memory is disabled.")
        return
    console.print(_header())
    with console.status("[cyan]Recalling...[/]", spinner="dots"):
        out = mem.recall(query, top_k=top_k, max_bytes=6000)
    console.print(Panel(out or "(nothing recalled)", title="MEMORY", border_style="cyan", box=_box(allow_emoji)))


@memory_app.command("add")
def memory_add_cmd(
    text: str = typer.Argument(..., help="Fact to store, e.g. 'I prefer Python for tooling'."),
) -> None:
    mem = _memory()
    if mem is None:
        _fail("Memory is disabled.")
        return
    console.print(_header())
    with console.status("[cyan]Curating into memory (LLM extraction)...[/]", spinner="dots"):
        r = mem.ingest_episode(text, "", session_id="", kind="manual")
    console.print(section_rule(f"STORED  ·  {json.dumps(r)}"))


@memory_app.command("forget")
def memory_forget_cmd(
    name: str = typer.Argument(..., help="Entity name to invalidate."),
) -> None:
    mem = _memory()
    if mem is None:
        _fail("Memory is disabled.")
        return
    r = mem.forget(name)
    console.print(section_rule("FORGOT" if r.get("forgot") else f"NOT FOUND  ·  {r.get('reason', '')}"))


@memory_app.command("clear")
def memory_clear_cmd(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    if not yes:
        console.print("This wipes ALL long-term memory. Re-run with --yes to confirm.")
        return
    mem = _memory()
    if mem is None:
        _fail("Memory is disabled.")
        return
    mem.clear()
    console.print(section_rule("MEMORY CLEARED"))


@memory_app.command("consolidate")
def memory_consolidate_cmd() -> None:
    allow_emoji = _allow_emoji()
    mem = _memory()
    if mem is None:
        _fail("Memory is disabled.")
        return
    console.print(_header())
    with console.status("[cyan]Sleep-time compute: decay, note links, communities, core blocks...[/]", spinner="dots"):
        r = mem.consolidate(min_interval_s=0.0)
    console.print(Panel(json.dumps(r), title="CONSOLIDATION", border_style="cyan", box=_box(allow_emoji)))


@memory_app.command("eval")
def memory_eval_cmd(
    generate: bool = typer.Option(False, "--generate", help="Regenerate golden Q/A from current facts first."),
    use_llm: bool = typer.Option(False, "--llm", help="Use LLM generation + LLM judge (default: deterministic offline)."),
    top_k: int = typer.Option(6, "--top", "-k"),
) -> None:
    allow_emoji = _allow_emoji()
    mem = _memory()
    if mem is None:
        _fail("Memory is disabled.")
        return
    console.print(_header())
    from memory import db as _mdb, eval as _eval
    con = mem._open()
    try:
        if generate:
            with console.status("[cyan]Generating golden Q/A...[/]", spinner="dots"):
                pairs = _eval.generate_pairs(con, use_llm=use_llm)
            console.print(section_rule(f"EVAL PAIRS  ·  {len(pairs)} generated"))
        with console.status("[cyan]Running eval (full read path per question)...[/]", spinner="dots"):
            report = _eval.run_eval(mem, use_llm=use_llm, top_k=top_k)
        table = styled_table("MEMORY EVAL", allow_emoji)
        table.add_column("CATEGORY", style="cyan")
        table.add_column("HITS", justify="right")
        table.add_column("TOTAL", justify="right")
        table.add_column("HIT RATE", justify="right")
        for cat, d in (report.get("per_category") or {}).items():
            table.add_row(cat, str(d.get("hits", 0)), str(d.get("total", 0)), f"{float(d.get('hit_rate', 0)):.0%}")
        table.add_row("[bold]OVERALL[/]", str(report.get("hits", 0)), str(report.get("total", 0)), f"{float(report.get('hit_rate', 0)):.0%}")
        console.print(table)
    finally:
        if getattr(mem, "_own", True):
            try:
                con.close()
            except Exception:
                pass


@memory_app.command("people")
def memory_people_cmd(limit: int = typer.Option(15, "--limit", "-n")) -> None:
    allow_emoji = _allow_emoji()
    mem = _memory()
    if mem is None:
        _fail("Memory is disabled.")
        return
    console.print(_header())
    from memory import people as _people
    con = mem._open()
    try:
        rows = _people.people_overview(con, limit=limit)
        text = _people.render_people(rows)
    finally:
        if getattr(mem, "_own", True):
            try:
                con.close()
            except Exception:
                pass
    console.print(Panel(safe_text(text, allow_emoji), title="PEOPLE", border_style="cyan", box=_box(allow_emoji)))


soul_app = typer.Typer(help="Soul identity file: show / init / diff / accept / reject.")
app.add_typer(soul_app, name="soul")


@soul_app.command("show")
def soul_show_cmd() -> None:
    allow_emoji = _allow_emoji()
    import soul as _soul
    console.print(_header())
    console.print(Panel(safe_text(_soul.load() or "(no soul.md yet)", allow_emoji), title="SOUL",
                        title_align="left", border_style="cyan", box=_box(allow_emoji), padding=(0, 2)))


@soul_app.command("init")
def soul_init_cmd(
    sound: str = typer.Option("", "--sound", help="How Zumba should sound."),
    keep: str = typer.Option("", "--keep", help="What to keep in mind about you."),
    off_limits: str = typer.Option("", "--off-limits", help="Off-limits topics/tone."),
    wingit: bool = typer.Option(False, "--wingit", help="Draft from early exchanges."),
) -> None:
    import soul as _soul
    console.print(_header())
    if wingit or not any([sound, keep, off_limits]):
        r = _soul.bootstrap_flow({"sound": sound or "just wing it", "keep": keep, "off_limits": off_limits})
    else:
        r = _soul.bootstrap_flow({"sound": sound, "keep": keep, "off_limits": off_limits})
    console.print(section_rule(f"SOUL WRITTEN  ·  {r.get('soul', '')}"))


@soul_app.command("diff")
def soul_diff_cmd() -> None:
    allow_emoji = _allow_emoji()
    import soul as _soul
    console.print(Panel(safe_text(_soul.diff_proposed(), allow_emoji), title="SOUL DIFF",
                        title_align="left", border_style="cyan", box=_box(allow_emoji), padding=(0, 2)))


@soul_app.command("accept")
def soul_accept_cmd() -> None:
    import soul as _soul
    console.print(section_rule("SOUL UPDATED" if _soul.apply_proposal() else "NO PROPOSAL"))


@soul_app.command("reject")
def soul_reject_cmd() -> None:
    import soul as _soul
    _soul.reject_proposal()
    console.print(section_rule("SOUL PROPOSAL REJECTED"))


@app.command("daily")
def daily_cmd(
    install_reminder: bool = typer.Option(False, "--install-reminder", help="Register a Windows Task Scheduler daily job."),
    at: str = typer.Option("08:00", "--at", help="Reminder time HH:MM."),
    use_llm: bool = typer.Option(True, "--llm/--no-llm", help="Compose with LLM or raw digest."),
) -> None:
    allow_emoji = _allow_emoji()
    if install_reminder:
        from memory import briefing as _br
        console.print(_header())
        console.print(Panel(json.dumps(_br.install_reminder(time_hhmm=at), indent=2), title="DAILY REMINDER",
                            title_align="left", border_style="cyan", box=_box(allow_emoji)))
        return
    mem = _memory()
    if mem is None:
        _fail("Memory is disabled.")
        return
    console.print(_header())
    from memory import briefing as _br2
    con = mem._open()
    try:
        text = _br2.compose_daily(con, use_llm=use_llm)
    finally:
        if getattr(mem, "_own", True):
            try:
                con.close()
            except Exception:
                pass
    console.print(Panel(safe_text(text[:8000], allow_emoji), title="DAILY BRIEF",
                        title_align="left", border_style="cyan", box=_box(allow_emoji), padding=(1, 2)))


@app.command("mood")
def mood_cmd(days: int = typer.Option(30, "--days", "-d")) -> None:
    allow_emoji = _allow_emoji()
    mem = _memory()
    if mem is None:
        _fail("Memory is disabled.")
        return
    console.print(_header())
    from memory import mood as _mood
    con = mem._open()
    try:
        text = _mood.render_chart(con, days=days)
    finally:
        if getattr(mem, "_own", True):
            try:
                con.close()
            except Exception:
                pass
    console.print(Panel(safe_text(text, allow_emoji), title="MOOD",
                        title_align="left", border_style="cyan", box=_box(allow_emoji), padding=(0, 2)))


@app.command("me")
def me_cmd() -> None:
    allow_emoji = _allow_emoji()
    import userprofile as _up
    console.print(_header())
    console.print(Panel(safe_text(_up.profile_block() or "(no user.md yet)", allow_emoji), title="ME  ·  user.md",
                        title_align="left", border_style="cyan", box=_box(allow_emoji), padding=(0, 2)))


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
        table.add_row("zumba memory", "Long-term memory: stats / search / add / forget / consolidate")
        table.add_row("zumba mcp", "MCP servers: list / add / remove / tools / call")
        table.add_row("zumba doctor", "Terminal + rendering diagnostics")
        table.add_row("zumba version", "Show version")
        console.print(table)
        console.print(section_rule("SET KILO_API_KEY TO CHAT  ·  DEFAULT kilo-auto/free"))


if __name__ == "__main__":
    app()
