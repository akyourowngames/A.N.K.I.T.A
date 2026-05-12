from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.browser_agent as browser_agent
import tools.browser_state as browser_state
from tools.browser_agent import browser_launch, close_browser


class BrowserTimeoutFixTests(unittest.TestCase):
    def test_launch_keeps_viewport_out_of_persistent_context_kwargs(self) -> None:
        class FakeFrame:
            name = ""
            url = "about:blank"
            parent_frame = None

        class FakePage:
            def __init__(self) -> None:
                self.url = "about:blank"
                self.frames = [FakeFrame()]
                self.viewport: dict[str, int] | None = None
                self.events: list[str] = []

            def is_closed(self) -> bool:
                return False

            def title(self) -> str:
                return ""

            def evaluate(self, _script: str) -> list[str]:
                return []

            def on(self, event: str, _handler: object) -> None:
                self.events.append(event)

            def set_viewport_size(self, viewport: dict[str, int]) -> None:
                self.viewport = viewport

        class FakeContext:
            def __init__(self) -> None:
                self.page = FakePage()
                self.pages = [self.page]
                self.events: list[str] = []

            def new_page(self) -> FakePage:
                self.page = FakePage()
                self.pages = [self.page]
                return self.page

            def on(self, event: str, _handler: object) -> None:
                self.events.append(event)

            def cookies(self) -> list[dict[str, object]]:
                return []

            def close(self) -> None:
                return

        class FakeEngine:
            executable_path = r"C:\fake\playwright-chromium.exe"

            def __init__(self) -> None:
                self.context = FakeContext()
                self.kwargs: dict[str, object] = {}

            def launch_persistent_context(self, _profile: str, **kwargs: object) -> FakeContext:
                self.kwargs = dict(kwargs)
                return self.context

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeEngine()
                self.firefox = FakeEngine()

            def stop(self) -> None:
                return

        class FakeStarter:
            def __init__(self, playwright: FakePlaywright) -> None:
                self.playwright = playwright

            def start(self) -> FakePlaywright:
                return self.playwright

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "browser.json"
            config_path.write_text(
                json.dumps(
                    {
                        "profiles_dir": str(root / "profiles"),
                        "sessions_dir": str(root / "sessions"),
                        "screenshots_dir": str(root / "screens"),
                        "downloads_dir": str(root / "downloads"),
                        "recordings_dir": str(root / "recordings"),
                        "cache_dir": str(root / "cache"),
                        "headless": True,
                        "default_viewport": {"width": 800, "height": 600},
                        "browser_executable_candidates": [],
                    }
                ),
                encoding="utf-8",
            )
            fake_playwright = FakePlaywright()
            playwright_module = types.ModuleType("playwright")
            sync_api = types.ModuleType("playwright.sync_api")
            sync_api.sync_playwright = lambda: FakeStarter(fake_playwright)
            playwright_module.sync_api = sync_api
            with patch.dict(sys.modules, {"playwright": playwright_module, "playwright.sync_api": sync_api}, clear=False):
                with patch.dict(os.environ, {"JARVIS_BROWSER_CONFIG": str(config_path)}, clear=False):
                    with patch("tools.browser_agent.playwright_available", return_value=True):
                        try:
                            launched = browser_launch({"profile_name": "viewport-test", "headless": True})
                        finally:
                            close_browser()

        self.assertNotIn("viewport", fake_playwright.chromium.kwargs)
        self.assertEqual(fake_playwright.chromium.context.page.viewport, {"width": 800, "height": 600})
        self.assertTrue(launched["viewport_applied"])

    def test_template_values_uses_cached_playwright_path_without_second_start(self) -> None:
        previous = browser_agent._PLAYWRIGHT_CHROMIUM_EXECUTABLE
        browser_agent._PLAYWRIGHT_CHROMIUM_EXECUTABLE = r"C:\cached\chromium.exe"
        try:
            values = browser_agent.template_values()
        finally:
            browser_agent._PLAYWRIGHT_CHROMIUM_EXECUTABLE = previous

        self.assertEqual(values["playwright_chromium"], r"C:\cached\chromium.exe")

    def test_page_events_attach_once_per_page(self) -> None:
        class FakePage:
            def __init__(self) -> None:
                self.events: list[str] = []

            def on(self, event: str, _handler: object) -> None:
                self.events.append(event)

        class FakeSession:
            session_id = "event-session"
            state: dict[str, object] = {}

        page = FakePage()
        browser_agent._ATTACHED_PAGE_EVENTS.clear()
        with patch("tools.browser_agent.browser_network.attach_network_listeners"):
            browser_agent.attach_page_events(FakeSession(), page)
            browser_agent.attach_page_events(FakeSession(), page)

        self.assertEqual(page.events.count("dialog"), 1)
        self.assertEqual(page.events.count("download"), 1)

    def test_stability_wait_skips_networkidle_hot_path(self) -> None:
        class FakePage:
            def __init__(self) -> None:
                self.states: list[str] = []

            def wait_for_load_state(self, state: str, timeout: int) -> None:
                self.states.append(state)
                if state == "networkidle":
                    raise AssertionError("networkidle should be explicit, not part of hot-path stability")

        class FakeSession:
            def __init__(self) -> None:
                self.page = FakePage()
                self.page_load_state = "unknown"

        session = FakeSession()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "browser.json"
            config_path.write_text(json.dumps({"network_idle_timeout_ms": 500}), encoding="utf-8")
            with patch.dict(os.environ, {"JARVIS_BROWSER_CONFIG": str(config_path)}, clear=False):
                browser_agent.wait_for_stability(session, {"timeout_ms": 1000})

        self.assertEqual(session.page.states, ["domcontentloaded"])
        self.assertEqual(session.page_load_state, "domcontentloaded")

    def test_profile_lock_cleanup_removes_stale_agent_locks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            default = profile / "Default"
            default.mkdir(parents=True)
            singleton = profile / "SingletonLock"
            lock = default / "LOCK"
            singleton.write_text("host-999999", encoding="utf-8")
            lock.write_text("", encoding="utf-8")

            with patch("tools.browser_agent.process_is_running", return_value=False):
                removed = browser_agent.cleanup_profile_locks(profile)

        self.assertFalse(singleton.exists())
        self.assertFalse(lock.exists())
        self.assertEqual(set(removed), {str(singleton), str(lock)})

    def test_config_cache_invalidates_when_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "browser.json"
            config_path.write_text(json.dumps({"agent_name": "First"}), encoding="utf-8")
            with patch.dict(os.environ, {"JARVIS_BROWSER_CONFIG": str(config_path)}, clear=False):
                first = browser_state.load_config()
                config_path.write_text(json.dumps({"agent_name": "Second"}), encoding="utf-8")
                future = time.time() + 1
                os.utime(config_path, (future, future))
                second = browser_state.load_config()

        self.assertEqual(first["agent_name"], "First")
        self.assertEqual(second["agent_name"], "Second")


if __name__ == "__main__":
    unittest.main()
