import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voice_web


class VoiceWebTests(unittest.TestCase):
    def test_extract_audio_b64_from_audios(self) -> None:
        out = voice_web._extract_audio_b64({"audios": ["abc123"]})
        self.assertEqual(out, "abc123")

    def test_extract_audio_b64_from_audio(self) -> None:
        out = voice_web._extract_audio_b64({"audio": "xyz789"})
        self.assertEqual(out, "xyz789")

    def test_extract_audio_b64_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            voice_web._extract_audio_b64({"ok": True})


if __name__ == "__main__":
    unittest.main(verbosity=2)

