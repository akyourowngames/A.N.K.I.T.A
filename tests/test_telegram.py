import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import telegram_bot


class TelegramBridgeTests(unittest.TestCase):
    def test_chunk_text(self) -> None:
        text = "a" * 9000
        chunks = telegram_bot.chunk_text(text, chunk_size=3900)
        self.assertEqual(len(chunks), 3)
        self.assertEqual("".join(chunks), text)

    def test_offset_read_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            old_state_dir = telegram_bot.STATE_DIR
            old_offset_file = telegram_bot.OFFSET_FILE
            try:
                telegram_bot.STATE_DIR = base / ".ankita" / "telegram"
                telegram_bot.OFFSET_FILE = telegram_bot.STATE_DIR / "update-offset.json"
                self.assertEqual(telegram_bot.read_offset(), 0)
                telegram_bot.write_offset(42)
                self.assertEqual(telegram_bot.read_offset(), 42)
            finally:
                telegram_bot.STATE_DIR = old_state_dir
                telegram_bot.OFFSET_FILE = old_offset_file

    def test_allowed_chat_id_parse(self) -> None:
        ids = telegram_bot.parse_allowed_chat_ids("123, -100456, bad, , 999")
        self.assertIn(123, ids)
        self.assertIn(-100456, ids)
        self.assertIn(999, ids)
        self.assertEqual(len(ids), 3)

    def test_parse_text_message(self) -> None:
        parsed = telegram_bot.parse_incoming_message(
            {
                "message_id": 10,
                "chat": {"id": 123},
                "text": "hello",
            }
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.kind, "text")
        self.assertEqual(parsed.text, "hello")
        self.assertEqual(parsed.chat_id, 123)

    def test_parse_photo_message_picks_largest(self) -> None:
        parsed = telegram_bot.parse_incoming_message(
            {
                "message_id": 7,
                "chat": {"id": 321},
                "caption": "check this",
                "photo": [
                    {"file_id": "small", "file_size": 1500},
                    {"file_id": "big", "file_size": 9000},
                ],
            }
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.kind, "photo")
        self.assertEqual(parsed.file_id, "big")
        self.assertEqual(parsed.file_size, 9000)
        self.assertEqual(parsed.caption, "check this")

    def test_parse_document_and_voice(self) -> None:
        doc = telegram_bot.parse_incoming_message(
            {
                "message_id": 1,
                "chat": {"id": 55},
                "document": {
                    "file_id": "doc123",
                    "file_name": "x.pdf",
                    "mime_type": "application/pdf",
                    "file_size": 2048,
                },
            }
        )
        self.assertEqual(doc.kind, "document")
        self.assertEqual(doc.file_name, "x.pdf")

        voice = telegram_bot.parse_incoming_message(
            {
                "message_id": 2,
                "chat": {"id": 55},
                "voice": {
                    "file_id": "v1",
                    "mime_type": "audio/ogg",
                    "file_size": 4096,
                },
            }
        )
        self.assertEqual(voice.kind, "voice")
        self.assertEqual(voice.file_id, "v1")

    def test_choose_reaction(self) -> None:
        parsed = telegram_bot.ParsedTelegramInput(kind="text", text="hi")
        self.assertEqual(telegram_bot.choose_reaction(parsed, "received", ""), "👍")
        self.assertEqual(telegram_bot.choose_reaction(parsed, "start", ""), "⚡")
        self.assertEqual(telegram_bot.choose_reaction(parsed, "", "success"), "✅")
        self.assertEqual(telegram_bot.choose_reaction(parsed, "", "recoverable_failure"), "🤔")
        self.assertEqual(telegram_bot.choose_reaction(parsed, "", "hard_failure"), "⚠️")

    def test_send_reaction_best_effort_call_shape(self) -> None:
        with patch.object(telegram_bot, "tg_api") as mock_api:
            telegram_bot.send_reaction("tok", 10, 20, "👍")
            mock_api.assert_called_once()
            _, method, payload = mock_api.call_args[0]
            self.assertEqual(method, "setMessageReaction")
            self.assertEqual(payload["chat_id"], 10)
            self.assertEqual(payload["message_id"], 20)
            self.assertEqual(payload["reaction"][0]["emoji"], "👍")

    def test_download_file(self) -> None:
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size=65536):
                del chunk_size
                yield b"abc"
                yield b"def"

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "out.bin"
            with patch.object(telegram_bot.requests, "get", return_value=_Resp()):
                out = telegram_bot.download_file("tok", "a/b/c.bin", dest)
            self.assertTrue(out.exists())
            self.assertEqual(out.read_bytes(), b"abcdef")

    def test_send_document_uses_multipart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "r.txt"
            path.write_text("hello", encoding="utf-8")
            with patch.object(telegram_bot, "tg_api_form") as mock_form:
                telegram_bot.send_document("tok", 99, path, caption="c")
            mock_form.assert_called_once()
            args = mock_form.call_args[0]
            self.assertEqual(args[1], "sendDocument")

    def test_build_media_prompt(self) -> None:
        p = Path("C:/tmp/f.jpg")
        photo = telegram_bot.ParsedTelegramInput(kind="photo", text="", caption="cap")
        s = telegram_bot._build_media_prompt(photo, p)
        self.assertIn("Analyze this image", s)
        self.assertIn("cap", s)

        doc = telegram_bot.ParsedTelegramInput(kind="document", text="", file_name="a.pdf", mime_type="application/pdf")
        s2 = telegram_bot._build_media_prompt(doc, Path("C:/tmp/a.pdf"))
        self.assertIn("a.pdf", s2)

    def test_file_size_limit_logic(self) -> None:
        max_mb = 25
        max_bytes = max_mb * 1024 * 1024
        parsed = telegram_bot.ParsedTelegramInput(kind="document", text="", file_size=max_bytes + 1)
        self.assertTrue(parsed.file_size > max_bytes)

    def test_parse_send_file_intent(self) -> None:
        self.assertEqual(telegram_bot._parse_send_file_intent("/sendfile foo.txt"), "foo.txt")
        self.assertEqual(telegram_bot._parse_send_file_intent("ankita send that file on telegram"), "__LAST_ARTIFACT__")
        self.assertEqual(telegram_bot._parse_send_file_intent("send me this on telegram"), "__LAST_ARTIFACT__")
        self.assertEqual(telegram_bot._parse_send_file_intent("send random file from download folder on telegram"), "__DOWNLOADS_RANDOM__")
        self.assertEqual(telegram_bot._parse_send_file_intent("send me random image from my pc"), "__AGENT_PICK__")

    def test_extract_candidate_paths_finds_existing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "abc_report.txt"
            fp.write_text("ok", encoding="utf-8")
            text = f"Done. File saved at {fp}"
            out = telegram_bot._extract_candidate_paths(text)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0], fp)

    def test_choose_reaction_with_llm_fallback(self) -> None:
        parsed = telegram_bot.ParsedTelegramInput(kind="text", text="hi")
        with patch.object(telegram_bot, "call_chat_once", side_effect=RuntimeError("x")):
            emoji = telegram_bot.choose_reaction_with_llm(object(), parsed, "received", "")
        self.assertIn(emoji, {"👍", "👀"})

    def test_extract_mentioned_filenames_and_resolve(self) -> None:
        names = telegram_bot._extract_mentioned_filenames('Opened random image: "photo_123.jpg"')
        self.assertIn("photo_123.jpg", names)
        with tempfile.TemporaryDirectory() as td:
            old_root = telegram_bot.WORKSPACE_ROOT
            try:
                telegram_bot.WORKSPACE_ROOT = Path(td)
                fp = Path(td) / "photo_123.jpg"
                fp.write_bytes(b"x")
                resolved = telegram_bot._resolve_file_by_name("photo_123.jpg")
                self.assertEqual(resolved, fp.resolve())
            finally:
                telegram_bot.WORKSPACE_ROOT = old_root

    def test_extract_send_directives(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.txt"
            p.write_text("x", encoding="utf-8")
            note = f"Done.\nTELEGRAM_FILE: {p}\n"
            clean, paths = telegram_bot._extract_send_directives(note)
            self.assertEqual(clean, "Done.")
            self.assertEqual(paths, [p])

    def test_extract_send_directives_only_directive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.txt"
            p.write_text("ok", encoding="utf-8")
            note = f"TELEGRAM_FILE: {p}"
            clean, paths = telegram_bot._extract_send_directives(note)
            self.assertEqual(clean, "")
            self.assertEqual(paths, [p])


if __name__ == "__main__":
    unittest.main(verbosity=2)
