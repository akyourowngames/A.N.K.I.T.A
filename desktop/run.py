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
from desktop.gui import run_gui
from desktop.state import DesktopBus


class _MutedSTT:
    def listen_once(self, timeout=30.0, abort=None):
        raise RuntimeError("text-only mode: microphone disabled")


class _MutedSpeaker:
    def speak(self, text, stop_event=None, summarize=True):
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Zumba desktop voice assistant.")
    parser.add_argument("--text-only", action="store_true",
                        help="disable microphone and speaker, type instead")
    parser.add_argument("--session", default="desktop",
                        help="zumba session id for desktop chats")
    args = parser.parse_args()

    bus = DesktopBus(
        assistant_name=os.getenv("ZUMBA_ASSISTANT_NAME", "Zumba"),
        username=os.getenv("ZUMBA_USERNAME", "Sir"),
    )
    controller = VoiceController(
        bus,
        session_id=args.session,
        stt=_MutedSTT() if args.text_only else None,
        speaker=_MutedSpeaker() if args.text_only else None,
    )
    controller.start()
    try:
        code = run_gui(bus, controller.handle_query)
    finally:
        controller.shutdown()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
