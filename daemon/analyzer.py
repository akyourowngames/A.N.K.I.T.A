from __future__ import annotations

from typing import Any

from daemon.llm import DaemonLLM
from daemon.report import build_llm_evidence


PROJECT_ANALYSIS_PROMPT = """You are a project daemon analyst.

Analyze the project from generic evidence only. Do not assume the project type.
Infer the project identity, features, progress, and needs from file names, file excerpts, git status, commits, and tool output.
The final report is for memory, not for code display: do not include code snippets, code blocks, raw excerpts, or line-by-line implementation dumps.
Do not use a fixed feature checklist.
Do not invent files, commands, scripts, test results, or project goals that are not supported by evidence.
If .env is present, do not say it is missing; never request secret values.
If persona evidence is present, use it when judging personality/persona status.
If validation output shows tests passing, treat tests as run and mention only remaining live/manual validation gaps.
Git status prefix `??` means the file is untracked, not that the file has a runtime problem.
Do not call a feature incomplete, half-done, missing, broken, or risky just because its files changed or exist.
Only mark something incomplete when evidence directly shows failure, TODO markers, errors, or failed validation.
If something is uncertain, say "unclear from evidence".
Write concise Markdown with these sections:
- Project Identity
- What It Can Do
- Completed / Working
- In Progress / Half Done
- What It Needs Next
- Unclear From Evidence

Use project-specific words from file names, skill documents, persona, tests, and excerpts.
Do not ask generic project-charter questions. If uncertain, give the best-supported inference and state what evidence is missing.
"""

STATUS_REVIEW_PROMPT = """You are a factual project-status daemon.

Review the project evidence and changed files. Write concise Markdown:
- Verified Status
- Validation Already Done
- Needs Manual Verification
- Real Blockers

Do not include code snippets, code blocks, raw excerpts, or line-by-line implementation dumps.
Do not invent file contents, risks, missing tests, blockers, or integration problems beyond the evidence.
Do not create generic "likely risks" just because files changed.
Use the discovered test inventory when judging test coverage.
If validation output shows tests passed, clearly say tests passed.
Only mention missing tests when evidence directly shows a specific untested behavior.
Only mention manual verification for behavior that unit tests cannot prove, such as live LLM calls, Windows app opening, microphone input, or real external APIs.
Git status prefix `??` means untracked file; do not say the file must "handle ?? status".
Do not recommend tools, commands, or files that are not present in evidence.
"""

NEXT_ACTIONS_PROMPT = """You are a project planning daemon.

From the evidence, write a short actionable plan:
- Immediate Next Step
- Then
- Before Commit
- What JARVIS Should Remember

Keep it concrete and project-specific.
Do not include code snippets, code blocks, raw excerpts, or line-by-line implementation dumps.
Do not recommend `git add .`; recommend reviewing and staging intended files by path.
Do not mention non-existent scripts or commands.
Git status prefix `??` means untracked file; suggest reviewing/staging it, not changing the file to handle that status.
If validation output is not included, say to run the existing test command visible in evidence if available.
"""


class DaemonAnalyzer:
    def __init__(self, llm: DaemonLLM | None = None) -> None:
        self.llm = llm

    def analyze(self, snapshot: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, str]:
        if not self.llm:
            return {}

        evidence = build_llm_evidence(snapshot, events)
        return {
            "project_analysis": self._safe_chat("review", PROJECT_ANALYSIS_PROMPT, evidence),
            "status_review": self._safe_chat("code_review", STATUS_REVIEW_PROMPT, evidence),
            "next_actions": self._safe_chat("writing", NEXT_ACTIONS_PROMPT, evidence),
        }

    def _safe_chat(self, role: str, system: str, user: str) -> str:
        try:
            return self.llm.chat(role, system, user)
        except Exception as error:
            return f"LLM section unavailable: {error}"
