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
    extract_durable_memories,
    normalize_memory_text,
    parse_key_value_line,
)
from core.pc_monitor import PcMonitor, PcMonitorConfig, format_activity_record
from core.speech import (
    SpeechConfig,
    SpeechRecognitionSpeechToText,
    TTSConfig,
    _effect_sample_rate,
    _extract_nvidia_streaming_text,
    _nvidia_metadata,
    _nvidia_tts_text,
    _process_pcm16,
    _voice_effect_settings,
    convert_to_english,
    create_speech_to_text,
    text_for_speech,
)
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
from tool.tavily_search import TavilySearchTool
from tool.terminal import TerminalTool
from tool.weather import WeatherTool
from telegram_bot import split_message


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


class CalendarFollowupFakeLLM:
    def __init__(self) -> None:
        self.messages = []

    def chat(self, messages, **kwargs):
        self.messages = messages
        return '{"tool":"google_calendar","args":{"action":"list","calendar_id":"primary","max_results":10}}'


class TranslationFakeLLM:
    def __init__(self) -> None:
        self.messages = []

    def chat(self, messages):
        self.messages = messages
        return "Open YouTube and play music."


class EmptyTranslateSpeech:
    def transcribe(self, audio_path):
        return "YouTube kholo aur music chalao."

    def translate_audio_to_english(self, audio_path):
        return ""


class FakeWhisperSegment:
    text = "hello"


class FakeWhisperModel:
    def __init__(self) -> None:
        self.calls = []

    def transcribe(self, audio_path, **kwargs):
        self.calls.append((audio_path, kwargs))
        return [FakeWhisperSegment()], None


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
        "heavy_pitch_factor": 1.06,
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

    def test_activity_record_format_handles_errors(self) -> None:
        result = format_activity_record({"timestamp": "now", "error": "blocked"})

        self.assertIn("monitor error", result)

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
            self.assertIn("Do not claim calendar", messages[0]["content"])

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
                    return "Allowed local folders:\n- C:\\Users\\anime\\Desktop"

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
            self.assertIn("Allowed local folders:", llm.stream_messages[-1]["content"])

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

    def test_extracts_durable_memory(self) -> None:
        memories = list(extract_durable_memories("remember that I prefer short answers"))

        self.assertEqual(memories, ["Preference: short answers"])

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

    def test_permanent_memory_remembers_user_statement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )

            saved = memory.remember_from_user_text("remember that I am building a personal AI assistant")
            context = memory.context_for("personal assistant", top_k=3)

            self.assertEqual(saved, 1)
            self.assertIn("personal AI assistant", context)

    def test_memory_context_hides_sources_and_scores(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = PermanentMemory(
                Path(temp_dir),
                EmbeddingModel(model_name="missing-local-model", use_sentence_transformers=False),
            )
            (memory.data_dir / "profile.txt").write_text("Name: Krish", encoding="utf-8")
            memory.remember_from_user_text("i like pizza in food")

            context = memory.context_for("favorite food", top_k=3)

            self.assertIn("Name: Krish", context)
            self.assertIn("Favorite food: pizza", context)
            self.assertNotIn("score=", context)
            self.assertNotIn("profile.txt", context)

    def test_normalizes_memory_text(self) -> None:
        self.assertEqual(normalize_memory_text("i like pizza in food"), "Favorite food: pizza")
        self.assertEqual(normalize_memory_text("i am good"), "")

    def test_date_time_tool_returns_timezone_text(self) -> None:
        result = DateTimeTool().run("UTC")

        self.assertIn("UTC", result)
        self.assertIn("Time of day:", result)
        self.assertIn("Morning now:", result)

    def test_tavily_formats_results(self) -> None:
        body = {
            "answer": "Short answer.",
            "results": [
                {"title": "Example", "url": "https://example.com", "content": "Example summary."}
            ],
        }

        result = TavilySearchTool._format_results(body)

        self.assertIn("Short answer.", result)
        self.assertIn("https://example.com", result)

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
        self.assertIn("31°C", result)
        self.assertIn("Clear", result)

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
        self.assertIn("allowed", specs["local_files"].description.lower())
        self.assertIn("yt-dlp", specs["music"].description.lower())
        self.assertIn("nvidia", specs["image_generation"].description.lower())

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

    def test_local_files_tool_respects_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as allowed_dir, tempfile.TemporaryDirectory() as blocked_dir:
            allowed = Path(allowed_dir)
            blocked = Path(blocked_dir)
            (allowed / "notes.txt").write_text("Allowed note.", encoding="utf-8")
            (blocked / "secret.txt").write_text("Blocked note.", encoding="utf-8")

            with patch.dict(os.environ, {"LOCAL_FILE_ALLOWED_PATHS": str(allowed)}, clear=False):
                tool = LocalFilesTool()
                allowed_result = tool.run("read", path=str(allowed / "notes.txt"))
                blocked_result = tool.run("read", path=str(blocked / "secret.txt"))

            self.assertIn("Allowed note.", allowed_result)
            self.assertIn("FAILED:", blocked_result)
            self.assertIn("outside allowed local folders", blocked_result)

    def test_local_files_tool_resolves_known_folder_aliases(self) -> None:
        desktop = Path.home() / "Desktop"
        desktop.mkdir(exist_ok=True)

        with patch.dict(os.environ, {"LOCAL_FILE_ALLOWED_PATHS": str(desktop)}, clear=False):
            result = LocalFilesTool().run("list", path="Desktop", max_results=5)

        self.assertIn(f"Folder: {desktop}", result)

    def test_local_files_tool_treats_allowed_folders_phrase_as_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOCAL_FILE_ALLOWED_PATHS": temp_dir}, clear=False):
                result = LocalFilesTool().run("list", path="allowed local folders")

        self.assertIn("Allowed local folders:", result)
        self.assertIn(temp_dir, result)

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

    def test_terminal_runs_command(self) -> None:
        result = TerminalTool().run("Write-Output 'terminal-ok'", timeout=10)

        self.assertIn("exit_code: 0", result)
        self.assertIn("terminal-ok", result)

    def test_system_control_generates_commands(self) -> None:
        tool = SystemControlTool()

        self.assertIn("Brightness set to 42%", tool.command_for("set_brightness", value=42))
        self.assertIn("ms-settings:bluetooth", tool.command_for("open_bluetooth"))
        self.assertIn("SetVolume(25)", tool.command_for("set_volume", value=25))
        open_app_command = tool.command_for("open_app", target="notepad")
        self.assertIn("VERIFIED: app opened", open_app_command)
        self.assertIn("Get-Command $query", open_app_command)
        self.assertIn("Test-AppMatch", open_app_command)
        self.assertIn("$looksLikePathOrExe", open_app_command)
        self.assertNotIn("$query.Substring", open_app_command)
        self.assertNotIn("Get-Command \"$query*\"", open_app_command)
        self.assertIn("Get-StartApps", open_app_command)
        self.assertIn("*.lnk", open_app_command)
        self.assertIn("App Paths", open_app_command)
        self.assertIn("FALLBACK_COMMAND", open_app_command)
        self.assertIn("Get-StartApps", tool._app_discovery_command("notepad"))
        self.assertIn("App Paths", tool._app_discovery_command("notepad"))

    def test_registry_system_fallback_uses_terminal(self) -> None:
        class BadSystem:
            def run(self, action, value=None, target=None):
                return "FAILED: nope\nFALLBACK_COMMAND: Write-Output 'fallback-ok'"

        registry = ToolRegistry()
        registry.system_control = BadSystem()

        result = registry.run("system_control", {"action": "set_brightness", "value": 1})

        self.assertIn("Terminal fallback result", result)
        self.assertIn("fallback-ok", result)

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

    def test_speech_config_defaults_to_fast_speech_recognition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text("", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                config = SpeechConfig.from_env(Path(temp_dir))

            self.assertEqual(config.provider, "speech_recognition")
            self.assertEqual(config.speech_recognition_language, "en-IN")
            self.assertEqual(config.local_model, "small")
            self.assertEqual(config.local_compute_type, "int8")
            self.assertEqual(config.english_conversion, "off")
            self.assertEqual(config.language, "")
            self.assertEqual(config.sample_rate, 16000)
            self.assertEqual(config.start_timeout_seconds, 4)

    def test_create_speech_to_text_uses_speech_recognition_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text("STT_PROVIDER=simple\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                config = SpeechConfig.from_env(Path(temp_dir))

            self.assertIsInstance(create_speech_to_text(config), SpeechRecognitionSpeechToText)

    def test_speech_config_uses_language_hint_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text("STT_SPEECH_RECOGNITION_LANGUAGE=en-IN\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                config = SpeechConfig.from_env(Path(temp_dir))

            self.assertEqual(config.language, "en")
            self.assertEqual(config.speech_recognition_language, "en-IN")

    def test_speech_config_prefers_new_language_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text(
                "STT_LANGUAGE=hi-IN\nSTT_SPEECH_RECOGNITION_LANGUAGE=en-IN\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = SpeechConfig.from_env(Path(temp_dir))

            self.assertEqual(config.language, "hi")
            self.assertEqual(config.speech_recognition_language, "en-IN")

    def test_speech_config_supports_nvidia_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text(
                "\n".join(
                    [
                        "STT_PROVIDER=nvidia",
                        "NVIDIA_API_KEY=test-key",
                        "STT_LANGUAGE=en-IN",
                        "STT_NVIDIA_FUNCTION_ID=test-function",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = SpeechConfig.from_env(Path(temp_dir))

            self.assertEqual(config.provider, "nvidia")
            self.assertEqual(config.nvidia_asr_server, "grpc.nvcf.nvidia.com:443")
            self.assertEqual(config.nvidia_asr_language_code, "en-US")
            self.assertEqual(config.nvidia_asr_function_id, "test-function")
            self.assertTrue(config.nvidia_asr_use_ssl)
            self.assertEqual(
                _nvidia_metadata(config),
                [["function-id", "test-function"], ["authorization", "Bearer test-key"]],
            )

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
            self.assertEqual(config.heavy_pitch_factor, 1.06)
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

        self.assertEqual(_voice_effect_settings(heavy), (1.06, 0.62))
        self.assertEqual(_voice_effect_settings(normal), (1.0, 0.0))

    def test_voice_effect_sample_rate_slightly_increases_default_speed(self) -> None:
        self.assertEqual(_effect_sample_rate(44100, 1.06), 46746)

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

    def test_faster_whisper_receives_language_hint(self) -> None:
        from core.speech import FasterWhisperSpeechToText

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text("STT_LANGUAGE=en-IN\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                config = SpeechConfig.from_env(Path(temp_dir))
            model = FakeWhisperModel()
            speech = object.__new__(FasterWhisperSpeechToText)
            speech.config = config
            speech.model = model

            result = speech._transcribe_segments(Path(temp_dir) / "speech.wav", task="transcribe", vad_filter=True)

            self.assertEqual(result, "hello")
            self.assertEqual(model.calls[0][1]["language"], "en")

    def test_convert_to_english_preserves_user_intent(self) -> None:
        llm = TranslationFakeLLM()

        result = convert_to_english("YouTube kholo aur music chalao.", llm)

        self.assertEqual(result, "Open YouTube and play music.")
        self.assertIn("Return only the converted user message", llm.messages[0]["content"])
        self.assertEqual(llm.messages[1]["content"], "YouTube kholo aur music chalao.")

    def test_local_speech_auto_falls_back_to_transcript_conversion(self) -> None:
        from core.speech import speech_to_english

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text("STT_PROVIDER=local\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                config = SpeechConfig.from_env(Path(temp_dir))
            llm = TranslationFakeLLM()

            result = speech_to_english(Path(temp_dir) / "empty.wav", EmptyTranslateSpeech(), llm, config)

            self.assertEqual(result, "Open YouTube and play music.")

    def test_simple_speech_recognition_returns_raw_transcript_without_refining(self) -> None:
        from core.speech import speech_to_english

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text("STT_PROVIDER=speech_recognition\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                config = SpeechConfig.from_env(Path(temp_dir))
            llm = TranslationFakeLLM()

            result = speech_to_english(Path(temp_dir) / "empty.wav", EmptyTranslateSpeech(), llm, config)

            self.assertEqual(result, "YouTube kholo aur music chalao.")
            self.assertEqual(llm.messages, [])


if __name__ == "__main__":
    unittest.main()
