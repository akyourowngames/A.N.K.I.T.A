import os
import re
import sys
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

APP_NAME = "ZUMBA"
APP_VERSION = "1.1.0"
APP_TAGLINE = "Personal AI Assistant  ·  Kilo Gateway"
ACCENT = "cyan"
BORDER_DIM = "dim"
ERROR_BORDER = "red"
OK_BORDER = "green"

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U00002B00-\U00002BFF"
    "\uFE0F"
    "\u200D"
    "\u2640-\u2642"
    "\u2695-\u2696"
    "]+",
    flags=re.UNICODE,
)


def setup_windows_console() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass


def is_modern_terminal() -> bool:
    if os.getenv("ZUMBA_FORCE_EMOJI", "") == "1":
        return True
    if os.getenv("ZUMBA_NO_EMOJI", "") == "1":
        return False
    if os.getenv("WT_SESSION", ""):
        return True
    term_program = (os.getenv("TERM_PROGRAM", "") or "").lower()
    if "vscode" in term_program or "hyper" in term_program or "wezterm" in term_program:
        return True
    if os.getenv("VSCODE_INJECTION", "") or os.getenv("VSCODE_PID", ""):
        return True
    if os.getenv("TERM", "") == "xterm-256color":
        return True
    return False


def emoji_supported() -> bool:
    return is_modern_terminal()


def remove_emoji_only(text: str) -> str:
    if not text:
        return text
    return _EMOJI_PATTERN.sub("", text)


def strip_emoji(text: str) -> str:
    if not text:
        return text
    cleaned = _EMOJI_PATTERN.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def safe_text(text: str, allow_emoji: bool = True) -> str:
    if allow_emoji:
        return text
    return strip_emoji(text)


def make_console(allow_emoji: bool = True) -> Console:
    if allow_emoji:
        return Console(legacy_windows=False, force_terminal=None)
    return Console(legacy_windows=True, force_terminal=None)


def table_box(allow_emoji: bool) -> box.Box:
    if allow_emoji:
        return box.ROUNDED
    return box.ASCII


def write_stream_chunk(text: str) -> None:
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except Exception:
        pass


def terminal_report() -> dict:
    out_cp = 0
    in_cp = 0
    try:
        import ctypes
        out_cp = int(ctypes.windll.kernel32.GetConsoleOutputCP())
        in_cp = int(ctypes.windll.kernel32.GetConsoleCP())
    except Exception:
        pass
    return {
        "modern": is_modern_terminal(),
        "wt_session": bool(os.getenv("WT_SESSION", "")),
        "term_program": os.getenv("TERM_PROGRAM", ""),
        "vscode": bool(os.getenv("VSCODE_PID", "") or os.getenv("VSCODE_INJECTION", "")),
        "output_cp": out_cp,
        "input_cp": in_cp,
        "stdout_encoding": getattr(sys.stdout, "encoding", "?"),
    }


def app_header(allow_emoji: bool = True) -> Panel:
    sep = "·" if allow_emoji else "-"
    body = (
        f"[bold white]{APP_NAME}[/]  [dim]v{APP_VERSION}  {sep}  {APP_TAGLINE}[/]"
    )
    return Panel(body, border_style=ACCENT, box=table_box(allow_emoji), padding=(0, 2), expand=True)


def section_rule(text: str = "") -> Rule:
    return Rule(text, style=BORDER_DIM, align="left")


def error_panel(message: str, hint: str = "", allow_emoji: bool = True) -> Panel:
    body = safe_text(message, allow_emoji)
    if hint:
        body += f"\n\n[dim]{safe_text(hint, allow_emoji)}[/]"
    return Panel(body, title="[bold red]ERROR[/]", border_style=ERROR_BORDER, box=table_box(allow_emoji), padding=(1, 2), expand=False)


def info_panel(body: str, title: str = "INFO", allow_emoji: bool = True) -> Panel:
    return Panel(safe_text(body, allow_emoji), title=f"[bold cyan]{title}[/]", title_align="left", border_style=ACCENT, box=table_box(allow_emoji), padding=(1, 2), expand=False)


def styled_table(title: str, allow_emoji: bool = True) -> Table:
    return Table(
        title=f"[bold white]{title}[/]",
        title_justify="left",
        box=table_box(allow_emoji),
        border_style=BORDER_DIM,
        header_style="bold cyan",
        show_lines=False,
        pad_edge=False,
        padding=(0, 2),
    )


def assistant_panel(text: str, model: str = "", allow_emoji: bool = True, tokens: str = "") -> Panel:
    shown = text if allow_emoji else strip_emoji(text)
    title = f"[bold white]ASSISTANT[/][dim]{'  ·  ' + model if model else ''}[/]"
    subtitle = f"[dim]{tokens}[/]" if tokens else ""
    try:
        body = Markdown(shown)
    except Exception:
        body = safe_text(shown, allow_emoji)
    return Panel(body, title=title, title_align="left", subtitle=subtitle, subtitle_align="right", border_style=ACCENT, box=table_box(allow_emoji), padding=(1, 2), expand=True)


def meta_line(label: str, value: str) -> str:
    return f"[dim]{label}:[/] [white]{value}[/]"
