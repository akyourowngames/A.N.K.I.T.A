from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from extension_system import load_extension_catalog
from jarvis_nim import JarvisConfig
from memory_system import MemoryConfig
from telegram_bot import (
    PerChatRateLimiter,
    TelegramDeliveryRegistry,
    TelegramConfig,
    TelegramRuntime,
    TelegramSession,
    chunk_telegram_response,
    prune_session_messages,
    refreshed_session_messages,
)
from tools import discover_tools
from tools.telegram_bot_tools import (
    TelegramToolContext,
    auto_queue_file_outputs,
    clear_telegram_context,
    drain_telegram_outbox,
    set_telegram_context,
    telegram_send_file,
    telegram_session_info,
    telegram_status,
)


class TelegramBotConfigTests(unittest.TestCase):
    def test_env_allowed_chats_override_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "telegram.json"
            config_path.write_text(
                '{"allowed_chat_ids":[111],"session_dir":"sessions","upload_dir":"uploads","download_dir":"downloads"}',
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "JARVIS_TELEGRAM_CONFIG": str(config_path),
                    "TELEGRAM_ALLOWED_CHATS": "222, -333",
                },
                clear=False,
            ):
                config = TelegramConfig.from_env(root)

        self.assertEqual(config.allowed_chat_ids, (222, -333))
        self.assertTrue(config.is_allowed(222))
        self.assertFalse(config.is_allowed(111))

    def test_rate_limiter_is_per_chat(self) -> None:
        limiter = PerChatRateLimiter(1)

        self.assertTrue(limiter.allow(1))
        self.assertFalse(limiter.allow(1))
        self.assertTrue(limiter.allow(2))


class TelegramBotSessionTests(unittest.TestCase):
    def test_prune_keeps_system_messages_and_recent_turns(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
            {"role": "assistant", "content": "four"},
        ]

        pruned = prune_session_messages(messages, 2)

        self.assertEqual(pruned, [messages[0], messages[3], messages[4]])

    def test_session_load_refreshes_system_context_but_keeps_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            telegram_config = TelegramConfig(
                agent_name="Test Telegram",
                bot_token_env="TELEGRAM_BOT_TOKEN",
                allowed_chat_ids=(),
                memory_mode="shared",
                per_user_memory_root=root / "memory-users",
                session_dir=root / "sessions",
                upload_dir=root / "uploads",
                download_dir=root / "downloads",
                max_session_messages=4,
                max_message_length=4000,
                parse_mode="plain",
                typing_indicator=False,
                rate_limit_per_minute=0,
                voice_transcription=False,
                send_files_inline=True,
                webhook_mode=False,
                webhook_url="",
                webhook_port=8443,
                rejection_message="private",
                slow_down_message="slow",
                ffmpeg_command="ffmpeg",
                auto_send_file_result_paths=(),
                config_path=root / "telegram.json",
            )
            telegram_config.session_dir.mkdir(parents=True)
            memory_config = MemoryConfig(
                root=root / "memory",
                max_context_chars=2000,
                max_file_chars=1000,
                include_transcripts=False,
                extract_enabled=False,
                extract_background=False,
                extract_max_tokens=100,
                context_prompt_file=Path("prompts/memory_context.txt"),
            )
            jarvis_config = JarvisConfig(
                api_key="test",
                chat_url="https://example.test/v1/chat/completions",
                model="test-model",
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
                user_name="User",
                assistant_name="JARVIS",
            )
            runtime = TelegramRuntime(telegram_config, jarvis_config, Mock(), memory_config, load_extension_catalog())
            saved = {
                "chat_id": 123,
                "user_name": "Old",
                "memory_dir": "old-memory",
                "created_at": "2026-05-10T00:00:00+05:30",
                "last_active": "2026-05-10T00:00:00+05:30",
                "messages": [
                    {"role": "system", "content": "stale context"},
                    {"role": "user", "content": "old user turn"},
                    {"role": "assistant", "content": "old assistant turn"},
                ],
            }
            (telegram_config.session_dir / "123.json").write_text(json.dumps(saved), encoding="utf-8")
            fresh = [{"role": "system", "content": "fresh context"}]
            with patch("telegram_bot.build_messages", return_value=fresh):
                loaded = runtime.sessions.load(123, "Krish", "new text")

        self.assertEqual(loaded.messages, [fresh[0], {"role": "user", "content": "old user turn"}, {"role": "assistant", "content": "old assistant turn"}])
        self.assertEqual(loaded.memory_dir, str(memory_config.root))

    def test_refreshed_session_messages_keeps_only_fresh_system_messages(self) -> None:
        fresh = [{"role": "system", "content": "fresh"}]
        saved = [{"role": "system", "content": "stale"}, {"role": "user", "content": "hello"}]

        self.assertEqual(refreshed_session_messages(fresh, saved), [{"role": "system", "content": "fresh"}, {"role": "user", "content": "hello"}])

    def test_runtime_turn_uses_chat_once_and_saves_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            telegram_config = TelegramConfig(
                agent_name="Test Telegram",
                bot_token_env="TELEGRAM_BOT_TOKEN",
                allowed_chat_ids=(),
                memory_mode="shared",
                per_user_memory_root=root / "memory-users",
                session_dir=root / "sessions",
                upload_dir=root / "uploads",
                download_dir=root / "downloads",
                max_session_messages=4,
                max_message_length=4000,
                parse_mode="plain",
                typing_indicator=False,
                rate_limit_per_minute=0,
                voice_transcription=False,
                send_files_inline=True,
                webhook_mode=False,
                webhook_url="",
                webhook_port=8443,
                rejection_message="private",
                slow_down_message="slow",
                ffmpeg_command="ffmpeg",
                auto_send_file_result_paths=("rendered_report.output_path",),
                config_path=root / "telegram.json",
            )
            memory_config = MemoryConfig(
                root=root / "memory",
                max_context_chars=2000,
                max_file_chars=1000,
                include_transcripts=False,
                extract_enabled=False,
                extract_background=False,
                extract_max_tokens=100,
                context_prompt_file=Path("prompts/memory_context.txt"),
            )
            jarvis_config = JarvisConfig(
                api_key="test",
                chat_url="https://example.test/v1/chat/completions",
                model="test-model",
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
                user_name="User",
                assistant_name="JARVIS",
            )
            registry = Mock()
            registry.visible_tools.return_value = []
            runtime = TelegramRuntime(
                telegram_config,
                jarvis_config,
                registry,
                memory_config,
                load_extension_catalog(),
            )
            session = TelegramSession(
                chat_id=123,
                user_name="Krish",
                messages=[{"role": "system", "content": "base"}],
                memory_dir=str(memory_config.root),
                created_at="2026-05-10T00:00:00+05:30",
                last_active="2026-05-10T00:00:00+05:30",
            )

            with patch("telegram_bot.vector_memory_system_message", return_value=None):
                with patch("telegram_bot.chat_once", return_value="telegram reply") as chat_once:
                    with patch("telegram_bot.remember_chat") as remember_chat:
                        reply = runtime.run_chat_turn(session, "hello from Telegram")

            saved_path = telegram_config.session_dir / "123.json"
            saved_exists = saved_path.exists()

        self.assertEqual(reply, "telegram reply")
        self.assertTrue(saved_exists)
        chat_once.assert_called_once()
        sent_messages = chat_once.call_args.args[1]
        self.assertEqual(sent_messages[-1], {"role": "user", "content": "hello from Telegram"})
        remember_chat.assert_called_once()


class TelegramBotFormatterTests(unittest.TestCase):
    def test_response_chunking_prefers_paragraph_boundaries(self) -> None:
        text = "First paragraph.\n\nSecond paragraph is longer."

        chunks = chunk_telegram_response(text, 30)

        self.assertEqual(chunks, ["First paragraph.", "Second paragraph is longer."])

    def test_response_chunking_keeps_small_code_block_together(self) -> None:
        text = "Intro.\n\n```python\nprint('hello')\n```\n\nDone."

        chunks = chunk_telegram_response(text, 40)

        self.assertTrue(any("```python\nprint('hello')\n```" in chunk for chunk in chunks))


class TelegramBotToolTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_telegram_context()

    def test_normal_registry_does_not_expose_telegram_runtime_tools(self) -> None:
        registry = discover_tools(extension_catalog=load_extension_catalog())
        names = {tool.name for tool in registry.visible_tools()}

        self.assertNotIn("telegram_status", names)
        self.assertNotIn("telegram_send_file", names)
        self.assertNotIn("telegram_session_info", names)

    def test_telegram_tools_report_inactive_outside_runtime(self) -> None:
        status = telegram_status({})
        info = telegram_session_info({})

        self.assertFalse(status["active"])
        self.assertFalse(info["active"])

    def test_send_file_queues_absolute_file_for_current_chat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "report.txt"
            source.write_text("report ready", encoding="utf-8")
            outbox = root / "outbox"
            set_telegram_context(
                TelegramToolContext(
                    active=True,
                    chat_id="777",
                    session_path=str(root / "session.json"),
                    session_metadata={"turns": 1},
                    memory_mode="shared",
                    webhook_mode=False,
                    rate_limit={"limit_per_minute": 20},
                    session_count=1,
                    active_file_path="",
                    outbox_dir=outbox,
                    download_dir=root / "downloads",
                )
            )

            result = telegram_send_file({"file_path": f"`{source}`", "caption": "Report"})
            entries = drain_telegram_outbox("777", outbox)

        self.assertTrue(result["queued"])
        self.assertEqual(result["file_name"], "report.txt")
        self.assertEqual(entries[0]["file_path"], str(source.resolve()))
        self.assertEqual(entries[0]["caption"], "Report")

    def test_auto_queue_file_outputs_finds_rendered_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ai-report.md"
            source.write_text("report ready", encoding="utf-8")
            outbox = root / "outbox"
            set_telegram_context(
                TelegramToolContext(
                    active=True,
                    chat_id="777",
                    session_path=str(root / "session.json"),
                    session_metadata={"turns": 1},
                    memory_mode="shared",
                    webhook_mode=False,
                    rate_limit={"limit_per_minute": 20},
                    session_count=1,
                    active_file_path="",
                    outbox_dir=outbox,
                    download_dir=root / "downloads",
                    auto_send_file_result_paths=("rendered_report.output_path",),
                )
            )
            payload = json.dumps(
                {
                    "ok": True,
                    "tool": "run_jarvis_qa",
                    "result": {"rendered_report": {"output_path": str(source)}},
                }
            )

            queued = auto_queue_file_outputs(payload)
            entries = drain_telegram_outbox("777", outbox)

        self.assertEqual(queued, [source.resolve()])
        self.assertEqual(entries[0]["file_path"], str(source.resolve()))

    def test_auto_queue_file_outputs_ignores_unconfigured_path_strings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.py"
            source.write_text("print('not a deliverable')", encoding="utf-8")
            outbox = root / "outbox"
            set_telegram_context(
                TelegramToolContext(
                    active=True,
                    chat_id="777",
                    session_path=str(root / "session.json"),
                    session_metadata={"turns": 1},
                    memory_mode="shared",
                    webhook_mode=False,
                    rate_limit={"limit_per_minute": 20},
                    session_count=1,
                    active_file_path="",
                    outbox_dir=outbox,
                    download_dir=root / "downloads",
                    auto_send_file_result_paths=("rendered_report.output_path",),
                )
            )
            payload = json.dumps(
                {
                    "ok": True,
                    "tool": "inspect_source",
                    "result": {
                        "safe_user_output": f"Looked at {source}",
                        "notes": [{"path": str(source)}],
                    },
                }
            )

            queued = auto_queue_file_outputs(payload)
            entries = drain_telegram_outbox("777", outbox)

        self.assertEqual(queued, [])
        self.assertEqual(entries, [])

    def test_delivery_registry_defers_missing_generated_file_path(self) -> None:
        base = Mock()
        registry = TelegramDeliveryRegistry(base, send_files_inline=True)

        payload = json.loads(registry.execute("telegram_send_file", {"file_path": "missing-report.md"}))

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["result"]["deferred"])
        base.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
