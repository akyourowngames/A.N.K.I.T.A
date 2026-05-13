from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from extension_system import ExtensionCatalog
from jarvis_nim import JarvisConfig
from memory_system import MemoryConfig
from web_assistant import WebAssistantConfig, WebAssistantRuntime, clean_session_id


def make_jarvis_config() -> JarvisConfig:
    return JarvisConfig(
        api_key="test",
        chat_url="https://example.test/v1/chat/completions",
        model="test-model",
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
        tool_mode="json",
        auto_tools=True,
        system_prompt_file=Path("prompts/chat_system.txt"),
        persona_file=Path("prompts/persona.txt"),
        tool_protocol_file=Path("prompts/tool_protocol.txt"),
        user_name="User",
        assistant_name="JARVIS",
    )


def make_memory_config(root: Path) -> MemoryConfig:
    return MemoryConfig(
        root=root / "memory",
        max_context_chars=2000,
        max_file_chars=1000,
        include_transcripts=False,
        extract_enabled=False,
        extract_background=False,
        extract_max_tokens=100,
        context_prompt_file=Path("prompts/memory_context.txt"),
    )


class WebAssistantRuntimeTests(unittest.TestCase):
    def test_stream_chat_emits_tokens_and_saves_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = Mock()
            registry.visible_tools.return_value = []
            registry.capability_text.return_value = ""
            runtime = WebAssistantRuntime(
                WebAssistantConfig(session_dir=root / "sessions", max_session_messages=8),
                make_jarvis_config(),
                registry,
                make_memory_config(root),
                ExtensionCatalog(root=root / "extensions", extensions=[], errors=()),
            )

            def fake_chat_once(_config: JarvisConfig, messages: list[dict[str, str]], _registry: object) -> str:
                print("hello ", end="")
                print("from web", end="")
                self.assertEqual(messages[-1], {"role": "user", "content": "hi"})
                return "hello from web"

            with patch("web_assistant.chat_once", side_effect=fake_chat_once):
                with patch("web_assistant.remember_chat") as remember_chat:
                    events = asyncio.run(collect_events(runtime.stream_chat("hi")))

            session_id = next(event["session_id"] for event in events if event["type"] == "done")
            saved_path = root / "sessions" / f"{session_id}.json"
            self.assertTrue(saved_path.exists())
            remember_chat.assert_called_once()

        self.assertIn({"type": "token", "content": "hello "}, events)
        self.assertIn({"type": "token", "content": "from web"}, events)
        self.assertEqual(events[-1]["reply"], "hello from web")

    def test_clean_session_id_replaces_unsafe_input(self) -> None:
        clean = clean_session_id("abc-123_X")
        replaced = clean_session_id("../bad")

        self.assertEqual(clean, "abc-123_X")
        self.assertNotEqual(replaced, "../bad")
        self.assertTrue(replaced)


async def collect_events(source: object) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    async for event in source:
        events.append(event)
    return events


if __name__ == "__main__":
    unittest.main()
