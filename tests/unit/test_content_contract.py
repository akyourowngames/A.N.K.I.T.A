import unittest

from agents.content_contract import parse_content_payload, validate_content_payload, extract_body


class ContentContractTests(unittest.TestCase):
    def test_valid_payload_normal(self) -> None:
        txt = (
            "CONTENT_PAYLOAD_V1\n"
            "TASK_TYPE: poem\n"
            "TITLE: Monsoon Verse\n"
            "FORMAT: plain_text\n"
            "AUDIENCE: general\n"
            "TONE: lyrical\n"
            "WORD_TARGET: 120\n"
            "BODY_START\nRain writes softly on tin roofs.\nBODY_END\n"
            "NOTES_START\n\nNOTES_END\n"
            "CONTENT_PAYLOAD_V1_END"
        )
        payload = parse_content_payload(txt)
        ok, errors = validate_content_payload(payload)
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        self.assertIn("Rain writes softly", extract_body(payload))

    def test_valid_payload_deep_report(self) -> None:
        txt = (
            "CONTENT_PAYLOAD_V1\n"
            "TASK_TYPE: report\n"
            "TITLE: AI Policy Review\n"
            "FORMAT: markdown\n"
            "AUDIENCE: leadership\n"
            "TONE: formal\n"
            "WORD_TARGET: 6500\n"
            "BODY_START\n## Executive Summary\nDetailed content.\nBODY_END\n"
            "NOTES_START\nuse .md\nNOTES_END\n"
            "CONTENT_PAYLOAD_V1_END"
        )
        payload = parse_content_payload(txt)
        ok, _ = validate_content_payload(payload)
        self.assertTrue(ok)

    def test_valid_payload_accepts_richer_document_types(self) -> None:
        txt = (
            "CONTENT_PAYLOAD_V1\n"
            "TASK_TYPE: thank_you_letter\n"
            "TITLE: Thank You\n"
            "FORMAT: plain_text\n"
            "AUDIENCE: hiring manager\n"
            "TONE: warm and professional\n"
            "WORD_TARGET: 220\n"
            "BODY_START\nDear Sarah,\n\nThank you for your time.\n\nBest regards,\nAnkita\nBODY_END\n"
            "NOTES_START\n\nNOTES_END\n"
            "CONTENT_PAYLOAD_V1_END"
        )
        payload = parse_content_payload(txt)
        ok, errors = validate_content_payload(payload)
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_missing_markers(self) -> None:
        payload = parse_content_payload("TASK_TYPE: report\nTITLE: X")
        ok, errors = validate_content_payload(payload)
        self.assertFalse(ok)
        self.assertTrue(any("Missing CONTENT_PAYLOAD_V1" in e for e in errors))

    def test_empty_body(self) -> None:
        txt = (
            "CONTENT_PAYLOAD_V1\n"
            "TASK_TYPE: article\nTITLE: X\nFORMAT: markdown\nAUDIENCE: all\nTONE: neutral\nWORD_TARGET: 500\n"
            "BODY_START\n\nBODY_END\nNOTES_START\n\nNOTES_END\nCONTENT_PAYLOAD_V1_END"
        )
        ok, errors = validate_content_payload(parse_content_payload(txt))
        self.assertFalse(ok)
        self.assertTrue(any("BODY is empty" in e for e in errors))

    def test_non_integer_word_target(self) -> None:
        txt = (
            "CONTENT_PAYLOAD_V1\n"
            "TASK_TYPE: email\nTITLE: Follow Up\nFORMAT: plain_text\nAUDIENCE: client\nTONE: polite\nWORD_TARGET: many\n"
            "BODY_START\nThanks.\nBODY_END\nNOTES_START\n\nNOTES_END\nCONTENT_PAYLOAD_V1_END"
        )
        ok, errors = validate_content_payload(parse_content_payload(txt))
        self.assertFalse(ok)
        self.assertTrue(any("WORD_TARGET must be an integer" in e for e in errors))

    def test_extra_text_outside_payload(self) -> None:
        txt = (
            "Here is your report\n"
            "CONTENT_PAYLOAD_V1\n"
            "TASK_TYPE: report\nTITLE: X\nFORMAT: markdown\nAUDIENCE: all\nTONE: formal\nWORD_TARGET: 300\n"
            "BODY_START\nBody\nBODY_END\nNOTES_START\n\nNOTES_END\nCONTENT_PAYLOAD_V1_END\n"
            "Thanks!"
        )
        ok, errors = validate_content_payload(parse_content_payload(txt))
        self.assertFalse(ok)
        self.assertTrue(any("Extra text exists outside" in e for e in errors))


if __name__ == "__main__":
    unittest.main()

