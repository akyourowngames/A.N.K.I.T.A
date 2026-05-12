from __future__ import annotations

import ast
import unittest
import contextlib
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

from extension_system import load_extension_catalog
from jarvis_nim import JarvisConfig, chat_with_native_streaming_tools, collect_tool_decision, contains_unresolved_placeholder, direct_single_tool_reply, final_chat_response, open_url_with_retries, parse_tool_requests, planner_turn_context, public_result_payload, public_tool_results, read_native_tool_stream, read_streaming_response, stream_token, tool_planner_model, tool_selector_model, tool_selection_from_selector_content, tool_results_prompt
from main import configure_stream_encoding, interactive_speech_command
from memory_system import MemoryConfig, load_memory_context, parse_memory_json, prose_memory_fallback
from skill_system import load_skill_context
from tools import discover_tools
from tools.browser_agent import (
    browser,
    browser_click,
    browser_detect_state,
    browser_find_element,
    browser_get_text,
    browser_intercept_start,
    browser_launch,
    browser_manage,
    browser_media_extract,
    browser_media_state,
    browser_navigate,
    browser_network_log,
    browser_screenshot,
    browser_snapshot,
    browser_state,
    browser_status,
    browser_type,
    browser_wait_for,
    browser_workflow_start,
    browser_workflow_status,
    browser_workflow_step,
    close_browser,
    normalize_url,
)
from tools.calculator import evaluate_expression
from tools.diagnostics_tools import jarvis_latency_probe
from tools.entertainment_agent import (
    apply_track_lists,
    cached_track,
    canonical_text,
    entertainment_config,
    entertainment_equalizer,
    entertainment_history,
    entertainment_library,
    entertainment_lyrics,
    entertainment_metadata,
    entertainment_mood,
    entertainment_play,
    entertainment_playback,
    entertainment_playlist,
    entertainment_podcast,
    entertainment_queue,
    entertainment_radio,
    entertainment_recommend,
    entertainment_share,
    entertainment_session,
    entertainment_status,
    load_config,
    load_index,
    load_state,
    save_index,
    stable_track_id,
)
from tools.filesystem_tools import display_name, get_file_info, list_directory, read_text_file, search_text_files
from tools.google_auth import dependency_status
from tools.instagram_agent import instagram_config, instagram_manage, instagram_status
from tools.memory_wiki import wiki_apply, wiki_lint, wiki_search, wiki_status
from tools.path_resolver import resolve_local_path
from tools.productivity_agent import calendar_api, calendar_manage, display_text, github_manage, gmail_api, gmail_manage, productivity_config, productivity_status
from tools.research_agent import (
    research_extract_claims,
    research_plan,
    research_rank_sources,
    research_run,
    research_save,
    research_search,
    research_status,
    research_synthesize,
    research_verify_claims,
    research_watchlist,
)
from tools.registry import ToolInputError
from tools.runtime_info import get_runtime_info
from tools.skill_workshop import skill_workshop
from tools.system_tools import get_pc_status, get_system_info
from tools.terminal import resolve_shell_name, run_terminal
from tools.text_tools import generate_uuid, hash_text, text_stats
from tools.utility_tools import compare_text, transform_text
from tools.web_tools import document_extract_text, parse_duckduckgo_results, readable_text, summarize_readable_text
from tools.workspace_tools import workspace_inspect
from vector_memory import VectorMemoryConfig, build_vector_index, embed_texts, load_vector_memory_context, vector_search
from voice_system import (
    VoiceConfig,
    VoiceError,
    VoiceSpeaker,
    listen_after_output_idle,
    load_voice_profile,
    normalized_energy_threshold,
    output_sample_rate,
    read_text_or_voice,
    short_voice_error,
    speech_chunks,
    speech_threshold,
    speakable_text,
    transcript_from_asr_response,
    tts_input_text,
)


class ToolRegistryTests(unittest.TestCase):
    def test_entertainment_agent_has_no_duplicate_top_level_functions(self) -> None:
        module = ast.parse(Path("tools/entertainment_agent.py").read_text(encoding="utf-8"))
        seen: dict[str, int] = {}
        duplicates: list[tuple[str, int, int]] = []
        for node in module.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in seen:
                    duplicates.append((node.name, seen[node.name], node.lineno))
                else:
                    seen[node.name] = node.lineno
        self.assertEqual([], duplicates)

    def test_discovers_registered_tools(self) -> None:
        registry = discover_tools()
        names = [tool.name for tool in registry.visible_tools()]
        self.assertIn("calculate", names)
        self.assertIn("browser_status", names)
        self.assertIn("browser", names)
        self.assertIn("browser_manage", names)
        self.assertIn("browser_launch", names)
        self.assertIn("browser_snapshot", names)
        self.assertIn("browser_state", names)
        self.assertIn("browser_find_element", names)
        self.assertIn("browser_workflow_start", names)
        self.assertIn("browser_network_log", names)
        self.assertIn("browser_media_state", names)
        self.assertIn("get_current_datetime", names)
        self.assertIn("get_weather", names)
        self.assertIn("run_terminal", names)
        self.assertIn("get_runtime_info", names)
        self.assertIn("get_system_info", names)
        self.assertIn("get_pc_status", names)
        self.assertIn("list_directory", names)
        self.assertIn("read_text_file", names)
        self.assertIn("get_file_info", names)
        self.assertIn("search_text_files", names)
        self.assertIn("text_stats", names)
        self.assertIn("hash_text", names)
        self.assertIn("generate_uuid", names)
        self.assertIn("fetch_url_text", names)
        self.assertIn("list_registered_tools", names)
        self.assertIn("web_search", names)
        self.assertIn("extract_url_content", names)
        self.assertIn("document_extract_text", names)
        self.assertIn("wiki_status", names)
        self.assertIn("wiki_search", names)
        self.assertIn("wiki_get", names)
        self.assertIn("wiki_apply", names)
        self.assertIn("wiki_lint", names)
        self.assertIn("memory_vector_status", names)
        self.assertIn("memory_vector_reindex", names)
        self.assertIn("memory_vector_search", names)
        self.assertIn("skill_workshop", names)
        self.assertIn("run_jarvis_qa", names)
        self.assertIn("transform_text", names)
        self.assertIn("compare_text", names)
        self.assertIn("workspace_inspect", names)
        self.assertIn("jarvis_latency_probe", names)
        self.assertIn("entertainment_status", names)
        self.assertIn("entertainment_session", names)
        self.assertIn("entertainment_library", names)
        self.assertIn("entertainment_search", names)
        self.assertIn("entertainment_download", names)
        self.assertIn("entertainment_play", names)
        self.assertIn("entertainment_stream_direct", names)
        self.assertIn("entertainment_playback", names)
        self.assertIn("entertainment_queue", names)
        self.assertIn("entertainment_playlist", names)
        self.assertIn("entertainment_mood", names)
        self.assertIn("entertainment_recommend", names)
        self.assertIn("entertainment_lyrics", names)
        self.assertIn("entertainment_radio", names)
        self.assertIn("entertainment_podcast", names)
        self.assertIn("entertainment_history", names)
        self.assertIn("entertainment_equalizer", names)
        self.assertIn("entertainment_metadata", names)
        self.assertIn("entertainment_share", names)
        self.assertIn("entertainment_config", names)
        self.assertIn("productivity_status", names)
        self.assertIn("github_manage", names)
        self.assertIn("gmail_api", names)
        self.assertIn("calendar_api", names)
        self.assertIn("productivity_config", names)
        self.assertIn("instagram_status", names)
        self.assertIn("instagram_config", names)
        self.assertIn("instagram_manage", names)
        self.assertIn("research_status", names)
        self.assertIn("research_plan", names)
        self.assertIn("research_run", names)
        self.assertIn("research_watchlist", names)

    def test_manifest_command_tool_runs_without_python_handler_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extension = root / "extensions" / "command-tools"
            scripts = extension / "scripts"
            scripts.mkdir(parents=True)
            script = scripts / "echo_tool.py"
            script.write_text(
                "\n".join(
                    [
                        "import json",
                        "import os",
                        "import sys",
                        "",
                        "params = json.loads(sys.stdin.read() or '{}')",
                        "message = str(params.get('message', ''))",
                        "print(json.dumps({",
                        "    'message': message.upper(),",
                        "    'tool': os.environ.get('JARVIS_TOOL_NAME'),",
                        "    'has_workspace': bool(os.environ.get('JARVIS_WORKSPACE')),",
                        "}))",
                    ]
                ),
                encoding="utf-8",
            )
            (extension / "extension.json").write_text(
                json.dumps(
                    {
                        "id": "command-tools",
                        "name": "Command Tools",
                        "tools": [
                            {
                                "name": "manifest_command_echo",
                                "description": "Echo a message through a manifest-declared command.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"message": {"type": "string"}},
                                    "required": ["message"],
                                },
                                "executor": {
                                    "type": "command",
                                    "command": [sys.executable, "{extension_root}/scripts/echo_tool.py"],
                                    "output": "json",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            catalog = load_extension_catalog(root / "extensions")
            registry = discover_tools(extension_catalog=catalog)
            payload = json.loads(registry.execute("manifest_command_echo", {"message": "jarvis"}))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["json"]["message"], "JARVIS")
        self.assertEqual(payload["result"]["json"]["tool"], "manifest_command_echo")
        self.assertTrue(payload["result"]["json"]["has_workspace"])

    def test_manifest_command_tool_failure_is_reported_as_tool_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extension = root / "extensions" / "command-tools"
            scripts = extension / "scripts"
            scripts.mkdir(parents=True)
            script = scripts / "fail_tool.py"
            script.write_text(
                "\n".join(
                    [
                        "import sys",
                        "print('visible stdout')",
                        "print('visible stderr', file=sys.stderr)",
                        "raise SystemExit(7)",
                    ]
                ),
                encoding="utf-8",
            )
            (extension / "extension.json").write_text(
                json.dumps(
                    {
                        "id": "command-tools",
                        "tools": [
                            {
                                "name": "manifest_command_fail",
                                "description": "Fail through a manifest-declared command.",
                                "parameters": {"type": "object", "properties": {}},
                                "executor": {
                                    "type": "command",
                                    "command": [sys.executable, "{extension_root}/scripts/fail_tool.py"],
                                    "output": "text",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            catalog = load_extension_catalog(root / "extensions")
            registry = discover_tools(extension_catalog=catalog)
            payload = json.loads(registry.execute("manifest_command_fail", {}))

        self.assertFalse(payload["ok"])
        self.assertIn("exited with code 7", payload["error"])
        self.assertIn("visible stdout", payload["error"])
        self.assertIn("visible stderr", payload["error"])

    def test_calculator_evaluates_numeric_expression(self) -> None:
        result = evaluate_expression({"expression": "2 + 3 * 4"})
        self.assertEqual(result["result"], 14)

    def test_calculator_rejects_non_numeric_expression(self) -> None:
        with self.assertRaises(ToolInputError):
            evaluate_expression({"expression": "__import__('os').system('whoami')"})

    def test_json_tool_request_parses_registered_tool(self) -> None:
        registry = discover_tools()
        requests = parse_tool_requests(
            '{"name":"get_current_datetime","parameters":{"timezone":"Asia/Kolkata"}}',
            registry,
        )
        self.assertEqual(
            requests,
            [{"name": "get_current_datetime", "parameters": {"timezone": "Asia/Kolkata"}}],
        )

    def test_embedded_json_tool_request_parses_registered_tool(self) -> None:
        registry = discover_tools()
        requests = parse_tool_requests(
            'Need this {"name":"calculate","parameters":{"expression":"2 + 2"}} first.',
            registry,
        )
        self.assertEqual(requests, [{"name": "calculate", "parameters": {"expression": "2 + 2"}}])

    def test_truncated_tool_calls_wrapper_recovers_inner_call(self) -> None:
        registry = discover_tools()
        requests = parse_tool_requests(
            '{"tool_calls":[{"name":"text_stats","parameters":{"text":"hello world"}}]',
            registry,
        )
        self.assertEqual(requests, [{"name": "text_stats", "parameters": {"text": "hello world"}}])

    def test_empty_tool_calls_stop_later_junk(self) -> None:
        registry = discover_tools()
        requests = parse_tool_requests(
            '{"tool_calls":[]}{"name":"save_memory","parameters":{"content":"No memory."}}',
            registry,
        )
        self.assertEqual(requests, [])

    def test_tool_request_parser_drops_unresolved_placeholder_parameters(self) -> None:
        registry = discover_tools()
        requests = parse_tool_requests(
            '{"tool_calls":[{"name":"entertainment_playlist","parameters":{"operation":"list"}},{"name":"entertainment_playlist","parameters":{"operation":"show","playlist":"<playlist_name>"}}]}',
            registry,
        )

        self.assertEqual(requests, [{"name": "entertainment_playlist", "parameters": {"operation": "list"}}])
        self.assertTrue(contains_unresolved_placeholder({"playlist": "<playlist_name>"}))

    def test_tool_modules_do_not_register_tools_in_code(self) -> None:
        for path in Path("tools").glob("*.py"):
            if path.name in {"__init__.py", "registry.py"}:
                continue
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("def register(", content)
            self.assertNotIn("registry.register(", content)

    def test_terminal_tool_runs_command(self) -> None:
        result = run_terminal(
            {
                "command": "Write-Output jarvis-terminal-ok",
                "shell": "powershell",
                "timeout_seconds": 10,
                "max_output_chars": 1000,
            }
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("jarvis-terminal-ok", result["stdout"])
        self.assertIn("jarvis-terminal-ok", result["user_output"])

    def test_terminal_background_action_returns_done(self) -> None:
        result = run_terminal(
            {
                "command": "cmd /c exit 0",
                "background": True,
                "timeout_seconds": 10,
            }
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["background"])
        self.assertEqual(result["user_output"], "Started.")

    def test_terminal_system_shell_uses_configured_shell(self) -> None:
        with patch.dict(os.environ, {"JARVIS_TERMINAL_SHELL": "powershell"}, clear=False):
            self.assertEqual(resolve_shell_name("system"), "powershell")
        with patch.dict(os.environ, {"JARVIS_TERMINAL_SHELL": ""}, clear=False):
            self.assertEqual(resolve_shell_name("system"), "system")

    def test_basic_grounded_tools(self) -> None:
        self.assertEqual(text_stats({"text": "hello world"})["words"], 2)
        self.assertEqual(hash_text({"text": "abc", "algorithm": "sha256"})["hash"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertIn("uuid", generate_uuid({}))
        self.assertIn("system", get_system_info({}))

    def test_content_tools_transform_and_compare(self) -> None:
        formatted = transform_text({"operation": "json_format", "text": '{"b":2,"a":1}', "indent": 2})
        self.assertIn('"a": 1', formatted["result"])
        encoded = transform_text({"operation": "base64_encode", "text": "Jarvis"})
        decoded = transform_text({"operation": "base64_decode", "text": encoded["result"]})
        self.assertEqual(decoded["result"], "Jarvis")
        diff = compare_text({"left": "one\ntwo", "right": "one\nthree"})
        self.assertTrue(diff["changed"])
        self.assertIn("three", diff["diff"])

    def test_filesystem_tools(self) -> None:
        current = list_directory({"path": ".", "limit": 5})
        self.assertGreaterEqual(current["count"], 1)
        self.assertIn("total_count", current)
        self.assertNotIn("path", current["entries"][0])
        self.assertIn("summary", current)
        self.assertNotIn('"path"', current["summary"])
        self.assertEqual(display_name("#🇯🇵𝙹𝚊𝚙𝚊𝚗.mp4"), "#Japan.mp4")
        info = get_file_info({"path": "README.md"})
        self.assertEqual(info["type"], "file")
        content = read_text_file({"path": "README.md", "max_chars": 100})
        self.assertIn("Jarvis", content["content"])
        matches = search_text_files({"path": "README.md", "query": "Jarvis", "max_files": 1})
        self.assertTrue(matches["matches"])

    def test_natural_folder_aliases_resolve_for_filesystem_and_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = root / "Downloads"
            downloads.mkdir()
            (downloads / "sample.txt").write_text("alias works", encoding="utf-8")
            config_path = root / "aliases.json"
            config_path.write_text(
                json.dumps(
                    {
                        "aliases": {
                            "download folder": str(downloads),
                        },
                        "search_roots": [str(root)],
                        "search_depth": 1,
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"JARVIS_PATH_ALIASES_CONFIG": str(config_path)}, clear=False):
                listed = list_directory({"path": "download folder", "limit": 5})
                listed_natural = list_directory({"path": "my download folder", "limit": 5})
                terminal = run_terminal(
                    {
                        "command": "Get-Location",
                        "cwd": "download folder",
                        "shell": "powershell",
                        "timeout_seconds": 10,
                        "max_output_chars": 2000,
                    }
                )

        self.assertEqual(Path(listed["path"]), downloads.resolve())
        self.assertEqual(Path(listed_natural["path"]), downloads.resolve())
        self.assertEqual(listed["entries"][0]["name"], "sample.txt")
        self.assertEqual(terminal["exit_code"], 0)
        self.assertIn(str(downloads.resolve()), terminal["stdout"])

    def test_explicit_new_paths_do_not_collapse_to_parent_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media").mkdir()
            target = resolve_local_path("media/browser-profile", root)

        self.assertEqual(target, (root / "media" / "browser-profile").resolve())

    def test_browser_agent_opens_and_snapshots_live_page(self) -> None:
        import importlib.util

        if importlib.util.find_spec("playwright") is None:
            self.skipTest("playwright is not installed")
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        edge = Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
        executable = chrome if chrome.exists() else edge
        if not executable.exists():
            self.skipTest("Chrome or Edge executable is not installed")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "browser.json"
            config_path.write_text(
                json.dumps(
                    {
                        "agent_name": "Test Browser Agent",
                        "headless": True,
                        "user_data_dir": str(root / "profile"),
                        "default_timeout_ms": 15000,
                        "screenshot_dir": str(root / "screens"),
                        "search_url_template": "https://example.com/?q={query}",
                        "browser_executable_candidates": [str(executable)],
                        "launch_args": ["--disable-dev-shm-usage"],
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "JARVIS_BROWSER_CONFIG": str(config_path),
                    "JARVIS_BROWSER_HEADLESS": "true",
                },
                clear=False,
            ):
                try:
                    status = browser_status({})
                    opened = browser_manage(
                        {
                            "operation": "open_url",
                            "url": "data:text/html,<title>Jarvis Browser Test</title><main>Hello Browser Agent</main>",
                        }
                    )
                    snapshot = browser_manage({"operation": "snapshot", "max_chars": 500})
                    screenshot = browser_manage({"operation": "screenshot"})
                    screenshot_exists = Path(screenshot["path"]).exists()
                finally:
                    close_browser()

        self.assertTrue(status["playwright_available"])
        self.assertEqual(Path(status["browser_executable"]), executable.resolve())
        self.assertEqual(opened["title"], "Jarvis Browser Test")
        self.assertIn("Hello Browser Agent", snapshot["text"])
        self.assertTrue(screenshot_exists)
        self.assertIn("screens", screenshot["path"])

    def test_browser_operator_surface_tracks_state_dom_network_workflow_and_media_live(self) -> None:
        import http.server
        import importlib.util
        import socketserver

        if importlib.util.find_spec("playwright") is None:
            self.skipTest("playwright is not installed")
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        edge = Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
        executable = chrome if chrome.exists() else edge
        if not executable.exists():
            self.skipTest("Chrome or Edge executable is not installed")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/api/data":
                    payload = b'{"status":"api-ok","price":123}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                html = b"""<!doctype html>
<html>
<head><title>Browser Operator Test</title></head>
<body>
<main>
  <h1>Operator Form</h1>
  <form id="booking">
    <label for="name">Name</label>
    <input id="name" name="name" aria-label="Name" autocomplete="name" required>
    <label id="from-label">From</label>
    <div id="from" role="combobox" contenteditable="true" aria-labelledby="from-label" aria-controls="from-options" aria-expanded="false" style="display:block; width:240px; min-height:24px; border:1px solid #777;"></div>
    <ul id="from-options" role="listbox" hidden>
      <li role="option" data-value="DEL" onclick="chooseFrom(this)">Delhi DEL</li>
      <li role="option" data-value="BOM" onclick="chooseFrom(this)">Mumbai BOM</li>
    </ul>
    <button id="submit" type="button" onclick="submitForm()">Submit</button>
  </form>
  <p id="api"></p>
  <p id="result"></p>
  <video id="player" controls></video>
</main>
<script>
async function submitForm() {
  const response = await fetch('/api/data');
  const data = await response.json();
  document.getElementById('api').textContent = data.status;
  document.getElementById('result').textContent = 'Hello ' + document.getElementById('name').value + ' from ' + document.getElementById('from').textContent;
}
document.getElementById('from').addEventListener('input', () => {
  document.getElementById('from-options').hidden = false;
  document.getElementById('from').setAttribute('aria-expanded', 'true');
});
function chooseFrom(item) {
  document.getElementById('from').textContent = item.textContent;
  document.getElementById('from-options').hidden = true;
  document.getElementById('from').setAttribute('aria-expanded', 'false');
}
</script>
</body>
</html>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        class Server(socketserver.TCPServer):
            allow_reuse_address = True

        server = Server(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "browser.json"
            config_path.write_text(
                json.dumps(
                    {
                        "agent_name": "Operator Test Browser Agent",
                        "profiles_dir": str(root / "profiles"),
                        "sessions_dir": str(root / "sessions"),
                        "screenshots_dir": str(root / "screens"),
                        "downloads_dir": str(root / "downloads"),
                        "recordings_dir": str(root / "recordings"),
                        "cache_dir": str(root / "cache"),
                        "default_profile": "operator",
                        "headless": True,
                        "default_timeout_ms": 15000,
                        "network_idle_timeout_ms": 500,
                        "browser_executable_candidates": [str(executable)],
                        "launch_args": ["--disable-dev-shm-usage"],
                        "network_interception": {
                            "enabled": True,
                            "capture_patterns": [],
                            "max_captured_responses": 20,
                            "max_response_body_chars": 2000,
                        },
                        "dom_snapshot": {
                            "max_elements_per_type": 25,
                            "include_hidden_inputs": True,
                            "include_accessibility_tree": True,
                            "max_text_per_element": 200,
                            "auto_snapshot_on_navigate": True,
                        },
                        "workflow": {
                            "max_steps_per_workflow": 10,
                            "step_timeout_seconds": 10,
                            "retry_attempts": 1,
                            "checkpoint_every_n_steps": 2,
                            "resume_on_restart": True,
                        },
                        "sites": {},
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "JARVIS_BROWSER_CONFIG": str(config_path),
                    "JARVIS_BROWSER_HEADLESS": "true",
                },
                clear=False,
            ):
                try:
                    launched = browser_launch({"profile_name": "operator", "headless": True})
                    session_id = launched["session_id"]
                    browser_intercept_start({"session_id": session_id, "patterns": ["/api/data"], "capture_bodies": True})
                    navigated = browser_navigate(
                        {
                            "session_id": session_id,
                            "url": f"http://127.0.0.1:{server.server_address[1]}/",
                            "capture_snapshot": True,
                        }
                    )
                    snapshot = browser_snapshot({"session_id": session_id})
                    found = browser_find_element({"session_id": session_id, "description": "name field"})
                    from_field = browser_find_element({"session_id": session_id, "description": "from field"})
                    browser_type({"session_id": session_id, "selector": "#name", "text": "Krish", "clear": True})
                    ref_snapshot = browser({"action": "snapshot", "targetId": session_id, "interactive": True, "compact": True})
                    from_ref = next(
                        item["ref"]
                        for item in ref_snapshot["refs"].values()
                        if item.get("selector") == from_field["selector"]
                    )
                    typed_from = browser(
                        {
                            "action": "act",
                            "targetId": session_id,
                            "request": {"kind": "type", "ref": from_ref, "text": "Delhi"},
                        }
                    )
                    browser_wait_for({"session_id": session_id, "condition": "element_appears", "selector": "#from-options [role='option']"})
                    options_snapshot = browser({"action": "snapshot", "targetId": session_id, "interactive": True, "compact": True})
                    option_ref = next(
                        item["ref"]
                        for item in options_snapshot["refs"].values()
                        if item.get("text") == "Delhi DEL"
                    )
                    browser(
                        {
                            "action": "act",
                            "targetId": session_id,
                            "request": {"kind": "click", "ref": option_ref},
                        }
                    )
                    browser_click({"session_id": session_id, "selector": "#submit"})
                    browser_wait_for({"session_id": session_id, "condition": "text_appears", "text": "Hello Krish from Delhi DEL"})
                    page_text_result = browser_get_text({"session_id": session_id, "selector": "#result", "max_chars": 100})
                    network = browser_network_log({"session_id": session_id, "limit": 10, "include_bodies": True})
                    media_state = browser_media_state({"session_id": session_id})
                    media_extract = browser_media_extract({"session_id": session_id})
                    detected = browser_detect_state({"session_id": session_id})
                    workflow = browser_workflow_start({"session_id": session_id, "type": "form_fill", "parameters": {"fields": {"name": "Krish"}}})
                    workflow_step = browser_workflow_step({"session_id": session_id})
                    workflow_status = browser_workflow_status({"session_id": session_id})
                    screenshot = browser_screenshot({"session_id": session_id})
                    state = browser_state({"session_id": session_id})
                    snapshot_exists = Path(snapshot["snapshot_path"]).exists()
                    screenshot_exists = Path(screenshot["path"]).exists()
                finally:
                    close_browser()
                    server.shutdown()
                    server.server_close()

        self.assertEqual(navigated["title"], "Browser Operator Test")
        self.assertIn("inputs", snapshot["interactive_elements"])
        self.assertIn("comboboxes", snapshot["interactive_elements"])
        self.assertTrue(snapshot_exists)
        self.assertEqual(found["selector"], "#name")
        self.assertEqual(from_field["selector"], "#from")
        self.assertIn(typed_from["result"]["strategy"], {"filled_element", "clicked_and_typed", "dom_input_event"})
        self.assertIn("Delhi DEL", options_snapshot["snapshot"])
        self.assertIn("Hello Krish from Delhi DEL", page_text_result["text"])
        self.assertTrue(any("/api/data" in entry.get("url", "") for entry in network["entries"]))
        self.assertEqual(len(media_state["state"]["media"]), 1)
        self.assertEqual(media_extract["title"], "Browser Operator Test")
        self.assertEqual(detected["state"], "form")
        self.assertEqual(workflow["workflow"]["name"], "form_fill")
        self.assertEqual(workflow_step["workflow"]["current_step"], 1)
        self.assertEqual(workflow_status["workflow"]["status"], "running")
        self.assertTrue(screenshot_exists)
        self.assertEqual(state["current_title"], "Browser Operator Test")

    def test_browser_url_normalization_is_config_free(self) -> None:
        self.assertEqual(normalize_url("example.com"), "https://example.com")
        self.assertEqual(normalize_url("https://example.com"), "https://example.com")
        self.assertEqual(normalize_url("data:text/html,hi"), "data:text/html,hi")

    def test_console_stream_encoding_is_utf8_safe_when_supported(self) -> None:
        class FakeStream:
            def __init__(self) -> None:
                self.calls: list[dict[str, str]] = []

            def reconfigure(self, **kwargs: str) -> None:
                self.calls.append(kwargs)

        stream = FakeStream()

        self.assertTrue(configure_stream_encoding(stream))
        self.assertEqual(stream.calls, [{"encoding": "utf-8", "errors": "replace"}])

    def test_workspace_inspect_tools(self) -> None:
        status = workspace_inspect({"operation": "git_status"})
        self.assertIn("Branch:", status["summary"])
        tree = workspace_inspect({"operation": "project_tree", "path": ".", "depth": 1, "limit": 10})
        self.assertTrue(tree["entries"])
        digest = workspace_inspect({"operation": "file_hash", "path": "README.md", "algorithm": "sha256"})
        self.assertEqual(len(digest["hash"]), 64)

    def test_runtime_info_reports_current_python_process(self) -> None:
        result = get_runtime_info({})
        self.assertEqual(result["python_version"], platform.python_version())
        self.assertEqual(result["python_executable"], sys.executable)

    def test_pc_status_returns_human_summary(self) -> None:
        result = get_pc_status({})
        self.assertIn("summary", result)
        self.assertIn("OS:", result["summary"])
        self.assertIn("Architecture:", result["summary"])

    def test_html_fetch_text_becomes_readable_text(self) -> None:
        text = readable_text(
            '<!doctype html><html><head><title>Example Domain</title><style>bad</style></head><body><h1>Example Domain</h1><script>bad</script><p>Hello world.</p></body></html>',
            "text/html",
        )
        self.assertIn("Example Domain", text)
        self.assertIn("Hello world.", text)
        self.assertNotIn("<html", text)
        summary = summarize_readable_text(text, "https://example.com")
        self.assertIn("Example Domain", summary)
        self.assertIn("Hello world.", summary)

    def test_memory_reads_user_text_file(self) -> None:
        root = Path("test-memory-tmp")
        root.mkdir(exist_ok=True)
        try:
            (root / "user.txt").write_text("User\n\n- Likes fast local tools\n", encoding="utf-8")
            config = MemoryConfig(
                root=root,
                max_context_chars=2000,
                max_file_chars=1000,
                include_transcripts=False,
                extract_enabled=False,
                extract_background=False,
                extract_max_tokens=100,
                context_prompt_file=Path("prompts/memory_context.txt"),
            )
            context = load_memory_context(config)
            self.assertIn("Likes fast local tools", context)
        finally:
            for path in sorted(root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            if root.exists():
                root.rmdir()

    def test_memory_extractor_accepts_prose_fallback(self) -> None:
        items = prose_memory_fallback("- User prefers JSON or Markdown tool definitions.")
        self.assertEqual(items, ["User prefers JSON or Markdown tool definitions."])

    def test_memory_extractor_accepts_fenced_json_array(self) -> None:
        parsed = parse_memory_json('```json\n["User prefers JSON tool manifests."]\n```')
        self.assertEqual(parsed, ["User prefers JSON tool manifests."])

    def test_extension_catalog_loads_prompt_skills_and_tools(self) -> None:
        catalog = load_extension_catalog()
        extension_ids = [extension.id for extension in catalog.extensions]
        self.assertIn("web", extension_ids)
        self.assertIn("browser-agent", extension_ids)
        self.assertIn("instagram-agent", extension_ids)
        self.assertIn("research-agent", extension_ids)
        self.assertTrue(any(tool.get("name") == "web_search" for tool in catalog.tool_descriptors()))
        self.assertTrue(any(tool.get("name") == "browser" for tool in catalog.tool_descriptors()))
        self.assertTrue(any(tool.get("name") == "browser_manage" for tool in catalog.tool_descriptors()))
        self.assertTrue(any(tool.get("name") == "browser_workflow_start" for tool in catalog.tool_descriptors()))
        self.assertTrue(any(tool.get("name") == "browser_snapshot" for tool in catalog.tool_descriptors()))
        self.assertTrue(any(tool.get("name") == "instagram_manage" for tool in catalog.tool_descriptors()))
        self.assertTrue(any(tool.get("name") == "gmail_api" for tool in catalog.tool_descriptors()))
        self.assertTrue(any(tool.get("name") == "calendar_api" for tool in catalog.tool_descriptors()))
        self.assertTrue(any(tool.get("name") == "research_run" for tool in catalog.tool_descriptors()))
        self.assertIn("Web And Document Tools", catalog.prompt_context())
        self.assertIn("Browser Agent Protocol", catalog.prompt_context())
        self.assertIn("Instagram Agent Protocol", catalog.prompt_context())
        self.assertIn("Research Agent Protocol", catalog.prompt_context())
        self.assertTrue(catalog.skill_roots())

    def test_jarvis_cli_lists_expanded_browser_tool_surface(self) -> None:
        completed = subprocess.run(
            [sys.executable, "main.py", "--list-tools"],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("- browser:", completed.stdout)
        self.assertIn("browser_snapshot", completed.stdout)
        self.assertIn("browser_workflow_start", completed.stdout)
        self.assertIn("browser_network_log", completed.stdout)

    def test_skill_context_loads_extension_skill_files(self) -> None:
        catalog = load_extension_catalog()
        with patch.dict(os.environ, {"JARVIS_SKILL_CONTEXT_CHARS": "30000"}, clear=False):
            context = load_skill_context(catalog, Path.cwd())
        self.assertIn("Skill: web-research", context)
        self.assertIn("Skill: browser-operator", context)
        self.assertIn("Skill: instagram-operator", context)
        self.assertIn("Skill: jarvis-qa", context)
        self.assertIn("Skill: research", context)

    def test_tool_manifests_do_not_define_canned_final_responses(self) -> None:
        manifest = Path("tools/tools.json").read_text(encoding="utf-8")
        self.assertNotIn("direct_response", manifest)
        for path in Path("extensions").glob("*/extension.json"):
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("display_templates", content)

    def test_duckduckgo_result_parser_extracts_results(self) -> None:
        html = (
            '<html><body><a class="result__a" '
            'href="/l/?uddg=https%3A%2F%2Fexample.com">Example Domain</a></body></html>'
        )
        results = parse_duckduckgo_results(html, 3)
        self.assertEqual(results, [{"title": "Example Domain", "url": "https://example.com"}])

    def test_research_agent_plans_from_config_and_status(self) -> None:
        status = research_status({})
        self.assertIn("Research Agent", status["summary"])
        self.assertIn("breaking_news", status["source_policies"])

        result = research_plan(
            {
                "topic": "AI agents latest news",
                "mode": "headlines",
                "quality": "fast",
                "time_window": "last 7 days",
            }
        )

        self.assertEqual(result["plan"]["mode"], "headlines")
        self.assertEqual(result["plan"]["quality"], "fast")
        self.assertEqual(result["plan"]["source_policy"], "breaking_news")
        self.assertGreaterEqual(len(result["plan"]["queries"]), 1)
        self.assertIn("AI agents latest news", result["plan"]["queries"][0]["query"])

    def test_research_search_uses_configured_provider_without_core_registration(self) -> None:
        payload = {
            "results": [
                {
                    "title": "Example Domain",
                    "url": "https://example.com/",
                    "content": "Example Domain page",
                    "score": 0.9,
                    "published_date": "2026-05-10T00:00:00Z",
                }
            ]
        }
        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}, clear=False):
            with patch("tools.research_agent.urllib.request.urlopen", return_value=FakeHttpResponse(payload)):
                result = research_search({"queries": [{"type": "test", "query": "Example Domain"}], "count": 1})

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["source_provider"], "tavily")
        self.assertEqual(result["results"][0]["publisher"], "example.com")

    def test_research_pipeline_ranks_verifies_synthesizes_and_saves(self) -> None:
        sentence = "Jarvis Research Agent gathers current sources, ranks evidence, and saves grounded dossiers for users."
        sources = [
            {
                "source_id": "s1",
                "ok": True,
                "url": "https://reuters.com/world/jarvis-research",
                "title": "Jarvis research update",
                "published_date": "2026-05-10T00:00:00+00:00",
                "text": sentence + " The system keeps memory separate from current source proof.",
                "text_hash": "one",
            },
            {
                "source_id": "s2",
                "ok": True,
                "url": "https://apnews.com/article/jarvis-research",
                "title": "Research agent evidence update",
                "published_date": "2026-05-10T00:00:00+00:00",
                "text": sentence + " Reports include source links and confidence labels.",
                "text_hash": "two",
            },
        ]

        ranked = research_rank_sources({"sources": sources, "source_policy": "general"})
        claims = research_extract_claims({"sources": ranked["ranked_sources"], "max_claims": 4})
        verified = research_verify_claims(
            {
                "claims": claims["claims"],
                "sources": ranked["ranked_sources"],
                "minimum_independent_sources": 2,
            }
        )
        synth = research_synthesize(
            {
                "verified_claims": verified["verified_claims"],
                "sources": ranked["ranked_sources"],
                "topic": "Jarvis Research Agent",
            }
        )

        self.assertEqual(len(ranked["ranked_sources"]), 2)
        self.assertGreaterEqual(claims["count"], 1)
        self.assertEqual(verified["verified_claims"][0]["confidence"], "high")
        self.assertEqual(len(synth["evidence_pack"]["source_list"]), 2)

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "research.json"
            config_path.write_text(
                json.dumps(
                    {
                        "dossier_dir": str(Path(tmp) / "dossiers"),
                        "cache_dir": str(Path(tmp) / "cache"),
                        "watchlist_path": str(Path(tmp) / "watchlists.json"),
                        "run_log_path": str(Path(tmp) / "runs.jsonl"),
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"JARVIS_RESEARCH_CONFIG": str(config_path)}, clear=False):
                saved = research_save({"topic": "Jarvis Research Agent", "evidence_pack": synth["evidence_pack"]})
                watch = research_watchlist({"operation": "upsert", "topic": "AI agents", "frequency": "weekly", "source_policy": "preferred"})
                listed = research_watchlist({"operation": "list"})
                report_exists = Path(saved["report_path"]).exists()
                evidence_exists = Path(saved["evidence_path"]).exists()

        self.assertTrue(report_exists)
        self.assertTrue(evidence_exists)
        self.assertTrue(watch["saved"])
        self.assertEqual(watch["watchlist"]["source_policy"], "general")
        self.assertEqual(listed["count"], 1)

    def test_research_run_executes_full_pipeline_with_mocked_external_io(self) -> None:
        source_a = {
            "source_id": "a",
            "ok": True,
            "url": "https://reuters.com/technology/ai-agents",
            "title": "AI agents research",
            "published_date": "2026-05-10T00:00:00+00:00",
            "text": "AI agent systems now combine planning, tool use, source reading, and verification before writing reports.",
            "text_hash": "a",
        }
        source_b = {
            "source_id": "b",
            "ok": True,
            "url": "https://openai.com/research/agents",
            "title": "Agent systems",
            "published_date": "2026-05-10T00:00:00+00:00",
            "text": "AI agent systems now combine planning, tool use, source reading, and verification before writing reports.",
            "text_hash": "b",
        }
        search_results = [
            {"title": source_a["title"], "url": source_a["url"], "source_provider": "test"},
            {"title": source_b["title"], "url": source_b["url"], "source_provider": "test"},
        ]
        with patch("tools.research_agent.search_one_query", return_value=(search_results, [])):
            with patch("tools.research_agent.fetch_source", side_effect=[source_a, source_b]):
                result = research_run({"topic": "AI agents", "mode": "market_tech_trend", "quality": "fast", "max_sources": 2})

        self.assertEqual(result["plan"]["mode"], "market_tech_trend")
        self.assertEqual(result["pipeline"]["ranked_source_count"], 2)
        self.assertGreaterEqual(result["pipeline"]["verified_claim_count"], 1)
        self.assertTrue(result["evidence_pack"]["source_list"])
        self.assertIn("Confidence:", result["report_draft"])
        self.assertEqual(result["safe_user_output"], result["report_draft"])

    def test_document_extract_text_reads_local_text_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"
            path.write_text("Jarvis document extraction works.", encoding="utf-8")
            result = document_extract_text({"path": str(path)})
        self.assertIn("Jarvis document extraction works.", result["content"])
        self.assertIn("note.txt", result["summary"])

    def test_memory_wiki_tools_use_txt_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"JARVIS_MEMORY_DIR": str(Path(tmp) / "memory")}, clear=False):
                saved = wiki_apply(
                    {
                        "topic": "Live QA",
                        "content": "Jarvis QA should use the live CLI.",
                        "source": "unit test",
                        "mode": "replace",
                    }
                )
                self.assertTrue(saved["saved"])
                found = wiki_search({"query": "live CLI"})
                self.assertEqual(found["count"], 1)
                status = wiki_status({})
                self.assertEqual(status["page_count"], 1)
                lint = wiki_lint({})
                self.assertEqual(lint["finding_count"], 0)

    def test_entertainment_agent_config_cache_queue_and_favorites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "entertainment.json"
            library = root / "music"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_ENTERTAINMENT_CONFIG": str(config_path),
                    "JARVIS_ENTERTAINMENT_LIBRARY_DIR": str(library),
                    "JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER": "true",
                },
                clear=False,
            ):
                config = load_config()
                self.assertEqual(config["agent_name"], "Codex Entertainment Agent")
                audio = library / "desi track.m4a"
                audio.parent.mkdir(parents=True, exist_ok=True)
                audio.write_bytes(b"fake")
                track_id = stable_track_id("yt-video-1")
                index = {
                    "tracks": {
                        track_id: {
                            "id": track_id,
                            "title": "Haryanvi Desi Track",
                            "file_path": str(audio),
                            "webpage_url": "https://www.youtube.com/watch?v=yt-video-1",
                        }
                    },
                    "aliases": {
                        canonical_text("haryanvi desi track"): track_id,
                    },
                }
                save_index(config, index)

                cached = cached_track(load_index(config), ["Haryanvi Desi Track"])
                self.assertIsNotNone(cached)
                self.assertEqual(cached["id"], track_id)

                apply_track_lists(config, track_id, True, "roadtrip")
                updated = load_config()
                self.assertIn(track_id, updated["favorites"])
                self.assertIn(track_id, updated["playlists"]["roadtrip"])

                play = entertainment_play({"query": "haryanvi desi track"})
                self.assertIn("Playing", play["summary"])

                queue = entertainment_queue({"operation": "add", "track_id": track_id})
                self.assertIn(track_id, queue["queue"])
                next_status = entertainment_queue({"operation": "next"})
                self.assertIn("Queue:", next_status["summary"])

                favorite = entertainment_playlist({"operation": "show", "playlist": "favorites"})
                self.assertEqual(len(favorite["tracks"]), 1)
                self.assertIn("Haryanvi Desi Track", favorite["summary"])
                playlists = entertainment_playlist({"operation": "list"})
                self.assertIn("roadtrip", playlists["summary"])
                self.assertIn("Haryanvi Desi Track", playlists["summary"])
                default_play = entertainment_playlist({"operation": "play"})
                self.assertIn(track_id, default_play["queue"])
                self.assertEqual(default_play["tracks"][0]["title"], "Haryanvi Desi Track")
                alias_play = entertainment_playlist({"operation": "play", "playlist": "my saved playlist"})
                self.assertIn(track_id, alias_play["queue"])

                status = entertainment_status({})
                self.assertIn("local tracks", status["summary"])

    def test_entertainment_config_updates_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "entertainment.json"
            with patch.dict(os.environ, {"JARVIS_ENTERTAINMENT_CONFIG": str(config_path)}, clear=False):
                result = entertainment_config(
                    {
                        "operation": "update",
                        "values": {
                            "preferred_music_context": ["Hindi songs", "Haryanvi songs"],
                            "search_limit": 7,
                        },
                    }
                )

                self.assertEqual(result["config"]["search_limit"], 7)
                self.assertIn("Haryanvi songs", config_path.read_text(encoding="utf-8"))

    def test_entertainment_os_tools_cover_user_facing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "entertainment.json"
            library = root / "music"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_ENTERTAINMENT_CONFIG": str(config_path),
                    "JARVIS_ENTERTAINMENT_LIBRARY_DIR": str(library),
                    "JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER": "true",
                },
                clear=False,
            ):
                entertainment_config(
                    {
                        "operation": "update",
                        "values": {
                            "lyrics_dir": str(root / "lyrics"),
                            "podcast_dir": str(root / "podcasts"),
                            "equalizer_dir": str(root / "eq"),
                            "radio": {
                                "saved_stations_path": str(root / "radio.json"),
                                "default_stations": {
                                    "test": {
                                        "name": "Test Radio",
                                        "query": "test radio",
                                        "language": "English",
                                        "url": "https://example.com/radio.mp3",
                                    }
                                },
                            },
                            "podcast": {"feeds_path": str(root / "feeds.json")},
                            "history": {"path": str(root / "history.json")},
                            "mood": {"context_path": str(root / "context.json")},
                        },
                    }
                )
                config = load_config()
                audio = library / "late night coding.m4a"
                second_audio = library / "focus drive.m4a"
                audio.parent.mkdir(parents=True, exist_ok=True)
                audio.write_bytes(b"fake")
                second_audio.write_bytes(b"fake")
                track_id = stable_track_id("night-drive")
                second_id = stable_track_id("focus-drive")
                index = {
                    "tracks": {
                        track_id: {
                            "id": track_id,
                            "type": "music",
                            "title": "Late Night Coding",
                            "artist": "Jarvis Test",
                            "language": "English",
                            "genre": ["lofi"],
                            "tags": ["coding"],
                            "mood_tags": ["calm", "night", "focus"],
                            "bpm": 72,
                            "rating": 5,
                            "file_path": str(audio),
                            "source_url": "https://www.youtube.com/watch?v=night-drive",
                            "duration_seconds": 120,
                            "aliases": ["late night coding"],
                        },
                        second_id: {
                            "id": second_id,
                            "type": "music",
                            "title": "Focus Drive",
                            "artist": "Jarvis Test",
                            "language": "English",
                            "genre": ["lofi"],
                            "tags": ["coding"],
                            "mood_tags": ["calm", "focus"],
                            "bpm": 78,
                            "rating": 4,
                            "file_path": str(second_audio),
                            "source_url": "https://www.youtube.com/watch?v=focus-drive",
                            "duration_seconds": 140,
                            "aliases": ["focus drive"],
                        },
                    },
                    "aliases": {
                        canonical_text("late night coding"): track_id,
                        canonical_text("focus drive"): second_id,
                    },
                }
                save_index(config, index)
                lyrics_dir = Path(config["lyrics_dir"])
                lyrics_dir.mkdir(parents=True, exist_ok=True)
                (lyrics_dir / f"{track_id}.lrc").write_text("[00:01.00]hello night\n[00:10.00]keep coding\n", encoding="utf-8")

                stats = entertainment_library({"operation": "stats"})
                self.assertEqual(stats["stats"]["total_tracks"], 2)
                search = entertainment_library({"operation": "search", "query": "night coding"})
                self.assertEqual(search["results"][0]["id"], track_id)

                mood = entertainment_mood({"operation": "match", "description": "calm night coding", "limit": 5})
                self.assertEqual(mood["tracks"][0]["id"], track_id)
                entertainment_mood({"operation": "set_context", "context": "working"})
                queue = entertainment_queue({"operation": "add", "track_ids": [track_id, second_id]})
                self.assertEqual(queue["queue"], [track_id, second_id])
                playing = entertainment_playback({"operation": "play"})
                self.assertEqual(playing["current_track"]["id"], track_id)
                volume = entertainment_playback({"operation": "volume", "value": 42})
                self.assertEqual(volume["volume"], 42)

                shown = entertainment_lyrics({"operation": "show", "track_id": track_id})
                self.assertTrue(shown["available"])
                current_line = entertainment_lyrics({"operation": "current_line", "track_id": track_id, "position_seconds": 11})
                self.assertEqual(current_line["line"], "keep coding")

                similar = entertainment_recommend({"operation": "similar", "track_id": track_id, "limit": 5})
                self.assertEqual(similar["tracks"][0]["id"], second_id)
                eq_created = entertainment_equalizer({"operation": "create", "profile": "focus-test", "bands": {"1000": 2}})
                self.assertIn("focus-test", eq_created["summary"])
                eq = entertainment_equalizer({"operation": "apply", "profile": "focus-test"})
                self.assertEqual(eq["profile"], "focus-test")

                metadata = entertainment_metadata({"operation": "write_tags", "track_id": track_id, "values": {"album": "Tests"}})
                self.assertEqual(metadata["track"]["album"], "Tests")
                history = entertainment_history({"operation": "stats", "range": "all"})
                self.assertGreaterEqual(history["stats"]["entry_count"], 1)
                share = entertainment_share({"operation": "now_playing"})
                self.assertIn("Late Night Coding", share["text"])

                radio = entertainment_radio({"operation": "play", "query": "test radio"})
                self.assertEqual(radio["station"]["name"], "Test Radio")

                rss = root / "feed.xml"
                rss.write_text(
                    "<rss><channel><title>Test Podcast</title><description>Tests</description>"
                    "<item><title>Episode One</title><description>Hello</description>"
                    "<enclosure url=\"https://example.com/episode.mp3\" type=\"audio/mpeg\" />"
                    "</item></channel></rss>",
                    encoding="utf-8",
                )
                subscribed = entertainment_podcast({"operation": "subscribe", "url": str(rss)})
                podcast_id = subscribed["podcast"]["id"]
                episodes = entertainment_podcast({"operation": "episodes", "podcast": podcast_id})
                self.assertEqual(episodes["episodes"][0]["title"], "Episode One")
                podcast_play = entertainment_podcast({"operation": "play_episode", "podcast": podcast_id})
                self.assertIn("Episode One", podcast_play["summary"])

                status = entertainment_status({})
                self.assertEqual(status["library"]["total_tracks"], 2)

    def test_entertainment_radio_curated_query_without_url_searches_real_station_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "entertainment.json"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_ENTERTAINMENT_CONFIG": str(config_path),
                    "JARVIS_ENTERTAINMENT_LIBRARY_DIR": str(Path(tmp) / "music"),
                    "JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER": "true",
                },
                clear=False,
            ):
                entertainment_config(
                    {
                        "operation": "update",
                        "values": {
                            "radio": {
                                "api_url": "https://radio.test",
                                "saved_stations_path": str(Path(tmp) / "radio.json"),
                                "default_stations": {
                                    "punjabi": {
                                        "name": "Punjabi",
                                        "query": "Punjabi hits",
                                        "language": "Punjabi",
                                    }
                                },
                            }
                        },
                    }
                )
                payload = [
                    {
                        "stationuuid": "air-punjabi",
                        "name": "AIR Punjabi",
                        "url_resolved": "https://example.test/punjabi.m3u8",
                    }
                ]
                with patch("tools.entertainment_agent.urllib.request.urlopen", return_value=FakeHttpResponse(payload)) as open_call:
                    search = entertainment_radio({"operation": "search", "query": "Punjabi live radio", "limit": 5})
                    play = entertainment_radio({"operation": "play", "query": "Punjabi live radio"})

                self.assertEqual(search["stations"][0]["name"], "AIR Punjabi")
                self.assertEqual(play["station"]["name"], "AIR Punjabi")
                self.assertTrue(open_call.called)

    def test_entertainment_radio_play_failure_returns_safe_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "entertainment.json"
            with patch.dict(os.environ, {"JARVIS_ENTERTAINMENT_CONFIG": str(config_path)}, clear=False):
                entertainment_config(
                    {
                        "operation": "update",
                        "values": {
                            "radio": {
                                "saved_stations_path": str(Path(tmp) / "radio.json"),
                                "default_stations": {
                                    "punjabi": {
                                        "name": "AIR Punjabi",
                                        "url": "https://example.test/punjabi.m3u8",
                                    }
                                },
                            }
                        },
                    }
                )
                with patch(
                    "tools.entertainment_agent.choose_player_backend",
                    return_value={"name": "", "available": False, "supports_stream": False, "supports_eq": False},
                ):
                    result = entertainment_radio({"operation": "play", "query": "Punjabi"})

                self.assertFalse(result["action_completed"])
                self.assertIn("Direct streaming requires", result["safe_user_output"])
                self.assertEqual(result["station"]["name"], "AIR Punjabi")

    def test_entertainment_radio_play_can_use_latest_grounded_search_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "entertainment.json"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_ENTERTAINMENT_CONFIG": str(config_path),
                    "JARVIS_ENTERTAINMENT_LIBRARY_DIR": str(Path(tmp) / "music"),
                    "JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER": "true",
                },
                clear=False,
            ):
                entertainment_config(
                    {
                        "operation": "update",
                        "values": {
                            "radio": {
                                "api_url": "https://radio.test",
                                "saved_stations_path": str(Path(tmp) / "radio.json"),
                                "default_stations": {},
                            }
                        },
                    }
                )
                payload = [
                    {
                        "stationuuid": "air-punjabi",
                        "name": "AIR Punjabi",
                        "url_resolved": "https://example.test/punjabi.m3u8",
                    }
                ]
                with patch("tools.entertainment_agent.urllib.request.urlopen", return_value=FakeHttpResponse(payload)):
                    entertainment_radio({"operation": "search", "query": "Punjabi live radio", "limit": 1})
                    result = entertainment_radio({"operation": "play", "station_id": "best grounded station"})

                self.assertEqual(result["station"]["name"], "AIR Punjabi")
                self.assertEqual(result["backend"], "dry_run")

    def test_entertainment_radio_ranks_grounded_candidates_before_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "entertainment.json"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_ENTERTAINMENT_CONFIG": str(config_path),
                    "JARVIS_ENTERTAINMENT_LIBRARY_DIR": str(Path(tmp) / "music"),
                    "JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER": "true",
                },
                clear=False,
            ):
                entertainment_config(
                    {
                        "operation": "update",
                        "values": {
                            "radio": {
                                "api_url": "https://radio.test",
                                "saved_stations_path": str(Path(tmp) / "radio.json"),
                                "default_stations": {},
                                "search_candidate_limit": 5,
                            }
                        },
                    }
                )
                payload = [
                    {
                        "stationuuid": "general-news",
                        "name": "Morning News Radio",
                        "url_resolved": "https://example.test/general.m3u8",
                        "votes": 5000,
                        "lastcheckok": 1,
                    },
                    {
                        "stationuuid": "abc-news",
                        "name": "ABC News Radio",
                        "url_resolved": "https://example.test/abc.m3u8",
                        "votes": 10,
                        "lastcheckok": 1,
                    },
                ]
                with patch("tools.entertainment_agent.urllib.request.urlopen", return_value=FakeHttpResponse(payload)):
                    search = entertainment_radio({"operation": "search", "query": "ABC News Radio", "limit": 1})
                    play = entertainment_radio({"operation": "play", "query": "ABC News Radio"})

                self.assertEqual(search["stations"][0]["name"], "ABC News Radio")
                self.assertEqual(play["station"]["name"], "ABC News Radio")

    def test_entertainment_radio_play_without_query_uses_latest_grounded_search_when_idle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "entertainment.json"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_ENTERTAINMENT_CONFIG": str(config_path),
                    "JARVIS_ENTERTAINMENT_LIBRARY_DIR": str(Path(tmp) / "music"),
                    "JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER": "true",
                },
                clear=False,
            ):
                entertainment_config(
                    {
                        "operation": "update",
                        "values": {
                            "radio": {
                                "api_url": "https://radio.test",
                                "saved_stations_path": str(Path(tmp) / "radio.json"),
                                "default_stations": {},
                            }
                        },
                    }
                )
                payload = [
                    {
                        "stationuuid": "abc-news",
                        "name": "ABC News Radio",
                        "url_resolved": "https://example.test/abc.m3u8",
                        "votes": 10,
                        "lastcheckok": 1,
                    }
                ]
                with patch("tools.entertainment_agent.urllib.request.urlopen", return_value=FakeHttpResponse(payload)):
                    entertainment_radio({"operation": "search", "query": "ABC News Radio", "limit": 1})
                result = entertainment_radio({"operation": "play"})

                self.assertEqual(result["station"]["name"], "ABC News Radio")
                self.assertEqual(load_state(load_config())["active_media_type"], "radio")

    def test_entertainment_radio_replay_uses_current_station_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "entertainment.json"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_ENTERTAINMENT_CONFIG": str(config_path),
                    "JARVIS_ENTERTAINMENT_LIBRARY_DIR": str(Path(tmp) / "music"),
                    "JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER": "true",
                },
                clear=False,
            ):
                entertainment_config(
                    {
                        "operation": "update",
                        "values": {
                            "radio": {
                                "saved_stations_path": str(Path(tmp) / "radio.json"),
                                "default_stations": {
                                    "news": {
                                        "name": "Test News Radio",
                                        "query": "news radio",
                                        "country": "Testland",
                                        "url": "https://example.test/news.m3u8",
                                    }
                                },
                            }
                        },
                    }
                )
                first = entertainment_radio({"operation": "play", "query": "news radio"})
                replay = entertainment_radio({"operation": "play"})
                state = load_state(load_config())

                self.assertTrue(first["action_completed"])
                self.assertTrue(replay["action_completed"])
                self.assertEqual(replay["station"]["name"], "Test News Radio")
                self.assertEqual(state["active_media_type"], "radio")
                self.assertEqual(state["radio"]["station"]["name"], "Test News Radio")
                self.assertEqual(state["stream"]["url"], "https://example.test/news.m3u8")

    def test_entertainment_playback_replay_prefers_active_radio_over_stale_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "entertainment.json"
            library = root / "music"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_ENTERTAINMENT_CONFIG": str(config_path),
                    "JARVIS_ENTERTAINMENT_LIBRARY_DIR": str(library),
                    "JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER": "true",
                },
                clear=False,
            ):
                entertainment_config(
                    {
                        "operation": "update",
                        "values": {
                            "radio": {
                                "saved_stations_path": str(root / "radio.json"),
                                "default_stations": {
                                    "news": {
                                        "name": "Test News Radio",
                                        "query": "news radio",
                                        "url": "https://example.test/news.m3u8",
                                    }
                                },
                            }
                        },
                    }
                )
                config = load_config()
                audio = library / "local song.m4a"
                audio.parent.mkdir(parents=True, exist_ok=True)
                audio.write_bytes(b"fake")
                track_id = stable_track_id("local-song")
                save_index(
                    config,
                    {
                        "tracks": {
                            track_id: {
                                "id": track_id,
                                "type": "music",
                                "title": "Local Song",
                                "file_path": str(audio),
                            }
                        },
                        "aliases": {canonical_text("local song"): track_id},
                    },
                )
                entertainment_play({"query": "local song"})
                entertainment_radio({"operation": "play", "query": "news radio"})

                replay = entertainment_playback({"operation": "replay"})
                state = load_state(load_config())

                self.assertEqual(replay["station"]["name"], "Test News Radio")
                self.assertEqual(state["active_media_type"], "radio")
                self.assertEqual(state["radio"]["station"]["name"], "Test News Radio")

    def test_entertainment_favorite_without_query_uses_current_playing_track(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "entertainment.json"
            library = root / "music"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_ENTERTAINMENT_CONFIG": str(config_path),
                    "JARVIS_ENTERTAINMENT_LIBRARY_DIR": str(library),
                    "JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER": "true",
                },
                clear=False,
            ):
                config = load_config()
                audio = library / "current song.m4a"
                audio.parent.mkdir(parents=True, exist_ok=True)
                audio.write_bytes(b"fake")
                track_id = stable_track_id("current-song")
                save_index(
                    config,
                    {
                        "tracks": {
                            track_id: {
                                "id": track_id,
                                "type": "music",
                                "title": "Current Song",
                                "file_path": str(audio),
                                "source_url": "https://example.test/current-song",
                            }
                        },
                        "aliases": {},
                    },
                )
                entertainment_play({"track_id": track_id})

                favorite = entertainment_playlist({"operation": "add_favorite"})
                playlist_add = entertainment_playlist({"operation": "add_track", "playlist": "roadtrip"})

                self.assertEqual(favorite["track"]["id"], track_id)
                self.assertEqual(playlist_add["track"]["id"], track_id)
                updated = load_config()
                self.assertIn(track_id, updated["favorites"])
                self.assertIn(track_id, updated["playlists"]["roadtrip"])

    def test_entertainment_session_handles_thin_library_without_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "entertainment.json"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_ENTERTAINMENT_CONFIG": str(config_path),
                    "JARVIS_ENTERTAINMENT_LIBRARY_DIR": str(Path(tmp) / "music"),
                    "JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER": "true",
                },
                clear=False,
            ):
                result = entertainment_session(
                    {
                        "description": "calm focus low energy coding",
                        "context": "working",
                        "limit": 5,
                        "minimum_local_tracks": 2,
                        "scan": True,
                    }
                )

                self.assertFalse(result["action_completed"])
                self.assertIn("No downloads were started", result["summary"])
                self.assertIn("Evidence used:", result["safe_user_output"])
                self.assertIn("Search/download candidates:", result["safe_user_output"])
                self.assertTrue(result["search_candidates"])
                self.assertEqual(entertainment_mood({"operation": "get_context"})["context"], "working")

    def test_entertainment_session_queues_and_starts_matching_local_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "entertainment.json"
            library = root / "music"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_ENTERTAINMENT_CONFIG": str(config_path),
                    "JARVIS_ENTERTAINMENT_LIBRARY_DIR": str(library),
                    "JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER": "true",
                },
                clear=False,
            ):
                config = load_config()
                first = library / "focus one.m4a"
                second = library / "focus two.m4a"
                first.parent.mkdir(parents=True, exist_ok=True)
                first.write_bytes(b"fake")
                second.write_bytes(b"fake")
                first_id = stable_track_id("focus-one")
                second_id = stable_track_id("focus-two")
                save_index(
                    config,
                    {
                        "tracks": {
                            first_id: {
                                "id": first_id,
                                "type": "music",
                                "title": "Focus One",
                                "file_path": str(first),
                                "mood_tags": ["calm", "focus"],
                                "tags": ["coding"],
                            },
                            second_id: {
                                "id": second_id,
                                "type": "music",
                                "title": "Focus Two",
                                "file_path": str(second),
                                "mood_tags": ["calm", "focus"],
                                "tags": ["coding"],
                            },
                        },
                        "aliases": {},
                    },
                )

                result = entertainment_session(
                    {
                        "description": "calm focus coding",
                        "context": "working",
                        "limit": 2,
                        "minimum_local_tracks": 2,
                        "start_playback": True,
                        "playlist": "Coding Session",
                        "volume": 70,
                        "crossfade_seconds": 6,
                        "fetch_lyrics": True,
                        "include_history": True,
                        "target_minutes": 30,
                        "upcoming_limit": 1,
                    }
                )

                self.assertTrue(result["action_completed"])
                self.assertEqual(len(result["queue"]), 2)
                self.assertEqual(result["playlist"], "Coding Session")
                self.assertIn("Playing queue", result["playback"]["summary"])
                self.assertIn("Requested duration: 30 minute(s). Actual queued duration:", result["safe_user_output"])
                self.assertIn("Volume: 70.", result["safe_user_output"])
                self.assertIn("lyrics", result["safe_user_output"])

    def test_productivity_agent_builds_gmail_and_calendar_links_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "productivity.json"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_PRODUCTIVITY_CONFIG": str(config_path),
                    "JARVIS_PRODUCTIVITY_DRY_RUN": "true",
                },
                clear=False,
            ):
                status = productivity_status({})
                self.assertIn("github", status)
                gmail = gmail_manage({"operation": "compose", "to": "krish@example.com", "subject": "Hello Jarvis", "body": "Ship it"})
                calendar = calendar_manage(
                    {
                        "operation": "create_event",
                        "title": "Jarvis QA",
                        "details": "Live assistant test",
                        "start": "20260510T090000",
                        "end": "20260510T093000",
                    }
                )

        self.assertIn("krish%40example.com", gmail["url"])
        self.assertFalse(gmail["opened"])
        self.assertFalse(gmail["action_completed"])
        self.assertIn("Jarvis%20QA", calendar["url"])
        self.assertIn("20260510T090000%2F20260510T093000", calendar["url"])
        self.assertFalse(calendar["action_completed"])

    def test_productivity_google_api_status_is_grounded_without_login(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "productivity.json"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_PRODUCTIVITY_CONFIG": str(config_path),
                    "GOOGLE_OAUTH_CLIENT_SECRETS": str(Path(tmp) / "missing-client.json"),
                    "GMAIL_TOKEN_FILE": str(Path(tmp) / "missing-gmail-token.json"),
                    "GOOGLE_CALENDAR_TOKEN_FILE": str(Path(tmp) / "missing-calendar-token.json"),
                },
                clear=False,
            ):
                status = gmail_api({"operation": "auth_status"})
                calendar = calendar_api({"operation": "auth_status"})

        self.assertIn("dependencies", status)
        self.assertIn("token_exists", status)
        self.assertIn("client_secrets_exists", calendar)
        self.assertFalse(status["ready"])
        self.assertIn("not connected", status["status_text"])
        self.assertIn("not connected", calendar["status_text"])
        self.assertTrue(dependency_status()["googleapiclient"])

    def test_gmail_display_text_preserves_words_without_console_wide_symbols(self) -> None:
        text = display_text("Hi Krish, 📝Only 13 hours remain to ✍complete &amp; publish नमस्ते\u200d")

        self.assertIn("Only 13 hours remain to complete", text)
        self.assertIn("& publish", text)
        self.assertIn("नमस्ते", text)
        self.assertNotIn("📝", text)
        self.assertNotIn("\u200d", text)

    def test_gmail_api_list_messages_uses_google_service(self) -> None:
        class FakeMessages:
            def list(self, **_kwargs: object) -> object:
                return FakeExecute({"messages": [{"id": "m1"}], "resultSizeEstimate": 1})

            def get(self, **kwargs: object) -> object:
                return FakeExecute(
                    {
                        "id": kwargs["id"],
                        "threadId": "t1",
                        "snippet": "hello",
                        "payload": {"headers": [{"name": "Subject", "value": "Jarvis QA"}]},
                    }
                )

            def send(self, **_kwargs: object) -> object:
                return FakeExecute({"id": "sent1"})

        class FakeUsers:
            def messages(self) -> FakeMessages:
                return FakeMessages()

        class FakeService:
            def users(self) -> FakeUsers:
                return FakeUsers()

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "productivity.json"
            with patch.dict(os.environ, {"JARVIS_PRODUCTIVITY_CONFIG": str(config_path)}, clear=False):
                with patch("tools.productivity_agent.google_service", return_value=FakeService()) as service_call:
                    result = gmail_api({"operation": "list_messages", "query": "from:krish", "limit": 1, "allow_interactive_auth": True})
                    sent = gmail_api({"operation": "send", "to": "krish@example.com", "subject": "Hi", "body": "Ship", "allow_interactive_auth": True})

        self.assertEqual(result["messages"][0]["headers"]["Subject"], "Jarvis QA")
        self.assertEqual(sent["result"]["id"], "sent1")
        service_call.assert_called()

    def test_google_api_list_operations_return_grounded_not_connected_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "productivity.json"
            with patch.dict(
                os.environ,
                {
                    "JARVIS_PRODUCTIVITY_CONFIG": str(config_path),
                    "GOOGLE_OAUTH_CLIENT_SECRETS": str(Path(tmp) / "missing-client.json"),
                    "GMAIL_TOKEN_FILE": str(Path(tmp) / "missing-gmail-token.json"),
                    "GOOGLE_CALENDAR_TOKEN_FILE": str(Path(tmp) / "missing-calendar-token.json"),
                },
                clear=False,
            ):
                with patch("tools.productivity_agent.google_service") as service_call:
                    gmail = gmail_api({"operation": "list_messages", "limit": 5})
                    calendar = calendar_api({"operation": "list_events", "limit": 5})

        self.assertFalse(gmail["ready"])
        self.assertFalse(calendar["ready"])
        self.assertEqual(gmail["messages"], [])
        self.assertEqual(calendar["events"], [])
        self.assertIn("not connected", gmail["status_text"])
        self.assertIn("not connected", calendar["status_text"])
        self.assertEqual(gmail["safe_user_output"], gmail["status_text"])
        self.assertEqual(calendar["safe_user_output"], calendar["status_text"])
        service_call.assert_not_called()

    def test_gmail_send_honors_productivity_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "productivity.json"
            with patch.dict(
                os.environ,
                {"JARVIS_PRODUCTIVITY_CONFIG": str(config_path), "JARVIS_PRODUCTIVITY_DRY_RUN": "true"},
                clear=False,
            ):
                with patch("tools.productivity_agent.google_service") as service_call:
                    result = gmail_api({"operation": "send", "to": "krish@example.com", "subject": "Hi", "body": "Ship"})

        self.assertTrue(result["dry_run"])
        self.assertFalse(result["action_completed"])
        self.assertFalse(result["external_state_changed"])
        self.assertIn("No Gmail message was sent", result["summary"])
        self.assertIn("No external action happened", result["safe_user_output"])
        service_call.assert_not_called()

    def test_calendar_api_list_and_create_use_google_service(self) -> None:
        class FakeEvents:
            def list(self, **_kwargs: object) -> object:
                return FakeExecute({"items": [{"id": "e1", "summary": "Jarvis QA", "status": "confirmed"}]})

            def insert(self, **_kwargs: object) -> object:
                return FakeExecute({"id": "e2", "summary": "Created", "status": "confirmed"})

        class FakeService:
            def events(self) -> FakeEvents:
                return FakeEvents()

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "productivity.json"
            with patch.dict(os.environ, {"JARVIS_PRODUCTIVITY_CONFIG": str(config_path)}, clear=False):
                with patch("tools.productivity_agent.google_service", return_value=FakeService()):
                    listed = calendar_api({"operation": "list_events", "limit": 1, "allow_interactive_auth": True})
                    created = calendar_api(
                        {
                            "operation": "api_create_event",
                            "title": "Created",
                            "start": "2026-05-10T09:00:00+05:30",
                            "end": "2026-05-10T09:30:00+05:30",
                            "allow_interactive_auth": True,
                        }
                    )

        self.assertEqual(listed["events"][0]["summary"], "Jarvis QA")
        self.assertEqual(created["event"]["id"], "e2")

    def test_productivity_config_updates_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "productivity.json"
            with patch.dict(os.environ, {"JARVIS_PRODUCTIVITY_CONFIG": str(config_path)}, clear=False):
                result = productivity_config(
                    {
                        "operation": "update",
                        "values": {
                            "github": {"default_repo": "akyourowngames/A.N.K.I.T.A"},
                            "dry_run": True,
                        },
                    }
                )

        self.assertEqual(result["config"]["github"]["default_repo"], "akyourowngames/A.N.K.I.T.A")
        self.assertTrue(result["config"]["dry_run"])

    def test_github_manage_uses_gh_cli_without_shell(self) -> None:
        completed = subprocess.CompletedProcess(
            ["gh", "repo", "view"],
            0,
            stdout='{"nameWithOwner":"akyourowngames/A.N.K.I.T.A"}',
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "productivity.json"
            with patch.dict(os.environ, {"JARVIS_PRODUCTIVITY_CONFIG": str(config_path)}, clear=False):
                with patch("tools.productivity_agent.subprocess.run", return_value=completed) as run_call:
                    result = github_manage({"operation": "repo_view", "repo": "akyourowngames/A.N.K.I.T.A"})

        self.assertEqual(result["data"]["nameWithOwner"], "akyourowngames/A.N.K.I.T.A")
        called_args = run_call.call_args.args[0]
        self.assertEqual(called_args[:3], ["gh", "repo", "view"])
        self.assertIn("--repo", called_args)

    def test_instagram_agent_config_and_missing_dependency_are_grounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "instagram.json"
            with patch.dict(os.environ, {"JARVIS_INSTAGRAM_CONFIG": str(config_path), "INSTAGRAM_DRY_RUN": "true"}, clear=False):
                status = instagram_status({})
                updated = instagram_config(
                    {
                        "operation": "update",
                        "values": {
                            "monitored_profiles": ["nvidia"],
                            "rate_limit_seconds": 0,
                        },
                    }
                )
                dry_run = instagram_manage({"operation": "post_photo", "path": "README.md", "caption": "Jarvis QA"})

        self.assertIn("instagrapi_available", status)
        self.assertFalse(status["ready"])
        self.assertIn("not connected", status["status_text"])
        self.assertIn("nvidia", updated["config"]["monitored_profiles"])
        self.assertTrue(dry_run["dry_run"])
        self.assertFalse(dry_run["action_completed"])
        self.assertFalse(dry_run["external_state_changed"])
        self.assertIn("No external action happened", dry_run["safe_user_output"])

    def test_instagram_live_operation_requires_dependency_instead_of_faking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "instagram.json"
            with patch.dict(os.environ, {"JARVIS_INSTAGRAM_CONFIG": str(config_path), "INSTAGRAM_DRY_RUN": "false"}, clear=False):
                with self.assertRaises(ToolInputError):
                    instagram_manage({"operation": "profile", "username": "nvidia"})

    def test_vector_memory_indexes_and_searches_with_cached_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            root.mkdir()
            (root / "user.txt").write_text(
                "Name: Krish\nPreference: low latency vector memory for Jarvis\n",
                encoding="utf-8",
            )
            (root / "extracted.txt").write_text("Weather notes are unrelated.\n", encoding="utf-8")
            memory_config = MemoryConfig(
                root=root,
                max_context_chars=2000,
                max_file_chars=1000,
                include_transcripts=False,
                extract_enabled=False,
                extract_background=False,
                extract_max_tokens=100,
                context_prompt_file=Path("prompts/memory_context.txt"),
            )
            vector_config = VectorMemoryConfig(
                root=root,
                index_path=root / "vector" / "index.json",
                model="fake-embedding-model",
                chunk_chars=500,
                max_index_files=20,
                max_index_chunks=50,
                search_top_k=2,
                min_score=0.1,
                context_chars=1000,
                active=True,
                query_timeout_seconds=2.0,
                include_transcripts=False,
                background_reindex=False,
            )
            nim_config = JarvisConfig(
                api_key="test",
                chat_url="https://example.test/v1/chat/completions",
                model="chat",
                temperature=0,
                max_tokens=100,
                stream=False,
                stream_mode="native",
                synthetic_chunk_chars=48,
                synthetic_chunk_delay_seconds=0,
                timeout_seconds=10,
                retry_attempts=0,
                retry_delay_seconds=0,
                max_tool_rounds=1,
                tool_mode="json",
                auto_tools=True,
                system_prompt_file=Path("prompts/chat_system.txt"),
                persona_file=Path("prompts/persona.txt"),
                tool_protocol_file=Path("prompts/tool_protocol.txt"),
                user_name="Krish",
                assistant_name="JARVIS",
            )

            build = build_vector_index(memory_config, vector_config, nim_config, fake_memory_embedder)
            self.assertEqual(build["indexed_files"], 2)
            result = vector_search("Jarvis latency memory", vector_config, nim_config, fake_memory_embedder)
            self.assertTrue(result["matches"])
            self.assertIn("low latency vector memory", result["matches"][0]["text"])
            with patch("vector_memory.embed_texts", side_effect=fake_live_memory_embedder):
                context = load_vector_memory_context(
                    "what does Jarvis remember about latency",
                    memory_config,
                    vector_config,
                    nim_config,
                )
            self.assertIn("Relevant vector memory", context)
            self.assertIn("low latency vector memory", context)

    def test_vector_embedding_retries_temporary_throttle(self) -> None:
        nim_config = JarvisConfig(
            api_key="test",
            chat_url="https://example.test/v1/chat/completions",
            model="chat",
            temperature=0,
            max_tokens=100,
            stream=False,
            stream_mode="native",
            synthetic_chunk_chars=48,
            synthetic_chunk_delay_seconds=0,
            timeout_seconds=10,
            retry_attempts=0,
            retry_delay_seconds=0,
            max_tool_rounds=1,
            tool_mode="json",
            auto_tools=True,
            system_prompt_file=Path("prompts/chat_system.txt"),
            persona_file=Path("prompts/persona.txt"),
            tool_protocol_file=Path("prompts/tool_protocol.txt"),
            user_name="Krish",
            assistant_name="JARVIS",
        )
        throttle = urllib.error.HTTPError(
            "https://example.test/v1/embeddings",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b"slow down"),
        )
        response = FakeHttpResponse({"data": [{"embedding": [1.0, 2.0]}]})
        with patch.dict(
            os.environ,
            {"MEMORY_VECTOR_RETRY_ATTEMPTS": "1", "MEMORY_VECTOR_RETRY_DELAY_SECONDS": "0"},
            clear=False,
        ):
            with patch("vector_memory.urllib.request.urlopen", side_effect=[throttle, response]) as open_call:
                vectors = embed_texts(nim_config, ["Jarvis memory"], "passage")

        self.assertEqual(vectors, [[1.0, 2.0]])
        self.assertEqual(open_call.call_count, 2)

    def test_skill_workshop_can_apply_skill_without_core_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"JARVIS_SKILLS_DIR": str(Path(tmp) / "skills")}, clear=False):
                result = skill_workshop(
                    {
                        "action": "suggest",
                        "skill_name": "Live QA",
                        "title": "Live QA",
                        "body": "# Live QA\n\n- Run live Jarvis checks before shipping.",
                        "apply": True,
                    }
                )
                self.assertEqual(result["status"], "applied")
                read = skill_workshop({"action": "read", "skill_name": "Live QA"})
                self.assertIn("Run live Jarvis checks", read["content"])

    def test_tool_protocol_lives_outside_nim_client(self) -> None:
        client = Path("jarvis_nim.py").read_text(encoding="utf-8")
        protocol = Path("prompts/tool_protocol.txt").read_text(encoding="utf-8")
        self.assertIn("Local tool protocol:", protocol)
        self.assertIn("installed software", protocol)
        self.assertNotIn("Local tool protocol:", client)

    def test_tool_selector_prompt_lives_outside_nim_client(self) -> None:
        client = Path("jarvis_nim.py").read_text(encoding="utf-8")
        prompt = Path("prompts/tool_selector.txt").read_text(encoding="utf-8")
        self.assertIn("{tool_candidates}", prompt)
        self.assertIn("direct_response", prompt)
        self.assertNotIn("direct_response only when no local tool", client)

    def test_tool_results_prompt_lives_outside_nim_client(self) -> None:
        client = Path("jarvis_nim.py").read_text(encoding="utf-8")
        prompt = Path("prompts/tool_results.txt").read_text(encoding="utf-8")
        self.assertIn("Grounded local results:", prompt)
        self.assertNotIn("Grounded local results:", client)

    def test_tool_results_prompt_includes_display_name_context(self) -> None:
        prompt = tool_results_prompt([], "what is my name", "Krish")
        self.assertIn("Current user's display name:", prompt)
        self.assertIn("Krish", prompt)
        self.assertNotIn("{user_name}", prompt)

    def test_tool_results_prompt_does_not_expose_internal_tool_names(self) -> None:
        results = [
            {
                "name": "entertainment_playlist",
                "parameters": {"operation": "list"},
                "result": {"summary": "Playlists:\ndefault: 1 track(s) - License Ka Asla"},
            }
        ]

        prompt = tool_results_prompt(results, "show me playlist", "Krish")

        self.assertIn("License Ka Asla", prompt)
        self.assertNotIn("entertainment_playlist", prompt)
        self.assertNotIn("Clean tool summaries", prompt)
        self.assertEqual(public_tool_results(results)[0]["result_index"], 1)

    def test_tool_results_prompt_preserves_non_ascii_names_for_model(self) -> None:
        results = [
            {
                "name": "list_directory",
                "parameters": {"path": "download folder"},
                "result": {"ok": True, "result": {"entries": [{"name": "हिंदी-song.mp4"}]}},
            }
        ]

        prompt = tool_results_prompt(results, "list files in download folder", "Krish")

        self.assertIn("हिंदी-song.mp4", prompt)
        self.assertNotIn("\\u0939", prompt)
        self.assertIn("truncated=true", Path("prompts/tool_results.txt").read_text(encoding="utf-8"))
        self.assertIn("action_completed=false", Path("prompts/tool_results.txt").read_text(encoding="utf-8"))
        self.assertIn("No external action happened", Path("prompts/tool_results.txt").read_text(encoding="utf-8"))

    def test_public_tool_results_strip_internal_tool_field(self) -> None:
        payload = {"ok": True, "tool": "get_current_datetime", "result": {"date": "2026-05-09"}}

        public = public_result_payload(payload)

        self.assertNotIn("tool", public)
        self.assertEqual(public["result"]["date"], "2026-05-09")

    def test_public_tool_results_rename_count_when_total_count_exists(self) -> None:
        payload = {"ok": True, "result": {"count": 10, "total_count": 191, "truncated": True}}

        public = public_result_payload(payload)

        self.assertNotIn("count", public["result"])
        self.assertEqual(public["result"]["shown_count"], 10)
        self.assertEqual(public["result"]["total_count"], 191)

    def test_public_tool_results_rename_dry_run_operation(self) -> None:
        payload = {"ok": True, "result": {"operation": "api_create_event", "dry_run": True, "action_completed": False}}

        public = public_result_payload(payload)

        self.assertNotIn("operation", public["result"])
        self.assertEqual(public["result"]["requested_action"], "api_create_event")

    def test_chat_prompt_lives_outside_nim_client(self) -> None:
        client = Path("jarvis_nim.py").read_text(encoding="utf-8")
        prompt = Path("prompts/chat_system.txt").read_text(encoding="utf-8")
        self.assertIn("Answer normal chat naturally", prompt)
        self.assertNotIn("Answer normal chat naturally", client)

    def test_persona_lives_outside_nim_client(self) -> None:
        client = Path("jarvis_nim.py").read_text(encoding="utf-8")
        persona = Path("prompts/persona.txt").read_text(encoding="utf-8")
        self.assertIn("Jarvis Persona", persona)
        self.assertNotIn("Jarvis Persona", client)

    def test_stream_token_ignores_empty_chunks(self) -> None:
        self.assertEqual(stream_token({"choices": []}), "")

    def test_stream_reader_stops_on_done(self) -> None:
        response = io.BytesIO(
            b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n'
            b"data: [DONE]\n"
            b'data: {"choices":[{"delta":{"content":" late"}}]}\n'
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = read_streaming_response(response)
        self.assertEqual(result, "Hi")
        self.assertNotIn("late", output.getvalue())

    def test_native_tool_stream_reader_collects_tool_calls(self) -> None:
        response = io.BytesIO(
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"get_current_datetime","arguments":"{}"}}]}}]}\n'
            b"data: [DONE]\n"
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            requests, reply = read_native_tool_stream(response, discover_tools())
        self.assertEqual(requests, [{"name": "get_current_datetime", "parameters": {}}])
        self.assertEqual(reply, "")
        self.assertEqual(output.getvalue(), "")

    def test_native_tool_stream_reader_streams_content(self) -> None:
        response = io.BytesIO(
            b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n'
            b'data: {"choices":[{"delta":{"content":" Krish"}}]}\n'
            b"data: [DONE]\n"
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            requests, reply = read_native_tool_stream(response, discover_tools())
        self.assertEqual(requests, [])
        self.assertEqual(reply, "Hi Krish")
        self.assertIn("Hi Krish", output.getvalue())

    def test_native_tool_stream_reader_converts_json_content_tool_call(self) -> None:
        response = io.BytesIO(
            b'data: {"choices":[{"delta":{"content":"{\\"name\\":\\"get_current_datetime\\","}}]}\n'
            b'data: {"choices":[{"delta":{"content":"\\"parameters\\":{}}"}}]}\n'
            b"data: [DONE]\n"
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            requests, reply = read_native_tool_stream(response, discover_tools())
        self.assertEqual(requests, [{"name": "get_current_datetime", "parameters": {}}])
        self.assertEqual(reply, "")
        self.assertEqual(output.getvalue(), "")

    def test_native_tool_stream_reader_suppresses_malformed_json_content(self) -> None:
        response = io.BytesIO(
            b'data: {"choices":[{"delta":{"content":"{\\"name\\": \\"transform_text\\", \\"parameters\\": {\\"text\\": \\"{\\"x\\": 1}\\"}}"}}]}\n'
            b"data: [DONE]\n"
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            requests, reply = read_native_tool_stream(response, discover_tools())
        self.assertEqual(requests, [])
        self.assertEqual(reply, "")
        self.assertEqual(output.getvalue(), "")

    def test_default_stream_mode_is_native(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NVIDIA_API_KEY": "test-key",
                "NVIDIA_BASE_URL": "https://example.test/v1",
                "NVIDIA_MODEL": "test-model",
            },
            clear=False,
        ):
            os.environ.pop("NIM_STREAM_MODE", None)
            config = JarvisConfig.from_env()
        self.assertEqual(config.stream_mode, "native")

    def test_tool_planner_uses_env_model(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NVIDIA_API_KEY": "test-key",
                "NVIDIA_BASE_URL": "https://example.test/v1",
                "NVIDIA_MODEL": "chat-model",
                "NVIDIA_TOOL_MODEL": "tool-model",
            },
            clear=False,
        ):
            config = JarvisConfig.from_env()
            self.assertEqual(tool_planner_model(config), "tool-model")

    def test_tool_selector_uses_env_model(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NVIDIA_API_KEY": "test-key",
                "NVIDIA_BASE_URL": "https://example.test/v1",
                "NVIDIA_MODEL": "chat-model",
                "NVIDIA_TOOL_MODEL": "tool-model",
                "NVIDIA_TOOL_SELECTOR_MODEL": "selector-model",
            },
            clear=False,
        ):
            config = JarvisConfig.from_env()
            self.assertEqual(tool_selector_model(config), "selector-model")

    def test_selector_direct_response_skips_empty_planner_call(self) -> None:
        config = JarvisConfig(
            api_key="test",
            chat_url="https://example.test/v1/chat/completions",
            model="chat",
            temperature=0,
            max_tokens=100,
            stream=False,
            stream_mode="native",
            synthetic_chunk_chars=48,
            synthetic_chunk_delay_seconds=0,
            timeout_seconds=10,
            retry_attempts=0,
            retry_delay_seconds=0,
            max_tool_rounds=1,
            tool_mode="json",
            auto_tools=True,
            system_prompt_file=Path("prompts/chat_system.txt"),
            persona_file=Path("prompts/persona.txt"),
            tool_protocol_file=Path("prompts/tool_protocol.txt"),
            user_name="Krish",
            assistant_name="JARVIS",
        )
        registry = discover_tools()
        selector_payload = {"choices": [{"message": {"content": json.dumps({"tool_names": [], "direct_response": "Hi."})}}]}
        with patch.dict(os.environ, {"TOOL_PLANNER_DYNAMIC_SCHEMAS": "true", "TOOL_PLANNER_DYNAMIC_SCHEMA_MIN_TOOLS": "1"}, clear=False):
            with patch("jarvis_nim.post_json", return_value=selector_payload) as post_json_call:
                requests, reply = collect_tool_decision(config, [{"role": "user", "content": "hi"}], registry)

        self.assertEqual(requests, [])
        self.assertEqual(reply, "Hi.")
        self.assertEqual(post_json_call.call_count, 1)

    def test_selector_direct_response_with_history_falls_back_to_grounded_planner(self) -> None:
        config = JarvisConfig(
            api_key="test",
            chat_url="https://example.test/v1/chat/completions",
            model="chat",
            temperature=0,
            max_tokens=100,
            stream=False,
            stream_mode="native",
            synthetic_chunk_chars=48,
            synthetic_chunk_delay_seconds=0,
            timeout_seconds=10,
            retry_attempts=0,
            retry_delay_seconds=0,
            max_tool_rounds=1,
            tool_mode="json",
            auto_tools=True,
            system_prompt_file=Path("prompts/chat_system.txt"),
            persona_file=Path("prompts/persona.txt"),
            tool_protocol_file=Path("prompts/tool_protocol.txt"),
            user_name="Krish",
            assistant_name="JARVIS",
        )
        registry = discover_tools()
        selector_payload = {"choices": [{"message": {"content": json.dumps({"tool_names": [], "direct_response": "Today is 2024-02-20."})}}]}
        planner_payload = {"choices": [{"message": {"content": json.dumps({"name": "get_current_datetime", "parameters": {}})}}]}
        calls: list[dict[str, Any]] = []

        def fake_post_json(_config: JarvisConfig, payload: dict[str, Any]) -> dict[str, Any]:
            calls.append(payload)
            return selector_payload if len(calls) == 1 else planner_payload

        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello."},
            {"role": "user", "content": "what is the date today"},
        ]
        with patch.dict(os.environ, {"TOOL_PLANNER_DYNAMIC_SCHEMAS": "true", "TOOL_PLANNER_DYNAMIC_SCHEMA_MIN_TOOLS": "1"}, clear=False):
            with patch("jarvis_nim.post_json", side_effect=fake_post_json):
                requests, reply = collect_tool_decision(config, messages, registry)

        self.assertEqual(requests, [{"name": "get_current_datetime", "parameters": {}}])
        self.assertEqual(reply, "")
        self.assertEqual(len(calls), 2)

    def test_selector_direct_tool_call_skips_second_planner_call(self) -> None:
        config = JarvisConfig(
            api_key="test",
            chat_url="https://example.test/v1/chat/completions",
            model="chat",
            temperature=0,
            max_tokens=100,
            stream=False,
            stream_mode="native",
            synthetic_chunk_chars=48,
            synthetic_chunk_delay_seconds=0,
            timeout_seconds=10,
            retry_attempts=0,
            retry_delay_seconds=0,
            max_tool_rounds=1,
            tool_mode="json",
            auto_tools=True,
            system_prompt_file=Path("prompts/chat_system.txt"),
            persona_file=Path("prompts/persona.txt"),
            tool_protocol_file=Path("prompts/tool_protocol.txt"),
            user_name="Krish",
            assistant_name="JARVIS",
        )
        registry = discover_tools()
        selector_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"name": "get_current_datetime", "parameters": {"timezone": "Asia/Kolkata"}}
                        )
                    }
                }
            ]
        }
        with patch.dict(os.environ, {"TOOL_PLANNER_DYNAMIC_SCHEMAS": "true", "TOOL_PLANNER_DYNAMIC_SCHEMA_MIN_TOOLS": "1"}, clear=False):
            with patch("jarvis_nim.post_json", return_value=selector_payload) as post_json_call:
                requests, reply = collect_tool_decision(config, [{"role": "user", "content": "what time is it"}], registry)

        self.assertEqual(requests, [{"name": "get_current_datetime", "parameters": {"timezone": "Asia/Kolkata"}}])
        self.assertEqual(reply, "")
        self.assertEqual(post_json_call.call_count, 1)

    def test_manifest_can_keep_terminal_available_after_selector_subset(self) -> None:
        config = JarvisConfig(
            api_key="test",
            chat_url="https://example.test/v1/chat/completions",
            model="chat",
            temperature=0,
            max_tokens=100,
            stream=False,
            stream_mode="native",
            synthetic_chunk_chars=48,
            synthetic_chunk_delay_seconds=0,
            timeout_seconds=10,
            retry_attempts=0,
            retry_delay_seconds=0,
            max_tool_rounds=1,
            tool_mode="json",
            auto_tools=True,
            system_prompt_file=Path("prompts/chat_system.txt"),
            persona_file=Path("prompts/persona.txt"),
            tool_protocol_file=Path("prompts/tool_protocol.txt"),
            user_name="Krish",
            assistant_name="JARVIS",
        )
        registry = discover_tools()
        selector_payload = {"choices": [{"message": {"content": json.dumps({"tool_names": ["get_runtime_info"]})}}]}
        planner_payload = {
            "choices": [
                {"message": {"content": json.dumps({"name": "run_terminal", "parameters": {"command": "python --version"}})}}
            ]
        }
        calls: list[dict[str, Any]] = []

        def fake_post_json(_config: JarvisConfig, payload: dict[str, Any]) -> dict[str, Any]:
            calls.append(payload)
            return selector_payload if len(calls) == 1 else planner_payload

        with patch.dict(os.environ, {"TOOL_PLANNER_DYNAMIC_SCHEMAS": "true", "TOOL_PLANNER_DYNAMIC_SCHEMA_MIN_TOOLS": "1"}, clear=False):
            with patch("jarvis_nim.post_json", side_effect=fake_post_json):
                requests, reply = collect_tool_decision(config, [{"role": "user", "content": "check python version"}], registry)

        self.assertEqual(requests, [{"name": "run_terminal", "parameters": {"command": "python --version"}}])
        self.assertEqual(reply, "")
        self.assertEqual(len(calls), 2)
        planner_prompt = calls[1]["messages"][0]["content"]
        self.assertIn("run_terminal", planner_prompt)
        self.assertIn("get_runtime_info", planner_prompt)

    def test_tool_selection_parser_accepts_direct_response_only_when_no_tools(self) -> None:
        names, direct = tool_selection_from_selector_content(
            '{"tool_names":[],"direct_response":"Hello."}',
            {"calculate"},
        )
        self.assertEqual(names, [])
        self.assertEqual(direct, "Hello.")

        names, direct = tool_selection_from_selector_content(
            '{"tool_names":["calculate"],"direct_response":"Hello."}',
            {"calculate"},
        )
        self.assertEqual(names, ["calculate"])
        self.assertEqual(direct, "")

    def test_direct_single_tool_reply_uses_structured_tool_output(self) -> None:
        result = [
            {
                "name": "get_current_datetime",
                "parameters": {},
                "result": {
                    "ok": True,
                    "tool": "get_current_datetime",
                    "result": {"summary": "Current date and time: 2026-05-12 10:00:00 IST"},
                },
            }
        ]
        with patch.dict(os.environ, {"NIM_DIRECT_SINGLE_TOOL_RESULT": "true"}, clear=False):
            self.assertEqual(direct_single_tool_reply(result), "Current date and time: 2026-05-12 10:00:00 IST")

    def test_direct_single_tool_reply_does_not_hide_multi_tool_results(self) -> None:
        results = [
            {"result": {"ok": True, "result": {"summary": "one"}}},
            {"result": {"ok": True, "result": {"summary": "two"}}},
        ]
        with patch.dict(os.environ, {"NIM_DIRECT_SINGLE_TOOL_RESULT": "true"}, clear=False):
            self.assertEqual(direct_single_tool_reply(results), "")

    def test_planner_context_includes_recent_assistant_message(self) -> None:
        context = planner_turn_context(
            [
                {"role": "system", "content": "ignore"},
                {"role": "user", "content": "check python version"},
                {"role": "assistant", "content": "You are running Python 3.12.8."},
                {"role": "user", "content": "are you sure"},
            ]
        )
        self.assertIn("are you sure", context)
        self.assertIn("You are running Python 3.12.8.", context)
        self.assertNotIn("ignore", context)

    def test_native_stream_mode_uses_stream_endpoint(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NVIDIA_API_KEY": "test-key",
                "NVIDIA_BASE_URL": "https://example.test/v1",
                "NVIDIA_MODEL": "test-model",
                "NVIDIA_STREAM": "true",
                "NIM_STREAM_MODE": "native",
            },
            clear=False,
        ):
            config = JarvisConfig.from_env()

        with patch("jarvis_nim.post_stream", return_value="ok") as post_stream:
            reply = final_chat_response(config, [{"role": "user", "content": "hi"}])

        self.assertEqual(reply, "ok")
        post_stream.assert_called_once()

    def test_native_stream_no_tool_reply_gets_planner_fallback(self) -> None:
        config = JarvisConfig(
            api_key="test",
            chat_url="https://example.test/v1/chat/completions",
            model="chat",
            temperature=0,
            max_tokens=100,
            stream=True,
            stream_mode="native",
            synthetic_chunk_chars=48,
            synthetic_chunk_delay_seconds=0,
            timeout_seconds=10,
            retry_attempts=0,
            retry_delay_seconds=0,
            max_tool_rounds=1,
            tool_mode="native_stream",
            auto_tools=True,
            system_prompt_file=Path("prompts/chat_system.txt"),
            persona_file=Path("prompts/persona.txt"),
            tool_protocol_file=Path("prompts/tool_protocol.txt"),
            user_name="Krish",
            assistant_name="JARVIS",
        )
        registry = discover_tools()
        messages = [{"role": "user", "content": "calculate 2+2"}]
        with patch.dict(os.environ, {"NIM_NATIVE_VERIFY_NO_TOOL": "true"}, clear=False):
            with patch("jarvis_nim.collect_native_stream_tool_decision", return_value=([], "I can do that.")):
                with patch(
                    "jarvis_nim.collect_tool_requests",
                    return_value=[{"name": "calculate", "parameters": {"expression": "2 + 2"}}],
                ):
                    with patch("jarvis_nim.final_chat_response", return_value="It is 4.") as final_response:
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output):
                            reply = chat_with_native_streaming_tools(config, messages, registry)

        self.assertEqual(reply, "It is 4.")
        final_response.assert_called_once()
        self.assertNotIn("I can do that", output.getvalue())

    def test_native_stream_default_no_tool_does_not_wait_for_planner(self) -> None:
        config = JarvisConfig(
            api_key="test",
            chat_url="https://example.test/v1/chat/completions",
            model="chat",
            temperature=0,
            max_tokens=100,
            stream=True,
            stream_mode="native",
            synthetic_chunk_chars=48,
            synthetic_chunk_delay_seconds=0,
            timeout_seconds=10,
            retry_attempts=0,
            retry_delay_seconds=0,
            max_tool_rounds=1,
            tool_mode="native_stream",
            auto_tools=True,
            system_prompt_file=Path("prompts/chat_system.txt"),
            persona_file=Path("prompts/persona.txt"),
            tool_protocol_file=Path("prompts/tool_protocol.txt"),
            user_name="Krish",
            assistant_name="JARVIS",
        )
        registry = discover_tools()
        messages = [{"role": "user", "content": "hi"}]
        with patch.dict(os.environ, {"NIM_NATIVE_VERIFY_NO_TOOL": "false"}, clear=False):
            with patch("jarvis_nim.collect_native_stream_tool_decision", return_value=([], "Hi Krish.")):
                with patch("jarvis_nim.collect_tool_requests") as planner:
                    reply = chat_with_native_streaming_tools(config, messages, registry)

        self.assertEqual(reply, "Hi Krish.")
        planner.assert_not_called()

    def test_nim_retry_uses_retry_after_for_throttle(self) -> None:
        config = JarvisConfig(
            api_key="test",
            chat_url="https://example.test/v1/chat/completions",
            model="chat",
            temperature=0,
            max_tokens=100,
            stream=True,
            stream_mode="native",
            synthetic_chunk_chars=48,
            synthetic_chunk_delay_seconds=0,
            timeout_seconds=10,
            retry_attempts=1,
            retry_delay_seconds=0,
            max_tool_rounds=1,
            tool_mode="json",
            auto_tools=True,
            system_prompt_file=Path("prompts/chat_system.txt"),
            persona_file=Path("prompts/persona.txt"),
            tool_protocol_file=Path("prompts/tool_protocol.txt"),
            user_name="Krish",
            assistant_name="JARVIS",
        )
        headers = {"Retry-After": "0"}
        throttle = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            429,
            "Too Many Requests",
            headers,
            io.BytesIO(b"slow down"),
        )
        request = urllib.request.Request("https://example.test/v1/chat/completions")
        response = FakeHttpResponse({"ok": True})
        with patch("jarvis_nim.urllib.request.urlopen", side_effect=[throttle, response]) as open_call:
            result = open_url_with_retries(config, request)

        self.assertIs(result, response)
        self.assertEqual(open_call.call_count, 2)


class VoiceSystemTests(unittest.TestCase):
    def test_interactive_speech_commands_toggle_tts_output(self) -> None:
        voice_config = type("VoiceConfigStub", (), {"tts_enabled": True})()

        handled, enabled, message = interactive_speech_command("/speakoff", True, voice_config)
        self.assertTrue(handled)
        self.assertFalse(enabled)
        self.assertIn("off", message)

        handled, enabled, message = interactive_speech_command("/speakon", False, voice_config)
        self.assertTrue(handled)
        self.assertTrue(enabled)
        self.assertIn("on", message)

        handled, enabled, _message = interactive_speech_command("hello", False, voice_config)
        self.assertFalse(handled)
        self.assertFalse(enabled)

    def test_interactive_speech_on_stays_off_when_tts_disabled(self) -> None:
        voice_config = type("VoiceConfigStub", (), {"tts_enabled": False})()

        handled, enabled, message = interactive_speech_command("/speakon", False, voice_config)

        self.assertTrue(handled)
        self.assertFalse(enabled)
        self.assertIn("disabled", message)

    def test_voice_config_uses_nvidia_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NVIDIA_API_KEY": "test-key",
                "STT_NVIDIA_FUNCTION_ID": "asr-id",
                "TTS_NVIDIA_FUNCTION_ID": "tts-id",
            },
            clear=True,
        ):
            config = VoiceConfig.from_env()

        self.assertTrue(config.space_trigger)
        self.assertTrue(config.stt_enabled)
        self.assertEqual(config.stt_provider, "nvidia")
        self.assertTrue(config.tts_ssml)
        self.assertEqual(config.tts_provider, "nvidia")
        self.assertEqual(config.profile_name, "heavy_english_jarvis")
        self.assertIn("Jason", config.tts_voice)

    def test_space_on_empty_prompt_calls_voice_listener(self) -> None:
        config = VoiceConfig.from_env()
        listener = Mock(return_value="hello Jarvis")
        chars = iter([" "])
        output = io.StringIO()

        text = read_text_or_voice(
            "Krish: ",
            config,
            listener=listener,
            char_reader=lambda: next(chars),
            writer=output,
        )

        self.assertEqual(text, "hello Jarvis")
        listener.assert_called_once()
        self.assertIn("[listening...]", output.getvalue())
        self.assertIn("hello Jarvis", output.getvalue())

    def test_space_after_typed_text_stays_literal(self) -> None:
        config = VoiceConfig.from_env()
        listener = Mock(return_value="voice should not run")
        chars = iter(["h", "i", " ", "b", "u", "d", "\r"])
        output = io.StringIO()

        text = read_text_or_voice(
            "Krish: ",
            config,
            listener=listener,
            char_reader=lambda: next(chars),
            writer=output,
        )

        self.assertEqual(text, "hi bud")
        listener.assert_not_called()

    def test_tts_input_uses_configured_voice_style(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TTS_NVIDIA_SSML": "true",
                "TTS_RATE": "+24%",
                "TTS_PITCH": "-8Hz",
                "TTS_VOLUME": "+80%",
            },
            clear=False,
        ):
            config = VoiceConfig.from_env()

        text = tts_input_text(config, "Jarvis <online>")

        self.assertIn("<speak>", text)
        self.assertIn('rate="124%"', text)
        self.assertIn('pitch="-8Hz"', text)
        self.assertIn('volume="+4.8dB"', text)
        self.assertIn("Jarvis &lt;online&gt;", text)

    def test_tts_input_does_not_make_apostrophes_spoken_as_hash_entities(self) -> None:
        with patch.dict(os.environ, {"TTS_NVIDIA_SSML": "true"}, clear=False):
            config = VoiceConfig.from_env()

        text = tts_input_text(config, "How's your day? I'm online.")

        self.assertIn("How's", text)
        self.assertIn("I'm", text)
        self.assertNotIn("&#x27;", text)
        self.assertNotIn("&apos;", text)

    def test_speakable_text_removes_timing_and_markdown_noise(self) -> None:
        text = speakable_text("First=1.911s total=1.917s\n# Hello `Krish`")

        self.assertEqual(text, "Hello Krish")

    def test_speakable_text_skips_paths_and_urls(self) -> None:
        text = speakable_text(
            "Downloaded: License Ka Asla -> C:\\Users\\anime\\Music\\License Ka Asla.m4a\n"
            "Saved to C:\\Users\\anime\\Music\\License Ka Asla.m4a. Playlist default is ready.\n"
            "Source: https://www.youtube.com/watch?v=test123"
        )

        self.assertIn("Downloaded: License Ka Asla", text)
        self.assertIn("Saved to local file. Playlist default is ready.", text)
        self.assertNotIn("C:", text)
        self.assertNotIn("youtube.com", text)

    def test_speech_chunks_keep_tts_requests_below_limit(self) -> None:
        long_playlist = "Playlists: " + "; ".join(f"Song {index}" for index in range(1, 60))

        chunks = speech_chunks(long_playlist, 180)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 180 for chunk in chunks))

    def test_short_voice_error_hides_raw_grpc_wall(self) -> None:
        error = VoiceError(
            "NVIDIA TTS failed: <_InactiveRpcError of RPC that terminated with details = Error: Triton model failed during inference. Input sentence is longer than maximum sequence length: 675 > 400>"
        )

        message = short_voice_error(error)

        self.assertIn("Voice output failed", message)
        self.assertNotIn("_InactiveRpcError", message)
        self.assertNotIn("675 > 400", message)

    def test_voice_audio_threshold_and_playback_speed_are_config_driven(self) -> None:
        with patch.dict(
            os.environ,
            {
                "STT_ENERGY_THRESHOLD": "35",
                "TTS_PLAYBACK_SPEED": "1.10",
                "TTS_HEAVY_PITCH_FACTOR": "1.05",
            },
            clear=False,
        ):
            config = VoiceConfig.from_env()

        self.assertAlmostEqual(normalized_energy_threshold(35), 35 / 32768)
        self.assertGreater(output_sample_rate(config), config.tts_sample_rate)

    def test_voice_profile_can_be_changed_without_code_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voice_profiles.json"
            path.write_text(
                '{"default_profile":"ops","profiles":{"ops":{"tts_voice":"Magpie-Multilingual.EN-US.Jason.Calm","tts_playback_speed":1.03}}}',
                encoding="utf-8",
            )

            name, profile = load_voice_profile(path, "")

        self.assertEqual(name, "ops")
        self.assertEqual(profile["tts_voice"], "Magpie-Multilingual.EN-US.Jason.Calm")

    def test_noise_floor_raises_speech_threshold(self) -> None:
        threshold = speech_threshold([0.018, 0.02, 0.022], 650 / 32768, 0.035, 2.4)

        self.assertGreater(threshold, 0.04)

    def test_listening_waits_for_speaker_idle_before_microphone(self) -> None:
        config = VoiceConfig.from_env()
        speaker = VoiceSpeaker(config)
        called = []
        speaker._idle.clear()

        def release() -> None:
            time.sleep(0.02)
            speaker._idle.set()

        threading.Thread(target=release, daemon=True).start()
        with patch("voice_system.time.sleep", return_value=None) as sleep_call:
            transcript = listen_after_output_idle(config, speaker, lambda _config: called.append("listen") or "user text")

        self.assertEqual(transcript, "user text")
        self.assertEqual(called, ["listen"])
        sleep_call.assert_called()
        speaker.close()

    def test_asr_response_transcript_is_assembled_from_alternatives(self) -> None:
        alternative = type("Alternative", (), {"transcript": "hello Krish"})()
        result = type("Result", (), {"alternatives": [alternative]})()
        response = type("Response", (), {"results": [result]})()

        self.assertEqual(transcript_from_asr_response(response), "hello Krish")


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        import json

        return json.dumps(self.payload).encode("utf-8")


class FakeExecute:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def execute(self) -> dict[str, object]:
        return self.payload


def fake_memory_embedder(texts: list[str], input_type: str) -> list[list[float]]:
    vectors = []
    for text in texts:
        clean = text.lower()
        latency_score = 1.0 if "latency" in clean or "memory" in clean or "jarvis" in clean else 0.0
        weather_score = 1.0 if "weather" in clean else 0.0
        vectors.append([latency_score, weather_score])
    return vectors


def fake_live_memory_embedder(
    config: JarvisConfig,
    texts: list[str],
    input_type: str,
    timeout_seconds: float | None = None,
) -> list[list[float]]:
    return fake_memory_embedder(texts, input_type)


if __name__ == "__main__":
    unittest.main()
