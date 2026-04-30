from __future__ import annotations

import re
from datetime import datetime
from typing import Any


CODE_BLOCK_PATTERN = re.compile(r"```.*?```", re.DOTALL)
CODE_LINE_PATTERNS = (
    re.compile(r"^\s*def\s+\w+\s*\("),
    re.compile(r"^\s*class\s+\w+"),
    re.compile(r"^\s*import\s+\w+"),
    re.compile(r"^\s*from\s+\S+\s+import\s+"),
)


def build_report(
    snapshot: dict[str, Any],
    events: list[dict[str, Any]],
    llm_sections: dict[str, str] | None = None,
) -> str:
    project = snapshot.get("project") or {}
    changed_files = snapshot.get("changed_files") or []
    file_context = snapshot.get("file_context") or {}
    test_inventory = snapshot.get("test_inventory") or []
    recent_events = events[-10:]
    llm_sections = llm_sections or {}

    lines = [
        "# Daemon Project Report",
        "",
        f"Updated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Project Overview",
        "",
        clean_section(llm_sections.get("project_analysis"), "No project analysis available yet."),
        "",
        "## Current Status",
        "",
        f"- Project folder: {project.get('name') or 'unknown'}",
        f"- Branch: {snapshot.get('branch') or 'unknown'}",
        f"- Changed files: {len(changed_files)}",
        f"- Python files scanned: {project.get('python_file_count', 0)}",
        f"- Skill files scanned: {len(project.get('skill_files') or [])}",
        f"- Validation: {summarize_validation(snapshot.get('validation'))}",
        f"- Last daemon note: {recent_events[-1].get('summary') if recent_events else 'none yet'}",
        "",
        "## Quality And Risks",
        "",
        clean_section(llm_sections.get("code_review"), "No quality/risk review available yet."),
        "",
        "## Next Actions",
        "",
        clean_section(llm_sections.get("next_actions"), "No next-action plan available yet."),
        "",
        "## Evidence Sources",
        "",
        "### Files Read",
        "",
    ]

    if file_context:
        lines.extend(f"- {file_path}" for file_path in sorted(file_context))
    else:
        lines.append("- No representative files read.")

    lines.extend(["", "### Changed Files", ""])
    if changed_files:
        lines.extend(f"- {file_path}" for file_path in changed_files)
    else:
        lines.append("- No changed files detected.")

    lines.extend(["", "### Discovered Tests", ""])
    if test_inventory:
        lines.extend(f"- {name}" for name in test_inventory)
    else:
        lines.append("- No tests discovered.")

    lines.extend(["", "### Git Reading", ""])
    lines.append(f"- Working tree: {summarize_git_status(snapshot.get('status'))}")
    lines.append(f"- Diff size: {summarize_diff_stat(snapshot.get('diff_stat'))}")
    lines.append(f"- Recent commits: {summarize_line_count(snapshot.get('recent_commits'), 'commit')}")
    lines.append(f"- GitHub remote: {summarize_github(snapshot.get('github'))}")

    lines.extend(["", "## Recent Daemon Events", ""])

    if recent_events:
        for event in recent_events:
            lines.append(f"- {event.get('timestamp')}: {event.get('summary')}")
    else:
        lines.append("- No daemon events recorded yet.")

    return "\n".join(lines).strip() + "\n"


def summarize_validation(text: str | None) -> str:
    if not text or not text.strip():
        return "not run"

    important = []
    for line in text.splitlines():
        stripped = line.strip()
        if (
            stripped.startswith("Ran ")
            or stripped in {"OK", "FAILED"}
            or stripped.startswith("FAILED ")
            or stripped.startswith("ERROR")
        ):
            important.append(stripped)

    return "; ".join(important[:3]) if important else "captured"


def summarize_git_status(text: str | None) -> str:
    if not text or not text.strip():
        return "clean"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return f"{len(lines)} changed or untracked path{'s' if len(lines) != 1 else ''}"


def summarize_diff_stat(text: str | None) -> str:
    if not text or not text.strip():
        return "no diff stat"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary_line = next((line for line in lines if "file" in line and ("changed" in line or "insertions" in line or "deletions" in line)), "")
    return summary_line or f"{len(lines)} diff-stat line{'s' if len(lines) != 1 else ''}"


def summarize_line_count(text: str | None, item_name: str) -> str:
    if not text or not text.strip():
        return "none"

    count = len([line for line in text.splitlines() if line.strip()])
    return f"{count} {item_name}{'s' if count != 1 else ''}"


def summarize_github(text: str | None) -> str:
    if not text or not text.strip():
        return "none detected"

    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line or "detected"


def clean_section(text: str | None, fallback: str) -> str:
    if not text or not text.strip():
        return fallback

    cleaned = CODE_BLOCK_PATTERN.sub("[code excerpt omitted]", text.strip())
    safe_lines = []
    for line in cleaned.splitlines():
        if any(pattern.match(line) for pattern in CODE_LINE_PATTERNS):
            continue
        safe_lines.append(line)
    return "\n".join(safe_lines).strip() or fallback


def build_llm_evidence(snapshot: dict[str, Any], events: list[dict[str, Any]]) -> str:
    project = snapshot.get("project") or {}
    changed_files = snapshot.get("changed_files") or []
    file_context = snapshot.get("file_context") or {}

    lines = [
        "Project evidence:",
        f"- Folder name: {project.get('name')}",
        f"- Root: {project.get('root')}",
        f"- Directories: {', '.join(project.get('directories') or [])}",
        f"- Important files: {', '.join(project.get('files') or [])}",
        f"- .env present: {project.get('env_file_present')}",
        f"- Python file count: {project.get('python_file_count')}",
        f"- Skill files: {', '.join(project.get('skill_files') or [])}",
        f"- Branch: {snapshot.get('branch')}",
        f"- Changed files: {', '.join(changed_files) if changed_files else 'none'}",
        f"- Validation summary: {summarize_validation(snapshot.get('validation'))}",
        "",
        "Persona excerpt:",
        project.get("persona_excerpt") or "<none>",
        "",
        "Discovered tests:",
        "\n".join(f"- {name}" for name in snapshot.get("test_inventory") or []) or "<none>",
        "",
        "Git status:",
        snapshot.get("status") or "<empty>",
        "",
        "Diff stat:",
        snapshot.get("diff_stat") or "<empty>",
        "",
        "Recent commits:",
        snapshot.get("recent_commits") or "<empty>",
        "",
        "Validation output:",
        snapshot.get("validation") or "<not run>",
        "",
        "Representative file excerpts:",
    ]

    for file_path, excerpt in file_context.items():
        lines.extend([f"\n--- {file_path} ---", excerpt[:4000]])

    if events:
        lines.extend(["", "Recent daemon events:"])
        for event in events[-10:]:
            lines.append(f"- {event.get('timestamp')}: {event.get('summary')}")

    return "\n".join(lines)
