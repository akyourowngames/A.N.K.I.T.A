from __future__ import annotations

import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


def detect_chrome_path(configured_path: str = "") -> str:
    candidates = [
        configured_path.strip(),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return ""


class BrowserTool(Tool):
    name = "browser"
    public = True
    description = (
        "Internal Chrome helper for navigation, search, page inspection, tab control, result opening, and media playback control."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "focus",
                    "open_url",
                    "search",
                    "status",
                    "inspect",
                    "open_result",
                    "play_pause",
                    "commit_address_bar",
                    "dismiss_address_bar",
                    "back",
                    "forward",
                    "refresh",
                    "close_tab",
                    "wait_for_text",
                ],
                "description": "Browser action.",
            },
            "url": {"type": "string", "description": "URL to open."},
            "query": {"type": "string", "description": "Target query or identity phrase for search/inspect actions."},
            "text": {"type": "string", "description": "Expected page text for action=wait_for_text."},
            "engine": {
                "type": "string",
                "enum": ["web", "news", "youtube"],
                "description": "Search engine flavor for action=search. Default web.",
            },
            "new_window": {"type": "boolean", "description": "Whether to force a new Chrome window."},
            "result_index": {"type": "integer", "description": "0-based result index for action=open_result."},
            "timeout_seconds": {"type": "number", "description": "Wait timeout for action=wait_for_text. Default 10."},
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    _QUERY_STOPWORDS = {
        "a",
        "an",
        "and",
        "for",
        "from",
        "in",
        "me",
        "music",
        "my",
        "on",
        "play",
        "playing",
        "search",
        "show",
        "song",
        "the",
        "to",
        "video",
        "watch",
        "youtube",
    }

    def __init__(
        self,
        tools: ToolRegistry,
        chrome_path: str = "",
        *,
        backend: str = "native",
        user_data_dir: str = "",
    ) -> None:
        self.tools = tools
        self.chrome_path = detect_chrome_path(chrome_path)
        self.backend = backend.strip().lower() or "native"
        self.playwright_user_data_dir = Path(user_data_dir).resolve() if user_data_dir else (Path.cwd() / "data" / "playwright_chrome").resolve()
        self._pw = None
        self._pw_context = None
        self._pw_page = None
        self._pw_error = ""

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("new_window", False)
        args.setdefault("engine", "web")
        args.setdefault("result_index", 0)
        args.setdefault("timeout_seconds", 10)
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "")).strip()
        if action == "focus":
            return self._focus_existing()
        if action == "open_url":
            return self._open_url(str(args.get("url", "")).strip(), new_window=bool(args.get("new_window", False)))
        if action == "search":
            return self._search(
                str(args.get("query", "")).strip(),
                engine=str(args.get("engine", "web")).strip() or "web",
                new_window=bool(args.get("new_window", False)),
            )
        if action == "status":
            return self._status()
        if action == "inspect":
            return self._inspect(query=str(args.get("query", "")).strip())
        if action == "open_result":
            return self._open_result(int(args.get("result_index", 0)))
        if action == "play_pause":
            return self._play_pause(query=str(args.get("query", "")).strip())
        if action == "commit_address_bar":
            return self._commit_address_bar(query=str(args.get("query", "")).strip())
        if action == "dismiss_address_bar":
            return self._dismiss_address_bar(query=str(args.get("query", "")).strip())
        if action == "back":
            return self._history(direction="back")
        if action == "forward":
            return self._history(direction="forward")
        if action == "refresh":
            return self._refresh(query=str(args.get("query", "")).strip())
        if action == "close_tab":
            return self._close_tab()
        if action == "wait_for_text":
            return self._wait_for_text(
                text=str(args.get("text", "")).strip(),
                query=str(args.get("query", "")).strip(),
                timeout_seconds=float(args.get("timeout_seconds", 10)),
            )
        return ToolResult(ok=False, summary=f"Unknown browser action: {action}", data={}, error="unknown_action")

    def _wants_playwright(self) -> bool:
        return self.backend in {"playwright", "auto"}

    def _playwright_page(self):
        if not self._wants_playwright():
            return None
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            self._pw_error = f"Playwright is not installed: {exc}"
            return None

        try:
            if self._pw is None:
                self._pw = sync_playwright().start()
            if self._pw_context is None:
                self.playwright_user_data_dir.mkdir(parents=True, exist_ok=True)
                launch_kwargs: dict[str, Any] = {
                    "headless": False,
                    "args": ["--start-maximized", "--disable-blink-features=AutomationControlled"],
                }
                if self.chrome_path:
                    launch_kwargs["executable_path"] = self.chrome_path
                self._pw_context = self._pw.chromium.launch_persistent_context(
                    str(self.playwright_user_data_dir),
                    **launch_kwargs,
                )
                self._pw_context.set_default_timeout(7000)
                self._pw_page = self._pw_context.pages[0] if self._pw_context.pages else self._pw_context.new_page()
            if self._pw_page is None or self._pw_page.is_closed():
                self._pw_page = self._pw_context.new_page()
            return self._pw_page
        except Exception as exc:  # noqa: BLE001
            self._pw_error = str(exc)
            return None

    def _playwright_active(self) -> bool:
        return self._pw_page is not None and not self._pw_page.is_closed()

    def _pw_goto(self, url: str, *, query: str = "") -> ToolResult | None:
        page = self._playwright_page()
        if page is None:
            return None
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            self._pw_handle_common_overlays(page)
            return self._pw_inspect(query=query)
        except Exception as exc:  # noqa: BLE001
            self._pw_error = str(exc)
            return ToolResult(ok=False, summary=f"Playwright navigation failed: {exc}", data={"automation_backend": "playwright"}, error="playwright_navigation_failed")

    def _pw_focus(self) -> ToolResult | None:
        page = self._playwright_page()
        if page is None:
            return None
        try:
            page.bring_to_front()
            return ToolResult(ok=True, summary=f"Focused Playwright Chrome page: {page.title() or page.url}", data=self._pw_status_payload(page))
        except Exception as exc:  # noqa: BLE001
            self._pw_error = str(exc)
            return None

    def _pw_status_payload(self, page) -> dict[str, Any]:
        title = ""
        url = ""
        try:
            title = page.title()
            url = page.url
        except Exception:
            pass
        active_title = f"{title} - Google Chrome" if title else "Google Chrome"
        return {
            "automation_backend": "playwright",
            "playwright_controlled": True,
            "has_chrome_window": True,
            "chrome_titles": [active_title],
            "active_title": active_title,
            "active_browser_title": active_title,
            "is_browser_foreground": True,
            "chrome_path": self.chrome_path,
            "current_url": url,
        }

    def _pw_status(self) -> ToolResult | None:
        if not self._playwright_active():
            return None
        page = self._playwright_page()
        if page is None:
            return None
        payload = self._pw_status_payload(page)
        return ToolResult(ok=True, summary="1 Playwright-controlled Chrome page detected.", data=payload)

    def _pw_inspect(self, query: str = "") -> ToolResult | None:
        page = self._playwright_page()
        if page is None:
            return None
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            title = page.title()
            current_url = page.url
            body_text = ""
            try:
                body_text = page.locator("body").inner_text(timeout=2500)
            except Exception:
                body_text = ""
            page_state = self._derive_page_state(
                active_title=f"{title} - Google Chrome" if title else "Google Chrome",
                current_url=current_url,
                ocr_text=body_text,
                query=query,
            )
            video = self._pw_video_state(page)
            if video:
                page_state["media_position_seconds"] = int(float(video.get("current_time", 0)))
                if video.get("paused") is False:
                    page_state["playback_ui_state"] = "playing"
                elif page_state.get("page_kind") == "youtube_watch":
                    page_state["playback_ui_state"] = "paused"
            payload = {**self._pw_status_payload(page), **page_state}
            payload["query"] = query
            payload["current_url"] = current_url
            payload["ocr_text"] = body_text[:2000]
            summary = self._inspect_summary(payload)
            return ToolResult(ok=True, summary=summary, data=payload)
        except Exception as exc:  # noqa: BLE001
            self._pw_error = str(exc)
            return ToolResult(ok=False, summary=f"Playwright inspection failed: {exc}", data={"automation_backend": "playwright"}, error="playwright_inspect_failed")

    def _pw_open_result(self, result_index: int) -> ToolResult | None:
        page = self._playwright_page()
        if page is None:
            return None
        inspect = self._pw_inspect()
        if not inspect or not inspect.ok:
            return inspect
        page_kind = str(inspect.data.get("page_kind", "")).strip()
        try:
            href = ""
            if page_kind == "youtube_search_results":
                href = self._pw_nth_href(page, "a[href*='/watch']", result_index, require=lambda item: "/watch" in item and "shorts" not in item)
            elif page_kind == "google_search_results":
                href = self._pw_nth_href(page, "a:has(h3)", result_index)
            else:
                return ToolResult(
                    ok=False,
                    summary="Playwright open_result works only from a recognized search results page.",
                    data=inspect.data,
                    error="wrong_page_kind",
                )
            if not href:
                return ToolResult(ok=False, summary="No clickable browser result was found.", data=inspect.data, error="result_not_found")
            page.goto(href, wait_until="domcontentloaded", timeout=20000)
            self._pw_handle_common_overlays(page)
            after = self._pw_inspect()
            if after:
                after.summary = f"Opened browser result #{result_index + 1} with Playwright."
                after.data["result_index"] = result_index
                return after
        except Exception as exc:  # noqa: BLE001
            self._pw_error = str(exc)
            return ToolResult(ok=False, summary=f"Playwright result opening failed: {exc}", data=inspect.data, error="playwright_result_failed")
        return None

    def _pw_play_pause(self, query: str = "") -> ToolResult | None:
        page = self._playwright_page()
        if page is None:
            return None
        try:
            page.bring_to_front()
            self._pw_handle_common_overlays(page)
            before = self._pw_video_state(page) or {}
            if before and before.get("paused") is False:
                inspect = self._pw_inspect(query=query)
                if inspect:
                    inspect.summary = "Playback appears active."
                    inspect.data["playback_ui_state"] = "playing"
                    return inspect

            try:
                page.locator("video").first.click(timeout=5000)
            except Exception:
                page.keyboard.press("k")
            try:
                page.evaluate(
                    """async () => {
                        const video = document.querySelector('video');
                        if (!video) return false;
                        video.muted = false;
                        try { await video.play(); } catch (error) {}
                        return !video.paused;
                    }"""
                )
            except Exception:
                pass
            time.sleep(1.2)
            after_state = self._pw_video_state(page) or {}
            inspect = self._pw_inspect(query=query)
            if inspect:
                before_time = float(before.get("current_time", 0) or 0)
                after_time = float(after_state.get("current_time", 0) or 0)
                if after_state.get("paused") is False or after_time > before_time + 0.5:
                    inspect.summary = "Playback appears active."
                    inspect.data["playback_ui_state"] = "playing"
                else:
                    inspect.summary = "Playback was requested but is not yet proven active."
                return inspect
        except Exception as exc:  # noqa: BLE001
            self._pw_error = str(exc)
            return ToolResult(ok=False, summary=f"Playwright playback control failed: {exc}", data={"automation_backend": "playwright"}, error="playwright_playback_failed")
        return None

    @staticmethod
    def _pw_nth_href(page, selector: str, index: int, require=None) -> str:
        hrefs = page.locator(selector).evaluate_all("(nodes) => nodes.map((node) => node.href || node.getAttribute('href') || '')")
        cleaned: list[str] = []
        for href in hrefs:
            item = str(href).strip()
            if not item or item.startswith(("javascript:", "#")):
                continue
            if require and not require(item):
                continue
            cleaned.append(item)
        if not cleaned:
            return ""
        return cleaned[min(max(index, 0), len(cleaned) - 1)]

    @staticmethod
    def _pw_video_state(page) -> dict[str, Any] | None:
        try:
            state = page.evaluate(
                """() => {
                    const video = document.querySelector('video');
                    if (!video) return null;
                    return {
                        paused: video.paused,
                        current_time: video.currentTime || 0,
                        duration: Number.isFinite(video.duration) ? video.duration : 0,
                        ready_state: video.readyState
                    };
                }"""
            )
            return state if isinstance(state, dict) else None
        except Exception:
            return None

    @staticmethod
    def _pw_handle_common_overlays(page) -> None:
        patterns = [
            re.compile(r"^(accept all|i agree|agree|accept)$", re.IGNORECASE),
            re.compile(r"^(no thanks|not now|skip|continue)$", re.IGNORECASE),
        ]
        for pattern in patterns:
            try:
                button = page.get_by_role("button", name=pattern).first
                if button.count():
                    button.click(timeout=1200)
                    time.sleep(0.3)
                    return
            except Exception:
                continue

    def _search(self, query: str, *, engine: str, new_window: bool) -> ToolResult:
        if not query:
            return ToolResult(ok=False, summary="Browser search query is required.", data={}, error="missing_query")
        encoded = urllib.parse.quote_plus(query)
        engine_name = engine.lower()
        if engine_name == "youtube":
            url = f"https://www.youtube.com/results?search_query={encoded}"
        elif engine_name == "news":
            url = f"https://www.google.com/search?tbm=nws&q={encoded}"
        else:
            url = f"https://www.google.com/search?q={encoded}"
            engine_name = "web"
        playwright_result = self._pw_goto(url, query=query)
        if playwright_result is not None:
            if playwright_result.ok:
                playwright_result.summary = f"Searched {engine_name} for: {query}"
                playwright_result.data["query"] = query
                playwright_result.data["engine"] = engine_name
            return playwright_result
        result = self._open_url(url, new_window=new_window)
        if result.ok:
            result.summary = f"Searched {engine_name} for: {query}"
            result.data["query"] = query
            result.data["engine"] = engine_name
        return result

    def _open_url(self, url: str, *, new_window: bool) -> ToolResult:
        if not url:
            return ToolResult(ok=False, summary="Browser URL is required.", data={}, error="missing_url")
        playwright_result = self._pw_goto(url, query="")
        if playwright_result is not None:
            if playwright_result.ok:
                playwright_result.summary = f"Opened URL with Playwright: {url}"
                playwright_result.data["url"] = url
                playwright_result.data["used_existing_window"] = False
            return playwright_result
        existing = self._status()
        if existing.ok and existing.data.get("has_chrome_window") and not new_window:
            focus = self._focus_existing()
            if not focus.ok:
                return focus
            if not self._navigate_in_focused_chrome(url):
                return ToolResult(ok=False, summary="Failed to navigate in focused Chrome window.", data={}, error="navigation_failed")
            inspect = self._inspect()
            if inspect.ok:
                inspect.summary = f"Opened URL in existing Chrome: {url}"
                inspect.data["url"] = url
                inspect.data["used_existing_window"] = True
                return inspect
            return ToolResult(ok=True, summary=f"Opened URL in existing Chrome: {url}", data={"url": url, "used_existing_window": True})

        if not self.chrome_path:
            return ToolResult(
                ok=False,
                summary="Chrome executable not found. Set JAKATA_CHROME_PATH or install Chrome in the default location.",
                data={},
                error="missing_browser",
            )
        quoted_path = self.chrome_path.replace('"', '""')
        quoted_url = url.replace('"', '""')
        command = f'Start-Process -FilePath "{quoted_path}" -ArgumentList "--new-window","{quoted_url}"'
        launched = self.tools.execute("shell", {"command": f'powershell -NoProfile -Command "{command}"'})
        if not launched.ok:
            return ToolResult(ok=False, summary=launched.summary, data=launched.data, error=launched.error or "launch_failed")
        time.sleep(2.0)
        inspect = self._inspect()
        if inspect.ok:
            inspect.summary = f"Launched Chrome with URL: {url}"
            inspect.data["url"] = url
            inspect.data["used_existing_window"] = False
            inspect.data["chrome_path"] = self.chrome_path
            return inspect
        return ToolResult(ok=True, summary=f"Launched Chrome with URL: {url}", data={"url": url, "used_existing_window": False, "chrome_path": self.chrome_path})

    def _focus_existing(self) -> ToolResult:
        playwright_result = self._pw_focus()
        if playwright_result is not None:
            return playwright_result
        listing = self._status()
        if not listing.ok or not listing.data.get("has_chrome_window"):
            return ToolResult(ok=False, summary="No Chrome window is open.", data=listing.data if listing.ok else {}, error="window_not_found")
        focus = self.tools.execute("window", {"action": "focus", "title": "Chrome"})
        if not focus.ok:
            return ToolResult(ok=False, summary=focus.summary, data=focus.data, error=focus.error)
        time.sleep(0.5)
        active = self.tools.execute("window", {"action": "active"})
        title = str(active.data.get("title", "")) if active.ok else ""
        payload = {"title": title}
        if active.ok:
            for key in ("left", "top", "width", "height", "right", "bottom"):
                if key in active.data:
                    payload[key] = active.data[key]
        return ToolResult(ok=True, summary=f"Focused Chrome window: {title or 'Chrome'}", data=payload)

    def _status(self) -> ToolResult:
        playwright_result = self._pw_status()
        if playwright_result is not None:
            return playwright_result
        windows = self.tools.execute("window", {"action": "list"})
        active = self.tools.execute("window", {"action": "active"})
        chrome_titles: list[str] = []
        if windows.ok:
            titles = windows.data.get("windows", [])
            if isinstance(titles, list):
                chrome_titles = [str(title) for title in titles if "chrome" in str(title).lower()]
        active_title = str(active.data.get("title", "")) if active.ok else ""
        active_browser_title = active_title if "chrome" in active_title.lower() else ""
        payload = {
            "has_chrome_window": bool(chrome_titles),
            "chrome_titles": chrome_titles,
            "active_title": active_title,
            "active_browser_title": active_browser_title,
            "is_browser_foreground": bool(active_browser_title),
            "chrome_path": self.chrome_path,
        }
        if active.ok:
            for key in ("left", "top", "width", "height", "right", "bottom"):
                if key in active.data:
                    payload[key] = active.data[key]
        return ToolResult(ok=True, summary=f"{len(chrome_titles)} Chrome window(s) detected.", data=payload)

    def _inspect(self, query: str = "") -> ToolResult:
        playwright_result = self._pw_inspect(query=query)
        if playwright_result is not None:
            return playwright_result
        status = self._status()
        if not status.ok:
            return status
        current_url = self._read_current_url() if status.data.get("has_chrome_window") else ""
        ocr_text = self._read_browser_ocr() if status.data.get("has_chrome_window") else ""
        page_state = self._derive_page_state(
            active_title=str(status.data.get("active_title", "")),
            current_url=current_url,
            ocr_text=ocr_text,
            query=query,
        )
        payload = {**status.data, **page_state}
        payload["query"] = query
        payload["current_url"] = current_url
        payload["ocr_text"] = ocr_text[:2000]
        summary = self._inspect_summary(payload)
        return ToolResult(ok=True, summary=summary, data=payload)

    def _open_result(self, result_index: int) -> ToolResult:
        playwright_result = self._pw_open_result(result_index)
        if playwright_result is not None:
            return playwright_result
        inspect = self._inspect()
        if not inspect.ok:
            return inspect
        page_kind = str(inspect.data.get("page_kind", "")).strip()
        if inspect.data.get("address_bar_focused"):
            self.tools.execute("keyboard", {"action": "press", "keys": "esc"})
            time.sleep(0.2)
            inspect = self._inspect()
            if not inspect.ok:
                return inspect
            page_kind = str(inspect.data.get("page_kind", "")).strip()
        bounds = self._window_bounds(inspect.data)
        if not bounds:
            return ToolResult(ok=False, summary="Browser result opening needs active window bounds.", data=inspect.data, error="missing_bounds")
        if page_kind == "youtube_search_results":
            x = bounds["left"] + int(bounds["width"] * 0.42)
            y = bounds["top"] + 255 + max(result_index, 0) * 180
        elif page_kind == "google_search_results":
            x = bounds["left"] + int(bounds["width"] * 0.34)
            y = bounds["top"] + 245 + max(result_index, 0) * 150
        else:
            return ToolResult(
                ok=False,
                summary="Browser open_result works only from a recognized search results page.",
                data=inspect.data,
                error="wrong_page_kind",
            )

        after: ToolResult | None = None
        candidate_points = [
            (x, y),
            (bounds["left"] + int(bounds["width"] * 0.48), y + 35),
            (bounds["left"] + int(bounds["width"] * 0.28), y + 70),
        ]
        for candidate_x, candidate_y in candidate_points:
            move = self.tools.execute("mouse", {"action": "move", "x": candidate_x, "y": candidate_y, "duration": 0.1})
            if not move.ok:
                return ToolResult(ok=False, summary=move.summary, data=inspect.data, error=move.error or "mouse_move_failed")
            click = self.tools.execute("mouse", {"action": "click", "x": candidate_x, "y": candidate_y})
            if not click.ok:
                return ToolResult(ok=False, summary=click.summary, data=inspect.data, error=click.error or "mouse_click_failed")
            time.sleep(2.0)
            after = self._inspect()
            if after.ok and str(after.data.get("page_kind", "")).strip() != page_kind:
                break
        if after.ok:
            after.summary = f"Opened browser result #{result_index + 1}."
            after.data["result_index"] = result_index
            return after
        return ToolResult(ok=True, summary=f"Opened browser result #{result_index + 1}.", data={"result_index": result_index})

    def _play_pause(self, query: str = "") -> ToolResult:
        playwright_result = self._pw_play_pause(query=query)
        if playwright_result is not None:
            return playwright_result
        focus = self._focus_existing()
        if not focus.ok:
            return focus
        before = self._inspect(query=query)
        if before.ok and before.data.get("address_bar_focused"):
            self.tools.execute("keyboard", {"action": "press", "keys": "esc"})
            time.sleep(0.2)
        attempt = self.tools.execute("keyboard", {"action": "press", "keys": "k"})
        if not attempt.ok:
            return ToolResult(ok=False, summary=attempt.summary, data={}, error=attempt.error or "keyboard_failed")
        time.sleep(0.8)
        inspect = self._inspect(query=query)
        if inspect.ok and inspect.data.get("playback_ui_state") == "playing":
            inspect.summary = "Playback appears active."
            return inspect

        bounds = self._window_bounds(inspect.data if inspect.ok else focus.data)
        if bounds:
            player_x = bounds["left"] + int(bounds["width"] * 0.50)
            player_y = bounds["top"] + int(bounds["height"] * 0.38)
            click = self.tools.execute("mouse", {"action": "click", "x": player_x, "y": player_y})
            if click.ok:
                self.tools.execute("keyboard", {"action": "press", "keys": "k"})
                time.sleep(0.8)
        after = self._inspect(query=query)
        if after.ok and after.data.get("page_kind") == "youtube_watch" and after.data.get("playback_ui_state") != "playing":
            before_position = after.data.get("media_position_seconds")
            time.sleep(1.8)
            later = self._inspect(query=query)
            if later.ok:
                later_position = later.data.get("media_position_seconds")
                if isinstance(before_position, int) and isinstance(later_position, int) and later_position > before_position:
                    later.data["playback_ui_state"] = "playing"
                    later.summary = "Playback appears active."
                    return later
                after = later
        if after.ok:
            after.summary = (
                "Playback appears active." if after.data.get("playback_ui_state") == "playing" else "Playback was toggled but is not yet proven active."
            )
            return after
        return ToolResult(ok=False, summary="Playback toggle failed.", data={}, error="playback_not_verified")

    def _commit_address_bar(self, query: str = "") -> ToolResult:
        if self._playwright_active():
            inspect = self._pw_inspect(query=query)
            if inspect is not None:
                inspect.summary = "Playwright browser has no address bar focus to commit."
                inspect.data["action"] = "commit_address_bar"
                return inspect
        focus = self._focus_existing()
        if not focus.ok:
            return focus
        pressed = self.tools.execute("keyboard", {"action": "press", "keys": "enter"})
        if not pressed.ok:
            return ToolResult(ok=False, summary=pressed.summary, data={}, error=pressed.error or "keyboard_failed")
        time.sleep(1.5)
        inspect = self._inspect(query=query)
        if inspect.ok:
            inspect.summary = "Committed the address bar input."
            inspect.data["action"] = "commit_address_bar"
            return inspect
        return ToolResult(ok=True, summary="Committed the address bar input.", data={"action": "commit_address_bar"})

    def _dismiss_address_bar(self, query: str = "") -> ToolResult:
        if self._playwright_active():
            inspect = self._pw_inspect(query=query)
            if inspect is not None:
                inspect.summary = "Playwright browser focus is already page-controlled."
                inspect.data["action"] = "dismiss_address_bar"
                return inspect
        focus = self._focus_existing()
        if not focus.ok:
            return focus
        pressed = self.tools.execute("keyboard", {"action": "press", "keys": "esc"})
        if not pressed.ok:
            return ToolResult(ok=False, summary=pressed.summary, data={}, error=pressed.error or "keyboard_failed")
        time.sleep(0.4)
        inspect = self._inspect(query=query)
        if inspect.ok:
            inspect.summary = "Returned browser focus to the page."
            inspect.data["action"] = "dismiss_address_bar"
            return inspect
        return ToolResult(ok=True, summary="Returned browser focus to the page.", data={"action": "dismiss_address_bar"})

    def _history(self, *, direction: str) -> ToolResult:
        if direction not in {"back", "forward"}:
            return ToolResult(ok=False, summary=f"Unknown browser history action: {direction}", data={}, error="unknown_action")
        if self._playwright_active():
            page = self._playwright_page()
            if page is not None:
                try:
                    if direction == "back":
                        page.go_back(wait_until="domcontentloaded", timeout=15000)
                    else:
                        page.go_forward(wait_until="domcontentloaded", timeout=15000)
                    self._pw_handle_common_overlays(page)
                    inspect = self._pw_inspect()
                    if inspect is not None:
                        inspect.summary = f"Went {direction} in Chrome."
                        inspect.data["action"] = direction
                        return inspect
                except Exception as exc:  # noqa: BLE001
                    self._pw_error = str(exc)
                    return ToolResult(
                        ok=False,
                        summary=f"Playwright {direction} navigation failed: {exc}",
                        data={"automation_backend": "playwright"},
                        error=f"playwright_{direction}_failed",
                    )
        shortcut = "alt+left" if direction == "back" else "alt+right"
        return self._native_shortcut_navigation(shortcut=shortcut, summary=f"Went {direction} in Chrome.", action=direction)

    def _refresh(self, query: str = "") -> ToolResult:
        if self._playwright_active():
            page = self._playwright_page()
            if page is not None:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=20000)
                    self._pw_handle_common_overlays(page)
                    inspect = self._pw_inspect(query=query)
                    if inspect is not None:
                        inspect.summary = "Refreshed Chrome."
                        inspect.data["action"] = "refresh"
                        return inspect
                except Exception as exc:  # noqa: BLE001
                    self._pw_error = str(exc)
                    return ToolResult(
                        ok=False,
                        summary=f"Playwright refresh failed: {exc}",
                        data={"automation_backend": "playwright"},
                        error="playwright_refresh_failed",
                    )
        return self._native_shortcut_navigation(shortcut="f5", summary="Refreshed Chrome.", action="refresh", query=query)

    def _close_tab(self) -> ToolResult:
        if self._playwright_active():
            page = self._playwright_page()
            if page is not None:
                try:
                    page.close()
                    if self._pw_context is not None:
                        remaining = [item for item in self._pw_context.pages if not item.is_closed()]
                        self._pw_page = remaining[0] if remaining else None
                    status = self._pw_status()
                    if status is not None and status.ok:
                        status.summary = "Closed the current Chrome tab."
                        status.data["action"] = "close_tab"
                        return status
                    return ToolResult(ok=True, summary="Closed the current Chrome tab.", data={"action": "close_tab"})
                except Exception as exc:  # noqa: BLE001
                    self._pw_error = str(exc)
                    return ToolResult(
                        ok=False,
                        summary=f"Playwright close_tab failed: {exc}",
                        data={"automation_backend": "playwright"},
                        error="playwright_close_tab_failed",
                    )
        return self._native_shortcut_navigation(shortcut="ctrl+w", summary="Closed the current Chrome tab.", action="close_tab", settle_seconds=0.5)

    def _wait_for_text(self, *, text: str, query: str = "", timeout_seconds: float = 10.0) -> ToolResult:
        if not text:
            return ToolResult(ok=False, summary="Browser wait_for_text requires text.", data={}, error="missing_text")
        deadline = time.time() + max(0.5, min(timeout_seconds, 60.0))
        expected = text.lower()
        last: ToolResult | None = None
        while time.time() <= deadline:
            last = self._inspect(query=query)
            if last.ok:
                haystack = "\n".join(
                    [
                        str(last.data.get("active_title", "")),
                        str(last.data.get("current_url", "")),
                        str(last.data.get("ocr_text", "")),
                    ]
                ).lower()
                if expected in haystack:
                    last.summary = f"Observed browser text: {text}"
                    last.data["action"] = "wait_for_text"
                    last.data["text"] = text
                    return last
            time.sleep(0.8)
        return ToolResult(
            ok=False,
            summary=f"Timed out waiting for browser text: {text}",
            data={**(last.data if last and isinstance(last.data, dict) else {}), "action": "wait_for_text", "text": text},
            error="timeout",
        )

    def _native_shortcut_navigation(
        self,
        *,
        shortcut: str,
        summary: str,
        action: str,
        query: str = "",
        settle_seconds: float = 1.1,
    ) -> ToolResult:
        focus = self._focus_existing()
        if not focus.ok:
            return focus
        keyboard_action = "hotkey" if "+" in shortcut else "press"
        pressed = self.tools.execute("keyboard", {"action": keyboard_action, "keys": shortcut})
        if not pressed.ok:
            return ToolResult(ok=False, summary=pressed.summary, data={}, error=pressed.error or "keyboard_failed")
        time.sleep(max(0.1, settle_seconds))
        inspect = self._inspect(query=query)
        if inspect.ok:
            inspect.summary = summary
            inspect.data["action"] = action
            return inspect
        return ToolResult(ok=True, summary=summary, data={"action": action})

    def _navigate_in_focused_chrome(self, url: str) -> bool:
        clipboard = self.tools.execute("clipboard", {"action": "write", "text": url})
        if not clipboard.ok:
            return False
        sequence = self.tools.execute(
            "keyboard",
            {
                "action": "sequence",
                "steps": [
                    {"action": "hotkey", "keys": "ctrl+l"},
                    {"action": "hotkey", "keys": "ctrl+v", "delay": 0.1},
                    {"action": "press", "keys": "enter", "delay": 0.1},
                ],
            },
        )
        if not sequence.ok:
            return False
        time.sleep(2.0)
        return True

    def _read_current_url(self) -> str:
        original_clipboard = self._safe_clipboard_read()
        self._focus_existing()
        sequence = self.tools.execute(
            "keyboard",
            {
                "action": "sequence",
                "steps": [
                    {"action": "hotkey", "keys": "ctrl+l"},
                    {"action": "hotkey", "keys": "ctrl+c", "delay": 0.1},
                    {"action": "press", "keys": "esc", "delay": 0.05},
                ],
            },
        )
        if not sequence.ok:
            return ""
        time.sleep(0.15)
        current_url = self._safe_clipboard_read()
        if original_clipboard is not None:
            self.tools.execute("clipboard", {"action": "write", "text": original_clipboard})
        return current_url.strip()

    def _read_browser_ocr(self) -> str:
        capture = self.tools.execute("screen", {"action": "capture"})
        if not capture.ok:
            return ""
        ocr = self.tools.execute("ocr", {"action": "extract_text", "path": capture.data.get("path", "")})
        if not ocr.ok:
            return ""
        return str(ocr.data.get("text", "")).strip()

    def _safe_clipboard_read(self) -> str | None:
        clip = self.tools.execute("clipboard", {"action": "read"})
        if not clip.ok:
            return None
        return str(clip.data.get("text", ""))

    def _derive_page_state(self, *, active_title: str, current_url: str, ocr_text: str, query: str) -> dict[str, Any]:
        text = f"{active_title}\n{current_url}\n{ocr_text}".lower()
        site = "youtube" if "youtube" in text or "youtu.be" in text else "google" if "google" in text else "other"
        looks_like_url = self._looks_like_url(current_url)
        page_kind = "unknown"
        if "youtube.com/results" in current_url or "results?search_query=" in current_url:
            page_kind = "youtube_search_results"
        elif "youtube.com/watch" in current_url or "youtu.be/" in current_url:
            page_kind = "youtube_watch"
        elif "google.com/search" in current_url:
            page_kind = "google_search_results"
        title_lower = active_title.lower()
        ocr_lower = ocr_text.lower()
        if page_kind == "unknown" and "google search" in title_lower:
            page_kind = "google_search_results"
        if page_kind == "unknown" and site == "youtube":
            if "filters" in ocr_lower and any(token in ocr_lower for token in ("views", "playlist", "mix", "channel", "subscribers", "ago")):
                page_kind = "youtube_search_results"
            elif any(token in ocr_lower for token in ("subscribe", "share", "save", "clip", "pause (k)", "play (k)", "autoplay")):
                page_kind = "youtube_watch"
        if page_kind == "unknown" and any(token in title_lower for token in (" - youtube - google chrome", " - youtube")):
            page_kind = "youtube_watch"
        if page_kind == "unknown" and "youtube" in title_lower and any(token in ocr_lower for token in ("0:00 /", "transcription", "subscribed", "subscribe", "like", "share")):
            page_kind = "youtube_watch"
        if page_kind == "unknown" and current_url and looks_like_url:
            page_kind = "generic_page"
        if page_kind == "unknown" and " - google chrome" in title_lower and "new tab" not in title_lower:
            page_kind = "generic_page"
        is_search_results_page = page_kind in {"youtube_search_results", "google_search_results"}
        is_target_media_page = page_kind == "youtube_watch"
        playback_ui_state = self._playback_state_from_text(text, is_target_media_page=is_target_media_page)
        media_position_seconds = self._media_position_seconds(text) if is_target_media_page else None
        target_tokens = self._query_tokens(query)
        address_bar_focused = self._address_bar_focused(current_url=current_url, ocr_text=ocr_text)
        address_bar_input = ""
        if address_bar_focused and current_url and not looks_like_url:
            address_bar_input = current_url.strip()
        if address_bar_input:
            focus_context = "address_bar_query"
        elif address_bar_focused:
            focus_context = "address_bar_url"
        elif page_kind != "unknown":
            focus_context = "page"
        else:
            focus_context = "unknown"
        target_match = self._target_match(target_tokens, text)
        if focus_context == "address_bar_query":
            target_match = False
        return {
            "site": site,
            "page_kind": page_kind,
            "is_search_results_page": is_search_results_page,
            "is_target_media_page": is_target_media_page,
            "playback_ui_state": playback_ui_state,
            "media_position_seconds": media_position_seconds,
            "target_match": target_match,
            "target_tokens": target_tokens,
            "address_bar_focused": address_bar_focused,
            "address_bar_input": address_bar_input,
            "focus_context": focus_context,
        }

    def _inspect_summary(self, data: dict[str, Any]) -> str:
        page_kind = str(data.get("page_kind", "unknown"))
        url = str(data.get("current_url", "")).strip()
        title = str(data.get("active_title", "")).strip()
        playback = str(data.get("playback_ui_state", "unknown")).strip()
        focus_context = str(data.get("focus_context", "")).strip()
        focus_suffix = f" [{focus_context}]" if focus_context.startswith("address_bar") else ""
        if page_kind == "youtube_search_results":
            return f"YouTube results page{focus_suffix}: {title or url}"
        if page_kind == "youtube_watch":
            return f"YouTube watch page ({playback}){focus_suffix}: {title or url}"
        if page_kind == "google_search_results":
            return f"Google results page{focus_suffix}: {title or url}"
        if focus_context == "address_bar_query":
            pending = str(data.get("address_bar_input", "")).strip()
            if pending:
                return f"Chrome address bar has pending input: {pending}"
        if title and url:
            return f"{title}\n{url}"
        if title:
            return title
        if url:
            return url
        return data.get("summary", "Browser action complete.")

    @classmethod
    def _query_tokens(cls, query: str) -> list[str]:
        raw_tokens = re.findall(r"[a-z0-9]+", query.lower())
        tokens: list[str] = []
        seen: set[str] = set()
        for token in raw_tokens:
            if len(token) < 3 or token in cls._QUERY_STOPWORDS:
                continue
            if token not in seen:
                seen.add(token)
                tokens.append(token)
        return tokens

    @staticmethod
    def _target_match(tokens: list[str], haystack: str) -> bool:
        if not tokens:
            return False
        required = min(len(tokens), 2 if len(tokens) >= 2 else 1)
        return sum(1 for token in tokens if token in haystack) >= required

    @staticmethod
    def _playback_state_from_text(text: str, *, is_target_media_page: bool) -> str:
        if not is_target_media_page:
            return "unknown"
        if any(signal in text for signal in (" pause ", "pause (k)", "pause keyboard shortcut", "playing")):
            return "playing"
        if any(signal in text for signal in (" play ", "play (k)", "play keyboard shortcut")):
            return "paused"
        return "unknown"

    @staticmethod
    def _media_position_seconds(text: str) -> int | None:
        match = re.search(r"\b(\d{1,2}):([0-5]\d)\s*/\s*(\d{1,2}):([0-5]\d)\b", text)
        if not match:
            return None
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        return minutes * 60 + seconds

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        candidate = value.strip().lower()
        if not candidate or " " in candidate:
            return False
        if candidate.startswith(("http://", "https://")):
            return True
        if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(/.*)?$", candidate):
            return True
        return False

    @staticmethod
    def _address_bar_focused(*, current_url: str, ocr_text: str) -> bool:
        if BrowserTool._looks_like_url(current_url):
            return False
        excerpt = ocr_text.replace("\r", "\n").splitlines()
        visible = " ".join(line.strip() for line in excerpt[:3] if line.strip()).lower()
        if not visible:
            return False
        lowered_url = current_url.lower().strip()
        if lowered_url and lowered_url in visible and len(visible) < max(220, len(lowered_url) + 60):
            return True
        return False

    @staticmethod
    def _window_bounds(data: dict[str, Any]) -> dict[str, int]:
        if not isinstance(data, dict):
            return {}
        bounds: dict[str, int] = {}
        for key in ("left", "top", "width", "height", "right", "bottom"):
            if key in data and data.get(key) not in (None, ""):
                bounds[key] = int(data[key])
        if {"left", "top", "width", "height"}.issubset(bounds):
            bounds.setdefault("right", bounds["left"] + bounds["width"])
            bounds.setdefault("bottom", bounds["top"] + bounds["height"])
        return bounds

    def render(self, data: dict[str, Any]) -> str:
        if data.get("action") in {"play_pause", "refresh", "back", "forward", "close_tab", "wait_for_text"}:
            return data.get("summary", "Browser action complete.")
        if "page_kind" in data:
            return self._inspect_summary(data)
        title = str(data.get("active_title", "")).strip()
        url = str(data.get("url", "")).strip() or str(data.get("current_url", "")).strip()
        if title and url:
            return f"{title}\n{url}"
        if title:
            return title
        if url:
            return url
        return data.get("summary", "Browser action complete.")


def register_browser_tools(
    registry: ToolRegistry,
    chrome_path: str = "",
    *,
    backend: str = "native",
    user_data_dir: str = "",
) -> None:
    registry.register(BrowserTool(registry, chrome_path=chrome_path, backend=backend, user_data_dir=user_data_dir))
