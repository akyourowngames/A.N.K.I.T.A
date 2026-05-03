from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlparse

from tool.date_time import DateTimeTool
from tool.gmail import GmailTool
from tool.google_calendar import GoogleCalendarTool
from tool.local_files import LocalFilesTool
from tool.music import MusicTool
from tool.nvidia_image import NvidiaImageTool
from tool.system_control import SystemControlTool
from tool.tavily_search import TavilySearchTool
from tool.terminal import TerminalTool
from tool.weather import WeatherTool


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: dict[str, str]


class ToolRegistry:
    def __init__(self) -> None:
        self.date_time = DateTimeTool()
        self.tavily_search = TavilySearchTool()
        self.weather = WeatherTool()
        self.system_control = SystemControlTool()
        self.terminal = TerminalTool()
        self.local_files = LocalFilesTool()
        self.music = MusicTool()
        self.image_generation = NvidiaImageTool()
        self.gmail = GmailTool()
        self.google_calendar = GoogleCalendarTool()
        self._planner_text_cache: str | None = None

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="date_time",
                description="Get current date/time, compare timezones, or convert ISO datetimes between timezones.",
                args={
                    "timezone": "Optional source/current IANA timezone. Default: Asia/Kolkata.",
                    "mode": "Optional: now, compare, convert. Default: now.",
                    "target_timezone": "Optional IANA timezone for compare/convert.",
                    "source_time": "Optional ISO datetime for convert, e.g. 2026-05-03T14:30:00.",
                },
            ),
            ToolSpec(
                name="tavily_search",
                description=(
                    "Search the live web for current, recent, future, external, official, or likely-changing "
                    "information, including exam cutoffs/results/admissions, news, prices, schedules, releases, "
                    "rankings, and facts that may be stale. Supports advanced search, news mode, and domain filters."
                ),
                args={
                    "query": "Search query with the user's key terms and context preserved.",
                    "max_results": "Optional integer, default 5.",
                    "search_depth": "Optional: basic or advanced. Default: advanced.",
                    "topic": "Optional: general or news.",
                    "include_domains": "Optional comma/list of domains to prioritize or restrict.",
                    "exclude_domains": "Optional comma/list of domains to exclude.",
                    "include_answer": "Optional boolean, default true.",
                    "days": "Optional recent-news window in days when topic=news.",
                },
            ),
            ToolSpec(
                name="weather",
                description="Get current weather, forecast, hourly outlook, and structured risk advisories for a city or location.",
                args={
                    "location": "City or location. Uses the tool default when omitted.",
                    "mode": "Optional: current, forecast, hourly, full/pro. Default: current.",
                    "days": "Optional forecast days from 1 to 3. Default: 1.",
                    "units": "Optional: metric or imperial. Default: metric.",
                    "include_hourly": "Optional boolean. Include hourly slots with forecast/full output.",
                    "hourly_slots": "Optional hourly rows per day, 1-8. Default: 4.",
                },
            ),
            ToolSpec(
                name="system_control",
                description=(
                    "Control local Windows settings and apps dynamically, including system status, volume, mute/unmute, "
                    "screen/display brightness, Bluetooth/settings pages, URL/path opening, app discovery, and app launching. "
                    "If it fails, terminal fallback is used."
                ),
                args={
                    "action": (
                        "status, get_volume, set_volume, volume_up, volume_down, mute, unmute, toggle_mute, "
                        "get_brightness, set_brightness, brightness_up, brightness_down, open_bluetooth, "
                        "open_settings, open_app, find_app, open_url, open_path, reveal_path, lock_screen. "
                        "Use brightness_up/down or set_brightness for dim/brighten requests."
                    ),
                    "value": (
                        "Optional percent 0-100 for set_volume/set_brightness, or URL/path/settings/app value when target is omitted."
                    ),
                    "target": "Optional settings page, app name, URL, file path, or folder path.",
                    "open_app": "Use for application names, program names, executable commands, and installed app discovery.",
                    "open_url": "Use only for absolute URLs/URIs with a scheme such as https://, mailto:, file:, or ms-settings:.",
                    "amount": "Optional adjustment step for volume_up/down or brightness_up/down. Default 10.",
                    "timeout": "Optional seconds for Windows control commands. Default 90.",
                },
            ),
            ToolSpec(
                name="terminal",
                description="Run unrestricted local terminal commands for installs, downloads, package management, git, diagnostics, scripts, and shell workflows.",
                args={
                    "command": "Command text. Can run package managers, downloads, scripts, git, diagnostics, and shell pipelines.",
                    "cwd": "Optional working directory. Default: current project folder.",
                    "timeout": "Optional seconds, 1-3600. Default: 120.",
                    "shell": "Optional: powershell or cmd. Default: powershell.",
                    "stdin": "Optional standard input text.",
                    "env": "Optional environment variables as an object.",
                    "max_output_chars": "Optional output truncation limit.",
                },
            ),
            ToolSpec(
                name="local_files",
                description="List, tree, search, read, inspect metadata, and find recent local files. All local folders are accessible by default.",
                args={
                    "action": "roots, list, tree, search, read, stat, recent.",
                    "path": "Optional folder or file path. Defaults to the current working folder.",
                    "query": "Search query for file/folder names or file contents.",
                    "max_results": "Optional integer, default 20.",
                    "recursive": "Optional boolean for list/search behavior.",
                    "max_depth": "Optional recursion depth, 1-10.",
                    "include_hidden": "Optional boolean; include hidden dot files/folders.",
                    "file_types": "Optional type group or extension list: image, document, code, text, audio, video, archive, .py, .png.",
                    "sort": "Optional for list: name, type, size, modified.",
                    "search_mode": "Optional for search: name, content, both.",
                },
            ),
            ToolSpec(
                name="music",
                description="Search, play, queue, pause, resume, skip, stop, or check music through yt-dlp and a local player.",
                args={
                    "action": "play, queue, stop, pause, resume, next, status, clear.",
                    "query": "Song, artist, playlist/search text, or supported URL for play/queue.",
                    "url": "Optional direct URL when the user provides one.",
                    "player": "Optional backend override: auto, mpv, ffplay, vlc, browser, custom.",
                    "clear_queue": "Optional boolean for play; clear queued tracks first.",
                },
            ),
            ToolSpec(
                name="image_generation",
                description="Generate an image using NVIDIA image models and save it to an allowed output folder.",
                args={
                    "prompt": "Image description.",
                    "output_path": "Optional output file or folder path.",
                    "size": "Optional image size if supported by the configured NVIDIA model.",
                    "n": "Optional image count, default 1, max 4.",
                    "seed": "Optional integer seed if supported by the configured NVIDIA model.",
                    "open_after_save": "Optional boolean; open generated image files after saving.",
                },
            ),
            ToolSpec(
                name="gmail",
                description="Search, read, thread, draft, reply, send, label, archive, trash, and inspect Gmail email messages.",
                args={
                    "action": (
                        "search/list, read/get, thread/read_thread, draft, send, draft_reply/reply, send_reply, "
                        "labels, profile, mark_read, mark_unread, archive, move_to_inbox, star, unstar, "
                        "modify_labels, trash, untrash."
                    ),
                    "query": "Gmail search query for search/list.",
                    "message_id": "Message id for read/reply/label/trash operations.",
                    "thread_id": "Thread id for thread reads, threaded drafts, or replies when known.",
                    "to": "Recipient email for draft/send, or explicit reply recipient override.",
                    "cc": "Optional Cc recipients for draft/send/reply.",
                    "bcc": "Optional Bcc recipients for draft/send/reply.",
                    "subject": "Email subject for draft/send, or optional reply subject override.",
                    "body": "Email body for draft/send/reply.",
                    "label_ids": "Optional label ids to filter search/list, such as INBOX or UNREAD.",
                    "include_spam_trash": "Optional boolean for Gmail search/list.",
                    "add_labels": "Optional labels for modify_labels.",
                    "remove_labels": "Optional labels for modify_labels.",
                    "max_results": "Optional integer, default 5.",
                },
            ),
            ToolSpec(
                name="google_calendar",
                description="List, search, read, create, update, delete, free/busy-check, and discover Google Calendar events/calendars.",
                args={
                    "action": "list/upcoming/search, get/read, create/add, update/patch/edit, delete/remove, freebusy/availability, calendars/list_calendars.",
                    "calendar_id": "Optional calendar id, default primary.",
                    "query": "Optional search text for list/search.",
                    "summary": "Event title for create/update.",
                    "start": "ISO datetime or date for create/update.",
                    "end": "Optional ISO datetime or date for create/update.",
                    "timezone_name": "Optional IANA timezone, otherwise DEFAULT_TIMEZONE/local default is used.",
                    "location": "Optional event location for create/update.",
                    "description": "Optional event notes for create/update.",
                    "event_id": "Event id for get/update/delete.",
                    "time_min": "Optional ISO lower bound for list/freebusy.",
                    "time_max": "Optional ISO upper bound for list/freebusy.",
                    "attendees": "Optional attendee emails as list or comma/semicolon/newline separated text.",
                    "all_day": "Optional boolean for all-day event create/update.",
                    "recurrence": "Optional recurrence rules, such as RRULE:FREQ=WEEKLY;COUNT=4.",
                    "reminders": "Optional reminder minutes as list or comma/semicolon/newline separated text.",
                    "reminders_minutes": "Optional alias for reminders.",
                    "max_results": "Optional integer, default 10.",
                },
            ),
        ]

    def planner_text(self) -> str:
        if self._planner_text_cache is not None:
            return self._planner_text_cache
        lines = []
        for spec in self.specs():
            lines.append(
                json.dumps(
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "args": spec.args,
                    },
                    ensure_ascii=False,
                )
            )
        self._planner_text_cache = "\n".join(lines)
        return self._planner_text_cache

    def run(self, name: str, args: dict[str, Any] | None = None) -> str:
        args = args or {}
        try:
            if name == "date_time":
                timezone = str(args.get("timezone") or "Asia/Kolkata")
                return self.date_time.run(
                    timezone=timezone,
                    mode=str(args.get("mode") or "now"),
                    target_timezone=str(args.get("target_timezone") or args.get("target") or ""),
                    source_time=str(args.get("source_time") or args.get("time") or ""),
                )
            if name == "tavily_search":
                query = str(args.get("query") or "").strip()
                return self.tavily_search.run(
                    query=query,
                    max_results=args.get("max_results") or 5,
                    search_depth=str(args.get("search_depth") or "advanced"),
                    topic=str(args.get("topic") or "general"),
                    include_domains=args.get("include_domains"),
                    exclude_domains=args.get("exclude_domains"),
                    include_answer=self._optional_bool(args.get("include_answer")) if args.get("include_answer") not in (None, "") else True,
                    include_raw_content=self._optional_bool(args.get("include_raw_content")) or False,
                    days=args.get("days"),
                )
            if name == "weather":
                return self.weather.run(
                    location=str(args.get("location") or ""),
                    mode=str(args.get("mode") or args.get("action") or "current"),
                    days=args.get("days") or 1,
                    units=str(args.get("units") or "metric"),
                    include_hourly=self._optional_bool(args.get("include_hourly")),
                    hourly_slots=args.get("hourly_slots") or args.get("hours") or 4,
                )
            if name == "system_control":
                action = str(args.get("action") or "")
                value = args.get("value")
                target = str(args.get("target") or args.get("query") or "") or None
                amount = args.get("amount")
                if action == "open_url" and target and not self._is_absolute_uri(target):
                    action = "open_app"
                try:
                    result = self.system_control.run(
                        action=action,
                        value=value,
                        target=target,
                        amount=amount,
                        timeout=args.get("timeout"),
                    )
                except TypeError:
                    result = self.system_control.run(action=action, value=value, target=target)
                if result.startswith("FAILED:") and "FALLBACK_COMMAND:" in result:
                    fallback_command = result.split("FALLBACK_COMMAND:", 1)[1].strip()
                    fallback_result = self.terminal.run(fallback_command)
                    return f"{result}\n\nTerminal fallback result:\n{fallback_result}"
                return result
            if name == "terminal":
                command = str(args.get("command") or "")
                cwd = str(args.get("cwd") or "") or None
                env = args.get("env") if isinstance(args.get("env"), dict) else None
                return self.terminal.run(
                    command=command,
                    cwd=cwd,
                    timeout=args.get("timeout") or 120,
                    shell=str(args.get("shell") or "powershell"),
                    stdin=str(args.get("stdin") or ""),
                    env=env,
                    max_output_chars=args.get("max_output_chars"),
                )
            if name == "local_files":
                return self.local_files.run(
                    action=str(args.get("action") or "roots"),
                    path=str(args.get("path") or ""),
                    query=str(args.get("query") or ""),
                    max_results=args.get("max_results") or 20,
                    recursive=self._optional_bool(args.get("recursive")),
                    max_depth=args.get("max_depth") or 2,
                    include_hidden=self._optional_bool(args.get("include_hidden")) or False,
                    file_types=str(args.get("file_types") or args.get("type") or ""),
                    sort=str(args.get("sort") or "name"),
                    search_mode=str(args.get("search_mode") or "name"),
                    preview_chars=args.get("preview_chars") or 220,
                )
            if name == "music":
                return self.music.run(
                    action=str(args.get("action") or "play"),
                    query=str(args.get("query") or ""),
                    url=str(args.get("url") or ""),
                    player=str(args.get("player") or ""),
                    clear_queue=self._optional_bool(args.get("clear_queue")),
                )
            if name == "image_generation":
                seed_value = args.get("seed")
                seed = int(seed_value) if seed_value not in (None, "") else None
                return self.image_generation.run(
                    prompt=str(args.get("prompt") or ""),
                    output_path=str(args.get("output_path") or ""),
                    size=str(args.get("size") or ""),
                    n=int(args.get("n") or 1),
                    seed=seed,
                    open_after_save=self._optional_bool(args.get("open_after_save")),
                )
            if name == "gmail":
                return self.gmail.run(
                    action=str(args.get("action") or "search"),
                    query=str(args.get("query") or ""),
                    to=str(args.get("to") or ""),
                    subject=str(args.get("subject") or ""),
                    body=str(args.get("body") or ""),
                    message_id=str(args.get("message_id") or ""),
                    max_results=args.get("max_results") or 5,
                    cc=str(args.get("cc") or ""),
                    bcc=str(args.get("bcc") or ""),
                    thread_id=str(args.get("thread_id") or ""),
                    label_ids=args.get("label_ids"),
                    include_spam_trash=self._optional_bool(args.get("include_spam_trash")),
                    add_labels=args.get("add_labels"),
                    remove_labels=args.get("remove_labels"),
                )
            if name == "google_calendar":
                return self.google_calendar.run(
                    action=str(args.get("action") or "list"),
                    calendar_id=str(args.get("calendar_id") or "primary"),
                    query=str(args.get("query") or ""),
                    summary=str(args.get("summary") or ""),
                    start=str(args.get("start") or ""),
                    end=str(args.get("end") or ""),
                    timezone_name=str(args.get("timezone_name") or ""),
                    location=str(args.get("location") or ""),
                    description=str(args.get("description") or ""),
                    event_id=str(args.get("event_id") or ""),
                    max_results=args.get("max_results") or 10,
                    time_min=str(args.get("time_min") or ""),
                    time_max=str(args.get("time_max") or ""),
                    attendees=args.get("attendees"),
                    all_day=self._optional_bool(args.get("all_day")) or False,
                    recurrence=args.get("recurrence"),
                    reminders=args.get("reminders"),
                    reminders_minutes=args.get("reminders_minutes"),
                )
        except Exception as error:
            return f"Tool error: {error}"

        return f"Unknown tool: {name}"

    def run_stream(self, name: str, args: dict[str, Any] | None = None) -> Iterator[str]:
        args = args or {}
        if name == "image_generation":
            seed_value = args.get("seed")
            seed = int(seed_value) if seed_value not in (None, "") else None
            result = yield from self.image_generation.run_stream(
                prompt=str(args.get("prompt") or ""),
                output_path=str(args.get("output_path") or ""),
                size=str(args.get("size") or ""),
                n=int(args.get("n") or 1),
                seed=seed,
                open_after_save=self._optional_bool(args.get("open_after_save")),
            )
            return result

        yield self.run(name, args)

    @staticmethod
    def _optional_bool(value: Any) -> bool | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _is_absolute_uri(value: str) -> bool:
        parsed = urlparse(str(value or "").strip())
        return bool(parsed.scheme and len(parsed.scheme) > 1)
