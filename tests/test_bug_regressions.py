from __future__ import annotations

import contextlib
import gc
import io
import tempfile
import unittest
import weakref
from pathlib import Path

import tools.browser_network as browser_network
from extension_system import load_extension_catalog


class BrowserNetworkRegressionTests(unittest.TestCase):
    def test_network_listener_attachment_uses_live_page_objects(self) -> None:
        class FakePage:
            def __init__(self) -> None:
                self.events: list[str] = []

            def on(self, event: str, _handler: object) -> None:
                self.events.append(event)

        browser_network._ATTACHED_PAGES.clear()
        first = FakePage()
        browser_network.attach_network_listeners(first, "session", {})
        first_ref = weakref.ref(first)

        self.assertEqual(first.events, ["request", "requestfinished", "requestfailed", "response"])
        self.assertIn(first, browser_network._ATTACHED_PAGES)

        del first
        gc.collect()

        second = FakePage()
        browser_network.attach_network_listeners(second, "session", {})

        self.assertIsNone(first_ref())
        self.assertEqual(second.events, ["request", "requestfinished", "requestfailed", "response"])
        self.assertIn(second, browser_network._ATTACHED_PAGES)


class ExtensionCatalogRegressionTests(unittest.TestCase):
    def test_invalid_extension_manifest_is_skipped_without_crashing_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = root / "valid"
            invalid = root / "invalid"
            valid.mkdir()
            invalid.mkdir()
            (valid / "extension.json").write_text(
                '{"id":"valid","name":"Valid Extension","tools":[],"prompt_files":[],"skill_dirs":[]}',
                encoding="utf-8",
            )
            (invalid / "extension.json").write_text('{"id":', encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                catalog = load_extension_catalog(root)

        self.assertEqual([extension.id for extension in catalog.extensions], ["valid"])
        self.assertEqual(len(catalog.errors), 1)
        self.assertIn("invalid", catalog.errors[0])
        self.assertIn("Skipping invalid extension", stderr.getvalue())
        self.assertTrue(any("skipped extension" in line for line in catalog.status_lines()))


if __name__ == "__main__":
    unittest.main()
