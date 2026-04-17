import unittest
import json
from unittest.mock import patch
from types import SimpleNamespace

from agents.orchestrator import _is_capability_routing_reason
from agents.supervisor import SupervisorAgent, _needs_followup_disambiguation, _resolve_followup_scope


class SupervisorFollowupTests(unittest.TestCase):
    def test_followup_disambiguation_only_triggers_for_capability_style_prompts(self) -> None:
        history = [{"role": "assistant", "content": "Done."}]
        self.assertTrue(_needs_followup_disambiguation("what else", history))
        self.assertFalse(_needs_followup_disambiguation("what are you fixing huh", history))

    def test_resolve_followup_scope_ignores_non_capability_clarification(self) -> None:
        history = [
            {"role": "user", "content": "nothing i am mad man"},
            {"role": "assistant", "content": "Yeah, that's annoying. Let me fix it."},
        ]
        with patch("agents.supervisor.call_chat_once") as mock_call:
            mode = _resolve_followup_scope(
                runtime=object(),
                user_text="what are you fixing huh",
                history=history,
                current_agents=["GeneralAgent"],
            )
        self.assertIsNone(mode)
        mock_call.assert_not_called()

    def test_capability_reason_requires_explicit_capability_language(self) -> None:
        self.assertFalse(_is_capability_routing_reason("follow-up question about which tools were used"))
        self.assertTrue(_is_capability_routing_reason("global capability question about available tools"))

    def test_local_discovery_puts_terminal_agent_first(self) -> None:
        payload = {
            "agents": ["FileAgent", "SystemAgent"],
            "parallel": True,
            "reasoning": "open the local file",
            "confidence": 0.9,
        }
        with patch("agents.supervisor.call_chat_once", return_value={"content": json.dumps(payload)}):
            runtime = SimpleNamespace(provider="nvidia", model="meta/llama-3.1-8b-instruct", api_key="x", base_url="https://example.com", max_tokens=512)
            route = SupervisorAgent(runtime=runtime).route("find the gateway file and open it", history=[])
        self.assertEqual(route["agents"][0], "TerminalAgent")
        self.assertEqual(route["agents"][1:], ["FileAgent", "SystemAgent"])
        self.assertFalse(route["parallel"])

    def test_code_writer_agent_survives_validation(self) -> None:
        payload = {
            "agents": ["CodeWriterAgent"],
            "parallel": False,
            "reasoning": "local page generation is a code artifact workflow",
            "confidence": 0.95,
        }
        with patch("agents.supervisor.call_chat_once", return_value={"content": json.dumps(payload)}):
            runtime = SimpleNamespace(provider="nvidia", model="meta/llama-3.1-8b-instruct", api_key="x", base_url="https://example.com", max_tokens=512)
            route = SupervisorAgent(runtime=runtime).route("build me a landing page for a tea shop and open it in browser", history=[])
        self.assertEqual(route["agents"], ["CodeWriterAgent"])


if __name__ == "__main__":
    unittest.main()
