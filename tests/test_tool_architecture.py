from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_nim import (
    JarvisConfig,
    ToolSubsetRegistry,
    collect_native_tool_decision,
    execute_tool_requests,
    json_tool_protocol,
)
from extension_system import load_extension_catalog
from tools.registry import ToolRegistry, ToolRegistryError, define_tool, discover_tools, tool_from_descriptor


def test_config(tool_mode: str = "json") -> JarvisConfig:
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
        tool_mode=tool_mode,
        auto_tools=True,
        system_prompt_file=Path("prompts/chat_system.txt"),
        persona_file=Path("prompts/persona.txt"),
        tool_protocol_file=Path("prompts/tool_protocol.txt"),
        user_name="Krish",
        assistant_name="JARVIS",
    )


def make_tool(
    name: str,
    *,
    delay_seconds: float = 0,
    skill: str = "",
    risk: str = "read",
    parallel_safe: bool | None = None,
    requires_confirmation: bool | None = None,
):
    def handler(_params: dict[str, object]) -> dict[str, object]:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        return {"tool": name}

    return define_tool(
        name=name,
        description=f"{name} test tool.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
        skill=skill,
        risk=risk,
        parallel_safe=parallel_safe,
        requires_confirmation=requires_confirmation,
    ).to_tool()


class ToolArchitectureTests(unittest.TestCase):
    def test_define_tool_builds_tool_with_metadata(self) -> None:
        spec = define_tool(
            name="write_note",
            description="Write a note.",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            handler=lambda params: {"ok": bool(params)},
            skill="Use only after the user asks to persist a note.",
            category="notes",
            risk="write",
            parallel_safe=False,
            requires_confirmation=True,
        )

        tool = spec.to_tool()

        self.assertEqual(tool.name, "write_note")
        self.assertEqual(tool.category, "notes")
        self.assertEqual(tool.risk, "write")
        self.assertFalse(tool.parallel_safe)
        self.assertTrue(tool.requires_confirmation)
        self.assertIn("persist a note", tool.skill)
        self.assertEqual(tool.openai_schema()["function"]["parameters"]["properties"]["text"]["type"], "string")

    def test_duplicate_tool_names_fail(self) -> None:
        registry = ToolRegistry()
        registry.register(make_tool("same_name"))

        with self.assertRaises(ToolRegistryError):
            registry.register(make_tool("same_name"))

    def test_manifest_metadata_is_parsed(self) -> None:
        tool = tool_from_descriptor(
            {
                "name": "metadata_text_stats",
                "description": "Count supplied text.",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                "category": "text",
                "skill": "Use for text measurement only.",
                "risk": "read",
                "parallel_safe": True,
                "requires_confirmation": False,
                "executor": {
                    "module": "tools.text_tools",
                    "function": "text_stats",
                },
            }
        )

        self.assertEqual(tool.category, "text")
        self.assertEqual(tool.skill, "Use for text measurement only.")
        self.assertEqual(tool.risk, "read")
        self.assertTrue(tool.parallel_safe)
        self.assertFalse(tool.requires_confirmation)

    def test_core_terminal_tool_is_dangerous_and_confirmation_gated(self) -> None:
        registry = discover_tools()
        tool = registry.tool("run_terminal")

        self.assertIsNotNone(tool)
        self.assertEqual(tool.risk, "dangerous")
        self.assertFalse(tool.parallel_safe)
        self.assertTrue(tool.requires_confirmation)

        with patch.dict(
            "os.environ",
            {
                "JARVIS_ENABLE_DANGEROUS_TOOLS": "",
                "JARVIS_TOOL_DEV_MODE": "",
                "JARVIS_DEBUG_TOOLS": "",
                "JARVIS_TOOL_CONFIRMATION_APPROVED": "",
            },
            clear=False,
        ):
            payload = json.loads(registry.execute("run_terminal", {"command": "python --version"}))

        self.assertFalse(payload["ok"])
        self.assertIn("disabled", payload["error"])

    def test_write_tool_requires_confirmation(self) -> None:
        registry = ToolRegistry()
        registry.register(make_tool("write_memory", risk="write"))

        payload = json.loads(registry.execute("write_memory", {}))

        self.assertFalse(payload["ok"])
        self.assertIn("requires explicit confirmation", payload["error"])

        approved = json.loads(registry.execute("write_memory", {"confirm_tool_execution": "write_memory"}))

        self.assertTrue(approved["ok"])

    def test_native_mode_exposes_selected_subset_and_selected_skill_only(self) -> None:
        registry = ToolRegistry()
        for index in range(10):
            registry.register(make_tool(f"tool_{index}", skill=f"skill for tool {index}"))

        calls: list[dict[str, object]] = []
        selector_payload = {"choices": [{"message": {"content": json.dumps({"tool_names": ["tool_3"]})}}]}
        native_payload = {"choices": [{"message": {"content": "No tool needed."}}]}

        def fake_post_json(_config: JarvisConfig, payload: dict[str, object]) -> dict[str, object]:
            calls.append(payload)
            return selector_payload if len(calls) == 1 else native_payload

        with patch.dict(
            "os.environ",
            {
                "TOOL_PLANNER_DYNAMIC_SCHEMAS": "true",
                "TOOL_PLANNER_DYNAMIC_SCHEMA_MIN_TOOLS": "1",
                "TOOL_PLANNER_SELECTION_CACHE": "false",
            },
            clear=False,
        ):
            with patch("jarvis_nim.post_json", side_effect=fake_post_json):
                requests, reply = collect_native_tool_decision(
                    test_config("native"),
                    [{"role": "user", "content": "use the matching tool"}],
                    registry,
                )

        self.assertEqual(requests, [])
        self.assertEqual(reply, "No tool needed.")
        self.assertEqual(len(calls[1]["tools"]), 1)
        self.assertEqual(calls[1]["tools"][0]["function"]["name"], "tool_3")
        native_messages = calls[1]["messages"]
        native_skill_text = "\n".join(message["content"] for message in native_messages)
        self.assertIn("skill for tool 3", native_skill_text)
        self.assertNotIn("skill for tool 4", native_skill_text)

    def test_safe_read_tools_execute_in_parallel(self) -> None:
        registry = ToolRegistry()
        registry.register(make_tool("slow_a", delay_seconds=0.2, risk="read", parallel_safe=True))
        registry.register(make_tool("slow_b", delay_seconds=0.2, risk="read", parallel_safe=True))
        started = time.perf_counter()

        results = execute_tool_requests(
            registry,
            [
                {"name": "slow_a", "parameters": {}},
                {"name": "slow_b", "parameters": {}},
            ],
        )
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.35)
        self.assertEqual([result["name"] for result in results], ["slow_a", "slow_b"])
        self.assertTrue(all(result["result"]["ok"] for result in results))

    def test_tool_skill_context_only_includes_selected_tools(self) -> None:
        registry = ToolRegistry()
        registry.register(make_tool("selected_tool", skill="selected skill text"))
        registry.register(make_tool("hidden_tool", skill="hidden skill text"))
        subset = ToolSubsetRegistry(registry, ["selected_tool"])

        protocol = json_tool_protocol(subset)

        self.assertIn("selected skill text", protocol)
        self.assertNotIn("hidden skill text", protocol)

    def test_extension_skill_dirs_become_scoped_tool_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extension = root / "extensions" / "scoped"
            skill_dir = extension / "skills" / "scoped-helper"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.txt").write_text(
                "---\nname: scoped-helper\n---\nUse the scoped helper only for this extension tool.",
                encoding="utf-8",
            )
            (extension / "extension.json").write_text(
                json.dumps(
                    {
                        "id": "scoped",
                        "tools": [
                            {
                                "name": "scoped_echo",
                                "description": "Echo text.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"text": {"type": "string"}},
                                },
                                "executor": {
                                    "module": "tools.text_tools",
                                    "function": "text_stats",
                                },
                            }
                        ],
                        "skill_dirs": ["skills"],
                    }
                ),
                encoding="utf-8",
            )

            catalog = load_extension_catalog(root / "extensions")
            registry = discover_tools(extension_catalog=catalog)
            subset = ToolSubsetRegistry(registry, ["scoped_echo"])

        protocol = json_tool_protocol(subset)

        self.assertIn("Use the scoped helper only for this extension tool.", protocol)


if __name__ == "__main__":
    unittest.main()
