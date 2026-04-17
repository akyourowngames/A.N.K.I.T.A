import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agents.orchestration.completion import review_completion_attempt


class CompletionScreenshotVerificationTests(unittest.TestCase):
    def test_screenshot_verification_can_close_ambiguous_desktop_task(self) -> None:
        runtime = SimpleNamespace(
            provider="nvidia",
            model="meta/llama-3.1-8b-instruct",
            api_key="x",
            base_url="https://example.com",
            max_tokens=512,
        )
        results = [
            {
                "agent": "SystemAgent",
                "ok": False,
                "reply": "[FAILED] launch_app\nerror: transient provider issue",
                "artifacts": {"files": [], "urls": [], "handoffs": [], "opened_files": [], "launched_apps": []},
            }
        ]

        with patch(
            "agents.orchestration.completion.call_chat_once",
            return_value={"content": '{"use_screenshot_verification": true, "reason": "GUI task is ambiguous", "focus": "look for the requested app window"}'},
        ) as mock_decider:
            with patch(
                "agents.orchestration.completion.desktop_ops.capture_screen",
                return_value={"ok": True, "FILE_PATH": r"C:\tmp\verify.png", "base64": "abcd", "base64_mime": "image/png"},
            ) as mock_capture:
                with patch(
                    "agents.orchestration.completion.build_vision_runtime_from_env",
                    return_value=SimpleNamespace(provider="gemini", model="gemini-2.0-flash"),
                ):
                    with patch(
                        "agents.orchestration.completion.call_chat_with_image",
                        return_value='{"status":"complete","reason":"Calculator window is clearly visible.","visible_evidence":"The Calculator app is open on screen."}',
                    ) as mock_vision:
                        review = review_completion_attempt(
                            runtime,
                            "open calculator",
                            "[FAILED] launch_app\nerror: transient provider issue",
                            results,
                            1,
                            [],
                        )

        self.assertEqual(review["status"], "complete")
        self.assertEqual(review["verification_summary"], "screenshot_verified")
        self.assertEqual(review["verification"]["screenshot_verification"]["status"], "complete")
        mock_decider.assert_called_once()
        mock_capture.assert_called_once()
        mock_vision.assert_called_once()


if __name__ == "__main__":
    unittest.main()
