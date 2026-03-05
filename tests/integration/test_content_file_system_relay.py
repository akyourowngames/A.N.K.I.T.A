import unittest

from agents.orchestrator import _build_prior_context_block


VALID_PAYLOAD = (
    "CONTENT_PAYLOAD_V1\n"
    "TASK_TYPE: report\n"
    "TITLE: AI Regulation in India\n"
    "FORMAT: markdown\n"
    "AUDIENCE: policy team\n"
    "TONE: formal\n"
    "WORD_TARGET: 1200\n"
    "BODY_START\n## Executive Summary\nPolicy overview.\nBODY_END\n"
    "NOTES_START\nprefer concise bullets\nNOTES_END\n"
    "CONTENT_PAYLOAD_V1_END"
)


class ContentFileRelayIntegrationTests(unittest.TestCase):
    def test_content_payload_handoff_contains_schema_and_legacy_content(self) -> None:
        ctx = _build_prior_context_block("ContentAgent", VALID_PAYLOAD, {"files": [], "urls": [], "handoffs": []})
        self.assertIn("CONTENT_SCHEMA: CONTENT_PAYLOAD_V1", ctx)
        self.assertIn("TASK_TYPE: report", ctx)
        self.assertIn("TITLE: AI Regulation in India", ctx)
        self.assertIn("FILENAME_HINT:", ctx)
        self.assertIn("CONTENT:\n## Executive Summary\nPolicy overview.\n:END_CONTENT", ctx)

    def test_legacy_fallback_when_payload_invalid(self) -> None:
        reply = "write this as plain text with no envelope"
        ctx = _build_prior_context_block("ContentAgent", reply, {"files": [], "urls": [], "handoffs": []})
        self.assertIn("CONTENT_SCHEMA_ERRORS:", ctx)
        self.assertIn("CONTENT:\nwrite this as plain text with no envelope\n:END_CONTENT", ctx)

    def test_skip_content_embed_when_file_artifact_exists(self) -> None:
        reply = VALID_PAYLOAD
        ctx = _build_prior_context_block(
            "ContentAgent",
            reply,
            {"files": ["C:\\Users\\anime\\Desktop\\report.md"], "urls": [], "handoffs": []},
        )
        self.assertIn("FILE: C:\\Users\\anime\\Desktop\\report.md", ctx)
        self.assertNotIn("CONTENT_SCHEMA: CONTENT_PAYLOAD_V1", ctx)
        self.assertNotIn("CONTENT:\n", ctx)


if __name__ == "__main__":
    unittest.main()

