from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_brain import graph_export, memory_brain_reindex, search_memory_brain
from memory_graph import connected_edges, list_entities
from memory_ingest import build_memory_graph
from memory_retrieval import entity_neighbors
from memory_system import MemoryConfig, clean_memory_candidates, load_memory_context
from tools import discover_tools


def make_memory_config(root: Path) -> MemoryConfig:
    return MemoryConfig(
        root=root / "memory",
        max_context_chars=1600,
        max_file_chars=900,
        include_transcripts=False,
        extract_enabled=False,
        extract_background=False,
        extract_max_tokens=100,
        context_prompt_file=Path.cwd() / "prompts" / "memory_context.txt",
    )


def seed_memory(root: Path) -> MemoryConfig:
    config = make_memory_config(root)
    config.root.mkdir(parents=True, exist_ok=True)
    (config.root / "user.txt").write_text(
        "\n".join(
            [
                "User Memory",
                "",
                "Preferences:",
                "- Krish prefers Ankita responses to feel instant with low latency.",
                "- Browser Controller Agent should keep extraction-first verification.",
                "- Krish prefers dark UI for Ankita.",
                "- Krish does not prefer dark UI for Ankita.",
                "",
                "Projects:",
                "- A.N.K.I.T.A uses a Browser Controller Agent.",
            ]
        ),
        encoding="utf-8",
    )
    (config.root / "extracted.txt").write_text(
        "\n".join(
            [
                "Extracted Chat Memory",
                "",
                "[2026-05-15T10:00:00+05:30]",
                "",
                "- [project] Browser Controller Agent uses Playwright CDP. | Entities: Browser Controller Agent, Playwright CDP | Relations: Browser Controller Agent -> uses -> Playwright CDP",
                "- [decision] TXT memory remains the source of truth while graph memory is generated.",
            ]
        ),
        encoding="utf-8",
    )
    project_page = config.root / "wiki" / "pages" / "projects"
    project_page.mkdir(parents=True, exist_ok=True)
    (project_page / "ankita.txt").write_text(
        "\n".join(
            [
                "Title: Ankita",
                "Updated: 2026-05-15T10:00:00+05:30",
                "Source: test",
                "Confidence: test",
                "",
                "- Ankita has a TXT-backed memory brain plan.",
            ]
        ),
        encoding="utf-8",
    )
    return config


class MemoryBrainTests(unittest.TestCase):
    def test_reindex_keeps_txt_sources_and_writes_generated_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = seed_memory(root)
            with brain_env(root):
                result = memory_brain_reindex(root, config)

            self.assertTrue((config.root / "user.txt").exists())
            self.assertTrue((config.root / "extracted.txt").exists())
            self.assertTrue((config.root / "graph" / "memory.db").exists())
            self.assertTrue((config.root / "graph" / "graph.json").exists())
            self.assertGreater(result["facts"], 0)
            self.assertGreater(result["entities"], 0)

    def test_reindex_scans_user_extracted_and_wiki_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = seed_memory(root)
            with brain_env(root):
                graph = build_memory_graph(config)

            self.assertIn("user.txt", graph["source_files"])
            self.assertIn("extracted.txt", graph["source_files"])
            self.assertIn("wiki/pages/projects/ankita.txt", graph["source_files"])

    def test_entities_are_deduplicated_and_relations_keep_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = seed_memory(root)
            with brain_env(root):
                memory_brain_reindex(root, config)
                entities = list_entities(config.root / "graph" / "memory.db")

            browser_entities = [entity for entity in entities if entity["canonical_name"] == "Browser Controller Agent"]
            self.assertEqual(len(browser_entities), 1)
            edges = connected_edges(config.root / "graph" / "memory.db", browser_entities[0]["id"])
            self.assertTrue(any(edge["relation_type"] == "uses" for edge in edges))
            self.assertTrue(any(edge["source_path"] == "extracted.txt" for edge in edges))

    def test_hybrid_search_finds_preference_and_graph_neighbors_expand_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = seed_memory(root)
            with brain_env(root):
                memory_brain_reindex(root, config)
                result = search_memory_brain("latency Ankita", root)
                entities = list_entities(config.root / "graph" / "memory.db")
                browser = next(entity for entity in entities if entity["canonical_name"] == "Browser Controller Agent")
                neighbors = entity_neighbors(config.root / "graph" / "memory.db", browser["id"], max_hops=2)

            fact_text = "\n".join(item["fact"]["text"] for item in result["answer_relevant_facts"])
            self.assertIn("low latency", fact_text)
            self.assertTrue(neighbors["facts"])

    def test_contradiction_creates_supersedes_or_contradicts_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = seed_memory(root)
            with brain_env(root):
                memory_brain_reindex(root, config)
                exported = graph_export(root)

            relation_types = {edge["relation_type"] for edge in exported["edges"]}
            self.assertIn("contradicts", relation_types)
            self.assertIn("supersedes", relation_types)
            conflicts = json.loads((config.root / "graph" / "unresolved_conflicts.json").read_text(encoding="utf-8"))
            self.assertTrue(conflicts)

    def test_secret_candidates_are_not_saved(self) -> None:
        candidates = clean_memory_candidates(
            [
                {
                    "text": "NVIDIA_API_KEY=abc123secret456",
                    "type": "fact",
                    "importance": 1,
                    "confidence": 1,
                    "should_save": True,
                }
            ]
        )

        self.assertEqual(candidates, [])

    def test_memory_context_is_compact_and_dynamic_can_be_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = seed_memory(root)
            with brain_env(root):
                memory_brain_reindex(root, config)
                dynamic_context = load_memory_context(config, user_text="latency Ankita")
                skipped_context = load_memory_context(config, user_text="hello", include_dynamic=False)

            self.assertIn("Relevant memory", dynamic_context)
            self.assertLess(len(dynamic_context), 1800)
            self.assertNotIn("Relevant memory", skipped_context)
            self.assertIn("Stable profile memory", skipped_context)

    def test_reindex_uses_sqlite_without_external_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = seed_memory(root)
            with brain_env(root):
                memory_brain_reindex(root, config)

            self.assertTrue((config.root / "graph" / "memory.db").is_file())

    def test_forget_request_tool_requires_confirmation(self) -> None:
        registry = discover_tools()
        tool = registry.tool("memory_forget_request")

        self.assertIsNotNone(tool)
        self.assertEqual(tool.risk, "write")
        self.assertTrue(tool.requires_confirmation)


def brain_env(root: Path):
    return patch.dict(
        "os.environ",
        {
            "JARVIS_MEMORY_DIR": str(root / "memory"),
            "MEMORY_BRAIN_ENABLED": "true",
            "MEMORY_BRAIN_AUTO_REINDEX": "false",
            "MEMORY_BRAIN_INCLUDE_TRANSCRIPTS": "false",
            "USER_NAME": "Krish",
        },
        clear=False,
    )


if __name__ == "__main__":
    unittest.main()
