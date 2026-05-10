from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extension_system import load_extension_catalog
from skill_system import load_skill_context
from tools import discover_tools
from tools.document_agent import (
    document_annotate,
    document_close,
    document_compare,
    document_extract,
    document_merge,
    document_open,
    document_read,
    document_status,
    document_transform,
    document_write,
)
from tools.report_compiler import compiler_list_templates, compiler_preview, compiler_render, compiler_status, compiler_validate
from tools.research_agent import research_run


class ReportCompilerAndDocumentAgentTests(unittest.TestCase):
    def test_extensions_register_compiler_and_document_tools(self) -> None:
        registry = discover_tools()
        names = [tool.name for tool in registry.visible_tools()]
        self.assertIn("compiler_status", names)
        self.assertIn("compiler_render", names)
        self.assertIn("compiler_preview", names)
        self.assertIn("document_status", names)
        self.assertIn("document_open", names)
        self.assertIn("document_read", names)
        self.assertIn("document_extract", names)
        self.assertIn("document_write", names)

        catalog = load_extension_catalog()
        extension_ids = [extension.id for extension in catalog.extensions]
        self.assertIn("report-compiler", extension_ids)
        self.assertIn("document-agent", extension_ids)
        self.assertTrue(any(tool.get("name") == "compiler_render" for tool in catalog.tool_descriptors()))
        self.assertTrue(any(tool.get("name") == "document_open" for tool in catalog.tool_descriptors()))
        self.assertIn("Report Compiler Protocol", catalog.prompt_context())
        self.assertIn("Document Agent Protocol", catalog.prompt_context())
        with patch.dict(os.environ, {"JARVIS_SKILL_CONTEXT_CHARS": "30000"}, clear=False):
            context = load_skill_context(catalog, Path.cwd())
        self.assertIn("Skill: report-compiler", context)
        self.assertIn("Skill: document-operator", context)

    def test_report_compiler_validates_previews_and_renders_markdown(self) -> None:
        content = {
            "title": "Jarvis Compiler Test",
            "subtitle": "Unit proof",
            "metadata": {"author": "Jarvis", "date": "2026-05-10"},
            "sections": [
                {
                    "heading": "Summary",
                    "level": 1,
                    "body": "The compiler renders structured content.",
                    "items": ["Markdown is always available"],
                    "table": {"headers": ["Name", "Status"], "rows": [["Compiler", "ready"]]},
                    "citations": ["https://example.com"],
                }
            ],
            "bibliography": [
                {"index": 1, "title": "Example", "url": "https://example.com", "publisher": "example.com", "date": "2026-05-10"}
            ],
            "appendix": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "compiler.json"
            output_path = Path(tmp) / "compiler-test.md"
            config_path.write_text(
                json.dumps({"output_dir": str(Path(tmp) / "reports"), "templates_dir": str(Path.cwd() / "templates")}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"JARVIS_REPORT_COMPILER_CONFIG": str(config_path)}, clear=False):
                status = compiler_status({})
                templates = compiler_list_templates({})
                validation = compiler_validate({"content": content, "template": "research_briefing"})
                preview = compiler_preview({"content": content, "template": "research_briefing"})
                rendered = compiler_render({"content": content, "format": "md", "template": "research_briefing", "output_path": str(output_path)})
                rendered_exists = Path(rendered["output_path"]).exists()
                rendered_text = output_path.read_text(encoding="utf-8")

        self.assertIn("Report Compiler", status["summary"])
        self.assertGreaterEqual(templates["count"], 1)
        self.assertTrue(validation["valid"])
        self.assertIn("Jarvis Compiler Test", preview["preview"])
        self.assertTrue(rendered_exists)
        self.assertIn("| Name | Status |", rendered_text)
        self.assertIn("https://example.com", rendered_text)

    def test_document_agent_sessions_extract_transform_compare_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "doc-one.md"
            second = root / "doc-two.md"
            first.write_text("# Intro\nJarvis can open documents.\n\n# Details\nIt stores sessions and writes reports.", encoding="utf-8")
            second.write_text("# Intro\nJarvis can open document files.\n\n# Extra\nIt compares versions.", encoding="utf-8")
            document_config = root / "document.json"
            compiler_config = root / "compiler.json"
            output_path = root / "document-output.md"
            document_config.write_text(
                json.dumps(
                    {
                        "session_dir": str(root / "sessions"),
                        "output_dir": str(root / "documents"),
                        "cache_dir": str(root / "cache"),
                        "default_output_format": "md",
                    }
                ),
                encoding="utf-8",
            )
            compiler_config.write_text(
                json.dumps({"output_dir": str(root / "reports"), "templates_dir": str(Path.cwd() / "templates")}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "JARVIS_DOCUMENT_AGENT_CONFIG": str(document_config),
                    "JARVIS_REPORT_COMPILER_CONFIG": str(compiler_config),
                },
                clear=False,
            ):
                status = document_status({})
                opened = document_open({"path": str(first)})
                session_id = opened["session_id"]
                read = document_read({"session_id": session_id, "section_heading": "Intro"})
                extracted = document_extract({"session_id": session_id, "operation": "outline"})
                annotated = document_annotate({"session_id": session_id, "note": "Check intro tone.", "target": "Intro"})
                transformed = document_transform({"session_id": session_id, "operation": "summarize", "sentences": 2})
                compared = document_compare({"left_session_id": session_id, "right_path": str(second)})
                written = document_write({"session_id": session_id, "format": "md", "output_path": str(output_path), "title": "Document Export"})
                merged = document_merge({"session_ids": [session_id], "paths": [str(second)], "title": "Merged Docs"})
                closed = document_close({"session_id": merged["session_id"], "delete_session": True})
                output_exists = output_path.exists()

        self.assertIn("Document Agent", status["summary"])
        self.assertEqual(opened["structure"]["section_count"], 2)
        self.assertIn("Jarvis can open documents", read["content"])
        self.assertEqual(len(extracted["headings"]), 2)
        self.assertTrue(annotated["annotated"])
        self.assertIn("Jarvis can open documents", transformed["transform"]["result"])
        self.assertLess(compared["similarity_score"], 1.0)
        self.assertTrue(written["written"])
        self.assertTrue(output_exists)
        self.assertTrue(merged["merged"])
        self.assertTrue(closed["closed"])

    def test_research_run_can_render_through_shared_compiler(self) -> None:
        source_a = {
            "source_id": "a",
            "ok": True,
            "url": "https://reuters.com/technology/ai-agents",
            "title": "AI agents research",
            "published_date": "2026-05-10T00:00:00+00:00",
            "text": "AI agent systems now combine planning, tool use, source reading, and verification before writing reports.",
            "text_hash": "a",
        }
        source_b = {
            "source_id": "b",
            "ok": True,
            "url": "https://openai.com/research/agents",
            "title": "Agent systems",
            "published_date": "2026-05-10T00:00:00+00:00",
            "text": "AI agent systems now combine planning, tool use, source reading, and verification before writing reports.",
            "text_hash": "b",
        }
        search_results = [
            {"title": source_a["title"], "url": source_a["url"], "source_provider": "test"},
            {"title": source_b["title"], "url": source_b["url"], "source_provider": "test"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            compiler_config = Path(tmp) / "compiler.json"
            output_path = Path(tmp) / "ai-agents.md"
            compiler_config.write_text(
                json.dumps(
                    {
                        "output_dir": str(Path(tmp) / "reports"),
                        "templates_dir": str(Path.cwd() / "templates"),
                        "default_format": "md",
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"JARVIS_REPORT_COMPILER_CONFIG": str(compiler_config)}, clear=False):
                with patch("tools.research_agent.search_one_query", return_value=(search_results, [])):
                    with patch("tools.research_agent.fetch_source", side_effect=[source_a, source_b]):
                        result = research_run(
                            {
                                "topic": "AI agents",
                                "mode": "market_tech_trend",
                                "quality": "fast",
                                "max_sources": 2,
                                "render_format": "md",
                                "output_path": str(output_path),
                            }
                        )
            rendered_exists = output_path.exists()

        self.assertTrue(result["compiler_content"]["sections"])
        self.assertEqual(result["rendered_report"]["format"], "md")
        self.assertTrue(rendered_exists)
        self.assertIn("Research report saved to", result["safe_user_output"])


if __name__ == "__main__":
    unittest.main()
