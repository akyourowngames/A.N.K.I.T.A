"""Entry point for the Zumba desktop voice assistant.

    python desktop/run.py
    python desktop/run.py --text-only   # GUI without mic/speaker (type only)

The Qt GUI must live on the main thread (like the Jarvis reference), so the
voice controller runs on a background thread and both talk via DesktopBus.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desktop.brain import VoiceController
from desktop.state import DesktopBus


class _MutedSTT:
    def listen_once(self, timeout=30.0, abort=None, **kwargs):
        raise RuntimeError("text-only mode: microphone disabled")

    def close(self):
        pass


class _MutedSpeaker:
    def speak(self, text, stop_event=None, summarize=True, **kwargs):
        return True


def main() -> int:
    from core import config  # Load the same .env configuration as CLI/server before overrides.
    parser = argparse.ArgumentParser(description="Zumba desktop voice assistant.")
    parser.add_argument("--text-only", action="store_true",
                        help="disable microphone and speaker, type instead")
    parser.add_argument("--session", default="desktop",
                        help="zumba session id for desktop chats")
    parser.add_argument("--lang", help="STT language (auto, en, hi); overrides ZUMBA_STT_LANG")
    parser.add_argument("--hands-free", action="store_true", help="enable the microphone on startup")
    parser.add_argument("--wake-word", nargs="?", const="Hey Ankita", default=None,
                        help="only answer speech addressing this phrase (LLM intent gate)")
    parser.add_argument("--mic-device", help="sounddevice input id or name")
    parser.add_argument("--barge-in", action="store_true", default=None,
                        help="interrupt speech on microphone activity; use headphones to avoid echo")
    args = parser.parse_args()
    if args.lang:
        os.environ["ZUMBA_STT_LANG"] = args.lang
    if args.mic_device:
        os.environ["ZUMBA_MIC_DEVICE"] = args.mic_device
    from desktop.gui import run_gui

    bus = DesktopBus(
        assistant_name=os.getenv("ZUMBA_ASSISTANT_NAME", "Zumba"),
        username=os.getenv("ZUMBA_USERNAME", "Sir"),
    )
    controller = VoiceController(
        bus,
        session_id=args.session,
        stt=_MutedSTT() if args.text_only else None,
        speaker=_MutedSpeaker() if args.text_only else None,
        wake_word=args.wake_word,
        barge_in=args.barge_in,
    )
    bus.set_mic(args.hands_free and not args.text_only)
    controller.start()
    try:
        code = run_gui(bus, controller.handle_query)
    finally:
        controller.shutdown()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
