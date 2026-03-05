"""
Morning Agent — first-boot-of-day briefing for A.N.K.I.T.A.

Composes a short, spoken-friendly morning briefing from intent, tasks,
watchdog state, system stats, and cron. Max ~150 words, bullet-ish.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def generate_briefing(
    runtime: Any,
    intent: Optional[Dict[str, Any]] = None,
    tasks_summary: Optional[str] = None,
    watchdog_state: Optional[str] = None,
    system_stats: Optional[Dict[str, Any]] = None,
    cron_today: Optional[List[str]] = None,
    user_name: str = "Krish",
) -> str:
    """
    Generate a morning briefing string (max ~150 words, spoken-friendly).

    Args:
        runtime: LLMRuntime for the LLM call.
        intent: Daily intent dict (active_projects, open_loops, today_deadlines, etc.)
        tasks_summary: Summary of pending/overdue tasks.
        watchdog_state: WatchdogManager.status() or similar.
        system_stats: e.g. {"disk_pct": 87, "battery_pct": 100, "battery_plugged": True}
        cron_today: List of cron job descriptions due today.
        user_name: Name to use in greeting.

    Returns:
        Briefing text (plain, no markdown), or empty string on failure.
    """
    intent = intent or {}
    system_stats = system_stats or {}
    cron_today = cron_today or []
    tasks_summary = (tasks_summary or "").strip()
    watchdog_state = (watchdog_state or "").strip()

    # Build context block for the LLM
    lines = [
        f"User's name: {user_name}.",
        "",
        "Intent (what ANKITA thinks the user is focused on):",
        f"  Active projects: {intent.get('active_projects', [])}",
        f"  Open loops: {intent.get('open_loops', [])}",
        f"  Today's deadlines: {intent.get('today_deadlines', [])}",
        f"  Focus mode: {intent.get('focus_mode', 'unknown')}",
        f"  Suggested first action: {intent.get('suggested_first_action', '')}",
        "",
    ]
    if tasks_summary:
        lines.append("Pending/overdue tasks:")
        lines.append(tasks_summary)
        lines.append("")
    if watchdog_state:
        lines.append("Watchdog / alerts status:")
        lines.append(watchdog_state[:800] if len(watchdog_state) > 800 else watchdog_state)
        lines.append("")
    if system_stats:
        disk = system_stats.get("disk_pct")
        batt = system_stats.get("battery_pct")
        if disk is not None:
            lines.append(f"System: disk usage {disk}%.")
        if batt is not None:
            plugged = system_stats.get("battery_plugged", False)
            lines.append(f"Battery: {batt}%" + (" (plugged in)" if plugged else " (on battery)."))
        lines.append("")
    if cron_today:
        lines.append("Scheduled for today:")
        for c in cron_today[:10]:
            lines.append(f"  - {c}")
        lines.append("")

    context = "\n".join(lines).strip()

    system_prompt = (
        "You are A.N.K.I.T.A delivering a brief morning briefing. "
        "Output ONLY the briefing text: no labels, no 'Briefing:', no markdown. "
        "Maximum 150 words. Use short sentences. Sound natural when spoken aloud. "
        "Mention 2–4 concrete items: e.g. one open loop, one deadline, one system note, one suggestion. "
        "End with something like 'Say \"let\'s go\" to start.' or 'Ready when you are.'"
    )
    user_prompt = (
        "Generate the morning briefing based on this context.\n\n"
        "Context:\n" + context
    )

    try:
        from llm import call_chat_once
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = call_chat_once(runtime, messages, tools=None, max_tokens=300)
        out = (response.get("content") or "").strip()
        # Trim to ~150 words if the model over-generated
        words = out.split()
        if len(words) > 160:
            out = " ".join(words[:160]) + "..."
        return out
    except Exception as e:
        print(f"[MorningAgent] LLM failed: {e}", flush=True)
        return ""
