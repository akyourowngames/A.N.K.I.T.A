from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_nim import JarvisConfig, NimChatError, chat_once, select_planner_tool_decision
from latency_trace import LatencyTrace, use_latency_trace
from local_router import (
    ROUTE_CONFIRMATION_REQUIRED,
    ROUTE_DIRECT_CHAT,
    ROUTE_TOOL_REQUIRED,
    ROUTE_UNCERTAIN,
    route_chat_turn,
)
from main import build_messages
from memory_system import MemoryConfig
from extension_system import ExtensionCatalog
from tools.registry import ToolRegistry, define_tool, discover_tools


def test_config() -> JarvisConfig:
    return JarvisConfig(
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


class LatencyFastLaneTests(unittest.TestCase):
    def test_hi_bud_routes_direct_chat(self) -> None:
        decision = route_chat_turn("hi bud", [], discover_tools())

        self.assertEqual(decision.mode, ROUTE_DIRECT_CHAT)
        self.assertEqual(decision.selected_tool_names, [])

    def test_direct_chat_does_not_call_selector_or_include_tool_schemas(self) -> None:
        registry = discover_tools()
        opened_payloads: list[dict[str, object]] = []

        def fake_urlopen(request, timeout=0):
            opened_payloads.append(json.loads(request.data.decode("utf-8")))
            return FakeHttpResponse({"choices": [{"message": {"content": "Hey."}}]})

        trace = LatencyTrace(enabled=True)
        with use_latency_trace(trace):
            with patch("jarvis_nim.urllib.request.urlopen", side_effect=fake_urlopen):
                with patch("jarvis_nim.select_planner_tool_decision") as selector:
                    reply = chat_once(test_config(), [{"role": "user", "content": "hi bud"}], registry)

        self.assertEqual(reply, "Hey.")
        selector.assert_not_called()
        self.assertEqual(trace.finish()["model_calls"], 1)
        self.assertEqual(len(opened_payloads), 1)
        self.assertNotIn("tools", opened_payloads[0])

    def test_obvious_date_and_pc_status_route_to_local_tools(self) -> None:
        registry = discover_tools()

        date_decision = route_chat_turn("what is today's date?", [], registry)
        status_decision = route_chat_turn("show my pc status", [], registry)

        self.assertEqual(date_decision.mode, ROUTE_TOOL_REQUIRED)
        self.assertIn("get_current_datetime", date_decision.selected_tool_names)
        self.assertEqual(status_decision.mode, ROUTE_TOOL_REQUIRED)
        self.assertIn("get_pc_status", status_decision.selected_tool_names)

    def test_uncertain_request_can_use_remote_selector(self) -> None:
        registry = discover_tools()
        decision = route_chat_turn("status", [], registry)
        self.assertEqual(decision.mode, ROUTE_UNCERTAIN)

        selector_payload = {"choices": [{"message": {"content": json.dumps({"tool_names": ["get_pc_status"]})}}]}
        with patch.dict("os.environ", {"TOOL_PLANNER_SELECTION_CACHE": "false"}, clear=False):
            with patch("jarvis_nim.post_json", return_value=selector_payload) as post_json:
                names, _reply, _requests = select_planner_tool_decision(
                    test_config(),
                    [{"role": "user", "content": "status"}],
                    registry,
                )

        self.assertIn("get_pc_status", names)
        self.assertEqual(post_json.call_count, 1)

    def test_selector_timeout_falls_back_to_small_safe_subset(self) -> None:
        registry = discover_tools()
        with patch("jarvis_nim.post_json", side_effect=NimChatError("timeout")):
            names, reply, requests = select_planner_tool_decision(
                test_config(),
                [{"role": "user", "content": "status"}],
                registry,
            )

        self.assertEqual(reply, "")
        self.assertEqual(requests, [])
        self.assertTrue(names)
        self.assertLessEqual(len(names), 6)
        self.assertNotIn("run_terminal", names)

    def test_vector_memory_is_skipped_for_direct_chat(self) -> None:
        registry = discover_tools()
        memory_config = MemoryConfig(
            root=Path("memory"),
            max_context_chars=1000,
            max_file_chars=1000,
            include_transcripts=False,
            extract_enabled=False,
            extract_background=False,
            extract_max_tokens=100,
            context_prompt_file=Path("prompts/memory_context.txt"),
        )
        catalog = ExtensionCatalog(root=Path("extensions"), extensions=[])

        with patch("main.load_vector_memory_context") as vector_memory:
            messages = build_messages(test_config(), registry, memory_config, catalog, "hi bud")

        vector_memory.assert_not_called()
        self.assertNotIn("Registered local tools:", messages[0]["content"])

    def test_selected_tool_path_does_not_expose_all_tools(self) -> None:
        registry = discover_tools()
        calls: list[dict[str, object]] = []

        def fake_post_json(_config: JarvisConfig, payload: dict[str, object]) -> dict[str, object]:
            calls.append(payload)
            if len(calls) == 1:
                return {"choices": [{"message": {"content": json.dumps({"tool_calls": []})}}]}
            return {"choices": [{"message": {"content": "Weather reply."}}]}

        with patch("jarvis_nim.post_json", side_effect=fake_post_json):
            chat_once(test_config(), [{"role": "user", "content": "weather in Delhi"}], registry)

        planner_prompt = calls[0]["messages"][0]["content"]
        self.assertIn("get_weather", planner_prompt)
        self.assertNotIn("run_terminal", planner_prompt)

    def test_zero_argument_date_tool_executes_without_remote_selector_or_planner(self) -> None:
        registry = discover_tools()
        opened_payloads: list[dict[str, object]] = []

        def fake_urlopen(request, timeout=0):
            opened_payloads.append(json.loads(request.data.decode("utf-8")))
            return FakeHttpResponse({"choices": [{"message": {"content": "Today."}}]})

        trace = LatencyTrace(enabled=True)
        with use_latency_trace(trace):
            with patch("jarvis_nim.urllib.request.urlopen", side_effect=fake_urlopen):
                with patch("jarvis_nim.select_planner_tool_decision") as selector:
                    with patch("jarvis_nim.collect_tool_decision") as planner:
                        reply = chat_once(
                            test_config(),
                            [{"role": "user", "content": "what is today's date?"}],
                            registry,
                        )

        self.assertEqual(reply, "Today.")
        selector.assert_not_called()
        planner.assert_not_called()
        self.assertEqual(len(opened_payloads), 1)
        stages = [event["stage"] for event in trace.finish()["events"]]
        self.assertIn("tool_execution_started", stages)
        self.assertIn("tool_execution_done", stages)

    def test_latency_trace_records_major_stages(self) -> None:
        registry = discover_tools()
        trace = LatencyTrace(enabled=True)

        with use_latency_trace(trace):
            with patch("jarvis_nim.post_json", return_value={"choices": [{"message": {"content": "Hey."}}]}):
                chat_once(test_config(), [{"role": "user", "content": "hi bud"}], registry)
        stages = [event["stage"] for event in trace.finish()["events"]]

        self.assertIn("request_received", stages)
        self.assertIn("local_router_started", stages)
        self.assertIn("local_router_done", stages)
        self.assertIn("final_model_started", stages)
        self.assertIn("response_done", stages)

    def test_dangerous_tools_are_not_auto_executed_from_local_router(self) -> None:
        registry = ToolRegistry()
        registry.register(
            define_tool(
                name="open_local_app",
                description="Open local desktop applications and files.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                handler=lambda _params: {"opened": True},
                risk="dangerous",
                requires_confirmation=True,
                parallel_safe=False,
            ).to_tool()
        )

        decision = route_chat_turn("open chrome", [], registry)

        self.assertEqual(decision.mode, ROUTE_CONFIRMATION_REQUIRED)
        self.assertEqual(decision.selected_tool_names, ["open_local_app"])


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
