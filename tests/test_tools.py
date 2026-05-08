from __future__ import annotations

import unittest
import contextlib
import io
import os
import platform
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from extension_system import load_extension_catalog
from jarvis_nim import JarvisConfig, final_chat_response, parse_tool_requests, planner_turn_context, read_native_tool_stream, read_streaming_response, stream_token, tool_planner_model
from memory_system import MemoryConfig, load_memory_context, parse_memory_json, prose_memory_fallback
from skill_system import load_skill_context
from tools import discover_tools
from tools.calculator import evaluate_expression
from tools.filesystem_tools import get_file_info, list_directory, read_text_file, search_text_files
from tools.memory_wiki import wiki_apply, wiki_lint, wiki_search, wiki_status
from tools.registry import ToolInputError
from tools.runtime_info import get_runtime_info
from tools.skill_workshop import skill_workshop
from tools.system_tools import get_pc_status, get_system_info
from tools.terminal import resolve_shell_name, run_terminal
from tools.text_tools import generate_uuid, hash_text, text_stats
from tools.web_tools import document_extract_text, parse_duckduckgo_results, readable_text, summarize_readable_text
from vector_memory import VectorMemoryConfig, build_vector_index, load_vector_memory_context, vector_search


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

    def test_extension_catalog_loads_prompt_skills_and_tools(self) -> None:
        catalog = load_extension_catalog()
        self.assertIn("web", [extension.id for extension in catalog.extensions])
        self.assertTrue(any(tool.get("name") == "web_search" for tool in catalog.tool_descriptors()))
        self.assertIn("Web And Document Tools", catalog.prompt_context())
        self.assertTrue(catalog.skill_roots())

    def test_skill_context_loads_extension_skill_files(self) -> None:
        catalog = load_extension_catalog()
        context = load_skill_context(catalog, Path.cwd())
        self.assertIn("Skill: web-research", context)
        self.assertIn("Skill: jarvis-qa", context)

    def test_display_templates_live_outside_tool_manifest(self) -> None:
        display = Path("tools/display.json").read_text(encoding="utf-8")
        manifest = Path("tools/tools.json").read_text(encoding="utf-8")
        self.assertIn("get_current_datetime", display)
        self.assertIn("responses", display)
        self.assertIn("direct_response", manifest)

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
