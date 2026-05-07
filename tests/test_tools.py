from __future__ import annotations

import unittest
import contextlib
import io
import os
import platform
import sys
from pathlib import Path
from unittest.mock import patch

from jarvis_nim import JarvisConfig, final_chat_response, parse_tool_requests, planner_turn_context, read_streaming_response, stream_token, tool_planner_model
from memory_system import MemoryConfig, load_memory_context, parse_memory_json, prose_memory_fallback
from tools import discover_tools
from tools.calculator import evaluate_expression
from tools.filesystem_tools import get_file_info, list_directory, read_text_file, search_text_files
from tools.registry import ToolInputError
from tools.runtime_info import get_runtime_info
from tools.system_tools import get_pc_status, get_system_info
from tools.terminal import resolve_shell_name, run_terminal
from tools.text_tools import generate_uuid, hash_text, text_stats
from tools.web_tools import readable_text, summarize_readable_text


class ToolRegistryTests(unittest.TestCase):
    def test_discovers_registered_tools(self) -> None:
        registry = discover_tools()
        names = [tool.name for tool in registry.visible_tools()]
        self.assertIn("calculate", names)
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

    def test_filesystem_tools(self) -> None:
        current = list_directory({"path": ".", "limit": 5})
        self.assertGreaterEqual(current["count"], 1)
        self.assertIn("summary", current)
        self.assertNotIn('"path"', current["summary"])
        info = get_file_info({"path": "README.md"})
        self.assertEqual(info["type"], "file")
        content = read_text_file({"path": "README.md", "max_chars": 100})
        self.assertIn("Jarvis", content["content"])
        matches = search_text_files({"path": "README.md", "query": "Jarvis", "max_files": 1})
        self.assertTrue(matches["matches"])

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

    def test_direct_response_template_comes_from_manifest(self) -> None:
        registry = discover_tools()
        response = registry.direct_response(
            "get_current_datetime",
            {"ok": True, "result": {"date": "2026-05-07", "time": "16:00:00", "timezone": "India Standard Time"}},
        )
        self.assertEqual(response, "Current date and time: 2026-05-07 16:00:00 India Standard Time")

    def test_direct_response_does_not_render_failed_payload(self) -> None:
        registry = discover_tools()
        response = registry.direct_response("get_current_datetime", {"ok": False, "error": "nope"})
        self.assertEqual(response, "")

    def test_datetime_direct_response_hides_tool_name(self) -> None:
        registry = discover_tools()
        payload = {
            "ok": True,
            "result": {
                "date": "2026-05-07",
                "time": "15:30:00",
                "timezone": "India Standard Time",
            },
        }
        response = registry.direct_response("get_current_datetime", payload)
        self.assertIn("2026-05-07", response)
        self.assertNotIn("get_current_datetime", response)

    def test_tool_protocol_lives_outside_nim_client(self) -> None:
        client = Path("jarvis_nim.py").read_text(encoding="utf-8")
        protocol = Path("prompts/tool_protocol.txt").read_text(encoding="utf-8")
        self.assertIn("Local tool protocol:", protocol)
        self.assertIn("installed software", protocol)
        self.assertNotIn("Local tool protocol:", client)

    def test_tool_results_prompt_lives_outside_nim_client(self) -> None:
        client = Path("jarvis_nim.py").read_text(encoding="utf-8")
        prompt = Path("prompts/tool_results.txt").read_text(encoding="utf-8")
        self.assertIn("Local tool results:", prompt)
        self.assertNotIn("Local tool results:", client)

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


if __name__ == "__main__":
    unittest.main()
