from __future__ import annotations

import json
import os
import base64
import time
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from core.brain import Brain
from core.logic import (
    ProjectPaths,
    append_chat_turn,
    chat_turns_as_messages,
    read_chat_turns,
    read_markdown_skills,
    read_markdown_skill_summaries,
    read_memory,
    sanitize_skill_text,
    session_file,
    summarize_chat_turns,
)
from core.memory import (
    EmbeddingModel,
    PermanentMemory,
    chat_file_transcript,
    extract_durable_memories,
    normalize_memory_text,
    parse_key_value_line,
)
from core.pc_monitor import PcMonitor, PcMonitorConfig, _clean_json_text, format_activity_record
from core.nvidia_stt import (
    NvidiaSTTConfig,
    SpeechRecognitionWebSpeechToText,
    _extract_nvidia_streaming_text,
    _gain_pcm16,
    _microphone_device_index,
    _nvidia_metadata,
    create_speech_to_text,
)
from core.speech import (
    TTSConfig,
    _effect_sample_rate,
    _nvidia_tts_text,
    _process_pcm16,
    _voice_effect_settings,
    text_for_speech,
)
from core.telegram_audio import AudioTranscriptionConfig
from daemon.config import DaemonConfig
from daemon.analyzer import NEXT_ACTIONS_PROMPT, STATUS_REVIEW_PROMPT
from daemon.project_daemon import ProjectDaemon
from daemon.report import build_report
from daemon.tools import DaemonTools
from tool.date_time import DateTimeTool
from tool.gmail import GmailTool
from tool.google_calendar import GoogleCalendarTool
from tool.local_files import LocalFilesTool
from tool.music import MusicTool, MusicTrack
from tool.nvidia_image import NvidiaImageTool
from tool.registry import ToolRegistry
from tool.system_control import SystemControlTool
from tool.tavily_search import FreeSearchHTMLParser, TavilySearchTool
from tool.terminal import TerminalTool
from tool.weather import WeatherTool
from telegram_bot import TelegramBot, TelegramConfig, encode_multipart_form_data, split_message


class FakeLLM:
    def __init__(self) -> None:
        self.messages = []

    def chat(self, messages):
        self.messages = messages
        return "Test reply"


class StreamingFakeLLM:
    def __init__(self) -> None:
        self.chat_calls = []
        self.stream_messages = []

    def chat(self, messages):
        self.chat_calls.append(messages)
        return '{"tool":"none","args":{}}'

    def stream_chat(self, messages):
        self.stream_messages = messages
        yield "Hello"
        yield " there"


class FailingStreamFakeLLM:
    def __init__(self) -> None:
        self.chat_calls = []

    def chat(self, messages):
        self.chat_calls.append(messages)
        return '{"tool":"none","args":{}}' if len(self.chat_calls) == 1 else "Fallback reply"

    def stream_chat(self, messages):
        raise RuntimeError("stream failed")


class ToolFakeLLM:
    def __init__(self) -> None:
        self.stream_messages = []

    def chat(self, messages):
        return '{"tool":"date_time","args":{"timezone":"UTC"}}'

    def stream_chat(self, messages):
        self.stream_messages = messages
        yield "It is time."


class ContextPlanFakeLLM:
    def __init__(self, plan: str, reply: str = "Test reply") -> None:
        self.plan = plan
        self.reply = reply
        self.chat_calls = []
        self.stream_messages = []

    def chat(self, messages, **kwargs):
        self.chat_calls.append(messages)
        return self.plan

    def stream_chat(self, messages):
        self.stream_messages = messages
        yield self.reply


class SlowPlannerFakeLLM:
    def __init__(self, delay: float, reply: str = "Fast reply") -> None:
        self.delay = delay
        self.reply = reply
        self.planner_started = threading.Event()
        self.chat_calls = []
        self.stream_messages = []

    def chat(self, messages, **kwargs):
        self.chat_calls.append((messages, kwargs))
        self.planner_started.set()
        time.sleep(self.delay)
        return '{"tool":"terminal","args":{"command":"slow"},"needs_memory":false,"needs_pc":false,"needs_skills":false}'

    def stream_chat(self, messages):
        self.stream_messages = messages
        yield self.reply


class CalendarFollowupFakeLLM:
    def __init__(self) -> None:
        self.messages = []

    def chat(self, messages, **kwargs):
        self.messages = messages
        return '{"tool":"google_calendar","args":{"action":"list","calendar_id":"primary","max_results":10}}'


class FakeRivaAlternative:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript


class FakeRivaResult:
    def __init__(self, transcript: str, is_final: bool) -> None:
        self.alternatives = [FakeRivaAlternative(transcript)]
        self.is_final = is_final


class FakeRivaResponse:
    def __init__(self, *results: FakeRivaResult) -> None:
        self.results = list(results)


def _test_tts_config(**overrides):
    values = {
        "enabled": True,
        "provider": "nvidia",
        "voice": "Magpie-Multilingual.EN-US.Ray.Neutral",
        "rate": "+24%",
        "volume": "+80%",
        "pitch": "-8Hz",
        "nvidia_api_key": "test-key",
        "nvidia_tts_server": "grpc.nvcf.nvidia.com:443",
        "nvidia_tts_function_id": "877104f7-e885-42b9-8de8-f6e4c6303969",
        "nvidia_tts_language_code": "en-US",
        "nvidia_tts_use_ssl": True,
        "nvidia_tts_sample_rate": 44100,
        "nvidia_tts_streaming": True,
        "nvidia_tts_ssml": False,
        "voice_effect": "heavy",
        "heavy_pitch_factor": 1.05,
        "heavy_darkness": 0.62,
        "player": "auto",
    }
    values.update(overrides)
    return TTSConfig(**values)


class CountingEmbedding:
    cache_key = "counting:test"

    def __init__(self) -> None:
        self.query_calls = 0

    def embed_document(self, text):
        return [1.0, 0.0]

    def embed_query(self, text):
        self.query_calls += 1
        return [1.0, 0.0]


class SlowEmbedding:
    cache_key = "slow:test"

    def embed_document(self, text):
        time.sleep(0.4)
        return [1.0, 0.0]

    def embed_query(self, text):
        time.sleep(0.4)
        return [1.0, 0.0]


class FlatEmbedding:
    cache_key = "flat:test"

    def embed_document(self, text):
        return [1.0, 0.0]

    def embed_query(self, text):
        return [1.0, 0.0]


class FakeDaemonTools:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        return {
            "project": {
                "name": "test-project",
                "directories": ["core", "tool", "skills", "daemon", "tests"],
                "python_files": ["core/brain.py", "daemon/project_daemon.py", "daemon/report.py", "tool/registry.py", "tests/test_core.py"],
                "skill_files": ["skills/daemon-project-monitor.md"],
            },
            "branch": "master",
            "status": "M core/brain.py",
            "diff_stat": "core/brain.py | 10 +++++",
            "recent_commits": "abc123 test commit",
            "changed_files": ["core/brain.py"],
            "file_context": {"core/brain.py": "class Brain: pass"},
            "github": "origin https://github.com/example/repo.git",
        }


class FakeDaemonAnalyzer:
    def analyze(self, snapshot, events):
        return {
            "project_analysis": "Project Identity\n\nA fake project.",
            "status_review": "Verified Status\n\nTests passed.",
            "next_actions": "Immediate Next Step\n\nRun tests.",
        }


class FakeMusicStdin:
    def __init__(self) -> None:
        self.writes = []

    def write(self, value):
        self.writes.append(value)

    def flush(self) -> None:
        return None


class FakeMusicProcess:
    def __init__(self, command, **kwargs) -> None:
        self.command = command
        self.kwargs = kwargs
        self.stdin = FakeMusicStdin()
        self.terminated = threading.Event()
        self.killed = False

    def poll(self):
        return 0 if self.terminated.is_set() else None

    def wait(self, timeout=None):
        if timeout is None:
            self.terminated.wait(5)
            return 0
        self.terminated.wait(timeout)
        return 0

    def terminate(self) -> None:
        self.terminated.set()

    def kill(self) -> None:
        self.killed = True
        self.terminated.set()


class CoreTests(unittest.TestCase):
    def test_reads_markdown_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skills = Path(temp_dir)
            (skills / "search.md").write_text("Use search carefully.", encoding="utf-8")
            (skills / "pc-monitor-skill.md").write_text("Use observed activity.", encoding="utf-8")
            (skills / "permanent-memory.md").write_text("Internal memory details.", encoding="utf-8")

            result = read_markdown_skills(skills)

            self.assertIn("search.md", result)
            self.assertIn("Use search carefully.", result)
            self.assertIn("pc-monitor-skill.md", result)
            self.assertIn("Use observed activity.", result)
            self.assertNotIn("permanent-memory.md", result)

    def test_reads_compact_skill_summaries_without_relevance_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skills = Path(temp_dir)
            (skills / "weather-tool.md").write_text("Use for weather and forecast requests.", encoding="utf-8")
            (skills / "gmail-tool.md").write_text("Use for inbox and email requests.", encoding="utf-8")
            (skills / "terminal-tool.md").write_text("Use for PowerShell commands.", encoding="utf-8")
            (skills / "calendar-tool.md").write_text("Use for meetings and events.", encoding="utf-8")

            result = read_markdown_skill_summaries(skills, max_chars_per_file=80)

            self.assertIn("weather-tool.md", result)
            self.assertIn("gmail-tool.md", result)

    def test_sanitizes_internal_skill_details(self) -> None:
        text = "Use search.\nTool code: tool/search.py\nAPI key lives in .env\nUse results."

        result = sanitize_skill_text(text)

        self.assertIn("Use search.", result)
        self.assertIn("Use results.", result)
        self.assertNotIn("tool/search.py", result)
        self.assertNotIn(".env", result)

    def test_reads_txt_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = Path(temp_dir)
            (memory / "profile.txt").write_text("The user likes concise answers.", encoding="utf-8")

            result = read_memory(memory)

            self.assertIn("profile.txt", result)
            self.assertIn("concise answers", result)

    def test_reads_md_memory_from_data_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = Path(temp_dir)
            data = memory / "data"
            data.mkdir()
            (data / "daemon-report.md").write_text("# Daemon Project Report\n\nProgress exists.", encoding="utf-8")

            result = read_memory(memory)

            self.assertIn("daemon-report.md", result)
            self.assertIn("Progress exists.", result)

    def test_appends_chat_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            chat_file = Path(temp_dir) / "session.txt"

            append_chat_turn(chat_file, "User", "Hello")

            record = json.loads(chat_file.read_text(encoding="utf-8").strip())
            self.assertEqual(record["speaker"], "User")
            self.assertEqual(record["text"], "Hello")

    def test_session_files_are_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = session_file(Path(temp_dir))

            self.assertEqual(path.suffix, ".jsonl")

    def test_reads_chat_turns_and_converts_to_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            chat_file = Path(temp_dir) / "session.jsonl"
            append_chat_turn(chat_file, "Krish", "Can you run a speed test?")
            append_chat_turn(chat_file, "JARVIS", "Certainly, sir.")

            turns = read_chat_turns(chat_file)
            messages = chat_turns_as_messages(turns, "Krish", "JARVIS")
            summary = summarize_chat_turns(turns)

            self.assertEqual(messages[0]["role"], "user")
            self.assertEqual(messages[1]["role"], "assistant")
            self.assertIn("speed test", summary)

    def test_brain_builds_prompt_and_logs_chat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            (paths.skills / "notes.md").write_text("Always be helpful.", encoding="utf-8")
            (paths.memory_data / "profile.txt").write_text("User name is Sam.", encoding="utf-8")

            fake_llm = ContextPlanFakeLLM(
                '{"tool":"none","args":{},"needs_memory":true,"needs_pc":false,"needs_skills":true}'
            )
            class FakeTools:
                def planner_text(self):
                    return ""

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return "User name is Sam."

                def remember_from_user_text(self, user_text):
                    return 0

            brain = Brain(paths, fake_llm, "Sam", "Nova", paths.memory_chats / "session.txt", FakeTools(), FakeMemory())

            reply = brain.answer("Hi")

            self.assertEqual(reply, "Test reply")
            system_prompt = fake_llm.stream_messages[0]["content"]
            self.assertIn("You are Nova", system_prompt)
            self.assertIn("notes.md", system_prompt)
            self.assertIn("User name is Sam.", system_prompt)
            transcript = brain.current_chat.read_text(encoding="utf-8")
            records = [json.loads(line) for line in transcript.splitlines()]
            self.assertEqual(records[0]["speaker"], "Sam")
            self.assertEqual(records[0]["text"], "Hi")
            self.assertEqual(records[1]["speaker"], "Nova")
            self.assertEqual(records[1]["text"], "Test reply")

    def test_brain_builds_configured_language_policy(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ASSISTANT_INPUT_LANGUAGES": "English",
                "ASSISTANT_OUTPUT_LANGUAGE": "English",
            },
            clear=False,
        ):
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                paths = ProjectPaths.from_root(root)
                for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                    folder.mkdir()

                class FakeTools:
                    def planner_text(self):
                        return ""

                    def run(self, name, args):
                        return ""

                class FakeMemory:
                    def context_for(self, user_text):
                        return ""

                    def remember_from_user_text(self, user_text):
                        return 0

                brain = Brain(
                    paths,
                    ContextPlanFakeLLM('{"tool":"none","args":{}}'),
                    "Sam",
                    "Nova",
                    paths.memory_chats / "session.jsonl",
                    FakeTools(),
                    FakeMemory(),
                )

                system_prompt = brain.build_system_prompt()

        self.assertIn("Language behavior:", system_prompt)
        self.assertIn("English", system_prompt)
        self.assertIn("Reply only in English", system_prompt)

    def test_brain_fetches_memory_even_when_planner_does_not_request_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ""

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return "Favorite food: rice"

                def remember_from_user_text(self, user_text):
                    return 0

            llm = ContextPlanFakeLLM(
                '{"tool":"none","args":{},"needs_memory":false,"needs_pc":false,"needs_skills":false}'
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            reply = brain.answer("what is my favorite food?")

            self.assertEqual(reply, "Test reply")
            self.assertIn("Favorite food: rice", llm.stream_messages[0]["content"])

    def test_brain_uses_async_memory_write_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ""

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def __init__(self):
                    self.async_calls = []
                    self.sync_calls = []
                    self.refresh_calls = 0

                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    self.sync_calls.append(user_text)
                    return 0

                def remember_from_user_text_async(self, user_text):
                    self.async_calls.append(user_text)
                    return 0

                def refresh_index_async(self):
                    self.refresh_calls += 1
                    return 0

            memory = FakeMemory()
            llm = ContextPlanFakeLLM(
                '{"tool":"none","args":{},"needs_memory":false,"needs_pc":false,"needs_skills":false}'
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), memory)

            with patch.dict(os.environ, {"MEMORY_WRITE_ASYNC": "true"}, clear=False):
                reply = brain.answer("remember that I like fast responses")

            self.assertEqual(reply, "Test reply")
            self.assertEqual(memory.async_calls, ["remember that I like fast responses"])
            self.assertEqual(memory.sync_calls, [])
            self.assertEqual(memory.refresh_calls, 1)

    def test_persona_includes_jarvis_style(self) -> None:
        text = Path("persona.md").read_text(encoding="utf-8")

        self.assertIn("Name: JARVIS", text)
        self.assertIn("sir", text)
        self.assertIn("Krish", text)

    def test_answer_stream_logs_streamed_reply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ""

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = StreamingFakeLLM()
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            reply = "".join(brain.answer_stream("Hi"))

            self.assertEqual(reply, "Hello there")
            records = [json.loads(line) for line in brain.current_chat.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[-1]["text"], "Hello there")

    def test_answer_stream_falls_back_when_stream_fails_before_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ""

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = FailingStreamFakeLLM()
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            with patch.dict(os.environ, {"NVIDIA_STREAM_FALLBACK": "true"}, clear=False):
                reply = "".join(brain.answer_stream("Hi"))

            self.assertEqual(reply, "Fallback reply")

    def test_answer_stream_includes_prior_session_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ""

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            chat_file = paths.memory_chats / "session.jsonl"
            append_chat_turn(chat_file, "Sam", "Can you run a speed test?")
            append_chat_turn(chat_file, "Nova", "I can help with that.")
            llm = StreamingFakeLLM()
            brain = Brain(paths, llm, "Sam", "Nova", chat_file, FakeTools(), FakeMemory())

            "".join(brain.answer_stream("what have we discussed?"))
            contents = [message["content"] for message in llm.stream_messages]

            self.assertIn("Can you run a speed test?", contents)
            self.assertIn("I can help with that.", contents)
            self.assertIn("Current session so far", llm.stream_messages[0]["content"])

    def test_pc_monitor_records_and_formats_activity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            monitor = PcMonitor(
                Path(temp_dir),
                PcMonitorConfig(enabled=False, interval_seconds=30, max_records=50, context_records=3),
                snapshot_provider=lambda: {
                    "timestamp": "2026-04-30T20:00:00",
                    "active_window": "Visual Studio Code - ANKITA",
                    "memory_percent": 64.5,
                    "battery_percent": 88,
                    "top_processes": [{"name": "Code"}, {"name": "python"}],
                },
            )

            monitor.sample_once()
            context = monitor.context_for("what was I doing")

            self.assertIn("Visual Studio Code", context)
            self.assertIn("Code, python", context)
            self.assertIn("memory: 64.5%", context)

    def test_pc_monitor_context_prefers_valid_activity_over_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            monitor = PcMonitor(
                Path(temp_dir),
                PcMonitorConfig(enabled=False, interval_seconds=30, max_records=50, context_records=3),
            )
            monitor._append({"timestamp": "2026-04-30T20:00:00", "error": "Invalid control character"})
            monitor._append({"timestamp": "2026-04-30T20:00:30", "active_window": "Codex"})

            context = monitor.context_for("what am I doing")

            self.assertIn("active window: Codex", context)
            self.assertNotIn("monitor error", context)

    def test_activity_record_format_handles_errors(self) -> None:
        result = format_activity_record({"timestamp": "now", "error": "blocked"})

        self.assertIn("monitor error", result)

    def test_clean_json_text_removes_control_characters(self) -> None:
        result = json.loads(_clean_json_text('{"active_window":"A\x01B"}'))

        self.assertEqual(result["active_window"], "AB")

    def test_brain_includes_pc_context_in_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ""

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            class FakeMonitor:
                def context_for(self, user_text):
                    return "active window: Visual Studio Code"

            llm = ContextPlanFakeLLM(
                '{"tool":"none","args":{},"needs_memory":false,"needs_pc":true,"needs_skills":false}',
                reply="PC context noted.",
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory(), FakeMonitor())

            "".join(brain.answer_stream("what am I doing?"))

            self.assertIn("Observed PC activity", llm.stream_messages[0]["content"])
            self.assertIn("Visual Studio Code", llm.stream_messages[0]["content"])

    def test_brain_includes_skill_summaries_without_planner_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()
            (paths.skills / "pc-monitor-skill.md").write_text("Use observed activity carefully.", encoding="utf-8")

            class FakeTools:
                def planner_text(self):
                    return ""

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = ContextPlanFakeLLM(
                '{"tool":"none","args":{},"needs_memory":false,"needs_pc":false,"needs_skills":false}',
                reply="Skill context noted.",
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            "".join(brain.answer_stream("hello"))

            self.assertIn("pc-monitor-skill.md", llm.stream_messages[0]["content"])
            self.assertIn("Use observed activity carefully.", llm.stream_messages[0]["content"])

    def test_tool_planner_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ""

                def run(self, name, args):
                    return "should not run"

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = ContextPlanFakeLLM(
                '{"tool":"terminal","args":{"command":"Get-ChildItem"},"needs_memory":false,"needs_pc":false,"needs_skills":false}',
                reply="No tool ran.",
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            with patch.dict(os.environ, {"TOOL_PLANNER_ENABLED": "false"}, clear=False):
                reply = "".join(brain.answer_stream("list files"))

            self.assertEqual(reply, "No tool ran.")
            self.assertEqual(llm.chat_calls, [])
            self.assertNotIn("Useful context from a just-completed action", llm.stream_messages[0]["content"])

    def test_slow_planner_does_not_block_fast_context_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def __init__(self):
                    self.calls = []

                def planner_text(self):
                    return ToolRegistry().planner_text()

                def run(self, name, args):
                    self.calls.append((name, args))
                    return "tool should not run after planner budget"

            class FakeMemory:
                def context_for(self, user_text):
                    return "Favorite food: rice"

                def remember_from_user_text(self, user_text):
                    return 0

            class FakeMonitor:
                def context_for(self, user_text):
                    return "active window: Codex"

            tools = FakeTools()
            llm = SlowPlannerFakeLLM(delay=1.0)
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", tools, FakeMemory(), FakeMonitor())

            with patch.dict(
                os.environ,
                {
                    "TOOL_PLANNER_ENABLED": "true",
                    "TOOL_PLANNER_WAIT_SECONDS": "0.05",
                    "TOOL_PLANNER_TIMEOUT_SECONDS": "0.2",
                },
                clear=False,
            ):
                start = time.perf_counter()
                reply = "".join(brain.answer_stream("what do you know?"))
                elapsed = time.perf_counter() - start

            self.assertEqual(reply, "Fast reply")
            self.assertTrue(llm.planner_started.is_set())
            self.assertLess(elapsed, 0.75)
            self.assertEqual(tools.calls, [])
            self.assertIn("Favorite food: rice", llm.stream_messages[0]["content"])
            self.assertNotIn("active window: Codex", llm.stream_messages[0]["content"])

    def test_tool_success_is_answered_by_final_llm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = ToolFakeLLM()
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", ToolRegistry(), FakeMemory())

            reply = "".join(brain.answer_stream("What time is it?"))

            self.assertEqual(reply, "It is time.")
            self.assertTrue(llm.stream_messages)
            self.assertIn("Useful context from a just-completed action", llm.stream_messages[-1]["content"])
            self.assertIn("UTC", llm.stream_messages[-1]["content"])

    def test_tool_answer_prompt_does_not_receive_memory_pc_or_session_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ToolRegistry().planner_text()

                def run(self, name, args):
                    return "VERIFIED: app opened"

            class FakeMemory:
                def context_for(self, user_text):
                    return "Favorite food: rice"

                def remember_from_user_text(self, user_text):
                    return 0

            class FakeMonitor:
                def context_for(self, user_text):
                    return "active window: Codex"

            chat_file = paths.memory_chats / "session.jsonl"
            append_chat_turn(chat_file, "Sam", "private prior-session detail")
            llm = ContextPlanFakeLLM(
                '{"tool":"system_control","args":{"action":"open_app","target":"notepad"},"needs_memory":false,"needs_pc":false,"needs_skills":false}',
                reply="Notepad is open.",
            )
            brain = Brain(paths, llm, "Sam", "Nova", chat_file, FakeTools(), FakeMemory(), FakeMonitor())

            reply = "".join(brain.answer_stream("open notepad"))

            self.assertEqual(reply, "Notepad is open.")
            prompt = llm.stream_messages[0]["content"]
            user_message = llm.stream_messages[-1]["content"]
            self.assertIn("Use only that output", prompt)
            self.assertIn("VERIFIED: app opened", user_message)
            combined = "\n".join(message["content"] for message in llm.stream_messages)
            self.assertNotIn("Favorite food: rice", combined)
            self.assertNotIn("active window: Codex", combined)
            self.assertNotIn("private prior-session detail", combined)
            self.assertNotIn("Known user facts", prompt)
            self.assertNotIn("Observed PC activity", prompt)
            self.assertNotIn("Current session so far", prompt)

    def test_slow_tool_output_is_context_for_final_llm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ToolRegistry().planner_text()

                def run(self, name, args):
                    time.sleep(0.05)
                    return "terminal done"

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = ContextPlanFakeLLM(
                '{"tool":"terminal","args":{"command":"slow"},"needs_memory":false,"needs_pc":false,"needs_skills":false}',
                reply="The command finished.",
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            reply = "".join(brain.answer_stream("run a slow command"))

            self.assertEqual(reply, "The command finished.")
            self.assertIn("terminal done", llm.stream_messages[-1]["content"])

    def test_short_confirmation_uses_previous_tool_offer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def __init__(self):
                    self.calls = []

                def planner_text(self):
                    return ToolRegistry().planner_text()

                def run(self, name, args):
                    self.calls.append((name, args))
                    return "No upcoming Google Calendar events found."

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            tools = FakeTools()
            llm = CalendarFollowupFakeLLM()
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", tools, FakeMemory())
            prior_turns = [{"speaker": "Nova", "text": "Shall I brief you on your schedule for the day?"}]

            context = brain._tool_context_for("yeah", prior_turns)

            self.assertIn("No upcoming Google Calendar events", context)
            self.assertEqual(tools.calls[0][0], "google_calendar")
            self.assertIn("Shall I brief you", llm.messages[-1]["content"])

    def test_tool_planner_receives_local_skill_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()
            (paths.skills / "system-control-tool.md").write_text("Use this when sir asks to open apps.", encoding="utf-8")
            (paths.skills / "local-files-tool.md").write_text("Use this when sir asks to inspect local files.", encoding="utf-8")

            class FakeTools:
                def planner_text(self):
                    return ToolRegistry().planner_text()

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = ContextPlanFakeLLM(
                '{"tool":"system_control","args":{"action":"open_app","target":"notepa"},"needs_memory":false,"needs_pc":false,"needs_skills":false}'
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            decision = brain._decide_tool("open notepa")
            planner_prompt = llm.chat_calls[0][0]["content"]

            self.assertEqual(decision["tool"], "system_control")
            self.assertIn("system-control-tool.md", planner_prompt)
            self.assertIn("Use this when sir asks to open apps.", planner_prompt)
            self.assertIn("local-files-tool.md", planner_prompt)

    def test_tool_planner_prompt_exposes_search_and_brightness_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()
            (paths.skills / "tavily-web-search-tool.md").write_text(
                "Use this for current official facts, exam cutoffs, results, admissions, and likely-changing public information.",
                encoding="utf-8",
            )
            (paths.skills / "system-control-tool.md").write_text(
                "Use action=set_brightness for screen brightness, dimming, and brightening requests.",
                encoding="utf-8",
            )

            class FakeTools:
                def planner_text(self):
                    return ToolRegistry().planner_text()

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = ContextPlanFakeLLM(
                '{"tool":"tavily_search","args":{"query":"JEE Main 2026 OBC cutoff marks","max_results":5},"needs_memory":false,"needs_pc":false,"needs_skills":false}'
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            decision = brain._decide_tool("what is cutoff for jee mains 2026 obc")
            planner_prompt = llm.chat_calls[0][0]["content"]

            self.assertEqual(decision["tool"], "tavily_search")
            self.assertIn("exam cutoffs", planner_prompt)
            self.assertIn("When tavily_search is available", planner_prompt)
            self.assertIn("terminal is intentionally unrestricted", planner_prompt)
            self.assertIn("open_app for application/program names", planner_prompt)
            self.assertIn("set_brightness", planner_prompt)

    def test_open_app_plan_feeds_system_control_output_to_final_llm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()
            (paths.skills / "system-control-tool.md").write_text("Use this when sir asks to open apps.", encoding="utf-8")
            (paths.skills / "local-files-tool.md").write_text("Use this when sir asks to inspect local files.", encoding="utf-8")

            class FakeTools:
                def __init__(self):
                    self.calls = []

                def planner_text(self):
                    return ToolRegistry().planner_text()

                def run(self, name, args):
                    self.calls.append((name, args))
                    return "VERIFIED: app opened using shortcut: Notepad.lnk (process: notepad)"

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            tools = FakeTools()
            llm = ContextPlanFakeLLM(
                '{"tool":"system_control","args":{"action":"open_app","target":"notepa"},"needs_memory":false,"needs_pc":false,"needs_skills":false}',
                reply="Notepad is open now.",
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", tools, FakeMemory())

            reply = "".join(brain.answer_stream("open notepa"))

            self.assertEqual(reply, "Notepad is open now.")
            self.assertEqual(tools.calls, [("system_control", {"action": "open_app", "target": "notepa"})])
            self.assertIn("VERIFIED: app opened", llm.stream_messages[-1]["content"])

    def test_no_tool_prompt_forbids_external_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ""

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            brain = Brain(paths, FakeLLM(), "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())
            messages = brain._answer_messages("yeah", "", "", [], "No session messages yet.", "", "")

            self.assertIn("No external tool output is supplied", messages[0]["content"])
            self.assertIn("Connected capability registry", messages[0]["content"])
            self.assertIn("must not state or imply", messages[0]["content"])
            self.assertIn("physical-world service", messages[0]["content"])
            self.assertIn("existing state only", messages[0]["content"])

    def test_failed_tool_output_is_answered_by_final_llm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ToolRegistry().planner_text()

                def run(self, name, args):
                    return "FAILED: Google OAuth client secret file is missing.\nExpected: secrets/google-client-secret.json"

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = ContextPlanFakeLLM(
                '{"tool":"google_calendar","args":{"action":"list","calendar_id":"primary","max_results":10},"needs_memory":false,"needs_pc":false,"needs_skills":false}',
                reply="Calendar setup is missing, so I could not check it.",
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            reply = "".join(brain.answer_stream("brief me on my schedule"))

            self.assertEqual(reply, "Calendar setup is missing, so I could not check it.")
            self.assertIn("FAILED: Google OAuth client secret file is missing", llm.stream_messages[-1]["content"])

    def test_local_file_tool_success_is_answered_by_final_llm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ToolRegistry().planner_text()

                def run(self, name, args):
                    return "Local file access:\nAll local folders are accessible by default.\n- C:\\Users\\anime\\Desktop"

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = ContextPlanFakeLLM(
                '{"tool":"local_files","args":{"action":"roots"},"needs_memory":false,"needs_pc":false,"needs_skills":false}',
                reply="You can browse the Desktop folder.",
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            reply = "".join(brain.answer_stream("show allowed folders"))

            self.assertEqual(reply, "You can browse the Desktop folder.")
            self.assertIn("All local folders are accessible by default", llm.stream_messages[-1]["content"])

    def test_unsupported_tool_plan_is_answered_by_final_llm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ToolRegistry().planner_text()

                def run(self, name, args):
                    raise AssertionError("Unsupported plans must not run a tool")

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = ContextPlanFakeLLM(
                '{"tool":"unsupported","args":{},"unsupported_reason":"image generation is not connected","needs_memory":false,"needs_pc":false,"needs_skills":false}',
                reply="Image generation is not connected here.",
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            reply = "".join(brain.answer_stream("generate an image of a car"))

            self.assertEqual(reply, "Image generation is not connected here.")
            self.assertIn("Unsupported capability: image generation is not connected", llm.stream_messages[-1]["content"])

    def test_tool_decision_parser_handles_json(self) -> None:
        parsed = Brain._parse_tool_decision('```json\n{"tool":"date_time","args":{"timezone":"UTC"}}\n```')

        self.assertEqual(parsed["tool"], "date_time")
        self.assertEqual(parsed["args"], {"timezone": "UTC"})

    def test_tool_decision_parser_accepts_new_tools(self) -> None:
        for tool_name in ("weather", "system_control", "terminal", "local_files", "music", "image_generation", "gmail", "google_calendar"):
            parsed = Brain._parse_tool_decision(f'{{"tool":"{tool_name}","args":{{}}}}')

            self.assertEqual(parsed["tool"], tool_name)

    def test_tool_decision_parser_accepts_unsupported(self) -> None:
        parsed = Brain._parse_tool_decision(
            '{"tool":"unsupported","args":{},"unsupported_reason":"image generation is not connected"}'
        )

        self.assertEqual(parsed["tool"], "unsupported")
        self.assertEqual(parsed["unsupported_reason"], "image generation is not connected")

    def test_tool_decision_parser_repairs_unescaped_windows_paths(self) -> None:
        raw = (
            '{"tool":"terminal","args":{'
            '"command":"Get-ChildItem C:\\Users\\anime\\Downloads",'
            '"cwd":"C:\\Users\\anime\\Documents\\New project 4",'
            '"timeout":600'
            "}}"
        )

        parsed = Brain._parse_tool_decision(raw)

        self.assertEqual(parsed["tool"], "terminal")
        self.assertEqual(parsed["args"]["command"], "Get-ChildItem C:\\Users\\anime\\Downloads")
        self.assertEqual(parsed["args"]["cwd"], "C:\\Users\\anime\\Documents\\New project 4")

    def test_tool_planner_honors_bounded_timeout_and_token_budget(self) -> None:
        class KwargLLM:
            def __init__(self) -> None:
                self.kwargs = {}

            def chat(self, messages, **kwargs):
                self.kwargs = kwargs
                return '{"tool":"none","args":{}}'

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ""

                def run(self, name, args):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            llm = KwargLLM()
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            with patch.dict(os.environ, {"TOOL_PLANNER_MAX_TOKENS": "64", "TOOL_PLANNER_TIMEOUT_SECONDS": "1"}, clear=False):
                brain._decide_tool("hello")

            self.assertEqual(llm.kwargs["max_tokens"], 64)
            self.assertEqual(llm.kwargs["timeout"], 1.0)

    def test_tool_planner_wait_defaults_to_planner_timeout(self) -> None:
        with patch.dict(
            os.environ,
            {"TOOL_PLANNER_TIMEOUT_SECONDS": "12"},
            clear=True,
        ):
            self.assertEqual(Brain._tool_planner_wait_seconds(), 12.0)

    def test_tool_planner_does_not_use_keyword_fallback_when_planner_fails(self) -> None:
        class BadPlannerLLM:
            def chat(self, messages, **kwargs):
                return "terminal should run it"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            class FakeTools:
                def planner_text(self):
                    return ""

            class FakeMemory:
                def context_for(self, user_text):
                    return ""

                def remember_from_user_text(self, user_text):
                    return 0

            brain = Brain(paths, BadPlannerLLM(), "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())
            prompt = "Use the terminal tool to run exactly this command with cwd set to C:\\Users\\anime: python -m pip --version. Then answer."

            decision = brain._decide_tool(prompt)

            self.assertEqual(decision["tool"], "none")
            self.assertEqual(decision["args"], {})

    def test_extracts_durable_memory(self) -> None:
        memories = list(extract_durable_memories("remember that I prefer short answers"))

        self.assertEqual(memories, [])

    def test_skips_transient_memory(self) -> None:
        memories = list(extract_durable_memories("i am good"))

        self.assertEqual(memories, [])

    def test_permanent_memory_searches_data_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            (memory.data_dir / "profile.txt").write_text("The user loves Python automation.", encoding="utf-8")

            context = memory.context_for("python scripts", top_k=3)

            self.assertIn("Python automation", context)

    def test_permanent_memory_ingests_md_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            (memory.data_dir / "daemon-report.md").write_text("Project progress: daemon added.", encoding="utf-8")

            context = memory.context_for("daemon progress", top_k=3)

            self.assertIn("daemon added", context)

    def test_memory_context_reads_fresh_data_files_before_async_embedding_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(Path(temp_dir), SlowEmbedding())
            (memory.data_dir / "project-status.md").write_text(
                "# Project Status\n\nFresh daemon report says the vector bridge is ready.",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "MEMORY_WRITE_ASYNC": "true",
                    "MEMORY_LOW_LATENCY": "true",
                    "MEMORY_SEARCH_MODE": "fast",
                },
                clear=False,
            ):
                start = time.perf_counter()
                context = memory.context_for("project status vector bridge", top_k=3)
                elapsed = time.perf_counter() - start
                index_thread = memory._index_thread
                if index_thread is not None:
                    index_thread.join(timeout=3)

            self.assertLess(elapsed, 0.25)
            self.assertIn("vector bridge is ready", context)

    def test_chat_file_transcript_formats_jsonl_turns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            chat_file = Path(temp_dir) / "session.jsonl"
            append_chat_turn(chat_file, "Krish", "jarvis my fav food is rice")
            append_chat_turn(chat_file, "JARVIS", "Rice, sir.")
            with chat_file.open("a", encoding="utf-8") as handle:
                handle.write("not-json\n")

            transcript = chat_file_transcript(chat_file)

            self.assertIn("Krish: jarvis my fav food is rice", transcript)
            self.assertIn("JARVIS: Rice, sir.", transcript)
            self.assertNotIn("not-json", transcript)

    def test_permanent_memory_indexes_chat_sessions_for_recall(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            chat_file = memory.chats_dir / "session-older.jsonl"
            append_chat_turn(chat_file, "Krish", "jarvis my fav food is rice")
            append_chat_turn(chat_file, "JARVIS", "Rice, sir.")

            context = memory.context_for("my fav food?", top_k=3)
            hits = memory.semantic_search("my fav food?", top_k=5)

            self.assertIn("Krish: jarvis my fav food is rice", context)
            self.assertTrue(any(hit.kind == "chat_session" and "rice" in hit.text.lower() for hit in hits))

    def test_fast_memory_ranking_prefers_informative_turns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            append_chat_turn(memory.chats_dir / "session-question.jsonl", "Krish", "my fav food ?")
            append_chat_turn(memory.chats_dir / "session-answer.jsonl", "Krish", "jarvis my fav food is rice")
            memory.ingest_chat_files()

            with patch.dict(os.environ, {"MEMORY_SEARCH_MODE": "fast"}, clear=False):
                hits = memory.search("my fav food please", top_k=2)

            self.assertIn("rice", hits[0].text.lower())

    def test_cached_semantic_search_still_merges_fast_text_recall(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(Path(temp_dir), FlatEmbedding())
            memory.add("A completely unrelated archived turn.", source="old", kind="chat_session")
            memory.add("Krish: jarvis my fav food is rice", source="food", kind="chat_session")
            query = "my fav food and what am I doing right now?"
            memory._cached_query_embedding(query)

            with patch.dict(
                os.environ,
                {"MEMORY_LOW_LATENCY": "true", "MEMORY_SEARCH_MODE": "semantic"},
                clear=False,
            ):
                hits = memory.search(query, top_k=2)

            self.assertTrue(any("rice" in hit.text.lower() for hit in hits))

    def test_low_latency_memory_skips_semantic_scan_when_text_recall_is_enough(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(Path(temp_dir), FlatEmbedding())
            memory.add("Krish: jarvis my fav food is rice", source="food", kind="chat_session")
            memory.add("Krish: my fav food question", source="question", kind="chat_session")
            memory._cached_query_embedding("my fav food")

            def fail_semantic_scan(*args, **kwargs):
                raise AssertionError("semantic scan should not run on the low-latency hot path")

            memory._semantic_search_with_vector = fail_semantic_scan

            with patch.dict(
                os.environ,
                {
                    "MEMORY_LOW_LATENCY": "true",
                    "MEMORY_SEARCH_MODE": "semantic",
                    "MEMORY_LOW_LATENCY_MIN_TEXT_HITS": "2",
                },
                clear=False,
            ):
                hits = memory.search("my fav food", top_k=2)

            self.assertEqual(len(hits), 2)
            self.assertTrue(any("rice" in hit.text.lower() for hit in hits))

    def test_permanent_memory_reindexes_changed_chat_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            chat_file = memory.chats_dir / "session-older.jsonl"
            append_chat_turn(chat_file, "Krish", "The project codename is blue notebook.")

            first_count = memory.ingest_chat_files()
            second_count = memory.ingest_chat_files()
            append_chat_turn(chat_file, "Krish", "The project codename changed to green notebook.")
            third_count = memory.ingest_chat_files()
            context = memory.context_for("green notebook", top_k=3)

            self.assertEqual(first_count, 1)
            self.assertEqual(second_count, 0)
            self.assertEqual(third_count, 2)
            self.assertIn("green notebook", context)

    def test_chat_session_index_persists_across_memory_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_memory = PermanentMemory(
                root,
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            append_chat_turn(first_memory.chats_dir / "session-older.jsonl", "Krish", "The launch phrase is silver sunrise.")
            self.assertIn("silver sunrise", first_memory.context_for("launch phrase", top_k=3))

            second_memory = PermanentMemory(
                root,
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )

            self.assertIn("silver sunrise", second_memory.context_for("launch phrase", top_k=3))

    def test_async_memory_context_does_not_block_on_slow_chat_indexing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(Path(temp_dir), SlowEmbedding())
            append_chat_turn(memory.chats_dir / "session-older.jsonl", "Krish", "jarvis my fav food is rice")

            with patch.dict(
                os.environ,
                {
                    "MEMORY_WRITE_ASYNC": "true",
                    "MEMORY_LOW_LATENCY": "true",
                    "MEMORY_SEARCH_MODE": "semantic",
                },
                clear=False,
            ):
                start = time.perf_counter()
                first_context = memory.context_for("my fav food?", top_k=3)
                elapsed = time.perf_counter() - start

                deadline = time.time() + 3
                final_context = first_context
                while time.time() < deadline:
                    final_context = memory.context_for("my fav food?", top_k=3)
                    if "rice" in final_context:
                        break
                    time.sleep(0.05)
                while time.time() < deadline:
                    index_thread = memory._index_thread
                    if not memory._warming_queries and (index_thread is None or not index_thread.is_alive()):
                        break
                    time.sleep(0.05)

            self.assertLess(elapsed, 0.25)
            self.assertIn("rice", final_context)

    def test_permanent_memory_skips_unchanged_data_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            (memory.data_dir / "profile.txt").write_text("The user likes fast tools.", encoding="utf-8")

            first_count = memory.ingest_data_files()
            second_count = memory.ingest_data_files()

            self.assertEqual(first_count, 1)
            self.assertEqual(second_count, 0)

    def test_profile_context_pins_editable_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            (memory.data_dir / "profile.txt").write_text(
                "Name: Krish\nLocation: Delhi\nProject: Yantra",
                encoding="utf-8",
            )

            context = memory.context_for("who am i", top_k=1)

            self.assertIn("Name: Krish", context)
            self.assertIn("Project: Yantra", context)

    def test_profile_value_reads_key_value_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            (memory.data_dir / "profile.txt").write_text("Name: Krish", encoding="utf-8")

            self.assertEqual(memory.profile_value("Name"), "Krish")
            self.assertEqual(parse_key_value_line("Location: Delhi"), ("Location", "Delhi"))

    def test_semantic_query_embedding_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            embedding = CountingEmbedding()
            memory = PermanentMemory(Path(temp_dir), embedding)
            memory.add("The user is building Yantra.", source="test", kind="fact")

            first = memory.semantic_search("Yantra project", top_k=1)
            second = memory.semantic_search("Yantra project", top_k=1)

            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            self.assertEqual(embedding.query_calls, 1)

    def test_permanent_memory_uses_chat_session_index_for_user_statements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            append_chat_turn(memory.chats_dir / "session-current.jsonl", "Krish", "remember that I am building a personal AI assistant")

            saved = memory.remember_from_user_text("remember that I am building a personal AI assistant")
            context = memory.context_for("personal assistant", top_k=3)

            self.assertEqual(saved, 0)
            self.assertIn("personal AI assistant", context)

    def test_memory_context_hides_sources_and_scores(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            (memory.data_dir / "profile.txt").write_text("Name: Krish", encoding="utf-8")
            memory.add("Food: pizza", source="test", kind="fact")

            context = memory.context_for("pizza food", top_k=3)

            self.assertIn("Name: Krish", context)
            self.assertIn("Food: pizza", context)
            self.assertNotIn("score=", context)
            self.assertNotIn("profile.txt", context)

    def test_normalizes_memory_text(self) -> None:
        self.assertEqual(normalize_memory_text("  i like pizza in food. "), "i like pizza in food")
        self.assertEqual(normalize_memory_text("i am good"), "i am good")

    def test_date_time_tool_returns_timezone_text(self) -> None:
        result = DateTimeTool().run("UTC")

        self.assertIn("UTC", result)
        self.assertIn("ISO date/time:", result)
        self.assertIn("UTC offset:", result)
        self.assertIn("Time of day:", result)
        self.assertIn("Morning now:", result)

    def test_date_time_tool_compares_and_converts_timezones(self) -> None:
        compare = DateTimeTool().run("UTC", mode="compare", target_timezone="Asia/Kolkata")
        converted = DateTimeTool().run(
            "UTC",
            mode="convert",
            target_timezone="Asia/Kolkata",
            source_time="2026-05-03T12:00:00",
        )

        self.assertIn("UTC:", compare)
        self.assertIn("Asia/Kolkata:", compare)
        self.assertIn("Offset difference:", compare)
        self.assertIn("Source:", converted)
        self.assertIn("Converted:", converted)
        self.assertIn("2026-05-03T17:30:00+05:30", converted)

    def test_tavily_formats_results(self) -> None:
        body = {
            "answer": "Short answer.",
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com",
                    "content": "Example summary.",
                    "score": 0.91,
                    "published_date": "2026-05-02",
                }
            ],
        }

        result = TavilySearchTool._format_results(body, query="example query")

        self.assertIn("example query", result)
        self.assertIn("Short answer.", result)
        self.assertIn("https://example.com", result)
        self.assertIn("published 2026-05-02", result)
        self.assertIn("score 0.910", result)

    def test_tavily_builds_pro_request_payload(self) -> None:
        payloads = []

        class FakeTavily(TavilySearchTool):
            def _request(self, **kwargs):
                payloads.append(kwargs)
                return {"answer": "ok", "results": []}

        result = FakeTavily(api_key="test").run(
            "latest python release",
            max_results=99,
            search_depth="basic",
            topic="news",
            include_domains="python.org, docs.python.org",
            exclude_domains=["example.com"],
            include_answer=True,
            include_raw_content=False,
            days=45,
        )

        self.assertIn("ok", result)
        self.assertEqual(payloads[0]["max_results"], 10)
        self.assertEqual(payloads[0]["search_depth"], "basic")
        self.assertEqual(payloads[0]["topic"], "news")
        self.assertEqual(payloads[0]["include_domains"], ["python.org", "docs.python.org"])
        self.assertEqual(payloads[0]["exclude_domains"], ["example.com"])
        self.assertEqual(payloads[0]["days"], 30)

    def test_free_search_parser_extracts_duckduckgo_results(self) -> None:
        parser = FreeSearchHTMLParser(max_results=1)
        parser.feed(
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">Example result</a>'
            '<a class="result__snippet">Example summary</a>'
        )

        self.assertEqual(len(parser.results), 1)
        self.assertEqual(parser.results[0].title, "Example result")
        self.assertEqual(parser.results[0].url, "https://example.com")
        self.assertEqual(parser.results[0].content, "Example summary")

    def test_tavily_uses_free_search_fallback_without_api_key(self) -> None:
        calls = []

        class FakeFreeSearch(TavilySearchTool):
            def _free_search(self, query, max_results):
                calls.append((query, max_results))
                return {
                    "answer": "",
                    "results": [
                        {
                            "title": "Free result",
                            "url": "https://example.com",
                            "content": "Free summary",
                        }
                    ],
                }

        with patch.dict(os.environ, {"TAVILY_API_KEY": "", "TAVILY_FREE_FALLBACK": "true"}, clear=False):
            result = FakeFreeSearch().run("latest free search", max_results=3)

        self.assertIn("Free result", result)
        self.assertEqual(calls, [("latest free search", 3)])

    def test_weather_formats_wttr_json(self) -> None:
        data = {
            "current_condition": [
                {
                    "temp_C": "31",
                    "FeelsLikeC": "33",
                    "humidity": "48",
                    "windspeedKmph": "12",
                    "uvIndex": "6",
                    "weatherDesc": [{"value": "Clear"}],
                }
            ],
            "nearest_area": [
                {
                    "areaName": [{"value": "Delhi"}],
                    "region": [{"value": "Delhi"}],
                    "country": [{"value": "India"}],
                }
            ],
            "weather": [{"astronomy": [{"sunrise": "05:40 AM", "sunset": "06:55 PM"}]}],
        }

        result = WeatherTool._format(data, fallback_location="Delhi")

        self.assertIn("Weather for Delhi", result)
        self.assertIn("31 deg C", result)
        self.assertIn("Clear", result)

    def test_weather_formats_pro_forecast_hourly_and_advisories(self) -> None:
        data = {
            "current_condition": [
                {
                    "temp_C": "39",
                    "FeelsLikeC": "41",
                    "humidity": "52",
                    "windspeedKmph": "45",
                    "uvIndex": "8",
                    "visibility": "3",
                    "precipMM": "0.4",
                    "pressure": "1002",
                    "weatherDesc": [{"value": "Sunny"}],
                }
            ],
            "nearest_area": [
                {
                    "areaName": [{"value": "Delhi"}],
                    "region": [{"value": "Delhi"}],
                    "country": [{"value": "India"}],
                }
            ],
            "weather": [
                {
                    "date": "2026-05-02",
                    "maxtempC": "42",
                    "mintempC": "29",
                    "uvIndex": "8",
                    "astronomy": [{"sunrise": "05:40 AM", "sunset": "06:55 PM"}],
                    "hourly": [
                        {
                            "time": "900",
                            "tempC": "35",
                            "FeelsLikeC": "39",
                            "windspeedKmph": "20",
                            "chanceofrain": "20",
                            "chanceofthunder": "10",
                            "chanceofsnow": "0",
                            "weatherDesc": [{"value": "Sunny"}],
                        },
                        {
                            "time": "1500",
                            "tempC": "41",
                            "FeelsLikeC": "46",
                            "windspeedKmph": "45",
                            "chanceofrain": "70",
                            "chanceofthunder": "55",
                            "chanceofsnow": "0",
                            "weatherDesc": [{"value": "Thunderstorm"}],
                        },
                    ],
                }
            ],
        }

        result = WeatherTool._format(data, fallback_location="Delhi", mode="pro", days=1, hourly_slots=2)

        self.assertIn("Advisories:", result)
        self.assertIn("heat stress likely", result)
        self.assertIn("strong wind", result)
        self.assertIn("low visibility", result)
        self.assertIn("high UV", result)
        self.assertIn("rain chance peaks near 70%", result)
        self.assertIn("storm chance peaks near 55%", result)
        self.assertIn("Forecast:", result)
        self.assertIn("high 42 deg C, low 29 deg C", result)
        self.assertIn("rain 70%, storm 55%, snow 0%", result)
        self.assertIn("Hourly:", result)
        self.assertIn("2026-05-02 09:00", result)
        self.assertIn("2026-05-02 15:00", result)

    def test_weather_supports_imperial_units(self) -> None:
        data = {
            "current_condition": [
                {
                    "temp_F": "88",
                    "FeelsLikeF": "91",
                    "humidity": "48",
                    "windspeedMiles": "7",
                    "uvIndex": "6",
                    "visibilityMiles": "5",
                    "precipInches": "0",
                    "weatherDesc": [{"value": "Clear"}],
                }
            ],
            "nearest_area": [{"areaName": [{"value": "Austin"}], "region": [{"value": "Texas"}]}],
            "weather": [],
        }

        result = WeatherTool._format(data, fallback_location="Austin", units="imperial")

        self.assertIn("88 deg F", result)
        self.assertIn("feels like 91 deg F", result)
        self.assertIn("wind 7 mph", result)
        self.assertIn("visibility 5 mi", result)

    def test_gmail_raw_email_encodes_content(self) -> None:
        raw = GmailTool._raw_email("sir@example.com", "Status", "All systems green.")

        self.assertIsInstance(raw, str)
        self.assertIn("QWxsIHN5c3RlbXMgZ3JlZW4u", raw)

    def test_google_calendar_parses_iso_datetime(self) -> None:
        parsed = GoogleCalendarTool._parse_datetime("2026-05-01T10:30:00+05:30")

        self.assertEqual(parsed.isoformat(), "2026-05-01T10:30:00+05:30")

    def test_registry_includes_google_tools(self) -> None:
        registry = ToolRegistry()
        specs = {spec.name: spec for spec in registry.specs()}

        self.assertIn("gmail", specs)
        self.assertIn("google_calendar", specs)
        self.assertIn("local_files", specs)
        self.assertIn("music", specs)
        self.assertIn("image_generation", specs)
        self.assertIn("email", specs["gmail"].description.lower())
        self.assertIn("calendar", specs["google_calendar"].description.lower())
        self.assertIn("all local folders", specs["local_files"].description.lower())
        self.assertIn("yt-dlp", specs["music"].description.lower())
        self.assertIn("nvidia", specs["image_generation"].description.lower())
        self.assertIn("exam cutoffs", specs["tavily_search"].description.lower())
        self.assertIn("screen/display brightness", specs["system_control"].description.lower())
        self.assertIn("downloads", specs["terminal"].description.lower())
        self.assertIn("domain filters", specs["tavily_search"].description.lower())

    def test_registry_routes_weather_pro_arguments(self) -> None:
        class FakeWeather:
            def __init__(self) -> None:
                self.kwargs = {}

            def run(self, **kwargs):
                self.kwargs = kwargs
                return "weather-ok"

        registry = ToolRegistry()
        fake_weather = FakeWeather()
        registry.weather = fake_weather

        result = registry.run(
            "weather",
            {
                "location": "Mumbai",
                "mode": "forecast",
                "days": 2,
                "units": "imperial",
                "include_hourly": True,
                "hourly_slots": 3,
            },
        )

        self.assertEqual(result, "weather-ok")
        self.assertEqual(fake_weather.kwargs["location"], "Mumbai")
        self.assertEqual(fake_weather.kwargs["mode"], "forecast")
        self.assertEqual(fake_weather.kwargs["days"], 2)
        self.assertEqual(fake_weather.kwargs["units"], "imperial")
        self.assertTrue(fake_weather.kwargs["include_hourly"])
        self.assertEqual(fake_weather.kwargs["hourly_slots"], 3)

    def test_registry_routes_local_files_pro_arguments(self) -> None:
        class FakeLocalFiles:
            def __init__(self) -> None:
                self.kwargs = {}

            def run(self, **kwargs):
                self.kwargs = kwargs
                return "local-files-ok"

        registry = ToolRegistry()
        fake_local_files = FakeLocalFiles()
        registry.local_files = fake_local_files

        result = registry.run(
            "local_files",
            {
                "action": "search",
                "path": "Pictures",
                "query": "invoice",
                "recursive": True,
                "max_depth": 4,
                "include_hidden": True,
                "file_types": "image,document",
                "sort": "modified",
                "search_mode": "both",
                "preview_chars": 300,
            },
        )

        self.assertEqual(result, "local-files-ok")
        self.assertEqual(fake_local_files.kwargs["action"], "search")
        self.assertEqual(fake_local_files.kwargs["path"], "Pictures")
        self.assertEqual(fake_local_files.kwargs["query"], "invoice")
        self.assertTrue(fake_local_files.kwargs["recursive"])
        self.assertEqual(fake_local_files.kwargs["max_depth"], 4)
        self.assertTrue(fake_local_files.kwargs["include_hidden"])
        self.assertEqual(fake_local_files.kwargs["file_types"], "image,document")
        self.assertEqual(fake_local_files.kwargs["sort"], "modified")
        self.assertEqual(fake_local_files.kwargs["search_mode"], "both")
        self.assertEqual(fake_local_files.kwargs["preview_chars"], 300)

    def test_registry_routes_terminal_pro_arguments(self) -> None:
        class FakeTerminal:
            def __init__(self) -> None:
                self.kwargs = {}

            def run(self, **kwargs):
                self.kwargs = kwargs
                return "terminal-ok"

        registry = ToolRegistry()
        fake_terminal = FakeTerminal()
        registry.terminal = fake_terminal

        result = registry.run(
            "terminal",
            {
                "command": "python -m pip install example",
                "cwd": ".",
                "timeout": 600,
                "shell": "powershell",
                "stdin": "input text",
                "env": {"EXAMPLE_FLAG": "1"},
                "max_output_chars": 5000,
            },
        )

        self.assertEqual(result, "terminal-ok")
        self.assertEqual(fake_terminal.kwargs["command"], "python -m pip install example")
        self.assertEqual(fake_terminal.kwargs["cwd"], ".")
        self.assertEqual(fake_terminal.kwargs["timeout"], 600)
        self.assertEqual(fake_terminal.kwargs["shell"], "powershell")
        self.assertEqual(fake_terminal.kwargs["stdin"], "input text")
        self.assertEqual(fake_terminal.kwargs["env"], {"EXAMPLE_FLAG": "1"})
        self.assertEqual(fake_terminal.kwargs["max_output_chars"], 5000)

    def test_registry_routes_system_control_pro_arguments(self) -> None:
        class FakeSystemControl:
            def __init__(self) -> None:
                self.kwargs = {}

            def run(self, **kwargs):
                self.kwargs = kwargs
                return "system-ok"

        registry = ToolRegistry()
        fake_system = FakeSystemControl()
        registry.system_control = fake_system

        result = registry.run(
            "system_control",
            {
                "action": "brightness_down",
                "amount": 12,
                "query": "display",
                "value": 40,
            },
        )

        self.assertEqual(result, "system-ok")
        self.assertEqual(fake_system.kwargs["action"], "brightness_down")
        self.assertEqual(fake_system.kwargs["amount"], 12)
        self.assertEqual(fake_system.kwargs["target"], "display")
        self.assertEqual(fake_system.kwargs["value"], 40)

    def test_registry_routes_tavily_pro_arguments(self) -> None:
        class FakeTavily:
            def __init__(self) -> None:
                self.kwargs = {}

            def run(self, **kwargs):
                self.kwargs = kwargs
                return "search-ok"

        registry = ToolRegistry()
        fake_tavily = FakeTavily()
        registry.tavily_search = fake_tavily

        result = registry.run(
            "tavily_search",
            {
                "query": "latest openai api docs",
                "max_results": 7,
                "search_depth": "advanced",
                "topic": "news",
                "include_domains": "openai.com",
                "exclude_domains": "example.com",
                "include_answer": False,
                "include_raw_content": True,
                "days": 3,
            },
        )

        self.assertEqual(result, "search-ok")
        self.assertEqual(fake_tavily.kwargs["query"], "latest openai api docs")
        self.assertEqual(fake_tavily.kwargs["max_results"], 7)
        self.assertEqual(fake_tavily.kwargs["search_depth"], "advanced")
        self.assertEqual(fake_tavily.kwargs["topic"], "news")
        self.assertEqual(fake_tavily.kwargs["include_domains"], "openai.com")
        self.assertEqual(fake_tavily.kwargs["exclude_domains"], "example.com")
        self.assertFalse(fake_tavily.kwargs["include_answer"])
        self.assertTrue(fake_tavily.kwargs["include_raw_content"])
        self.assertEqual(fake_tavily.kwargs["days"], 3)

    def test_music_tool_resolves_user_query_and_starts_player(self) -> None:
        queries = []
        processes = []

        def resolver(query):
            queries.append(query)
            return MusicTrack(
                title=f"Resolved {query}",
                webpage_url="https://example.com/watch",
                stream_url="https://media.example.com/audio",
                duration=187,
                artist="Test Artist",
            )

        def process_factory(command, **kwargs):
            process = FakeMusicProcess(command, **kwargs)
            processes.append(process)
            return process

        with patch("tool.music._find_executable", return_value="mpv"):
            tool = MusicTool(resolver=resolver, process_factory=process_factory)
            result = tool.run(action="play", query="anything sir wants", player="mpv")
            pause_result = tool.run(action="pause")
            resume_result = tool.run(action="resume")
            stop_result = tool.run(action="stop")

        self.assertEqual(queries, ["anything sir wants"])
        self.assertIn("Playing: Resolved anything sir wants by Test Artist (3:07)", result)
        self.assertIn("Backend: mpv", result)
        self.assertIn("https://example.com/watch", processes[0].command)
        self.assertEqual(pause_result, "Music paused.")
        self.assertEqual(resume_result, "Music resumed.")
        self.assertEqual(processes[0].stdin.writes, [b"p\n", b"p\n"])
        self.assertEqual(stop_result, "Music stopped.")

    def test_music_tool_queues_when_track_is_already_playing(self) -> None:
        processes = []

        def resolver(query):
            return MusicTrack(
                title=query.title(),
                webpage_url=f"https://example.com/{query}",
                stream_url=f"https://media.example.com/{query}",
            )

        def process_factory(command, **kwargs):
            process = FakeMusicProcess(command, **kwargs)
            processes.append(process)
            return process

        with patch("tool.music._find_executable", return_value="mpv"):
            tool = MusicTool(resolver=resolver, process_factory=process_factory)
            play_result = tool.run(action="play", query="first", player="mpv")
            queue_result = tool.run(action="queue", query="second", player="mpv")
            status = tool.run(action="status")
            tool.run(action="stop")

        self.assertIn("Playing: First", play_result)
        self.assertIn("Queued: Second", queue_result)
        self.assertIn("Queue size: 1", status)
        self.assertEqual(len(processes), 1)

    def test_local_files_tool_defaults_to_all_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as quick_root, tempfile.TemporaryDirectory() as other_dir:
            quick = Path(quick_root)
            other = Path(other_dir)
            (quick / "notes.txt").write_text("Quick note.", encoding="utf-8")
            (other / "open.txt").write_text("Open local file.", encoding="utf-8")

            env = {
                "LOCAL_FILE_ALLOWED_PATHS": str(quick),
                "LOCAL_FILE_RESTRICT_TO_ALLOWED_PATHS": "false",
            }
            with patch.dict(os.environ, env, clear=False):
                tool = LocalFilesTool()
                roots_result = tool.run("roots")
                quick_result = tool.run("read", path=str(quick / "notes.txt"))
                other_result = tool.run("read", path=str(other / "open.txt"))

            self.assertIn("All local folders are accessible by default", roots_result)
            self.assertIn("Quick note.", quick_result)
            self.assertIn("Open local file.", other_result)

    def test_local_files_tool_can_still_restrict_when_explicitly_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as allowed_dir, tempfile.TemporaryDirectory() as blocked_dir:
            allowed = Path(allowed_dir)
            blocked = Path(blocked_dir)
            (allowed / "notes.txt").write_text("Allowed note.", encoding="utf-8")
            (blocked / "secret.txt").write_text("Blocked note.", encoding="utf-8")

            env = {
                "LOCAL_FILE_ALLOWED_PATHS": str(allowed),
                "LOCAL_FILE_RESTRICT_TO_ALLOWED_PATHS": "true",
            }
            with patch.dict(os.environ, env, clear=False):
                tool = LocalFilesTool()
                allowed_result = tool.run("read", path=str(allowed / "notes.txt"))
                blocked_result = tool.run("read", path=str(blocked / "secret.txt"))

            self.assertIn("Allowed note.", allowed_result)
            self.assertIn("FAILED:", blocked_result)
            self.assertIn("outside the configured local folders", blocked_result)

    def test_local_files_tool_resolves_known_folder_aliases(self) -> None:
        desktop = Path.home() / "Desktop"
        desktop.mkdir(exist_ok=True)

        with patch.dict(os.environ, {"LOCAL_FILE_ALLOWED_PATHS": str(desktop)}, clear=False):
            result = LocalFilesTool().run("list", path="Desktop", max_results=5)

        self.assertIn(f"Folder: {desktop}", result)

    def test_local_files_tool_treats_local_folders_phrase_as_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOCAL_FILE_ALLOWED_PATHS": temp_dir}, clear=False):
                result = LocalFilesTool().run("list", path="local folders")

        self.assertIn("Local file access:", result)
        self.assertIn(temp_dir, result)

    def test_local_files_tool_searches_content_and_reports_image_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "notes.txt").write_text("Remember the blue launch folder.", encoding="utf-8")
            image = root / "photo.png"
            image.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + (13).to_bytes(4, "big")
                + b"IHDR"
                + (640).to_bytes(4, "big")
                + (480).to_bytes(4, "big")
                + b"\x08\x02\x00\x00\x00"
            )

            tool = LocalFilesTool()
            search_result = tool.run("search", path=temp_dir, query="blue launch", search_mode="both")
            image_result = tool.run("stat", path=str(image))
            list_result = tool.run("list", path=temp_dir, file_types="image")

        self.assertIn("notes.txt", search_result)
        self.assertIn("match:", search_result)
        self.assertIn("640x480 image", image_result)
        self.assertIn("photo.png", list_result)
        self.assertIn("640x480 image", list_result)

    def test_nvidia_image_tool_saves_openai_image_response(self) -> None:
        class FakeImageTool(NvidiaImageTool):
            def _request(self, prompt: str, n: int, size: str = "", seed: int | None = None):
                return {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode("ascii")}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "generated.png"
            env = {
                "LOCAL_FILE_ALLOWED_PATHS": temp_dir,
                "NVIDIA_IMAGE_MODEL": "black-forest-labs/flux.2-klein-4b",
            }
            with patch.dict(os.environ, env, clear=False):
                result = FakeImageTool(api_key="test-key", base_url="http://localhost:8000/v1").run(
                    "small red cube",
                    output_path=str(output),
                )

            self.assertEqual(output.read_bytes(), b"image-bytes")
            self.assertIn("Generated 1 image", result)
            self.assertIn(str(output), result)
            metadata = json.loads(output.with_suffix(".png.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["prompt"], "small red cube")
            self.assertEqual(metadata["model"], "black-forest-labs/flux.2-klein-4b")

    def test_nvidia_image_tool_saves_artifacts_response(self) -> None:
        class FakeImageTool(NvidiaImageTool):
            def _request(self, prompt: str, n: int, size: str = "", seed: int | None = None):
                return {"artifacts": [{"base64": base64.b64encode(b"artifact-bytes").decode("ascii")}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "artifact.png"
            env = {
                "LOCAL_FILE_ALLOWED_PATHS": temp_dir,
                "NVIDIA_IMAGE_ENDPOINT": "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev",
            }
            with patch.dict(os.environ, env, clear=False):
                result = FakeImageTool(api_key="test-key").run("small blue cube", output_path=str(output))

            self.assertEqual(output.read_bytes(), b"artifact-bytes")
            self.assertIn("black-forest-labs/flux.1-dev", result)

    def test_nvidia_image_tool_splits_multi_image_genai_requests(self) -> None:
        class FakeImageTool(NvidiaImageTool):
            def __init__(self) -> None:
                super().__init__(api_key="test-key")
                self.payloads = []

            def _endpoint(self) -> str:
                return "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"

            def _post(self, endpoint: str, key: str, payload: dict[str, object]):
                self.payloads.append(payload)
                encoded = base64.b64encode(f"image-{len(self.payloads)}".encode("ascii")).decode("ascii")
                return {"artifacts": [{"base64": encoded}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "LOCAL_FILE_ALLOWED_PATHS": temp_dir,
                "NVIDIA_IMAGE_MAX_SAMPLES_PER_REQUEST": "1",
            }
            with patch.dict(os.environ, env, clear=False):
                tool = FakeImageTool()
                result = tool.run("small green cube", output_path=temp_dir, n=2)

            self.assertEqual(len(tool.payloads), 2)
            self.assertEqual([payload["samples"] for payload in tool.payloads], [1, 1])
            self.assertIn("Generated 2 image", result)

    def test_nvidia_image_tool_streams_progress_and_returns_final_result(self) -> None:
        class FakeImageTool(NvidiaImageTool):
            def __init__(self) -> None:
                super().__init__(api_key="test-key")
                self.calls = 0

            def _request(self, prompt: str, n: int, size: str = "", seed: int | None = None):
                self.calls += 1
                encoded = base64.b64encode(f"stream-image-{self.calls}".encode("ascii")).decode("ascii")
                return {"artifacts": [{"base64": encoded}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "LOCAL_FILE_ALLOWED_PATHS": temp_dir,
                "NVIDIA_IMAGE_ENDPOINT": "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev",
            }
            with patch.dict(os.environ, env, clear=False):
                stream = FakeImageTool().run_stream("small orange cube", output_path=temp_dir, n=2, seed=10)
                chunks: list[str] = []
                while True:
                    try:
                        chunks.append(next(stream))
                    except StopIteration as done:
                        result = done.value
                        break

            self.assertEqual(chunks, ["Generating image 1/2...\n", "Generating image 2/2...\n"])
            self.assertIn("Generated 2 image", result)
            saved = sorted(Path(temp_dir).glob("*.png"))
            self.assertEqual(len(saved), 2)
            metadata = [json.loads(path.with_suffix(".png.json").read_text(encoding="utf-8")) for path in saved]
            self.assertEqual([item["seed"] for item in metadata], [10, 11])

    def test_nvidia_image_tool_retries_transient_failures_once(self) -> None:
        class RetryImageTool(NvidiaImageTool):
            def __init__(self) -> None:
                super().__init__(api_key="test-key")
                self.calls = 0

            def _endpoint(self) -> str:
                return "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"

            def _post(self, endpoint: str, key: str, payload: dict[str, object]):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("429 rate limited")
                return {"artifacts": [{"base64": base64.b64encode(b"retry-ok").decode("ascii")}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "LOCAL_FILE_ALLOWED_PATHS": temp_dir,
                "NVIDIA_IMAGE_RETRY_ATTEMPTS": "2",
                "NVIDIA_IMAGE_RETRY_DELAY_SECONDS": "0",
            }
            with patch.dict(os.environ, env, clear=False):
                tool = RetryImageTool()
                result = tool.run("small purple cube", output_path=temp_dir)

            self.assertEqual(tool.calls, 2)
            self.assertIn("Generated 1 image", result)

    def test_google_tools_return_setup_guidance_without_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "GOOGLE_CLIENT_SECRET_FILE": str(Path(temp_dir) / "missing-client-secret.json"),
                "GOOGLE_TOKEN_FILE": str(Path(temp_dir) / "missing-token.json"),
            }
            with patch.dict(os.environ, env, clear=False):
                result = GmailTool().run(action="search", query="newer_than:1d")

        if result.startswith("FAILED: Google API libraries are not installed."):
            self.assertIn("pip install google-api-python-client", result)
        else:
            self.assertIn("Google OAuth client secret file is missing", result)

    def test_telegram_splits_long_messages(self) -> None:
        chunks = split_message("x" * 8000)

        self.assertEqual(len(chunks), 3)
        self.assertLessEqual(max(len(chunk) for chunk in chunks), 3900)

    def test_telegram_audio_config_defaults_to_free_local_autodetect(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text("", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                config = AudioTranscriptionConfig.from_env(root)
                self.assertEqual(os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"], "1")
                self.assertEqual(os.environ["HF_HUB_VERBOSITY"], "error")

        self.assertTrue(config.enabled)
        self.assertEqual(config.model_name, "base")
        self.assertEqual(config.language, "")
        self.assertEqual(config.task, "transcribe")
        self.assertEqual(config.compute_type, "int8")
        self.assertTrue(str(config.download_root).endswith(str(Path("memory") / "store" / "faster-whisper")))

    def test_telegram_lists_and_sends_numbered_files(self) -> None:
        class FakePaths:
            def __init__(self, root: Path) -> None:
                self.root = root

        class FakeBrain:
            def __init__(self, root: Path) -> None:
                self.paths = FakePaths(root)

            def answer(self, text: str) -> str:
                return "brain reply"

        class FakeTranscriber:
            def status(self) -> str:
                return "enabled"

        class CapturingTelegramBot(TelegramBot):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                self.calls = []

            def _request(self, method, params, files=None, timeout=None):
                self.calls.append((method, params, files, timeout))
                return {"ok": True, "result": []}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_path = root / "alpha.txt"
            file_path.write_text("hello", encoding="utf-8")
            config = TelegramConfig(
                download_root=root / "downloads",
                export_root=root / "exports",
                max_send_mb=50,
                max_batch_send=5,
                list_limit=25,
                search_limit=20,
                search_depth=4,
                upload_timeout_seconds=180,
                request_timeout_seconds=35,
                typing_actions=False,
            )
            bot = CapturingTelegramBot(FakeBrain(root), "token", config=config, transcriber=FakeTranscriber())

            self.assertTrue(bot.handle_telegram_text("123", f"/files {root}"))
            self.assertIn("alpha.txt", bot.calls[-1][1]["text"])
            self.assertNotIn("/send", bot.calls[-1][1]["text"])
            self.assertTrue(bot.handle_telegram_text("123", "/send 1"))

        self.assertEqual(bot.calls[-1][0], "sendDocument")
        self.assertEqual(bot.calls[-1][2]["document"], file_path)

    def test_telegram_handles_natural_file_chat_without_commands(self) -> None:
        class FakePaths:
            def __init__(self, root: Path) -> None:
                self.root = root

        class FakeBrain:
            def __init__(self, root: Path) -> None:
                self.paths = FakePaths(root)
                self.answer_calls = []

            def answer(self, text: str) -> str:
                self.answer_calls.append(text)
                return "brain reply"

        class FakeTranscriber:
            def status(self) -> str:
                return "enabled"

        class CapturingTelegramBot(TelegramBot):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                self.calls = []

            def _request(self, method, params, files=None, timeout=None):
                self.calls.append((method, params, files, timeout))
                return {"ok": True, "result": []}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_path = root / "desktop.ini"
            file_path.write_text("hello", encoding="utf-8")
            config = TelegramConfig(
                download_root=root / "downloads",
                export_root=root / "exports",
                max_send_mb=50,
                max_batch_send=5,
                list_limit=25,
                search_limit=20,
                search_depth=4,
                upload_timeout_seconds=180,
                request_timeout_seconds=35,
                typing_actions=False,
            )
            brain = FakeBrain(root)
            bot = CapturingTelegramBot(brain, "token", config=config, transcriber=FakeTranscriber())

            self.assertTrue(bot.handle_telegram_text("123", f"show files in {root}"))
            self.assertIn("desktop.ini", bot.calls[-1][1]["text"])
            self.assertNotIn("/send", bot.calls[-1][1]["text"])
            self.assertTrue(bot.handle_telegram_text("123", "send desktop ini"))

        self.assertEqual(bot.calls[-1][0], "sendDocument")
        self.assertEqual(bot.calls[-1][2]["document"], file_path)
        self.assertEqual(brain.answer_calls, [])

    def test_telegram_keeps_casual_ack_short(self) -> None:
        class FakePaths:
            def __init__(self, root: Path) -> None:
                self.root = root

        class FakeBrain:
            def __init__(self, root: Path) -> None:
                self.paths = FakePaths(root)
                self.answer_calls = []

            def answer(self, text: str) -> str:
                self.answer_calls.append(text)
                return "brain reply"

        class FakeTranscriber:
            def status(self) -> str:
                return "enabled"

        class CapturingTelegramBot(TelegramBot):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                self.calls = []

            def _request(self, method, params, files=None, timeout=None):
                self.calls.append((method, params, files, timeout))
                return {"ok": True, "result": []}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = TelegramConfig(
                download_root=root / "downloads",
                export_root=root / "exports",
                max_send_mb=50,
                max_batch_send=5,
                list_limit=25,
                search_limit=20,
                search_depth=4,
                upload_timeout_seconds=180,
                request_timeout_seconds=35,
                typing_actions=False,
            )
            brain = FakeBrain(root)
            bot = CapturingTelegramBot(brain, "token", config=config, transcriber=FakeTranscriber())

            self.assertTrue(bot.handle_telegram_text("123", "ok thnx"))

        self.assertEqual(bot.calls[-1][1]["text"], "Anytime.")
        self.assertEqual(brain.answer_calls, [])

    def test_telegram_multipart_encoder_includes_file_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "note.txt"
            path.write_text("hello", encoding="utf-8")

            body, content_type = encode_multipart_form_data({"chat_id": "123"}, {"document": path})

        self.assertIn("multipart/form-data", content_type)
        self.assertIn(b'name="chat_id"', body)
        self.assertIn(b'filename="note.txt"', body)
        self.assertIn(b"hello", body)

    def test_terminal_runs_command(self) -> None:
        result = TerminalTool().run("Write-Output 'terminal-ok'", timeout=10)

        self.assertIn("exit_code: 0", result)
        self.assertIn("cwd:", result)
        self.assertIn("shell: powershell", result)
        self.assertIn("duration_seconds:", result)
        self.assertIn("terminal-ok", result)

    def test_terminal_supports_cwd_env_stdin_cmd_and_output_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = TerminalTool().run(
                "set /p value= & call echo %value%-%TERMINAL_TEST_VALUE%",
                cwd=temp_dir,
                timeout=10,
                shell="cmd",
                stdin="hello\n",
                env={"TERMINAL_TEST_VALUE": "world"},
                max_output_chars=2000,
            )

        self.assertIn("exit_code: 0", result)
        self.assertIn("shell: cmd", result)
        self.assertIn("hello-world", result)

    def test_terminal_truncates_large_output(self) -> None:
        result = TerminalTool().run(
            "$text = 'x' * 1500; Write-Output $text",
            timeout=10,
            max_output_chars=1000,
        )

        self.assertIn("exit_code: 0", result)
        self.assertIn("output truncated to 1000 characters", result)

    def test_terminal_reports_timeout_with_partial_output(self) -> None:
        result = TerminalTool().run(
            "Write-Output 'before-timeout'; Start-Sleep -Seconds 2",
            timeout=1,
        )

        self.assertIn("FAILED: command timed out after 1s", result)
        self.assertIn("exit_code: timeout", result)
        self.assertIn("before-timeout", result)

    def test_system_control_generates_commands(self) -> None:
        tool = SystemControlTool()

        brightness_command = tool.command_for("set_brightness", value=42)
        self.assertIn("$target = 42", brightness_command)
        self.assertIn("WmiSetBrightness", brightness_command)
        self.assertIn("Brightness set to 42%", brightness_command)
        self.assertIn("Brightness:", tool.command_for("get_brightness"))
        self.assertIn("+ 7", tool.command_for("brightness_up", amount=7))
        self.assertIn("ms-settings:bluetooth", tool.command_for("open_bluetooth"))
        self.assertIn("SetVolume(25)", tool.command_for("set_volume", value=25))
        self.assertIn("GetVolume", tool.command_for("get_volume"))
        self.assertIn("+ 5", tool.command_for("volume_up", amount=5))
        self.assertIn("SetMute($true)", tool.command_for("mute"))
        self.assertIn("System status:", tool.command_for("status"))
        self.assertIn("URL opened", tool.command_for("open_url", target="https://example.com"))
        self.assertIn("Path opened", tool.command_for("open_path", target="."))
        self.assertIn("Path revealed", tool.command_for("reveal_path", target="."))
        open_app_command = tool.command_for("open_app", target="notepad")
        self.assertIn("VERIFIED: app opened", open_app_command)
        self.assertIn("Get-Command $query", open_app_command)
        self.assertIn("Test-AppMatch", open_app_command)
        self.assertIn("Split-AppWords", open_app_command)
        self.assertIn("$looksLikePathOrExe", open_app_command)
        self.assertNotIn("$query.Substring", open_app_command)
        self.assertNotIn("Get-Command \"$query*\"", open_app_command)
        self.assertNotIn("[regex]", open_app_command.lower())
        self.assertIn("Get-StartApps", open_app_command)
        self.assertIn("*.lnk", open_app_command)
        self.assertIn("App Paths", open_app_command)
        self.assertIn("FALLBACK_COMMAND", open_app_command)
        self.assertIn("Get-StartApps", tool._app_discovery_command("notepad"))
        self.assertIn("App Paths", tool._app_discovery_command("notepad"))
        registry = ToolRegistry()
        system_spec = {spec.name: spec for spec in registry.specs()}["system_control"]
        self.assertIn("absolute URLs/URIs", system_spec.args["open_url"])
        self.assertIn("application names", system_spec.args["open_app"])

    def test_registry_system_fallback_uses_terminal(self) -> None:
        class BadSystem:
            def run(self, action, value=None, target=None):
                return "FAILED: nope\nFALLBACK_COMMAND: Write-Output 'fallback-ok'"

        registry = ToolRegistry()
        registry.system_control = BadSystem()

        result = registry.run("system_control", {"action": "set_brightness", "value": 1})

        self.assertIn("Terminal fallback result", result)
        self.assertIn("fallback-ok", result)

    def test_registry_repairs_non_uri_open_url_as_app_launch(self) -> None:
        class FakeSystem:
            def __init__(self) -> None:
                self.calls = []

            def run(self, action, value=None, target=None, amount=None, timeout=None):
                self.calls.append((action, target))
                return "VERIFIED: app opened"

        registry = ToolRegistry()
        fake_system = FakeSystem()
        registry.system_control = fake_system

        result = registry.run("system_control", {"action": "open_url", "target": "tool-name.exe"})

        self.assertEqual(result, "VERIFIED: app opened")
        self.assertEqual(fake_system.calls, [("open_app", "tool-name.exe")])
        self.assertTrue(ToolRegistry._is_absolute_uri("https://example.com"))
        self.assertTrue(ToolRegistry._is_absolute_uri("ms-settings:display"))
        self.assertFalse(ToolRegistry._is_absolute_uri("tool-name.exe"))
        self.assertFalse(ToolRegistry._is_absolute_uri("C:\\Windows\\notepad.exe"))

    def test_daemon_report_builder_includes_project_state(self) -> None:
        report = build_report(
            {
                "project": {
                    "name": "test-project",
                    "directories": ["core", "tool", "skills", "daemon", "tests"],
                    "python_files": ["core/brain.py", "core/llm_service.py", "core/memory.py", "daemon/project_daemon.py", "daemon/report.py", "tool/registry.py", "tests/test_core.py"],
                    "skill_files": ["skills/daemon-project-monitor.md"],
                },
                "branch": "master",
                "changed_files": ["core/brain.py"],
                "status": "M core/brain.py",
                "diff_stat": "core/brain.py | 10 +++++",
                "recent_commits": "abc123 test",
                "file_context": {"core/brain.py": "class Brain: pass"},
                "validation": "Ran 45 tests in 2.5s\n\nOK",
            },
            [{"timestamp": "now", "summary": "Project changed with 1 changed file."}],
            {
                "project_analysis": "Project Identity\n\nTest project analysis.\nThis may have introduced new bugs.",
                "status_review": "Verified Status\n\nTest status.\n```python\nclass Leaked: pass\n```\ndef leaked(): pass",
                "next_actions": "Immediate Next Step\n\nTest next step.\nRun the existing test command to ensure that all tests pass.",
            },
        )

        self.assertIn("# Daemon Project Report", report)
        self.assertIn("## Project Overview", report)
        self.assertIn("local personal AI assistant", report)
        self.assertIn("Brain and message flow", report)
        self.assertIn("## Verified Status", report)
        self.assertIn("Unit tests:", report)
        self.assertIn("no speculative missing-test", report)
        self.assertIn("## Next Actions", report)
        self.assertIn("Stage only the intended files by path", report)
        self.assertNotIn("may have introduced", report)
        self.assertNotIn("Run the existing test command", report)
        self.assertIn("## Evidence Sources", report)
        self.assertIn("core/brain.py", report)
        self.assertNotIn("class Brain", report)
        self.assertNotIn("class Leaked", report)
        self.assertNotIn("def leaked", report)
        self.assertNotIn("```", report)
        self.assertIn("Project changed", report)

    def test_project_daemon_writes_report_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = DaemonConfig(
                project_root=root,
                state_dir=root / "daemon" / "state",
                interval_seconds=60,
                report_path=root / "memory" / "data" / "daemon-report.md",
                run_tests=False,
                default_model="model",
                review_model="model",
                code_review_model="model",
                writing_model="model",
                summary_model="model",
            )
            daemon = ProjectDaemon(config, FakeDaemonTools(), FakeDaemonAnalyzer())

            event = daemon.run_once()

            self.assertTrue(event["changed"])
            self.assertTrue(config.report_path.exists())
            self.assertTrue(daemon.events_path.exists())
            self.assertIn("core/brain.py", config.report_path.read_text(encoding="utf-8"))

    def test_project_daemon_report_is_visible_to_memory_before_async_embedding_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = DaemonConfig(
                project_root=root,
                state_dir=root / "daemon" / "state",
                interval_seconds=60,
                report_path=root / "memory" / "data" / "daemon-report.md",
                run_tests=False,
                default_model="model",
                review_model="model",
                code_review_model="model",
                writing_model="model",
                summary_model="model",
            )
            daemon = ProjectDaemon(config, FakeDaemonTools(), FakeDaemonAnalyzer())
            daemon.run_once()
            memory = PermanentMemory(root / "memory", SlowEmbedding())

            with patch.dict(
                os.environ,
                {
                    "MEMORY_WRITE_ASYNC": "true",
                    "MEMORY_LOW_LATENCY": "true",
                    "MEMORY_SEARCH_MODE": "fast",
                },
                clear=False,
            ):
                start = time.perf_counter()
                context = memory.context_for("daemon project status changed files core brain", top_k=4)
                elapsed = time.perf_counter() - start
                index_thread = memory._index_thread
                if index_thread is not None:
                    index_thread.join(timeout=5)

            self.assertLess(elapsed, 0.25)
            self.assertIn("Daemon Project Report", context)
            self.assertIn("core/brain.py", context)

    def test_daemon_tools_extracts_stdout(self) -> None:
        output = "exit_code: 0\nstdout:\nhello\nstderr:\n<empty>"

        self.assertEqual(DaemonTools._stdout(output), "hello")

    def test_daemon_project_overview_uses_posix_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "core").mkdir()
            (root / "core" / "brain.py").write_text("", encoding="utf-8")
            (root / "skills").mkdir()
            (root / "skills" / "example.md").write_text("", encoding="utf-8")

            overview = DaemonTools(root).project_overview()

            self.assertIn("core/brain.py", overview["python_files"])
            self.assertIn("skills/example.md", overview["skill_files"])

    def test_daemon_project_overview_reports_env_and_persona(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text("SECRET=value", encoding="utf-8")
            (root / "persona.md").write_text("Name: JARVIS", encoding="utf-8")

            overview = DaemonTools(root).project_overview()

            self.assertTrue(overview["env_file_present"])
            self.assertEqual(overview["persona_excerpt"], "Name: JARVIS")

    def test_daemon_test_inventory_lists_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "tests").mkdir()
            (root / "tests" / "test_core.py").write_text("def test_example():\n    pass\n", encoding="utf-8")

            inventory = DaemonTools(root).test_inventory()

            self.assertIn("tests/test_core.py::test_example", inventory)

    def test_daemon_file_context_reads_generic_project_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "core").mkdir()
            (root / "core" / "brain.py").write_text("class Brain: pass", encoding="utf-8")
            (root / "skills").mkdir()
            (root / "skills" / "example.md").write_text("# Skill", encoding="utf-8")

            context = DaemonTools(root).file_context()

            self.assertIn("core/brain.py", context)
            self.assertIn("class Brain", context["core/brain.py"])

    def test_daemon_next_actions_prompt_avoids_blind_stage_all(self) -> None:
        self.assertIn("Do not invent file contents, risks, missing tests", STATUS_REVIEW_PROMPT)
        self.assertIn("If validation output shows tests passed, clearly say tests passed", STATUS_REVIEW_PROMPT)
        self.assertIn("Do not recommend `git add .`", NEXT_ACTIONS_PROMPT)
        self.assertIn("Do not mention non-existent scripts", NEXT_ACTIONS_PROMPT)
        self.assertIn("Do not include code snippets", NEXT_ACTIONS_PROMPT)
        self.assertIn("untracked file", NEXT_ACTIONS_PROMPT)

    def test_nvidia_stt_config_defaults_to_cli_listening(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text("", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                config = NvidiaSTTConfig.from_env(Path(temp_dir))

            self.assertEqual(config.provider, "nvidia")
            self.assertEqual(config.server, "grpc.nvcf.nvidia.com:443")
            self.assertEqual(config.function_id, "d8dd4e9b-fbf5-4fb0-9dba-8cf436c8d965")
            self.assertEqual(config.language_code, "en-US")
            self.assertEqual(config.language_codes, ("en-US",))
            self.assertEqual(config.web_language_codes, ("en-US",))
            self.assertTrue(config.web_fallback)
            self.assertEqual(config.model, "")
            self.assertTrue(config.use_ssl)
            self.assertTrue(config.automatic_punctuation)
            self.assertEqual(config.file_streaming_chunk, 1600)
            self.assertEqual(config.sample_rate, 16000)
            self.assertEqual(config.input_device, "")
            self.assertEqual(config.listen_timeout_seconds, 5)
            self.assertEqual(config.phrase_time_limit_seconds, 20)
            self.assertEqual(config.adjust_for_ambient_noise_seconds, 0.6)
            self.assertEqual(config.energy_threshold, 120)
            self.assertTrue(config.dynamic_energy_threshold)
            self.assertEqual(config.input_gain, 1.0)
            self.assertEqual(config.pause_threshold, 0.8)
            self.assertEqual(config.non_speaking_duration, 0.5)

    def test_nvidia_stt_config_uses_stt_env_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text(
                "\n".join(
                    [
                        "STT_PROVIDER=nvidia",
                        "NVIDIA_API_KEY=test-key",
                        "STT_NVIDIA_SERVER=server.example:443",
                        "STT_NVIDIA_FUNCTION_ID=test-function",
                        "STT_NVIDIA_LANGUAGE_CODE=en-US",
                        "STT_NVIDIA_MODEL=canary",
                        "STT_NVIDIA_USE_SSL=false",
                        "STT_NVIDIA_AUTOMATIC_PUNCTUATION=false",
                        "STT_NVIDIA_FILE_STREAMING_CHUNK=3200",
                        "STT_SAMPLE_RATE=22050",
                        "STT_INPUT_DEVICE=Blue Yeti",
                        "STT_LISTEN_TIMEOUT_SECONDS=3",
                        "STT_PHRASE_TIME_LIMIT_SECONDS=12",
                        "STT_ADJUST_FOR_AMBIENT_NOISE_SECONDS=0.2",
                        "STT_ENERGY_THRESHOLD=180",
                        "STT_DYNAMIC_ENERGY_THRESHOLD=false",
                        "STT_INPUT_GAIN=1.75",
                        "STT_PAUSE_THRESHOLD=1.1",
                        "STT_NON_SPEAKING_DURATION=0.3",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = NvidiaSTTConfig.from_env(Path(temp_dir))

            self.assertEqual(config.provider, "nvidia")
            self.assertEqual(config.api_key, "test-key")
            self.assertEqual(config.server, "server.example:443")
            self.assertEqual(config.function_id, "test-function")
            self.assertEqual(config.language_code, "en-US")
            self.assertEqual(config.language_codes, ("en-US",))
            self.assertEqual(config.web_language_codes, ("en-US",))
            self.assertEqual(config.model, "canary")
            self.assertFalse(config.use_ssl)
            self.assertFalse(config.automatic_punctuation)
            self.assertEqual(config.file_streaming_chunk, 3200)
            self.assertEqual(config.sample_rate, 22050)
            self.assertEqual(config.input_device, "Blue Yeti")
            self.assertEqual(config.listen_timeout_seconds, 3)
            self.assertEqual(config.phrase_time_limit_seconds, 12)
            self.assertEqual(config.adjust_for_ambient_noise_seconds, 0.2)
            self.assertEqual(config.energy_threshold, 180)
            self.assertFalse(config.dynamic_energy_threshold)
            self.assertEqual(config.input_gain, 1.75)
            self.assertEqual(config.pause_threshold, 1.1)
            self.assertEqual(config.non_speaking_duration, 0.3)
            self.assertEqual(
                _nvidia_metadata(config),
                [["function-id", "test-function"], ["authorization", "Bearer test-key"]],
            )

    def test_nvidia_stt_config_accepts_legacy_microphone_tuning_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text(
                "\n".join(
                    [
                        "NVIDIA_API_KEY=test-key",
                        "STT_START_TIMEOUT_SECONDS=8",
                        "STT_LISTEN_MAX_SECONDS=0",
                        "STT_CALIBRATION_SECONDS=0",
                        "STT_MIN_ENERGY=50",
                        "STT_SILENCE_SECONDS=0.55",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = NvidiaSTTConfig.from_env(Path(temp_dir))

            self.assertEqual(config.listen_timeout_seconds, 8)
            self.assertEqual(config.phrase_time_limit_seconds, 20)
            self.assertEqual(config.adjust_for_ambient_noise_seconds, 0)
            self.assertEqual(config.energy_threshold, 50)
            self.assertEqual(config.pause_threshold, 0.55)

    def test_speech_input_gain_boosts_pcm_audio(self) -> None:
        boosted = _gain_pcm16(b"\x00\x00\x10\x00\xf0\xff\xff\x7f\x00\x80", 2.0)

        self.assertEqual(boosted, b"\x00\x00 \x00\xe0\xff\xff\x7f\x00\x80")

    def test_nvidia_stt_config_maps_language_hint_without_explicit_nvidia_language(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text(
                "\n".join(
                    [
                        "NVIDIA_API_KEY=test-key",
                        "STT_LANGUAGE=en",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = NvidiaSTTConfig.from_env(Path(temp_dir))

            self.assertEqual(config.language_code, "en-US")
            self.assertEqual(config.language_codes, ("en-US",))
            self.assertEqual(config.web_language_codes, ("en-US",))

    def test_nvidia_stt_config_accepts_multiple_language_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text(
                "\n".join(
                    [
                        "NVIDIA_API_KEY=test-key",
                        "STT_NVIDIA_LANGUAGE_CODES=en-US,en-GB",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = NvidiaSTTConfig.from_env(Path(temp_dir))

            self.assertEqual(config.language_code, "en-US")
            self.assertEqual(config.language_codes, ("en-US", "en-GB"))
            self.assertEqual(config.web_language_codes, ("en-US", "en-GB"))

    def test_stt_config_supports_web_provider_for_english_voice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text(
                "\n".join(
                    [
                        "STT_PROVIDER=web",
                        "STT_WEB_LANGUAGE_CODES=en-US",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = NvidiaSTTConfig.from_env(Path(temp_dir))

            self.assertEqual(config.provider, "web")
            self.assertEqual(config.web_language_codes, ("en-US",))
            self.assertIsInstance(create_speech_to_text(config), SpeechRecognitionWebSpeechToText)

    def test_microphone_device_index_accepts_number_or_name(self) -> None:
        names = ["Built-in Microphone", "NVIDIA Broadcast", "USB Mic"]

        self.assertIsNone(_microphone_device_index("", names))
        self.assertEqual(_microphone_device_index("2", names), 2)
        self.assertEqual(_microphone_device_index("broadcast", names), 1)
        self.assertEqual(_microphone_device_index("usb", [(4, "USB Mic")]), 4)

    def test_nvidia_streaming_text_prefers_final_results(self) -> None:
        responses = [
            FakeRivaResponse(FakeRivaResult("partial text", is_final=False)),
            FakeRivaResponse(FakeRivaResult("final one", is_final=True)),
            FakeRivaResponse(FakeRivaResult("final two", is_final=True)),
        ]

        result = _extract_nvidia_streaming_text(responses)

        self.assertEqual(result, "final one final two")

    def test_nvidia_streaming_text_uses_partial_fallback(self) -> None:
        responses = [
            FakeRivaResponse(FakeRivaResult("first partial", is_final=False)),
            FakeRivaResponse(FakeRivaResult("last partial", is_final=False)),
        ]

        result = _extract_nvidia_streaming_text(responses)

        self.assertEqual(result, "last partial")

    def test_tts_config_defaults_to_nvidia_voice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text("", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                config = TTSConfig.from_env(Path(temp_dir))

            self.assertTrue(config.enabled)
            self.assertEqual(config.provider, "nvidia")
            self.assertEqual(config.voice, "Magpie-Multilingual.EN-US.Ray.Neutral")
            self.assertEqual(config.rate, "+24%")
            self.assertEqual(config.volume, "+80%")
            self.assertEqual(config.pitch, "-8Hz")
            self.assertEqual(config.nvidia_tts_server, "grpc.nvcf.nvidia.com:443")
            self.assertEqual(config.nvidia_tts_function_id, "877104f7-e885-42b9-8de8-f6e4c6303969")
            self.assertEqual(config.nvidia_tts_language_code, "en-US")
            self.assertTrue(config.nvidia_tts_use_ssl)
            self.assertEqual(config.nvidia_tts_sample_rate, 44100)
            self.assertTrue(config.nvidia_tts_streaming)
            self.assertFalse(config.nvidia_tts_ssml)
            self.assertEqual(config.voice_effect, "heavy")
            self.assertEqual(config.heavy_pitch_factor, 1.05)
            self.assertEqual(config.heavy_darkness, 0.62)

    def test_tts_config_can_be_muted_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text(
                "TTS_ENABLED=false\nTTS_VOICE=Magpie-Multilingual.EN-US.Aria\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = TTSConfig.from_env(Path(temp_dir))

            self.assertFalse(config.enabled)
            self.assertEqual(config.voice, "Magpie-Multilingual.EN-US.Aria")

    def test_nvidia_tts_text_wraps_ssml_prosody(self) -> None:
        config = _test_tts_config(nvidia_tts_ssml=True)

        result = _nvidia_tts_text("Use <NVIDIA> & speak.", config)

        self.assertIn('<prosody rate="+24%" volume="+80%" pitch="-8Hz">', result)
        self.assertIn("Use &lt;NVIDIA&gt; &amp; speak.", result)

    def test_nvidia_tts_text_defaults_to_plain_text_for_magpie(self) -> None:
        config = _test_tts_config()

        result = _nvidia_tts_text("Plain NVIDIA speech.", config)

        self.assertEqual(result, "Plain NVIDIA speech.")

    def test_voice_effect_settings_can_disable_heavy_processing(self) -> None:
        heavy = _test_tts_config()
        normal = _test_tts_config(voice_effect="none")

        self.assertEqual(_voice_effect_settings(heavy), (1.05, 0.62))
        self.assertEqual(_voice_effect_settings(normal), (1.0, 0.0))

    def test_voice_effect_sample_rate_slightly_increases_default_speed(self) -> None:
        self.assertEqual(_effect_sample_rate(44100, 1.05), 46305)

    def test_voice_effect_processing_changes_audio(self) -> None:
        audio = b"\x00\x00\x10\x00\x20\x00\x30\x00\x40\x00"

        result = _process_pcm16(audio, volume=1.2, darkness=0.62)

        self.assertEqual(len(result), len(audio))
        self.assertNotEqual(result, audio)

    def test_text_for_speech_removes_markdown(self) -> None:
        text = "Here is `code`.\n```python\nprint('skip')\n```\n[Open docs](https://example.com) now."

        result = text_for_speech(text, max_chars=1200)

        self.assertNotIn("https://", result)
        self.assertNotIn("print", result)
        self.assertIn("code", result)

    def test_text_for_speech_keeps_long_replies(self) -> None:
        text = " ".join(f"word{i}" for i in range(90))

        result = text_for_speech(text, max_chars=1200)

        self.assertIn("word0", result)
        self.assertIn("word40", result)
        self.assertIn("word89", result)


if __name__ == "__main__":
    unittest.main()
