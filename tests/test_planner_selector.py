from __future__ import annotations

import unittest

from jarvis_nim import tool_names_from_selector_content


class PlannerSelectorTests(unittest.TestCase):
    def test_selector_content_extracts_known_tool_names(self) -> None:
        names = tool_names_from_selector_content(
            '{"tool_names":["run_jarvis_qa","telegram_send_file","missing_tool"]}',
            {"run_jarvis_qa", "telegram_send_file"},
        )

        self.assertEqual(names, ["run_jarvis_qa", "telegram_send_file"])

    def test_selector_content_accepts_name_objects(self) -> None:
        names = tool_names_from_selector_content(
            '{"name":"run_jarvis_qa","parameters":{}}',
            {"run_jarvis_qa"},
        )

        self.assertEqual(names, ["run_jarvis_qa"])


if __name__ == "__main__":
    unittest.main()
