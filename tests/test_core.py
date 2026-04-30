from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.brain import Brain
from core.logic import ProjectPaths, append_chat_turn, read_markdown_skills, read_memory, sanitize_skill_text, session_file
from core.memory import EmbeddingModel, PermanentMemory, extract_durable_memories, normalize_memory_text, parse_key_value_line
from tool.date_time import DateTimeTool
from tool.registry import ToolRegistry
from tool.tavily_search import TavilySearchTool


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


class CountingEmbedding:
    cache_key = "counting:test"

    def __init__(self) -> None:
        self.query_calls = 0

    def embed_document(self, text):
        return [1.0, 0.0]

    def embed_query(self, text):
        self.query_calls += 1
        return [1.0, 0.0]


class CoreTests(unittest.TestCase):
    def test_reads_markdown_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skills = Path(temp_dir)
            (skills / "search.md").write_text("Use search carefully.", encoding="utf-8")

            result = read_markdown_skills(skills)

            self.assertIn("search.md", result)
            self.assertIn("Use search carefully.", result)

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

    def test_brain_builds_prompt_and_logs_chat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ProjectPaths.from_root(root)
            for folder in (paths.core, paths.skills, paths.memory, paths.memory_chats, paths.memory_data, paths.memory_store, paths.chat):
                folder.mkdir()

            (paths.skills / "notes.md").write_text("Always be helpful.", encoding="utf-8")
            (paths.memory_data / "profile.txt").write_text("User name is Sam.", encoding="utf-8")

            fake_llm = FakeLLM()
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
            system_prompt = fake_llm.messages[0]["content"]
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

    def test_tool_decision_parser_handles_json(self) -> None:
        parsed = Brain._parse_tool_decision('```json\n{"tool":"date_time","args":{"timezone":"UTC"}}\n```')

        self.assertEqual(parsed["tool"], "date_time")
        self.assertEqual(parsed["args"], {"timezone": "UTC"})

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


if __name__ == "__main__":
    unittest.main()
