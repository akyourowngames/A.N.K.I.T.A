"""FEATURE S — soul.md: self-authored identity + user.md companion.

soul.md = who Zumba IS (voice/values/boundaries, soul.md spec structure).
user.md  = who YOU are (AgentOS "what goes where" split).

Bootstrap (first message only, zero hardcoding): 3 short questions, skippable
("just wing it" -> LLM drafts from early exchanges). Zumba writes soul.md
ITSELF via one LLM call, persisted with its own shell tool when available.

Self-editing with consent (Letta rethink_memory pattern): consolidation
proposes updates -> soul.proposed.md -> /soul diff -> /soul accept|reject.
Hard cap ~4k chars (context budget protection).
"""

from __future__ import annotations

import difflib
import os
import re
from pathlib import Path

SOUL_CAP = 4000
USER_CAP = 4000

BOOTSTRAP_QUESTIONS = [
    "How should I sound? (e.g. terse, warm, playful — or 'just wing it')",
    "What should I always keep in mind about you? (work, projects, people)",
    "Anything off-limits? (topics, tone, things to never do)",
]


def _home() -> Path:
    try:
        from store import zumba_home
        return zumba_home()
    except Exception:
        h = Path.home() / ".zumba"
        h.mkdir(parents=True, exist_ok=True)
        return h


def soul_path() -> Path:
    return Path(os.getenv("ZUMBA_HOME", str(_home()))) / "soul.md" if os.getenv("ZUMBA_HOME") else _home() / "soul.md"


def user_path() -> Path:
    return soul_path().parent / "user.md"


def proposed_path() -> Path:
    return soul_path().parent / "soul.proposed.md"


def exists() -> bool:
    try:
        return soul_path().exists() and soul_path().stat().st_size > 0
    except Exception:
        return False


def needs_bootstrap() -> bool:
    return not exists()


def enforce_cap(text: str, limit: int = SOUL_CAP) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    at = cut.rfind("\n")
    if at > limit * 0.6:
        cut = cut[:at]
    return cut.rstrip() + "\n\n<!-- truncated to 4k cap -->"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text or "", re.S)
    if not m:
        return {}, (text or "")
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, m.group(2)


def _shell_write(path: Path, content: str) -> None:
    try:
        import shelltool
        if shelltool.enabled():
            shelltool.run(f"New-Item -ItemType Directory -Force -Path {str(path.parent)!r} | Out-Null")
    except Exception:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def compose_soul(answers: dict, early_exchanges: list | None = None) -> str:
    name = (answers.get("name") or "Zumba").strip() or "Zumba"
    sound = (answers.get("sound") or answers.get("voice") or "").strip()
    keep = (answers.get("keep") or answers.get("about_you") or "").strip()
    off = (answers.get("off_limits") or answers.get("boundaries") or "").strip()
    if (not sound and not keep and not off) or (sound.lower().startswith("just wing") or sound.lower() == "skip"):
        drafted = _draft_from_exchanges(early_exchanges or [])
        if drafted:
            return enforce_cap(drafted)
    prompt = (
        "Write a soul.md for a personal AI assistant following this structure:\n"
        "YAML frontmatter (name, version, updated) then sections: ## Identity, ## Voice, ## Values, ## Boundaries.\n"
        "Keep it concrete, first-person as the assistant, under 2500 chars.\n"
        f"Assistant name: {name}\nVoice notes: {sound or '(choose a direct warm voice)'}\n"
        f"About the user: {keep or '(unknown yet)'}\nOff-limits: {off or '(none stated)'}\n"
    )
    try:
        from memory import llm as _llm
        out = _llm.chat_text(prompt, system="You write soul.md identity files. Output markdown only.", max_tokens=1200)
        if out and "## Identity" in out:
            return enforce_cap(out.strip())
    except Exception:
        pass
    body = (
        f"---\nname: {name}\nversion: 1\nupdated: auto\n---\n\n"
        f"## Identity\nI am {name}, a personal AI assistant. Direct, warm, zero fluff.\n\n"
        f"## Voice\n{(sound or 'Direct and warm. Short answers unless depth is asked for. Use remembered context without being asked.')}\n\n"
        f"## Values\nRemember what matters to the user. Prefer action over narration. Admit uncertainty.\n"
        + (f"Keep in mind: {keep}\n" if keep else "")
        + f"\n## Boundaries\n{(off or 'No hard boundaries stated. Ask before risky or irreversible actions.')}\n"
    )
    return enforce_cap(body)


def _draft_from_exchanges(exchanges: list) -> str:
    if not exchanges:
        return ""
    bits = []
    for e in exchanges[:6]:
        if isinstance(e, dict):
            bits.append(f"USER: {(e.get('user') or e.get('content') or '')[:300]}")
        else:
            bits.append(f"USER: {str(e)[:300]}")
    try:
        from memory import llm as _llm
        out = _llm.chat_text(
            "Draft a soul.md (frontmatter + Identity/Voice/Values/Boundaries, <2500 chars) for a personal "
            "assistant from these first exchanges. Infer a direct warm voice; do not invent user facts.\n\n" + "\n".join(bits),
            system="You write soul.md identity files. Output markdown only.",
            max_tokens=1200,
        )
        if out:
            return enforce_cap(out.strip())
    except Exception:
        pass
    return ""


def compose_user_md(answers: dict) -> str:
    keep = (answers.get("keep") or answers.get("about_you") or "").strip()
    body = (
        "---\nname: user\nversion: 1\nupdated: auto\n---\n\n"
        "# User\n\n## Identity\n" + (keep or "(unknown yet — fill in as we learn)") + "\n\n"
        "## Projects\n(none recorded yet)\n\n## People\n(none recorded yet)\n\n"
        "## Preferences\n(none recorded yet)\n\n## Goals\n(none recorded yet)\n\n"
        "## Current focus\n(none recorded yet)\n"
    )
    return enforce_cap(body, USER_CAP)


def bootstrap_flow(answers: dict, early_exchanges: list | None = None) -> dict:
    soul = compose_soul(answers, early_exchanges)
    user = compose_user_md(answers)
    _shell_write(soul_path(), soul)
    _shell_write(user_path(), user)
    return {"soul": str(soul_path()), "user": str(user_path()), "soul_chars": len(soul)}


def load() -> str:
    try:
        return soul_path().read_text(encoding="utf-8") if exists() else ""
    except Exception:
        return ""


def load_user() -> str:
    try:
        p = user_path()
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except Exception:
        return ""


def inject_block(max_chars: int = SOUL_CAP) -> str:
    text = load()
    if not text:
        return ""
    meta, body = parse_frontmatter(text)
    head = f"soul.md ({meta.get('name', 'Zumba')})" if meta else "soul.md"
    block = f"[{head} — who I am, in my own words]\n" + (body.strip() or text.strip())
    if len(block) > max_chars:
        block = enforce_cap(block, max_chars)
    return block


def propose_update(new_content: str) -> str:
    capped = enforce_cap(new_content or "")
    _shell_write(proposed_path(), capped)
    return str(proposed_path())


def has_proposal() -> bool:
    try:
        return proposed_path().exists() and proposed_path().stat().st_size > 0
    except Exception:
        return False


def diff_proposed() -> str:
    cur = load()
    try:
        prop = proposed_path().read_text(encoding="utf-8") if has_proposal() else ""
    except Exception:
        prop = ""
    if not prop:
        return "No pending soul proposal."
    if not cur:
        return prop
    diff = difflib.unified_diff(cur.splitlines(), prop.splitlines(), fromfile="soul.md", tofile="soul.proposed.md", lineterm="")
    out = "\n".join(diff)
    return out or "(no differences)"


def apply_proposal() -> bool:
    if not has_proposal():
        return False
    try:
        prop = proposed_path().read_text(encoding="utf-8")
        _shell_write(soul_path(), enforce_cap(prop))
        proposed_path().unlink()
        return True
    except Exception:
        return False


def reject_proposal() -> bool:
    try:
        if has_proposal():
            proposed_path().unlink()
        return True
    except Exception:
        return False


def append_voice_preference(line: str) -> str:
    cur = load()
    if not cur:
        return ""
    addition = f"\n- {line.strip()}\n"
    if "## Voice" in cur:
        new = cur.replace("## Voice", "## Voice" + addition, 1)
    else:
        new = cur.rstrip() + "\n\n## Voice\n" + addition
    return propose_update(new)
