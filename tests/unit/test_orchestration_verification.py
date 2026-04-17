import unittest

from agents.orchestration.completion import (
    _has_strong_completion_signal,
    reply_looks_like_failure,
    verification_has_any_objective_success,
)
from agents.orchestration.core import (
    _fallback_verified_completion_reply,
    _history_reply_with_artifacts,
    _reply_conflicts_with_verification,
)
from agents.orchestration.shared import extract_clean_history


class OrchestrationVerificationTests(unittest.TestCase):
    def test_reply_failure_detector_flags_false_negative_text(self) -> None:
        self.assertTrue(reply_looks_like_failure("It failed to open the image."))
        self.assertFalse(reply_looks_like_failure("Done - opened screenshot-1.png."))

    def test_verification_success_detector_uses_objective_artifacts(self) -> None:
        verification = {
            "existing_files": [],
            "opened_files": [r"C:\Users\anime\Desktop\shot.png"],
            "launched_apps": [],
        }
        self.assertTrue(verification_has_any_objective_success(verification))

    def test_verified_completion_fallback_prefers_opened_and_launched_artifacts(self) -> None:
        verification = {
            "existing_files": [r"C:\Users\anime\Desktop\report.txt"],
            "opened_files": [r"C:\Users\anime\Desktop\report.txt"],
            "launched_apps": ["notepad"],
        }
        reply = _fallback_verified_completion_reply(verification)
        self.assertIn("opened report.txt", reply)
        self.assertIn("launched notepad", reply)

    def test_strong_completion_signal_does_not_trust_open_only_without_failure_context(self) -> None:
        results = [
            {
                "agent": "SystemAgent",
                "ok": True,
                "reply": "Done - opened the file.",
                "artifacts": {"files": [], "urls": [], "handoffs": [], "opened_files": [r"C:\tmp\wrong.txt"], "launched_apps": []},
            }
        ]
        verification = {
            "existing_files": [],
            "missing_files": [],
            "opened_files": [r"C:\tmp\wrong.txt"],
            "launched_apps": [],
            "failures": [],
        }
        self.assertFalse(_has_strong_completion_signal(results, verification))

    def test_strong_completion_signal_keeps_redundant_downstream_failure_shortcut(self) -> None:
        results = [
            {
                "agent": "ContentAgent",
                "ok": True,
                "reply": "Saved report.\nFILE_PATH: C:\\tmp\\report.md",
                "artifacts": {"files": [r"C:\tmp\report.md"], "urls": [], "handoffs": [], "opened_files": [], "launched_apps": []},
            },
            {
                "agent": "SystemAgent",
                "ok": False,
                "reply": "[FAILED] open_path\nerror: duplicate open suppressed",
                "artifacts": {"files": [r"C:\tmp\report.md"], "urls": [], "handoffs": [], "opened_files": [r"C:\tmp\report.md"], "launched_apps": []},
            },
        ]
        verification = {
            "existing_files": [r"C:\tmp\report.md"],
            "missing_files": [],
            "opened_files": [r"C:\tmp\report.md"],
            "launched_apps": [],
            "failures": [{"agent": "SystemAgent", "reply_preview": "duplicate open suppressed"}],
        }
        self.assertTrue(_has_strong_completion_signal(results, verification))

    def test_history_reply_with_artifacts_preserves_receipts_for_followups(self) -> None:
        verification = {
            "existing_files": [r"C:\Users\anime\Desktop\tea_shop.html"],
            "opened_files": [r"C:\Users\anime\Desktop\tea_shop.html"],
            "launched_apps": ["chrome"],
        }
        history_reply = _history_reply_with_artifacts("Done - opened the landing page.", verification)
        self.assertIn("FILE_PATH: C:\\Users\\anime\\Desktop\\tea_shop.html", history_reply)
        self.assertIn("OPENED_FILE: C:\\Users\\anime\\Desktop\\tea_shop.html", history_reply)
        self.assertIn("LAUNCHED_APP: chrome", history_reply)

    def test_extract_clean_history_strips_receipt_lines_from_routing_context(self) -> None:
        messages = [
            {"role": "assistant", "content": "Done - opened it.\nFILE_PATH: C:\\Users\\anime\\Desktop\\tea_shop.html\nLAUNCHED_APP: chrome"},
            {"role": "user", "content": "take a screenshot and open it"},
        ]
        history = extract_clean_history(messages, max_turns=4)
        self.assertEqual(history[0]["content"], "Done - opened it.")
        self.assertEqual(history[1]["content"], "take a screenshot and open it")

    def test_reply_conflict_detector_flags_wrong_file_extension(self) -> None:
        verification = {
            "existing_files": [r"C:\Users\anime\Desktop\coffee_shop_landing_page.html"],
            "opened_files": [r"C:\Users\anime\Desktop\coffee_shop_landing_page.html"],
            "launched_apps": ["chrome"],
        }
        self.assertTrue(
            _reply_conflicts_with_verification(
                "Done - built the landing page, saved it as coffee_shop_landing_page.md, and opened it in a web browser.",
                verification,
            )
        )
        self.assertFalse(
            _reply_conflicts_with_verification(
                "Done - opened coffee_shop_landing_page.html and launched chrome.",
                verification,
            )
        )

if __name__ == "__main__":
    unittest.main()
