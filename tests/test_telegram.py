import tempfile
import unittest
from pathlib import Path
import sys

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
