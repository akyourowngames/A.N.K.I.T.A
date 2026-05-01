from __future__ import annotations

import json
import os
import tempfile
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
from core.speech import SpeechConfig, convert_to_english
from daemon.config import DaemonConfig
from daemon.analyzer import NEXT_ACTIONS_PROMPT, STATUS_REVIEW_PROMPT
from daemon.project_daemon import ProjectDaemon
from daemon.report import build_report
from daemon.tools import DaemonTools
from tool.date_time import DateTimeTool
from tool.gmail import GmailTool
from tool.google_calendar import GoogleCalendarTool
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

    def test_brain_can_pass_tool_observation_to_final_answer(self) -> None:
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
            final_user_message = llm.stream_messages[-1]["content"]

            self.assertEqual(reply, "It is time.")
            self.assertIn("UTC", final_user_message)

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

    def test_failed_tool_returns_direct_failure_without_final_llm(self) -> None:
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

            brain = Brain(paths, CalendarFollowupFakeLLM(), "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            reply = "".join(brain.answer_stream("brief me on my schedule"))

            self.assertIn("couldn't complete", reply)
            self.assertIn("Google OAuth client secret file is missing", reply)

    def test_unsupported_tool_plan_returns_direct_reply_without_final_llm(self) -> None:
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
                reply="This should not be used.",
            )
            brain = Brain(paths, llm, "Sam", "Nova", paths.memory_chats / "session.jsonl", FakeTools(), FakeMemory())

            reply = "".join(brain.answer_stream("generate an image of a car"))

            self.assertIn("can't do that from here", reply)
            self.assertIn("image generation is not connected", reply)
            self.assertEqual(llm.stream_messages, [])

    def test_tool_decision_parser_handles_json(self) -> None:
        parsed = Brain._parse_tool_decision('```json\n{"tool":"date_time","args":{"timezone":"UTC"}}\n```')

        self.assertEqual(parsed["tool"], "date_time")
        self.assertEqual(parsed["args"], {"timezone": "UTC"})

    def test_tool_decision_parser_accepts_new_tools(self) -> None:
        for tool_name in ("weather", "system_control", "terminal", "gmail", "google_calendar"):
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
        self.assertIn("email", specs["gmail"].description.lower())
        self.assertIn("calendar", specs["google_calendar"].description.lower())

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

    def test_speech_config_defaults_to_local_transcription(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text("", encoding="utf-8")

            config = SpeechConfig.from_env(Path(temp_dir))

            self.assertEqual(config.provider, "local")
            self.assertEqual(config.local_model, "small")
            self.assertEqual(config.local_compute_type, "int8")
            self.assertEqual(config.english_conversion, "auto")
            self.assertEqual(config.sample_rate, 16000)

    def test_convert_to_english_preserves_user_intent(self) -> None:
        llm = TranslationFakeLLM()

        result = convert_to_english("YouTube kholo aur music chalao.", llm)

        self.assertEqual(result, "Open YouTube and play music.")
        self.assertIn("Return only the converted user message", llm.messages[0]["content"])
        self.assertEqual(llm.messages[1]["content"], "YouTube kholo aur music chalao.")

    def test_local_speech_auto_falls_back_to_transcript_conversion(self) -> None:
        from core.speech import speech_to_english

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / ".env").write_text("", encoding="utf-8")
            config = SpeechConfig.from_env(Path(temp_dir))
            llm = TranslationFakeLLM()

            result = speech_to_english(Path(temp_dir) / "empty.wav", EmptyTranslateSpeech(), llm, config)

            self.assertEqual(result, "Open YouTube and play music.")


if __name__ == "__main__":
    unittest.main()
