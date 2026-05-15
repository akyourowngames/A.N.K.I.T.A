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
from jarvis_nim import JarvisConfig, chat_with_native_streaming_tools, collect_tool_decision, contains_unresolved_placeholder, final_chat_response, open_url_with_retries, parse_tool_requests, planner_turn_context, public_result_payload, public_tool_results, read_native_tool_stream, read_streaming_response, stream_token, tool_planner_model, tool_selector_model, tool_selection_from_selector_content, tool_results_prompt
from main import configure_stream_encoding, interactive_speech_command
from memory_system import MemoryConfig, load_memory_context, parse_memory_json, prose_memory_fallback
from skill_system import load_skill_context
from tools import discover_tools
from tools.calculator import evaluate_expression
from tools.diagnostics_tools import jarvis_latency_probe
from tools.filesystem_tools import display_name, get_file_info, list_directory, read_text_file, search_text_files
from tools.memory_wiki import wiki_apply, wiki_lint, wiki_search, wiki_status
from tools.music_agent import music_control, music_download, music_library, music_play, music_playlist, music_search, music_status
from tools.path_resolver import resolve_local_path
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

    def test_discovers_registered_tools(self) -> None:
        registry = discover_tools()
        names = [tool.name for tool in registry.visible_tools()]
        self.assertIn("calculate", names)
        self.assertIn("get_current_datetime", names)
        self.assertIn("music_play", names)
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
            '{"tool_calls":[{"name":"wiki_get","parameters":{"path":"memory/wiki/index.md"}},{"name":"wiki_get","parameters":{"path":"<page_path>"}}]}',
            registry,
        )

        self.assertEqual(requests, [{"name": "wiki_get", "parameters": {"path": "memory/wiki/index.md"}}])
        self.assertTrue(contains_unresolved_placeholder({"path": "<page_path>"}))

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
        self.assertNotIn("user_output", result)

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
        self.assertNotIn("user_output", result)

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
            target = resolve_local_path("media/new-profile", root)

        self.assertEqual(target, (root / "media" / "new-profile").resolve())

    def test_music_agent_searches_local_files_with_close_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "music.json"
            library = root / "library"
            library.mkdir()
            (library / "Imagine Dragons - Believer.mp3").write_text("fake audio", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "library_dir": str(library),
                        "database_path": str(root / "music_db.json"),
                        "state_path": str(root / "player_state.json"),
                        "dry_run_player": True,
                        "download_enabled": False,
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"JARVIS_MUSIC_CONFIG": str(config_path)}, clear=False):
                result = music_search({"query": "beliver"})

        self.assertTrue(result["searched_local_first"])
        self.assertEqual(result["local_matches"][0]["title"], "Believer")
        self.assertEqual(result["local_matches"][0]["artist"], "Imagine Dragons")

    def test_music_download_reuses_existing_local_track(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "music.json"
            library = root / "library"
            library.mkdir()
            (library / "Ed Sheeran - Shape of You.mp3").write_text("fake audio", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "library_dir": str(library),
                        "database_path": str(root / "music_db.json"),
                        "state_path": str(root / "player_state.json"),
                        "dry_run_player": True,
                        "download_enabled": True,
                        "download_command": "missing-downloader",
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"JARVIS_MUSIC_CONFIG": str(config_path)}, clear=False):
                result = music_download({"query": "shape of you"})

        self.assertFalse(result["downloaded"])
        self.assertTrue(result["already_existed"])
        self.assertEqual(result["track"]["title"], "Shape of You")

    def test_music_play_updates_recent_history_without_real_player(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "music.json"
            library = root / "library"
            library.mkdir()
            (library / "Daft Punk - One More Time.mp3").write_text("fake audio", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "library_dir": str(library),
                        "database_path": str(root / "music_db.json"),
                        "state_path": str(root / "player_state.json"),
                        "dry_run_player": True,
                        "download_enabled": False,
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"JARVIS_MUSIC_CONFIG": str(config_path)}, clear=False):
                play_result = music_play({"query": "one more time"})
                recent = music_library({"operation": "recent"})
                status = music_status({})

        self.assertTrue(play_result["played"])
        self.assertEqual(play_result["playback"]["backend"], "dry_run")
        self.assertEqual(recent["tracks"][0]["title"], "One More Time")
        self.assertEqual(status["current_track"]["title"], "One More Time")

    def test_music_play_uses_last_query_for_followup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "music.json"
            library = root / "library"
            library.mkdir()
            (library / "Serena - Safari.mp3").write_text("fake audio", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "library_dir": str(library),
                        "database_path": str(root / "music_db.json"),
                        "state_path": str(root / "player_state.json"),
                        "dry_run_player": True,
                        "download_enabled": False,
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"JARVIS_MUSIC_CONFIG": str(config_path)}, clear=False):
                music_search({"query": "serena safari"})
                play_result = music_play({})

        self.assertTrue(play_result["played"])
        self.assertEqual(play_result["track"]["title"], "Safari")
        self.assertEqual(play_result["track"]["artist"], "Serena")

    def test_music_play_uses_vlc_command_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "music.json"
            library = root / "library"
            library.mkdir()
            (library / "VLC Test - Tone.mp3").write_text("fake audio", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "library_dir": str(library),
                        "database_path": str(root / "music_db.json"),
                        "state_path": str(root / "player_state.json"),
                        "download_enabled": False,
                        "vlc_command": sys.executable,
                        "vlc_extra_args": ["-c", "import time; time.sleep(2)"],
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"JARVIS_MUSIC_CONFIG": str(config_path)}, clear=False):
                play_result = music_play({"query": "tone"})
                status = music_status({})

        pid = play_result["playback"].get("pid")
        if isinstance(pid, int):
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=10)
            else:
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
        self.assertTrue(play_result["played"])
        self.assertEqual(play_result["playback"]["backend"], "vlc")
        self.assertTrue(status["player"]["available"])

    def test_music_playlist_adds_and_plays_local_track(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "music.json"
            library = root / "library"
            library.mkdir()
            (library / "Survivor - Eye of the Tiger.mp3").write_text("fake audio", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "library_dir": str(library),
                        "database_path": str(root / "music_db.json"),
                        "state_path": str(root / "player_state.json"),
                        "dry_run_player": True,
                        "download_enabled": False,
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"JARVIS_MUSIC_CONFIG": str(config_path)}, clear=False):
                music_library({"operation": "scan"})
                added = music_playlist({"operation": "add", "name": "workout", "query": "eye tiger"})
                played = music_playlist({"operation": "play", "name": "workout"})

        self.assertTrue(added["changed"])
        self.assertEqual(added["playlist"]["track_count"], 1)
        self.assertTrue(played["played"])

    def test_music_playlist_add_top_downloads_remembered_remote_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "music.json"
            library = root / "library"
            library.mkdir()
            config_path.write_text(
                json.dumps(
                    {
                        "library_dir": str(library),
                        "database_path": str(root / "music_db.json"),
                        "state_path": str(root / "player_state.json"),
                        "dry_run_player": True,
                        "download_enabled": True,
                        "download_command": sys.executable,
                    }
                ),
                encoding="utf-8",
            )
            remote_results = [
                {"title": "License Ka Asla", "artist": "Masoom Sharma", "url": "https://example.test/license"},
                {"title": "Yaari", "artist": "Masoom Sharma", "url": "https://example.test/yaari"},
                {"title": "Yaha Ke Bahubali", "artist": "Masoom Sharma", "url": "https://example.test/bahubali"},
            ]

            def fake_download(context: dict[str, object], source: str) -> Path:
                title_by_source = {
                    "https://example.test/license": "License Ka Asla",
                    "https://example.test/yaari": "Yaari",
                    "https://example.test/bahubali": "Yaha Ke Bahubali",
                }
                title = title_by_source[source]
                path = Path(context["library_dir"]) / f"Masoom Sharma - {title}.mp3"
                path.write_text("fake audio", encoding="utf-8")
                return path

            with patch.dict(os.environ, {"JARVIS_MUSIC_CONFIG": str(config_path)}, clear=False):
                with patch("tools.music_agent.remote_search", return_value=remote_results):
                    music_search({"query": "Masoom Sharma songs", "include_remote": True, "limit": 3})
                with patch("tools.music_agent.run_download", side_effect=fake_download):
                    added = music_playlist({"operation": "add_top", "name": "fav", "count": 3})
                    shown = music_playlist({"operation": "show", "name": "fav"})

        self.assertTrue(added["changed"])
        self.assertEqual(len(added["added_tracks"]), 3)
        self.assertEqual(added["failed"], [])
        self.assertEqual(shown["playlist"]["track_count"], 3)
        self.assertEqual([track["title"] for track in shown["playlist"]["tracks"]], ["License Ka Asla", "Yaari", "Yaha Ke Bahubali"])

    def test_music_playlist_play_sends_all_tracks_to_vlc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "music.json"
            library = root / "library"
            library.mkdir()
            (library / "Serena - Safari.mp3").write_text("fake audio", encoding="utf-8")
            (library / "Masoom Sharma - License Ka Asla.mp3").write_text("fake audio", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "library_dir": str(library),
                        "database_path": str(root / "music_db.json"),
                        "state_path": str(root / "player_state.json"),
                        "download_enabled": False,
                        "vlc_command": sys.executable,
                        "vlc_extra_args": ["-c", "import time; time.sleep(2)"],
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"JARVIS_MUSIC_CONFIG": str(config_path)}, clear=False):
                music_library({"operation": "scan"})
                music_playlist({"operation": "add", "name": "fav", "query": "safari", "allow_download": False})
                music_playlist({"operation": "add", "name": "fav", "query": "license asla", "allow_download": False})
                played = music_playlist({"operation": "play", "name": "fav"})
                music_control_result = None
                try:
                    music_control_result = music_control({"operation": "stop"})
                finally:
                    pid = played["playback"].get("pid")
                    if isinstance(pid, int):
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=10)
                        else:
                            try:
                                os.kill(pid, 15)
                            except OSError:
                                pass

        self.assertTrue(played["played"])
        self.assertEqual(played["playback"]["backend"], "vlc")
        self.assertEqual(played["playback"]["track_count"], 2)
        self.assertEqual(len(played["playback"]["paths"]), 2)
        self.assertEqual(played["queue"]["length"], 2)
        self.assertIsNotNone(music_control_result)




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
        self.assertIn("music-agent", extension_ids)
        self.assertTrue(any(tool.get("name") == "web_search" for tool in catalog.tool_descriptors()))
        self.assertTrue(any(tool.get("name") == "music_play" for tool in catalog.tool_descriptors()))
        self.assertIn("Web And Document Tools", catalog.prompt_context())
        self.assertIn("Music Agent Protocol", catalog.prompt_context())
        self.assertTrue(catalog.skill_roots())

    def test_jarvis_cli_lists_current_tool_surface(self) -> None:
        completed = subprocess.run(
            [sys.executable, "main.py", "--list-tools"],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("- web_search:", completed.stdout)
        self.assertIn("- run_terminal:", completed.stdout)

    def test_skill_context_loads_extension_skill_files(self) -> None:
        catalog = load_extension_catalog()
        with patch.dict(os.environ, {"JARVIS_SKILL_CONTEXT_CHARS": "30000"}, clear=False):
            context = load_skill_context(catalog, Path.cwd())
        self.assertIn("Skill: web-research", context)
        self.assertIn("Skill: jarvis-qa", context)

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
                "name": "wiki_get",
                "parameters": {"path": "memory/wiki/example.txt"},
                "result": {"summary": "Wiki page:\nLicense Ka Asla"},
            }
        ]

        prompt = tool_results_prompt(results, "show me playlist", "Krish")

        self.assertIn("License Ka Asla", prompt)
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
        self.assertIn("supporting data only", Path("prompts/tool_results.txt").read_text(encoding="utf-8"))

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
