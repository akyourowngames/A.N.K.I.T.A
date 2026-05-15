from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_nim import chat_once
from local_router import ROUTE_DIRECT_CHAT, ROUTE_TOOL_REQUIRED, route_chat_turn
from tests.test_latency_fast_lane import test_config
from tools.registry import ToolRegistry, define_tool, discover_tools


class GroundingContractTests(unittest.TestCase):
    def test_prompts_ban_false_live_verification_claims(self) -> None:
        system_prompt = Path("prompts/chat_system.txt").read_text(encoding="utf-8")
        result_prompt = Path("prompts/tool_results.txt").read_text(encoding="utf-8")

        self.assertIn("Never claim that you checked", system_prompt)
        self.assertIn("unless a current-turn tool result contains", system_prompt)
        self.assertIn("If the available result is empty", system_prompt)
        self.assertIn("Never say you checked", result_prompt)
        self.assertIn("If evidence_ok=false", result_prompt)

    def test_current_news_question_does_not_go_direct_chat(self) -> None:
        decision = route_chat_turn("whats new in indian politics", [], discover_tools())

        self.assertEqual(decision.mode, ROUTE_TOOL_REQUIRED)
        self.assertEqual(decision.selected_tool_names, ["web_search"])

    def test_normal_chat_still_goes_direct_chat(self) -> None:
        decision = route_chat_turn("hi bud", [], discover_tools())

        self.assertEqual(decision.mode, ROUTE_DIRECT_CHAT)
        self.assertEqual(decision.selected_tool_names, [])

    def test_web_search_results_are_rendered_without_final_model_invention(self) -> None:
        registry = ToolRegistry()
        registry.register(
            define_tool(
                name="web_search",
                description="Search the web for current, new, latest, right-now, news, public-office, time-sensitive, or external information.",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                handler=lambda params: {
                    "query": params["query"],
                    "fetched_at_utc": "2026-05-15T00:00:00+00:00",
                    "evidence_ok": True,
                    "count": 1,
                    "results": [{"title": "Current source title", "url": "https://example.test/source"}],
                },
                category="web",
                risk="read",
                parallel_safe=True,
            ).to_tool()
        )

        with patch("jarvis_nim.urllib.request.urlopen") as urlopen:
            reply = chat_once(test_config(), [{"role": "user", "content": "whats new in indian politics"}], registry)

        urlopen.assert_not_called()
        self.assertIn("Current source title", reply)
        self.assertIn("https://example.test/source", reply)
        self.assertIn("will not infer details", reply)


if __name__ == "__main__":
    unittest.main()
