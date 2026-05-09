from __future__ import annotations

import unittest
import contextlib
import io
import os
import platform
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

from extension_system import load_extension_catalog
from jarvis_nim import JarvisConfig, chat_with_native_streaming_tools, final_chat_response, open_url_with_retries, parse_tool_requests, planner_turn_context, read_native_tool_stream, read_streaming_response, stream_token, tool_planner_model, tool_results_prompt
from memory_system import MemoryConfig, load_memory_context, parse_memory_json, prose_memory_fallback
from skill_system import load_skill_context
from tools import discover_tools
from tools.calculator import evaluate_expression
from tools.diagnostics_tools import jarvis_latency_probe
from tools.filesystem_tools import get_file_info, list_directory, read_text_file, search_text_files
from tools.memory_wiki import wiki_apply, wiki_lint, wiki_search, wiki_status
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
    VoiceSpeaker,
    listen_after_output_idle,
    load_voice_profile,
    normalized_energy_threshold,
    output_sample_rate,
    read_text_or_voice,
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
        self.assertIn("summary", current)
        self.assertNotIn('"path"', current["summary"])
        info = get_file_info({"path": "README.md"})
        self.assertEqual(info["type"], "file")
        content = read_text_file({"path": "README.md", "max_chars": 100})
        self.assertIn("Jarvis", content["content"])
        matches = search_text_files({"path": "README.md", "query": "Jarvis", "max_files": 1})
        self.assertTrue(matches["matches"])

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

    def test_tool_results_prompt_lives_outside_nim_client(self) -> None:
        client = Path("jarvis_nim.py").read_text(encoding="utf-8")
        prompt = Path("prompts/tool_results.txt").read_text(encoding="utf-8")
        self.assertIn("Local tool results:", prompt)
        self.assertNotIn("Local tool results:", client)

    def test_tool_results_prompt_includes_display_name_context(self) -> None:
        prompt = tool_results_prompt([], "what is my name", "", "Krish")
        self.assertIn("Current user's display name:", prompt)
        self.assertIn("Krish", prompt)
        self.assertNotIn("{user_name}", prompt)

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
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        reply = chat_with_native_streaming_tools(config, messages, registry)

        self.assertEqual(reply, "4")
        self.assertIn("4", output.getvalue())
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
