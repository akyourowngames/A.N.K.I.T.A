import unittest
from unittest.mock import patch

from agents.orchestrator import _validate_or_repair_content_payload


VALID_PAYLOAD = (
    "CONTENT_PAYLOAD_V1\n"
    "TASK_TYPE: report\n"
    "TITLE: Market Snapshot\n"
    "FORMAT: markdown\n"
    "AUDIENCE: leadership\n"
    "TONE: formal\n"
    "WORD_TARGET: 700\n"
    "BODY_START\n## Summary\nAll good.\nBODY_END\n"
    "NOTES_START\n\nNOTES_END\n"
    "CONTENT_PAYLOAD_V1_END"
)


class OrchestratorContentPayloadEnforcementTests(unittest.TestCase):
    def test_first_pass_valid_no_retry(self) -> None:
        with patch("agents.orchestrator.call_chat_once") as mock_call:
            out = _validate_or_repair_content_payload(
                specialist_runtime=object(),
                messages=[],
                reply=VALID_PAYLOAD,
                max_tokens=512,
            )
            self.assertTrue(out["content_payload_valid"])
            self.assertFalse(out["content_payload_repaired"])
            mock_call.assert_not_called()

    def test_invalid_first_pass_repaired_on_retry(self) -> None:
        bad = "Here is your report"
        with patch("agents.orchestrator.call_chat_once", return_value={"content": VALID_PAYLOAD}) as mock_call:
            out = _validate_or_repair_content_payload(
                specialist_runtime=object(),
                messages=[],
                reply=bad,
                max_tokens=512,
            )
            self.assertTrue(out["content_payload_valid"])
            self.assertTrue(out["content_payload_repaired"])
            self.assertEqual(out["reply"], VALID_PAYLOAD)
            mock_call.assert_called_once()

    def test_invalid_after_retry_falls_back_legacy(self) -> None:
        bad = "plain freeform response"
        with patch("agents.orchestrator.call_chat_once", return_value={"content": "still invalid"}) as mock_call:
            out = _validate_or_repair_content_payload(
                specialist_runtime=object(),
                messages=[],
                reply=bad,
                max_tokens=512,
            )
            self.assertFalse(out["content_payload_valid"])
            self.assertFalse(out["content_payload_repaired"])
            # Legacy fallback keeps original reply
            self.assertEqual(out["reply"], bad)
            mock_call.assert_called_once()


if __name__ == "__main__":
    unittest.main()

