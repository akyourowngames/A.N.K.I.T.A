"""Offline STT diagnostic: --file recording.wav, or capture from the microphone."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    from core import config  # Load shared .env defaults before command-line overrides.
    from core import speech
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, help="transcribe a local audio file without opening the mic")
    parser.add_argument("--seconds", type=float, default=6)
    parser.add_argument("--lang", help="auto, en, hi, or another Whisper language")
    parser.add_argument("--device", help="input device id or name")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--download-model", action="store_true", help="explicitly download configured model once")
    args = parser.parse_args()
    if args.lang:
        os.environ["ZUMBA_STT_LANG"] = args.lang
    if not 0 < args.seconds <= speech.MAX_SECONDS:
        parser.error("--seconds must be between 0 and 60")
    try:
        if args.download_model:
            from faster_whisper import WhisperModel
            WhisperModel(os.getenv("ZUMBA_STT_MODEL", "tiny"), device="cpu", compute_type="int8")
            print("Model cached. Subsequent transcription runs offline.")
            return 0
        if args.list_devices:
            import sounddevice as sd
            print(sd.query_devices())
            print("Default input/output:", sd.default.device)
            return 0
        print(json.dumps(speech.diagnostics(), indent=2), flush=True)
        if args.file:
            with args.file.open("rb") as audio:
                data = audio.read(speech.MAX_BYTES + 1)
        else:
            import sounddevice as sd
            import numpy as np
            print("Loading local model...", flush=True)
            speech.prepare()
            selected = args.device or os.getenv("ZUMBA_MIC_DEVICE")
            device = int(selected) if selected and selected.isdigit() else selected
            print(f"Speak now ({args.seconds:g} seconds)...", flush=True)
            data = sd.rec(int(args.seconds * speech.SAMPLE_RATE), samplerate=speech.SAMPLE_RATE,
                          channels=1, dtype="float32", device=device, blocking=True)[:, 0]
            print(f"Peak microphone level: {float(np.max(np.abs(data))):.4f}", flush=True)
        result = speech.transcribe(data, on_partial=lambda text: print("Partial:", text, flush=True))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["transcript"]:
            print("No speech detected. Check input device and microphone level.")
            return 1
        return 0
    except Exception as exc:
        print(f"STT failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
