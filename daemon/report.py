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
        build_project_overview(project, snapshot),
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
        "## Verified Status",
        "",
        build_verified_status(snapshot),
        "",
        "## Next Actions",
        "",
        build_next_actions(snapshot),
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


def factual_status_fallback(snapshot: dict[str, Any]) -> str:
    return (
        "- Unit tests: "
        f"{summarize_validation(snapshot.get('validation'))}\n"
        "- Manual verification still useful for live LLM calls, Windows app control, microphone input, and external APIs.\n"
        "- No unsupported missing-test or integration-risk claims were generated."
    )


def build_verified_status(snapshot: dict[str, Any]) -> str:
    validation = summarize_validation(snapshot.get("validation"))
    lines = [
        f"- Unit tests: {validation}",
        "- Report mode: factual status only; no speculative missing-test or integration-risk claims.",
    ]
    if "OK" in validation:
        lines.append("- Known blockers from evidence: none.")
    else:
        lines.append("- Known blockers from evidence: validation needs attention.")
    lines.append("- Manual checks still useful for live LLM calls, microphone input, Windows app opening, and real external APIs.")
    return "\n".join(lines)


def build_project_overview(project: dict[str, Any], snapshot: dict[str, Any]) -> str:
    capabilities = capability_readings(project)
    changed_files = snapshot.get("changed_files") or []
    validation = summarize_validation(snapshot.get("validation"))

    lines = [
        "### Project Identity",
        "",
        f"- Name: {project.get('name') or 'unknown'}",
        "- Reading: local personal AI assistant with core brain logic, tool use, skills, memory, chat sessions, and daemon project reporting.",
        "",
        "### Capabilities Visible From Files",
        "",
    ]
    lines.extend(f"- {capability}" for capability in capabilities)
    lines.extend(
        [
            "",
            "### Completed / Working Evidence",
            "",
            f"- Validation: {validation}",
            f"- Core directories present: {', '.join(project.get('directories') or []) or 'none detected'}",
            f"- Python files scanned: {project.get('python_file_count', 0)}",
            f"- Skill files scanned: {len(project.get('skill_files') or [])}",
            "",
            "### Active Work",
            "",
        ]
    )
    if changed_files:
        lines.extend(f"- {path}" for path in changed_files)
    else:
        lines.append("- No changed files detected.")

    lines.extend(
        [
            "",
            "### Next Useful Checks",
            "",
            "- Review the changed files listed above before commit.",
            "- Keep unit tests passing.",
            "- Manually verify live-only behavior: LLM calls, microphone input, Windows app opening, and external APIs.",
        ]
    )
    return "\n".join(lines)


def capability_readings(project: dict[str, Any]) -> list[str]:
    paths = set(project.get("python_files") or []) | set(project.get("skill_files") or []) | set(project.get("files") or [])
    readings = []
    checks = [
        ("core/brain.py", "Brain and message flow"),
        ("core/memory.py", "Permanent memory"),
        ("core/pc_monitor.py", "PC activity awareness"),
        ("core/speech.py", "Text-to-speech support"),
        ("core/nvidia_stt.py", "CLI voice input with SpeechRecognition and NVIDIA STT"),
        ("tool/system_control.py", "Windows system control"),
        ("tool/terminal.py", "PowerShell terminal execution"),
        ("tool/weather.py", "Weather lookup"),
        ("tool/gmail.py", "Gmail search/read/draft/send"),
        ("tool/google_calendar.py", "Google Calendar events"),
        ("skills/tavily-web-search-tool.md", "Tavily web search"),
        ("telegram_bot.py", "Telegram bot bridge"),
        ("daemon/project_daemon.py", "Background project daemon"),
        ("daemon/report.py", "Clean project-status report generation"),
        ("persona.md", "JARVIS-style persona"),
    ]
    for path, label in checks:
        if path in paths:
            readings.append(label)
    return readings or ["Project files were scanned, but no named capabilities were detected."]


def build_next_actions(snapshot: dict[str, Any]) -> str:
    changed_files = snapshot.get("changed_files") or []
    lines = [
        "- Review the changed files listed in Active Work / Evidence Sources.",
        "- Stage only the intended files by path when ready.",
        "- Keep the existing unit test suite passing.",
        "- Manually verify live-only behavior touched by this work: LLM calls, microphone input, Windows app opening, and external APIs.",
    ]
    if changed_files:
        lines.append(f"- Current changed-file count: {len(changed_files)}.")
    return "\n".join(lines)


def remove_speculation(text: str) -> str:
    return remove_lines_containing(
        text,
        [
            "missing tests",
            "integration concern",
            "likely risks",
            "not yet fully implemented",
            "not fully implemented",
            "incomplete or inconsistent",
            "incomplete",
            "needs to have",
            "needs to continue development",
            "needs further development",
            "may have introduced",
            "new bugs",
            "broken existing functionality",
            "not entirely clear",
            "unclear",
            "what is the purpose",
        ],
    )


def remove_lines_containing(text: str, phrases: list[str]) -> str:
    lower_phrases = [phrase.lower() for phrase in phrases]
    kept = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(phrase in lowered for phrase in lower_phrases):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


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
