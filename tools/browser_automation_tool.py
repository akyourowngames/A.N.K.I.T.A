#!/usr/bin/env python3
"""
Browser automation tool using Selenium with batched step execution.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import Select, WebDriverWait
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.edge.service import Service as EdgeService
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from selenium.webdriver.firefox.service import Service as FirefoxService

    SELENIUM_AVAILABLE = True
except ImportError:
    webdriver = None
    TimeoutException = Exception
    WebDriverException = Exception
    By = None
    Keys = None
    EC = None
    Select = None
    WebDriverWait = None
    ChromeOptions = None
    ChromeService = None
    EdgeOptions = None
    EdgeService = None
    FirefoxOptions = None
    FirefoxService = None
    SELENIUM_AVAILABLE = False

try:
    from webdriver_manager.chrome import ChromeDriverManager
    from webdriver_manager.firefox import GeckoDriverManager
    from webdriver_manager.microsoft import EdgeChromiumDriverManager

    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    ChromeDriverManager = None
    GeckoDriverManager = None
    EdgeChromiumDriverManager = None
    WEBDRIVER_MANAGER_AVAILABLE = False

try:
    from browser_bridge import BrowserBridgeManager

    BROWSER_BRIDGE_AVAILABLE = True
except ImportError:
    BrowserBridgeManager = None
    BROWSER_BRIDGE_AVAILABLE = False


class BrowserAutomationTool:
    """Complex browser automation with reusable sessions and step batches."""

    _sessions: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def get_schema():
        """Get tool schema for function calling."""
        return {
            "type": "function",
            "function": {
                "name": "browser_automation",
                "description": (
                    "Complex browser automation with reusable sessions. Use start_session, "
                    "run_steps, snapshot, list_sessions, and close_session for DOM-aware browsing."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "start_session",
                                "run_steps",
                                "snapshot",
                                "close_session",
                                "list_sessions",
                            ],
                            "description": "Browser automation action to perform",
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Existing browser session id",
                        },
                        "backend": {
                            "type": "string",
                            "enum": ["auto", "selenium", "bridge"],
                            "description": "Execution backend. Use bridge for the localhost extension path.",
                        },
                        "browser": {
                            "type": "string",
                            "enum": ["chrome", "chromium", "edge", "firefox"],
                            "description": "Browser to launch",
                        },
                        "headless": {
                            "type": "boolean",
                            "description": "Launch in headless mode",
                        },
                        "url": {
                            "type": "string",
                            "description": "Initial URL for start_session",
                        },
                        "width": {
                            "type": "integer",
                            "description": "Viewport width",
                        },
                        "height": {
                            "type": "integer",
                            "description": "Viewport height",
                        },
                        "download_dir": {
                            "type": "string",
                            "description": "Download directory for the session",
                        },
                        "binary_path": {
                            "type": "string",
                            "description": "Optional browser executable path",
                        },
                        "driver_path": {
                            "type": "string",
                            "description": "Optional local WebDriver executable path",
                        },
                        "target_client_id": {
                            "type": "string",
                            "description": "Optional extension client id when using bridge mode",
                        },
                        "wait_for_result": {
                            "type": "boolean",
                            "description": "Whether bridge mode should wait for an extension result",
                        },
                        "timeout_sec": {
                            "type": "number",
                            "description": "Default timeout in seconds",
                        },
                        "steps": {
                            "type": "array",
                            "description": (
                                "Batch of browser steps for run_steps. Step types include goto, click, fill, "
                                "press, select, wait_for, extract, screenshot, upload, script, scroll, "
                                "new_tab, switch_tab, and close_tab."
                            ),
                            "items": {
                                "type": "object"
                            },
                        },
                        "max_items": {
                            "type": "integer",
                            "description": "Maximum items returned by snapshot",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Maximum extracted text length",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    @staticmethod
    def execute(arguments: dict) -> str:
        """Execute a browser automation action."""
        action = arguments.get("action", "")
        if not action:
            return "Error: action is required"

        backend = BrowserAutomationTool._resolve_backend(arguments)
        if backend == "bridge":
            return BrowserAutomationTool._execute_via_bridge(arguments)

        if not SELENIUM_AVAILABLE:
            if backend == "auto" and BROWSER_BRIDGE_AVAILABLE:
                return BrowserAutomationTool._execute_via_bridge(arguments)
            return "Error: selenium is not installed. Run: pip install selenium"

        handlers = {
            "start_session": BrowserAutomationTool._start_session,
            "run_steps": BrowserAutomationTool._run_steps,
            "snapshot": BrowserAutomationTool._snapshot,
            "close_session": BrowserAutomationTool._close_session,
            "list_sessions": BrowserAutomationTool._list_sessions,
        }

        handler = handlers.get(action)
        if handler is None:
            return f"Error: Unknown action '{action}'"

        try:
            return handler(arguments)
        except Exception as exc:
            return f"Error: {exc}"

    @staticmethod
    def _resolve_backend(arguments: dict) -> str:
        requested = str(arguments.get("backend") or os.getenv("BROWSER_AUTOMATION_BACKEND", "auto")).strip().lower()
        if requested not in {"auto", "selenium", "bridge"}:
            requested = "auto"

        if requested == "auto" and BROWSER_BRIDGE_AVAILABLE:
            auto_start = os.getenv("BROWSER_BRIDGE_AUTOSTART", "true").strip().lower() in {"1", "true", "yes", "on"}
            manager = BrowserBridgeManager.ensure_running() if auto_start else BrowserBridgeManager.get_instance()
            if manager.state.has_connected_extensions():
                return "bridge"

        return requested

    @staticmethod
    def _execute_via_bridge(arguments: dict) -> str:
        if not BROWSER_BRIDGE_AVAILABLE:
            return "Error: browser_bridge module is not available"

        bridge_status = BrowserAutomationTool._bridge_status()
        if bridge_status is None:
            # Fallback to in-process bridge only when HTTP is unavailable.
            manager = BrowserBridgeManager.ensure_running()
            bridge_status = manager.state.status()
            if not bridge_status.get("connected_extensions"):
                return BrowserAutomationTool._json(
                    {
                        "ok": False,
                        "action": arguments.get("action"),
                        "backend": "bridge",
                        "error": "no_extension_connected",
                        "bridge": bridge_status,
                    }
                )
            result = manager.state.enqueue_command(
                payload={k: v for k, v in arguments.items() if k not in {"backend"}},
                wait_for_result=bool(arguments.get("wait_for_result", True)),
                timeout_sec=float(arguments.get("timeout_sec", os.getenv("BROWSER_BRIDGE_COMMAND_TIMEOUT_SEC", "30"))),
                target_client_id=arguments.get("target_client_id"),
            )
            if isinstance(result, dict):
                result.setdefault("backend", "bridge")
                result.setdefault("bridge", bridge_status)
            return BrowserAutomationTool._json(
                result if isinstance(result, dict) else {"ok": False, "error": str(result), "backend": "bridge"}
            )

        if not bridge_status.get("connected_extensions"):
            return BrowserAutomationTool._json(
                {
                    "ok": False,
                    "action": arguments.get("action"),
                    "backend": "bridge",
                    "error": "no_extension_connected",
                    "bridge": bridge_status,
                }
            )

        wait_for_result = bool(arguments.get("wait_for_result", True))
        timeout_sec = float(
            arguments.get(
                "timeout_sec",
                BrowserAutomationTool._default_bridge_timeout(arguments.get("action")),
            )
        )
        payload = {k: v for k, v in arguments.items() if k not in {"backend"}}
        result = BrowserAutomationTool._bridge_command(
            payload=payload,
            wait_for_result=wait_for_result,
            timeout_sec=timeout_sec,
            target_client_id=arguments.get("target_client_id"),
        )
        if isinstance(result, dict):
            result.setdefault("backend", "bridge")
            result.setdefault("bridge", bridge_status)
        return BrowserAutomationTool._json(
            result if isinstance(result, dict) else {"ok": False, "error": str(result), "backend": "bridge"}
        )

    @staticmethod
    def _bridge_base_url() -> str:
        host = os.getenv("BROWSER_BRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port = os.getenv("BROWSER_BRIDGE_PORT", "8766").strip() or "8766"
        return f"http://{host}:{port}"

    @staticmethod
    def _default_bridge_timeout(action: Optional[str]) -> float:
        fast_actions = {"snapshot", "list_sessions", "start_session"}
        if action and str(action).lower() in fast_actions:
            return float(os.getenv("BROWSER_BRIDGE_FAST_TIMEOUT_SEC", "10"))
        return float(os.getenv("BROWSER_BRIDGE_COMMAND_TIMEOUT_SEC", "30"))

    @staticmethod
    def _bridge_http_json(method: str, path: str, payload: Optional[dict] = None) -> Optional[Dict[str, Any]]:
        url = BrowserAutomationTool._bridge_base_url() + path
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, timeout=5) as response:
                raw = response.read().decode("utf-8") if response else "{}"
                return json.loads(raw or "{}")
        except (HTTPError, URLError, ValueError):
            return None

    @staticmethod
    def _bridge_status() -> Optional[Dict[str, Any]]:
        return BrowserAutomationTool._bridge_http_json("GET", "/status")

    @staticmethod
    def _bridge_command(
        payload: Dict[str, Any],
        wait_for_result: bool,
        timeout_sec: float,
        target_client_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        body = {
            "command": payload,
            "wait_for_result": wait_for_result,
            "timeout_sec": timeout_sec,
        }
        if target_client_id:
            body["target_client_id"] = target_client_id
        return BrowserAutomationTool._bridge_http_json("POST", "/command", body)

    @staticmethod
    def _json(payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _new_session_id() -> str:
        return "browser-" + uuid.uuid4().hex[:8]

    @staticmethod
    def _artifacts_dir(session_id: str) -> Path:
        path = Path(".cache") / "browser" / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _timeout(arguments: dict, session: Optional[Dict[str, Any]] = None) -> float:
        if arguments.get("timeout_sec") is not None:
            return float(arguments["timeout_sec"])
        if session is not None:
            return float(session.get("timeout_sec", 15))
        return 15.0

    @staticmethod
    def _get_session(arguments: dict) -> Dict[str, Any]:
        session_id = arguments.get("session_id")
        if not session_id:
            raise RuntimeError("session_id is required")
        session = BrowserAutomationTool._sessions.get(session_id)
        if session is None:
            raise RuntimeError(f"Unknown browser session '{session_id}'")
        return session

    @staticmethod
    def _build_driver(arguments: dict, session_id: str):
        browser = str(arguments.get("browser", "edge")).lower()
        headless = bool(arguments.get("headless", False))
        width = arguments.get("width")
        height = arguments.get("height")
        download_dir = arguments.get("download_dir") or str(BrowserAutomationTool._artifacts_dir(session_id) / "downloads")
        binary_path = arguments.get("binary_path")
        driver_path = arguments.get("driver_path")
        Path(download_dir).mkdir(parents=True, exist_ok=True)

        if browser in {"chrome", "chromium"}:
            options = ChromeOptions()
            if headless:
                options.add_argument("--headless=new")
            options.add_argument("--disable-blink-features=AutomationControlled")
            if binary_path:
                options.binary_location = str(Path(binary_path))
            options.add_experimental_option(
                "prefs",
                {
                    "download.default_directory": str(Path(download_dir).resolve()),
                    "download.prompt_for_download": False,
                    "download.directory_upgrade": True,
                },
            )
            driver = BrowserAutomationTool._start_chrome_driver(options, driver_path)
        elif browser == "edge":
            options = EdgeOptions()
            if headless:
                options.add_argument("--headless=new")
            if binary_path:
                options.binary_location = str(Path(binary_path))
            options.add_experimental_option(
                "prefs",
                {
                    "download.default_directory": str(Path(download_dir).resolve()),
                    "download.prompt_for_download": False,
                    "download.directory_upgrade": True,
                },
            )
            driver = BrowserAutomationTool._start_edge_driver(options, driver_path)
        elif browser == "firefox":
            options = FirefoxOptions()
            if headless:
                options.add_argument("--headless")
            if binary_path:
                options.binary_location = str(Path(binary_path))
            options.set_preference("browser.download.folderList", 2)
            options.set_preference("browser.download.dir", str(Path(download_dir).resolve()))
            options.set_preference("browser.download.useDownloadDir", True)
            options.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/octet-stream")
            driver = BrowserAutomationTool._start_firefox_driver(options, driver_path)
        else:
            raise RuntimeError(f"Unsupported browser '{browser}'")

        if width and height:
            driver.set_window_size(int(width), int(height))
        else:
            try:
                driver.maximize_window()
            except WebDriverException:
                pass

        driver.implicitly_wait(0)
        driver.set_page_load_timeout(int(BrowserAutomationTool._timeout(arguments)))
        return driver, browser, download_dir

    @staticmethod
    def _start_chrome_driver(options, driver_path: Optional[str] = None):
        try:
            if driver_path:
                return webdriver.Chrome(service=ChromeService(str(Path(driver_path))), options=options)
            return webdriver.Chrome(options=options)
        except Exception as exc:
            if not WEBDRIVER_MANAGER_AVAILABLE:
                raise RuntimeError(f"Unable to start Chrome driver: {exc}")
            try:
                service = ChromeService(ChromeDriverManager().install())
                return webdriver.Chrome(service=service, options=options)
            except Exception as manager_exc:
                raise RuntimeError(
                    f"Unable to start Chrome driver. Original error: {exc}. "
                    f"Manager fallback failed: {manager_exc}. "
                    "Provide a local driver_path or install chromedriver."
                )

    @staticmethod
    def _start_edge_driver(options, driver_path: Optional[str] = None):
        try:
            if driver_path:
                return webdriver.Edge(service=EdgeService(str(Path(driver_path))), options=options)
            return webdriver.Edge(options=options)
        except Exception as exc:
            if not WEBDRIVER_MANAGER_AVAILABLE:
                raise RuntimeError(f"Unable to start Edge driver: {exc}")
            try:
                service = EdgeService(EdgeChromiumDriverManager().install())
                return webdriver.Edge(service=service, options=options)
            except Exception as manager_exc:
                raise RuntimeError(
                    f"Unable to start Edge driver. Original error: {exc}. "
                    f"Manager fallback failed: {manager_exc}. "
                    "Provide a local driver_path or install msedgedriver."
                )

    @staticmethod
    def _start_firefox_driver(options, driver_path: Optional[str] = None):
        try:
            if driver_path:
                return webdriver.Firefox(service=FirefoxService(str(Path(driver_path))), options=options)
            return webdriver.Firefox(options=options)
        except Exception as exc:
            if not WEBDRIVER_MANAGER_AVAILABLE:
                raise RuntimeError(f"Unable to start Firefox driver: {exc}")
            try:
                service = FirefoxService(GeckoDriverManager().install())
                return webdriver.Firefox(service=service, options=options)
            except Exception as manager_exc:
                raise RuntimeError(
                    f"Unable to start Firefox driver. Original error: {exc}. "
                    f"Manager fallback failed: {manager_exc}. "
                    "Provide a local driver_path or install geckodriver."
                )

    @staticmethod
    def _start_session(arguments: dict) -> str:
        session_id = arguments.get("session_id") or BrowserAutomationTool._new_session_id()
        if session_id in BrowserAutomationTool._sessions:
            return f"Error: Browser session '{session_id}' already exists"

        driver, browser, download_dir = BrowserAutomationTool._build_driver(arguments, session_id)
        url = arguments.get("url")
        if url:
            driver.get(url)

        timeout_sec = BrowserAutomationTool._timeout(arguments)
        BrowserAutomationTool._sessions[session_id] = {
            "driver": driver,
            "browser": browser,
            "timeout_sec": timeout_sec,
            "download_dir": download_dir,
            "artifacts_dir": str(BrowserAutomationTool._artifacts_dir(session_id)),
        }

        return BrowserAutomationTool._json(
            {
                "ok": True,
                "action": "start_session",
                "session_id": session_id,
                "browser": browser,
                "url": driver.current_url,
                "title": driver.title,
                "download_dir": download_dir,
            }
        )

    @staticmethod
    def _list_sessions(arguments: dict) -> str:
        sessions = []
        for session_id, session in BrowserAutomationTool._sessions.items():
            driver = session["driver"]
            sessions.append(
                {
                    "session_id": session_id,
                    "browser": session.get("browser"),
                    "url": driver.current_url,
                    "title": driver.title,
                    "tab_count": len(driver.window_handles),
                }
            )
        return BrowserAutomationTool._json({"ok": True, "action": "list_sessions", "sessions": sessions})

    @staticmethod
    def _close_session(arguments: dict) -> str:
        session = BrowserAutomationTool._get_session(arguments)
        session_id = arguments["session_id"]
        session["driver"].quit()
        BrowserAutomationTool._sessions.pop(session_id, None)
        return BrowserAutomationTool._json({"ok": True, "action": "close_session", "session_id": session_id})

    @staticmethod
    def _snapshot(arguments: dict) -> str:
        session = BrowserAutomationTool._get_session(arguments)
        driver = session["driver"]
        max_items = int(arguments.get("max_items", 10))
        data = driver.execute_script(
            """
            const limit = arguments[0];
            const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
            const take = (items) => items.filter(Boolean).slice(0, limit);
            return {
              url: window.location.href,
              title: document.title,
              headings: take(Array.from(document.querySelectorAll('h1,h2,h3')).map(el => clean(el.innerText))),
              buttons: take(Array.from(document.querySelectorAll('button,[role=\"button\"],input[type=\"button\"],input[type=\"submit\"]')).map(el => clean(el.innerText || el.value || el.getAttribute('aria-label')))),
              links: take(Array.from(document.querySelectorAll('a[href]')).map(el => ({text: clean(el.innerText), href: el.href}))),
              fields: take(Array.from(document.querySelectorAll('input,textarea,select')).map(el => ({
                tag: el.tagName.toLowerCase(),
                type: el.type || null,
                name: el.name || null,
                id: el.id || null,
                placeholder: el.placeholder || null,
                aria_label: el.getAttribute('aria-label')
              })))
            };
            """,
            max_items,
        )
        data["tab_count"] = len(driver.window_handles)
        return BrowserAutomationTool._json({"ok": True, "action": "snapshot", "session_id": arguments["session_id"], "snapshot": data})

    @staticmethod
    def _run_steps(arguments: dict) -> str:
        session = BrowserAutomationTool._get_session(arguments)
        driver = session["driver"]
        steps = arguments.get("steps") or []
        if not isinstance(steps, list) or not steps:
            return "Error: steps must be a non-empty array for run_steps"

        results = []
        artifacts: List[Dict[str, Any]] = []

        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                return f"Error: step {index} must be an object"

            try:
                step_result, step_artifact = BrowserAutomationTool._execute_step(driver, session, step, index, arguments)
                results.append(step_result)
                if step_artifact:
                    artifacts.append(step_artifact)
            except Exception as exc:
                results.append(
                    {
                        "index": index,
                        "type": step.get("type", "unknown"),
                        "ok": False,
                        "error": str(exc),
                    }
                )
                return BrowserAutomationTool._json(
                    {
                        "ok": False,
                        "action": "run_steps",
                        "session_id": arguments["session_id"],
                        "url": driver.current_url,
                        "title": driver.title,
                        "steps": results,
                        "artifacts": artifacts,
                        "error": str(exc),
                    }
                )

        return BrowserAutomationTool._json(
            {
                "ok": True,
                "action": "run_steps",
                "session_id": arguments["session_id"],
                "url": driver.current_url,
                "title": driver.title,
                "steps": results,
                "artifacts": artifacts,
                "error": None,
            }
        )

    @staticmethod
    def _execute_step(driver, session: Dict[str, Any], step: Dict[str, Any], index: int, arguments: dict) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        step_type = str(step.get("type", "")).lower().strip()
        if not step_type:
            raise RuntimeError(f"Step {index} is missing type")

        timeout = float(step.get("timeout_sec", BrowserAutomationTool._timeout(arguments, session)))
        artifact = None

        if step_type == "goto":
            url = step.get("url")
            if not url:
                raise RuntimeError("goto step requires url")
            driver.get(url)
            return {"index": index, "type": step_type, "ok": True, "url": driver.current_url}, artifact

        if step_type == "new_tab":
            driver.switch_to.new_window("tab")
            if step.get("url"):
                driver.get(step["url"])
            return {"index": index, "type": step_type, "ok": True, "tab_count": len(driver.window_handles), "url": driver.current_url}, artifact

        if step_type == "switch_tab":
            tab_index = int(step.get("tab_index", 0))
            handles = driver.window_handles
            if tab_index < 0 or tab_index >= len(handles):
                raise RuntimeError(f"Invalid tab_index {tab_index}; session has {len(handles)} tab(s)")
            driver.switch_to.window(handles[tab_index])
            return {"index": index, "type": step_type, "ok": True, "tab_index": tab_index, "url": driver.current_url}, artifact

        if step_type == "close_tab":
            handles = driver.window_handles
            tab_index = int(step.get("tab_index", len(handles) - 1))
            if len(handles) <= 1:
                raise RuntimeError("Cannot close the last remaining tab")
            if tab_index < 0 or tab_index >= len(handles):
                raise RuntimeError(f"Invalid tab_index {tab_index}; session has {len(handles)} tab(s)")
            driver.switch_to.window(handles[tab_index])
            driver.close()
            remaining = driver.window_handles
            driver.switch_to.window(remaining[max(0, min(tab_index, len(remaining) - 1))])
            return {"index": index, "type": step_type, "ok": True, "tab_count": len(remaining), "url": driver.current_url}, artifact

        if step_type == "scroll":
            amount = int(step.get("amount", 800))
            driver.execute_script("window.scrollBy(0, arguments[0]);", amount)
            return {"index": index, "type": step_type, "ok": True, "amount": amount}, artifact

        if step_type == "script":
            script = step.get("script") or step.get("text")
            if not script:
                raise RuntimeError("script step requires script or text")
            result = driver.execute_script(script)
            return {"index": index, "type": step_type, "ok": True, "result": result}, artifact

        if step_type == "wait_for":
            BrowserAutomationTool._wait_for_step(driver, step, timeout)
            return {"index": index, "type": step_type, "ok": True}, artifact

        if step_type == "extract":
            extracted = BrowserAutomationTool._extract_step(driver, step, timeout)
            max_chars = int(step.get("max_chars", arguments.get("max_chars", 3000)))
            if isinstance(extracted, str) and len(extracted) > max_chars:
                extracted = extracted[:max_chars]
            return {"index": index, "type": step_type, "ok": True, "output": extracted}, artifact

        if step_type == "screenshot":
            path = step.get("path") or str(BrowserAutomationTool._artifacts_dir(arguments["session_id"]) / f"step_{index + 1}.png")
            output_path = Path(path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            target = step.get("target")
            if target:
                element = BrowserAutomationTool._locate_element(driver, target, timeout, condition="visible")
                element.screenshot(str(output_path))
            else:
                driver.save_screenshot(str(output_path))
            artifact = {"type": "screenshot", "path": str(output_path)}
            return {"index": index, "type": step_type, "ok": True, "path": str(output_path)}, artifact

        if step_type == "upload":
            target = step.get("target")
            file_path = step.get("file_path")
            if not target or not file_path:
                raise RuntimeError("upload step requires target and file_path")
            resolved = Path(file_path)
            if not resolved.exists():
                raise RuntimeError(f"File not found: {resolved}")
            element = BrowserAutomationTool._locate_element(driver, target, timeout, condition="visible")
            element.send_keys(str(resolved))
            return {"index": index, "type": step_type, "ok": True, "file_path": str(resolved)}, artifact

        target = step.get("target")
        if step_type in {"click", "fill", "select", "press"} and not target and step_type != "press":
            raise RuntimeError(f"{step_type} step requires target")

        if step_type == "click":
            element = BrowserAutomationTool._locate_element(driver, target, timeout, condition="clickable")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            element.click()
            return {"index": index, "type": step_type, "ok": True}, artifact

        if step_type == "fill":
            text = step.get("text", "")
            element = BrowserAutomationTool._locate_element(driver, target, timeout, condition="visible")
            if not step.get("append", False):
                element.clear()
            element.send_keys(text)
            return {"index": index, "type": step_type, "ok": True, "chars": len(text)}, artifact

        if step_type == "select":
            value = step.get("value")
            if value is None:
                raise RuntimeError("select step requires value")
            element = BrowserAutomationTool._locate_element(driver, target, timeout, condition="visible")
            select = Select(element)
            try:
                select.select_by_visible_text(str(value))
            except Exception:
                select.select_by_value(str(value))
            return {"index": index, "type": step_type, "ok": True, "value": value}, artifact

        if step_type == "press":
            key_value = step.get("key") or step.get("text") or step.get("value")
            if not key_value:
                raise RuntimeError("press step requires key, text, or value")
            if target:
                element = BrowserAutomationTool._locate_element(driver, target, timeout, condition="visible")
                element.send_keys(BrowserAutomationTool._resolve_key(key_value))
            else:
                driver.switch_to.active_element.send_keys(BrowserAutomationTool._resolve_key(key_value))
            return {"index": index, "type": step_type, "ok": True, "key": key_value}, artifact

        raise RuntimeError(f"Unsupported step type '{step_type}'")

    @staticmethod
    def _resolve_key(value: str):
        normalized = str(value).upper().replace(" ", "_")
        if hasattr(Keys, normalized):
            return getattr(Keys, normalized)
        return value

    @staticmethod
    def _wait_for_step(driver, step: Dict[str, Any], timeout: float) -> None:
        condition = str(step.get("condition", "visible")).lower()
        target = step.get("target")
        text = step.get("text")
        if target:
            BrowserAutomationTool._locate_element(driver, target, timeout, condition=condition)
            return
        if text:
            WebDriverWait(driver, timeout).until(lambda drv: text.lower() in drv.page_source.lower())
            return
        raise RuntimeError("wait_for step requires target or text")

    @staticmethod
    def _extract_step(driver, step: Dict[str, Any], timeout: float):
        mode = str(step.get("mode", "text")).lower()
        target = step.get("target")
        attribute = step.get("attribute")

        if target:
            element = BrowserAutomationTool._locate_element(driver, target, timeout, condition="visible")
            if mode == "html":
                return element.get_attribute("innerHTML")
            if mode == "attribute":
                if not attribute:
                    raise RuntimeError("extract step with mode=attribute requires attribute")
                return element.get_attribute(attribute)
            return element.text

        if mode == "html":
            return driver.page_source
        return driver.find_element(By.TAG_NAME, "body").text

    @staticmethod
    def _locate_element(driver, target: Dict[str, Any], timeout: float, condition: str = "visible"):
        locator = BrowserAutomationTool._build_locator(target)
        if locator is None:
            raise RuntimeError("Unsupported target locator")

        wait = WebDriverWait(driver, timeout)
        by, value = locator

        if condition == "clickable":
            return wait.until(EC.element_to_be_clickable((by, value)))
        if condition == "presence":
            return wait.until(EC.presence_of_element_located((by, value)))
        return wait.until(EC.visibility_of_element_located((by, value)))

    @staticmethod
    def _build_locator(target: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        if not isinstance(target, dict):
            return None

        if target.get("css"):
            return By.CSS_SELECTOR, str(target["css"])
        if target.get("xpath"):
            return By.XPATH, str(target["xpath"])
        if target.get("id"):
            return By.ID, str(target["id"])
        if target.get("name"):
            return By.NAME, str(target["name"])
        if target.get("class_name"):
            return By.CLASS_NAME, str(target["class_name"])
        if target.get("tag_name"):
            return By.TAG_NAME, str(target["tag_name"])
        if target.get("link_text"):
            return By.LINK_TEXT, str(target["link_text"])
        if target.get("partial_link_text"):
            return By.PARTIAL_LINK_TEXT, str(target["partial_link_text"])
        if target.get("label"):
            label = BrowserAutomationTool._xpath_literal(str(target["label"]))
            return (
                By.XPATH,
                f"//label[normalize-space()={label}]/following::*[self::input or self::textarea or self::select][1]",
            )
        if target.get("role") and target.get("name"):
            role = BrowserAutomationTool._xpath_literal(str(target["role"]))
            name = BrowserAutomationTool._xpath_literal(str(target["name"]))
            return (
                By.XPATH,
                (
                    f"//*[@role={role} and (normalize-space()={name} or @aria-label={name} or @title={name})]"
                ),
            )
        if target.get("text"):
            text = BrowserAutomationTool._xpath_literal(str(target["text"]))
            return By.XPATH, f"//*[normalize-space()={text} or contains(normalize-space(), {text})]"

        return None

    @staticmethod
    def _xpath_literal(value: str) -> str:
        if "'" not in value:
            return f"'{value}'"
        if '"' not in value:
            return f'"{value}"'
        parts = value.split("'")
        return "concat(" + ", \"'\", ".join(f"'{part}'" for part in parts) + ")"
